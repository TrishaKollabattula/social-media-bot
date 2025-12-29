import re
import logging
from datetime import datetime, timedelta  
import json
from boto3.dynamodb.conditions import Attr


from .crm_dynamodb import CRMDynamoDB as CRMDatabase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CommentMonitor:
    """Monitor and analyze comments from social media platforms"""
    
    # Query keywords for detection
    QUERY_KEYWORDS = [
        'price', 'cost', 'how much', 'pricing', 'fees', 'charges',
        'demo', 'demonstration', 'show me', 'trial',
        'features', 'capabilities', 'what can', 'functions',
        'support', 'help', 'issue', 'problem', 'assistance',
        'contact', 'reach out', 'email', 'phone', 'call',
        'interested', 'want more', 'tell me more', 'sign up', 'join'
    ]
    
    # Lead indicator keywords
    LEAD_KEYWORDS = [
        'interested', 'want more', 'contact me', 'sign up', 
        'join', 'tell me more', 'when can', 'how do i',
        'where can i', 'i need', 'looking for', 'can you help'
    ]
    
    def __init__(self):
        self.db = CRMDatabase()
        self.db.connect()
    
    def __del__(self):
        """Cleanup database connection"""
        if hasattr(self, 'db'):
            self.db.disconnect()
    
    def detect_query(self, comment_text):
        """Detect if a comment contains a query"""
        comment_lower = comment_text.lower()
        
        for keyword in self.QUERY_KEYWORDS:
            if keyword.lower() in comment_lower:
                return True, self.classify_query_type(comment_text)
        
        # Check for question marks as additional indicator
        if '?' in comment_text:
            return True, self.classify_query_type(comment_text)
        
        return False, None
    
    def classify_query_type(self, comment_text):
        """Classify the type of query"""
        comment_lower = comment_text.lower()
        
        query_types = {
            'price': ['price', 'cost', 'how much', 'pricing', 'fees', 'charges'],
            'demo': ['demo', 'demonstration', 'show me', 'trial'],
            'features': ['features', 'capabilities', 'what can', 'functions', 'what does'],
            'support': ['support', 'help', 'issue', 'problem', 'assistance'],
            'contact': ['contact', 'reach out', 'email', 'phone', 'call'],
            'interested': ['interested', 'want more', 'tell me more', 'sign up', 'join']
        }
        
        for query_type, keywords in query_types.items():
            for keyword in keywords:
                if keyword in comment_lower:
                    return query_type
        
        return 'general'
    
    def detect_lead_indicator(self, comment_text):
        """Detect if comment shows strong lead indicators"""
        comment_lower = comment_text.lower()
        
        for keyword in self.LEAD_KEYWORDS:
            if keyword in comment_lower:
                return True
        
        return False
    
    def calculate_engagement_score(self, comment_text, user_id):
        """Calculate engagement score (0-30 points)"""
        score = 0
        comment_lower = comment_text.lower()
        
        # Length of comment (up to 10 points)
        word_count = len(comment_text.split())
        if word_count > 20:
            score += 10
        elif word_count > 10:
            score += 7
        elif word_count > 5:
            score += 5
        else:
            score += 3
        
        # Contains question (5 points)
        if '?' in comment_text:
            score += 5
        
        # Personal pronouns indicate engagement (5 points)
        personal_pronouns = ['i', 'me', 'my', 'we', 'our']
        if any(pronoun in comment_lower.split() for pronoun in personal_pronouns):
            score += 5
        
        # Check if user has commented before (10 points for returning user)
        previous_comments = self.db.get_comments_by_user(user_id, limit=1)
        if previous_comments:  # any prior comment found
            score += 10
        
        return min(score, 30)
    
    def calculate_query_score(self, comment_text, has_query):
        """Calculate query score (0-40 points)"""
        if not has_query:
            return 0
        
        score = 20  # Base score for having a query
        comment_lower = comment_text.lower()
        
        # High-intent keywords (20 additional points)
        high_intent = ['price', 'buy', 'purchase', 'demo', 'sign up', 'interested', 'when can']
        if any(keyword in comment_lower for keyword in high_intent):
            score += 20
        # Medium-intent keywords (10 additional points)
        elif any(keyword in comment_lower for keyword in ['features', 'how does', 'tell me']):
            score += 10
        # Low-intent keywords (5 additional points)
        else:
            score += 5
        
        return min(score, 40)
    
    def calculate_lead_indicator_score(self, comment_text):
        """Calculate lead indicator score (0-30 points)"""
        score = 0
        comment_lower = comment_text.lower()
        
        # Count lead indicators
        lead_count = sum(1 for keyword in self.LEAD_KEYWORDS if keyword in comment_lower)
        
        if lead_count >= 3:
            score = 30
        elif lead_count == 2:
            score = 20
        elif lead_count == 1:
            score = 15
        
        # Specific strong indicators
        strong_indicators = ['sign up', 'interested', 'want to join', 'contact me', 'dm me']
        if any(indicator in comment_lower for indicator in strong_indicators):
            score = max(score, 25)
        
        return score
    
    def calculate_lead_score(self, comment_text, user_id, has_query):
        """
        Calculate total lead score (0-100)
        - Engagement: 0-30 points
        - Query relevance: 0-40 points
        - Lead indicators: 0-30 points
        """
        engagement_score = self.calculate_engagement_score(comment_text, user_id)
        query_score = self.calculate_query_score(comment_text, has_query)
        lead_score = self.calculate_lead_indicator_score(comment_text)
        
        total_score = engagement_score + query_score + lead_score
        
        logger.info(f"Lead Score Breakdown - Engagement: {engagement_score}, Query: {query_score}, Lead: {lead_score}, Total: {total_score}")
        
        return min(total_score, 100)
    
    def process_comment(self, comment_data):
        """
        Process a new comment from webhook
        
        Args:
            comment_data: dict with keys:
                - comment_id: unique comment identifier
                - user_id: user identifier
                - comment_text: the comment text
                - platform: 'instagram' or 'linkedin'
                - post_id: post identifier
        
        Returns:
            dict with processing results
        """
        try:
            comment_id = comment_data['comment_id']
            user_id = comment_data['user_id']
            comment_text = comment_data['comment_text']
            platform = comment_data['platform']
            post_id = comment_data['post_id']
            
            logger.info(f"📝 Processing comment {comment_id} from {user_id} on {platform}")
            
            # Step 1: Detect if comment has a query
            has_query, query_type = self.detect_query(comment_text)
            
            # Step 2: Store comment in database
            self.db.insert_comment(
                comment_id=comment_id,
                user_id=user_id,
                comment_text=comment_text,
                platform=platform,
                post_id=post_id,
                has_query=has_query
            )
            
            # Step 3: Track interaction
            self.db.track_interaction(
                user_id=user_id,
                interaction_type='comment',
                comment_id=comment_id,
                interaction_data={
                    'platform': platform,
                    'has_query': has_query,
                    'query_type': query_type
                }
            )
            
            # Step 4: Check if this is a lead
            has_lead_indicator = self.detect_lead_indicator(comment_text)
            
            result = {
                'comment_id': comment_id,
                'has_query': has_query,
                'query_type': query_type,
                'has_lead_indicator': has_lead_indicator,
                'should_reply': has_query,
                'should_create_lead': has_lead_indicator or (has_query and query_type in ['interested', 'price', 'demo'])
            }
            
            # Step 5: Calculate lead score if applicable
            if result['should_create_lead']:
                lead_score = self.calculate_lead_score(comment_text, user_id, has_query)
                lead_id = f"lead_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                
                self.db.insert_lead(
                    lead_id=lead_id,
                    user_id=user_id,
                    lead_score=lead_score,
                    source_comment_id=comment_id,
                    status='new'
                )
                
                result['lead_id'] = lead_id
                result['lead_score'] = lead_score
                result['should_send_dm'] = lead_score >= 70
                
                logger.info(f"✅ Lead created: {lead_id} with score {lead_score}")
                
                # Track lead creation
                self.db.track_interaction(
                    user_id=user_id,
                    interaction_type='lead_created',
                    comment_id=comment_id,
                    lead_id=lead_id,
                    interaction_data={'lead_score': lead_score}
                )
            
            # Step 6: Get reply template if query detected
            if has_query:
                template = self.db.match_reply_template(comment_text)
                if template:
                    result['reply_template'] = template['template_text']
                    result['template_type'] = template['query_type']
                else:
                    result['reply_template'] = self.generate_generic_reply()
                    result['template_type'] = 'generic'
            
            logger.info(f"✅ Comment processed successfully: {result}")
            return result
        
        except Exception as e:
            logger.error(f"❌ Error processing comment: {e}")
            return {'error': str(e)}
    
    def generate_generic_reply(self):
        """Generate a generic reply for comments without specific templates"""
        return (
            "Thank you for your comment! 🙌 We appreciate your interest. "
            "Please feel free to DM us or visit www.craftingbrain.com for more information. "
            "You can also reach us at 9115706096. Looking forward to connecting with you!"
        )
    
    def get_comment_analytics(self, start_date=None, end_date=None):
        """Aggregate comment analytics from DynamoDB by date + platform."""
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')

        start_iso = f"{start_date}T00:00:00"
        end_iso   = f"{end_date}T23:59:59"

        table = self.db.comments_table

        # Full scan with date filter; paginate if needed
        items = []
        scan_kwargs = {
            "FilterExpression": Attr("created_at").between(start_iso, end_iso)
        }
        while True:
            resp = table.scan(**scan_kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

        # Aggregate
        from collections import defaultdict
        agg = defaultdict(lambda: {"total_comments": 0, "query_comments": 0})

        for it in items:
            date = (it.get("created_at", "")[:10]) or "unknown"
            platform = it.get("platform", "unknown")
            key = (date, platform)
            agg[key]["total_comments"] += 1
            if it.get("has_query"):
                agg[key]["query_comments"] += 1

        # Flatten & sort by date desc
        out = []
        for (date, platform), vals in agg.items():
            out.append({
                "date": date,
                "platform": platform,
                "total_comments": vals["total_comments"],
                "query_comments": vals["query_comments"],
            })
        out.sort(key=lambda r: r["date"], reverse=True)
        return out



if __name__ == "__main__":
    # Test comment monitoring
    monitor = CommentMonitor()
    
    # Test comment 1: Query with lead indicator
    test_comment_1 = {
        'comment_id': 'test_001',
        'user_id': 'user_001',
        'comment_text': 'This looks amazing! What are your pricing plans? I am very interested in signing up!',
        'platform': 'instagram',
        'post_id': 'post_001'
    }
    
    result_1 = monitor.process_comment(test_comment_1)
    print("\n=== Test Comment 1 ===")
    print(json.dumps(result_1, indent=2))
    
    # Test comment 2: Simple query
    test_comment_2 = {
        'comment_id': 'test_002',
        'user_id': 'user_002',
        'comment_text': 'Can you tell me more about the features?',
        'platform': 'linkedin',
        'post_id': 'post_001'
    }
    
    result_2 = monitor.process_comment(test_comment_2)
    print("\n=== Test Comment 2 ===")
    print(json.dumps(result_2, indent=2))
    
    # Test comment 3: No query
    test_comment_3 = {
        'comment_id': 'test_003',
        'user_id': 'user_003',
        'comment_text': 'Great post! 👍',
        'platform': 'instagram',
        'post_id': 'post_001'
    }
    
    result_3 = monitor.process_comment(test_comment_3)
    print("\n=== Test Comment 3 ===")
    print(json.dumps(result_3, indent=2))