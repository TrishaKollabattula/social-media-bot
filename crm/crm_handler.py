import json
import logging
from datetime import datetime

from .comment_monitor import CommentMonitor
from .auto_reply import AutoReplySystem
from .crm_dynamodb import CRMDynamoDB as CRMDatabase


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CRMHandler:
    """Main CRM handler for webhook processing and API endpoints"""
    
    def __init__(self):
        self.comment_monitor = CommentMonitor()
        self.auto_reply = AutoReplySystem()
        self.db = CRMDatabase()
        self.db.connect()
    
    def __del__(self):
        """Cleanup"""
        if hasattr(self, 'db'):
            self.db.disconnect()
    
    # ==================== WEBHOOK HANDLERS ====================
    
    def handle_instagram_webhook(self, context):
        """
        Handle Instagram comment webhook
        
        Expected payload:
        {
            "comment_id": "instagram_comment_123",
            "user_id": "instagram_user_456",
            "comment_text": "What are your prices?",
            "post_id": "post_789"
        }
        """
        try:
            request = context["request"]
            data = json.loads(request.get("body", "{}"))
            
            # Validate required fields
            required_fields = ['comment_id', 'user_id', 'comment_text', 'post_id']
            for field in required_fields:
                if field not in data:
                    return {"error": f"Missing required field: {field}"}, 400
            
            # Add platform identifier
            comment_data = {
                'comment_id': data['comment_id'],
                'user_id': data['user_id'],
                'comment_text': data['comment_text'],
                'platform': 'instagram',
                'post_id': data['post_id']
            }
            
            # Process comment
            result = self.comment_monitor.process_comment(comment_data)
            
            # Auto-reply if query detected
            if result.get('should_reply') and result.get('reply_template'):
                reply_result = self.auto_reply.send_auto_reply(
                    comment_id=data['comment_id'],
                    platform='instagram',
                    reply_text=result['reply_template']
                )
                result['reply_result'] = reply_result
            
            # Send DM if high-value lead
            if result.get('should_send_dm') and result.get('lead_id'):
                dm_result = self.auto_reply.send_dm_to_lead(result['lead_id'])
                result['dm_result'] = dm_result
            
            logger.info(f"✅ Instagram webhook processed: {result}")
            return {"status": "success", "data": result}, 200
        
        except Exception as e:
            logger.error(f"❌ Error handling Instagram webhook: {e}")
            return {"error": str(e)}, 500
    
    def handle_linkedin_webhook(self, context):
        """
        Handle LinkedIn comment webhook
        
        Expected payload:
        {
            "comment_id": "linkedin_comment_urn",
            "user_id": "linkedin_user_urn",
            "comment_text": "Interested in learning more!",
            "post_id": "post_urn"
        }
        """
        try:
            request = context["request"]
            data = json.loads(request.get("body", "{}"))
            
            # Validate required fields
            required_fields = ['comment_id', 'user_id', 'comment_text', 'post_id']
            for field in required_fields:
                if field not in data:
                    return {"error": f"Missing required field: {field}"}, 400
            
            # Add platform identifier
            comment_data = {
                'comment_id': data['comment_id'],
                'user_id': data['user_id'],
                'comment_text': data['comment_text'],
                'platform': 'linkedin',
                'post_id': data['post_id']
            }
            
            # Process comment
            result = self.comment_monitor.process_comment(comment_data)
            
            # Auto-reply if query detected
            if result.get('should_reply') and result.get('reply_template'):
                reply_result = self.auto_reply.send_auto_reply(
                    comment_id=data['comment_id'],
                    platform='linkedin',
                    reply_text=result['reply_template']
                )
                result['reply_result'] = reply_result
            
            # Send DM if high-value lead
            if result.get('should_send_dm') and result.get('lead_id'):
                dm_result = self.auto_reply.send_dm_to_lead(result['lead_id'])
                result['dm_result'] = dm_result
            
            logger.info(f"✅ LinkedIn webhook processed: {result}")
            return {"status": "success", "data": result}, 200
        
        except Exception as e:
            logger.error(f"❌ Error handling LinkedIn webhook: {e}")
            return {"error": str(e)}, 500
    
    # ==================== DASHBOARD API ENDPOINTS ====================
    
    def get_dashboard(self, context):
        """
        Get dashboard summary
        
        Returns comprehensive metrics for the dashboard
        """
        try:
            summary = self.db.get_dashboard_summary()
            
            return {
                "status": "success",
                "data": summary,
                "generated_at": datetime.now().isoformat()
            }, 200
        
        except Exception as e:
            logger.error(f"❌ Error getting dashboard: {e}")
            return {"error": str(e)}, 500
    
    def get_lead_pipeline(self, context):
        """Get lead pipeline data"""
        try:
            pipeline = self.db.fetch_query("""
                SELECT 
                    status,
                    COUNT(*) as count,
                    AVG(lead_score) as avg_score,
                    SUM(CASE WHEN dm_sent = TRUE THEN 1 ELSE 0 END) as contacted
                FROM leads_table
                GROUP BY status
                ORDER BY 
                    CASE status
                        WHEN 'new' THEN 1
                        WHEN 'contacted' THEN 2
                        WHEN 'qualified' THEN 3
                        WHEN 'converted' THEN 4
                        WHEN 'lost' THEN 5
                    END
            """)
            
            return {
                "status": "success",
                "pipeline": pipeline
            }, 200
        
        except Exception as e:
            logger.error(f"❌ Error getting lead pipeline: {e}")
            return {"error": str(e)}, 500
    
    def get_leads(self, context):
        """
        Get leads with optional filtering
        
        Query parameters:
        - status: Filter by status
        - min_score: Minimum lead score
        - limit: Number of results
        """
        try:
            request = context["request"]
            params = request.get("queryStringParameters", {}) or {}
            
            status = params.get('status')
            min_score = int(params.get('min_score', 0))
            limit = int(params.get('limit', 50))
            
            if status:
                leads = self.db.get_leads_by_status(status, limit)
            elif min_score > 0:
                leads = self.db.get_high_score_leads(min_score, limit)
            else:
                leads = self.db.fetch_query(
                    "SELECT * FROM leads_table ORDER BY created_at DESC LIMIT %s",
                    (limit,)
                )
            
            return {
                "status": "success",
                "count": len(leads),
                "leads": leads
            }, 200
        
        except Exception as e:
            logger.error(f"❌ Error getting leads: {e}")
            return {"error": str(e)}, 500
    
    def get_comments(self, context):
        """
        Get comments with optional filtering
        
        Query parameters:
        - post_id: Filter by post
        - has_query: Filter by query presence (true/false)
        - platform: Filter by platform
        - limit: Number of results
        """
        try:
            request = context["request"]
            params = request.get("queryStringParameters", {}) or {}
            
            post_id = params.get('post_id')
            has_query = params.get('has_query')
            platform = params.get('platform')
            limit = int(params.get('limit', 50))
            
            conditions = []
            query_params = []
            
            if post_id:
                conditions.append("post_id = %s")
                query_params.append(post_id)
            
            if has_query:
                conditions.append("has_query = %s")
                query_params.append(has_query.lower() == 'true')
            
            if platform:
                conditions.append("platform = %s")
                query_params.append(platform)
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            query = f"""
                SELECT * FROM comments_table 
                WHERE {where_clause}
                ORDER BY created_at DESC 
                LIMIT %s
            """
            query_params.append(limit)
            
            comments = self.db.fetch_query(query, tuple(query_params))
            
            return {
                "status": "success",
                "count": len(comments),
                "comments": comments
            }, 200
        
        except Exception as e:
            logger.error(f"❌ Error getting comments: {e}")
            return {"error": str(e)}, 500
    
    def get_analytics(self, context):
        """
        Get analytics metrics
        
        Query parameters:
        - start_date: Start date (YYYY-MM-DD)
        - end_date: End date (YYYY-MM-DD)
        """
        try:
            request = context["request"]
            params = request.get("queryStringParameters", {}) or {}
            
            start_date = params.get('start_date')
            end_date = params.get('end_date')
            
            metrics = self.db.get_metrics(start_date, end_date)
            
            return {
                "status": "success",
                "metrics": metrics
            }, 200
        
        except Exception as e:
            logger.error(f"❌ Error getting analytics: {e}")
            return {"error": str(e)}, 500
    
    def update_lead_status(self, context):
        """
        Update lead status
        
        Payload:
        {
            "lead_id": "lead_123",
            "status": "qualified"
        }
        """
        try:
            request = context["request"]
            data = json.loads(request.get("body", "{}"))
            
            if 'lead_id' not in data or 'status' not in data:
                return {"error": "Missing lead_id or status"}, 400
            
            valid_statuses = ['new', 'contacted', 'qualified', 'converted', 'lost']
            if data['status'] not in valid_statuses:
                return {"error": f"Invalid status. Must be one of: {valid_statuses}"}, 400
            
            self.db.update_lead_status(data['lead_id'], data['status'])
            
            return {
                "status": "success",
                "message": f"Lead {data['lead_id']} updated to {data['status']}"
            }, 200
        
        except Exception as e:
            logger.error(f"❌ Error updating lead status: {e}")
            return {"error": str(e)}, 500
    
    def process_pending_dms(self, context):
        """
        Process and send DMs to high-value leads
        
        Query parameters:
        - min_score: Minimum lead score (default: 70)
        - batch_size: Number of leads to process (default: 10)
        """
        try:
            request = context["request"]
            params = request.get("queryStringParameters", {}) or {}
            
            min_score = int(params.get('min_score', 70))
            batch_size = int(params.get('batch_size', 10))
            
            result = self.auto_reply.process_high_value_leads(min_score, batch_size)
            
            return {
                "status": "success",
                "result": result
            }, 200
        
        except Exception as e:
            logger.error(f"❌ Error processing pending DMs: {e}")
            return {"error": str(e)}, 500
    
    def update_daily_analytics(self, context):
        """Update daily analytics metrics"""
        try:
            self.db.update_daily_metrics()
            
            return {
                "status": "success",
                "message": "Daily analytics updated"
            }, 200
        
        except Exception as e:
            logger.error(f"❌ Error updating analytics: {e}")
            return {"error": str(e)}, 500


if __name__ == "__main__":
    # Test CRM handler
    print("=== Testing CRM Handler ===\n")
    
    handler = CRMHandler()
    
    # Test Instagram webhook
    test_context = {
        "request": {
            "body": json.dumps({
                "comment_id": "ig_comment_123",
                "user_id": "ig_user_456",
                "comment_text": "This is amazing! What are your pricing plans? I'm very interested!",
                "post_id": "ig_post_789"
            })
        }
    }
    
    result, status = handler.handle_instagram_webhook(test_context)
    print("Instagram Webhook Result:")
    print(json.dumps(result, indent=2))
    print(f"\nStatus Code: {status}")