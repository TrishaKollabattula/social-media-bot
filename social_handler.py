# social_handler.py

import json
import boto3
import requests
import os
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import traceback

load_dotenv()

LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
LINKEDIN_REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI")

# Facebook Configuration
FACEBOOK_CLIENT_ID = os.getenv("FACEBOOK_CLIENT_ID", "1095157869184608")
FACEBOOK_CLIENT_SECRET = os.getenv("FACEBOOK_CLIENT_SECRET")
FACEBOOK_REDIRECT_URI = os.getenv(
    "FACEBOOK_REDIRECT_URI",
    "https://13.233.45.167:5000/social/facebook/callback"
)

# Instagram (Graph API via Facebook OAuth dialog)
INSTAGRAM_CLIENT_ID = os.getenv("INSTAGRAM_CLIENT_ID", "23985206087742789")
INSTAGRAM_CLIENT_SECRET = os.getenv("INSTAGRAM_CLIENT_SECRET")
INSTAGRAM_REDIRECT_URI = os.getenv("INSTAGRAM_REDIRECT_URI")  # must be set

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
social_tokens_table = dynamodb.Table("SocialTokens")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
}


def _clean_ddb_item(d: dict) -> dict:
    clean = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue
        if isinstance(v, (list, dict)) and len(v) == 0:
            continue
        clean[k] = v
    return clean


class SocialHandler:

    # ---------------------------
    # Common
    # ---------------------------

    def get_user_social_data(self, user_id, platform=None):
        try:
            resp = social_tokens_table.get_item(Key={"user_id": user_id})
            user_data = resp.get("Item") or {}

            if not user_data:
                return {}

            if platform:
                return {
                    f"{platform}_access_token": user_data.get(f"{platform}_access_token"),
                    f"{platform}_user_urn": user_data.get(f"{platform}_user_urn"),
                    f"{platform}_org_urn": user_data.get(f"{platform}_org_urn"),
                    f"{platform}_preferred_urn": user_data.get(f"{platform}_preferred_urn"),
                    f"{platform}_all_org_urns": user_data.get(f"{platform}_all_org_urns"),
                    f"{platform}_has_org_access": user_data.get(f"{platform}_has_org_access"),
                    f"{platform}_page_id": user_data.get(f"{platform}_page_id"),
                    f"{platform}_page_name": user_data.get(f"{platform}_page_name"),
                }

            return user_data

        except Exception as e:
            logger.error(f"Error fetching user data: {e}")
            return {}

    def get_status(self, context):
        try:
            request = context["request"]
            query_params = request.get("queryStringParameters", {}) or {}
            app_user = query_params.get("app_user")

            if not app_user:
                return {"error": "app_user parameter required"}, 400

            user_data = self.get_user_social_data(app_user)

            # LinkedIn Status
            linkedin_status = {"connected": bool(user_data.get("linkedin_access_token")), "detail": None}
            if linkedin_status["connected"]:
                all_org_urns_str = user_data.get("linkedin_all_org_urns", "[]")
                all_org_urns = json.loads(all_org_urns_str) if isinstance(all_org_urns_str, str) else all_org_urns_str
                linkedin_status["detail"] = {
                    "preferred_posting_urn": user_data.get("linkedin_preferred_urn"),
                    "user_urn": user_data.get("linkedin_user_urn"),
                    "org_urn": user_data.get("linkedin_org_urn"),
                    "all_org_urns": all_org_urns,
                    "has_org_access": user_data.get("linkedin_has_org_access", False),
                    "posting_method": "Organization Page"
                    if user_data.get("linkedin_has_org_access") and user_data.get("linkedin_org_urn")
                    else "Personal Profile",
                    "organization_count": len(all_org_urns),
                    "connected_at": user_data.get("linkedin_connected_at"),
                }

            # Instagram Status (✅ use instagram_page_access_token)
            instagram_status = {"connected": bool(user_data.get("instagram_page_access_token")), "detail": None}
            if instagram_status["connected"]:
                instagram_status["detail"] = {
                    "user_id": user_data.get("instagram_user_id"),
                    "username": user_data.get("instagram_username"),
                    "connected_at": user_data.get("instagram_connected_at"),
                    "page_id": user_data.get("instagram_page_id"),
                    "page_name": user_data.get("instagram_page_name"),
                }

            # Facebook Status
            facebook_status = {"connected": bool(user_data.get("facebook_page_access_token")), "detail": None}
            if facebook_status["connected"]:
                all_pages_str = user_data.get("facebook_all_pages", "[]")
                all_pages = json.loads(all_pages_str) if isinstance(all_pages_str, str) else all_pages_str
                facebook_status["detail"] = {
                    "page_id": user_data.get("facebook_page_id"),
                    "page_name": user_data.get("facebook_page_name"),
                    "all_pages": all_pages,
                    "connected_at": user_data.get("facebook_connected_at"),
                }

            return {
                "linkedin": linkedin_status,
                "instagram": instagram_status,
                "twitter": {"connected": False, "detail": None},
                "facebook": facebook_status,
            }

        except Exception as e:
            logger.error(f"Error in get_status: {e}")
            logger.error(traceback.format_exc())
            return {"error": str(e)}, 500

    # ---------------------------
    # LinkedIn
    # ---------------------------

    def detect_organizations_comprehensive(self, access_token, user_urn):
        org_urn = None
        has_org_access = False
        all_org_urns = []

        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        logger.info("=== Starting organization detection ===")

        try:
            acl_url = "https://api.linkedin.com/v2/organizationAcls?q=roleAssignee"

            acl_response = requests.get(
                acl_url,
                headers={**headers, "roleAssignee": user_urn},
                timeout=30,
            )

            logger.info(f"ACL Response Status: {acl_response.status_code}")

            if acl_response.status_code == 200:
                acl_data = acl_response.json()
                elements = acl_data.get("elements", [])

                posting_roles = {
                    "ADMINISTRATOR",
                    "CONTENT_ADMINISTRATOR",
                    "CONTENT_ADMIN",
                    "ORGANIC_POSTER",
                    "DIRECT_SPONSORED_CONTENT_POSTER",
                }

                for element in elements:
                    role = element.get("role")
                    state = element.get("state")
                    organization = element.get("organization")

                    if state == "APPROVED" and organization:
                        if organization not in all_org_urns:
                            all_org_urns.append(organization)

                        if role in posting_roles and not org_urn:
                            org_urn = organization
                            has_org_access = True
                            logger.info(f"PRIMARY ORG SET: {organization} (Role: {role})")

        except Exception as e:
            logger.error(f"ACL detection error: {e}")

        logger.info(f"Primary org: {org_urn}, All orgs: {all_org_urns}, Has access: {has_org_access}")

        return org_urn, all_org_urns, has_org_access

    def linkedin_callback(self, context):
        try:
            request = context["request"]
            body = json.loads(request.get("body", "{}"))

            code = body.get("code")
            state = body.get("state")

            if not code or not state:
                return {"error": "Missing code or state"}, 400

            app_user = state

            token_response = requests.post(
                "https://www.linkedin.com/oauth/v2/accessToken",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": LINKEDIN_REDIRECT_URI,
                    "client_id": LINKEDIN_CLIENT_ID,
                    "client_secret": LINKEDIN_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )

            if token_response.status_code != 200:
                logger.error(f"Token exchange failed: {token_response.text}")
                return {"error": "Token exchange failed"}, 400

            access_token = token_response.json().get("access_token")
            if not access_token:
                return {"error": "No access token received"}, 400

            profile_response = requests.get(
                "https://api.linkedin.com/v2/me",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30,
            )
            if profile_response.status_code != 200:
                return {"error": "Failed to fetch profile"}, 400

            profile_data = profile_response.json()
            person_id = profile_data.get("id")
            user_urn = f"urn:li:person:{person_id}"

            org_urn, all_org_urns, has_org_access = self.detect_organizations_comprehensive(access_token, user_urn)
            preferred_urn = org_urn if (org_urn and has_org_access) else user_urn

            current_time = datetime.utcnow().isoformat()
            existing_data = self.get_user_social_data(app_user)

            social_data = {
                "user_id": app_user,
                "platform": "linkedin",
                "linkedin_access_token": access_token,
                "linkedin_user_urn": user_urn,
                "linkedin_org_urn": org_urn if org_urn else "",
                "linkedin_all_org_urns": json.dumps(all_org_urns),
                "linkedin_preferred_urn": preferred_urn,
                "linkedin_has_org_access": has_org_access,
                "linkedin_connected_at": current_time,
                "updated_at": current_time,
            }

            final_data = _clean_ddb_item({**existing_data, **social_data})
            social_tokens_table.put_item(Item=final_data)

            return {
                "success": True,
                "user_urn": user_urn,
                "org_urn": org_urn,
                "all_org_urns": all_org_urns,
                "preferred_urn": preferred_urn,
                "has_org_access": has_org_access,
                "posting_method": "Organization Page" if (org_urn and has_org_access) else "Personal Profile",
                "organization_count": len(all_org_urns),
                "message": f"LinkedIn connected - {len(all_org_urns)} organization(s) detected",
            }

        except Exception as e:
            logger.error(f"LinkedIn callback error: {e}")
            logger.error(traceback.format_exc())
            return {"error": str(e)}, 500

    def linkedin_callback_frontend(self, context):
        try:
            request = context["request"]
            query_params = request.get("queryStringParameters", {}) or {}

            code = query_params.get("code")
            state = query_params.get("state")
            error = query_params.get("error")

            if error:
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                    "body": f"""<script>
                        window.opener && window.opener.postMessage({{type: 'linkedin_callback', success: false, error: '{error}'}}, '*');
                        window.close();
                    </script>""",
                }

            if not code or not state:
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                    "body": """<script>
                        window.opener && window.opener.postMessage({type: 'linkedin_callback', success: false, error: 'Missing parameters'}, '*');
                        window.close();
                    </script>""",
                }

            callback_result = self.linkedin_callback({"request": {"body": json.dumps({"code": code, "state": state})}})
            if isinstance(callback_result, tuple):
                result_data, status_code = callback_result
                success = status_code == 200 and result_data.get("success", False)
            else:
                result_data = callback_result
                success = result_data.get("success", False)

            if success:
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                    "body": f"""<script>
                        window.opener && window.opener.postMessage({{
                            type: 'linkedin_callback', success: true,
                            posting_method: '{result_data.get("posting_method")}',
                            app_user: '{state}'
                        }}, '*');
                        window.close();
                    </script>""",
                }

            return {
                "statusCode": 200,
                "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                "body": f"""<script>
                    window.opener && window.opener.postMessage({{type: 'linkedin_callback', success: false, error: '{result_data.get("error", "Connection failed")}' }}, '*');
                    window.close();
                </script>""",
            }

        except Exception as e:
            logger.error(f"Frontend callback error: {e}")
            logger.error(traceback.format_exc())
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                "body": "<script>window.opener && window.opener.postMessage({type: 'linkedin_callback', success: false, error: 'Server error'}, '*'); window.close();</script>",
            }

    def linkedin_disconnect(self, context):
        try:
            request = context["request"]
            body = json.loads(request.get("body", "{}"))
            app_user = body.get("app_user")

            if not app_user:
                return {"statusCode": 400, "body": json.dumps({"error": "app_user required"})}

            existing_data = self.get_user_social_data(app_user)
            if not existing_data.get("linkedin_access_token"):
                return {"statusCode": 200, "body": json.dumps({"success": True, "message": "Already disconnected"})}

            linkedin_keys = [
                "linkedin_access_token",
                "linkedin_user_urn",
                "linkedin_org_urn",
                "linkedin_all_org_urns",
                "linkedin_preferred_urn",
                "linkedin_has_org_access",
                "linkedin_connected_at",
            ]
            for key in linkedin_keys:
                existing_data.pop(key, None)

            existing_data["updated_at"] = datetime.utcnow().isoformat()
            social_tokens_table.put_item(Item=existing_data)

            return {"statusCode": 200, "body": json.dumps({"success": True, "message": "LinkedIn disconnected"})}

        except Exception as e:
            logger.error(f"Disconnect error: {e}")
            logger.error(traceback.format_exc())
            return {"statusCode": 500, "body": json.dumps({"error": str(e)})}

    # ---------------------------
    # Facebook
    # ---------------------------

    def facebook_callback(self, context):
        try:
            request = context["request"]
            body = json.loads(request.get("body", "{}"))

            code = body.get("code")
            state = body.get("state")
            if not code or not state:
                logger.error("Missing code or state in Facebook callback")
                return {"error": "Missing code or state"}, 400

            app_user = state
            logger.info(f"[FACEBOOK] Processing callback for user: {app_user}")

            token_url = "https://graph.facebook.com/v20.0/oauth/access_token"
            token_params = {
                "client_id": FACEBOOK_CLIENT_ID,
                "client_secret": FACEBOOK_CLIENT_SECRET,
                "redirect_uri": FACEBOOK_REDIRECT_URI,
                "code": code,
            }
            token_response = requests.get(token_url, params=token_params, timeout=15)
            if token_response.status_code != 200:
                logger.error(f"[FACEBOOK] Token exchange failed: {token_response.text}")
                return {"error": f"Token exchange failed: {token_response.text}"}, 400

            token_data = token_response.json()
            user_access_token = token_data.get("access_token")
            if not user_access_token:
                return {"error": "Failed to get access token"}, 400

            pages_url = "https://graph.facebook.com/v20.0/me/accounts"
            pages_params = {"access_token": user_access_token, "fields": "id,name,access_token"}
            pages_response = requests.get(pages_url, params=pages_params, timeout=15)
            if pages_response.status_code != 200:
                return {"error": f"Failed to get pages: {pages_response.text}"}, 400

            pages_data = pages_response.json()
            pages = pages_data.get("data", [])
            if not pages:
                return {"error": "No Facebook Pages found. Please create a Facebook Page first."}, 400

            selected_page = pages[0]
            page_id = selected_page.get("id")
            page_name = selected_page.get("name")
            page_access_token = selected_page.get("access_token")

            current_time = datetime.utcnow().isoformat()
            existing_data = self.get_user_social_data(app_user)

            social_data = {
                "user_id": app_user,
                "platform": "facebook",
                "facebook_page_id": page_id,
                "facebook_page_name": page_name,
                "facebook_page_access_token": page_access_token,
                "facebook_user_access_token": user_access_token,
                "facebook_all_pages": json.dumps([{"id": p.get("id"), "name": p.get("name")} for p in pages]),
                "facebook_connected_at": current_time,
                "updated_at": current_time,
            }

            final_data = _clean_ddb_item({**existing_data, **social_data})
            social_tokens_table.put_item(Item=final_data)

            return {
                "success": True,
                "page_id": page_id,
                "page_name": page_name,
                "all_pages": [{"id": p.get("id"), "name": p.get("name")} for p in pages],
                "message": f"Successfully connected to Facebook Page: {page_name}",
            }

        except Exception as e:
            logger.error(f"[FACEBOOK] Callback error: {str(e)}")
            logger.error(traceback.format_exc())
            return {"error": str(e)}, 500

    def facebook_callback_frontend(self, context):
        try:
            request = context["request"]
            query_params = request.get("queryStringParameters", {}) or {}

            code = query_params.get("code")
            state = query_params.get("state")
            error = query_params.get("error")
            error_description = query_params.get("error_description")

            logger.info(f"[FACEBOOK FRONTEND] Callback - code: {bool(code)}, state: {state}, error: {error}")

            if error:
                error_msg = error_description or error
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                    "body": f"""
                    <html><body>
                        <h2>Facebook Connection Error</h2>
                        <p>{error_msg}</p>
                        <script>
                            if (window.opener) {{
                                window.opener.postMessage({{
                                    type: 'facebook_callback',
                                    success: false,
                                    error: '{error_msg}'
                                }}, '*');
                            }}
                            setTimeout(() => window.close(), 800);
                        </script>
                    </body></html>
                    """,
                }

            if not code or not state:
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                    "body": """
                    <html><body>
                        <h2>Missing Parameters</h2>
                        <script>
                            if (window.opener) {
                                window.opener.postMessage({
                                    type: 'facebook_callback',
                                    success: false,
                                    error: 'Missing parameters'
                                }, '*');
                            }
                            setTimeout(() => window.close(), 800);
                        </script>
                    </body></html>
                    """,
                }

            callback_result = self.facebook_callback({"request": {"body": json.dumps({"code": code, "state": state})}})
            if isinstance(callback_result, tuple):
                result_data, status_code = callback_result
                success = status_code == 200 and result_data.get("success", False)
            else:
                result_data = callback_result
                success = result_data.get("success", False)

            if success:
                page_name = result_data.get("page_name", "")
                page_id = result_data.get("page_id", "")
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                    "body": f"""
                    <html><body>
                        <h2>Facebook Connected Successfully!</h2>
                        <p>Page: {page_name}</p>
                        <script>
                            if (window.opener) {{
                                window.opener.postMessage({{
                                    type: 'facebook_callback',
                                    success: true,
                                    page_name: '{page_name}',
                                    page_id: '{page_id}',
                                    app_user: '{state}'
                                }}, '*');
                            }}
                            setTimeout(() => window.close(), 800);
                        </script>
                    </body></html>
                    """,
                }

            error_msg = result_data.get("error", "Connection failed")
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                "body": f"""
                <html><body>
                    <h2>Connection Failed</h2>
                    <p>{error_msg}</p>
                    <script>
                        if (window.opener) {{
                            window.opener.postMessage({{
                                type: 'facebook_callback',
                                success: false,
                                error: '{error_msg}'
                            }}, '*');
                        }}
                        setTimeout(() => window.close(), 800);
                    </script>
                </body></html>
                """,
            }

        except Exception as e:
            logger.error(f"[FACEBOOK] Frontend callback error: {e}")
            logger.error(traceback.format_exc())
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                "body": """
                <html><body>
                    <h2>Server Error</h2>
                    <script>
                        if (window.opener) {
                            window.opener.postMessage({
                                type: 'facebook_callback',
                                success: false,
                                error: 'Server error'
                            }, '*');
                        }
                        setTimeout(() => window.close(), 800);
                    </script>
                </body></html>
                """,
            }

    def facebook_disconnect(self, context):
        try:
            request = context["request"]
            body = json.loads(request.get("body", "{}"))
            app_user = body.get("app_user")

            if not app_user:
                return {
                    "statusCode": 400,
                    "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                    "body": json.dumps({"error": "app_user required"}),
                }

            existing_data = self.get_user_social_data(app_user)
            if not existing_data.get("facebook_page_access_token"):
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                    "body": json.dumps({"success": True, "message": "Already disconnected"}),
                }

            keys = [
                "facebook_page_id",
                "facebook_page_name",
                "facebook_page_access_token",
                "facebook_user_access_token",
                "facebook_all_pages",
                "facebook_connected_at",
            ]
            for k in keys:
                existing_data.pop(k, None)

            existing_data["updated_at"] = datetime.utcnow().isoformat()
            social_tokens_table.put_item(Item=existing_data)

            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps({"success": True, "message": "Facebook disconnected successfully"}),
            }

        except Exception as e:
            logger.error(f"[FACEBOOK] Disconnect error: {e}")
            logger.error(traceback.format_exc())
            return {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps({"error": str(e)}),
            }

    # ---------------------------
    # Instagram
    # ---------------------------

    def instagram_callback(self, context):
        try:
            request = context["request"]
            body = json.loads(request.get("body", "{}"))

            code = body.get("code")
            state = body.get("state")
            if not code or not state:
                return {"error": "Missing code or state"}, 400

            app_user = state
            logger.info(f"[INSTAGRAM] Processing callback for user: {app_user}")

            if not INSTAGRAM_CLIENT_ID or not INSTAGRAM_CLIENT_SECRET or not INSTAGRAM_REDIRECT_URI:
                return {"error": "Instagram env missing (CLIENT_ID/SECRET/REDIRECT_URI)"}, 500

            # 1) Code -> short lived user token
            token_url = "https://graph.facebook.com/v21.0/oauth/access_token"
            token_params = {
                "client_id": INSTAGRAM_CLIENT_ID,
                "client_secret": INSTAGRAM_CLIENT_SECRET,
                "redirect_uri": INSTAGRAM_REDIRECT_URI,
                "code": code,
            }
            token_resp = requests.get(token_url, params=token_params, timeout=20)
            if token_resp.status_code != 200:
                return {"error": f"Token exchange failed: {token_resp.text}"}, 400

            short_user_token = (token_resp.json() or {}).get("access_token")
            if not short_user_token:
                return {"error": "No access token received"}, 400

            # 2) Short -> long lived user token
            long_url = "https://graph.facebook.com/v21.0/oauth/access_token"
            long_params = {
                "grant_type": "fb_exchange_token",
                "client_id": INSTAGRAM_CLIENT_ID,
                "client_secret": INSTAGRAM_CLIENT_SECRET,
                "fb_exchange_token": short_user_token,
            }
            long_resp = requests.get(long_url, params=long_params, timeout=20)

            if long_resp.status_code == 200:
                long_user_token = (long_resp.json() or {}).get("access_token", short_user_token)
                expires_in = (long_resp.json() or {}).get("expires_in", 5184000)
            else:
                logger.warning(f"[INSTAGRAM] long-lived token failed, using short: {long_resp.text}")
                long_user_token = short_user_token
                expires_in = 5184000

            expiry_date = datetime.utcnow() + timedelta(seconds=int(expires_in))

            # 3) Get pages
            pages_url = "https://graph.facebook.com/v21.0/me/accounts"
            pages_params = {"access_token": long_user_token, "fields": "id,name,access_token"}
            pages_resp = requests.get(pages_url, params=pages_params, timeout=20)
            if pages_resp.status_code != 200:
                return {"error": f"Failed to get pages: {pages_resp.text}"}, 400

            pages = (pages_resp.json() or {}).get("data", [])
            if not pages:
                return {"error": "No Facebook Pages found. IG Business must be linked to a Page."}, 400

            # 4) Find page that has instagram_business_account
            selected_page = None
            instagram_user_id = None

            for p in pages:
                pid = p.get("id")
                ptoken = p.get("access_token")
                if not pid or not ptoken:
                    continue

                check_url = f"https://graph.facebook.com/v21.0/{pid}"
                check_params = {"fields": "instagram_business_account", "access_token": ptoken}
                check_resp = requests.get(check_url, params=check_params, timeout=20)

                if check_resp.status_code == 200:
                    iba = (check_resp.json() or {}).get("instagram_business_account")
                    if iba and iba.get("id"):
                        selected_page = p
                        instagram_user_id = iba["id"]
                        break

            if not selected_page or not instagram_user_id:
                return {"error": "No Instagram Business Account linked to your Pages."}, 400

            page_id = selected_page["id"]
            page_name = selected_page.get("name", "")
            page_access_token = selected_page["access_token"]

            # 5) Get username
            instagram_username = ""
            prof_url = f"https://graph.facebook.com/v21.0/{instagram_user_id}"
            prof_params = {"fields": "username", "access_token": page_access_token}
            prof_resp = requests.get(prof_url, params=prof_params, timeout=20)
            if prof_resp.status_code == 200:
                instagram_username = (prof_resp.json() or {}).get("username", "") or ""

            # 6) Save in DynamoDB
            current_time = datetime.utcnow().isoformat()
            existing_data = self.get_user_social_data(app_user)

            social_data = {
                "user_id": app_user,
                "instagram_user_id": instagram_user_id,
                "instagram_username": instagram_username,
                # store both:
                "instagram_user_access_token": long_user_token,
                "instagram_page_access_token": page_access_token,
                "instagram_page_id": page_id,
                "instagram_page_name": page_name,
                "instagram_token_expires_at": expiry_date.isoformat(),
                "instagram_connected_at": current_time,
                "updated_at": current_time,
            }

            final_data = _clean_ddb_item({**existing_data, **social_data})
            social_tokens_table.put_item(Item=final_data)

            return {
                "success": True,
                "instagram_user_id": instagram_user_id,
                "instagram_username": instagram_username,
                "page_id": page_id,
                "page_name": page_name,
                "expires_at": expiry_date.isoformat(),
                "message": f"Instagram connected{' @' + instagram_username if instagram_username else ''}",
            }

        except Exception as e:
            logger.error(f"[INSTAGRAM] Callback error: {e}")
            logger.error(traceback.format_exc())
            return {"error": str(e)}, 500

    def instagram_callback_frontend(self, context):
        """
        ✅ Uses ONLY your old mapping:
        GET /social/instagram/callback?state=<app_user>   -> starts login (302)
        GET /social/instagram/callback?code=...&state=... -> finishes login (popup postMessage)
        """
        try:
            request = context["request"]
            q = request.get("queryStringParameters", {}) or {}

            code = q.get("code")
            state = q.get("state")
            error = q.get("error")
            error_description = q.get("error_description")

            logger.info(f"[INSTAGRAM FRONTEND] code: {bool(code)}, state: {state}, error: {error}")

            # ✅ if user just clicked connect (no code yet) -> redirect to FB login
            if not code and not error:
                if not state:
                    return {
                        "statusCode": 200,
                        "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                        "body": """<script>
                            window.opener && window.opener.postMessage({type:'instagram_callback', success:false, error:'Missing state (app_user)'}, '*');
                            window.close();
                        </script>""",
                    }

                if not INSTAGRAM_CLIENT_ID or not INSTAGRAM_REDIRECT_URI:
                    return {
                        "statusCode": 200,
                        "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                        "body": """<script>
                            window.opener && window.opener.postMessage({type:'instagram_callback', success:false, error:'Instagram env missing (CLIENT_ID/REDIRECT_URI)'}, '*');
                            window.close();
                        </script>""",
                    }

                scopes = [
                    "pages_show_list",
                    "pages_read_engagement",
                    "instagram_basic",
                    "instagram_content_publish",
                    "business_management",
                ]

                auth_url = (
                    "https://www.facebook.com/v21.0/dialog/oauth"
                    f"?client_id={INSTAGRAM_CLIENT_ID}"
                    f"&redirect_uri={INSTAGRAM_REDIRECT_URI}"
                    f"&state={state}"
                    f"&response_type=code"
                    f"&scope={','.join(scopes)}"
                )

                return {"statusCode": 302, "headers": {"Location": auth_url, **CORS_HEADERS}, "body": ""}

            # ✅ OAuth error
            if error:
                error_msg = error_description or error
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                    "body": f"""
                    <html><body>
                        <h2>Instagram Connection Error</h2>
                        <p>{error_msg}</p>
                        <script>
                            if (window.opener) {{
                                window.opener.postMessage({{
                                    type: 'instagram_callback',
                                    success: false,
                                    error: '{error_msg}'
                                }}, '*');
                            }}
                            setTimeout(() => window.close(), 800);
                        </script>
                    </body></html>
                    """,
                }

            # ✅ Must have code+state to finish
            if not code or not state:
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                    "body": """
                    <html><body>
                        <h2>Missing Parameters</h2>
                        <script>
                            if (window.opener) {
                                window.opener.postMessage({
                                    type: 'instagram_callback',
                                    success: false,
                                    error: 'Missing parameters'
                                }, '*');
                            }
                            setTimeout(() => window.close(), 800);
                        </script>
                    </body></html>
                    """,
                }

            # Call backend callback (POST logic reused)
            callback_result = self.instagram_callback({"request": {"body": json.dumps({"code": code, "state": state})}})

            if isinstance(callback_result, tuple):
                result_data, status_code = callback_result
                success = status_code == 200 and result_data.get("success", False)
            else:
                result_data = callback_result
                success = result_data.get("success", False)

            if success:
                username = result_data.get("instagram_username", "")
                user_id = result_data.get("instagram_user_id", "")
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                    "body": f"""
                    <html><body>
                        <h2>Instagram Connected Successfully!</h2>
                        <p>Account: @{username}</p>
                        <script>
                            if (window.opener) {{
                                window.opener.postMessage({{
                                    type: 'instagram_callback',
                                    success: true,
                                    instagram_username: '{username}',
                                    instagram_user_id: '{user_id}',
                                    app_user: '{state}'
                                }}, '*');
                            }}
                            setTimeout(() => window.close(), 800);
                        </script>
                    </body></html>
                    """,
                }

            error_msg = result_data.get("error", "Connection failed")
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                "body": f"""
                <html><body>
                    <h2>Connection Failed</h2>
                    <p>{error_msg}</p>
                    <script>
                        if (window.opener) {{
                            window.opener.postMessage({{
                                type: 'instagram_callback',
                                success: false,
                                error: '{error_msg}'
                            }}, '*');
                        }}
                        setTimeout(() => window.close(), 800);
                    </script>
                </body></html>
                """,
            }

        except Exception as e:
            logger.error(f"[INSTAGRAM] Frontend callback error: {e}")
            logger.error(traceback.format_exc())
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "text/html", **CORS_HEADERS},
                "body": """
                <html><body>
                    <h2>Server Error</h2>
                    <script>
                        if (window.opener) {
                            window.opener.postMessage({
                                type: 'instagram_callback',
                                success: false,
                                error: 'Server error'
                            }, '*');
                        }
                        setTimeout(() => window.close(), 800);
                    </script>
                </body></html>
                """,
            }

    def instagram_disconnect(self, context):
        try:
            request = context["request"]
            body = json.loads(request.get("body", "{}"))
            app_user = body.get("app_user")

            if not app_user:
                return {
                    "statusCode": 400,
                    "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                    "body": json.dumps({"error": "app_user required"}),
                }

            existing_data = self.get_user_social_data(app_user)

            # ✅ correct token key check
            if not existing_data.get("instagram_page_access_token"):
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                    "body": json.dumps({"success": True, "message": "Already disconnected"}),
                }

            instagram_keys = [
                "instagram_user_id",
                "instagram_username",
                "instagram_user_access_token",
                "instagram_page_access_token",
                "instagram_page_id",
                "instagram_page_name",
                "instagram_token_expires_at",
                "instagram_connected_at",
            ]
            for key in instagram_keys:
                existing_data.pop(key, None)

            existing_data["updated_at"] = datetime.utcnow().isoformat()
            social_tokens_table.put_item(Item=existing_data)

            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps({"success": True, "message": "Instagram disconnected successfully"}),
            }

        except Exception as e:
            logger.error(f"[INSTAGRAM] Disconnect error: {e}")
            logger.error(traceback.format_exc())
            return {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json", **CORS_HEADERS},
                "body": json.dumps({"error": str(e)}),
            }