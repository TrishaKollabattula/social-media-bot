# Q/jobs_repo.py
"""
DynamoDB repository for tracking job status.
Enhanced with detailed error tracking and user notifications.
"""
import os
import time
import json
import boto3
from decimal import Decimal

REGION = os.getenv("AWS_REGION", "ap-south-1")
TABLE = os.getenv("JOBS_TABLE", "MarketingJobs")

ddb = boto3.resource("dynamodb", region_name=REGION)
table = ddb.Table(TABLE)

def _now_ms():
    """Get current timestamp in milliseconds"""
    return int(time.time() * 1000)

def _sanitize(value):
    """Convert floats to Decimal for DynamoDB"""
    if value is None:
        return None
    return json.loads(json.dumps(value), parse_float=Decimal)

def put_status(job_id: str, status: str, meta: dict = None):
    """
    Update job status in DynamoDB.
    Status can be: queued | in_progress | completed | failed
    """
    item = {
        "job_id": job_id,
        "status": status,
        "updated_at": _now_ms(),
    }
    if meta:
        item["meta"] = _sanitize(meta)

    table.put_item(Item=item)

def get_status(job_id: str) -> dict:
    """Get job status from DynamoDB"""
    try:
        resp = table.get_item(Key={"job_id": job_id})
        return resp.get("Item")
    except Exception as e:
        print(f"Error getting status for {job_id}: {e}")
        return None

def mark_queued(job_id: str, payload: dict = None):
    """Mark job as queued"""
    meta = {
        "payload": payload or {},
        "queued_at": _now_ms()
    }
    put_status(job_id, "queued", meta)

def mark_in_progress(job_id: str):
    """Mark job as in progress"""
    meta = {
        "started_at": _now_ms()
    }
    put_status(job_id, "in_progress", meta)

def mark_completed(job_id: str, result: dict):
    """Mark job as completed with result"""
    meta = {
        "result": result,
        "completed_at": _now_ms()
    }
    put_status(job_id, "completed", meta)

def mark_failed(job_id: str, error_msg: str, technical_error: str = None):
    """
    Mark job as failed with both user-friendly and technical error messages.
    """
    meta = {
        "error": error_msg,  # User-friendly message
        "failed_at": _now_ms()
    }

    if technical_error:
        meta["technical_error"] = technical_error

    put_status(job_id, "failed", meta)
    
def was_completed(job_id: str) -> bool:
    """
    Idempotency helper for Standard SQS (which can deliver duplicates).
    Returns True if job_id already finished successfully.
    """
    item = get_status(job_id)
    return bool(item and item.get("status") == "completed")
