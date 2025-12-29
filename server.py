# server.py - FIXED CORS ISSUES
from flask import Flask, request, jsonify, make_response
import json
import os
import requests
from dotenv import load_dotenv
load_dotenv()
import threading
import traceback
import time
import logging
import boto3

# ✅ QUEUE SYSTEM IMPORTS
from Q.worker import run_forever as start_worker_loop
from Q.sqs_helpers import enqueue_job, get_queue_depth
from Q.jobs_repo import get_status, mark_queued
from Q.notifications import notify_job_queued

from lambda_function import lambda_handler
from flask_cors import CORS

# Scheduler imports
try:
    from scheduler import scheduler_task, run_scheduler
    scheduler_available = True
except ImportError as e:
    print(f"Warning: Could not import scheduler: {e}")
    scheduler_available = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# LinkedIn config
CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI")

# AWS config for user lookup
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
USERS_TABLE = os.getenv("USERS_TABLE", "Users")
AVG_JOB_MINUTES = int(os.getenv("AVG_JOB_MINUTES", "3"))

ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
users_table = ddb.Table(USERS_TABLE)

def _find_user_email(username: str):
    """Look up user email from DynamoDB Users table."""
    if not username:
        return None
    try:
        resp = users_table.get_item(Key={"username": username})
        return (resp.get("Item") or {}).get("email")
    except Exception as e:
        logger.warning(f"Users table lookup failed: {e}")
        return None

def _cookie_value(cookie_header: str, key: str):
    """Extract value from cookie header."""
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith(key + "="):
            return part.split("=", 1)[1]
    return None

app = Flask(__name__)

# ✅ FIXED CORS - Simplified configuration
CORS(app, 
     resources={r"/*": {"origins": "*"}},  # Allow all origins for now
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

@app.route('/')
def home():
    return "Flask server is running!"
# ✅ ADD THIS HEALTH CHECK ROUTE
@app.route('/health', methods=['GET', 'OPTIONS'])
def health_check():
    """Health check endpoint - indicates server is fully ready."""
    if request.method == 'OPTIONS':
        return '', 204
    
    return jsonify({
        "status": "ready",
        "message": "Flask server is running",
        "timestamp": int(time.time())
    }), 200
# ✅ END OF HEALTH CHECK ROUTE


@app.route('/favicon.ico')
def favicon():
    return "", 204

# ================== QUEUE ENDPOINTS (FIXED) ==================

@app.route('/queue/enqueue', methods=['POST', 'OPTIONS'])
def queue_enqueue():
    """
    Enqueue a content generation job.
    Users get immediate confirmation and email notification.
    """
    # ✅ Let Flask-CORS handle OPTIONS automatically
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        raw_body = request.data.decode("utf-8") if request.data else "{}"
        try:
            body_json = json.loads(raw_body or "{}")
        except json.JSONDecodeError:
            body_json = {}

        headers = dict(request.headers)
        query = request.args.to_dict()
        cookie_header = headers.get("Cookie") or headers.get("cookie") or ""

        # Resolve username from multiple places
        username = (
            body_json.get("username")
            or body_json.get("userId")
            or body_json.get("user_id")  # ✅ Added
            or headers.get("X-User-Resolved")
            or headers.get("X-Username")
            or headers.get("X-App-User")
            or query.get("app_user")
            or _cookie_value(cookie_header, "app_user")
        )

        # Ensure user_id present for downstream handlers
        if username:
            body_json["user_id"] = username
            body_json["username"] = username  # ✅ Added

        # Resolve email
        user_email = (
            body_json.get("email")
            or body_json.get("user_email")
            or headers.get("X-User-Email")
            or _find_user_email(username)
        )
        if user_email:
            body_json["user_email"] = user_email

        # Re-serialize the corrected body
        raw_body = json.dumps(body_json)

        # Build event for worker
        event = {
            "path": "/content/generate",
            "httpMethod": "POST",
            "headers": headers,
            "queryStringParameters": query,
            "body": raw_body,
            "isBase64Encoded": False,
            "user_email": user_email,
        }

        # Enqueue the job
        job_id = enqueue_job(event, job_type="CONTENT_GENERATE")
        mark_queued(job_id, {"event": "content/generate", "username": username})

        logger.info(f"✅ Job {job_id} enqueued successfully for user '{username}'")

        # Send queued email notification
        try:
            if user_email:
                position = max(get_queue_depth(), 1)
                prompt_excerpt = (body_json.get("prompt") or "")[:160]
                notify_job_queued(job_id, user_email, position, prompt_excerpt)
                logger.info(f"📧 Queued notification sent to {user_email}")
        except Exception as e:
            logger.warning(f"Could not send queued notification: {e}")

        # Response - Flask-CORS will add headers automatically
        queue_depth = max(get_queue_depth(), 1)
        return jsonify({
            "job_id": job_id,
            "status": "queued",
            "queue_position": queue_depth,
            "estimated_minutes": queue_depth * max(AVG_JOB_MINUTES, 1),
            "message": "Job queued successfully. Check your email for updates."
        }), 202

    except Exception as e:
        logger.error(f"❌ Failed to enqueue job: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/queue/status/<job_id>', methods=['GET', 'OPTIONS'])
def queue_status(job_id):
    """
    Get job status by job_id.
    """
    # ✅ Let Flask-CORS handle OPTIONS automatically
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        item = get_status(job_id)
        if not item:
            return jsonify({"error": "job_id not found"}), 404

        import decimal
        def decimal_default(obj):
            if isinstance(obj, decimal.Decimal):
                return float(obj)
            raise TypeError

        # Flask-CORS will add headers automatically
        return jsonify(json.loads(json.dumps(item, default=decimal_default)))

    except Exception as e:
        logger.error(f"❌ Failed to get job status: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ================== EXISTING ENDPOINTS ==================

@app.route('/trigger-scheduler', methods=["POST"])
def trigger_scheduler():
    """Manually trigger the scheduler."""
    try:
        if scheduler_available:
            scheduler_task()
            return jsonify({"status": "Scheduler successfully triggered"}), 200
        else:
            return jsonify({"error": "Scheduler not available"}), 500
    except Exception as e:
        logger.error(f"Error triggering scheduler: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/linkedin/callback', methods=["POST"])
def linkedin_callback():
    """LinkedIn OAuth callback."""
    try:
        data = request.json
        code = data.get("code")
        if not code:
            return jsonify({"error": "No authorization code provided"}), 400

        token_resp = requests.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        profile_resp = requests.get(
            "https://api.linkedin.com/v2/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        profile_data = profile_resp.json()
        person_id = profile_data.get("id")

        if not person_id:
            return jsonify({"error": "Failed to get person ID"}), 400

        person_urn = f"urn:li:person:{person_id}"

        return jsonify({"access_token": access_token, "person_urn": person_urn})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/<path:path>', methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
def handle_request(path):
    """
    Handle all other requests via lambda_handler.
    """
    # ✅ Let Flask-CORS handle OPTIONS automatically
    if request.method == 'OPTIONS':
        return '', 204
    
    event = {
        "path": f"/{path}",
        "httpMethod": request.method,
        "headers": dict(request.headers),
        "queryStringParameters": request.args.to_dict(),
        "body": request.data.decode("utf-8") if request.data else None,
        "isBase64Encoded": False
    }

    response = lambda_handler(event, None)

    # Handle HTML responses
    content_type = response.get("headers", {}).get("Content-Type", "")
    if "text/html" in content_type:
        flask_response = make_response(response["body"], response["statusCode"])
        flask_response.headers["Content-Type"] = "text/html"
        return flask_response

    # Handle JSON responses
    if isinstance(response["body"], str) and response["body"].strip():
        try:
            response_body = json.loads(response["body"])
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON response body: {response['body'][:100]}")
            response_body = {"message": response["body"]}
    else:
        response_body = response["body"] if response["body"] is not None else {}

    # Flask-CORS adds headers automatically
    return jsonify(response_body), response["statusCode"]

# ================== WORKER & SCHEDULER STARTUP ==================

def start_worker_background():
    """Start the SQS worker in a background thread."""
    t = threading.Thread(target=start_worker_loop, daemon=True, name="QWorkerThread")
    t.start()
    logger.info("🚀 SQS Worker thread started")
    return t

def start_scheduler_safe():
    """Start scheduler in background if available."""
    if scheduler_available:
        logger.info("📅 Starting scheduler in background thread...")
        try:
            run_scheduler()
        except Exception as e:
            logger.error(f"Scheduler failed: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
    else:
        logger.warning("⚠️ No scheduler available - server will run without scheduler")

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("🚀 Starting Marketing Bot Server")
    logger.info("=" * 60)
    
    # Start worker thread
    start_worker_background()
    
    # Start scheduler thread
    if scheduler_available:
        threading.Thread(target=start_scheduler_safe, daemon=True).start()
        logger.info("📅 Scheduler thread started")
    else:
        logger.warning("⚠️ No scheduler available")
    
    logger.info("=" * 60)
    logger.info("✅ Server ready on http://0.0.0.0:5000")
    logger.info("=" * 60)
    
    # Start Flask app (debug=False for production)
    app.run(host="0.0.0.0", port=5000, debug=False)