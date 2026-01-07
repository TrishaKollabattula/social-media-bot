#userhandler.py
import json
import time
import os
import re
import boto3
import jwt
import uuid
import base64
import bcrypt  # pip install bcrypt
from botocore.exceptions import ClientError
from decimal import Decimal
from dotenv import load_dotenv
import logging
import requests

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize AWS clients
dynamodb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION"))
s3_client = boto3.client("s3", region_name=os.getenv("AWS_REGION"))

users_table = dynamodb.Table("Users")
survey_table = dynamodb.Table("UserSurveyData")

S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
AWS_REGION = os.getenv("AWS_REGION")
SECRET_KEY = os.getenv("SECRET_KEY", "my-secure-secret-key-12345")

class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal types to JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super(DecimalEncoder, self).default(obj)

class UserHandler:
    def hash_password(self, password):
        """Hash a password using bcrypt"""
        try:
            salt = bcrypt.gensalt(rounds=12)
            hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
            return hashed.decode('utf-8')
        except Exception as e:
            logger.error(f"Error hashing password: {str(e)}")
            raise Exception("Error processing password")
    
    def verify_password(self, password, hashed_password):
        """Verify a password against its hash"""
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))
        except Exception as e:
            logger.error(f"Error verifying password: {str(e)}")
            return False

    def validate_email(self, email):
        """Validate email format"""
        pattern = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        return re.match(pattern, email) is not None

    def validate_username(self, username):
        """Validate username format"""
        if len(username) < 3:
            return False
        pattern = r'^[a-zA-Z0-9_]+$'
        return re.match(pattern, username) is not None

    def check_existing_user(self, username=None, email=None):
        """Check if user already exists by username or email"""
        try:
            if username:
                response = users_table.get_item(Key={"username": username})
                if response.get("Item"):
                    return "username"
            if email:
                response = users_table.scan(
                    FilterExpression="email = :email",
                    ExpressionAttributeValues={":email": email}
                )
                if response.get("Items"):
                    return "email"
            return None
        except ClientError as e:
            logger.error(f"Database error checking user: {str(e)}")
            raise Exception("Database error while checking existing user: " + str(e))

    def upload_logo_to_s3(self, logo_data, username):
        """Upload logo to S3 bucket in logos/ folder"""
        try:
            if not logo_data or not isinstance(logo_data, dict):
                logger.warning("No valid logo data provided")
                return None
            
            base64_data = logo_data.get("data", "")
            file_name = logo_data.get("fileName", "logo.png")
            file_type = logo_data.get("fileType", "image/png")
            
            if not base64_data:
                logger.warning("No base64 data in logo")
                return None
            
            if "," in base64_data:
                base64_data = base64_data.split(",")[1]
            
            try:
                image_bytes = base64.b64decode(base64_data)
            except Exception as e:
                logger.error(f"Failed to decode base64: {str(e)}")
                return None
            
            file_extension = file_name.split(".")[-1] if "." in file_name else "png"
            unique_filename = f"logos/{username}_{uuid.uuid4().hex[:8]}.{file_extension}"
            
            s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=unique_filename,
                Body=image_bytes,
                ContentType=file_type,
                ACL='public-read'
            )
            
            s3_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{unique_filename}"
            logger.info(f"✅ Logo uploaded to S3: {s3_url}")
            return s3_url
            
        except Exception as e:
            logger.error(f"❌ Error uploading logo to S3: {str(e)}")
            return None

    def login(self, context):
        """Handle user login with bcrypt password verification"""
        request = context["request"]
        body = request.get("body")
        logger.info(f"Login request received")

        if not body:
            raise Exception("Request body is empty")

        data = json.loads(body) if isinstance(body, str) else body
        username = data.get("username")
        password = data.get("password")
        remember_me = data.get("rememberMe", False)

        if not username or not password:
            raise Exception("Username and password are required")

        try:
            response = users_table.get_item(Key={"username": username})
            user = response.get("Item")

            if not user:
                raise Exception("Invalid username or password")
            
            hashed_password = user.get("password")
            if not hashed_password:
                raise Exception("Invalid username or password")
            
            # Check if password is already hashed (starts with $2b$)
            if hashed_password.startswith('$2b$'):
                # New encrypted password - verify with bcrypt
                if not self.verify_password(password, hashed_password):
                    raise Exception("Invalid username or password")
            else:
                # Old plain-text password - verify directly and then migrate
                if password != hashed_password:
                    raise Exception("Invalid username or password")
                
                # Hash and update password for security
                new_hashed = self.hash_password(password)
                users_table.update_item(
                    Key={"username": username},
                    UpdateExpression="SET password = :pwd, updated_at = :updated",
                    ExpressionAttributeValues={
                        ":pwd": new_hashed,
                        ":updated": int(time.time())
                    }
                )
                logger.info(f"✅ Migrated password for user: {username}")
            
            logger.info(f"✅ User {username} logged in successfully")
                
        except ClientError as e:
            logger.error(f"DynamoDB error during login: {str(e)}")
            raise Exception("DynamoDB error: " + str(e))

        # Set token expiration based on remember_me
        expiration_time = 30 * 24 * 3600 if remember_me else 3600  # 30 days or 1 hour
        
        token_payload = {
            "username": username,
            "name": user.get("name", ""),
            "email": user.get("email", ""),
            "exp": int(time.time()) + expiration_time
        }
        token = jwt.encode(token_payload, SECRET_KEY, algorithm="HS256")

        return {
            "token": token,
            "rememberMe": remember_me,
            "expiresIn": expiration_time,
            "user": {
                "username": username,
                "name": user.get("name", ""),
                "email": user.get("email", "")
            }
        }

    def register(self, context):
        """Handle user registration with bcrypt password hashing"""
        request = context["request"]
        body = request.get("body")
        logger.info(f"Register request received")

        if not body:
            raise Exception("Request body is empty")

        data = json.loads(body) if isinstance(body, str) else body

        name = data.get("name", "").strip()
        email = data.get("email", "").strip().lower()
        username = data.get("username", "").strip()
        password = data.get("password", "")
        confirm_password = data.get("confirmPassword", "")

        if not name and not data.get("surveyData"):
            raise Exception("Name is required")
        if not email and not data.get("surveyData"):
            raise Exception("Email is required")
        if not username and not data.get("surveyData"):
            raise Exception("Username is required")
        if not password and not data.get("surveyData"):
            raise Exception("Password is required")
        if not confirm_password and not data.get("surveyData"):
            raise Exception("Confirm Password is required")

        if password and confirm_password and password != confirm_password:
            raise Exception("Passwords do not match")

        if name and len(name) < 2:
            raise Exception("Name must be at least 2 characters")
        if email and not self.validate_email(email):
            raise Exception("Invalid email format")
        if username and not self.validate_username(username):
            raise Exception("Username must be at least 3 characters and contain only letters, numbers, and underscores")
        if password and len(password) < 6:
            raise Exception("Password must be at least 6 characters")

        if username and email:
            existing_check = self.check_existing_user(username=username, email=email)
            if existing_check == "username":
                raise Exception("Username already exists. Please choose another.")
            if existing_check == "email":
                raise Exception("Email already registered. Please use another email.")

        if name and email and username and password and confirm_password:
            try:
                # Hash the password before storing
                hashed_password = self.hash_password(password)
                
                user_item = {
                    "username": username,
                    "password": hashed_password,  # Store hashed password
                    "name": name,
                    "email": email,
                    "business_type": "Not specified",
                    "posts_created": 0,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time())
                }
                users_table.put_item(Item=user_item)
                logger.info(f"✅ User {username} registered with encrypted password")
            except ClientError as e:
                logger.error(f"Database error saving user: {str(e)}")
                raise Exception("Database error while saving user: " + str(e))

        # Handle survey data (rest remains the same as your original code)
        survey_data = data.get("surveyData")
        if survey_data:
            logger.info(f"📋 Processing survey data with potential logo")
            survey_user_id = survey_data.get("userId")
            
            if not survey_user_id:
                raise Exception("userId is required in surveyData")
            
            try:
                answers = survey_data.get("answers", {})
                logo_s3_url = None
                logo_filename = ""
                logo_filetype = ""
                logo_filesize = 0
                
                if isinstance(answers, dict) and "business_logo" in answers:
                    logo_data = answers.get("business_logo")
                    
                    if logo_data and isinstance(logo_data, dict):
                        logger.info(f"🖼️ Logo found, uploading to S3...")
                        logo_s3_url = self.upload_logo_to_s3(logo_data, survey_user_id)
                        
                        if logo_s3_url:
                            logo_filename = logo_data.get("fileName", "")
                            logo_filetype = logo_data.get("fileType", "")
                            logo_filesize = logo_data.get("fileSize", 0)
                            logger.info(f"✅ Logo uploaded to S3: {logo_s3_url}")
                        else:
                            logger.warning("⚠️ Failed to upload logo to S3")
                    
                    answers["business_logo"] = None
                
                survey_item = {
                    "userId": survey_user_id,
                    "business_type": survey_data.get("businessType", ""),
                    "answers": answers,
                    "timestamp": survey_data.get("timestamp", str(int(time.time()))),
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                    "is_anonymous": False,
                    "has_logo": bool(logo_s3_url),
                    "logo_s3_url": logo_s3_url or "",
                    "logo_filename": logo_filename,
                    "logo_filetype": logo_filetype,
                    "logo_filesize": logo_filesize
                }

                survey_table.put_item(Item=survey_item)
                logger.info(f"✅ Survey data saved with userId={survey_user_id}")
                
                if survey_data.get("businessType"):
                    try:
                        users_table.update_item(
                            Key={"username": survey_user_id},
                            UpdateExpression="SET business_type = :bt, updated_at = :updated",
                            ExpressionAttributeValues={
                                ":bt": survey_data.get("businessType"),
                                ":updated": int(time.time())
                            }
                        )
                        logger.info(f"✅ Updated business_type for user {survey_user_id}")
                    except ClientError as e:
                        logger.error(f"❌ Error updating business_type: {str(e)}")
                
            except ClientError as e:
                logger.error(f"❌ Database error saving survey data: {str(e)}")
                raise Exception("Database error while saving survey data: " + str(e))

        token = None
        if name and email and username and password and confirm_password:
            token_payload = {
                "username": username,
                "name": name,
                "email": email,
                "exp": int(time.time()) + 3600
            }
            token = jwt.encode(token_payload, SECRET_KEY, algorithm="HS256")

        return {
            "message": "User registered successfully!" if (name and email and username and password and confirm_password) else "Survey data saved successfully!",
            "token": token,
            "user": {
                "username": username,
                "name": name,
                "email": email
            } if (name and email and username and password and confirm_password) else {}
        }
        
    def get_profile(self, context):
        """
        Get user profile information from DynamoDB including survey data and logo S3 URL
        """
        try:
            # Get username from JWT claims
            claims = context.get("claims")
            if not claims:
                raise Exception("Unauthorized - No claims found")
            
            username = claims.get("username")
            if not username:
                raise Exception("Username not found in token")

            logger.info(f"📊 Fetching profile for user: {username}")

            # Query DynamoDB for user data
            response = users_table.get_item(Key={'username': username})
            
            if 'Item' not in response:
                raise Exception("User not found")
            
            user_data = response['Item']
            
            # Fetch survey data - Use query instead of get_item since there's a sort key
            scheduled_time = "Not set"
            color_theme = []
            business_type_from_survey = None
            has_logo = False
            logo_s3_url = None
            logo_filename = None
            profile_image = user_data.get("profile_image", None)
            
            try:
                # Query by partition key (userId) - this will get the latest entry
                survey_response = survey_table.query(
                    KeyConditionExpression='userId = :uid',
                    ExpressionAttributeValues={':uid': username},
                    ScanIndexForward=False,  # Get most recent first
                    Limit=1
                )
                
                if survey_response.get('Items') and len(survey_response['Items']) > 0:
                    survey_item = survey_response['Items'][0]
                    answers = survey_item.get("answers", {})
                    
                    logger.info(f"📋 Survey answers retrieved: {type(answers)}")
                    
                    # Extract scheduledTime and colorTheme from answers
                    if isinstance(answers, dict):
                        scheduled_time = answers.get("post_schedule_time", "Not set")
                        
                        # Handle color_theme - it can be a list or string
                        raw_color_theme = answers.get("color_theme", [])
                        if isinstance(raw_color_theme, str):
                            try:
                                color_theme = json.loads(raw_color_theme)
                            except:
                                color_theme = []
                        elif isinstance(raw_color_theme, list):
                            color_theme = raw_color_theme
                        else:
                            color_theme = []
                        
                        logger.info(f"✅ Retrieved scheduled_time: {scheduled_time}, color_theme: {color_theme}")
                    
                    business_type_from_survey = survey_item.get("business_type", None)
                    has_logo = survey_item.get("has_logo", False)
                    logo_s3_url = survey_item.get("logo_s3_url", None)
                    logo_filename = survey_item.get("logo_filename", None)
                    
                    logger.info(f"✅ Survey data retrieved - Has Logo: {has_logo}, S3 URL: {logo_s3_url}")
                else:
                    logger.warning(f"⚠️ No survey data found for user {username}")
                    
            except Exception as e:
                logger.error(f"❌ Error fetching survey data for user {username}: {str(e)}")
            
            # Remove sensitive data before sending
            if 'password' in user_data:
                del user_data['password']
            
            # Convert Decimal to int for JSON serialization
            created_at = user_data.get("created_at")
            updated_at = user_data.get("updated_at")
            posts_created = user_data.get("posts_created", 0)
            
            # Convert color_theme to JSON string if it's a list
            color_theme_response = json.dumps(color_theme) if isinstance(color_theme, list) and color_theme else "Not set"
            
            # Return user profile data with survey data
            return {
                "username": user_data.get("username"),
                "email": user_data.get("email"),
                "name": user_data.get("name"),
                "profile_image": profile_image,
                "created_at": int(created_at) if created_at else None,
                "updated_at": int(updated_at) if updated_at else None,
                "business_type": business_type_from_survey or user_data.get("business_type", "Not specified"),
                "posts_created": int(posts_created) if posts_created else 0,
                "scheduled_time": scheduled_time,
                "color_theme": color_theme_response,
                "has_logo": has_logo,
                "logo_s3_url": logo_s3_url,
                "logo_filename": logo_filename,
                "connected_accounts": 0  # Placeholder - implement tracking later
            }

        except Exception as e:
            logger.error(f"❌ Error fetching profile: {str(e)}")
            raise Exception(f"Error fetching profile: {str(e)}")

    def get_user_logo(self, context):
        """
        Retrieve user's business logo S3 URL from DynamoDB
        Returns the S3 URL of the logo
        """
        try:
            claims = context.get("claims")
            if not claims:
                raise Exception("Unauthorized - No claims found")
            
            username = claims.get("username")
            if not username:
                raise Exception("Username not found in token")

            logger.info(f"🖼️ Fetching logo for user: {username}")

            # Fetch survey data
            survey_response = survey_table.get_item(Key={'userId': username})
            
            if 'Item' not in survey_response:
                return {
                    "has_logo": False,
                    "message": "Survey data not found"
                }
            
            survey_item = survey_response['Item']
            
            if not survey_item.get("has_logo", False):
                return {
                    "has_logo": False,
                    "message": "No logo uploaded"
                }
            
            logo_s3_url = survey_item.get("logo_s3_url", "")
            
            if not logo_s3_url:
                return {
                    "has_logo": False,
                    "message": "Logo S3 URL not found"
                }
            
            logger.info(f"✅ Logo S3 URL retrieved: {logo_s3_url}")
            
            return {
                "has_logo": True,
                "logo_s3_url": logo_s3_url,
                "file_name": survey_item.get("logo_filename", ""),
                "file_type": survey_item.get("logo_filetype", ""),
                "file_size": survey_item.get("logo_filesize", 0)
            }

        except Exception as e:
            logger.error(f"❌ Error fetching logo: {str(e)}")
            raise Exception(f"Error fetching logo: {str(e)}")

    def update_profile(self, context):
        """
        Update user profile information (name, email, business_type)
        """
        try:
            claims = context.get("claims")
            if not claims:
                raise Exception("Unauthorized - No claims found")
            
            username = claims.get("username")
            if not username:
                raise Exception("Username not found in token")
            
            request = context["request"]
            body = json.loads(request.get("body", "{}"))
            
            logger.info(f"📝 Updating profile for user: {username}")

            # Fields that can be updated
            update_expression = "SET "
            expression_values = {}
            expression_names = {}
            
            updatable_fields = {
                "name": "#n",
                "email": "#e",
                "business_type": "#bt"
            }
            
            updates = []
            for field, placeholder in updatable_fields.items():
                if field in body:
                    # Validate email if updating
                    if field == "email" and not self.validate_email(body[field]):
                        raise Exception("Invalid email format")
                    
                    # Validate name if updating
                    if field == "name" and len(body[field].strip()) < 2:
                        raise Exception("Name must be at least 2 characters")
                    
                    updates.append(f"{placeholder} = :{field}")
                    expression_values[f":{field}"] = body[field]
                    expression_names[placeholder] = field
            
            if not updates:
                raise Exception("No fields to update")
            
            update_expression += ", ".join(updates)
            
            # Add updated_at timestamp
            expression_values[":updated"] = int(time.time())
            expression_names["#ua"] = "updated_at"
            update_expression += ", #ua = :updated"

            # Update in DynamoDB
            response = users_table.update_item(
                Key={'username': username},
                UpdateExpression=update_expression,
                ExpressionAttributeValues=expression_values,
                ExpressionAttributeNames=expression_names,
                ReturnValues="ALL_NEW"
            )
            
            updated_data = response['Attributes']
            if 'password' in updated_data:
                del updated_data['password']
            
            # Convert Decimal to int for JSON serialization
            created_at = updated_data.get("created_at")
            updated_at = updated_data.get("updated_at")
            posts_created = updated_data.get("posts_created", 0)
            
            logger.info(f"✅ Profile updated successfully for user: {username}")
            
            return {
                "message": "Profile updated successfully",
                "user": {
                    "username": updated_data.get("username"),
                    "email": updated_data.get("email"),
                    "name": updated_data.get("name"),
                    "created_at": int(created_at) if created_at else None,
                    "updated_at": int(updated_at) if updated_at else None,
                    "business_type": updated_data.get("business_type", "Not specified"),
                    "posts_created": int(posts_created) if posts_created else 0
                }
            }

        except Exception as e:
            logger.error(f"❌ Error updating profile: {str(e)}")
            raise Exception(f"Error updating profile: {str(e)}")

    def update_preferences(self, context):
        """
        Update user preferences (scheduled_time, color_theme, business_type, and logo) in UserSurveyData table
        """
        try:
            claims = context.get("claims")
            if not claims:
                raise Exception("Unauthorized - No claims found")
            
            username = claims.get("username")
            if not username:
                raise Exception("Username not found in token")
            
            request = context["request"]
            body = json.loads(request.get("body", "{}"))
            
            logger.info(f"⚙️ Updating preferences for user: {username}")
            logger.info(f"📦 Request body: {body}")

            scheduled_time = body.get("scheduled_time")
            color_theme = body.get("color_theme")
            business_type = body.get("business_type")
            logo_data = body.get("logo_data")

            if not scheduled_time and not color_theme and not business_type and not logo_data:
                raise Exception("No preferences to update")

            # Check if survey data exists for the user
            try:
                # Query by userId to get the latest survey data based on timestamp
                survey_response = survey_table.query(
                    KeyConditionExpression='userId = :uid',
                    ExpressionAttributeValues={':uid': username},
                    ScanIndexForward=False,  # Get most recent entry first
                    Limit=1
                )
                
                logo_s3_url = None
                update_expression_parts = []
                expression_attribute_values = {}
                expression_attribute_names = {}
                
                if survey_response.get('Items'):
                    # Update existing survey entry
                    survey_item = survey_response['Items'][0]
                    timestamp = survey_item['timestamp']
                    answers = survey_item.get("answers", {})
                    
                    # Ensure answers is a dict
                    if not isinstance(answers, dict):
                        answers = {}

                    # Update answers with new preferences if provided
                    if scheduled_time:
                        answers["post_schedule_time"] = scheduled_time
                        logger.info(f"✅ Updated scheduled_time to: {scheduled_time}")
                    
                    if color_theme:
                        answers["color_theme"] = color_theme
                        logger.info(f"✅ Updated color_theme to: {color_theme}")
                    
                    # Handle logo update if provided
                    if logo_data:
                        logger.info(f"🖼️ Processing logo upload...")
                        logo_s3_url = self.upload_logo_to_s3(logo_data, username)
                        if logo_s3_url:
                            logger.info(f"✅ Logo uploaded to: {logo_s3_url}")
                            update_expression_parts.append("#has_logo = :has_logo")
                            update_expression_parts.append("#logo_s3_url = :logo_s3_url")
                            update_expression_parts.append("#logo_filename = :logo_filename")
                            update_expression_parts.append("#logo_filetype = :logo_filetype")
                            update_expression_parts.append("#logo_filesize = :logo_filesize")
                            
                            expression_attribute_names["#has_logo"] = "has_logo"
                            expression_attribute_names["#logo_s3_url"] = "logo_s3_url"
                            expression_attribute_names["#logo_filename"] = "logo_filename"
                            expression_attribute_names["#logo_filetype"] = "logo_filetype"
                            expression_attribute_names["#logo_filesize"] = "logo_filesize"
                            
                            expression_attribute_values[":has_logo"] = True
                            expression_attribute_values[":logo_s3_url"] = logo_s3_url
                            expression_attribute_values[":logo_filename"] = logo_data.get("fileName", "")
                            expression_attribute_values[":logo_filetype"] = logo_data.get("fileType", "")
                            expression_attribute_values[":logo_filesize"] = logo_data.get("fileSize", 0)
                    
                    # Build update expression
                    update_expression_parts.append("#answers = :answers")
                    update_expression_parts.append("#updated_at = :updated")
                    
                    expression_attribute_names["#answers"] = "answers"
                    expression_attribute_names["#updated_at"] = "updated_at"
                    
                    expression_attribute_values[":answers"] = answers
                    expression_attribute_values[":updated"] = int(time.time())
                    
                    # Handle business_type update
                    if business_type:
                        update_expression_parts.append("#business_type = :business_type")
                        expression_attribute_names["#business_type"] = "business_type"
                        expression_attribute_values[":business_type"] = business_type
                        logger.info(f"✅ Updated business_type to: {business_type}")
                    
                    update_expression = "SET " + ", ".join(update_expression_parts)
                    
                    # Update the survey table
                    survey_table.update_item(
                        Key={'userId': username, 'timestamp': timestamp},
                        UpdateExpression=update_expression,
                        ExpressionAttributeNames=expression_attribute_names,
                        ExpressionAttributeValues=expression_attribute_values
                    )
                    logger.info(f"✅ Updated preferences for user: {username}")
                else:
                    # Create new survey entry if no data found
                    logger.info(f"📝 Creating new survey entry for user: {username}")
                    answers = {}
                    if scheduled_time:
                        answers["post_schedule_time"] = scheduled_time
                    if color_theme:
                        answers["color_theme"] = color_theme
                    
                    # Handle logo update if provided
                    if logo_data:
                        logo_s3_url = self.upload_logo_to_s3(logo_data, username)
                        if logo_s3_url:
                            logger.info(f"✅ Logo uploaded to: {logo_s3_url}")
                    
                    survey_item = {
                        "userId": username,
                        "business_type": business_type or "Not specified",
                        "answers": answers,
                        "timestamp": str(int(time.time())),
                        "created_at": int(time.time()),
                        "updated_at": int(time.time()),
                        "is_anonymous": False,
                        "has_logo": bool(logo_s3_url),
                        "logo_s3_url": logo_s3_url or "",
                        "logo_filename": logo_data.get("fileName", "") if logo_data else "",
                        "logo_filetype": logo_data.get("fileType", "") if logo_data else "",
                        "logo_filesize": logo_data.get("fileSize", 0) if logo_data else 0
                    }
                    survey_table.put_item(Item=survey_item)
                    logger.info(f"✅ Created new survey entry with preferences for user: {username}")
                
                # Return response
                response = {
                    "message": "Preferences updated successfully",
                    "scheduled_time": scheduled_time or answers.get("post_schedule_time", "Not set"),
                    "color_theme": color_theme or answers.get("color_theme", "Not set"),
                    "business_type": business_type or (survey_item['business_type'] if 'survey_item' in locals() else answers.get("business_type", "Not set"))
                }
                
                if logo_s3_url:
                    response["logo_s3_url"] = logo_s3_url
                    response["has_logo"] = True
                
                return response
                
            except ClientError as e:
                logger.error(f"❌ Error updating preferences: {str(e)}")
                raise Exception(f"Error updating preferences: {str(e)}")

        except Exception as e:
            logger.error(f"❌ Error updating preferences: {str(e)}")
            raise Exception(f"Error updating preferences: {str(e)}")

    def upload_profile_image(self, context):
        """
        Upload user profile image to S3
        """
        try:
            claims = context.get("claims")
            if not claims:
                raise Exception("Unauthorized - No claims found")
            
            username = claims.get("username")
            if not username:
                raise Exception("Username not found in token")
            
            request = context["request"]
            body = json.loads(request.get("body", "{}"))
            
            image_data = body.get("image_data")
            file_name = body.get("file_name", "profile.png")
            file_type = body.get("file_type", "image/png")
            
            if not image_data:
                raise Exception("No image data provided")
            
            # Remove data URL prefix if present
            if "," in image_data:
                image_data = image_data.split(",")[1]
            
            # Decode base64
            try:
                image_bytes = base64.b64decode(image_data)
            except Exception as e:
                logger.error(f"Failed to decode base64: {str(e)}")
                raise Exception("Invalid image data")
            
            # Generate unique filename
            file_extension = file_name.split(".")[-1] if "." in file_name else "png"
            unique_filename = f"profile_images/{username}_{uuid.uuid4().hex[:8]}.{file_extension}"
            
            # Upload to S3
            s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=unique_filename,
                Body=image_bytes,
                ContentType=file_type,
                ACL='public-read'
            )
            
            # Generate S3 URL
            image_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{unique_filename}"
            
            # Update user profile with image URL
            users_table.update_item(
                Key={'username': username},
                UpdateExpression="SET profile_image = :img, updated_at = :updated",
                ExpressionAttributeValues={
                    ":img": image_url,
                    ":updated": int(time.time())
                }
            )
            
            logger.info(f"✅ Profile image uploaded to S3: {image_url}")
            
            return {
                "message": "Profile image uploaded successfully",
                "image_url": image_url
            }
            
        except Exception as e:
            logger.error(f"❌ Error uploading profile image: {str(e)}")
            raise Exception(f"Error uploading profile image: {str(e)}")

    def linkedin_callback(self, context):
        """
        Handle LinkedIn OAuth callback.
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

        # Make request to LinkedIn to exchange code
        token_url = "https://www.linkedin.com/oauth/v2/accessToken"
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": os.getenv("LINKEDIN_REDIRECT_URI"),
            "client_id": os.getenv("LINKEDIN_CLIENT_ID"),
            "client_secret": os.getenv("LINKEDIN_CLIENT_SECRET")
        }

        response = requests.post(token_url, data=payload)
        response.raise_for_status()
        token_data = response.json()

        access_token = token_data.get("access_token")
        if not access_token:
            raise Exception(f"Failed to get access token: {token_data}")

        return {"access_token": access_token}

    def get_social_status(self, context):
        """
        Get social media connection status for a user
        Returns which platforms are connected
        """
        try:
            request = context["request"]
            query_params = request.get("queryStringParameters", {})
            app_user = query_params.get("app_user")
            
            if not app_user:
                raise Exception("app_user parameter is required")
            
            logger.info(f"📊 Fetching social status for user: {app_user}")
            
            # Query user data to check connected platforms
            response = users_table.get_item(Key={'username': app_user})
            
            if 'Item' not in response:
                return {
                    "status": "success",
                    "connected": {
                        "instagram": False,
                        "linkedin": False,
                        "twitter": False,
                        "facebook": False
                    },
                    "total_connected": 0
                }
            
            user_data = response['Item']
            
            # Check for connected platforms
            instagram_connected = bool(user_data.get("instagram_token"))
            linkedin_connected = bool(user_data.get("linkedin_token"))
            twitter_connected = bool(user_data.get("twitter_token"))
            facebook_connected = bool(user_data.get("facebook_token"))
            
            total_connected = sum([
                instagram_connected,
                linkedin_connected,
                twitter_connected,
                facebook_connected
            ])
            
            return {
                "status": "success",
                "connected": {
                    "instagram": instagram_connected,
                    "linkedin": linkedin_connected,
                    "twitter": twitter_connected,
                    "facebook": facebook_connected
                },
                "total_connected": total_connected
            }
            
        except Exception as e:
            logger.error(f"❌ Error fetching social status: {str(e)}")
            return {
                "status": "error",
                "message": str(e),
                "connected": {
                    "instagram": False,
                    "linkedin": False,
                    "twitter": False,
                    "facebook": False
                },
                "total_connected": 0
            }