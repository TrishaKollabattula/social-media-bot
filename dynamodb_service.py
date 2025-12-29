# core/dynamodb_service.py
import boto3
import os
from typing import Dict, Any, Optional
from botocore.exceptions import ClientError, NoCredentialsError
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DynamoDBService:
    """Service to fetch company data from DynamoDB with flexible business types"""
    
    def __init__(self):
        self.region_name = os.getenv('AWS_REGION', 'us-east-1')  # Default to us-east-1 if not set
        self.table_name = os.getenv('DYNAMODB_TABLE_NAME', 'UserSurveyData')
        
        # Use boto3 Session for credential chain (env > shared > IAM)
        self.session = boto3.Session(region_name=self.region_name)
        
        # Validate credentials early
        self._validate_credentials()
        
        # Initialize DynamoDB client (better for error handling than resource)
        self.client = self.session.client('dynamodb')
        
        # Validate table existence (optional, but helpful)
        self._validate_table()
    
    def _validate_credentials(self):
        """Validate AWS credentials using STS"""
        try:
            sts = self.session.client('sts')
            sts.get_caller_identity()
            logger.info("AWS credentials validated successfully.")
        except NoCredentialsError:
            logger.error("No AWS credentials found. Set via environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY) or ~/.aws/credentials.")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'UnrecognizedClient':
                logger.error(f"Invalid AWS security token: {e}. Regenerate access keys in AWS IAM Console and update credentials.")
            else:
                logger.error(f"ClientError validating AWS credentials: {e} (Code: {error_code}).")
        except Exception as e:
            logger.error(f"Error validating AWS credentials: {e}. Check setup.")
    
    def _validate_table(self):
        """Check if table exists"""
        try:
            self.client.describe_table(TableName=self.table_name)
            logger.info(f"DynamoDB table '{self.table_name}' exists and is accessible.")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                logger.error(f"DynamoDB table '{self.table_name}' not found. Verify name and region.")
            else:
                logger.error(f"Error accessing DynamoDB table: {e} (Code: {error_code}).")
    
    def get_company_data(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Fetch company survey data including answers column"""
        try:
            logger.info(f"Fetching data for user_id: {user_id}")
            
            # FIX 1: Use correct key name (userId instead of user_id)
            # FIX 2: Handle composite key - query for all records for this userId
            response = self.client.query(
                TableName=self.table_name,
                KeyConditionExpression='userId = :userId',
                ExpressionAttributeValues={
                    ':userId': {'S': user_id}
                },
                # Get the most recent record by sorting timestamp descending
                ScanIndexForward=False,
                Limit=1  # Only get the most recent record
            )
            
            if response.get('Items') and len(response['Items']) > 0:
                logger.info(f"✅ Found company data for {user_id}")
                return response['Items'][0]  # Return the most recent record
            else:
                logger.warning(f"❌ No data found for user_id: {user_id}")
                return {}
                
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ValidationException':
                logger.error("DynamoDB ValidationException: Key does not match schema.")
                self._log_table_schema()  # Auto-describe and log schema for fix
            elif error_code == 'UnrecognizedClient':
                logger.error(f"Invalid AWS security token in get_item: {e}. Regenerate credentials.")
            else:
                logger.error(f"DynamoDB ClientError: {e} (Code: {error_code}).")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return {}
    
    def get_company_data_by_timestamp(self, user_id: str, timestamp: str) -> Optional[Dict[str, Any]]:
        """Fetch specific company data by userId and timestamp"""
        try:
            logger.info(f"Fetching data for user_id: {user_id}, timestamp: {timestamp}")
            response = self.client.get_item(
                TableName=self.table_name,
                Key={
                    'userId': {'S': user_id},
                    'timestamp': {'S': timestamp}
                }
            )
            
            if 'Item' in response:
                logger.info(f"✅ Found company data for {user_id} at {timestamp}")
                return response['Item']
            else:
                logger.warning(f"❌ No data found for user_id: {user_id}, timestamp: {timestamp}")
                return {}
                
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ValidationException':
                logger.error("DynamoDB ValidationException: Key does not match schema.")
                self._log_table_schema()
            elif error_code == 'UnrecognizedClient':
                logger.error(f"Invalid AWS security token in get_item: {e}. Regenerate credentials.")
            else:
                logger.error(f"DynamoDB ClientError: {e} (Code: {error_code}).")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return {}
    
    def _log_table_schema(self):
        """Describe table and log key schema to help fix ValidationException"""
        try:
            response = self.client.describe_table(TableName=self.table_name)
            key_schema = response['Table']['KeySchema']
            attribute_defs = response['Table']['AttributeDefinitions']
            
            partition_key = next((k['AttributeName'] for k in key_schema if k['KeyType'] == 'HASH'), None)
            sort_key = next((k['AttributeName'] for k in key_schema if k['KeyType'] == 'RANGE'), None)
            
            logger.info(f"Table '{self.table_name}' Key Schema:")
            logger.info(f"- Partition Key (HASH): {partition_key} (Required)")
            if sort_key:
                logger.info(f"- Sort Key (RANGE): {sort_key} (Required if present)")
            logger.info(f"Attribute Types: {attribute_defs}")
            logger.info("FIXED: Now using query() for composite key and correct attribute names.")
        except Exception as e:
            logger.error(f"Error describing table schema: {e}. Check in AWS Console > DynamoDB > Tables > {self.table_name} > Overview.")
    
    def parse_company_context(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse raw DynamoDB data including answers column"""
        
        if not raw_data:
            return {}
        
        # Get answers data and business type
        answers = raw_data.get("answers", {})
        business_type = raw_data.get("business_type", "other")
        
        # Base company context - FIX: Use correct key name (userId)
        company_context = {
            "user_id": self._extract_string_value(raw_data.get("userId", "")),
            "business_type": self._extract_string_value(business_type),
            "company_name": self._extract_string_value(raw_data.get("company_name", "")),
            "industry": self._extract_string_value(business_type),  # Use business_type as industry
        }
        
        # Parse business-specific answers
        business_type_str = self._extract_string_value(business_type)
        if business_type_str == "technology":
            company_context.update(self._parse_technology_answers(answers))
        elif business_type_str == "restaurant":
            company_context.update(self._parse_restaurant_answers(answers))
        elif business_type_str == "finance":
            company_context.update(self._parse_finance_answers(answers))
        elif business_type_str == "education":
            company_context.update(self._parse_education_answers(answers))
        elif business_type_str == "healthcare":
            company_context.update(self._parse_healthcare_answers(answers))
        elif business_type_str == "real-estate":
            company_context.update(self._parse_real_estate_answers(answers))
        elif business_type_str == "ecommerce":
            company_context.update(self._parse_ecommerce_answers(answers))
        else:
            company_context.update(self._parse_other_answers(answers))
        
        # Parse common fields that might exist across all business types
        company_context.update({
            "contact_details": self._extract_string_value(answers.get("contact_details")),
            "post_schedule_time": self._extract_string_value(answers.get("post_schedule_time")),
            "color_theme": self._extract_list_values(answers.get("color_theme")),
        })
        
        logger.info(f"✅ Parsed {business_type_str} business context: {company_context.get('company_name', 'Unknown')}")
        return company_context
    
    def _parse_technology_answers(self, answers: Dict) -> Dict:
        """Parse technology business specific answers"""
        return {
            "products_services": self._extract_string_value(answers.get("tech_products")),
            "target_audience": self._extract_list_values(answers.get("target_audience")),
            "brand_values": self._extract_list_values(answers.get("brand_values")),
            "design_preference": self._extract_string_value(answers.get("design_preference")),
            "image_focus": self._extract_string_value(answers.get("image_focus")),
            "interactive_content": self._extract_string_value(answers.get("interactive_content")),
            "business_focus": "technology innovation and digital solutions"
        }
    
    def _parse_restaurant_answers(self, answers: Dict) -> Dict:
        """Parse restaurant business specific answers"""
        return {
            "products_services": self._extract_string_value(answers.get("cuisine_experience")),
            "target_audience": [self._extract_string_value(answers.get("typical_customers"))],
            "unique_selling_points": self._extract_string_value(answers.get("unique_qualities")),
            "content_highlights": self._extract_list_values(answers.get("content_highlight")),
            "image_preferences": self._extract_list_values(answers.get("image_preference")),
            "sustainability_focus": self._extract_string_value(answers.get("sustainability")),
            "business_focus": "food service and dining experience"
        }
    
    def _parse_finance_answers(self, answers: Dict) -> Dict:
        """Parse finance business specific answers"""
        return {
            "products_services": self._extract_string_value(answers.get("financial_products")),
            "target_audience": [self._extract_string_value(answers.get("target_audience"))],
            "brand_values": self._extract_list_values(answers.get("social_tone")),
            "image_focus": self._extract_list_values(answers.get("image_focus")),
            "visual_style": self._extract_list_values(answers.get("visual_style")),
            "include_data_visuals": self._extract_string_value(answers.get("include_data_visuals")),
            "business_focus": "financial services and solutions"
        }
    
    def _parse_education_answers(self, answers: Dict) -> Dict:
        """Parse education business specific answers"""
        return {
            "products_services": self._extract_string_value(answers.get("educational_services")),
            "target_audience": self._extract_list_values(answers.get("primary_audience")),
            "key_messages": self._extract_string_value(answers.get("key_messages")),
            "image_showcase": self._extract_list_values(answers.get("image_showcase")),
            "learning_format": self._extract_list_values(answers.get("learning_format")),
            "feature_content": self._extract_list_values(answers.get("feature_content")),
            "business_focus": "education and learning services"
        }
    
    def _parse_healthcare_answers(self, answers: Dict) -> Dict:
        """Parse healthcare business specific answers"""
        return {
            "products_services": self._extract_string_value(answers.get("healthcare_services")),
            "target_audience": self._extract_list_values(answers.get("primary_audience")),
            "brand_values": self._extract_list_values(answers.get("core_values")),
            "image_highlight": self._extract_list_values(answers.get("image_highlight")),
            "visual_focus": self._extract_list_values(answers.get("visual_focus")),
            "treatment_visuals": self._extract_string_value(answers.get("include_treatment_visuals")),
            "business_focus": "healthcare and wellness services"
        }
    
    def _parse_real_estate_answers(self, answers: Dict) -> Dict:
        """Parse real estate business specific answers"""
        return {
            "property_specialization": self._extract_list_values(answers.get("property_specialization")),
            "target_audience": self._extract_list_values(answers.get("main_clients")),
            "unique_selling_points": self._extract_string_value(answers.get("selling_points")),
            "image_showcase": self._extract_list_values(answers.get("image_showcase")),
            "client_stories": self._extract_string_value(answers.get("feature_client_stories")),
            "business_focus": "real estate and property services"
        }
    
    def _parse_ecommerce_answers(self, answers: Dict) -> Dict:
        """Parse ecommerce business specific answers"""
        return {
            "products_services": self._extract_string_value(answers.get("product_types")),
            "target_audience": [self._extract_string_value(answers.get("main_customers"))],
            "brand_values": self._extract_list_values(answers.get("brand_personality")),
            "image_style": self._extract_list_values(answers.get("image_style")),
            "content_highlight": self._extract_list_values(answers.get("content_highlight")),
            "ugc_strategy": self._extract_string_value(answers.get("ugc_strategy")),
            "business_focus": "ecommerce and retail sales"
        }
    
    def _parse_other_answers(self, answers: Dict) -> Dict:
        """Parse other/general business answers"""
        return {
            "products_services": self._extract_string_value(answers.get("business_description")),
            "target_audience": [self._extract_string_value(answers.get("target_audience"))],
            "key_messages": self._extract_string_value(answers.get("key_messages")),
            "image_style": self._extract_list_values(answers.get("image_style")),
            "visual_focus": self._extract_list_values(answers.get("visual_focus")),
            "preferred_themes": self._extract_string_value(answers.get("preferred_themes")),
            "business_focus": "general business services"
        }
    
    def _extract_string_value(self, dynamo_item) -> str:
        """Extract string value from DynamoDB format"""
        if isinstance(dynamo_item, dict) and 'S' in dynamo_item:
            return dynamo_item['S']
        elif isinstance(dynamo_item, str):
            return dynamo_item
        return ""
    
    def _extract_list_values(self, dynamo_item) -> list:
        """Extract list values from DynamoDB format"""
        if isinstance(dynamo_item, dict) and 'L' in dynamo_item:
            return [self._extract_string_value(item) for item in dynamo_item['L']]
        elif isinstance(dynamo_item, list):
            return dynamo_item
        return []