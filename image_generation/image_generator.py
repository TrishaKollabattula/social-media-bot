# image_generation/image_generator.py - FINAL UPDATED
"""
Key Guarantees:
✅ COPY LOCK: copy extracted once; never changed on regen
✅ status file freshness (prevents reading old/partial json)
✅ subprocess cleanup (terminate/kill) -> no zombie processes
✅ download correctness checks (ext/size/recentness)
✅ DOWNLOAD retries (common flake fix)
✅ SMART REGEN: A/B/C/D enforced + fast-target behavior
✅ overlays user's logo (from S3 logos/) onto the downloaded image BEFORE uploading
✅ when score reaches threshold (9.5), do ONE FINAL image generation (NO eval) ONLY for download, then download

NEW IN THIS VERSION (your requests):
✅ Controlled visual diversity across slides (2/3/4/5) while staying on-topic (composition/lighting/background tweaks only)
✅ Convert all final images into ONE PDF at the end and upload to S3 "pdfs/" folder
✅ Delete local downloaded images after successful S3 upload (keeps server clean)

Expected run.py flags used by this file:
- --url
- --goal or --goal-file
- --mode attach
- --wait_for_image
- --download_only
"""

from __future__ import annotations

import os
import time
import uuid
import json
import re
import logging
import traceback
import subprocess
import hashlib
from io import BytesIO
from typing import List, Dict, Any, Optional, Tuple

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# Pillow for logo overlay + PDF creation
from PIL import Image, ImageFilter  # pip: pillow

load_dotenv()

logger = logging.getLogger("imagegen")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

# =========================================================================================
# ENV CONFIG
# =========================================================================================
AWS_REGION = (os.getenv("AWS_REGION") or "ap-south-1").strip()
S3_BUCKET_NAME = (os.getenv("S3_BUCKET_NAME") or "").strip()
AUTOMATION_AGENT_DIR = (os.getenv("AUTOMATION_AGENT_DIR") or "").strip()

IMG_MAX_ITERS = int(os.getenv("IMG_MAX_ITERS", "10"))
IMG_FAST_TARGET_ITERS = int(os.getenv("IMG_FAST_TARGET_ITERS", "4"))

# ✅ Force threshold default to 9.5 (override via .env if needed)
IMG_SCORE_THRESHOLD = float(os.getenv("IMG_SCORE_THRESHOLD", "9.5"))

IMG_MAX_TIME_SEC = int(os.getenv("IMG_MAX_TIME_SEC", "1800"))
IMG_PATIENCE = int(os.getenv("IMG_PATIENCE", "8"))

S3_IMAGE_PREFIX = (os.getenv("S3_IMAGE_PREFIX", "images") or "images").strip().strip("/")
S3_LOGO_PREFIX = (os.getenv("S3_LOGO_PREFIX", "logos") or "logos").strip().strip("/")
S3_PDF_PREFIX = (os.getenv("S3_PDF_PREFIX", "pdfs") or "pdfs").strip().strip("/")  # ✅ NEW

S3_PUBLIC_READ = str(os.getenv("S3_PUBLIC_READ", "false")).lower() == "true"
S3_CDN_BASE_URL = (os.getenv("S3_CDN_BASE_URL", "") or "").strip().rstrip("/")

STEP_STATUS_FILE = "step_status.json"

TEXT_TIMEOUT_DEFAULT = int(os.getenv("AGENT_TEXT_TIMEOUT", "220"))
EVAL_TIMEOUT_DEFAULT = int(os.getenv("AGENT_EVAL_TIMEOUT", "240"))
IMAGE_TIMEOUT_DEFAULT = int(os.getenv("AGENT_IMAGE_TIMEOUT", "900"))
DOWNLOAD_TIMEOUT_DEFAULT = int(os.getenv("AGENT_DL_TIMEOUT", "240"))

STATUS_POLL_SLEEP = float(os.getenv("AGENT_STATUS_POLL_SLEEP", "0.15"))
STATUS_CHANGE_SETTLE = float(os.getenv("AGENT_STATUS_SETTLE_SLEEP", "0.10"))

# After image generation, let UI settle a bit so "latest image" is truly latest
POST_IMAGE_SETTLE_SEC = float(os.getenv("AGENT_POST_IMAGE_SETTLE_SEC", "1.5"))

AGENT_LOG_DIR = os.getenv("AGENT_LOG_DIR", "") or os.path.join(os.getcwd(), "agent_logs")
os.makedirs(AGENT_LOG_DIR, exist_ok=True)

GOAL_FILES_DIR = os.path.join(os.getcwd(), "agent_goal_files")
os.makedirs(GOAL_FILES_DIR, exist_ok=True)

DOWNLOAD_MIN_BYTES = int(os.getenv("DOWNLOAD_MIN_BYTES", "50000"))  # 50KB default safety

# Download retry
DOWNLOAD_RETRIES = int(os.getenv("DOWNLOAD_RETRIES", "3"))
DOWNLOAD_RETRY_SLEEP = float(os.getenv("DOWNLOAD_RETRY_SLEEP", "1.25"))
DOWNLOAD_RETRY_TIMEOUT_BUMP = int(os.getenv("DOWNLOAD_RETRY_TIMEOUT_BUMP", "60"))

# Logo overlay controls
LOGO_ENABLED = str(os.getenv("LOGO_ENABLED", "true")).lower() == "true"
LOGO_MAX_W = int(os.getenv("LOGO_MAX_W", "190"))          # px in 1080x1350
LOGO_MAX_H = int(os.getenv("LOGO_MAX_H", "120"))          # px
LOGO_PADDING = int(os.getenv("LOGO_PADDING", "46"))       # px from edges
LOGO_OPACITY = float(os.getenv("LOGO_OPACITY", "0.98"))   # 0..1
LOGO_MIN_ALPHA = int(os.getenv("LOGO_MIN_ALPHA", "20"))   # suppress very faint pixels

# =========================================================================================
# DIVERSITY (NEW)
# =========================================================================================

def _diversity_seed(idx: int, theme: str, company: str) -> str:
    """
    Deterministic seed: makes slide 2/3/4/5 prompts slightly different but stable across runs.
    """
    base = f"{company}|{theme}|slide:{idx}"
    h = hashlib.md5(base.encode("utf-8")).hexdigest()[:10]
    safe = re.sub(r"[^a-zA-Z0-9:\-|_]", "", base)[:50]
    return f"{safe}|{h}"

def _diversity_direction_for_slide(idx: int) -> str:
    """
    Strong, VISIBLY distinct presets.
    Each slide must use a DIFFERENT scene type + composition archetype.
    """
    presets = [
        # Slide 1: Exterior hero (ok)
        "PRESET 1 (EXTERIOR HERO): Wide establishing shot of salon exterior, clean premium facade, sky gradient, minimal text overlay, strong brand presence.",

        # Slide 2: Interior/lobby vibe (visibly different)
        "PRESET 2 (INTERIOR PREMIUM): Inside salon shot (reception / waiting lounge), warm premium lighting, mirrors, chairs, minimal decor, NO exterior building focus.",

        # Slide 3: Human + service (visibly different)
        "PRESET 3 (SERVICE MOMENT): Close-up haircut/styling moment (hands + tools), shallow depth-of-field, premium editorial photography, background softly blurred.",

        # Slide 4: Detail + product/tools (visibly different)
        "PRESET 4 (DETAIL STILL LIFE): Flat-lay or countertop still life (scissors, comb, towel, hair products), clean marble/wood texture, luxury minimal aesthetic.",

        # Slide 5: Abstract brand poster (visibly different)
        "PRESET 5 (ABSTRACT BRAND POSTER): No real scene. Use premium abstract gradients/shapes, subtle texture, brand colors, big typography-led design, minimal icons."
    ]
    return presets[(idx - 1) % len(presets)]


# =========================================================================================
# AWS INIT
# =========================================================================================
s3 = None
dynamodb = None
user_survey_table = None

try:
    if not S3_BUCKET_NAME:
        raise RuntimeError("S3_BUCKET_NAME is empty. Set it in .env")

    s3 = boto3.client("s3", region_name=AWS_REGION)
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    user_survey_table = dynamodb.Table("UserSurveyData")

    try:
        s3.head_bucket(Bucket=S3_BUCKET_NAME)
        logger.info(f"✅ S3 initialized: {S3_BUCKET_NAME} ({AWS_REGION})")
    except ClientError as e:
        logger.warning(f"⚠️ S3 head_bucket failed for {S3_BUCKET_NAME}: {e}")

except Exception as e:
    logger.error(f"❌ AWS initialization failed: {e}")
    s3 = None
    dynamodb = None
    user_survey_table = None


# =========================================================================================
# AGENT SUBPROCESS
# =========================================================================================

def _status_path(agent_dir: str) -> str:
    return os.path.join(agent_dir, STEP_STATUS_FILE)

def _clear_old_status(agent_dir: str) -> None:
    sp = _status_path(agent_dir)
    try:
        if os.path.exists(sp):
            os.remove(sp)
    except Exception:
        pass

def _safe_read_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _wait_status(agent_dir: str, timeout_sec: int, *, start_ts: float) -> dict:
    """
    Waits for step_status.json written AFTER start_ts.
    Also waits for file size to stabilize once to avoid partial JSON reads.
    """
    path = _status_path(agent_dir)
    end = time.time() + timeout_sec
    last_size = -1
    stable_count = 0

    while time.time() < end:
        if os.path.exists(path):
            try:
                sz = os.path.getsize(path)
                if sz != last_size:
                    last_size = sz
                    stable_count = 0
                    time.sleep(STATUS_CHANGE_SETTLE)
                    continue
                else:
                    stable_count += 1

                # require at least 2 stable reads
                if stable_count < 2:
                    time.sleep(STATUS_POLL_SLEEP)
                    continue

                data = _safe_read_json(path)
                if isinstance(data, dict) and "ok" in data:
                    # freshness check using file mtime
                    mtime = os.path.getmtime(path)
                    if mtime >= start_ts:
                        return data
            except Exception:
                pass

        time.sleep(STATUS_POLL_SLEEP)

    raise TimeoutError(f"Agent did not write fresh step_status.json within {timeout_sec}s")

def _terminate_process(proc: subprocess.Popen, *, kill_after: float = 2.0) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except Exception:
        pass

    end = time.time() + kill_after
    while time.time() < end:
        if proc.poll() is not None:
            return
        time.sleep(0.1)

    try:
        proc.kill()
    except Exception:
        pass

def _run_agent_subprocess(cmd: List[str], cwd: str, timeout_sec: int, log_prefix: str) -> dict:
    ts = time.strftime("%Y%m%d-%H%M%S")
    log_file = os.path.join(AGENT_LOG_DIR, f"{log_prefix}_{ts}.log")

    logger.info(f"🔧 Running: {' '.join(cmd)}")
    logger.info(f"📋 Log: {log_file}")

    start_ts = time.time()

    with open(log_file, "w", encoding="utf-8") as lf:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=lf, stderr=lf)
        try:
            status = _wait_status(cwd, timeout_sec=timeout_sec, start_ts=start_ts)
            return status
        finally:
            _terminate_process(proc)

def _write_goal_file(goal: str) -> str:
    p = os.path.join(GOAL_FILES_DIR, f"goal_{int(time.time())}_{uuid.uuid4().hex}.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write(goal)
    return p

def call_agent_text(goal: str, chat_url: Optional[str], timeout: int = TEXT_TIMEOUT_DEFAULT) -> Tuple[str, Optional[str]]:
    agent_dir = os.path.abspath(AUTOMATION_AGENT_DIR)
    if not agent_dir or not os.path.isdir(agent_dir):
        raise RuntimeError(f"AUTOMATION_AGENT_DIR invalid: {AUTOMATION_AGENT_DIR}")

    _clear_old_status(agent_dir)
    url_to_use = chat_url or "https://chatgpt.com"

    if len(goal) > 2500:
        gf = _write_goal_file(goal)
        cmd = ["python", "run.py", "--url", url_to_use, "--goal-file", gf, "--mode", "attach"]
    else:
        cmd = ["python", "run.py", "--url", url_to_use, "--goal", goal, "--mode", "attach"]

    status = _run_agent_subprocess(cmd, cwd=agent_dir, timeout_sec=timeout, log_prefix="TEXT")

    if not status.get("ok"):
        raise RuntimeError(status.get("error") or "Agent text step failed")

    reply = (status.get("reply_text") or "").strip()
    updated_chat = (status.get("chat_url") or chat_url or "").strip()
    return reply, updated_chat

def call_agent_image_generate(goal: str, chat_url: Optional[str], timeout: int = IMAGE_TIMEOUT_DEFAULT) -> Optional[str]:
    agent_dir = os.path.abspath(AUTOMATION_AGENT_DIR)
    if not agent_dir or not os.path.isdir(agent_dir):
        raise RuntimeError(f"AUTOMATION_AGENT_DIR invalid: {AUTOMATION_AGENT_DIR}")

    _clear_old_status(agent_dir)
    url_to_use = chat_url or "https://chatgpt.com"
    cmd = ["python", "run.py", "--url", url_to_use, "--goal", goal, "--mode", "attach", "--wait_for_image"]

    status = _run_agent_subprocess(cmd, cwd=agent_dir, timeout_sec=timeout, log_prefix="IMAGE_GEN")

    if not status.get("ok"):
        raise RuntimeError(status.get("error") or "Agent image generation failed")

    updated_chat = (status.get("chat_url") or chat_url or "").strip()

    # Small settle so the latest image is definitely “latest” for download-only click
    time.sleep(max(0.0, POST_IMAGE_SETTLE_SEC))
    return updated_chat

def call_agent_image_download_only(chat_url: Optional[str], timeout: int = DOWNLOAD_TIMEOUT_DEFAULT) -> Tuple[str, Optional[str]]:
    agent_dir = os.path.abspath(AUTOMATION_AGENT_DIR)
    if not agent_dir or not os.path.isdir(agent_dir):
        raise RuntimeError(f"AUTOMATION_AGENT_DIR invalid: {AUTOMATION_AGENT_DIR}")

    _clear_old_status(agent_dir)
    url_to_use = chat_url or "https://chatgpt.com"
    cmd = ["python", "run.py", "--url", url_to_use, "--goal", "DOWNLOAD_ONLY", "--mode", "attach", "--download_only"]

    status = _run_agent_subprocess(cmd, cwd=agent_dir, timeout_sec=timeout, log_prefix="DOWNLOAD")

    if not status.get("ok"):
        raise RuntimeError(status.get("error") or "Download failed")

    downloaded = (status.get("downloaded") or "").strip()
    updated_chat = (status.get("chat_url") or chat_url or "").strip()

    if not downloaded:
        raise RuntimeError("Download returned empty file path")

    # Validate download sanity
    if not os.path.exists(downloaded):
        raise RuntimeError(f"Downloaded file not found: {downloaded}")

    ext = os.path.splitext(downloaded)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise RuntimeError(f"Downloaded unexpected extension: {downloaded}")

    try:
        size = os.path.getsize(downloaded)
        if size < DOWNLOAD_MIN_BYTES:
            raise RuntimeError(f"Downloaded file too small ({size} bytes): {downloaded}")
    except Exception as e:
        raise RuntimeError(f"Downloaded file validation failed: {e}")

    return downloaded, updated_chat


# =========================================================================================
# PARSING UTILITIES
# =========================================================================================

def parse_score(text: str) -> float:
    patterns = [
        r"score[:\s]+(\d+\.?\d*)\s*/\s*10",
        r"score[:\s]+(\d+\.?\d*)",
        r"(\d+\.?\d*)\s*/\s*10",
    ]
    t = (text or "").lower()
    for p in patterns:
        m = re.search(p, t)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                pass
    return 0.0

def extract_issues_from_eval(eval_text: str) -> str:
    if not eval_text:
        return "No issues returned"
    m = re.search(r"Issues:\s*(.+?)\n\s*END\s*$", eval_text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return eval_text.strip()

def is_ready_prompt_valid(text: str) -> bool:
    if not text:
        return False
    t = text.strip()

    if not re.search(r"(?:^|\n)READY\s*$", t):
        return False

    low = t.lower()
    must_have = [
        "final headline",
        "final subheadline",
        "bullet",
        "cta",
        "visual blueprint",
        "layout",
        "typography",
        "1080",
        "1350",
    ]
    if not all(k in low for k in must_have):
        return False

    invalid_starts = [
        "got it", "sure", "i'm stepping", "i am stepping",
        "whenever you're ready", "please tell me", "understood", "okay"
    ]
    if any(low.startswith(phrase) for phrase in invalid_starts):
        return False

    return True

def build_prompt_repair_message() -> str:
    return """
❌ Your last message is INVALID.

Output the complete READY-TO-POST image generation prompt NOW.

Requirements:
• NO intro, NO "Got it", NO acknowledgments, NO questions
• Output ONLY the structured prompt

Required format:
1) FINAL HEADLINE (exact text)
2) FINAL SUBHEADLINE (exact text)
3) 2-4 BULLET POINTS (exact text)
4) CTA BUTTON TEXT (exact)
5) COMPLETE VISUAL BLUEPRINT (layout, typography, spacing, colors, background, style)
6) Format: 1080×1350
7) Style: Premium, anti-AI

End with: READY
""".strip()

def extract_copy_lock(ready_prompt: str) -> Dict[str, Any]:
    t = (ready_prompt or "").strip()

    def grab_line(pattern: str) -> str:
        m = re.search(pattern, t, flags=re.IGNORECASE | re.MULTILINE)
        return (m.group(1).strip() if m else "").strip()

    headline = grab_line(r"FINAL\s*HEADLINE.*?\)\s*[:\-]?\s*(.+)$")
    subheadline = grab_line(r"FINAL\s*SUBHEADLINE.*?\)\s*[:\-]?\s*(.+)$")
    cta = grab_line(r"CTA\s*BUTTON\s*TEXT.*?\)\s*[:\-]?\s*(.+)$")

    bullets_block = ""
    m = re.search(
        r"(?:2-4\s*BULLET\s*POINTS.*?\)\s*[:\-]?\s*)(.+?)(?:\n\s*4\)\s*CTA|\n\s*CTA\s*BUTTON\s*TEXT)",
        t,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        bullets_block = (m.group(1) or "").strip()

    bullets: List[str] = []
    for line in bullets_block.splitlines():
        s = line.strip().lstrip("•").lstrip("-").strip()
        if s:
            bullets.append(s)
    bullets = bullets[:4]

    return {"headline": headline, "subheadline": subheadline, "bullets": bullets, "cta": cta}

def layout_variant_for_attempt(attempt: int) -> str:
    variants = ["A", "B", "C", "D"]
    return variants[(attempt - 2) % 4]


# =========================================================================================
# IMAGE GENERATOR
# =========================================================================================

class ImageGenerator:
    def __init__(self):
        self.max_iterations = IMG_MAX_ITERS
        self.fast_target_iters = IMG_FAST_TARGET_ITERS
        self.score_threshold = IMG_SCORE_THRESHOLD
        logger.info(
            f"✅ ImageGenerator initialized (threshold={self.score_threshold}, "
            f"fast_target={self.fast_target_iters}, max_iters={self.max_iterations})"
        )

    def parse_dynamodb_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if item and all(not isinstance(v, dict) for v in item.values()):
                return item

            parsed: Dict[str, Any] = {}
            for k, v in item.items():
                if isinstance(v, dict):
                    if "S" in v:
                        parsed[k] = v["S"]
                    elif "N" in v:
                        parsed[k] = float(v["N"])
                    elif "BOOL" in v:
                        parsed[k] = v["BOOL"]
                    elif "M" in v:
                        parsed[k] = self.parse_dynamodb_item(v["M"])
                    else:
                        parsed[k] = v
                else:
                    parsed[k] = v
            return parsed
        except Exception:
            return item

    def get_user_business_data(self, user_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not user_id or not user_survey_table:
            return None

        try:
            resp = user_survey_table.query(
                KeyConditionExpression=Key("userId").eq(user_id),
                ScanIndexForward=False,
                Limit=1,
            )
            if not resp.get("Items"):
                return None

            parsed = self.parse_dynamodb_item(resp["Items"][0])
            answers = parsed.get("answers") if isinstance(parsed.get("answers"), dict) else parsed

            return {
                "company_name": answers.get("company_name") or answers.get("brand_name") or user_id,
                "brand_colors": answers.get("brand_colors") or answers.get("color_theme"),
                "tone": answers.get("tone") or "professional",
                "website": answers.get("website") or answers.get("website_url"),
                "business_type": answers.get("business_type") or parsed.get("business_type") or "general",
                "logo_s3_key": answers.get("logo_s3_key") or answers.get("logoKey") or answers.get("logo_key"),
                "logo_url": answers.get("logo_url") or answers.get("logoUrl") or answers.get("logo"),
            }
        except Exception as e:
            logger.error(f"❌ Failed to fetch business data for {user_id}: {e}")
            return None

    def load_content_details(self, content_path: str = "content_details.json") -> Optional[Dict[str, Any]]:
        try:
            if not os.path.exists(content_path):
                logger.warning(f"⚠️ {content_path} not found")
                return None
            with open(content_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"❌ Failed to load content_details.json: {e}")
            return None

    def _read_file_bytes(self, path: str) -> Optional[bytes]:
        try:
            if not path or not os.path.exists(path):
                return None
            with open(path, "rb") as f:
                b = f.read()
            return b if b and len(b) > 2000 else None
        except Exception:
            return None

    def _safe_delete_file(self, path: Optional[str]) -> None:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def _sanitize_user_id(self, user_id: Optional[str]) -> str:
        uid = (user_id or "anonymous").strip()
        uid = uid.replace(" ", "_").replace("/", "_").replace("\\", "_")
        uid = "".join(ch for ch in uid if ch.isalnum() or ch in ("_", "-", ".", "@"))
        return uid or "anonymous"

    # =====================================================================================
    # S3 LOGO FETCH + OVERLAY
    # =====================================================================================

    def _s3_get_bytes(self, key: str) -> Optional[bytes]:
        if not s3 or not S3_BUCKET_NAME or not key:
            return None
        try:
            obj = s3.get_object(Bucket=S3_BUCKET_NAME, Key=key)
            data = obj["Body"].read()
            return data if data and len(data) > 2000 else None
        except Exception:
            return None

    def _pick_latest_logo_key_for_user(self, user_id: str) -> Optional[str]:
        if not s3 or not S3_BUCKET_NAME:
            return None

        uid = self._sanitize_user_id(user_id)
        candidates: List[Tuple[str, float]] = []

        prefixes = [
            f"{S3_LOGO_PREFIX}/{uid}",
            f"{S3_LOGO_PREFIX}/{uid}_",
            f"{S3_LOGO_PREFIX}/{uid}/",
        ]

        for pref in prefixes:
            try:
                resp = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix=pref, MaxKeys=500)
                for it in resp.get("Contents", []) or []:
                    key = it.get("Key") or ""
                    if not key:
                        continue
                    kext = os.path.splitext(key)[1].lower()
                    if kext not in (".png", ".jpg", ".jpeg", ".webp"):
                        continue
                    lm = it.get("LastModified")
                    ts = lm.timestamp() if lm else 0.0
                    candidates.append((key, ts))
            except Exception:
                continue

        if not candidates:
            try:
                resp = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix=f"{S3_LOGO_PREFIX}/", MaxKeys=200)
                for it in resp.get("Contents", []) or []:
                    key = it.get("Key") or ""
                    if uid.lower() not in key.lower():
                        continue
                    kext = os.path.splitext(key)[1].lower()
                    if kext not in (".png", ".jpg", ".jpeg", ".webp"):
                        continue
                    lm = it.get("LastModified")
                    ts = lm.timestamp() if lm else 0.0
                    candidates.append((key, ts))
            except Exception:
                pass

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def _fetch_logo_bytes(self, user_id: Optional[str], business_context: Dict[str, Any]) -> Optional[bytes]:
        if not LOGO_ENABLED:
            return None
        if not user_id:
            return None
        if not s3 or not S3_BUCKET_NAME:
            return None

        logo_key = (business_context or {}).get("logo_s3_key") or ""
        if isinstance(logo_key, str) and logo_key.strip():
            b = self._s3_get_bytes(logo_key.strip())
            if b:
                return b

        logo_url = (business_context or {}).get("logo_url") or ""
        if isinstance(logo_url, str) and logo_url.startswith("s3://"):
            try:
                parts = logo_url.replace("s3://", "", 1).split("/", 1)
                bkt = parts[0]
                key = parts[1] if len(parts) > 1 else ""
                if bkt == S3_BUCKET_NAME and key:
                    b = self._s3_get_bytes(key)
                    if b:
                        return b
            except Exception:
                pass

        key = self._pick_latest_logo_key_for_user(user_id)
        if key:
            b = self._s3_get_bytes(key)
            if b:
                return b

        return None

    def _overlay_logo(self, base_img_bytes: bytes, logo_bytes: bytes) -> bytes:
        """
        Overlay logo on base image with background removal.
        ✅ NEW: Removes white/light backgrounds from logo before overlay
        """
        try:
            base = Image.open(BytesIO(base_img_bytes)).convert("RGBA")
            logo = Image.open(BytesIO(logo_bytes)).convert("RGBA")

            bw, bh = base.size

            # ✅ STEP 1: REMOVE BACKGROUND
            # Make white and near-white pixels transparent
            logo_pixels = logo.load()
            for y in range(logo.size[1]):
                for x in range(logo.size[0]):
                    r, g, b, a = logo_pixels[x, y]
                    
                    # Remove pure white and near-white backgrounds (RGB > 240)
                    if r > 240 and g > 240 and b > 240:
                        logo_pixels[x, y] = (r, g, b, 0)  # Make transparent
                    # Also remove light gray backgrounds (RGB > 220)
                    elif r > 220 and g > 220 and b > 220:
                        # Gradual transparency for light grays
                        logo_pixels[x, y] = (r, g, b, 0)

            # ✅ STEP 2: RESIZE (maintaining aspect ratio)
            lw, lh = logo.size
            scale = min(LOGO_MAX_W / max(1, lw), LOGO_MAX_H / max(1, lh), 1.0)
            nw, nh = max(1, int(lw * scale)), max(1, int(lh * scale))
            if (nw, nh) != (lw, lh):
                logo = logo.resize((nw, nh), Image.LANCZOS)

            # ✅ STEP 3: APPLY OPACITY (existing logic)
            if logo.mode == "RGBA":
                r, g, b, a = logo.split()
                a = a.point(lambda p: 0 if p < LOGO_MIN_ALPHA else int(p * LOGO_OPACITY))
                logo = Image.merge("RGBA", (r, g, b, a))

            # ✅ STEP 4: POSITION (top-right corner)
            x = max(0, bw - logo.size[0] - LOGO_PADDING)
            y = max(0, LOGO_PADDING)

            # ✅ STEP 5: ADD SHADOW
            shadow_alpha = logo.split()[3].filter(ImageFilter.GaussianBlur(radius=2))
            shadow = Image.merge(
                "RGBA",
                (
                    Image.new("L", logo.size, 0),
                    Image.new("L", logo.size, 0),
                    Image.new("L", logo.size, 0),
                    shadow_alpha,
                ),
            )
            base.alpha_composite(shadow, dest=(x + 2, y + 3))
            
            # ✅ STEP 6: COMPOSITE LOGO
            base.alpha_composite(logo, dest=(x, y))

            # ✅ STEP 7: RETURN AS PNG BYTES
            out = BytesIO()
            base.convert("RGB").save(out, format="PNG", optimize=True)
            return out.getvalue()
            
        except Exception as e:
            logger.warning(f"⚠️ Logo overlay failed: {e}")
            return base_img_bytes

    # =====================================================================================
    # PDF (NEW)
    # =====================================================================================

    def _images_to_pdf_bytes(self, images_rgb_bytes: List[bytes]) -> bytes:
        pil_images: List[Image.Image] = []
        for b in images_rgb_bytes:
            img = Image.open(BytesIO(b)).convert("RGB")
            pil_images.append(img)

        if not pil_images:
            raise RuntimeError("No images to convert to PDF")

        out = BytesIO()
        first, rest = pil_images[0], pil_images[1:]
        first.save(out, format="PDF", save_all=True, append_images=rest)
        return out.getvalue()

    def _upload_pdf_to_s3(self, pdf_bytes: bytes, user_id: Optional[str]) -> str:
        if not s3:
            raise RuntimeError("S3 client not initialized")
        if not S3_BUCKET_NAME:
            raise RuntimeError("S3_BUCKET_NAME not set")

        uid = self._sanitize_user_id(user_id)
        key = f"{S3_PDF_PREFIX}/slides_{uid}_{uuid.uuid4().hex}.pdf"

        extra_args = {"ContentType": "application/pdf"}
        if S3_PUBLIC_READ:
            extra_args["ACL"] = "public-read"

        s3.upload_fileobj(BytesIO(pdf_bytes), S3_BUCKET_NAME, key, ExtraArgs=extra_args)

        if S3_CDN_BASE_URL:
            return f"{S3_CDN_BASE_URL}/{key}"
        if S3_PUBLIC_READ:
            return f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{key}"

        return s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": S3_BUCKET_NAME, "Key": key},
            ExpiresIn=7 * 24 * 3600,
        )

    # =====================================================================================

    def _upload_to_s3(self, image_bytes: bytes, user_id: Optional[str], idx: int) -> str:
        if not s3:
            raise RuntimeError("S3 client not initialized")
        if not S3_BUCKET_NAME:
            raise RuntimeError("S3_BUCKET_NAME not set")

        uid = self._sanitize_user_id(user_id)
        key = f"{S3_IMAGE_PREFIX}/slide_{uid}_{idx}_{uuid.uuid4().hex}.png"

        extra_args = {"ContentType": "image/png"}
        if S3_PUBLIC_READ:
            extra_args["ACL"] = "public-read"

        s3.upload_fileobj(BytesIO(image_bytes), S3_BUCKET_NAME, key, ExtraArgs=extra_args)

        if S3_CDN_BASE_URL:
            return f"{S3_CDN_BASE_URL}/{key}"
        if S3_PUBLIC_READ:
            return f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{key}"

        return s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": S3_BUCKET_NAME, "Key": key},
            ExpiresIn=7 * 24 * 3600,
        )

    def _build_slide_text(self, slide_data: Dict[str, Any]) -> Tuple[str, str, List[str]]:
        title = slide_data.get("title") or slide_data.get("headline") or slide_data.get("topic") or "Slide"
        body = slide_data.get("body") or slide_data.get("points") or slide_data.get("bullets") or []
        if not isinstance(body, list):
            body = [str(body)]
        body_txt = "\n".join([f"- {b}" for b in body])
        return title, body_txt, body

    def _extract_user_prompt(self, content_details: Dict[str, Any], user_image_prompt: Optional[str]) -> str:
        candidates = [
            user_image_prompt,
            content_details.get("user_image_prompt"),
            content_details.get("userPrompt"),
            content_details.get("custom_prompt"),
            content_details.get("user_submitted_prompt"),
            content_details.get("prompt"),
            content_details.get("input_prompt"),
        ]
        for c in candidates:
            if isinstance(c, str) and c.strip():
                return c.strip()
        return ""

    def _build_content_summary(self, caption: str, slide_title: str, slide_points: List[str]) -> str:
        pts = [p.strip() for p in slide_points if isinstance(p, str) and p.strip()]
        pts_short = pts[:4]
        cap = (caption or "").strip()
        cap_short = cap[:260] + ("…" if len(cap) > 260 else "")

        summary_lines = []
        if slide_title:
            summary_lines.append(f"- Slide focus: {slide_title}")
        if pts_short:
            summary_lines.append("- Key ideas: " + "; ".join(pts_short))
        if cap_short:
            summary_lines.append("- Caption context: " + cap_short)

        return "\n".join(summary_lines).strip()

    # --- Prompt builders ---

    def _build_step1_prompt(
        self,
        *,
        idx: int,  # ✅ NEW: for diversity control
        company: str,
        tone: str,
        brand_colors: Optional[str],
        website: Optional[str],
        theme: str,
        slide_title: str,
        slide_body_txt: str,
        content_summary: str,
        user_prompt: str,
    ) -> str:
        colors_line = f"Brand colors: {brand_colors}" if brand_colors else "Brand colors: (not provided — use minimal, premium palette)"
        website_line = f"Website: {website}" if website else "Website: (not provided)"

        user_prompt_block = ""
        if user_prompt:
            user_prompt_block = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USER'S CUSTOM INSTRUCTIONS (MUST RESPECT):
{user_prompt}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""".strip()

        summary_block = ""
        if content_summary:
            summary_block = f"""
CONTENT CONTEXT:
{content_summary}
""".strip()

        # ✅ NEW: controlled diversity block (visual only)
        div_seed = _diversity_seed(idx, theme, company)
        div_dir = _diversity_direction_for_slide(idx)

        return f"""
You are a senior brand designer creating image generation prompt.

⚠️ CRITICAL INSTRUCTIONS:
• NO questions, NO intro, NO acknowledgments
• Output ONE complete READY-TO-POST image generation prompt
• Must end with ONLY: READY

BRAND INFORMATION:
• Company: {company}
• Tone: {tone}
• {colors_line}
• {website_line}

CAMPAIGN:
• Theme: {theme}

SLIDE CONTENT:
• Headline: {slide_title} if it has request or generate or create improve it
• Points:
{slide_body_txt}

NON-NEGOTIABLE:
- Use the slide headline + points as the BASELINE truth.
- Do NOT invent claims, discounts, guarantees, or offers not present in the points.
- Keep copy premium, crisp, and mobile-readable.

{summary_block}

{user_prompt_block}

VISUAL DIVERSITY (MUST KEEP SAME TOPIC & BRAND):
- You MUST keep the same message and copy meaning.
- Make this slide visually distinct from other slides in this batch by varying:
  • composition (crop/angle), lighting (sunrise/dusk), background treatment, hero placement
- Do NOT introduce off-topic objects or claims.
- Diversity Seed: {div_seed}
- {div_dir}

OUTPUT FORMAT:
1) FINAL HEADLINE dont include anything like create or etc select the heading very nicely which can capture users attention (exact text)
2) FINAL SUBHEADLINE (exact text)
3) 2 BULLET POINTS (exact text)
4) CTA BUTTON TEXT (exact)
5) COMPLETE VISUAL BLUEPRINT:
   - Layout Grid: top/middle/bottom structure
   - Typography: fonts, sizes, weights, hierarchy
   - Spacing: margins, padding, alignment, whitespace
   - Colors: primary, secondary, accent, background
   - Background: base, texture, brand integration
   - Visual Style: aesthetic, icon/photo style, effects, anti-AI approach
6) FORMAT: 1080×1350 pixels (Instagram portrait 4:5)
7) QUALITY: Premium, modern, zero AI vibes, agency-grade, mobile-ready

by taking all this information create a prompt which i will be using below to generate a ready-to-post image and in theme is there is create or generate words dont try to include in the heading
u are free to use your thinking capabiltiy and then generate a prompt which will generate a best image prompt generation should bring the generated images very professional like that u need to generate the prompt
End with: READY
""".strip()

    def _build_step3_eval_prompt(self, attempt_num: int) -> str:
        return f"""
🚨 ULTRA-STRICT EVALUATION - ATTEMPT #{attempt_num} 🚨

RESPOND EXACTLY:

Score: X.X/10

Issues:
- Typography: [specific problem with score]
- Hierarchy: [specific problem with score]
- Design: [specific problem with score]
- Brand: [specific problem with score]
- [Any other specific flaws]

END
""".strip()

    def _build_step4_regen_prompt(
        self,
        *,
        issues: str,
        attempt_num: int,
        previous_score: float,
        copy_lock: Dict[str, Any],
        variant: str,
        aggressive: bool,
    ) -> str:
        headline = (copy_lock.get("headline") or "").strip()
        subheadline = (copy_lock.get("subheadline") or "").strip()
        bullets = copy_lock.get("bullets") or []
        cta = (copy_lock.get("cta") or "").strip()
        bullets_txt = "\n".join([f"- {b}" for b in bullets]) if bullets else "- (keep exact bullets from prior)"

        if aggressive:
            aggressive_block = """
FAST-TARGET MODE:
- Make improvement OBVIOUS: switch composition + background treatment + hero placement
- Keep premium minimal; no gimmicks
""".strip()
        else:
            aggressive_block = """
POLISH MODE:
- Keep composition, refine kerning, spacing, contrast, micro-shadows
- Remove template vibes, increase whitespace
""".strip()

        return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔥 REGENERATION ATTEMPT #{attempt_num} - PREVIOUS SCORE: {previous_score}/10
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚫 ABSOLUTE RULE: DO NOT CHANGE ANY COPY. USE THIS EXACT COPY ONLY:
regenerate image by taking the feedback and give me a improved image
HEADLINE:
{headline}

SUBHEADLINE:
{subheadline}

BULLETS:
{bullets_txt}

CTA:
{cta}

🎛️ REQUIRED LAYOUT VARIANT (MUST FOLLOW): {variant}
- Variant A: Left text column, right hero product (large), CTA under bullets
- Variant B: Top hero product, below: text block + bullets, CTA aligned left
- Variant C: Split card: top headline/subheadline, mid bullets, bottom hero + CTA
- Variant D: Bold headline top, bullets mid-left, hero mid-right, CTA bottom-left

❌ FIX THESE ISSUES (VISUALLY ONLY — NEVER by changing copy):
{issues}

{aggressive_block}

MANDATORY:
- Typography razor-sharp + larger for 1080×1350
- Strict grid, generous margins, subtle depth
- Brand gold only as intentional highlights (rules/lines/CTA outline)
- No plastic gradients, no sparkles, no cheap bevels

Format: 1080×1350 portrait
regenrate the image dont give me the feedback again regenerate the image okay
""".strip()

    def _build_final_download_render_prompt(
        self,
        *,
        copy_lock: Dict[str, Any],
        variant: str,
    ) -> str:
        headline = (copy_lock.get("headline") or "").strip()
        subheadline = (copy_lock.get("subheadline") or "").strip()
        bullets = copy_lock.get("bullets") or []
        cta = (copy_lock.get("cta") or "").strip()
        bullets_txt = "\n".join([f"- {b}" for b in bullets]) if bullets else "- (keep exact bullets from prior)"

        return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ FINAL DOWNLOAD RENDER (NO EVAL AFTER THIS)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚫 ABSOLUTE RULE: DO NOT CHANGE ANY COPY. USE THIS EXACT COPY ONLY:

HEADLINE:
{headline}

SUBHEADLINE:
{subheadline}

BULLETS:
{bullets_txt}

CTA:
{cta}

🎛️ REQUIRED LAYOUT VARIANT (MUST FOLLOW): {variant}
- Variant A: Left text column, right hero product (large), CTA under bullets
- Variant B: Top hero product, below: text block + bullets, CTA aligned left
- Variant C: Split card: top headline/subheadline, mid bullets, bottom hero + CTA
- Variant D: Bold headline top, bullets mid-left, hero mid-right, CTA bottom-left

GOAL:
- Render the FINAL polished image for downloading.
- Micro-polish only: kerning, edges razor sharp, spacing, contrast, margins, alignment.
- Do not add any new elements/copy. No template vibes.

Format: 1080×1350 portrait
""".strip()

    # =====================================================================================

    def generate_images(
        self,
        theme: str,
        content_type: str,
        num_images: int,
        subtopics: List[Dict[str, str]],
        user_id: Optional[str] = None,
        meme_mode: bool = False,
        create_pdf: bool = False,  # kept but we now always build pdf at end if any images produced
        creative_overlay_level: int = 1,
        website_url: Optional[str] = None,
        user_image_prompt: Optional[str] = None,
        content_summary: Optional[List[str]] = None,
        business_context: Optional[Dict[str, Any]] = None,
    ) -> List[str]:

        logger.info("\n" + "=" * 100)
        logger.info("🚀 IMAGE GENERATION WORKFLOW - HARDENED + LOGO OVERLAY + DIVERSITY + PDF")
        logger.info("=" * 100)
        logger.info(f"📊 Config: S3={S3_BUCKET_NAME} | Threshold={self.score_threshold} | Max Iterations={self.max_iterations}")
        logger.info(f"🎯 Target: {num_images} images for theme '{theme}'")
        logger.info("=" * 100)

        image_urls: List[str] = []
        chat_url: Optional[str] = None

        # ✅ NEW: collect final image bytes for PDF
        final_images_for_pdf: List[bytes] = []

        content_details = self.load_content_details()
        if not content_details:
            logger.error("❌ content_details.json missing")
            return []

        if not business_context:
            business_context = content_details.get("business_context") or {}
            if (not business_context) and user_id:
                logger.info(f"📋 Fetching business data from DynamoDB for user: {user_id}")
                business_context = self.get_user_business_data(user_id) or {}

        business_context = business_context or {}
        company = business_context.get("company_name") or business_context.get("brand_name") or (user_id or "Brand")
        tone = business_context.get("tone") or "professional"
        brand_colors = business_context.get("brand_colors") or business_context.get("colors")
        website = website_url or business_context.get("website") or business_context.get("website_url")

        slides = (content_details.get("slide_contents") or content_details.get("slideContents") or {})
        if not isinstance(slides, dict):
            slides = {}

        caption = (content_details.get("caption") or content_details.get("post_caption") or "").strip()
        stored_user_prompt = self._extract_user_prompt(content_details, user_image_prompt)

        # Pre-fetch logo once per job
        logo_bytes: Optional[bytes] = None
        if LOGO_ENABLED and user_id:
            logo_bytes = self._fetch_logo_bytes(user_id, business_context)
            if logo_bytes:
                logger.info("🧷 Logo found in S3. Will overlay before upload.")
            else:
                logger.info("🧷 No logo found in S3. Uploading images without logo overlay.")

        try:
            for idx in range(1, num_images + 1):
                slide_key = f"slide_{idx}"
                slide_data = slides.get(slide_key) or {}
                if not isinstance(slide_data, dict) or not slide_data:
                    logger.warning(f"⚠️ Missing {slide_key}, skipping")
                    continue

                slide_title, slide_body_txt, slide_points = self._build_slide_text(slide_data)
                summary = self._build_content_summary(caption, slide_title, slide_points)

                logger.info("\n" + "=" * 100)
                logger.info(f"🎯 PROCESSING SLIDE {idx}/{num_images}: {slide_title}")
                logger.info("=" * 100)

                # STEP 1: READY prompt (✅ now includes controlled diversity by slide idx)
                step1_goal = self._build_step1_prompt(
                    idx=idx,
                    company=company,
                    tone=tone,
                    brand_colors=brand_colors,
                    website=website,
                    theme=theme,
                    slide_title=slide_title,
                    slide_body_txt=slide_body_txt,
                    content_summary=summary,
                    user_prompt=stored_user_prompt,
                )

                step1_reply, chat_url = call_agent_text(step1_goal, chat_url=chat_url, timeout=TEXT_TIMEOUT_DEFAULT)

                repair_attempts = 0
                while not is_ready_prompt_valid(step1_reply) and repair_attempts < 2:
                    repair_attempts += 1
                    logger.warning(f"⚠️ STEP 1 invalid (attempt {repair_attempts}/2)")
                    step1_reply, chat_url = call_agent_text(
                        build_prompt_repair_message(),
                        chat_url=chat_url,
                        timeout=TEXT_TIMEOUT_DEFAULT
                    )

                if not is_ready_prompt_valid(step1_reply):
                    raise RuntimeError(f"STEP 1 failed for slide {idx}")

                copy_lock = extract_copy_lock(step1_reply)
                logger.info(
                    f"🔒 COPY LOCK: headline='{(copy_lock.get('headline') or '')[:60]}' "
                    f"| bullets={len(copy_lock.get('bullets') or [])} | cta='{(copy_lock.get('cta') or '')[:30]}'"
                )

                best_score = 0.0
                last_score = 0.0
                last_eval_text = ""
                no_improve = 0
                start_t = time.time()

                attempt = 1
                threshold_hit = False

                while True:
                    if attempt > self.max_iterations:
                        logger.info(f"⚠️ Max iterations reached. Best: {best_score}/10")
                        break
                    if (time.time() - start_t) > IMG_MAX_TIME_SEC:
                        logger.info(f"⚠️ Max time reached ({IMG_MAX_TIME_SEC}s). Best: {best_score}/10")
                        break

                    # STEP 2/4: image
                    if attempt == 1:
                        img_goal = "Generate the image from the READY-TO-POST prompt above. Format: 1080×1350 portrait."
                    else:
                        issues = extract_issues_from_eval(last_eval_text)
                        variant = layout_variant_for_attempt(attempt)
                        aggressive = attempt <= self.fast_target_iters

                        img_goal = self._build_step4_regen_prompt(
                            issues=issues,
                            attempt_num=attempt,
                            previous_score=last_score,
                            copy_lock=copy_lock,
                            variant=variant,
                            aggressive=aggressive,
                        )

                    chat_url = call_agent_image_generate(img_goal, chat_url=chat_url, timeout=IMAGE_TIMEOUT_DEFAULT)
                    logger.info(f"✅ Image generation complete (attempt {attempt})")

                    # STEP 3: evaluate (text)
                    eval_goal = self._build_step3_eval_prompt(attempt)
                    eval_reply, chat_url = call_agent_text(eval_goal, chat_url=chat_url, timeout=EVAL_TIMEOUT_DEFAULT)

                    last_score = parse_score(eval_reply)
                    last_eval_text = eval_reply

                    logger.info(f"📈 Score: {last_score}/10 (best: {best_score}/10, target: {self.score_threshold}/10)")

                    if last_score > best_score:
                        best_score = last_score
                        no_improve = 0
                    else:
                        no_improve += 1

                    if last_score >= self.score_threshold:
                        logger.info(f"🎉 THRESHOLD REACHED: {last_score}/10 >= {self.score_threshold}/10")
                        threshold_hit = True
                        break

                    if no_improve >= IMG_PATIENCE:
                        logger.info(f"⚠️ Plateau detected (no improve {no_improve}x). Best: {best_score}/10")
                        break

                    attempt += 1

                if not threshold_hit:
                    logger.warning(
                        f"❌ Not saving slide {idx}: last_score={last_score} < threshold={self.score_threshold}"
                    )
                    continue

                # ✅ FINAL DOWNLOAD RENDER (so latest assistant message is IMAGE, not evaluation)
                final_variant = layout_variant_for_attempt(attempt + 1)
                final_goal = self._build_final_download_render_prompt(copy_lock=copy_lock, variant=final_variant)

                logger.info("🧾 Final render for download (no eval after this)...")
                chat_url = call_agent_image_generate(final_goal, chat_url=chat_url, timeout=IMAGE_TIMEOUT_DEFAULT)
                logger.info("✅ Final download render complete. Proceeding to download-only.")

                # STEP 5: download latest (WITH RETRIES)
                dl_path = None
                dl_chat_url = chat_url
                last_dl_err = None

                for r in range(1, DOWNLOAD_RETRIES + 1):
                    try:
                        tmo = DOWNLOAD_TIMEOUT_DEFAULT + (r - 1) * DOWNLOAD_RETRY_TIMEOUT_BUMP
                        dl_path, dl_chat_url = call_agent_image_download_only(chat_url=dl_chat_url, timeout=tmo)
                        logger.info(f"✅ Downloaded: {dl_path} (retry {r}/{DOWNLOAD_RETRIES})")
                        break
                    except Exception as e:
                        last_dl_err = str(e)
                        logger.warning(f"⚠️ Download retry {r}/{DOWNLOAD_RETRIES} failed: {e}")
                        time.sleep(DOWNLOAD_RETRY_SLEEP)

                chat_url = dl_chat_url

                if not dl_path:
                    raise RuntimeError(f"Download failed after retries: {last_dl_err or 'unknown'}")

                img_bytes = self._read_file_bytes(dl_path)
                if not img_bytes:
                    # if failed reading, still cleanup local file
                    self._safe_delete_file(dl_path)
                    logger.error(f"❌ Failed to read: {dl_path}")
                    continue

                # LOGO OVERLAY (BEFORE UPLOAD)
                if logo_bytes:
                    img_bytes = self._overlay_logo(img_bytes, logo_bytes)

                # ✅ Add to PDF list (final, logo-applied bytes)
                final_images_for_pdf.append(img_bytes)

                logger.info("☁️ Uploading to S3...")
                s3_url = self._upload_to_s3(img_bytes, user_id=user_id, idx=idx)
                image_urls.append(s3_url)

                # ✅ Delete local downloaded file after successful upload
                self._safe_delete_file(dl_path)

                logger.info(f"✅ SLIDE {idx} COMPLETE | Best score: {best_score}/10")
                logger.info(f"🔗 S3 URL: {s3_url}")

            # ✅ NEW: Build ONE PDF and upload to S3 pdfs/
            if final_images_for_pdf:
                try:
                    logger.info("📄 Creating PDF from final images...")
                    pdf_bytes = self._images_to_pdf_bytes(final_images_for_pdf)
                    pdf_url = self._upload_pdf_to_s3(pdf_bytes, user_id=user_id)
                    logger.info(f"✅ PDF uploaded to S3: {pdf_url}")

                    # optional: include pdf in return list (last element)
                    image_urls.append(pdf_url)
                except Exception as e:
                    logger.warning(f"⚠️ PDF creation/upload failed: {e}")

            logger.info("\n" + "=" * 100)
            logger.info(f"🎉 WORKFLOW COMPLETE: {len(image_urls)} urls (images + optional pdf)")
            logger.info("=" * 100)

            return image_urls

        except Exception as e:
            logger.error(f"\n❌ ERROR: {e}")
            logger.error(traceback.format_exc())
            return []