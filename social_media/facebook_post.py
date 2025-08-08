import os
import boto3
import requests
import time
import json
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Environment variables
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN")

IMAGES_FOLDER = "images/"

# Validate environment variables
if not all([AWS_REGION, S3_BUCKET_NAME, FACEBOOK_PAGE_ID, FACEBOOK_ACCESS_TOKEN]):
    logger.error("Missing required Facebook environment variables")
    # Don't raise error here, just log it so the module can still be imported

s3 = boto3.client("s3", region_name=AWS_REGION) if AWS_REGION else None

# Retry decorator for API calls
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def post_with_retry(url, data=None, files=None):
    """Make API calls with retry mechanism"""
    if files:
        resp = requests.post(url, data=data, files=files, timeout=30)
    else:
        resp = requests.post(url, data=data, timeout=30)
    
    logger.info(f"Facebook API Response: {resp.status_code}")
    resp.raise_for_status()
    return resp

def load_captions_from_content_details():
    """Load captions from content_details.json file"""
    try:
        with open("content_details.json", "r") as f:
            content_details = json.load(f)
        
        captions_dict = content_details.get("captions", {})
        all_captions = []
        
        # Extract all captions from the captions dictionary
        for subtopic, caption_list in captions_dict.items():
            if isinstance(caption_list, list) and caption_list:
                # Take the first caption from each subtopic
                all_captions.append(caption_list[0])
            elif isinstance(caption_list, str):
                all_captions.append(caption_list)
        
        logger.info(f"Loaded {len(all_captions)} captions from content_details.json")
        return all_captions
        
    except FileNotFoundError:
        logger.warning("content_details.json not found, will use provided caption")
        return []
    except json.JSONDecodeError:
        logger.error("Error decoding content_details.json")
        return []
    except Exception as e:
        logger.error(f"Error loading captions: {str(e)}")
        return []

def get_summary_as_fallback_caption():
    """Get summary from content_details.json as fallback caption"""
    try:
        with open("content_details.json", "r") as f:
            content_details = json.load(f)
        
        summary = content_details.get("summary", [])
        if summary:
            return "\n".join(summary)
        return ""
        
    except Exception as e:
        logger.error(f"Error loading summary: {str(e)}")
        return ""

def validate_image_url(img_url):
    """Validate if the URL is a valid image URL (public or signed)."""
    try:
        # Allow signed URLs or public S3 URLs
        if not (img_url.startswith(f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{IMAGES_FOLDER}") or "AWSAccessKeyId" in img_url):
            logger.error(f"Invalid image URL format: {img_url}")
            return False
        
        resp = requests.head(img_url, timeout=5, allow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            logger.error(f"URL is not an image: {img_url}, Content-Type: {content_type}")
            return False
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Image URL inaccessible: {img_url}, Error: {str(e)}")
        return False

def check_facebook_token_validity():
    """Check if Facebook access token is valid"""
    try:
        if not FACEBOOK_ACCESS_TOKEN:
            return False, "Facebook access token not configured"
            
        token_check_url = f"https://graph.facebook.com/v19.0/me?access_token={FACEBOOK_ACCESS_TOKEN}"
        token_check_resp = requests.get(token_check_url, timeout=10)
        if token_check_resp.status_code != 200:
            logger.error(f"Invalid Facebook access token: {token_check_resp.text}")
            return False, f"Invalid Facebook access token: {token_check_resp.text}"
        return True, "Token is valid"
    except Exception as e:
        logger.error(f"Failed to validate Facebook access token: {str(e)}")
        return False, f"Failed to validate Facebook access token: {str(e)}"

def post_single_image_to_facebook(image_url, caption="", image_index=0, total_images=1):
    """Post a single image to Facebook"""
    try:
        # Check if Facebook is properly configured
        if not all([FACEBOOK_PAGE_ID, FACEBOOK_ACCESS_TOKEN]):
            return {
                "status": "error",
                "message": "Facebook credentials not configured",
                "image_url": image_url
            }
        
        # Load captions from content_details.json if no caption provided
        if not caption:
            captions = load_captions_from_content_details()
            if captions and image_index < len(captions):
                caption = captions[image_index]
            else:
                # Fallback to summary
                caption = get_summary_as_fallback_caption()
                if not caption:
                    caption = "Check out this amazing AI-generated content! 🚀✨"
        
        # Add image numbering for multiple images
        if total_images > 1:
            caption = f"{caption}\n\n(Image {image_index + 1} of {total_images})"
        
        # Method 1: Using image URL directly
        url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/photos"
        payload = {
            'url': image_url,
            'caption': caption,
            'access_token': FACEBOOK_ACCESS_TOKEN
        }
        
        response = post_with_retry(url, data=payload)
        result = response.json()
        
        if 'id' in result:
            logger.info(f"✅ Image posted successfully to Facebook: {result['id']}")
            return {
                "status": "success",
                "message": "Image posted successfully",
                "post_id": result['id'],
                "image_url": image_url
            }
        else:
            logger.error(f"❌ Failed to post image: {result}")
            return {
                "status": "error",
                "message": f"Failed to post image: {result}",
                "image_url": image_url
            }
            
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ HTTP error posting image: {str(e)}")
        
        # Method 2: Fallback - Download and upload binary
        try:
            logger.info("Trying fallback method: downloading and uploading binary data")
            
            # Download image
            img_response = requests.get(image_url, timeout=30)
            img_response.raise_for_status()
            
            # Upload binary data
            url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/photos"
            files = {'source': ('image.png', img_response.content, 'image/png')}
            data = {
                'caption': caption,
                'access_token': FACEBOOK_ACCESS_TOKEN
            }
            
            response = post_with_retry(url, data=data, files=files)
            result = response.json()
            
            if 'id' in result:
                logger.info(f"✅ Image posted successfully via fallback method: {result['id']}")
                return {
                    "status": "success",
                    "message": "Image posted successfully (fallback method)",
                    "post_id": result['id'],
                    "image_url": image_url
                }
            else:
                logger.error(f"❌ Fallback method also failed: {result}")
                return {
                    "status": "error",
                    "message": f"Both methods failed: {result}",
                    "image_url": image_url
                }
                
        except Exception as fallback_error:
            logger.error(f"❌ Fallback method failed: {str(fallback_error)}")
            return {
                "status": "error",
                "message": f"Both posting methods failed. Original error: {str(e)}, Fallback error: {str(fallback_error)}",
                "image_url": image_url
            }
    
    except Exception as e:
        logger.error(f"❌ Unexpected error posting image: {str(e)}")
        return {
            "status": "error",
            "message": f"Unexpected error: {str(e)}",
            "image_url": image_url
        }

def post_images_to_facebook(image_urls=None, caption="", num_images=1):
    """
    Main function to post images to Facebook.
    If image_urls is None or empty, fetch latest images from S3.
    """
    try:
        # Check if Facebook is properly configured
        if not all([FACEBOOK_PAGE_ID, FACEBOOK_ACCESS_TOKEN]):
            return {
                "status": "error", 
                "message": "Facebook credentials not configured (FACEBOOK_PAGE_ID, FACEBOOK_ACCESS_TOKEN)"
            }
        
        # Validate Facebook token
        token_valid, token_message = check_facebook_token_validity()
        if not token_valid:
            return {"status": "error", "message": token_message}
        
        # Validate num_images
        if isinstance(num_images, str):
            try:
                num_images = int(num_images)
            except ValueError:
                logger.error(f"Invalid num_images value: {num_images}")
                return {"status": "error", "message": f"Invalid num_images value: {num_images}"}
        
        if not isinstance(num_images, int) or num_images < 1:
            logger.error(f"Invalid num_images: {num_images}, must be a positive integer")
            return {"status": "error", "message": f"Invalid num_images: {num_images}, must be a positive integer"}

        # Fetch images from S3 if image_urls is None or empty
        if image_urls is None or not image_urls:
            try:
                if not s3:
                    return {"status": "error", "message": "AWS S3 not configured"}
                    
                response = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix=IMAGES_FOLDER)
                image_keys = [obj['Key'] for obj in response.get('Contents', []) if obj['Key'] != IMAGES_FOLDER]
                
                if not image_keys:
                    logger.error("No images found in S3 'images/' folder")
                    return {"status": "error", "message": "No images found in S3 'images/' folder"}

                # Sort by last modified (newest first) and take the requested number
                sorted_keys = sorted(response['Contents'], key=lambda x: x['LastModified'], reverse=True)
                selected_keys = [obj['Key'] for obj in sorted_keys if obj['Key'] != IMAGES_FOLDER][:num_images]
                image_urls = [f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{key}" for key in selected_keys]
                
                logger.info(f"Fetched {len(image_urls)} images from S3 for Facebook")
                
            except Exception as e:
                logger.error(f"Failed to fetch images from S3: {str(e)}")
                return {"status": "error", "message": f"Failed to fetch images from S3: {str(e)}"}

        # Validate image URLs
        valid_image_urls = [url for url in image_urls if validate_image_url(url)]
        if not valid_image_urls:
            logger.error("No valid image URLs provided after validation")
            return {"status": "error", "message": "No valid image URLs provided after validation"}

        # Use only the requested number of images
        valid_image_urls = valid_image_urls[:num_images]
        
        logger.info(f"Posting {len(valid_image_urls)} images to Facebook")

        # Post images (Facebook posts each image separately)
        results = []
        captions = load_captions_from_content_details() if not caption else []
        
        for idx, image_url in enumerate(valid_image_urls):
            # Use specific caption for each image if available
            if captions and idx < len(captions):
                image_caption = captions[idx]
            elif caption:
                image_caption = caption
            else:
                # Fallback to summary
                image_caption = get_summary_as_fallback_caption()
                if not image_caption:
                    image_caption = "Check out this amazing AI-generated content! 🚀✨"
            
            result = post_single_image_to_facebook(
                image_url, 
                image_caption, 
                image_index=idx, 
                total_images=len(valid_image_urls)
            )
            results.append(result)
            
            # Add delay between posts to avoid rate limiting
            if idx < len(valid_image_urls) - 1:
                time.sleep(5)
        
        successful_posts = sum(1 for r in results if r["status"] == "success")
        
        return {
            "status": "success" if successful_posts > 0 else "error",
            "message": f"Posted {successful_posts} out of {len(results)} images successfully to Facebook",
            "results": results,
            "total_images": len(results),
            "successful_posts": successful_posts
        }
            
    except Exception as e:
        logger.error(f"Unexpected error in post_images_to_facebook: {str(e)}")
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}