import os
import requests
import jwt  # PyJWT
from dotenv import load_dotenv

# Load your .env with client details
load_dotenv()

# Fetch credentials from environment variables
client_id = os.getenv("LINKEDIN_CLIENT_ID")
client_secret = os.getenv("LINKEDIN_CLIENT_SECRET")
redirect_uri = os.getenv("LINKEDIN_REDIRECT_URI")

# 👉 1️⃣ Replace with your new code from LinkedIn URL
authorization_code = "AQS2uE3e1sp51iSJQTPo3cE0jQ09Z7Y7KdWS0BTE1uoGTtd_zViKDS7Rrg82E59syDmEQvW62Ux7GjOa-ypOsRAcMh5SuuSiLQINr5LcCb24PXwWWwscl_Y-E9zXT51XIk1iAuanreEwVUs3YOtEIR_0ahR62YikUG6ggw9H5uZEzm39lcQvGUy3C3j160iW-uu4MXXmcxSTFn4l29M&state=123e4567-e89b-12d3-a456-426614174000"

# 👉 2️⃣ Exchange code for tokens (access + id_tok
token_url = "https://www.linkedin.com/oauth/v2/accessToken"

data = {
    'grant_type': 'authorization_code',
    'code': authorization_code,
    'redirect_uri': redirect_uri,
    'client_id': client_id,
    'client_secret': client_secret
}

response = requests.post(token_url, data=data)

if response.ok:
    # 3️⃣ Successful response: Extract access token and id_token
    token_data = response.json()
    access_token = token_data['access_token']
    id_token = token_data.get('id_token')

    print("✅ Access Token:", access_token)
    
    # Decode ID Token if available
    if id_token:
        decoded = jwt.decode(id_token, options={"verify_signature": False})
        print("✅ Decoded ID Token:", decoded)

        # Extract `sub` for the Person URN
        sub = decoded.get("sub")
        if sub:
            person_urn = f"urn:li:person:{sub}"
            print(f"✅ Your LinkedIn Person URN: {person_urn}")
        else:
            print("❌ 'sub' not found in ID Token")
    else:
        print("❌ No ID Token returned — check if 'openid' scope was set.")
else:
    print(f"❌ Token exchange failed: {response.status_code} {response.text}")
