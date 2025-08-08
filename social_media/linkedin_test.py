import requests
import logging
import os
import time
from dotenv import load_dotenv

# Load .env for ACCESS_TOKEN, ORGANIZATION_URN
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
API_VERSION = "202507"  # LinkedIn API version for July 2025

def post_pdf_to_linkedin(s3_pdf_url, caption, access_token, org_urn):
    """
    Upload a PDF to LinkedIn using the Documents API and share it in a post.
    """
    headers = {
        'Authorization': f'Bearer {access_token}',
        'LinkedIn-Version': API_VERSION,
        'X-Restli-Protocol-Version': '2.0.0',
        'Content-Type': 'application/json'
    }

    # Step 1: Initialize document upload
    init_payload = {
        "initializeUploadRequest": {
            "owner": org_urn
        }
    }

    try:
        init_resp = requests.post(
            "https://api.linkedin.com/rest/documents?action=initializeUpload",
            headers=headers,
            json=init_payload
        )
        init_resp.raise_for_status()
        init_data = init_resp.json()
        upload_url = init_data['value']['uploadUrl']
        document_urn = init_data['value']['document']
        logging.info(f"Initialized document upload: {document_urn}")
    except requests.exceptions.HTTPError as e:
        logging.error(f"Failed to initialize PDF upload: {init_resp.status_code} - {init_resp.text}")
        raise

    # Step 2: Download PDF from S3
    try:
        pdf_resp = requests.get(s3_pdf_url)
        pdf_resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logging.error(f"Failed to download PDF from S3: {pdf_resp.status_code} - {pdf_resp.text}")
        raise

    # Step 3: Upload PDF to LinkedIn
    try:
        upload_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/pdf"
        }
        upload_resp = requests.put(upload_url, headers=upload_headers, data=pdf_resp.content)
        upload_resp.raise_for_status()
        logging.info("PDF uploaded successfully")
    except requests.exceptions.HTTPError as e:
        logging.error(f"Failed to upload PDF: {upload_resp.status_code} - {upload_resp.text}")
        raise

    # Step 4: Create post with the document
    post_body = {
        "author": org_urn,
        "commentary": caption,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": []
        },
        "content": {
            "media": {
                "id": document_urn,
                "title": "My Latest Report"
            }
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False
    }

    try:
        post_resp = requests.post(
            "https://api.linkedin.com/rest/posts",
            headers=headers,
            json=post_body
        )
        post_resp.raise_for_status()
        logging.info(f"✅ PDF posted as document: {s3_pdf_url}")
        return True, f"✅ PDF posted as document: {s3_pdf_url}"
    except requests.exceptions.HTTPError as e:
        logging.error(f"Failed to create post: {post_resp.status_code} - {post_resp.text}")
        raise


if __name__ == "__main__":
    # Set your test parameters
    test_url = "https://marketing-bot-images.s3.ap-south-1.amazonaws.com/pdfs/IMG_877c9af1.pdf"  # Replace with your S3 PDF URL
    test_caption = "🚀 Sharing my latest report on LinkedIn!"
    access_token = os.getenv("LINKEDIN_ACCESS_TOKEN")
    org_urn = os.getenv("LINKEDIN_ORG_URN")

    # Wait to avoid rate limiting
    logging.info("Waiting 10 seconds to ensure token propagation...")
    time.sleep(10)
    
    success, message = post_pdf_to_linkedin(test_url, test_caption, access_token, org_urn)
    print("✅ Success:", message) if success else print("❌ Error:", message)
