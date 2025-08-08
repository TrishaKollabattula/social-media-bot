import json
import jwt
import time
import os
import requests
from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError

# ✅ Load .env file for your LinkedIn keys
load_dotenv()

SECRET_KEY = "my-secure-secret-key-12345"

# ✅ Read LinkedIn OAuth config
LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
LINKEDIN_REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI")

dynamodb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION"))
users_table = dynamodb.Table("Users")


class UserHandler:
    def login(self, context):
        request = context["request"]
        body = request.get("body")

        if not body:
            raise Exception("Request body is empty")

        data = json.loads(body) if isinstance(body, str) else body
        username = data.get("username")
        password = data.get("password")

        if not username or not password:
            raise Exception("Username and password are required")

        try:
            # Fetch user from DynamoDB
            response = users_table.get_item(Key={"username": username})
            user = response.get("Item")

            if not user or user.get("password") != password:
                raise Exception("Invalid username or password")
        except ClientError as e:
            raise Exception("DynamoDB error: " + str(e))

        # Generate JWT token
        token_payload = {
            "username": username,
            "exp": int(time.time()) + 3600
        }
        token = jwt.encode(token_payload, SECRET_KEY, algorithm="HS256")

        return {
            "token": token,
            "user": {"username": username}
        }

    def register(self, context):
        request = context["request"]
        body = request.get("body")

        if not body:
            raise Exception("Request body is empty")

        data = json.loads(body) if isinstance(body, str) else body
        username = data.get("username")
        password = data.get("password")

        if not username or not password:
            raise Exception("Username and password are required")

        # ✅ Save to DynamoDB
        try:
            users_table.put_item(
                Item={"username": username, "password": password}
            )
        except ClientError as e:
            raise Exception("DynamoDB error while saving user: " + str(e))

        # Generate token
        token_payload = {
            "username": username,
            "exp": int(time.time()) + 3600
        }
        token = jwt.encode(token_payload, SECRET_KEY, algorithm="HS256")

        return {
            "message": "User registered successfully!",
            "token": token,
            "user": {"username": username}
        }


    def linkedin_callback(self, context):
        """
        ✅ NEW: Handles LinkedIn OAuth callback.
        Exchanges 'code' for 'access_token'
        """
        request = context["request"]
        body = request.get("body")

        if not body:
            raise Exception("Request body is empty")

        data = json.loads(body) if isinstance(body, str) else body
        code = data.get("code")

        if not code:
            raise Exception("Authorization code is missing")

        # ✅ Make request to LinkedIn to exchange code
        token_url = "https://www.linkedin.com/oauth/v2/accessToken"
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": LINKEDIN_REDIRECT_URI,
            "client_id": LINKEDIN_CLIENT_ID,
            "client_secret": LINKEDIN_CLIENT_SECRET
        }

        response = requests.post(token_url, data=payload)
        response.raise_for_status()
        token_data = response.json()

        access_token = token_data.get("access_token")
        if not access_token:
            raise Exception(f"Failed to get access token: {token_data}")

        return {"access_token": access_token}
