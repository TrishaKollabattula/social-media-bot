# server.py - UPDATED (LinkedIn popup callback FIX + keep your queue system)
from flask import Flask, request, jsonify, make_response, Response
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
from refresh_engagement import refresh_bp

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

# ---------------------------
# LinkedIn config
# ---------------------------
CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI")  # MUST MATCH /social/linkedin/callback exactly

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

# ✅ FIXED CORS (Production safe)
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "https://postingexpert.com",
    "https://www.postingexpert.com",
]

CORS(
    app,
    resources={r"/*": {"origins": ALLOWED_ORIGINS}},
    supports_credentials=False,
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
)

@app.route('/')
def home():
    return "Flask server is running!"

# ✅ HEALTH CHECK
@app.route('/health', methods=['GET', 'OPTIONS'])
def health_check():
    if request.method == 'OPTIONS':
        return '', 204
    return jsonify({
        "status": "ready",
        "message": "Flask server is running",
        "timestamp": int(time.time())
    }), 200

@app.route('/favicon.ico')
def favicon():
    return "", 204


app.register_blueprint(refresh_bp)



# ============================================================
# ✅✅✅ LINKEDIN OAUTH POPUP CALLBACK FIX (MOST IMPORTANT)
# Put this BEFORE the catch-all route.
# LinkedIn redirects with GET to /social/linkedin/callback?code=...&state=...
# ============================================================
@app.route("/social/linkedin/callback", methods=["GET"])
def linkedin_oauth_callback_popup():
    """
    LinkedIn redirects here (GET) after user login/consent.
    We exchange code -> access_token -> person_urn
    Then return HTML that runs JS and postMessage() to opener.
    """
    try:
        code = request.args.get("code")
        state = request.args.get("state")  # you passed appUser as state in frontend

        if not code:
            payload = {
                "type": "linkedin_callback",
                "success": False,
                "error": "No authorization code provided",
            }
            html = f"""
            <!doctype html><html><body>
            <script>
              window.opener && window.opener.postMessage({json.dumps(payload)}, "*");
              window.close();
            </script>
            </body></html>
            """
            return Response(html, mimetype="text/html")

        # 1) Exchange code for access token
        token_resp = requests.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20
        )
        token_resp.raise_for_status()
        token_json = token_resp.json()
        access_token = token_json.get("access_token")

        if not access_token:
            raise Exception(f"No access_token returned by LinkedIn: {token_json}")

        # 2) Fetch profile (person id)
        profile_resp = requests.get(
            "https://api.linkedin.com/v2/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20
        )
        profile_resp.raise_for_status()
        profile_data = profile_resp.json()
        person_id = profile_data.get("id")

        if not person_id:
            raise Exception(f"Failed to get person id from LinkedIn: {profile_data}")

        person_urn = f"urn:li:person:{person_id}"

        # ✅ TODO: Save token & person_urn using `state` as appUser
        # Example: save_linkedin_tokens(app_user=state, access_token=access_token, person_urn=person_urn)

        payload = {
            "type": "linkedin_callback",
            "success": True,
            "posting_method": "Personal Profile",
            "organization_count": 0,
            "has_org_access": False,
            "person_urn": person_urn,
            "org_urn": None,
            "message": "LinkedIn connected successfully!"
        }

        html = f"""
        <!doctype html>
        <html>
          <head><meta charset="utf-8"><title>LinkedIn Connected</title></head>
          <body>
            <script>
              (function() {{
                var data = {json.dumps(payload)};
                if (window.opener) {{
                  window.opener.postMessage(data, "*");
                }}
                window.close();
              }})();
            </script>
            <p>LinkedIn connected. You can close this window.</p>
          </body>
        </html>
        """
        return Response(html, mimetype="text/html")

    except Exception as e:
        payload = {
            "type": "linkedin_callback",
            "success": False,
            "error": str(e),
        }
        html = f"""
        <!doctype html><html><body>
        <script>
          window.opener && window.opener.postMessage({json.dumps(payload)}, "*");
          window.close();
        </script>
        <p>LinkedIn connect failed: {str(e)}</p>
        </body></html>
        """
        return Response(html, mimetype="text/html")

# ================== QUEUE ENDPOINTS (YOUR SAME CODE) ==================


@app.route("/user/profile", methods=["GET"])
def user_profile():
    """
    Return user profile from DynamoDB Users table.
    Needs Bearer token that includes username in claims OR fallback localStorage user.
    """
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        return jsonify({"error": "Authorization missing"}), 401

    # ✅ If your JWT has username in it, decode it here (best)
    # For now, quick fallback: accept ?username=...
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "username required (add JWT decode for production)"}), 400

    try:
        resp = users_table.get_item(Key={"username": username})
        item = (resp.get("Item") or {})
        return jsonify({"profile": item}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/queue/enqueue', methods=['POST', 'OPTIONS'])
def queue_enqueue():
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

        username = (
            body_json.get("username")
            or body_json.get("userId")
            or body_json.get("user_id")
            or headers.get("X-User-Resolved")
            or headers.get("X-Username")
            or headers.get("X-App-User")
            or query.get("app_user")
            or _cookie_value(cookie_header, "app_user")
        )

        if username:
            body_json["user_id"] = username
            body_json["username"] = username

        user_email = (
            body_json.get("email")
            or body_json.get("user_email")
            or headers.get("X-User-Email")
            or _find_user_email(username)
        )
        if user_email:
            body_json["user_email"] = user_email

        raw_body = json.dumps(body_json)

        event = {
            "path": "/content/generate",
            "httpMethod": "POST",
            "headers": headers,
            "queryStringParameters": query,
            "body": raw_body,
            "isBase64Encoded": False,
            "user_email": user_email,
        }

        job_id = enqueue_job(event, job_type="CONTENT_GENERATE")
        mark_queued(job_id, {"event": "content/generate", "username": username})

        logger.info(f"✅ Job {job_id} enqueued successfully for user '{username}'")

        try:
            if user_email:
                position = max(get_queue_depth(), 1)
                prompt_excerpt = (body_json.get("prompt") or "")[:160]
                notify_job_queued(job_id, user_email, position, prompt_excerpt)
                logger.info(f"📧 Queued notification sent to {user_email}")
        except Exception as e:
            logger.warning(f"Could not send queued notification: {e}")

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

        return jsonify(json.loads(json.dumps(item, default=decimal_default)))

    except Exception as e:
        logger.error(f"❌ Failed to get job status: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ================== EXISTING ENDPOINTS ==================

@app.route('/trigger-scheduler', methods=["POST"])
def trigger_scheduler():
    try:
        if scheduler_available:
            scheduler_task()
            return jsonify({"status": "Scheduler successfully triggered"}), 200
        else:
            return jsonify({"error": "Scheduler not available"}), 500
    except Exception as e:
        logger.error(f"Error triggering scheduler: {e}")
        return jsonify({"error": str(e)}), 500

# ❌ Your old /linkedin/callback (POST) is NOT used by popup OAuth flow.
# You can keep it if something else calls it, but it won't fix popup.
# If you want, you can delete it safely.
# -------------------------------------------------------
# @app.route('/linkedin/callback', methods=["POST"])
# def linkedin_callback():
#     ...

# ================== CATCH-ALL (lambda routing) ==================
# IMPORTANT: must be AFTER /social/linkedin/callback route
@app.route('/<path:path>', methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
def handle_request(path):
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
    if isinstance(response.get("body"), str) and response["body"].strip():
        try:
            response_body = json.loads(response["body"])
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON response body: {response['body'][:100]}")
            response_body = {"message": response["body"]}
    else:
        response_body = response.get("body") if response.get("body") is not None else {}

    return jsonify(response_body), response["statusCode"]

# ================== WORKER & SCHEDULER STARTUP ==================

def start_worker_background():
    t = threading.Thread(target=start_worker_loop, daemon=True, name="QWorkerThread")
    t.start()
    logger.info("🚀 SQS Worker thread started")
    return t

def start_scheduler_safe():
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

    start_worker_background()

    if scheduler_available:
        threading.Thread(target=start_scheduler_safe, daemon=True).start()
        logger.info("📅 Scheduler thread started")
    else:
        logger.warning("⚠️ No scheduler available")

    logger.info("=" * 60)
    logger.info("✅ Server ready on http://0.0.0.0:5000")
    logger.info("=" * 60)

    app.run(host="0.0.0.0", port=5000, debug=False)
