#social_media/linkedin_post.py
import requests
import logging
import boto3
import os
import json
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
API_VERSION = "202507"  # LinkedIn API version
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
DYNAMODB_TABLE_NAME = "SocialTokens"  # Fixed table name

# Initialize AWS clients
s3 = boto3.client("s3", region_name=AWS_REGION) if AWS_REGION else None
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION) if AWS_REGION else None
table = dynamodb.Table(DYNAMODB_TABLE_NAME) if dynamodb else None

class LinkedInPoster:
    def __init__(self):
        self.api_version = API_VERSION
        
    def get_user_linkedin_credentials(self, user_id):
        """
        Fetch LinkedIn credentials from DynamoDB SocialTokens table.
        Table Schema: user_id (partition key) + platform (sort key)
        """
        try:
            if not table:
                logging.error("❌ DynamoDB table not initialized")
                return None
                
            logging.info(f"🔍 Fetching LinkedIn credentials for user: {user_id}")
            
            # Query with composite key: user_id + platform
            response = table.get_item(
                Key={
                    'user_id': user_id,
                    'platform': 'linkedin'
                }
            )
            
            if 'Item' not in response:
                logging.warning(f"⚠️ No LinkedIn credentials found for user: {user_id}")
                logging.warning(f"💡 User needs to connect LinkedIn via OAuth in the UI")
                return None
                
            item = response['Item']
            
            # Extract credentials from DynamoDB columns
            credentials = {
                'access_token': item.get('linkedin_access_token'),
                'person_urn': item.get('linkedin_user_urn') or item.get('linkedin_preferred_urn'),
                'org_urn': item.get('linkedin_org_urn'),
                'has_org_access': bool(item.get('linkedin_has_org_access', False)),
                'connected_at': item.get('linkedin_connected_at'),
                'user_id': user_id
            }
            
            logging.info(f"✅ Retrieved LinkedIn credentials for user: {user_id}")
            logging.info(f"   - Access Token: {'Found' if credentials['access_token'] else 'Missing'}")
            logging.info(f"   - Person URN: {credentials['person_urn'] or 'Missing'}")
            logging.info(f"   - Org URN: {credentials['org_urn'] or 'Missing'}")
            logging.info(f"   - Has Org Access: {credentials['has_org_access']}")
            
            # Validate required fields
            if not credentials['access_token']:
                logging.error(f"❌ Missing access_token for user: {user_id}")
                return None
                
            if not credentials['person_urn'] and not credentials['org_urn']:
                logging.error(f"❌ Missing both person_urn and org_urn for user: {user_id}")
                return None
                
            return credentials
            
        except Exception as e:
            logging.error(f"❌ Error fetching LinkedIn credentials for user {user_id}: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_latest_pdf_from_s3(self):
        """
        Fetch the most recent PDF from the S3 'pdfs' folder.
        Returns the S3 URL of the latest PDF or None if no PDFs found.
        """
        if not s3 or not S3_BUCKET_NAME:
            logging.error("❌ S3 client not initialized or S3_BUCKET_NAME not set")
            return None
        
        try:
            response = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix="pdfs/")
            pdfs = [obj for obj in response.get('Contents', []) if obj['Key'].endswith('.pdf')]
            
            if pdfs:
                # Sort by LastModified to get the most recent PDF
                latest_pdf = sorted(pdfs, key=lambda x: x['LastModified'], reverse=True)[0]
                s3_pdf_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{latest_pdf['Key']}"
                logging.info(f"✅ Latest PDF found: {s3_pdf_url}")
                return s3_pdf_url
            else:
                logging.warning("❌ No PDFs found in the 'pdfs' folder.")
                return None
        except Exception as e:
            logging.error(f"❌ Error fetching PDFs from S3: {str(e)}")
            return None
    
    def load_caption_from_content_details(self, path="content_details.json"):
        """
        Load caption from content_details.json file.
        Priority: post_caption > summary > fallback message
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Try to get post_caption first
            captions_obj = data.get("captions") or {}
            post_caption = captions_obj.get("post_caption")

            if isinstance(post_caption, str) and post_caption.strip():
                caption = post_caption.replace("\r\n", "\n").strip()
                logging.info(f"✅ Loaded post_caption ({len(caption)} chars)")
                return caption

            # Fallback to summary
            summary = data.get("summary")
            if isinstance(summary, list) and summary:
                fallback = " ".join(s.strip() for s in summary if isinstance(s, str)).strip()
                logging.warning("⚠️ No post_caption found; using summary fallback")
                return fallback

            # Final fallback
            logging.warning("⚠️ No post_caption or summary found; using default caption")
            return "Check out our latest content! 🚀 #AI #Technology #Innovation"

        except FileNotFoundError:
            logging.error("❌ content_details.json not found; using default caption")
            return "New content available! 🚀 #AI #Technology #Innovation"
        except json.JSONDecodeError:
            logging.error("❌ Invalid JSON in content_details.json; using default caption")
            return "Latest update from our team! 🚀 #AI #Technology #Innovation"
        except Exception as e:
            logging.exception(f"❌ Error loading caption: {e}")
            return "Exciting new content! 🚀 #AI #Technology #Innovation"
    
    def post_pdf_to_linkedin(self, s3_pdf_url, caption, credentials):
        """
        Upload and share a PDF on LinkedIn using user's credentials from DynamoDB.
        
        Posting Logic:
        - If user has org_urn AND has_org_access=True → Post to organization page
        - Otherwise → Post to personal profile
        
        Args:
            s3_pdf_url: S3 URL of the PDF to post
            caption: Caption for the LinkedIn post
            credentials: Dict from get_user_linkedin_credentials()
                {access_token, person_urn, org_urn, has_org_access, user_id}
        
        Returns:
            tuple: (success: bool, message: str)
        """
        access_token = credentials['access_token']
        
        # ✅ Determine posting target - prioritize org_urn if available
        posting_urn = None
        post_target = None
        
        if credentials['has_org_access'] and credentials['org_urn']:
            posting_urn = credentials['org_urn']
            post_target = "organization page"
        elif credentials['person_urn']:
            posting_urn = credentials['person_urn']
            post_target = "personal profile"
        else:
            logging.error("❌ No valid URN found for posting")
            return False, "No valid URN found for posting"
        
        logging.info(f"🚀 Starting PDF upload to LinkedIn {post_target}: {s3_pdf_url}")
        logging.info(f"🔐 Using access_token: {access_token[:20]}...")
        logging.info(f"🏢 Using URN: {posting_urn}")
        logging.info(f"📝 Caption length: {len(caption)} characters")
        
        try:
            # Step 1: Initialize upload
            init_url = "https://api.linkedin.com/rest/documents?action=initializeUpload"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "LinkedIn-Version": self.api_version,
                "X-Restli-Protocol-Version": "2.0.0",
                "Content-Type": "application/json"
            }
            init_data = {
                "initializeUploadRequest": {
                    "owner": posting_urn
                }
            }
            
            logging.info("📤 Step 1: Initializing document upload...")
            init_response = requests.post(init_url, headers=headers, json=init_data, timeout=30)
            
            if init_response.status_code != 200:
                error_message = init_response.text
                logging.error(f"❌ Failed to initialize upload: {init_response.status_code} - {error_message}")
                
                # Check if token expired
                if "EXPIRED_ACCESS_TOKEN" in error_message or init_response.status_code == 401:
                    return False, f"LinkedIn token expired for user {credentials['user_id']}. Please reconnect LinkedIn in the UI."
                
                return False, f"Failed to initialize upload: {error_message}"
            
            upload_url = init_response.json()["value"]["uploadUrl"]
            doc_urn = init_response.json()["value"]["document"]
            logging.info(f"✅ Upload initialized. Document URN: {doc_urn}")
            
            # Step 2: Download PDF from S3
            logging.info("📥 Step 2: Downloading PDF from S3...")
            pdf_response = requests.get(s3_pdf_url, timeout=60)
            if pdf_response.status_code != 200:
                logging.error(f"❌ Failed to download PDF from S3: {pdf_response.status_code}")
                return False, f"Failed to download PDF from S3: {pdf_response.status_code}"
            
            # Step 3: Upload PDF to LinkedIn
            logging.info(f"📤 Step 3: Uploading PDF to LinkedIn ({len(pdf_response.content)} bytes)...")
            upload_response = requests.put(
                upload_url, 
                headers={"Authorization": f"Bearer {access_token}"}, 
                data=pdf_response.content,
                timeout=120
            )
            
            if upload_response.status_code not in [200, 201]:
                logging.error(f"❌ Failed to upload PDF: {upload_response.status_code} - {upload_response.text}")
                return False, f"Failed to upload PDF: {upload_response.text}"
            
            logging.info("✅ PDF uploaded successfully to LinkedIn")
            
            # Step 4: Create post
            logging.info(f"📝 Step 4: Creating LinkedIn post on {post_target}...")
            post_url = "https://api.linkedin.com/rest/posts"
            
            # Extract filename for title
            pdf_filename = os.path.basename(s3_pdf_url).replace('.pdf', '')
            
            post_data = {
                "author": posting_urn,
                "commentary": caption,
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": []
                },
                "content": {
                    "media": {
                        "title": f"{pdf_filename}.pdf",
                        "id": doc_urn
                    }
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False
            }
            
            post_response = requests.post(post_url, headers=headers, json=post_data, timeout=30)
            
            if post_response.status_code == 201:
                post_id = post_response.headers.get('x-linkedin-id')
                success_msg = f"✅ PDF posted successfully to LinkedIn {post_target}! Post ID: {post_id} for user: {credentials['user_id']}"
                logging.info(success_msg)
                return True, success_msg
            else:
                logging.error(f"❌ Failed to create LinkedIn post: {post_response.status_code} - {post_response.text}")
                return False, f"Failed to create post: {post_response.text}"
                
        except requests.exceptions.Timeout:
            error_msg = "❌ Request timeout during LinkedIn posting"
            logging.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"❌ Unexpected error in LinkedIn PDF posting: {str(e)}"
            logging.error(error_msg)
            import traceback
            logging.error(traceback.format_exc())
            return False, error_msg
    
    def post_content_to_linkedin_for_user(self, user_id, s3_url=None, caption=None):
        """
        Main function: Post content to LinkedIn for a specific user.
        Fetches credentials from SocialTokens DynamoDB table.
        
        Args:
            user_id: User identifier (from JWT claims)
            s3_url: URL of the PDF to post (if None, will fetch latest PDF from S3)
            caption: Caption for the post (if None, will load from content_details.json)
        
        Returns:
            tuple: (success: bool, message: str)
        """
        logging.info(f"🎯 LinkedIn posting requested for user: {user_id}")
        
        # Step 1: Get user credentials from DynamoDB
        credentials = self.get_user_linkedin_credentials(user_id)
        if not credentials:
            error_msg = f"❌ Could not retrieve LinkedIn credentials for user: {user_id}. User needs to connect LinkedIn in the UI."
            logging.error(error_msg)
            return False, error_msg
        
        # Step 2: Load caption if not provided
        if not caption or caption.strip() == "":
            logging.info("📝 No caption provided, loading from content_details.json...")
            caption = self.load_caption_from_content_details()
        
        # Step 3: Get PDF URL if not provided
        if not s3_url:
            logging.info("🔍 No specific URL provided, fetching latest PDF from S3...")
            s3_url = self.get_latest_pdf_from_s3()
            
            if not s3_url:
                error_msg = "❌ No PDF files found in S3 to post to LinkedIn"
                logging.error(error_msg)
                return False, error_msg
        
        # Step 4: Validate URL is a PDF
        if not ("/pdfs/" in s3_url and s3_url.lower().endswith('.pdf')):
            error_msg = f"❌ LinkedIn only supports PDF files. Provided URL: {s3_url}"
            logging.error(error_msg)
            return False, error_msg
        
        # Step 5: Post to LinkedIn
        logging.info(f"📄 Posting PDF to LinkedIn for user {user_id}: {s3_url}")
        return self.post_pdf_to_linkedin(s3_url, caption, credentials)

# ========================================
# Global instance for easy import
# ========================================
linkedin_poster = LinkedInPoster()

# ========================================
# Main functions for external use
# ========================================

def post_to_linkedin_for_user(user_id, s3_url=None, caption=None):
    """
    Main function to post content to LinkedIn for a specific user.
    This is called by content_handler.py
    
    Args:
        user_id: User identifier (from JWT claims)
        s3_url: Optional PDF URL (will fetch latest if None)
        caption: Optional caption (will load from content_details.json if None)
    
    Returns:
        tuple: (success: bool, message: str)
    """
    return linkedin_poster.post_content_to_linkedin_for_user(user_id, s3_url, caption)

def get_user_linkedin_status(user_id):
    """
    Check if user has valid LinkedIn credentials in DynamoDB.
    
    Args:
        user_id: User identifier
        
    Returns:
        dict: Status information
    """
    credentials = linkedin_poster.get_user_linkedin_credentials(user_id)
    if credentials:
        return {
            "has_credentials": True,
            "has_org_access": credentials['has_org_access'],
            "connected_at": credentials['connected_at'],
            "posting_target": "organization page" if credentials['has_org_access'] and credentials['org_urn'] else "personal profile"
        }
    return {
        "has_credentials": False,
        "has_org_access": False,
        "connected_at": None,
        "posting_target": None
    }

# ========================================
# Test function
# ========================================

def test_linkedin_posting():
    """
    Test function to verify LinkedIn posting functionality.
    """
    logging.info("🧪 Testing LinkedIn posting functionality...")
    
    # Test with a sample user ID
    test_user_id = "vi8ekk"  # Replace with actual user ID
    
    # Check user status
    status = get_user_linkedin_status(test_user_id)
    logging.info(f"📊 User status: {status}")
    
    if status['has_credentials']:
        # Test posting
        success, message = post_to_linkedin_for_user(test_user_id)
        logging.info(f"📊 Test result: {'✅ Success' if success else '❌ Failed'} - {message}")
        return success, message
    else:
        message = f"❌ No LinkedIn credentials found for test user: {test_user_id}"
        logging.error(message)
        return False, message

if __name__ == "__main__":
    # Run test
    test_linkedin_posting()