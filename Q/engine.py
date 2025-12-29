# Q/engine.py
"""
Executes jobs with failure notifications and automatic recovery.
"""
import json
import logging

from Q.jobs_repo import mark_in_progress, mark_completed, mark_failed
from Q.notifications import (
    notify_job_failed,
    notify_job_completed,
    get_friendly_error_message,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _parse_body(event: dict) -> dict:
    """Parse event body - handles both string and dict."""
    body = (event or {}).get("body")
    if isinstance(body, dict):
        return body
    try:
        return json.loads(body or "{}")
    except Exception:
        return {}


def _get_header(headers: dict, key: str) -> str | None:
    """Case-insensitive header getter."""
    if not headers:
        return None
    for k, v in headers.items():
        if k.lower() == key.lower():
            return v
    return None


def _extract_user_id(payload: dict) -> str:
    """
    Extract user_id from as many places as possible.
    """
    event = (payload or {}).get("event", {}) or {}
    body = _parse_body(event)
    headers = event.get("headers", {}) or {}
    qs = event.get("queryStringParameters", {}) or {}

    user_id = (
        body.get("user_id")
        or body.get("userId")
        or body.get("username")
        or payload.get("user_id")
        or _get_header(headers, "X-User-Id")
        or _get_header(headers, "X-User-Resolved")
        or _get_header(headers, "X-Username")
        or qs.get("app_user")
        or "unknown"
    )
    return user_id


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def handle_content_generate(payload: dict) -> dict:
    """
    Handles CONTENT_GENERATE job by calling the original content_handler.
    """
    from content_handler import ContentGenerator

    event = payload["event"]
    user_id = _extract_user_id(payload)

    logger.info("🚀 Worker processing content generation job")
    logger.info(f"   User: {user_id}")

    context = {
        "request": event,
        "claims": {"user_id": user_id, "username": user_id},
    }

    content_gen = ContentGenerator()
    result = content_gen.generate(context)

    logger.info("✅ Content generation handler returned")
    logger.info(
        f"   Result type: {type(result)} "
        f"keys: {list(result.keys()) if isinstance(result, dict) else 'n/a'}"
    )

    if not isinstance(result, dict) or result.get("error"):
        raise RuntimeError(
            result.get("error") if isinstance(result, dict) else "Handler returned no result"
        )

    no_images = not result.get("image_urls")
    no_pdf = not result.get("pdf_url")
    if no_images and no_pdf:
        raise RuntimeError("No assets generated")

    return result


HANDLERS = {
    "CONTENT_GENERATE": handle_content_generate,
}

# ---------------------------------------------------------------------------
# Main entrypoint for worker
# ---------------------------------------------------------------------------

def run_job(payload: dict):
    """
    Main entry point for worker to execute a job.
    This function NEVER lets exceptions escape; the worker can safely
    continue to the next message.
    """
    job_id = payload["job_id"]
    job_type = payload["job_type"]
    user_id = _extract_user_id(payload)

    logger.info(f"🔄 Processing job {job_id} (type: {job_type})")
    logger.info(f"   User: {user_id}")

    if job_type not in HANDLERS:
        error_msg = f"Unknown job_type: {job_type}"
        logger.error(f"❌ {error_msg}")
        friendly_msg = "Invalid job type. Please contact support."
        mark_failed(job_id, friendly_msg)
        notify_job_failed(job_id, friendly_msg, user_id)
        return

    try:
        mark_in_progress(job_id)
        logger.info(f"▶️ Job {job_id} marked as in_progress")

        handler = HANDLERS[job_type]
        result = handler(payload)

        # Success path
        mark_completed(job_id, result or {})
        logger.info(f"✅ Job {job_id} completed successfully")
        notify_job_completed(job_id, result or {}, user_id)

    except Exception as e:
        error_msg = str(e)
        friendly_msg = get_friendly_error_message(error_msg)

        logger.error(f"❌ Job {job_id} failed: {error_msg}")
        mark_failed(job_id, friendly_msg, technical_error=error_msg)
        notify_job_failed(job_id, friendly_msg, user_id)

        logger.info("📢 User notified of failure")
        logger.info("⏭️ Worker will continue to next job")
        # DO NOT re-raise – the worker loop will move on
