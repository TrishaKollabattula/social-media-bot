# queue_handler.py
import json
import logging
import os
import boto3

from Q.sqs_helpers import enqueue_job, get_queue_depth
from Q.jobs_repo import mark_queued
from Q.notifications import notify_job_queued

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

USERS_TABLE = os.getenv("USERS_TABLE", "Users")
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
AVG_JOB_MINUTES = int(os.getenv("AVG_JOB_MINUTES", "3"))

ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
users_table = ddb.Table(USERS_TABLE)

def _get_user_email(username: str):
    """Fetch user email from DynamoDB Users table."""
    if not username:
        logger.warning("No username provided for email lookup")
        return None
    try:
        resp = users_table.get_item(Key={"username": username})
        item = resp.get("Item")
        if not item:
            logger.warning(f"User '{username}' not found in Users table")
            return None
        email = item.get("email")
        if not email:
            logger.warning(f"User '{username}' has no email field")
            return None
        return email
    except Exception as e:
        logger.error(f"Failed to get user email for '{username}': {e}")
        return None

class QueueHandler:
    def enqueue(self, context):
        """
        Handle job enqueueing with proper error handling and notifications.
        """
        try:
            request = context["request"]
            body = request.get("body")
            
            if not body:
                return {
                    "statusCode": 400,
                    "body": json.dumps({"error": "Request body is required"})
                }
            
            # Parse body
            data = json.loads(body) if isinstance(body, str) else body

            # Extract user information from multiple sources
            claims = context.get("claims", {})
            username = (
                data.get("username") 
                or data.get("userId") 
                or data.get("user_id")
                or claims.get("username")
            )
            
            if not username:
                logger.warning("No username provided in request")
                username = "unknown"
            
            # Set user_id if not present
            data["user_id"] = username
            data["username"] = username

            # Get user email (from request or DynamoDB)
            user_email = (
                data.get("email") 
                or data.get("user_email") 
                or _get_user_email(username)
            )
            
            if user_email:
                data["user_email"] = user_email
                logger.info(f"✅ User email found: {user_email}")
            else:
                logger.warning(f"⚠️  No email found for user '{username}' - notifications will be skipped")

            # Validate required fields
            prompt = data.get("prompt")
            if not prompt:
                return {
                    "statusCode": 400,
                    "body": json.dumps({"error": "Prompt is required"})
                }

            content_type = data.get("contentType")
            if not content_type:
                return {
                    "statusCode": 400,
                    "body": json.dumps({"error": "Content type is required"})
                }

            # Build event for worker
            event = {
                "path": "/content/generate",
                "httpMethod": "POST",
                "headers": request.get("headers", {}),
                "queryStringParameters": request.get("queryStringParameters", {}),
                "body": json.dumps(data),
                "isBase64Encoded": False,
                "user_email": user_email,
            }

            # Enqueue the job
            logger.info(f"📝 Enqueueing job for user '{username}'")
            logger.info(f"📋 Prompt: {prompt[:100]}...")
            
            job_id = enqueue_job(event, job_type="CONTENT_GENERATE")
            
            # Mark as queued in DynamoDB
            mark_queued(job_id, {
                "username": username,
                "prompt": prompt[:200],  # Truncate for storage
                "content_type": content_type,
            })
            
            logger.info(f"✅ Job {job_id} enqueued successfully")

            # Send queued notification email
            if user_email:
                try:
                    position = max(get_queue_depth(), 1)
                    prompt_excerpt = (prompt or "")[:160]
                    notify_job_queued(job_id, user_email, position, prompt_excerpt)
                    logger.info(f"📧 Queued notification sent to {user_email}")
                except Exception as e:
                    logger.warning(f"Failed to send queued notification: {e}")
                    # Don't fail the request if email fails
            else:
                logger.info("⚠️  No email address - skipping queued notification")

            # Calculate estimated time
            queue_depth = max(get_queue_depth(), 1)
            estimated_minutes = queue_depth * AVG_JOB_MINUTES

            # ✅ Return proper Lambda response format
            return {
                "statusCode": 202,
                "body": json.dumps({
                    "status": "queued",
                    "job_id": job_id,
                    "message": "Job has been queued for processing. You will receive email updates.",
                    "queue_position": queue_depth,
                    "estimated_minutes": estimated_minutes,
                })
            }

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in request body: {e}")
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Invalid JSON in request body"})
            }
            
        except ValueError as e:
            logger.error(f"Invalid parameter value: {e}")
            return {
                "statusCode": 400,
                "body": json.dumps({"error": f"Invalid parameter: {str(e)}"})
            }
            
        except Exception as e:
            logger.error(f"❌ Error enqueueing job: {e}", exc_info=True)
            return {
                "statusCode": 500,
                "body": json.dumps({"error": f"Failed to enqueue job: {str(e)}"})
            }

    def get_status(self, context):
        """
        Get job status from DynamoDB.
        """
        try:
            from Q.jobs_repo import get_status
            
            request = context["request"]
            path = request.get("path", "")
            
            # Extract job_id from path: /queue/status/{job_id}
            parts = [p for p in path.strip("/").split("/") if p]
            
            # Find job_id (should be after 'status')
            job_id = None
            for i, part in enumerate(parts):
                if part == "status" and i + 1 < len(parts):
                    job_id = parts[i + 1]
                    break
            
            if not job_id:
                return {
                    "statusCode": 400,
                    "body": json.dumps({"error": "Job ID is required in path: /queue/status/{job_id}"})
                }
            
            logger.info(f"🔍 Getting status for job: {job_id}")
            status = get_status(job_id)
            
            if not status:
                return {
                    "statusCode": 404,
                    "body": json.dumps({"error": "Job not found"})
                }
            
            # Convert Decimal types for JSON serialization
            import decimal
            def decimal_default(obj):
                if isinstance(obj, decimal.Decimal):
                    return float(obj)
                raise TypeError
            
            # Clean response
            response = json.loads(json.dumps(status, default=decimal_default))
            
            logger.info(f"✅ Job status retrieved: {response.get('status', 'unknown')}")
            
            return {
                "statusCode": 200,
                "body": json.dumps(response)
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting job status: {e}", exc_info=True)
            return {
                "statusCode": 500,
                "body": json.dumps({"error": f"Failed to get job status: {str(e)}"})
            }