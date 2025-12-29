# Q/worker.py
import os
import json
import time
import logging
import boto3

from Q.engine import run_job
from Q.jobs_repo import mark_queued, was_completed

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("Q.worker")

# ---------------------------------------------------------------------------
# SQS config (STANDARD QUEUE)
# ---------------------------------------------------------------------------
QUEUE_URL = os.getenv(
    "QUEUE_URL",
    "https://sqs.ap-south-1.amazonaws.com/509399605320/postingexpert-standard-queue",
)
REGION = os.getenv("AWS_REGION", "ap-south-1")

# Long polling (recommended)
WAIT_TIME = int(os.getenv("SQS_WAIT_TIME", "20"))

# For STANDARD queues:
# - This is the time a worker has to finish processing before SQS may redeliver.
VISIBILITY_TIMEOUT = int(os.getenv("SQS_VISIBILITY_TIMEOUT", "300"))  # 5 minutes

sqs = None


def init_sqs() -> bool:
    """Initialize SQS client and sanity-check connectivity."""
    global sqs
    try:
        log.info("🔗 Connecting to SQS...")
        log.info(f"   Queue: {QUEUE_URL}")
        log.info(f"   Region: {REGION}")

        sqs = boto3.client("sqs", region_name=REGION)

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
        log.info(f"✅ SQS connected! Messages in queue: {visible} (in-flight: {inflight})")
        return True

    except Exception as e:
        log.error(f"❌ SQS connection failed: {e}")
        log.error("   Check QUEUE_URL in .env file")
        log.error("   Check AWS credentials (IAM role or access keys)")
        return False


def _process_once() -> bool:
    """
    Poll for a single message and process it.

    STANDARD QUEUE IMPORTANT BEHAVIOR:
    - Delete message ONLY if processing succeeds.
    - If processing fails, DO NOT delete -> SQS will retry after VisibilityTimeout.
    - Standard queues can deliver duplicates -> use DynamoDB idempotency check.
    """
    resp = sqs.receive_message(
        QueueUrl=QUEUE_URL,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=WAIT_TIME,
        VisibilityTimeout=VISIBILITY_TIMEOUT,
    )

    msgs = resp.get("Messages", [])
    if not msgs:
        return False

    msg = msgs[0]
    receipt = msg["ReceiptHandle"]
    raw_body = msg.get("Body", "{}")

    job_id = None
    processed_ok = False  # controls delete behavior

    try:
        payload = json.loads(raw_body)
        job_id = payload.get("job_id")

        log.info("📨 Received message from queue")
        log.info(f"   job_id = {job_id}")

        # If no job_id, treat as malformed and drop it
        if not job_id:
            log.warning("⚠️ Message has no job_id. Deleting as malformed.")
            processed_ok = True
            return True

        # ✅ Idempotency: Standard SQS may deliver duplicates
        try:
            if was_completed(job_id):
                log.warning(
                    f"🔁 Duplicate delivery detected. Job {job_id} already completed. Deleting message."
                )
                processed_ok = True
                return True
        except Exception as e:
            # If DDB check fails, we still attempt processing (better than dropping)
            log.exception(f"⚠️ was_completed() check failed for job {job_id}: {e}")

        # Mark as queued in DynamoDB for UI polling (best-effort)
        try:
            mark_queued(job_id, payload)
            log.info(f"📝 Job {job_id} marked as queued in DDB")
        except Exception as e:
            log.exception(f"⚠️ Could not mark job {job_id} as queued: {e}")

        # Run the job (run_job handles in_progress/completed/failed + notifications)
        run_job(payload)
        processed_ok = True
        log.info(f"✅ Finished processing job {job_id}")

        return True

    except json.JSONDecodeError:
        # Bad payload – drop it so it doesn't poison the queue forever
        log.exception("❌ Failed to decode SQS message body as JSON; deleting bad message.")
        processed_ok = True
        return True

    except Exception as e:
        # Processing failure: do NOT delete so SQS retries automatically
        processed_ok = False
        log.exception(f"❌ Error processing message (job_id={job_id}): {e}")
        return True

    finally:
        try:
            if processed_ok:
                sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=receipt)
                log.info(f"🗑️ Message deleted from queue (job_id={job_id})")
            else:
                log.warning(
                    f"⚠️ Not deleting message (job_id={job_id}) because processing failed. "
                    f"It will be retried after visibility timeout ({VISIBILITY_TIMEOUT}s)."
                )
        except Exception as e:
            log.exception(f"⚠️ Failed to delete SQS message (job_id={job_id}): {e}")


def run_forever():
    """Main worker loop."""
    log.info("🚀 Worker started!")
    log.info(f"📡 Polling queue: {QUEUE_URL}")
    log.info(f"⏳ Wait time: {WAIT_TIME}s, Visibility timeout: {VISIBILITY_TIMEOUT}s")

    if not init_sqs():
        log.error("❌ Worker cannot start — SQS connection failed")
        return

    log.info("🔄 Starting polling loop...")

    while True:
        try:
            got_message = _process_once()
            if not got_message:
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("👋 Worker stopped by user")
            break
        except Exception as e:
            log.exception(f"❌ Worker error (outer loop): {e}")
            time.sleep(5)


if __name__ == "__main__":
    run_forever()
