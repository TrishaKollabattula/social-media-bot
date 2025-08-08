import json
import logging
import os
import jwt
from pathlib import Path
from dotenv import load_dotenv
import requests
import importlib
import boto3
import time

from content_handler import ContentGenerator
from user_handler import UserHandler
from social_media.linkedin_post import post_content_to_linkedin  # Updated import
from social_media.instagram_post import post_carousel_to_instagram
from social_media.twitter_post import post_content_to_twitter
from social_media.facebook_post import post_images_to_facebook  # ✅ Updated import for Facebook posting

# === Load env ===
load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET", "my-secure-secret-key-12345")
LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN")
LINKEDIN_USER_URN = os.getenv("LINKEDIN_USER_URN")
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
LINKEDIN_ORG_URN = os.getenv("LINKEDIN_ORG_URN", "urn:li:organization:99331065")

# Initialize s3 client
s3 = boto3.client("s3", region_name=AWS_REGION)

# === Load EC2 client for stopping the instance ===
ec2 = boto3.client("ec2", region_name=AWS_REGION)

def load_class(module: str, class_name: str):
    module_ref = importlib.import_module(module)
    return getattr(module_ref, class_name)

def call_method(class_obj, method_name, context: dict):
    method = getattr(class_obj, method_name)
    return method(context)

def verify_bearer_token(token: str):
    try:
        decoded_token = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return decoded_token
    except jwt.ExpiredSignatureError:
        raise Exception("Token has expired")
    except jwt.InvalidTokenError:
        raise Exception("Invalid token")

def download_image(image_url, retries=3):
    """Download image with retry mechanism."""
    for attempt in range(retries):
        try:
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()  # Check for successful response
            if "image" not in response.headers["Content-Type"]:
                logging.error(f"URL does not point to an image: {image_url}")
                return None
            return response.content
        except requests.exceptions.RequestException as e:
            logging.error(f"Error downloading image (attempt {attempt + 1}): {e}")
            time.sleep(2)  # Retry after a short delay
    return None  # Return None after retries fail

def upload_image_to_s3(image_data, image_name):
    """Upload image to S3."""
    try:
        s3.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=f"images/{image_name}",
            Body=image_data,
            ContentType="image/png"  # Assuming PNG image
        )
        logging.info(f"✅ Uploaded image to S3: {image_name}")
        image_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/images/{image_name}"
        return image_url
    except Exception as e:
        logging.error(f"❌ Failed to upload image to S3: {str(e)}")
        return None

def lambda_handler(event, context):
    logging.basicConfig(level=logging.DEBUG)
    try:
        if event.get("httpMethod") == "OPTIONS":
            return {
                "statusCode": 200,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization",
                },
                "body": ""
            }

        path = event.get("path", "").strip("/")
        path_parts = [part.strip() for part in path.split("/") if part.strip()]

        # Skip API Gateway stage name (e.g., 'prod')
        if path_parts and path_parts[0] == "prod":
            path_parts = path_parts[1:]

        logging.debug(f"Path components: {path_parts}")

        module_key = path_parts[0] if len(path_parts) > 0 else None
        api_key = path_parts[1] if len(path_parts) > 1 else None

        if not module_key:
            return {
                "statusCode": 200,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "text/plain",
                },
                "body": "✅ Backend is up and running!"
            }

        claims = None
        if not (module_key == "user" and api_key in ["login", "register"]):
            headers = event.get("headers", {})
            auth_header = headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                raise Exception("Authorization header missing or invalid")
            token = auth_header.split(" ")[1]
            claims = verify_bearer_token(token)

        api_mapping_file = Path(__file__).absolute().parent / "api-mapping.json"
        with open(api_mapping_file, "r", encoding="utf-8") as f:
            api_mapping = json.load(f)

        if module_key not in api_mapping:
            raise Exception(f"Module '{module_key}' not found in API mapping")

        module_config = api_mapping[module_key]
        if api_key not in module_config:
            raise Exception(f"API '{api_key}' not found in module '{module_key}'")

        apis = module_config[api_key]
        http_method = event.get("httpMethod", "").upper()
        selected_api = None

        for api in apis:
            if api["request_method"].upper() == http_method and api["path"] == "/".join(path_parts[2:]):
                selected_api = api
                break

        if not selected_api:
            raise Exception(f"No matching API found for path: {path} and method: {http_method}")

        package_name = selected_api["package"]
        class_name = selected_api["class"]
        method_name = selected_api["method"]

        handler_class = load_class(package_name, class_name)
        handler_instance = handler_class()
        context = {"request": event, "claims": claims} if claims else {"request": event}
        response = call_method(handler_instance, method_name, context)

        # Enhanced social media posting with proper caption extraction
        if module_key == "content" and api_key == "generate":
            body = json.loads(event.get("body", "{}"))
            platforms = body.get("platforms", {})
            prompt = body.get("prompt", "Generated Content")
            content_type = body.get("contentType", "Informative").capitalize()
            theme = body.get("theme", "default theme")
            
            try:
                num_images = int(body.get("numImages", 1))
            except ValueError:
                logging.error(f"Invalid numImages value: {body.get('numImages')}")
                num_images = 1

            # Load content details
            try:
                with open("content_details.json", "r", encoding="utf-8") as f:
                    content_details = json.load(f)
                logging.info("✅ Successfully loaded content_details.json")
            except Exception as e:
                logging.error(f"Failed to read content_details.json: {str(e)}")
                content_details = {}

            # Proper caption extraction for YOUR actual content_details.json structure
            captions_dict = content_details.get("captions", {})
            summary_paragraphs = content_details.get("summary", [])
            
            # Structure has "post_caption" as a direct key
            single_caption = captions_dict.get("post_caption", prompt)
            logging.info(f"✅ Found post_caption: {len(single_caption)} characters")
            
            # For LinkedIn, prefer summary, fallback to single caption
            linkedin_caption = "\n".join(summary_paragraphs) if summary_paragraphs else single_caption
            
            # For Instagram and Twitter, use the single caption
            instagram_caption = single_caption
            twitter_caption = single_caption
            
            # ✅ For Facebook, use the single caption
            facebook_caption = single_caption
            
            logging.info(f"📝 Captions prepared - LinkedIn: {len(linkedin_caption)} chars, Instagram: {len(instagram_caption)} chars, Twitter: {len(twitter_caption)} chars, Facebook: {len(facebook_caption)} chars")

            linkedin_access_token = body.get("linkedin_access_token") or LINKEDIN_ACCESS_TOKEN
            linkedin_org_urn = body.get("linkedin_org_urn") or LINKEDIN_ORG_URN

            if isinstance(response, tuple):
                response_data = response[0] if len(response) > 0 else {}
            else:
                response_data = response

            # Extract URLs from response
            pdf_url = response_data.get("pdf_url")
            image_urls = response_data.get("image_urls", []) if isinstance(response_data.get("image_urls"), list) else []

            # Filter image_urls to include only /images/ URLs with valid extensions
            image_urls = [url for url in image_urls if url.startswith(f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/images/") and url.lower().endswith(('.jpg', '.jpeg', '.png'))]
            logging.info(f"Filtered image_urls for social media: {image_urls}")

            linkedin_results = []

            # LinkedIn posting
            if platforms.get("linkedin"):
                logging.info("📸 Starting LinkedIn posting...")
                logging.info(f"🔐 LinkedIn credentials check - Token: {linkedin_access_token[:20] if linkedin_access_token else 'None'}...")
                logging.info(f"🏢 LinkedIn URN: {linkedin_org_urn}")
                
                # Direct call without dependency on response URLs
                try:
                    logging.info("🎯 About to call post_content_to_linkedin...")
                    success, message = post_content_to_linkedin(
                        caption=linkedin_caption,
                        access_token=linkedin_access_token,
                        user_urn=linkedin_org_urn
                    )
                    linkedin_results.append({"success": success, "message": message, "type": "auto"})
                    logging.info(f"✅ LinkedIn posting completed: {success} - {message}")
                    
                    if success:
                        logging.info("🎉 LinkedIn posting was SUCCESSFUL!")
                    else:
                        logging.error(f"❌ LinkedIn posting FAILED: {message}")
                except Exception as e:
                    error_msg = f"❌ Exception in LinkedIn posting: {str(e)}"
                    logging.error(error_msg, exc_info=True)
                    linkedin_results.append({"success": False, "message": error_msg, "type": "auto"})

                # Always add results to response
                response_data["linkedin_results"] = linkedin_results
                logging.info(f"📊 LinkedIn results added to response: {linkedin_results}")

            # Instagram posting
            if platforms.get("instagram"):
                logging.info(f"📷 Starting Instagram posting for {num_images} images...")
                try:
                    # Fetch images from S3 if image_urls is empty or insufficient
                    if not image_urls or len(image_urls) < num_images:
                        if S3_BUCKET_NAME and AWS_REGION:
                            response_s3 = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix="images/")
                            image_keys = [obj['Key'] for obj in response_s3.get('Contents', []) if obj['Key'] != "images/"]
                            if image_keys:
                                sorted_keys = sorted(response_s3['Contents'], key=lambda x: x['LastModified'], reverse=True)
                                selected_keys = [obj['Key'] for obj in sorted_keys if obj['Key'] != "images/"][:num_images]
                                image_urls = [f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{key}" for key in selected_keys]
                                logging.info(f"Fetched image_urls from S3: {image_urls}")
                            else:
                                logging.error("No images found in S3 for Instagram post")
                                response_data["instagram_result"] = {"status": "error", "message": "No images found in S3"}
                        else:
                            logging.error("S3_BUCKET_NAME or AWS_REGION not set")
                            response_data["instagram_result"] = {"status": "error", "message": "S3_BUCKET_NAME or AWS_REGION not set"}
                    
                    if image_urls:  # Only proceed if we have images
                        ig_result = post_carousel_to_instagram(
                            image_urls=image_urls,
                            caption=instagram_caption,
                            num_images=num_images
                        )
                        response_data["instagram_result"] = ig_result
                        logging.info(f"✅ Instagram posting result: {ig_result}")
                    
                except Exception as e:
                    logging.error(f"Failed to post to Instagram: {str(e)}")
                    response_data["instagram_result"] = {"status": "error", "message": f"Failed to post to Instagram: {str(e)}"}

            # Twitter posting (x platform)
            if platforms.get("twitter") or platforms.get("x"):
                logging.info(f"🐦 Starting Twitter posting...")
                try:
                    if image_urls:
                        twitter_result = post_content_to_twitter(
                            image_urls=image_urls[:1],  # Only first image for Twitter
                            caption=twitter_caption,
                            num_images=1
                        )
                        response_data["twitter_result"] = twitter_result
                        logging.info(f"✅ [TWITTER POST RESULT] {twitter_result}")
                    else:
                        logging.error("No images available for Twitter posting")
                        response_data["twitter_result"] = {"status": "error", "message": "No images available for Twitter posting"}
                except Exception as e:
                    logging.error(f"Failed to post to Twitter: {str(e)}")
                    response_data["twitter_result"] = {"status": "error", "message": f"Failed to post to Twitter: {str(e)}"}

            # ✅ Facebook posting (NEW)
            if platforms.get("facebook"):
                logging.info(f"📘 Starting Facebook posting for {num_images} images...")
                try:
                    # Fetch images from S3 if image_urls is empty or insufficient
                    if not image_urls or len(image_urls) < num_images:
                        if S3_BUCKET_NAME and AWS_REGION:
                            response_s3 = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix="images/")
                            image_keys = [obj['Key'] for obj in response_s3.get('Contents', []) if obj['Key'] != "images/"]
                            if image_keys:
                                sorted_keys = sorted(response_s3['Contents'], key=lambda x: x['LastModified'], reverse=True)
                                selected_keys = [obj['Key'] for obj in sorted_keys if obj['Key'] != "images/"][:num_images]
                                image_urls = [f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{key}" for key in selected_keys]
                                logging.info(f"Fetched image_urls from S3 for Facebook: {image_urls}")
                            else:
                                logging.error("No images found in S3 for Facebook post")
                                response_data["facebook_result"] = {"status": "error", "message": "No images found in S3"}
                        else:
                            logging.error("S3_BUCKET_NAME or AWS_REGION not set")
                            response_data["facebook_result"] = {"status": "error", "message": "S3_BUCKET_NAME or AWS_REGION not set"}
                    
                    if image_urls:  # Only proceed if we have images
                        facebook_result = post_images_to_facebook(
                            image_urls=image_urls,
                            caption=facebook_caption,
                            num_images=num_images
                        )
                        response_data["facebook_result"] = facebook_result
                        logging.info(f"✅ Facebook posting result: {facebook_result}")
                    
                except Exception as e:
                    logging.error(f"Failed to post to Facebook: {str(e)}")
                    response_data["facebook_result"] = {"status": "error", "message": f"Failed to post to Facebook: {str(e)}"}

            # === Stop EC2 instance AFTER all social media posting is complete ===
            try:
                instance_id = os.getenv("EC2_INSTANCE_ID")
                if instance_id:
                    ec2.stop_instances(InstanceIds=[instance_id])
                    logging.info(f"🛑 EC2 instance {instance_id} stopped successfully after all social media posting.")
                else:
                    logging.warning("⚠️ EC2_INSTANCE_ID not set, skipping instance stop.")
            except Exception as e:
                logging.error(f"❌ Failed to stop EC2 instance: {str(e)}")

        # === Handle successful response ===
        if isinstance(response, tuple):
            response, status_code = response
        else:
            status_code = 200

        return {
            "statusCode": status_code,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "*",
            },
            "body": json.dumps(response),
        }

    except Exception as e:
        logging.error("Error processing request", exc_info=True)
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*",
            },
            "body": json.dumps({"error": str(e)}),
        }