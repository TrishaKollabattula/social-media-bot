#lambda_function.py
import json
import logging
import os
import jwt
import time
from pathlib import Path
from dotenv import load_dotenv
import importlib
from crm.crm_handler import CRMHandler
from Q.sqs_helpers import enqueue_job
from Q.jobs_repo import get_status

# Load environment variables
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "my-secure-secret-key-12345")

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

def lambda_handler(event, context):
    try:
        if event.get("httpMethod") == "OPTIONS":
            return {
                "statusCode": 200,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization",
                },
                "body": ""
            }

        # ✅ ADD THIS HEALTH CHECK BLOCK
        path = event.get("path", "").strip("/")
        # Health check endpoint - NO AUTH required
        if path == "health":
            return {
                "statusCode": 200,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "application/json",
                },
                "body": json.dumps({
                    "status": "ready", 
                    "message": "Backend server is running",
                    "timestamp": int(time.time()) if 'time' in dir() else None
                })
            }
            
        path_parts = [part.strip() for part in path.split("/")]
        
        module_key = path_parts[0] if len(path_parts) > 0 else None
        api_key = path_parts[1] if len(path_parts) > 1 else None

        logger.info(f"Request: {path} [{event.get('httpMethod')}]")

        # -------------------------------------------
        # QUEUE ENDPOINTS (handled here, bypass mapping)
        # -------------------------------------------
        if module_key == "queue":
            http_method = event.get("httpMethod", "").upper()

            # POST /queue/enqueue
            if api_key == "enqueue" and http_method == "POST":
                # Build a normalized "content/generate" event for the worker
                normalized_event = {
                    "path": "/content/generate",
                    "httpMethod": "POST",
                    "headers": event.get("headers", {}),
                    "queryStringParameters": event.get("queryStringParameters", {}),
                    "body": event.get("body") or "{}",   # pass through original body
                    "isBase64Encoded": False
                }

                job_id = enqueue_job(normalized_event, job_type="CONTENT_GENERATE")
                # write initial row so status is immediately visible to clients
                from Q.jobs_repo import mark_queued
                mark_queued(job_id, {"event": "content/generate"})

                return {
                    "statusCode": 202,
                    "headers": {
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                        "Access-Control-Allow-Headers": "Content-Type, Authorization",
                        "Content-Type": "application/json"
                    },
                    "body": json.dumps({"job_id": job_id, "status": "queued"})
                }

            # GET /queue/status/<job_id>
            if api_key == "status" and http_method == "GET":
                job_id = path_parts[2] if len(path_parts) > 2 else None
                if not job_id:
                    return {
                        "statusCode": 400,
                        "headers": {"Access-Control-Allow-Origin": "*"},
                        "body": json.dumps({"error": "Missing job_id in path: /queue/status/<job_id>"})
                    }

                item = get_status(job_id)
                if not item:
                    return {
                        "statusCode": 404,
                        "headers": {"Access-Control-Allow-Origin": "*"},
                        "body": json.dumps({"error": "job_id not found"})
                    }

                return {
                    "statusCode": 200,
                    "headers": {
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                        "Access-Control-Allow-Headers": "Content-Type, Authorization",
                        "Content-Type": "application/json"
                    },
                    "body": json.dumps(item)
                }

        # -------------------------------------------
        # AUTHENTICATION CHECK (skip for some routes)
        # -------------------------------------------
        skip_auth_paths = [
            ("user", "login"),
            ("user", "register"),
            ("social", None),  # All social callbacks
        ]
        
        requires_auth = True
        for skip_module, skip_api in skip_auth_paths:
            if module_key == skip_module:
                if skip_api is None or api_key == skip_api:
                    requires_auth = False
                    break

        claims = None
        if requires_auth:
            headers = event.get("headers", {})
            auth_header = headers.get("Authorization") or headers.get("authorization")
            
            if not auth_header or not auth_header.startswith("Bearer "):
                return {
                    "statusCode": 401,
                    "headers": {"Access-Control-Allow-Origin": "*"},
                    "body": json.dumps({"error": "Authorization header missing or invalid"})
                }
            
            token = auth_header.split(" ")[1]
            claims = verify_bearer_token(token)
            
            if not claims:
                return {
                    "statusCode": 401,
                    "headers": {"Access-Control-Allow-Origin": "*"},
                    "body": json.dumps({"error": "Invalid or expired token"})
                }

        # -------------------------------------------
        # LOAD API MAPPING
        # -------------------------------------------
        if not module_key:
            return {
                "statusCode": 200,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "text/plain",
                },
                "body": "✅ Backend is up and running!"
            }

        api_mapping_file = Path(__file__).absolute().parent / "api-mapping.json"
        logger.info(f"Loading API mapping from: {api_mapping_file}")
        
        try:
            with open(api_mapping_file, "r") as f:
                api_mapping = json.load(f)
            logger.info(f"API mapping loaded successfully with {len(api_mapping)} modules")
        except FileNotFoundError:
            logger.error(f"API mapping file not found: {api_mapping_file}")
            return {
                "statusCode": 500,
                "headers": {"Access-Control-Allow-Origin": "*"},
                "body": json.dumps({"error": "API configuration not found"})
            }
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in API mapping: {e}")
            return {
                "statusCode": 500,
                "headers": {"Access-Control-Allow-Origin": "*"},
                "body": json.dumps({"error": "Invalid API configuration"})
            }

        if module_key not in api_mapping:
            return {
                "statusCode": 404,
                "headers": {"Access-Control-Allow-Origin": "*"},
                "body": json.dumps({"error": f"Module '{module_key}' not found in API mapping"})
            }

        module_config = api_mapping[module_key]
        
        # ✅ FIXED: Handle nested routes (e.g., social/linkedin/callback)
        current_config = module_config
        traversed_parts = 1  # Start after module_key
        
        # Traverse nested structure
        for i in range(1, len(path_parts)):
            part = path_parts[i]
            if isinstance(current_config, dict) and part in current_config:
                current_config = current_config[part]
                traversed_parts = i + 1
                
                # If we hit a list, we found the endpoint
                if isinstance(current_config, list):
                    break
            else:
                # Path not found in structure
                break
        
        # Check if we found a valid endpoint (list of APIs)
        if not isinstance(current_config, list):
            return {
                "statusCode": 404,
                "headers": {"Access-Control-Allow-Origin": "*"},
                "body": json.dumps({"error": f"API endpoint not found: {path}"})
            }
        
        apis = current_config
        
        # ✅ FIXED: Calculate remaining path correctly
        # For /social/linkedin/callback with traversed_parts=3, remaining should be ""
        remaining_path = "/".join(path_parts[traversed_parts:]) if traversed_parts < len(path_parts) else ""

        # Find matching API based on HTTP method and remaining path
        http_method = event.get("httpMethod", "").upper()
        selected_api = None

        logger.info(f"Looking for: method={http_method}, path='{remaining_path}', traversed={traversed_parts}")

        for api in apis:
            api_path = api.get("path", "")
            
            logger.debug(f"Checking API: method={api['request_method']}, path='{api_path}'")
            
            if api["request_method"].upper() == http_method and api_path == remaining_path:
                selected_api = api
                logger.info(f"✅ Matched API: {api['package']}.{api['class']}.{api['method']}")
                break

        if not selected_api:
            return {
                "statusCode": 404,
                "headers": {"Access-Control-Allow-Origin": "*"},
                "body": json.dumps({
                    "error": f"No matching API found for path: {path} and method: {http_method}",
                    "debug": {
                        "path_parts": path_parts,
                        "remaining_path": remaining_path,
                        "http_method": http_method
                    }
                })
            }

        # -------------------------------------------
        # CALL HANDLER
        # -------------------------------------------
        package_name = selected_api["package"]
        class_name = selected_api["class"]
        method_name = selected_api["method"]

        handler_class = load_class(package_name, class_name)
        handler_instance = handler_class()
        handler_context = {"request": event, "claims": claims} if claims else {"request": event}
        response = call_method(handler_instance, method_name, handler_context)

        # Return response
        if isinstance(response, dict) and "statusCode" in response:
            return response
        elif isinstance(response, tuple):
            response_body, status_code = response
            return {
                "statusCode": status_code,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization",
                    "Content-Type": "application/json"
                },
                "body": json.dumps(response_body) if not isinstance(response_body, str) else response_body,
            }
        else:
            return {
                "statusCode": 200,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization",
                    "Content-Type": "application/json"
                },
                "body": json.dumps(response) if not isinstance(response, str) else response,
            }

    except Exception as e:
        logger.error("Error processing request", exc_info=True)
        
        error_message = str(e)
        
        if "already exists" in error_message.lower():
            status_code = 409
        elif "invalid" in error_message.lower() or "required" in error_message.lower():
            status_code = 400
        elif "unauthorized" in error_message.lower() or "token" in error_message.lower():
            status_code = 401
        elif "not found" in error_message.lower():
            status_code = 404
        else:
            status_code = 500
        
        return {
            "statusCode": status_code,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*",
                "Content-Type": "application/json"
            },
            "body": json.dumps({"error": error_message})
        }