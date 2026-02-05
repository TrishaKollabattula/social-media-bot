# social_media/linkedin_post.py

"""
LinkedIn Poster (FULLY FIXED)

✅ DynamoDB credentials:
   Table: SocialConnections
   PK: user_id
   SK: sk = "platform#linkedin"

✅ Posting rule (your requirement):
   - If requested_images == 1  -> post IMAGE (ignore PDF)
   - If requested_images >= 2  -> post PDF (ignore images)

✅ Fixes:
   - Backward compatible: accepts s3_url=... (no TypeError)
   - Accepts direct media via args:
       media_urls=[img, pdf], image_url=..., pdf_url=..., all_urls=[...]
   - Does NOT depend on filtered_urls_for_social_media (works even if empty)
   - If requested_images missing -> infer from provided URLs (count image URLs)
   - Extracts LinkedIn Post ID reliably (x-linkedin-id OR x-restli-id OR location OR JSON)
"""

import os
import json
import logging
from typing import Optional, Dict, Any, Tuple, List, Any as AnyType

import boto3
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ----------------------------
# Env / Constants
# ----------------------------
API_VERSION = os.getenv("LINKEDIN_API_VERSION", "202507")
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")

S3_BUCKET_NAME = (
    os.getenv("S3_BUCKET_NAME")
    or os.getenv("MARKETING_S3_BUCKET")
    or os.getenv("S3_BUCKET")
)

DYNAMODB_TABLE_NAME = os.getenv("SOCIAL_DDB_TABLE", "SocialConnections")
HUBSPOT_API_URL = os.getenv("HUBSPOT_API_URL")

LINKEDIN_SK = "platform#linkedin"

# AWS clients
s3 = boto3.client("s3", region_name=AWS_REGION)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMODB_TABLE_NAME)


# ----------------------------
# Helpers
# ----------------------------
def _strip_q(url: str) -> str:
    return (url or "").strip().split("?")[0]


def _is_image_url(url: str) -> bool:
    u = _strip_q(url).lower()
    return u.endswith((".png", ".jpg", ".jpeg", ".webp"))


def _is_pdf_url(url: str) -> bool:
    u = _strip_q(url).lower()
    return u.endswith(".pdf")


def _is_image_key(key: str) -> bool:
    k = (key or "").lower()
    return k.endswith((".png", ".jpg", ".jpeg", ".webp"))


def _s3_https_url(bucket: str, region: str, key: str) -> str:
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


def _clean_urls(v: AnyType) -> List[str]:
    if not v:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return []
    out: List[str] = []
    for x in v:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    return out


def _pick_first(urls: List[str], predicate) -> Optional[str]:
    for u in urls:
        if predicate(u):
            return u
    return None


def _count_images_in_urls(urls: List[str]) -> int:
    return sum(1 for u in urls if _is_image_url(u))


def _extract_post_id_from_response(resp: requests.Response) -> Optional[str]:
    """
    LinkedIn may return ID in:
      - headers: x-linkedin-id
      - headers: x-restli-id
      - headers: location (contains URN/id)
      - JSON body: {"id": "..."} or {"value": {"id": "..."}}
    """
    try:
        # headers are case-insensitive
        post_id = resp.headers.get("x-linkedin-id") or resp.headers.get("x-restli-id")
        if post_id and str(post_id).strip():
            return str(post_id).strip()

        loc = resp.headers.get("location")
        if loc and loc.strip():
            # often ends with the id/urn
            return loc.strip().rstrip("/").split("/")[-1]

        # try JSON
        try:
            j = resp.json()
        except Exception:
            j = None

        if isinstance(j, dict):
            if isinstance(j.get("id"), str) and j["id"].strip():
                return j["id"].strip()
            val = j.get("value")
            if isinstance(val, dict) and isinstance(val.get("id"), str) and val["id"].strip():
                return val["id"].strip()

    except Exception:
        pass

    return None


class LinkedInPoster:
    def __init__(self):
        self.api_version = API_VERSION

    # ----------------------------
    # DynamoDB: fetch LinkedIn creds
    # ----------------------------
    def get_user_linkedin_credentials(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            logging.info(f"🔍 Fetching LinkedIn credentials for user: {user_id} (table={DYNAMODB_TABLE_NAME})")
            response = table.get_item(Key={"user_id": user_id, "sk": LINKEDIN_SK})

            if "Item" not in response:
                logging.warning(f"⚠️ No LinkedIn credentials found for user: {user_id}")
                return None

            item = response["Item"]
            creds = {
                "access_token": item.get("access_token"),
                "person_urn": item.get("person_urn") or item.get("preferred_urn"),
                "org_urn": item.get("org_urn"),
                "has_org_access": bool(item.get("has_org_access", False)),
                "connected_at": item.get("connected_at"),
                "user_id": user_id,
            }

            if not creds["access_token"]:
                logging.error("❌ Missing access_token")
                return None

            if not creds["person_urn"] and not creds["org_urn"]:
                logging.error("❌ Missing both person_urn and org_urn")
                return None

            return creds

        except Exception as e:
            import traceback
            logging.error(f"❌ Error fetching LinkedIn credentials: {e}")
            logging.error(traceback.format_exc())
            return None

    def _get_posting_target(self, creds: Dict[str, Any]) -> Tuple[Optional[str], str]:
        if creds.get("has_org_access") and creds.get("org_urn"):
            return creds["org_urn"], "organization page"
        if creds.get("person_urn"):
            return creds["person_urn"], "personal profile"
        return None, "unknown"

    # ----------------------------
    # content_details.json parsing
    # ----------------------------
    def load_job_meta(self, path: str) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _extract_job_id(self, meta: Dict[str, Any]) -> Optional[str]:
        for k in ("job_id", "jobId", "run_id", "runId", "request_id", "requestId"):
            v = meta.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    def _count_requested_images_from_meta(self, meta: Dict[str, Any]) -> Optional[int]:
        for k in ("requested_images", "num_images", "image_count", "requestedImageCount"):
            v = meta.get(k)
            if isinstance(v, int) and v >= 0:
                return v
        return None

    def _extract_urls_from_meta(self, meta: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], List[str]]:
        urls: List[str] = []
        urls += _clean_urls(meta.get("image_urls"))
        urls += _clean_urls(meta.get("all_urls"))
        urls += _clean_urls(meta.get("pdf_url"))
        urls += _clean_urls(meta.get("pdf_urls"))
        urls += _clean_urls(meta.get("images"))
        urls += _clean_urls(meta.get("final_images"))

        img = _pick_first(urls, _is_image_url)
        pdf = _pick_first(urls, _is_pdf_url)
        return img, pdf, urls

    # ----------------------------
    # Optional S3 lookup by job_id (only if your key names contain job_id)
    # ----------------------------
    def _find_job_pdf_key(self, job_id: str) -> Optional[str]:
        if not S3_BUCKET_NAME:
            return None
        try:
            resp = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix="pdfs/")
            contents = resp.get("Contents", []) or []
            matches = [
                o for o in contents
                if o.get("Key", "").lower().endswith(".pdf") and job_id in o.get("Key", "")
            ]
            if not matches:
                return None
            return sorted(matches, key=lambda x: x["LastModified"], reverse=True)[0]["Key"]
        except Exception:
            return None

    def _find_job_image_key(self, job_id: str) -> Optional[str]:
        if not S3_BUCKET_NAME:
            return None
        try:
            resp = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix="images/")
            contents = resp.get("Contents", []) or []
            matches = [
                o for o in contents
                if _is_image_key(o.get("Key", "")) and job_id in o.get("Key", "")
            ]
            if not matches:
                return None
            return sorted(matches, key=lambda x: x["LastModified"], reverse=True)[0]["Key"]
        except Exception:
            return None

    def get_job_media_from_s3(self, job_id: str) -> Tuple[Optional[str], Optional[str]]:
        if not job_id:
            return None, None
        pdf_key = self._find_job_pdf_key(job_id)
        img_key = self._find_job_image_key(job_id)
        pdf_url = _s3_https_url(S3_BUCKET_NAME, AWS_REGION, pdf_key) if (S3_BUCKET_NAME and pdf_key) else None
        img_url = _s3_https_url(S3_BUCKET_NAME, AWS_REGION, img_key) if (S3_BUCKET_NAME and img_key) else None
        return img_url, pdf_url

    # ----------------------------
    # Caption
    # ----------------------------
    def load_caption_from_content_details(self, path: str) -> str:
        try:
            meta = self.load_job_meta(path)
            captions = meta.get("captions") or {}
            post_caption = captions.get("post_caption")
            if isinstance(post_caption, str) and post_caption.strip():
                return post_caption.strip()
            if isinstance(meta.get("caption"), str) and meta["caption"].strip():
                return meta["caption"].strip()
        except Exception:
            pass
        return "Check out our latest content! 🚀 #AI #Marketing"

    # ----------------------------
    # LinkedIn: PDF posting
    # ----------------------------
    def post_pdf_to_linkedin(self, pdf_url: str, caption: str, creds: Dict[str, Any]) -> Tuple[bool, str]:
        access_token = creds["access_token"]
        posting_urn, target_label = self._get_posting_target(creds)
        if not posting_urn:
            return False, "No valid URN found for posting"

        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "LinkedIn-Version": self.api_version,
                "X-Restli-Protocol-Version": "2.0.0",
                "Content-Type": "application/json",
            }

            init_url = "https://api.linkedin.com/rest/documents?action=initializeUpload"
            init_payload = {"initializeUploadRequest": {"owner": posting_urn}}
            init_resp = requests.post(init_url, headers=headers, json=init_payload, timeout=30)
            if init_resp.status_code != 200:
                return False, f"Failed to initialize PDF upload: {init_resp.status_code} - {init_resp.text}"

            j = init_resp.json() or {}
            upload_url = j["value"]["uploadUrl"]
            doc_urn = j["value"]["document"]

            pdf_resp = requests.get(pdf_url, timeout=90)
            if pdf_resp.status_code != 200:
                return False, f"Failed to download PDF ({pdf_resp.status_code})"

            up_resp = requests.put(
                upload_url,
                headers={"Authorization": f"Bearer {access_token}"},
                data=pdf_resp.content,
                timeout=180,
            )
            if up_resp.status_code not in (200, 201):
                return False, f"Failed to upload PDF: {up_resp.status_code} - {up_resp.text}"

            post_url = "https://api.linkedin.com/rest/posts"
            filename = os.path.basename(_strip_q(pdf_url))

            post_payload = {
                "author": posting_urn,
                "commentary": caption,
                "visibility": "PUBLIC",
                "distribution": {"feedDistribution": "MAIN_FEED"},
                "content": {"media": {"title": filename, "id": doc_urn}},
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            }

            post_resp = requests.post(post_url, headers=headers, json=post_payload, timeout=30)
            if post_resp.status_code == 201:
                post_id = _extract_post_id_from_response(post_resp)
                return True, f"✅ Posted PDF to LinkedIn ({target_label}). Post ID: {post_id}"

            return False, f"Failed to create PDF post: {post_resp.status_code} - {post_resp.text}"

        except Exception as e:
            return False, f"❌ PDF post error: {str(e)}"

    # ----------------------------
    # LinkedIn: IMAGE posting
    # ----------------------------
    def post_image_to_linkedin(self, image_url: str, caption: str, creds: Dict[str, Any]) -> Tuple[bool, str]:
        access_token = creds["access_token"]
        posting_urn, target_label = self._get_posting_target(creds)
        if not posting_urn:
            return False, "No valid URN found for posting"

        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "LinkedIn-Version": self.api_version,
                "X-Restli-Protocol-Version": "2.0.0",
                "Content-Type": "application/json",
            }

            init_url = "https://api.linkedin.com/rest/images?action=initializeUpload"
            init_payload = {"initializeUploadRequest": {"owner": posting_urn}}
            init_resp = requests.post(init_url, headers=headers, json=init_payload, timeout=30)
            if init_resp.status_code != 200:
                return False, f"Failed to initialize image upload: {init_resp.status_code} - {init_resp.text}"

            j = init_resp.json() or {}
            upload_url = j["value"]["uploadUrl"]
            image_urn = j["value"]["image"]

            img_resp = requests.get(image_url, timeout=90)
            if img_resp.status_code != 200:
                return False, f"Failed to download image ({img_resp.status_code})"

            up_resp = requests.put(
                upload_url,
                headers={"Authorization": f"Bearer {access_token}"},
                data=img_resp.content,
                timeout=180,
            )
            if up_resp.status_code not in (200, 201):
                return False, f"Failed to upload image: {up_resp.status_code} - {up_resp.text}"

            post_url = "https://api.linkedin.com/rest/posts"
            filename = os.path.basename(_strip_q(image_url))

            post_payload = {
                "author": posting_urn,
                "commentary": caption,
                "visibility": "PUBLIC",
                "distribution": {"feedDistribution": "MAIN_FEED"},
                "content": {"media": {"id": image_urn, "title": filename}},
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            }

            post_resp = requests.post(post_url, headers=headers, json=post_payload, timeout=30)
            if post_resp.status_code == 201:
                post_id = _extract_post_id_from_response(post_resp)
                return True, f"✅ Posted IMAGE to LinkedIn ({target_label}). Post ID: {post_id}"

            return False, f"Failed to create image post: {post_resp.status_code} - {post_resp.text}"

        except Exception as e:
            return False, f"❌ Image post error: {str(e)}"

    # ----------------------------
    # Main entry (decision logic)
    # ----------------------------
    def post_content_to_linkedin_for_user(
        self,
        user_id: str,
        job_id: Optional[str] = None,
        requested_images: Optional[int] = None,
        caption: Optional[str] = None,
        content_details_path: str = "content_details.json",
        # Backward compat
        s3_url: Optional[str] = None,
        # NEW: direct media
        image_url: Optional[str] = None,
        pdf_url: Optional[str] = None,
        media_urls: Optional[List[str]] = None,
        all_urls: Optional[List[str]] = None,
        **kwargs,
    ) -> Tuple[bool, str]:
        creds = self.get_user_linkedin_credentials(user_id)
        if not creds:
            return False, f"❌ Could not retrieve LinkedIn credentials for user: {user_id}. Connect LinkedIn in UI."

        if not caption or not caption.strip():
            caption = self.load_caption_from_content_details(content_details_path)

        # 1) Collect direct args
        collected: List[str] = []
        collected += _clean_urls(media_urls)
        collected += _clean_urls(all_urls)
        if image_url:
            collected.append(image_url.strip())
        if pdf_url:
            collected.append(pdf_url.strip())
        if s3_url:
            collected.append(s3_url.strip())

        arg_img = _pick_first(collected, _is_image_url)
        arg_pdf = _pick_first(collected, _is_pdf_url)

        # ✅ If requested_images missing, infer from provided URLs FIRST
        if requested_images is None and collected:
            inferred = _count_images_in_urls(collected)
            if inferred > 0:
                requested_images = inferred

        # 2) If still missing, read meta file
        meta_img = meta_pdf = None
        meta_job_id = None
        if not arg_img and not arg_pdf:
            meta = self.load_job_meta(content_details_path)
            meta_job_id = self._extract_job_id(meta)
            if requested_images is None:
                requested_images = self._count_requested_images_from_meta(meta)
            meta_img, meta_pdf, meta_urls = self._extract_urls_from_meta(meta)

            # if still None, infer from meta urls
            if requested_images is None and meta_urls:
                inferred = _count_images_in_urls(meta_urls)
                if inferred > 0:
                    requested_images = inferred

        # 3) Optional S3 lookup by job_id (only works if keys include job_id)
        s3_img = s3_pdf = None
        effective_job_id = job_id or meta_job_id
        if effective_job_id and (not (arg_img or meta_img) or not (arg_pdf or meta_pdf)):
            s3_img, s3_pdf = self.get_job_media_from_s3(effective_job_id)

        final_img = arg_img or meta_img or s3_img
        final_pdf = arg_pdf or meta_pdf or s3_pdf

        if not final_img and not final_pdf:
            return False, "❌ Image generation failed, try again"

        logging.info(f"🎯 Decision input: requested_images={requested_images}, has_img={bool(final_img)}, has_pdf={bool(final_pdf)}")

        # RULE 1: Single image request -> POST IMAGE ONLY
        if requested_images == 1:
            if not final_img:
                return False, "❌ Image generation failed, try again"
            logging.info(f"📸 Posting IMAGE (requested_images=1): {final_img}")
            return self.post_image_to_linkedin(final_img, caption, creds)

        # RULE 2: Multiple images -> POST PDF ONLY
        if isinstance(requested_images, int) and requested_images >= 2:
            if not final_pdf:
                return False, "❌ Image generation failed, try again"
            logging.info(f"📄 Posting PDF (requested_images={requested_images}): {final_pdf}")
            return self.post_pdf_to_linkedin(final_pdf, caption, creds)

        # RULE 3: Unknown -> safest fallback
        if final_pdf:
            logging.info(f"📄 Posting PDF (fallback): {final_pdf}")
            return self.post_pdf_to_linkedin(final_pdf, caption, creds)
        return self.post_image_to_linkedin(final_img, caption, creds)


linkedin_poster = LinkedInPoster()


def post_to_linkedin_for_user(
    user_id: str,
    job_id: Optional[str] = None,
    requested_images: Optional[int] = None,
    caption: Optional[str] = None,
    content_details_path: str = "content_details.json",
    s3_url: Optional[str] = None,
    image_url: Optional[str] = None,
    pdf_url: Optional[str] = None,
    media_urls: Optional[List[str]] = None,
    all_urls: Optional[List[str]] = None,
    **kwargs,
) -> Tuple[bool, str]:
    return linkedin_poster.post_content_to_linkedin_for_user(
        user_id=user_id,
        job_id=job_id,
        requested_images=requested_images,
        caption=caption,
        content_details_path=content_details_path,
        s3_url=s3_url,
        image_url=image_url,
        pdf_url=pdf_url,
        media_urls=media_urls,
        all_urls=all_urls,
        **kwargs,
    )
