from flask import Flask, request, jsonify, make_response
import json
import os
import requests
from dotenv import load_dotenv

from lambda_function import lambda_handler
from flask_cors import CORS
from scheduler import scheduler_task, run_scheduler

# ✅ Load .env
load_dotenv()

# ✅ LinkedIn config
CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI")

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "http://marketing-bot-frontend.s3-website.ap-south-1.amazonaws.com"}})

@app.route('/')
def home():
    return "Flask server is running!"

@app.route('/trigger-scheduler', methods=["POST"])
def trigger_scheduler():
    try:
        scheduler_task()
        return jsonify({"status": "Scheduler successfully triggered"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ✅ LinkedIn OAuth callback: exchanges code for access_token + real profile.id
@app.route('/linkedin/callback', methods=["POST"])
def linkedin_callback():
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

        # ✅ Get real ID for posting
        profile_resp = requests.get(
            "https://api.linkedin.com/v2/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        profile_data = profile_resp.json()
        print("[DEBUG] /v2/me:", profile_data)

        person_id = profile_data.get("id")
        if not person_id:
            return jsonify({"error": "Failed to get person ID"}), 400

        person_urn = f"urn:li:person:{person_id}"

        return jsonify({
            "access_token": access_token,
            "person_urn": person_urn
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/<path:path>', methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
def handle_request(path):
    print("Incoming Headers:", request.headers)
    event = {
        "path": f"/{path}",
        "httpMethod": request.method,
        "headers": dict(request.headers),
        "queryStringParameters": request.args.to_dict(),
        "body": request.data.decode("utf-8") if request.data else None,
        "isBase64Encoded": False
    }

    response = lambda_handler(event, None)

    if isinstance(response["body"], str) and response["body"].strip():
        response_body = json.loads(response["body"])
    else:
        response_body = response["body"] if response["body"] is not None else {}

    flask_response = make_response(jsonify(response_body), response["statusCode"])
    flask_response.headers["Access-Control-Allow-Origin"] = "*"
    flask_response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    flask_response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"

    return flask_response

if __name__ == "__main__":
    import threading
    threading.Thread(target=run_scheduler, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=True)