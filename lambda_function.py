# lambda_function.py - FIXED VERSION
import json
import logging
import os
import jwt
import time
from pathlib import Path
from dotenv import load_dotenv
import importlib

from crm.crm_handler import CRMHandler

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "my-secure-secret-key-12345")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_ORIGINS = {
    "http://localhost:3000",
    "https://postingexpert.com",
    "https://www.postingexpert.com",
}

def _get_origin(event):
    h = event.get("headers") or {}
    return h.get("origin") or h.get("Origin")

def cors_headers(event=None):
    origin = _get_origin(event) if event else None
    allow_origin = origin if origin in ALLOWED_ORIGINS else "https://postingexpert.com"

    return {
        "Access-Control-Allow-Origin": allow_origin,
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Vary": "Origin",
        "Content-Type": "application/json",
    }

def with_cors(event, resp):
    """✅ Ensure every response includes CORS headers."""
    if not isinstance(resp, dict):
        return {
            "statusCode": 200,
            "headers": cors_headers(event),
            "body": json.dumps(resp),
        }

    headers = resp.get("headers") or {}
    merged = {**headers, **cors_headers(event)}
    resp["headers"] = merged

    if "body" not in resp:
        resp["body"] = ""

    return resp

def load_class(module: str, class_name: str):
    module_ref = importlib.import_module(module)
    return getattr(module_ref, class_name)

def call_method(class_obj, method_name, context: dict):
    method = getattr(class_obj, method_name)
    return method(context)

def verify_bearer_token(token: str):
    try:
        decoded_token = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return decoded_token
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token has expired")
        return None
    except jwt.InvalidTokenError:
        logger.error("Invalid JWT token")
        return None

def _get_http_method(event) -> str:
    return (
        (event.get("httpMethod") or "")
        or ((event.get("requestContext") or {}).get("http") or {}).get("method", "")
    ).upper()

def _get_raw_path(event) -> str:
    return (event.get("path") or event.get("rawPath") or "")

def _normalize_path_parts(event):
    """
    ✅ FIX: API Gateway stage prefix breaks routing.
    Example raw path: /prod/user/login
    We strip "prod" if it matches requestContext.stage
    """
    raw_path = _get_raw_path(event).strip("/")
    parts = [p.strip() for p in raw_path.split("/") if p.strip()]

    stage = (event.get("requestContext") or {}).get("stage")
    if stage and parts and parts[0] == stage:
        parts = parts[1:]

    return raw_path, stage, parts

def lambda_handler(event, context):
    try:
        http_method = _get_http_method(event)

        # ✅ OPTIONS preflight must always return CORS
        if http_method == "OPTIONS":
            return with_cors(event, {"statusCode": 200, "body": ""})

        raw_path, stage, path_parts = _normalize_path_parts(event)

        module_key = path_parts[0] if len(path_parts) > 0 else None
        api_key = path_parts[1] if len(path_parts) > 1 else None

        normalized_path = "/" + "/".join(path_parts) if path_parts else "/"
        logger.info(f"Request: {normalized_path} [{http_method}] (raw: /{raw_path}, stage: {stage})")

        # ✅ health
        if "/".join(path_parts) == "health":
            return with_cors(event, {
                "statusCode": 200,
                "body": json.dumps({
                    "status": "ready",
                    "message": "Lambda backend is running",
                    "timestamp": int(time.time())
                })
            })

        # ✅ root
        if not module_key:
            return with_cors(event, {
                "statusCode": 200,
                "body": json.dumps({"ok": True, "message": "✅ Backend is up"})
            })

        # -------------------------------------------
        # ❌ REMOVED HARDCODED QUEUE LOGIC
        # Now all queue requests go through queue_handler.py
        # -------------------------------------------

        # -------------------------------------------
        # AUTH CHECK
        # -------------------------------------------
        skip_auth_paths = [
            ("user", "login"),
            ("user", "register"),
            ("social", None),
        ]

        requires_auth = True
        for skip_module, skip_api in skip_auth_paths:
            if module_key == skip_module:
                if skip_api is None or api_key == skip_api:
                    requires_auth = False
                    break

        claims = None
        if requires_auth:
            headers = event.get("headers", {}) or {}
            auth_header = headers.get("Authorization") or headers.get("authorization")

            if not auth_header or not auth_header.startswith("Bearer "):
                return with_cors(event, {
                    "statusCode": 401,
                    "body": json.dumps({"error": "Authorization header missing or invalid"})
                })

            token = auth_header.split(" ", 1)[1]
            claims = verify_bearer_token(token)
            if not claims:
                return with_cors(event, {
                    "statusCode": 401,
                    "body": json.dumps({"error": "Invalid or expired token"})
                })

        # -------------------------------------------
        # LOAD API MAPPING
        # -------------------------------------------
        api_mapping_file = Path(__file__).absolute().parent / "api-mapping.json"
        logger.info(f"Loading API mapping from: {api_mapping_file}")

        try:
            with open(api_mapping_file, "r") as f:
                api_mapping = json.load(f)
        except Exception as e:
            logger.error(f"API mapping load failed: {e}")
            return with_cors(event, {
                "statusCode": 500,
                "body": json.dumps({"error": "API configuration not found/invalid"})
            })

        if module_key not in api_mapping:
            return with_cors(event, {
                "statusCode": 404,
                "body": json.dumps({"error": f"Module '{module_key}' not found"})
            })

        module_config = api_mapping[module_key]

        # ✅ traverse nested routes
        current_config = module_config
        traversed_parts = 1

        for i in range(1, len(path_parts)):
            part = path_parts[i]
            if isinstance(current_config, dict) and part in current_config:
                current_config = current_config[part]
                traversed_parts = i + 1
                if isinstance(current_config, list):
                    break
            else:
                break

        if not isinstance(current_config, list):
            return with_cors(event, {
                "statusCode": 404,
                "body": json.dumps({"error": f"API endpoint not found: {normalized_path}"})
            })

        apis = current_config
        remaining_path = "/".join(path_parts[traversed_parts:]) if traversed_parts < len(path_parts) else ""

        # -------------------------------------------
        # SELECT API (✅ FIX: allow wildcard path)
        # -------------------------------------------
        selected_api = None
        for api in apis:
            if api.get("request_method", "").upper() != http_method:
                continue

            api_path = api.get("path", "")

            # Exact match
            if api_path == remaining_path:
                selected_api = api
                break

            # ✅ Wildcard support (dynamic segments like job_id)
            if api_path == "*" and remaining_path:
                selected_api = api
                break

        if not selected_api:
            return with_cors(event, {
                "statusCode": 404,
                "body": json.dumps({
                    "error": f"No matching API for {normalized_path} [{http_method}]",
                    "debug": {"remaining_path": remaining_path}
                })
            })

        # -------------------------------------------
        # CALL HANDLER
        # -------------------------------------------
        handler_class = load_class(selected_api["package"], selected_api["class"])
        handler_instance = handler_class()
        handler_context = {"request": event, "claims": claims} if claims else {"request": event}

        response = call_method(handler_instance, selected_api["method"], handler_context)

        if isinstance(response, dict) and "statusCode" in response:
            return with_cors(event, response)

        if isinstance(response, tuple):
            response_body, status_code = response
            body = response_body if isinstance(response_body, str) else json.dumps(response_body)
            return with_cors(event, {"statusCode": status_code, "body": body})

        body = response if isinstance(response, str) else json.dumps(response)
        return with_cors(event, {"statusCode": 200, "body": body})

    except Exception as e:
        logger.error("Error processing request", exc_info=True)
        return with_cors(event, {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        })