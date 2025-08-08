import os
import boto3
import requests
import time
import re
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
INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID")
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")

IMAGES_FOLDER = "images/"

# Validate environment variables
if not all([AWS_REGION, S3_BUCKET_NAME, INSTAGRAM_USER_ID, INSTAGRAM_ACCESS_TOKEN]):
    logger.error("Missing required environment variables")
    raise ValueError("Missing required environment variables")

s3 = boto3.client("s3", region_name=AWS_REGION)

# === ✅ Sort helper ===
def sort_image_urls_by_number(urls):
    def extract_number(url):
        match = re.search(r'image_(\d+)_', url)
        return int(match.group(1)) if match else 0
    return sorted(urls, key=extract_number)

# === Retry POST ===
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def post_with_retry(url, data):
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }
    logger.info(f"Sending POST request to {url} with data: {data}")
    resp = requests.post(url, data=data, headers=headers, timeout=10)
    logger.info(f"API Response: {resp.status_code}, {resp.text}")
    resp.raise_for_status()
    return resp

# === Validate URL ===
def validate_image_url(img_url):
    try:
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

# === Main Post Function ===
def post_carousel_to_instagram(image_urls=None, caption="", num_images=1):
    try:
        if isinstance(num_images, str):
            try:
                num_images = int(num_images)
            except ValueError:
                return {"status": "error", "message": f"Invalid num_images value: {num_images}"}
        if not isinstance(num_images, int) or num_images < 1:
            return {"status": "error", "message": f"Invalid num_images: {num_images}"}

        if image_urls is None or not image_urls:
            try:
                response = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix=IMAGES_FOLDER)
                image_keys = [obj['Key'] for obj in response.get('Contents', []) if obj['Key'] != IMAGES_FOLDER]

                def extract_image_number(obj):
                    match = re.search(r'image_(\d+)_', obj['Key'])
                    return int(match.group(1)) if match else 0

                sorted_objects = sorted(response['Contents'], key=lambda obj: extract_image_number(obj))
                selected_keys = [obj['Key'] for obj in sorted_objects if obj['Key'] != IMAGES_FOLDER][:num_images]
                image_urls = [f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{key}" for key in selected_keys]
            except Exception as e:
                return {"status": "error", "message": f"Failed to fetch images from S3: {str(e)}"}

        # ✅ Sort image URLs by number in filename (image_1, image_2, ...)
        image_urls = sort_image_urls_by_number(image_urls)
        logger.info(f"Sorted image_urls: {image_urls}")

        valid_image_urls = [url for url in image_urls if validate_image_url(url)]
        if not valid_image_urls:
            return {"status": "error", "message": "No valid image URLs provided after validation"}
        if len(valid_image_urls) < num_images:
            return {"status": "error", "message": f"Only {len(valid_image_urls)} valid images available, but {num_images} requested"}
        if num_images > 1 and len(valid_image_urls) < 2:
            return {"status": "error", "message": "Carousel requires at least 2 images"}

        valid_image_urls = valid_image_urls[:num_images]

        token_check_url = f"https://graph.facebook.com/v19.0/me?access_token={INSTAGRAM_ACCESS_TOKEN}"
        token_check_resp = requests.get(token_check_url, timeout=5)
        if token_check_resp.status_code != 200:
            return {"status": "error", "message": f"Invalid Instagram access token: {token_check_resp.text}"}

        if num_images == 1:
            create_url = f"https://graph.facebook.com/v19.0/{INSTAGRAM_USER_ID}/media"
            create_resp = post_with_retry(create_url, data={
                "image_url": valid_image_urls[0],
                "caption": caption,
                "access_token": INSTAGRAM_ACCESS_TOKEN
            })
            container_id = create_resp.json().get("id")
            if not container_id:
                return {"status": "error", "message": "No container ID returned for single image"}

            publish_url = f"https://graph.facebook.com/v19.0/{INSTAGRAM_USER_ID}/media_publish"
            publish_resp = post_with_retry(publish_url, data={
                "creation_id": container_id,
                "access_token": INSTAGRAM_ACCESS_TOKEN
            })
            return {
                "status": "success",
                "message": "Single image posted successfully",
                "container_id": container_id,
                "publish_response": publish_resp.json()
            }

        # === Carousel logic ===
        children_ids = []
        for idx, img_url in enumerate(valid_image_urls, 1):
            create_url = f"https://graph.facebook.com/v19.0/{INSTAGRAM_USER_ID}/media"
            create_resp = post_with_retry(create_url, data={
                "image_url": img_url,
                "is_carousel_item": "true",
                "access_token": INSTAGRAM_ACCESS_TOKEN
            })
            container_id = create_resp.json().get("id")
            if not container_id:
                return {"status": "error", "message": f"No container ID returned for carousel item {idx}"}
            children_ids.append(str(container_id))
            time.sleep(10)

        carousel_create_url = f"https://graph.facebook.com/v19.0/{INSTAGRAM_USER_ID}/media"
        carousel_resp = post_with_retry(carousel_create_url, data={
            "caption": caption,
            "children": ",".join(children_ids),
            "access_token": INSTAGRAM_ACCESS_TOKEN,
            "media_type": "CAROUSEL"
        })

        container_id = carousel_resp.json().get("id")
        if not container_id:
            return {"status": "error", "message": "No container ID returned for carousel"}

        publish_url = f"https://graph.facebook.com/v19.0/{INSTAGRAM_USER_ID}/media_publish"
        publish_resp = post_with_retry(publish_url, data={
            "creation_id": container_id,
            "access_token": INSTAGRAM_ACCESS_TOKEN
        })

        return {
            "status": "success",
            "message": f"Carousel with {len(children_ids)} images posted",
            "carousel_container_id": container_id,
            "publish_response": publish_resp.json()
        }

    except Exception as e:
        logger.error(f"Unexpected error in post_carousel_to_instagram: {str(e)}")
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}
    

    