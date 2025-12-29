# Q/sqs_helpers.py
import os
import json
import time
import uuid
import boto3
import logging

log = logging.getLogger("Q.sqs")

REGION = os.getenv("AWS_REGION", "ap-south-1")
QUEUE_URL = os.getenv(
    "QUEUE_URL",
    "https://sqs.ap-south-1.amazonaws.com/509399605320/marketing-jobs.fifo",
)

# If SQS_GROUP_ID is set, we use that for *all* jobs (single FIFO group).
# If not set, we will use one FIFO group per user (user-<user_id>).
sqs = boto3.client("sqs", region_name=REGION)


def _resolve_user_id(event: dict) -> str:
    """
    Best-effort extraction of user identifier for grouping.
    """
    if not event:
        return "anonymous"

    if event.get("user_id"):
        return str(event["user_id"])

    headers = event.get("headers") or {}
    for k, v in headers.items():
        if k.lower() in ("x-user-resolved", "x-user-id", "x-username") and v:
            return str(v)

    return "anonymous"


def enqueue_job(event: dict, job_type: str = "CONTENT_GENERATE") -> str:
    """
    Enqueue a job to STANDARD SQS.
    Returns the job_id for tracking.
    """
    job_id = f"{int(time.time() * 1000)}-{uuid.uuid4().hex}"
    user_id = _resolve_user_id(event)

    payload = {
        "job_type": job_type,
        "job_id": job_id,
        "enqueued_at": int(time.time() * 1000),
        "event": event,
        "user_id": user_id,
    }

    try:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(payload),
            # ✅ STANDARD queue: no MessageGroupId, no MessageDeduplicationId
        )
        log.info(f"✅ Job {job_id} enqueued successfully (user: {user_id})")
        return job_id
    except Exception as e:
        log.error(f"❌ Failed to enqueue job: {e}")
        raise


def get_queue_depth() -> int:
    """Approximate number of outstanding messages (visible + not visible)."""
    try:
        attrs = sqs.get_queue_attributes(
            QueueUrl=QUEUE_URL,
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
            ],
        )
        a = attrs.get("Attributes", {})
        visible = int(a.get("ApproximateNumberOfMessages", "0"))
        inflight = int(a.get("ApproximateNumberOfMessagesNotVisible", "0"))
        return max(visible + inflight, 0)
    except Exception as e:
        log.warning(f"Could not read queue depth: {e}")
        return 1
