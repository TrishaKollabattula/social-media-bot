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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

# Optional (only if you later want debug_token)
INSTAGRAM_CLIENT_ID = os.getenv("INSTAGRAM_CLIENT_ID")
INSTAGRAM_CLIENT_SECRET = os.getenv("INSTAGRAM_CLIENT_SECRET")

IMAGES_FOLDER = "images/"

if not AWS_REGION or not S3_BUCKET_NAME:
    raise ValueError("Missing required env vars: AWS_REGION or S3_BUCKET_NAME")

s3 = boto3.client("s3", region_name=AWS_REGION)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
social_tokens_table = dynamodb.Table("SocialTokens")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def post_with_retry(url, data):
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    resp = requests.post(url, data=data, headers=headers, timeout=20)
    logger.info(f"[IG] POST {url} -> {resp.status_code} {resp.text[:400]}")
    resp.raise_for_status()
    return resp


def get_user_instagram_credentials(user_id: str):
    """
    ✅ Fetch Instagram credentials from DynamoDB.
    Requires SocialTokens PK = user_id.
    Stores & uses instagram_page_access_token for posting.
    """
    try:
        logger.info(f"[INSTAGRAM] Fetch credentials user_id={user_id}")

        resp = social_tokens_table.get_item(Key={"user_id": user_id})
        item = resp.get("Item") or {}

        if not item:
            logger.warning(f"[INSTAGRAM] No SocialTokens record for {user_id}")
            return None

        # ✅ IMPORTANT: Use page token for IG publishing
        page_token = item.get("instagram_page_access_token")
        ig_user_id = item.get("instagram_user_id")

        if not page_token or not ig_user_id:
            logger.warning(f"[INSTAGRAM] Missing instagram_page_access_token or instagram_user_id for {user_id}")
            return None

        # Expiry check (optional)
        expires_at = item.get("instagram_token_expires_at")
        if expires_at:
            try:
                if datetime.utcnow() > datetime.fromisoformat(expires_at):
                    logger.warning(f"[INSTAGRAM] Token expired for {user_id}")
                    return None
            except Exception:
                pass

        return {
            "instagram_user_id": ig_user_id,
            "instagram_page_access_token": page_token,
            "instagram_username": item.get("instagram_username") or "",
            "instagram_page_id": item.get("instagram_page_id") or "",
            "instagram_page_name": item.get("instagram_page_name") or "",
            "instagram_token_expires_at": expires_at or "",
        }

    except Exception as e:
        logger.error(f"[INSTAGRAM] get_user_instagram_credentials error: {e}")
        return None


def load_caption_from_content_details():
    try:
        with open("content_details.json", "r") as f:
            data = json.load(f)
        captions = data.get("captions", {})
        post_caption = captions.get("post_caption", "")
        if post_caption:
            return post_caption

        summary = data.get("summary", [])
        if summary:
            return " ".join(summary) + "\n\n#AI #Innovation #Technology"
        return "🚀 Explore the latest insights in AI! #AI #Innovation #Technology"
    except Exception:
        return "🚀 Explore the latest insights in AI! #AI #Innovation #Technology"


def validate_image_url(img_url):
    try:
        if not (img_url.startswith("https://") and img_url.lower().endswith((".jpg", ".jpeg", ".png"))):
            return False
        r = requests.head(img_url, timeout=10, allow_redirects=True)
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "")
        return ct.startswith("image/")
    except Exception:
        return False


def get_latest_image_set_from_s3(num_images):
    try:
        resp = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix=IMAGES_FOLDER)
        objs = [
            o for o in resp.get("Contents", [])
            if o["Key"] != IMAGES_FOLDER and o["Key"].lower().endswith((".jpg", ".jpeg", ".png"))
        ]
        if not objs:
            return []

        sorted_objs = sorted(objs, key=lambda x: x["LastModified"], reverse=True)
        recent = sorted_objs[: num_images * 2]

        def extract_num(key):
            m = re.search(r"image_(\d+)_", key)
            return int(m.group(1)) if m else 999

        recent_sorted = sorted(recent, key=lambda x: extract_num(x["Key"]))
        selected = recent_sorted[:num_images]

        return [
            f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{o['Key']}"
            for o in selected
        ]
    except Exception as e:
        logger.error(f"[INSTAGRAM] get_latest_image_set_from_s3 error: {e}")
        return []


def clean_instagram_caption(caption):
    if not caption:
        caption = "Check out this AI-generated content! 🚀 #AI #Innovation #Technology"

    max_length = 2000
    cleaned = re.sub(
        r"[^\x00-\x7F\u00A0-\u00FF\u0100-\u017F\u0180-\u024F\u2600-\u27BF\U0001F300-\U0001FAFF#@\n .,!?:;'\"()\-\u2019]",
        "",
        caption,
    )
    cleaned = cleaned.strip()

    if len(cleaned) > max_length:
        cleaned = cleaned[: max_length - 3] + "..."

    if "#" not in cleaned:
        cleaned += " #AI #Innovation #Technology"

    return cleaned


def post_carousel_to_instagram(user_id, image_urls=None, caption="", num_images=1):
    """
    ✅ Dynamic:
    - Reads IG user id + PAGE token from DynamoDB by user_id
    - Uses page token to create media & publish
    """
    try:
        creds = get_user_instagram_credentials(user_id)
        if not creds:
            return {
                "status": "error",
                "message": "Instagram not connected. Please connect Instagram first.",
                "action_required": "connect_instagram",
            }

        instagram_user_id = creds["instagram_user_id"]
        access_token = creds["instagram_page_access_token"]
        username = creds.get("instagram_username") or "your account"

        # num_images sanitize
        try:
            num_images = int(num_images)
        except Exception:
            return {"status": "error", "message": "num_images must be integer"}

        if num_images < 1:
            return {"status": "error", "message": "num_images must be >= 1"}

        if not caption.strip():
            caption = load_caption_from_content_details()

        caption = clean_instagram_caption(caption)

        # Images
        if image_urls and len(image_urls) > 0:
            final_urls = image_urls[:num_images]
        else:
            final_urls = get_latest_image_set_from_s3(num_images)

        if not final_urls:
            return {"status": "error", "message": "No images found to post"}

        # Validate URLs
        valid_urls = [u for u in final_urls if validate_image_url(u)]
        if not valid_urls:
            return {"status": "error", "message": "No valid image URLs after validation"}

        if num_images > 1 and len(valid_urls) < 2:
            return {"status": "error", "message": "Carousel requires at least 2 images"}

        valid_urls = valid_urls[:num_images]
        logger.info(f"[INSTAGRAM] Posting {len(valid_urls)} image(s) to @{username}")

        # SINGLE
        if len(valid_urls) == 1:
            create_url = f"https://graph.facebook.com/v21.0/{instagram_user_id}/media"
            create_resp = post_with_retry(create_url, data={
                "image_url": valid_urls[0],
                "caption": caption,
                "access_token": access_token,
            })
            container_id = (create_resp.json() or {}).get("id")
            if not container_id:
                return {"status": "error", "message": "No container id returned"}

            time.sleep(5)

            publish_url = f"https://graph.facebook.com/v21.0/{instagram_user_id}/media_publish"
            publish_resp = post_with_retry(publish_url, data={
                "creation_id": container_id,
                "access_token": access_token,
            })

            return {
                "status": "success",
                "platform": "instagram",
                "username": username,
                "message": f"Posted single image to @{username}",
                "container_id": container_id,
                "image_url": valid_urls[0],
                "publish_response": publish_resp.json(),
            }

        # CAROUSEL
        children_ids = []
        for idx, url in enumerate(valid_urls, 1):
            create_url = f"https://graph.facebook.com/v21.0/{instagram_user_id}/media"
            resp = post_with_retry(create_url, data={
                "image_url": url,
                "is_carousel_item": "true",
                "access_token": access_token,
            })
            cid = (resp.json() or {}).get("id")
            if not cid:
                return {"status": "error", "message": f"No container id for carousel item {idx}"}
            children_ids.append(str(cid))
            if idx < len(valid_urls):
                time.sleep(3)

        time.sleep(5)

        carousel_create_url = f"https://graph.facebook.com/v21.0/{instagram_user_id}/media"
        carousel_resp = post_with_retry(carousel_create_url, data={
            "media_type": "CAROUSEL",
            "caption": caption,
            "children": ",".join(children_ids),
            "access_token": access_token,
        })

        carousel_container_id = (carousel_resp.json() or {}).get("id")
        if not carousel_container_id:
            return {"status": "error", "message": "No carousel container id returned"}

        time.sleep(5)

        publish_url = f"https://graph.facebook.com/v21.0/{instagram_user_id}/media_publish"
        publish_resp = post_with_retry(publish_url, data={
            "creation_id": carousel_container_id,
            "access_token": access_token,
        })

        return {
            "status": "success",
            "platform": "instagram",
            "username": username,
            "message": f"Posted carousel ({len(children_ids)} images) to @{username}",
            "carousel_container_id": carousel_container_id,
            "children_ids": children_ids,
            "image_urls": valid_urls,
            "publish_response": publish_resp.json(),
        }

    except requests.exceptions.HTTPError as e:
        msg = f"Instagram API error: {str(e)}"
        if getattr(e, "response", None) is not None:
            msg += f" | {e.response.text}"
        return {"status": "error", "message": msg}

    except Exception as e:
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}


def post_image_to_instagram(user_id, image_url, caption=""):
    return post_carousel_to_instagram(
        user_id=user_id,
        image_urls=[image_url] if image_url else None,
        caption=caption,
        num_images=1,
    )
