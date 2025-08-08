import requests
import logging
import boto3
import os
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
API_VERSION = "202507"  # LinkedIn API version
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN")
# ✅ CHANGED: Updated to use ORG_URN instead of USER_URN for organization posting
LINKEDIN_ORG_URN = os.getenv("LINKEDIN_ORG_URN", "urn:li:organization:99331065")  # Default from your test

# Initialize S3 client
s3 = boto3.client("s3", region_name=AWS_REGION) if AWS_REGION else None


def get_latest_pdf_from_s3():
    """
    Fetch the most recent PDF from the S3 'pdfs' folder.
    Returns the S3 URL of the latest PDF or None if no PDFs found.
    """
    if not s3 or not S3_BUCKET_NAME:
        logging.error("S3 client not initialized or S3_BUCKET_NAME not set")
        return None
    
    try:
        response = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix="pdfs/")
        pdfs = [obj for obj in response.get('Contents', []) if obj['Key'].endswith('.pdf')]
        
        if pdfs:
            # Sort by LastModified to get the most recent PDF
            latest_pdf = sorted(pdfs, key=lambda x: x['LastModified'], reverse=True)[0]
            s3_pdf_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{latest_pdf['Key']}"
            logging.info(f"Latest PDF found: {s3_pdf_url}")
            return s3_pdf_url
        else:
            logging.warning("No PDFs found in the 'pdfs' folder.")
            return None
    except Exception as e:
        logging.error(f"Error fetching PDFs from S3: {str(e)}")
        return None


def get_latest_image_from_s3():
    """
    Fetch the most recent image from the S3 'images' folder.
    Returns the S3 URL of the latest image or None if no images found.
    """
    if not s3 or not S3_BUCKET_NAME:
        logging.error("S3 client not initialized or S3_BUCKET_NAME not set")
        return None
    
    try:
        response = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix="images/")
        images = [obj for obj in response.get('Contents', []) 
                 if obj['Key'].lower().endswith(('.jpg', '.jpeg', '.png')) and obj['Key'] != "images/"]
        
        if images:
            # Sort by LastModified to get the most recent image
            latest_image = sorted(images, key=lambda x: x['LastModified'], reverse=True)[0]
            s3_image_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{latest_image['Key']}"
            logging.info(f"Latest image found: {s3_image_url}")
            return s3_image_url
        else:
            logging.warning("No images found in the 'images' folder.")
            return None
    except Exception as e:
        logging.error(f"Error fetching images from S3: {str(e)}")
        return None


def load_caption_from_content_details():
    """
    Load caption from content_details.json summary.
    Returns a formatted caption or default message.
    """
    try:
        with open("content_details.json", 'r') as file:
            data = json.load(file)
            summary = data.get('summary', [])
            if summary:
                # ✅ CHANGED: Format as paragraph instead of bullet points
                caption = " ".join(summary)  # Join with spaces instead of newlines
                caption += "\n\n#DataScience #AI #MachineLearning #TechTrends #Innovation"
                logging.info(f"Loaded caption from summary: {caption[:100]}...")
                return caption
            else:
                # Fallback to default caption
                default_caption = "🚀 Explore the latest insights in Data Science and AI! #DataScience #AI #Innovation"
                logging.info("No summary found, using default caption")
                return default_caption
    except FileNotFoundError:
        logging.warning("content_details.json not found, using default caption")
        return "🚀 Check out our latest insights! #DataScience #AI #Innovation"
    except json.JSONDecodeError:
        logging.error("Invalid JSON in content_details.json, using default caption")
        return "🚀 Check out our latest insights! #DataScience #AI #Innovation"

# ✅ CHANGED: Updated function to match your working test code exactly
def post_pdf_to_linkedin(s3_pdf_url, caption, access_token=None, org_urn=None):
    """
    Upload and share a PDF on LinkedIn from S3 URL using the exact API from your working test.
    """
    access_token = access_token or LINKEDIN_ACCESS_TOKEN
    org_urn = org_urn or LINKEDIN_ORG_URN  # Ensure this is the correct org_urn
    
    if not access_token:
        logging.error("Missing LinkedIn access token")
        return False, "Missing LinkedIn access token"
    
    if not org_urn:
        logging.error("Missing LinkedIn organization URN")
        return False, "Missing LinkedIn organization URN"
    
    logging.info(f"🚀 Starting PDF upload to LinkedIn: {s3_pdf_url}")
    
    try:
        # Step 1: Initialize upload
        init_url = "https://api.linkedin.com/rest/documents?action=initializeUpload"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": "202507",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json"
        }
        init_data = {
            "initializeUploadRequest": {
                "owner": org_urn  # Use the organization URN here
            }
        }
        
        init_response = requests.post(init_url, headers=headers, json=init_data)
        if init_response.status_code != 200:
            logging.error(f"Failed to initialize upload: {init_response.text}")
            return False, f"Failed to initialize upload: {init_response.text}"
        
        upload_url = init_response.json()["value"]["uploadUrl"]
        doc_urn = init_response.json()["value"]["document"]
        logging.info(f"✅ Upload initialized. Document URN: {doc_urn}")
        
        # Step 2: Download PDF from URL and upload
        pdf_response = requests.get(s3_pdf_url)
        if pdf_response.status_code == 200:
            upload_response = requests.put(upload_url, headers={"Authorization": f"Bearer {access_token}"}, data=pdf_response.content)
            if upload_response.status_code == 201:
                logging.info("✅ PDF uploaded successfully")
            else:
                logging.error(f"Failed to upload PDF: {upload_response.text}")
                return False, f"Failed to upload PDF: {upload_response.text}"
        else:
            logging.error(f"Failed to download PDF: {pdf_response.text}")
            return False, f"Failed to download PDF: {pdf_response.text}"
        
        # Step 3: Create post
        post_url = "https://api.linkedin.com/rest/posts"
        post_data = {
            "author": org_urn,  # Ensure this is the correct org_urn, not user_urn
            "commentary": caption,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": []
            },
            "content": {
                "media": {
                    "title": os.path.basename(s3_pdf_url).replace('.pdf', '') + '.pdf',
                    "id": doc_urn
                }
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False
        }
        
        post_response = requests.post(post_url, headers=headers, json=post_data)
        if post_response.status_code == 201:
            post_id = post_response.headers.get('x-linkedin-id')
            success_msg = f"✅ PDF posted successfully! Post ID: {post_id}"
            logging.info(success_msg)
            return True, success_msg
        else:
            logging.error(f"Failed to create post: {post_response.text}")
            return False, f"Failed to create post: {post_response.text}"
            
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logging.error(error_msg)
        return False, error_msg


# In your post_image_to_linkedin function

def post_image_to_linkedin(s3_image_url, caption, access_token=None, org_urn=None):
    """
    Upload and share an image on LinkedIn from S3 URL.
    """
    access_token = access_token or LINKEDIN_ACCESS_TOKEN
    org_urn = org_urn or LINKEDIN_ORG_URN  # Ensure this is the correct org_urn
    
    if not access_token:
        logging.error("Missing LinkedIn access token")
        return False, "Missing LinkedIn access token"
    
    if not org_urn:
        logging.error("Missing LinkedIn organization URN")
        return False, "Missing LinkedIn organization URN"
    
    logging.info(f"🚀 Starting image upload to LinkedIn: {s3_image_url}")
    
    try:
        # Step 1: Initialize image upload
        init_url = "https://api.linkedin.com/rest/images?action=initializeUpload"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": "202507",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json"
        }
        init_data = {
            "initializeUploadRequest": {
                "owner": org_urn  # Use the organization URN here
            }
        }
        
        init_response = requests.post(init_url, headers=headers, json=init_data)
        if init_response.status_code != 200:
            logging.error(f"Failed to initialize image upload: {init_response.text}")
            return False, f"Failed to initialize image upload: {init_response.text}"
        
        upload_url = init_response.json()["value"]["uploadUrl"]
        image_urn = init_response.json()["value"]["image"]
        logging.info(f"✅ Image upload initialized. Image URN: {image_urn}")
        
        # Step 2: Download image from S3 and upload to LinkedIn
        image_response = requests.get(s3_image_url)
        if image_response.status_code == 200:
            # Determine content type
            if s3_image_url.lower().endswith('.png'):
                content_type = "image/png"
            elif s3_image_url.lower().endswith(('.jpg', '.jpeg')):
                content_type = "image/jpeg"
            else:
                content_type = "image/png"
            
            upload_response = requests.put(
                upload_url, 
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": content_type
                }, 
                data=image_response.content
            )
            if upload_response.status_code == 201:
                logging.info("✅ Image uploaded successfully")
            else:
                logging.error(f"Failed to upload image: {upload_response.text}")
                return False, f"Failed to upload image: {upload_response.text}"
        else:
            logging.error(f"Failed to download image: {image_response.text}")
            return False, f"Failed to download image: {image_response.text}"
        
        # Step 3: Create post
        post_url = "https://api.linkedin.com/rest/posts"
        post_data = {
            "author": org_urn,  # Ensure this is the correct org_urn, not user_urn
            "commentary": caption,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": []
            },
            "content": {
                "media": {
                    "id": image_urn
                }
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False
        }
        
        post_response = requests.post(post_url, headers=headers, json=post_data)
        if post_response.status_code == 201:
            post_id = post_response.headers.get('x-linkedin-id')
            success_msg = f"✅ Image posted successfully! Post ID: {post_id}"
            logging.info(success_msg)
            return True, success_msg
        else:
            logging.error(f"Failed to create image post: {post_response.text}")
            return False, f"Failed to create image post: {post_response.text}"
            
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logging.error(error_msg)
        return False, error_msg


# ✅ CHANGED: Updated function signature to match lambda_function.py calls
# In your post_content_to_linkedin function
def post_content_to_linkedin(s3_url=None, caption=None, access_token=None, user_urn=None):
    """
    Smart dispatcher: posts the latest PDF or image from S3 to LinkedIn.
    If s3_url is provided, posts that specific file.
    If s3_url is None, automatically fetches the latest PDF or image from S3.
    
    Note: user_urn parameter is kept for backward compatibility with lambda_function.py
    """
    logging.info(f"🎯 post_content_to_linkedin called with s3_url={s3_url}, caption_len={len(caption) if caption else 0}")
    
    access_token = access_token or LINKEDIN_ACCESS_TOKEN
    org_urn = user_urn or LINKEDIN_ORG_URN  # Use org_urn here
    
    logging.info(f"🔐 Using access_token: {access_token[:20] if access_token else 'None'}...")
    logging.info(f"🏢 Using org_urn: {org_urn}")
    
    if not access_token:
        error_msg = "❌ Missing LinkedIn access token."
        logging.error(error_msg)
        return False, error_msg
    
    if not org_urn:
        error_msg = "❌ Missing LinkedIn organization URN."
        logging.error(error_msg)
        return False, error_msg
    
    # Load caption from content_details.json if not provided
    if not caption:
        caption = load_caption_from_content_details()
        logging.info(f"📝 Loaded caption from content_details: {len(caption)} chars")
    
    # If specific URL provided, post that file
    if s3_url:
        logging.info(f"📎 Posting specific file: {s3_url}")
        if "/pdfs/" in s3_url and s3_url.lower().endswith('.pdf'):
            logging.info("📄 Detected PDF file, calling post_pdf_to_linkedin")
            return post_pdf_to_linkedin(s3_url, caption, access_token, org_urn)
        elif "/images/" in s3_url and s3_url.lower().endswith(('.jpg', '.jpeg', '.png')):
            logging.info("🖼️ Detected image file, calling post_image_to_linkedin")
            return post_image_to_linkedin(s3_url, caption, access_token, org_urn)
        else:
            error_msg = f"❌ Unsupported file type or invalid S3 URL: {s3_url}"
            logging.error(error_msg)
            return False, error_msg
    
    # If no URL provided, try to post latest PDF first, then latest image
    logging.info("🔍 No specific URL provided, auto-detecting latest content...")
    
    pdf_url = get_latest_pdf_from_s3()
    if pdf_url:
        logging.info(f"📄 Found latest PDF, posting to LinkedIn: {pdf_url}")
        return post_pdf_to_linkedin(pdf_url, caption, access_token, org_urn)
    
    image_url = get_latest_image_from_s3()
    if image_url:
        logging.info(f"🖼️ No PDF found, posting latest image to LinkedIn: {image_url}")
        return post_image_to_linkedin(image_url, caption, access_token, org_urn)
    
    error_msg = "❌ No PDF or image files found in S3 to post"
    logging.error(error_msg)
    return False, error_msg


def post_latest_content_to_linkedin():
    """
    Convenience function to post the latest generated content to LinkedIn.
    This function can be called after content generation is complete.
    """
    logging.info("🚀 Starting automatic LinkedIn posting...")
    
    try:
        success, message = post_content_to_linkedin()
        if success:
            logging.info(f"✅ LinkedIn posting successful: {message}")
        else:
            logging.error(f"❌ LinkedIn posting failed: {message}")
        return success, message
    except Exception as e:
        error_msg = f"Unexpected error in LinkedIn posting: {str(e)}"
        logging.error(error_msg)
        return False, error_msg


if __name__ == "__main__":
    # Test the posting functionality
    success, message = post_latest_content_to_linkedin()
    print(message)