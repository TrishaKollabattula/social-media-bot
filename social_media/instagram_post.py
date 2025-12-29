# social_media/instagram_post.py
import os
import boto3
import requests
import time
import json
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential
import logging
from datetime import datetime, timedelta
import re

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Environment variables
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

IMAGES_FOLDER = "images/"

# Only validate AWS credentials (required for all operations)
if not AWS_REGION or not S3_BUCKET_NAME:
    logger.error("Missing required AWS environment variables: AWS_REGION or S3_BUCKET_NAME")
    raise ValueError("Missing required environment variables: AWS_REGION or S3_BUCKET_NAME")

s3 = boto3.client("s3", region_name=AWS_REGION)
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
social_tokens_table = dynamodb.Table('SocialTokens')

# Retry decorator for API calls
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def post_with_retry(url, data):
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }
    logger.info(f"Sending POST request to {url}")
    resp = requests.post(url, data=data, headers=headers, timeout=15)
    logger.info(f"API Response: {resp.status_code}, {resp.text}")
    resp.raise_for_status()
    return resp

def get_user_instagram_credentials(user_id):
    """
    Fetch Instagram credentials from DynamoDB for the given user.
    
    Args:
        user_id: The app user ID (e.g., 'craftingbrain')
    
    Returns:
        dict: Instagram credentials or None if not found/expired
    """
    try:
        logger.info(f"[INSTAGRAM] Fetching credentials for user: {user_id}")
        
        # Fetch user data from DynamoDB
        response = social_tokens_table.scan(
            FilterExpression='user_id = :uid',
            ExpressionAttributeValues={':uid': user_id}
        )
        
        items = response.get('Items', [])
        
        if not items:
            logger.warning(f"[INSTAGRAM] No data found for user: {user_id}")
            return None
        
        user_data = {}
        for item in items:
            user_data.update(item)
        
        # Check if Instagram is connected
        if not user_data.get('instagram_access_token'):
            logger.warning(f"[INSTAGRAM] User {user_id} has not connected Instagram")
            return None
        
        # Check if token is expired
        token_expires_at = user_data.get('instagram_token_expires_at')
        if token_expires_at:
            try:
                expiry_date = datetime.fromisoformat(token_expires_at)
                if datetime.utcnow() > expiry_date:
                    logger.warning(f"[INSTAGRAM] Token expired for user {user_id}")
                    return None
            except Exception as e:
                logger.warning(f"[INSTAGRAM] Could not parse expiry date: {e}")
        
        credentials = {
            'instagram_user_id': user_data.get('instagram_user_id'),
            'instagram_access_token': user_data.get('instagram_access_token'),
            'instagram_username': user_data.get('instagram_username'),
            'instagram_page_name': user_data.get('instagram_page_name')
        }
        
        logger.info(f"[INSTAGRAM] ✅ Found credentials for user {user_id} (@{credentials.get('instagram_username')})")
        return credentials
        
    except Exception as e:
        logger.error(f"[INSTAGRAM] Error fetching credentials for user {user_id}: {str(e)}")
        return None

def load_caption_from_content_details():
    """
    Load caption from content_details.json > captions > post_caption.
    Returns the post_caption or a default message if not found.
    """
    try:
        with open("content_details.json", 'r') as file:
            data = json.load(file)
            
            # Get post_caption from captions object
            captions = data.get('captions', {})
            post_caption = captions.get('post_caption', '')
            
            if post_caption:
                logger.info(f"✅ Loaded post_caption from content_details.json: {len(post_caption)} characters")
                return post_caption
            else:
                # Fallback to summary if post_caption doesn't exist
                summary = data.get('summary', [])
                if summary:
                    fallback_caption = " ".join(summary)
                    fallback_caption += "\n\n#AI #Technology #Innovation #GenerativeAI"
                    logger.info("⚠️ No post_caption found, using summary as fallback")
                    return fallback_caption
                else:
                    # Final fallback
                    default_caption = "🚀 Explore the latest insights in AI and technology! #AI #Innovation #Technology"
                    logger.info("⚠️ No post_caption or summary found, using default caption")
                    return default_caption
                    
    except FileNotFoundError:
        logger.warning("⚠️ content_details.json not found, using default caption")
        return "🚀 Check out our latest AI insights! #AI #Innovation #Technology"
    except json.JSONDecodeError:
        logger.error("❌ Invalid JSON in content_details.json, using default caption")
        return "🚀 Check out our latest AI insights! #AI #Innovation #Technology"
    except Exception as e:
        logger.error(f"❌ Error loading caption: {str(e)}, using default caption")
        return "🚀 Check out our latest AI insights! #AI #Innovation #Technology"

def validate_image_url(img_url):
    """Validate if the URL is a valid image URL (public or signed)."""
    try:
        # More flexible URL validation - allow any HTTPS image URL
        if not (img_url.startswith("https://") and img_url.lower().endswith(('.jpg', '.jpeg', '.png'))):
            logger.error(f"Invalid image URL format: {img_url}")
            return False
        
        resp = requests.head(img_url, timeout=10, allow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            logger.error(f"URL is not an image: {img_url}, Content-Type: {content_type}")
            return False
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Image URL inaccessible: {img_url}, Error: {str(e)}")
        return False

def get_latest_image_set_from_s3(num_images):
    """
    Get the latest set of images from S3 - ONLY used as fallback when no specific URLs provided.
    Returns images in the correct sequence order (image_1_*, image_2_*, etc.)
    """
    try:
        response = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix=IMAGES_FOLDER)
        image_objects = [obj for obj in response.get('Contents', []) if obj['Key'] != IMAGES_FOLDER and obj['Key'].lower().endswith(('.jpg', '.jpeg', '.png'))]
        
        if not image_objects:
            logger.error("No images found in S3 'images/' folder")
            return []

        # Sort by LastModified to get the most recent images first
        sorted_objects = sorted(image_objects, key=lambda x: x['LastModified'], reverse=True)
        
        # Take the most recent images (likely just generated)
        recent_objects = sorted_objects[:num_images * 2]  # Get more to ensure we have enough
        
        # Sort by filename to ensure correct sequence (image_1_*, image_2_*, etc.)
        def extract_image_number(key):
            # Extract number from filename like "image_1_xxxxx.png" -> 1
            match = re.search(r'image_(\d+)_', key)
            return int(match.group(1)) if match else 999
        
        recent_objects_sorted = sorted(recent_objects, key=lambda x: extract_image_number(x['Key']))
        
        # Take only the requested number of images
        selected_objects = recent_objects_sorted[:num_images]
        
        # Convert to URLs
        image_urls = [f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{obj['Key']}" 
                     for obj in selected_objects]
        
        logger.info(f"✅ S3 Fallback - Selected images: {[obj['Key'] for obj in selected_objects]}")
        logger.info(f"✅ S3 Fallback - Image URLs: {image_urls}")
        
        return image_urls
        
    except Exception as e:
        logger.error(f"Failed to fetch latest images from S3: {str(e)}")
        return []

def clean_instagram_caption(caption):
    """Clean and optimize caption for Instagram"""
    if not caption:
        return "Check out this AI-generated content! 🚀 #AI #Technology #Innovation"
    
    # Instagram allows up to 2200 characters, but let's keep it reasonable
    max_length = 2000
    
    # Remove any problematic characters but keep emojis
    cleaned = re.sub(r'[^\x00-\x7F\u00A0-\u00FF\u0100-\u017F\u0180-\u024F\u2600-\u27BF\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]', '', caption)
    
    # Clean up extra spaces and newlines
    cleaned = ' '.join(cleaned.split())
    
    # If caption is too long, truncate smartly
    if len(cleaned) > max_length:
        # Try to truncate at a sentence boundary
        sentences = cleaned.split('.')
        truncated = ""
        for sentence in sentences:
            if len(truncated + sentence + ".") <= max_length - 50:  # Leave room for hashtags
                truncated += sentence + "."
            else:
                break
        
        if truncated:
            cleaned = truncated
        else:
            # Fallback: simple truncation
            cleaned = cleaned[:max_length-50] + "..."
    
    # Ensure we have some hashtags if none exist
    if '#' not in cleaned:
        cleaned += " #AI #Technology #Innovation"
    
    return cleaned.strip()

def post_carousel_to_instagram(user_id, image_urls=None, caption="", num_images=1):
    """
    Post images to Instagram for a specific user.
    
    AUTOMATICALLY fetches user's Instagram credentials from DynamoDB.
    
    Args:
        user_id: The app user ID (e.g., 'craftingbrain') - REQUIRED
        image_urls: List of image URLs to post (optional, will fetch from S3 if not provided)
        caption: Caption for the post (optional, will load from content_details.json)
        num_images: Number of images (1-10)
    
    Returns:
        dict: Status and details of the post
    """
    try:
        # STEP 1: Get user's Instagram credentials from DynamoDB
        logger.info(f"[INSTAGRAM] Starting post for user: {user_id}")
        
        credentials = get_user_instagram_credentials(user_id)
        
        if not credentials:
            error_msg = "Instagram not connected. Please connect your Instagram account first."
            logger.error(f"❌ {error_msg}")
            return {
                "status": "error", 
                "message": error_msg,
                "action_required": "connect_instagram"
            }
        
        instagram_user_id = credentials['instagram_user_id']
        instagram_access_token = credentials['instagram_access_token']
        instagram_username = credentials.get('instagram_username', 'Unknown')
        
        logger.info(f"[INSTAGRAM] ✅ Posting to @{instagram_username} (ID: {instagram_user_id[:20]}...)")
        
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

        # Load caption from content_details.json if not provided
        if not caption or caption.strip() == "":
            logger.info("📝 No caption provided, loading from content_details.json...")
            caption = load_caption_from_content_details()
        
        # Clean and prepare caption
        clean_caption = clean_instagram_caption(caption)
        logger.info(f"📝 Using Instagram caption: {len(clean_caption)} characters")
        logger.info(f"📝 Caption preview: {clean_caption[:100]}...")

        # Use provided image_urls if available, otherwise fallback to S3
        if image_urls and len(image_urls) > 0:
            logger.info(f"✅ Using PROVIDED image URLs: {[url.split('/')[-1] if '/' in url else url for url in image_urls]}")
            final_image_urls = image_urls[:num_images]
        else:
            logger.info(f"🔍 No image URLs provided, fetching latest {num_images} images from S3...")
            final_image_urls = get_latest_image_set_from_s3(num_images)
            if not final_image_urls:
                return {"status": "error", "message": "No images found - neither provided nor in S3 'images/' folder"}

        logger.info(f"📸 Processing {len(final_image_urls)} image_urls for Instagram: {[url.split('/')[-1] for url in final_image_urls]}")

        # Validate image URLs
        valid_image_urls = []
        for url in final_image_urls:
            if validate_image_url(url):
                valid_image_urls.append(url)
            else:
                logger.warning(f"Invalid image URL skipped: {url}")
        
        if not valid_image_urls:
            logger.error("No valid image URLs after validation")
            return {"status": "error", "message": "No valid image URLs after validation"}

        # Ensure enough images for request
        if len(valid_image_urls) < num_images:
            logger.warning(f"Requested {num_images} images, but only {len(valid_image_urls)} valid images available")
            num_images = len(valid_image_urls)
        
        # Ensure carousel has at least 2 images
        if num_images > 1 and len(valid_image_urls) < 2:
            logger.error("Carousel requires at least 2 images")
            return {"status": "error", "message": "Carousel requires at least 2 images"}

        # Use only the requested number of images IN THE CORRECT SEQUENCE
        valid_image_urls = valid_image_urls[:num_images]

        # Check Instagram access token validity
        try:
            token_check_url = f"https://graph.facebook.com/v19.0/me?access_token={instagram_access_token}"
            token_check_resp = requests.get(token_check_url, timeout=10)
            if token_check_resp.status_code != 200:
                logger.error(f"Invalid Instagram access token for user {user_id}: {token_check_resp.text}")
                return {
                    "status": "error", 
                    "message": "Instagram access token expired. Please reconnect your Instagram account.",
                    "action_required": "reconnect_instagram"
                }
        except Exception as e:
            logger.error(f"Failed to validate Instagram access token: {str(e)}")
            return {"status": "error", "message": f"Failed to validate Instagram access token: {str(e)}"}

        if num_images == 1:
            # Post single image
            create_url = f"https://graph.facebook.com/v19.0/{instagram_user_id}/media"
            try:
                logger.info(f"📤 Posting single image to @{instagram_username}: {valid_image_urls[0].split('/')[-1]}")
                create_resp = post_with_retry(create_url, data={
                    "image_url": valid_image_urls[0],
                    "caption": clean_caption,
                    "access_token": instagram_access_token
                })
                container_id = create_resp.json().get("id")
                if not container_id:
                    logger.error("No container ID returned for single image")
                    return {"status": "error", "message": "No container ID returned for single image"}

                # Wait before publishing
                logger.info("⏳ Waiting 10 seconds before publishing...")
                time.sleep(10)

                publish_url = f"https://graph.facebook.com/v19.0/{instagram_user_id}/media_publish"
                publish_resp = post_with_retry(publish_url, data={
                    "creation_id": container_id,
                    "access_token": instagram_access_token
                })
                
                result = {
                    "status": "success",
                    "message": f"Single image posted successfully to @{instagram_username}",
                    "platform": "instagram",
                    "username": instagram_username,
                    "container_id": container_id,
                    "image_url": valid_image_urls[0],
                    "caption_used": clean_caption,
                    "publish_response": publish_resp.json()
                }
                logger.info(f"✅ Instagram single image posted successfully to @{instagram_username}!")
                return result
                
            except requests.exceptions.HTTPError as e:
                error_msg = f"Single image post failed: {str(e)}"
                if hasattr(e, 'response'):
                    error_msg += f", Response: {e.response.text}"
                logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        else:
            # Post as carousel (2 or more images) IN CORRECT SEQUENCE
            children_ids = []
            logger.info(f"🎠 Creating carousel with {len(valid_image_urls)} images for @{instagram_username}...")
            
            for idx, img_url in enumerate(valid_image_urls, 1):
                create_url = f"https://graph.facebook.com/v19.0/{instagram_user_id}/media"
                try:
                    logger.info(f"📷 Creating carousel item {idx}/{len(valid_image_urls)}: {img_url.split('/')[-1]}")
                    create_resp = post_with_retry(create_url, data={
                        "image_url": img_url,
                        "is_carousel_item": "true",
                        "access_token": instagram_access_token
                    })
                    container_id = create_resp.json().get("id")
                    if not container_id:
                        logger.error(f"No container ID returned for carousel item {idx}")
                        return {"status": "error", "message": f"No container ID returned for carousel item {idx}"}
                    children_ids.append(str(container_id))
                    
                    # Delay between carousel items to avoid rate limits
                    if idx < len(valid_image_urls):
                        logger.info(f"⏳ Waiting 12 seconds before next carousel item...")
                        time.sleep(12)
                        
                except requests.exceptions.HTTPError as e:
                    error_msg = f"Carousel item {idx} creation failed: {str(e)}"
                    if hasattr(e, 'response'):
                        error_msg += f", Response: {e.response.text}"
                    logger.error(error_msg)
                    return {"status": "error", "message": error_msg}

            # Wait before creating carousel container
            logger.info("⏳ Waiting 10 seconds before creating carousel container...")
            time.sleep(10)

            carousel_create_url = f"https://graph.facebook.com/v19.0/{instagram_user_id}/media"
            carousel_payload = {
                "caption": clean_caption,
                "children": ",".join(children_ids),
                "access_token": instagram_access_token,
                "media_type": "CAROUSEL"
            }
            try:
                logger.info(f"🎠 Creating carousel post with {len(children_ids)} items for @{instagram_username}")
                carousel_create_resp = post_with_retry(carousel_create_url, data=carousel_payload)
                container_id = carousel_create_resp.json().get("id")
                if not container_id:
                    logger.error("No container ID returned for carousel")
                    return {"status": "error", "message": "No container ID returned for carousel"}

                # Wait before publishing
                logger.info("⏳ Waiting 15 seconds before publishing carousel...")
                time.sleep(15)

                publish_url = f"https://graph.facebook.com/v19.0/{instagram_user_id}/media_publish"
                publish_resp = post_with_retry(publish_url, data={
                    "creation_id": container_id,
                    "access_token": instagram_access_token
                })
                
                result = {
                    "status": "success",
                    "message": f"Carousel with {len(children_ids)} images posted successfully to @{instagram_username}",
                    "platform": "instagram",
                    "username": instagram_username,
                    "carousel_container_id": container_id,
                    "image_urls": valid_image_urls,
                    "children_ids": children_ids,
                    "caption_used": clean_caption,
                    "publish_response": publish_resp.json()
                }
                logger.info(f"✅ Instagram carousel posted successfully to @{instagram_username}!")
                return result
                
            except requests.exceptions.HTTPError as e:
                error_msg = f"Carousel post failed: {str(e)}"
                if hasattr(e, 'response'):
                    error_msg += f", Response: {e.response.text}"
                logger.error(error_msg)
                return {"status": "error", "message": error_msg}

    except Exception as e:
        error_msg = f"Unexpected error in Instagram posting: {str(e)}"
        logger.error(error_msg)
        return {"status": "error", "message": error_msg}

# Legacy compatibility function
def post_image_to_instagram(user_id, image_url, caption=""):
    """Legacy function for single image posting"""
    return post_carousel_to_instagram(
        user_id=user_id,
        image_urls=[image_url] if image_url else None,
        caption=caption,
        num_images=1
    )