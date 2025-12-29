import boto3
from boto3.dynamodb.conditions import Key, Attr
import os
from dotenv import load_dotenv
import json
from datetime import datetime, timedelta
import logging
from decimal import Decimal
import uuid

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert Decimal to int/float for JSON serialization"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super(DecimalEncoder, self).default(obj)


class CRMDynamoDB:
    """DynamoDB handler for CRM operations"""
    
    def __init__(self):
        self.region = os.getenv("AWS_REGION", "ap-south-1")
        self.dynamodb = boto3.resource('dynamodb', region_name=self.region)
        
        # Table names
        self.comments_table_name = "CRM_Comments"
        self.leads_table_name = "CRM_Leads"
        self.posts_table_name = "CRM_Posts"
        self.templates_table_name = "CRM_ReplyTemplates"
        self.analytics_table_name = "CRM_Analytics"
        self.interactions_table_name = "CRM_UserInteractions"
        
        # Initialize tables
        self.comments_table = None
        self.leads_table = None
        self.posts_table = None
        self.templates_table = None
        self.analytics_table = None
        self.interactions_table = None
    
    def connect(self):
        """Initialize table connections"""
        try:
            self.comments_table = self.dynamodb.Table(self.comments_table_name)
            self.leads_table = self.dynamodb.Table(self.leads_table_name)
            self.posts_table = self.dynamodb.Table(self.posts_table_name)
            self.templates_table = self.dynamodb.Table(self.templates_table_name)
            self.analytics_table = self.dynamodb.Table(self.analytics_table_name)
            self.interactions_table = self.dynamodb.Table(self.interactions_table_name)
            
            # Test connection
            self.comments_table.table_status
            logger.info("✅ Connected to DynamoDB tables")
            return True
        except Exception as e:
            logger.error(f"❌ Error connecting to DynamoDB: {e}")
            return False
    
    def disconnect(self):
        """DynamoDB doesn't need explicit disconnect"""
        logger.info("DynamoDB connection closed")
    
    # ==================== COMMENT OPERATIONS ====================
    
    def insert_comment(self, comment_id, user_id, comment_text, platform, post_id, has_query=False):
        """Insert a new comment into DynamoDB"""
        try:
            timestamp = datetime.now().isoformat()
            
            item = {
                'comment_id': comment_id,
                'user_id': user_id,
                'comment_text': comment_text,
                'has_query': has_query,
                'platform': platform,
                'post_id': post_id,
                'created_at': timestamp,
                'updated_at': timestamp,
                'ttl': int((datetime.now() + timedelta(days=365)).timestamp())  # 1 year TTL
            }
            
            self.comments_table.put_item(Item=item)
            logger.info(f"✅ Comment {comment_id} inserted")
            return comment_id
        except Exception as e:
            logger.error(f"❌ Error inserting comment: {e}")
            return None
    
    def get_comment(self, comment_id):
        """Retrieve a comment by ID"""
        try:
            response = self.comments_table.get_item(Key={'comment_id': comment_id})
            return response.get('Item')
        except Exception as e:
            logger.error(f"❌ Error getting comment: {e}")
            return None
    
    def get_comments_by_post(self, post_id, limit=50):
        """Get all comments for a specific post using GSI"""
        try:
            response = self.comments_table.query(
                IndexName='PostIdIndex',
                KeyConditionExpression=Key('post_id').eq(post_id),
                Limit=limit,
                ScanIndexForward=False  # Sort by created_at descending
            )
            return response.get('Items', [])
        except Exception as e:
            logger.error(f"❌ Error getting comments by post: {e}")
            return []
    
    def get_comments_by_user(self, user_id, limit=50):
        """Get all comments by a specific user using GSI"""
        try:
            response = self.comments_table.query(
                IndexName='UserIdIndex',
                KeyConditionExpression=Key('user_id').eq(user_id),
                Limit=limit,
                ScanIndexForward=False
            )
            return response.get('Items', [])
        except Exception as e:
            logger.error(f"❌ Error getting comments by user: {e}")
            return []
    
    def fetch_query(self, filter_expression=None, limit=50):
        """Generic query method for compatibility"""
        try:
            if filter_expression:
                response = self.comments_table.scan(
                    FilterExpression=filter_expression,
                    Limit=limit
                )
            else:
                response = self.comments_table.scan(Limit=limit)
            return response.get('Items', [])
        except Exception as e:
            logger.error(f"❌ Error in fetch_query: {e}")
            return []
    
    # ==================== LEAD OPERATIONS ====================
    
    def insert_lead(self, lead_id, user_id, lead_score, source_comment_id=None, status='new'):
        """Insert a new lead"""
        try:
            timestamp = datetime.now().isoformat()
            
            item = {
                'lead_id': lead_id,
                'user_id': user_id,
                'lead_score': Decimal(str(lead_score)),
                'status': status,
                'source_comment_id': source_comment_id or '',
                'dm_sent': False,
                'dm_sent_at': '',
                'created_at': timestamp,
                'updated_at': timestamp,
                'ttl': int((datetime.now() + timedelta(days=365)).timestamp())
            }
            
            self.leads_table.put_item(Item=item)
            logger.info(f"✅ Lead {lead_id} inserted with score {lead_score}")
            return lead_id
        except Exception as e:
            logger.error(f"❌ Error inserting lead: {e}")
            return None
    
    def update_lead_score(self, lead_id, new_score):
        """Update lead score"""
        try:
            self.leads_table.update_item(
                Key={'lead_id': lead_id},
                UpdateExpression='SET lead_score = :score, updated_at = :updated',
                ExpressionAttributeValues={
                    ':score': Decimal(str(new_score)),
                    ':updated': datetime.now().isoformat()
                }
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error updating lead score: {e}")
            return False
    
    def update_lead_status(self, lead_id, status):
        """Update lead status"""
        try:
            self.leads_table.update_item(
                Key={'lead_id': lead_id},
                UpdateExpression='SET #status = :status, updated_at = :updated',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':status': status,
                    ':updated': datetime.now().isoformat()
                }
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error updating lead status: {e}")
            return False
    
    def mark_dm_sent(self, lead_id):
        """Mark that a DM has been sent to this lead"""
        try:
            timestamp = datetime.now().isoformat()
            self.leads_table.update_item(
                Key={'lead_id': lead_id},
                UpdateExpression='SET dm_sent = :sent, dm_sent_at = :time, updated_at = :updated',
                ExpressionAttributeValues={
                    ':sent': True,
                    ':time': timestamp,
                    ':updated': timestamp
                }
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error marking DM sent: {e}")
            return False
    
    def get_lead(self, lead_id):
        """Get lead by ID"""
        try:
            response = self.leads_table.get_item(Key={'lead_id': lead_id})
            return response.get('Item')
        except Exception as e:
            logger.error(f"❌ Error getting lead: {e}")
            return None
    
    def get_high_score_leads(self, min_score=70, limit=100):
        """Get leads with score above threshold"""
        try:
            response = self.leads_table.scan(
                FilterExpression=Attr('lead_score').gte(Decimal(str(min_score))) & Attr('dm_sent').eq(False),
                Limit=limit
            )
            
            # Sort by score descending
            items = response.get('Items', [])
            items.sort(key=lambda x: float(x.get('lead_score', 0)), reverse=True)
            return items
        except Exception as e:
            logger.error(f"❌ Error getting high score leads: {e}")
            return []
    
    def get_leads_by_status(self, status, limit=100):
        """Get leads by status using GSI"""
        try:
            response = self.leads_table.query(
                IndexName='StatusIndex',
                KeyConditionExpression=Key('status').eq(status),
                Limit=limit,
                ScanIndexForward=False
            )
            return response.get('Items', [])
        except Exception as e:
            logger.error(f"❌ Error getting leads by status: {e}")
            return []
    
    # ==================== POST OPERATIONS ====================
    
    def insert_post(self, post_id, platform, post_url=None, likes_count=0, comments_count=0):
        """Insert a new post"""
        try:
            timestamp = datetime.now().isoformat()
            
            item = {
                'post_id': post_id,
                'platform': platform,
                'post_url': post_url or '',
                'likes_count': likes_count,
                'comments_count': comments_count,
                'engagement_rate': Decimal('0'),
                'created_at': timestamp,
                'updated_at': timestamp,
                'ttl': int((datetime.now() + timedelta(days=365)).timestamp())
            }
            
            self.posts_table.put_item(Item=item)
            logger.info(f"✅ Post {post_id} inserted")
            return post_id
        except Exception as e:
            logger.error(f"❌ Error inserting post: {e}")
            return None
    
    def update_post_engagement(self, post_id, likes_count, comments_count):
        """Update post engagement metrics"""
        try:
            engagement_rate = (likes_count + comments_count * 3) / max(likes_count, 1) * 100
            
            self.posts_table.update_item(
                Key={'post_id': post_id},
                UpdateExpression='SET likes_count = :likes, comments_count = :comments, engagement_rate = :rate, updated_at = :updated',
                ExpressionAttributeValues={
                    ':likes': likes_count,
                    ':comments': comments_count,
                    ':rate': Decimal(str(engagement_rate)),
                    ':updated': datetime.now().isoformat()
                }
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error updating post engagement: {e}")
            return False
    
    def get_post(self, post_id):
        """Get post by ID"""
        try:
            response = self.posts_table.get_item(Key={'post_id': post_id})
            return response.get('Item')
        except Exception as e:
            logger.error(f"❌ Error getting post: {e}")
            return None
    
    def get_recent_posts(self, days=7, limit=50):
        """Get recent posts"""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
            
            response = self.posts_table.scan(
                FilterExpression=Attr('created_at').gte(cutoff_date),
                Limit=limit
            )
            
            items = response.get('Items', [])
            items.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            return items
        except Exception as e:
            logger.error(f"❌ Error getting recent posts: {e}")
            return []
    
    # ==================== REPLY TEMPLATE OPERATIONS ====================
    
    def get_reply_template(self, query_type):
        """Get reply template by query type"""
        try:
            response = self.templates_table.get_item(Key={'query_type': query_type})
            return response.get('Item')
        except Exception as e:
            logger.error(f"❌ Error getting reply template: {e}")
            return None
    
    def get_all_reply_templates(self):
        """Get all reply templates"""
        try:
            response = self.templates_table.scan()
            return response.get('Items', [])
        except Exception as e:
            logger.error(f"❌ Error getting all templates: {e}")
            return []
    
    def match_reply_template(self, comment_text):
        """Match comment to appropriate reply template"""
        try:
            templates = self.get_all_reply_templates()
            comment_lower = comment_text.lower()
            
            for template in templates:
                keywords = template.get('keywords', [])
                if isinstance(keywords, str):
                    keywords = json.loads(keywords)
                
                for keyword in keywords:
                    if keyword.lower() in comment_lower:
                        return template
            
            return None
        except Exception as e:
            logger.error(f"❌ Error matching template: {e}")
            return None
    
    # ==================== ANALYTICS OPERATIONS ====================
    
    def update_daily_metrics(self, metric_date=None):
        """Update daily analytics metrics"""
        try:
            if metric_date is None:
                metric_date = datetime.now().date().isoformat()
            
            # Count today's data using scan with filters
            start_time = f"{metric_date}T00:00:00"
            end_time = f"{metric_date}T23:59:59"
            
            # Count comments
            comments_response = self.comments_table.scan(
                FilterExpression=Attr('created_at').between(start_time, end_time)
            )
            total_comments = len(comments_response.get('Items', []))
            total_queries = sum(1 for item in comments_response.get('Items', []) if item.get('has_query'))
            
            # Count leads
            leads_response = self.leads_table.scan(
                FilterExpression=Attr('created_at').between(start_time, end_time)
            )
            leads_items = leads_response.get('Items', [])
            total_leads = len(leads_items)
            
            # Count DMs sent
            total_dms = sum(1 for item in leads_items if item.get('dm_sent'))
            
            # Calculate average score
            scores = [float(item.get('lead_score', 0)) for item in leads_items]
            avg_score = sum(scores) / len(scores) if scores else 0
            
            # Calculate conversion rate
            conversion_rate = (total_dms / total_leads * 100) if total_leads > 0 else 0
            
            # Store metrics
            item = {
                'metric_date': metric_date,
                'total_comments': total_comments,
                'total_queries': total_queries,
                'total_leads': total_leads,
                'total_dms_sent': total_dms,
                'avg_lead_score': Decimal(str(round(avg_score, 2))),
                'conversion_rate': Decimal(str(round(conversion_rate, 2))),
                'instagram_engagement': Decimal('0'),
                'linkedin_engagement': Decimal('0'),
                'created_at': datetime.now().isoformat(),
                'ttl': int((datetime.now() + timedelta(days=365)).timestamp())
            }
            
            self.analytics_table.put_item(Item=item)
            logger.info(f"✅ Analytics updated for {metric_date}")
            return True
        except Exception as e:
            logger.error(f"❌ Error updating daily metrics: {e}")
            return False
    
    def get_metrics(self, start_date=None, end_date=None):
        """Get analytics metrics for a date range"""
        try:
            if start_date is None:
                start_date = (datetime.now() - timedelta(days=30)).date().isoformat()
            if end_date is None:
                end_date = datetime.now().date().isoformat()
            
            response = self.analytics_table.scan(
                FilterExpression=Attr('metric_date').between(start_date, end_date)
            )
            
            items = response.get('Items', [])
            items.sort(key=lambda x: x.get('metric_date', ''), reverse=True)
            return items
        except Exception as e:
            logger.error(f"❌ Error getting metrics: {e}")
            return []
    
    def get_dashboard_summary(self):
        """Get summary metrics for dashboard"""
        try:
            today = datetime.now().date().isoformat()
            week_ago = (datetime.now() - timedelta(days=7)).date().isoformat()
            month_ago = (datetime.now() - timedelta(days=30)).date().isoformat()
            
            # Today's metrics
            today_metrics = self.analytics_table.get_item(Key={'metric_date': today})
            
            # Weekly metrics
            weekly_response = self.analytics_table.scan(
                FilterExpression=Attr('metric_date').between(week_ago, today)
            )
            weekly_items = weekly_response.get('Items', [])
            
            # Monthly metrics
            monthly_response = self.analytics_table.scan(
                FilterExpression=Attr('metric_date').between(month_ago, today)
            )
            monthly_items = monthly_response.get('Items', [])
            
            # Aggregate weekly
            weekly_summary = {
                'total_comments': sum(int(item.get('total_comments', 0)) for item in weekly_items),
                'total_queries': sum(int(item.get('total_queries', 0)) for item in weekly_items),
                'total_leads': sum(int(item.get('total_leads', 0)) for item in weekly_items),
                'total_dms_sent': sum(int(item.get('total_dms_sent', 0)) for item in weekly_items),
                'avg_lead_score': sum(float(item.get('avg_lead_score', 0)) for item in weekly_items) / len(weekly_items) if weekly_items else 0,
                'conversion_rate': sum(float(item.get('conversion_rate', 0)) for item in weekly_items) / len(weekly_items) if weekly_items else 0
            }
            
            # Aggregate monthly
            monthly_summary = {
                'total_comments': sum(int(item.get('total_comments', 0)) for item in monthly_items),
                'total_queries': sum(int(item.get('total_queries', 0)) for item in monthly_items),
                'total_leads': sum(int(item.get('total_leads', 0)) for item in monthly_items),
                'total_dms_sent': sum(int(item.get('total_dms_sent', 0)) for item in monthly_items),
                'avg_lead_score': sum(float(item.get('avg_lead_score', 0)) for item in monthly_items) / len(monthly_items) if monthly_items else 0,
                'conversion_rate': sum(float(item.get('conversion_rate', 0)) for item in monthly_items) / len(monthly_items) if monthly_items else 0
            }
            
            # Lead pipeline
            all_leads = self.leads_table.scan()
            lead_items = all_leads.get('Items', [])
            
            pipeline = []
            for status in ['new', 'contacted', 'qualified', 'converted', 'lost']:
                status_leads = [l for l in lead_items if l.get('status') == status]
                pipeline.append({
                    'status': status,
                    'count': len(status_leads),
                    'avg_score': sum(float(l.get('lead_score', 0)) for l in status_leads) / len(status_leads) if status_leads else 0,
                    'contacted': sum(1 for l in status_leads if l.get('dm_sent'))
                })
            
            # Top posts
            top_posts = self.posts_table.scan()
            post_items = top_posts.get('Items', [])
            post_items.sort(key=lambda x: float(x.get('engagement_rate', 0)), reverse=True)
            
            return {
                "today": today_metrics.get('Item', {}),
                "weekly": weekly_summary,
                "monthly": monthly_summary,
                "lead_pipeline": pipeline,
                "top_posts": post_items[:5]
            }
        except Exception as e:
            logger.error(f"❌ Error getting dashboard summary: {e}")
            return {}
    
    # ==================== USER INTERACTION TRACKING ====================
    
    def track_interaction(self, user_id, interaction_type, comment_id=None, lead_id=None, interaction_data=None):
        """Track user interaction"""
        try:
            interaction_id = str(uuid.uuid4())
            timestamp = datetime.now().isoformat()
            
            item = {
                'interaction_id': interaction_id,
                'user_id': user_id,
                'interaction_type': interaction_type,
                'comment_id': comment_id or '',
                'lead_id': lead_id or '',
                'interaction_data': json.dumps(interaction_data) if interaction_data else '{}',
                'created_at': timestamp,
                'ttl': int((datetime.now() + timedelta(days=365)).timestamp())
            }
            
            self.interactions_table.put_item(Item=item)
            return interaction_id
        except Exception as e:
            logger.error(f"❌ Error tracking interaction: {e}")
            return None


if __name__ == "__main__":
    # Test DynamoDB connection
    db = CRMDynamoDB()
    if db.connect():
        print("✅ DynamoDB connection successful!")
        
        # Test insert comment
        comment_id = db.insert_comment(
            comment_id="test_comment_1",
            user_id="test_user_1",
            comment_text="What are your pricing plans?",
            platform="instagram",
            post_id="test_post_1",
            has_query=True
        )
        print(f"✅ Test comment inserted: {comment_id}")
        
        # Test get comment
        comment = db.get_comment("test_comment_1")
        print(f"✅ Retrieved comment: {comment}")
        
        db.disconnect()
    else:
        print("❌ DynamoDB connection failed!")