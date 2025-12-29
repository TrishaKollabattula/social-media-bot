import json
import os
from crm_handler import CRMHandler

handler_instance = None

def _get_handler():
    global handler_instance
    if handler_instance is None:
        handler_instance = CRMHandler()
    return handler_instance

def _response(body, status=200, headers=None):
    base_headers = {
        "Content-Type": "application/json",
        # CORS (adjust origin for prod)
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS"
    }
    if headers:
        base_headers.update(headers)
    return {
        "statusCode": status,
        "headers": base_headers,
        "body": json.dumps(body)
    }

def _mk_ctx_from_event(event):
    """Convert API Gateway event -> your CRMHandler's expected shape."""
    method = event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod", "")
    raw_query = event.get("queryStringParameters") or {}
    body_raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        # if needed, decode here
        import base64
        body_raw = base64.b64decode(body_raw).decode("utf-8")
    return {
        "request": {
            "method": method,
            "queryStringParameters": raw_query,
            "body": body_raw
        }
    }

def handler(event, context):
    """
    Single Lambda entry for all routes.
    Map (method, path) -> CRMHandler methods.
    """
    # Preflight CORS
    if (event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS" or
        event.get("httpMethod") == "OPTIONS"):
        return _response({"ok": True}, 200)

    path = event.get("rawPath") or event.get("path", "")
    method = event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod", "GET")

    h = _get_handler()
    ctx = _mk_ctx_from_event(event)

    try:
        # ====== ROUTES your React calls ======
        if method == "GET" and path == "/crm/dashboard":
            res, status = h.get_dashboard(ctx)
            return _response(res, status)

        if method == "GET" and path == "/crm/pipeline":
            res, status = h.get_lead_pipeline(ctx)
            return _response(res, status)

        if method == "GET" and path == "/crm/leads":
            res, status = h.get_leads(ctx)
            return _response(res, status)

        if method == "PUT" and path == "/crm/leads/status":
            res, status = h.update_lead_status(ctx)
            return _response(res, status)

        if method == "GET" and path == "/crm/comments":
            res, status = h.get_comments(ctx)
            return _response(res, status)

        if method == "GET" and path == "/crm/analytics":
            res, status = h.get_analytics(ctx)
            return _response(res, status)

        if method == "POST" and path == "/crm/dms/process":
            res, status = h.process_pending_dms(ctx)
            return _response(res, status)

        # ====== Optional: webhooks (wire later) ======
        if method == "POST" and path == "/webhooks/instagram":
            res, status = h.handle_instagram_webhook(ctx)
            return _response(res, status)

        if method == "POST" and path == "/webhooks/linkedin":
            res, status = h.handle_linkedin_webhook(ctx)
            return _response(res, status)

        return _response({"error": f"No route for {method} {path}"}, 404)
    except Exception as e:
        return _response({"error": str(e)}, 500)
