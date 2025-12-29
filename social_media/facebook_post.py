import os
import re
import json
import logging
from typing import List, Optional, Tuple

import boto3
import requests
from dotenv import load_dotenv

load_dotenv()

# --- Env ---
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID") or os.getenv("PAGE_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN") or os.getenv("PAGE_ACCESS_TOKEN")

if not FACEBOOK_PAGE_ID or not FACEBOOK_PAGE_ACCESS_TOKEN:
    logging.warning("⚠️ FACEBOOK_PAGE_ID or FACEBOOK_PAGE_ACCESS_TOKEN not set. Facebook posting will fail.")

s3 = boto3.client("s3", region_name=AWS_REGION)

GRAPH_API_BASE = "https://graph.facebook.com/v18.0"

# ---------- Helpers ----------
def _extract_image_number(key_or_url: str) -> int:
    """
    Pulls the number from patterns like 'image_1_abcd.png' so we can order correctly.
    If no number is found, return a high sentinel so it goes to the end.
    """
    m = re.search(r"image_(\d+)_", key_or_url)
    if not m:
        m = re.search(r"image-(\d+)-", key_or_url)  # secondary pattern, just in case
    return int(m.group(1)) if m else 999999

def _sort_image_urls_by_number(urls: List[str]) -> List[str]:
    return sorted(urls, key=_extract_image_number)

def _s3_url(key: str) -> str:
    # Regional S3 URL (matches your other modules)
    return f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{key}"

def _get_latest_generated_images_from_s3(num_images: int) -> List[str]:
    """
    Fetch the most recently uploaded images from s3://{bucket}/images/, then
    re-order them by image number so 'image_1_' posts first, 'image_2_' second, etc.
    """
    try:
        resp = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix="images/")
        if "Contents" not in resp:
            logging.error("No 'Contents' in S3 list_objects_v2 response.")
            return []

        image_objs = [
            obj for obj in resp["Contents"]
            if obj["Key"] != "images/" and obj["Key"].lower().endswith((".jpg", ".jpeg", ".png"))
        ]

        if not image_objs:
            logging.error("No images found in s3://%s/images/ folder.", S3_BUCKET_NAME)
            return []

        # Sort by LastModified desc to get latest generated set
        image_objs = sorted(image_objs, key=lambda x: x["LastModified"], reverse=True)[:num_images]

        # Now order by image number so 'image_1_' comes before 'image_2_'
        image_objs = sorted(image_objs, key=lambda x: _extract_image_number(x["Key"]))

        urls = [_s3_url(o["Key"]) for o in image_objs]
        logging.info("✅ Latest S3 images for Facebook: %s", [o["Key"] for o in image_objs])
        return urls

    except Exception as e:
        logging.exception("Failed to fetch images from S3: %s", str(e))
        return []

def _get_post_caption_from_content_details() -> str:
    """
    Pull post caption from content_details.json (priority: captions.post_caption).
    Fallback to a generic line if not found.
    """
    try:
        with open("content_details.json", "r", encoding="utf-8") as f:
            content = json.load(f)

        captions = content.get("captions", {})
        if isinstance(captions, dict) and "post_caption" in captions:
            cap = captions["post_caption"]
            if isinstance(cap, str) and cap.strip():
                return cap.strip()

        # Secondary fallback
        if "post_caption" in content and isinstance(content["post_caption"], str):
            return content["post_caption"].strip()

        # Tertiary fallback: long paragraph from captions dict (first long one)
        for _, v in captions.items():
            if isinstance(v, list) and v:
                if isinstance(v[0], str) and len(v[0]) > 100:
                    return v[0].strip()

        # Final fallback
        return "AI-powered content automation in action! #AI #Technology #Innovation"
    except Exception as e:
        logging.warning("Could not read caption from content_details.json: %s", str(e))
        return "AI-powered content automation in action! #AI #Technology #Innovation"

def _create_media_fbid(image_url: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Upload a photo to the page as unpublished (published=false) to obtain a media_fbid.
    Returns (success, media_fbid, error_message)
    """
    try:
        url = f"{GRAPH_API_BASE}/{FACEBOOK_PAGE_ID}/photos"
        data = {
            "url": image_url,
            "published": "false",
            "access_token": FACEBOOK_PAGE_ACCESS_TOKEN,
        }
        r = requests.post(url, data=data, timeout=60)
        if r.status_code == 200:
            j = r.json()
            media_fbid = j.get("id")
            if media_fbid:
                return True, media_fbid, None
            return False, None, f"Missing media_fbid in response: {j}"
        return False, None, f"HTTP {r.status_code}: {r.text}"
    except Exception as e:
        return False, None, f"Exception while creating media fbid: {str(e)}"

def _create_feed_post_with_media(media_fbids: List[str], caption: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Create a Page feed post using multiple media objects (carousel-style in a single post).
    Returns (success, post_id, error_message)
    """
    try:
        url = f"{GRAPH_API_BASE}/{FACEBOOK_PAGE_ID}/feed"
        attached_media = [{"media_fbid": fbid} for fbid in media_fbids]

        data = {
            "message": caption,
            "access_token": FACEBOOK_PAGE_ACCESS_TOKEN,
        }
        # attached_media needs to be passed as attached_media[0], attached_media[1], ...
        files = {}
        for idx, item in enumerate(attached_media):
            data[f"attached_media[{idx}]"] = json.dumps(item)

        r = requests.post(url, data=data, files=files, timeout=60)
        if r.status_code == 200:
            j = r.json()
            post_id = j.get("id")
            if post_id:
                return True, post_id, None
            return False, None, f"Missing post_id in response: {j}"
        return False, None, f"HTTP {r.status_code}: {r.text}"
    except Exception as e:
        return False, None, f"Exception while creating feed post: {str(e)}"

# ---------- Public API ----------
def post_images_to_facebook(
    image_urls: Optional[List[str]] = None,
    caption: Optional[str] = None,
    num_images: int = 1
) -> dict:
    """
    Posts 1..N images to a single Facebook Page post.
    - If image_urls is None or empty, fetch the latest from s3://{bucket}/images/
    - Caption defaults to content_details.json's captions.post_caption
    - For 1 image: direct /photos with message (published=true)
    - For >1 images: create unpublished photos to get media_fbids, then post /feed with attached_media[]

    Returns dict with status, details, and IDs.
    """
    try:
        if not FACEBOOK_PAGE_ID or not FACEBOOK_PAGE_ACCESS_TOKEN:
            return {"status": "error", "message": "FACEBOOK_PAGE_ID or FACEBOOK_PAGE_ACCESS_TOKEN is not configured"}

        # Prepare images
        urls = image_urls or _get_latest_generated_images_from_s3(num_images)
        if not urls:
            return {"status": "error", "message": "No images available to post"}
        # keep user-intended order by number (image_1_, image_2_, ...)
        urls = _sort_image_urls_by_number(urls)[:max(1, int(num_images))]

        # Prepare caption
        message = caption if (isinstance(caption, str) and caption.strip()) else _get_post_caption_from_content_details()

        if len(urls) == 1:
            # Single-image post to /photos (published)
            url = f"{GRAPH_API_BASE}/{FACEBOOK_PAGE_ID}/photos"
            data = {
                "url": urls[0],
                "message": message,
                "published": "true",
                "access_token": FACEBOOK_PAGE_ACCESS_TOKEN,
            }
            r = requests.post(url, data=data, timeout=60)
            if r.status_code == 200:
                j = r.json()
                photo_id = j.get("id")
                post_url = f"https://facebook.com/{photo_id}" if photo_id else None
                return {"status": "success", "type": "single", "photo_id": photo_id, "post_url": post_url}
            return {"status": "error", "message": f"HTTP {r.status_code}: {r.text}"}

        # Multi-image: create unpublished photos -> collect media_fbids -> post feed with attached_media
        fbids = []
        errors = []
        for u in urls:
            ok, fbid, err = _create_media_fbid(u)
            if ok and fbid:
                fbids.append(fbid)
            else:
                errors.append({"image_url": u, "error": err})
        if not fbids:
            return {"status": "error", "message": "Failed to create any media objects", "details": errors}

        ok, post_id, err = _create_feed_post_with_media(fbids, message)
        if not ok:
            return {"status": "error", "message": err or "Failed to create feed post", "details": errors}

        return {
            "status": "success",
            "type": "multi",
            "post_id": post_id,
            "attached_media_count": len(fbids),
            "errors": errors or None,
            "post_url": f"https://facebook.com/{post_id}" if post_id else None,
        }

    except Exception as e:
        logging.exception("Facebook posting failed: %s", str(e))
        return {"status": "error", "message": str(e)}





# if __name__ == "__main__":
#     import argparse
#     import sys

#     # Verbose logs for quick debugging
#     logging.basicConfig(
#         level=logging.INFO,
#         format="%(asctime)s - %(levelname)s - %(message)s"
#     )

#     # Quick sanity checks
#     if not AWS_REGION or not S3_BUCKET_NAME:
#         logging.error("AWS_REGION or S3_BUCKET_NAME missing. Check your .env")
#         sys.exit(1)
#     if not FACEBOOK_PAGE_ID or not FACEBOOK_PAGE_ACCESS_TOKEN:
#         logging.error("FACEBOOK_PAGE_ID or FACEBOOK_PAGE_ACCESS_TOKEN missing. Check your .env")
#         sys.exit(1)

#     # CLI arguments: python this_file.py --num 2 --caption "optional caption"
#     parser = argparse.ArgumentParser(description="Test Facebook multi-image posting from latest S3 images.")
#     parser.add_argument("--num", dest="num_images", type=int, default=int(os.getenv("TEST_FB_NUM_IMAGES", "2")),
#                         help="How many images to post (default: 2)")
#     parser.add_argument("--caption", dest="caption", type=str, default=None,
#                         help="Optional caption override")
#     parser.add_argument("--use-s3-latest", action="store_true",
#                         help="Force fetching latest images from S3 (default behavior)")
#     args = parser.parse_args()

#     # Fetch which images we’re about to use (for visibility before posting)
#     # This respects your image-number ordering (image_1_ first, image_2_ next, etc.)
#     candidate_urls = _get_latest_generated_images_from_s3(args.num_images)
#     candidate_urls = _sort_image_urls_by_number(candidate_urls)[:max(1, args.num_images)]
#     logging.info("🧪 Candidate images to post (in order): %s", candidate_urls)

#     # Kick off the post (passing image_urls is optional — your function can fetch itself)
#     result = post_images_to_facebook(
#         image_urls=candidate_urls,  # or None to let it fetch again internally
#         caption=args.caption,       # or None to auto-pull from content_details.json
#         num_images=args.num_images
#     )

#     # Pretty print result
#     print(json.dumps(result, indent=2, ensure_ascii=False))

#     # Helpful hints on common failures
#     if result.get("status") != "success":
#         logging.warning("❗Post failed. Common causes:")
#         logging.warning(" - Missing/invalid Page token (must be a PAGE token with pages_manage_posts).")
#         logging.warning(" - App not in a role with access (Dev Mode only works for admins/developers/testers).")
#         logging.warning(" - Images not publicly reachable (check S3 object ACL and URL).")
#         logging.warning(" - Wrong Graph API version or endpoint shape.")
