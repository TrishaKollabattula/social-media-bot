#!/usr/bin/env python3
"""
diagnose_queue.py (STANDARD SQS)

Diagnostic script to verify:
1) ENV is pointing to the correct Standard queue
2) Queue is accessible with current AWS credentials
3) Sending a test message works (NO FIFO params)
4) Receiving a message works
5) Optionally deleting the received message (safe toggle)

Usage:
  python diagnose_queue.py

Env vars:
  QUEUE_URL (required)  -> Standard queue URL
  AWS_REGION (optional) -> default ap-south-1
  DIAG_DELETE (optional)-> "true" to delete received message (default false)
"""

import os
import json
import time
import boto3
from dotenv import load_dotenv

load_dotenv()

QUEUE_URL = os.getenv(
    "QUEUE_URL",
    "https://sqs.ap-south-1.amazonaws.com/509399605320/postingexpert-standard-queue",
)
REGION = os.getenv("AWS_REGION", "ap-south-1")

# If set to true, the script will delete the received message.
DELETE_AFTER_RECEIVE = os.getenv("DIAG_DELETE", "false").lower() in ("1", "true", "yes")

sqs = boto3.client("sqs", region_name=REGION)

print("=" * 90)
print("DIAGNOSTIC (STANDARD SQS): Queue Send/Receive Check")
print("=" * 90)

# 1) Check queue URL
print("\n1️⃣ Queue URL Configuration:")
print(f"   AWS_REGION: {REGION}")
print(f"   QUEUE_URL:  {QUEUE_URL}")

# 2) Check if queue exists and is accessible
print("\n2️⃣ Checking SQS Queue Accessibility:")
try:
    attrs = sqs.get_queue_attributes(QueueUrl=QUEUE_URL, AttributeNames=["All"])
    print("   ✅ Queue is accessible")

    arn = attrs["Attributes"].get("QueueArn")
    qtype = attrs["Attributes"].get("FifoQueue", "false")
    print(f"   Queue ARN: {arn}")
    print(f"   FifoQueue attribute: {qtype}  (should be 'false' for Standard)")

    stats = {
        "visible": int(attrs["Attributes"].get("ApproximateNumberOfMessages", 0)),
        "in_flight": int(attrs["Attributes"].get("ApproximateNumberOfMessagesNotVisible", 0)),
        "delayed": int(attrs["Attributes"].get("ApproximateNumberOfMessagesDelayed", 0)),
    }

    print("\n3️⃣ Current Queue Status:")
    print(f"   Visible messages:   {stats['visible']}")
    print(f"   In-flight messages: {stats['in_flight']}")
    print(f"   Delayed messages:   {stats['delayed']}")
    print(f"   TOTAL:              {sum(stats.values())}")

except Exception as e:
    print(f"   ❌ Cannot access queue: {e}")
    print("   Check AWS credentials (IAM role or access keys) and QUEUE_URL")
    print("=" * 90)
    raise SystemExit(1)

# 4) Test sending a message (STANDARD: no FIFO params)
print("\n4️⃣ Testing Message Send (Standard queue):")
test_job_id = f"diagnostic-{int(time.time())}"
test_payload = {
    "job_id": test_job_id,
    "job_type": "TEST",
    "message": "Diagnostic test message (Standard SQS)",
    "sent_at": int(time.time() * 1000),
}

try:
    response = sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(test_payload),
        # ✅ STANDARD: do NOT include MessageGroupId / MessageDeduplicationId
    )
    print("   ✅ Test message sent successfully")
    print(f"   MessageId: {response.get('MessageId')}")

except Exception as e:
    print(f"   ❌ Failed to send test message: {e}")
    print("   If you previously used FIFO, make sure your queue URL is NOT a .fifo queue.")
    print("=" * 90)
    raise SystemExit(1)

# Confirm it appears in queue (best-effort)
time.sleep(2)
try:
    attrs2 = sqs.get_queue_attributes(
        QueueUrl=QUEUE_URL, AttributeNames=["ApproximateNumberOfMessages"]
    )
    count = int(attrs2["Attributes"].get("ApproximateNumberOfMessages", 0))
    print(f"   ✅ Approx visible messages after send: {count}")
except Exception as e:
    print(f"   ⚠️ Could not re-check count: {e}")

# 5) Attempt to receive a message
print("\n5️⃣ Attempting to Receive Message (like worker):")
try:
    recv = sqs.receive_message(
        QueueUrl=QUEUE_URL,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=10,      # long polling
        VisibilityTimeout=30,    # short for diagnostics
    )

    messages = recv.get("Messages", [])
    if not messages:
        print("   ⚠️ No messages received.")
        print("   Possible reasons:")
        print("   - Queue is empty (someone else consumed it)")
        print("   - Worker is consuming instantly")
        print("   - Permissions issue for ReceiveMessage")
    else:
        msg = messages[0]
        body = json.loads(msg.get("Body", "{}"))
        receipt = msg.get("ReceiptHandle")

        print(f"   ✅ Received 1 message")
        print(f"   Received job_id:   {body.get('job_id')}")
        print(f"   Received job_type: {body.get('job_type')}")
        print(f"   Body keys:         {list(body.keys())}")

        if DELETE_AFTER_RECEIVE:
            sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=receipt)
            print("   🗑️ Deleted received message (DIAG_DELETE=true)")
        else:
            print("   ℹ️ Not deleting message (DIAG_DELETE=false).")
            print("      It will become visible again after VisibilityTimeout.")

except Exception as e:
    print(f"   ❌ Failed to receive message: {e}")
    print("   Check IAM permissions for sqs:ReceiveMessage and sqs:DeleteMessage (if deleting).")

print("\n" + "=" * 90)
print("SUMMARY:")
print("=" * 90)

# Final status snapshot
try:
    attrs3 = sqs.get_queue_attributes(
        QueueUrl=QUEUE_URL,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )
    visible = int(attrs3["Attributes"].get("ApproximateNumberOfMessages", 0))
    inflight = int(attrs3["Attributes"].get("ApproximateNumberOfMessagesNotVisible", 0))
    print(f"Visible messages:   {visible}")
    print(f"In-flight messages: {inflight}")

    if visible > 0:
        print("\n✅ Messages exist in queue (good). If worker isn't processing:")
        print("   - Confirm worker QUEUE_URL matches this Standard queue URL")
        print("   - Confirm worker has permissions to ReceiveMessage/DeleteMessage")
        print("   - Check worker logs for JSON errors or handler failures")
    elif inflight > 0:
        print("\n⏳ Messages are currently being processed (in-flight).")
        print("   Wait for worker to finish or check worker logs.")
    else:
        print("\n✅ Queue looks empty right now.")
        print("   Either messages were processed, or none are pending.")

except Exception as e:
    print(f"⚠️ Could not fetch final queue status: {e}")

print("=" * 90)
