import os
import logging
import requests
from dotenv import load_dotenv
from .crm_dynamodb import CRMDynamoDB as CRMDatabase

import time

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AutoReplySystem:
    """Automated reply system for Instagram and LinkedIn comments"""
    
    def __init__(self):
        self.db = CRMDatabase()
        self.db.connect()
        
        # Instagram credentials
        self.instagram_access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
        self.instagram_user_id = os.getenv("INSTAGRAM_USER_ID")
        
        # LinkedIn credentials
        self.linkedin_access_token = os.getenv("LINKEDIN_ACCESS_TOKEN")
        self.linkedin_user_urn = os.getenv("LINKEDIN_USER_URN")
    
    def __del__(self):
        """Cleanup database connection"""
        if hasattr(self, 'db'):
            self.db.disconnect()
    
    # ==================== INSTAGRAM REPLY ====================
    
    def reply_instagram_comment(self, comment_id, reply_text):
        """
        Reply to an Instagram comment
        
        Args:
            comment_id: Instagram comment ID
            reply_text: Text to reply with
        
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            url = f"https://graph.facebook.com/v19.0/{comment_id}/replies"
            
            payload = {
                'message': reply_text,
                'access_token': self.instagram_access_token
            }
            
            response = requests.post(url, data=payload, timeout=10)
            response.raise_for_status()
            
            logger.info(f"✅ Instagram reply sent to comment {comment_id}")
            return True, f"Reply sent successfully: {response.json()}"
        
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to reply to Instagram comment: {e}")
            return False, f"Error: {str(e)}"
    
    def send_instagram_dm(self, user_id, message):
        """
        Send a direct message on Instagram
        
        Args:
            user_id: Instagram user ID
            message: Message text
        
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            # Note: Instagram DM API requires specific permissions
            url = f"https://graph.facebook.com/v19.0/me/messages"
            
            payload = {
                'recipient': {'id': user_id},
                'message': {'text': message},
                'access_token': self.instagram_access_token
            }
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            logger.info(f"✅ Instagram DM sent to user {user_id}")
            return True, "DM sent successfully"
        
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to send Instagram DM: {e}")
            return False, f"Error: {str(e)}"
    
    # ==================== LINKEDIN REPLY ====================
    
    def reply_linkedin_comment(self, comment_urn, reply_text):
        """
        Reply to a LinkedIn comment
        
        Args:
            comment_urn: LinkedIn comment URN
            reply_text: Text to reply with
        
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            url = "https://api.linkedin.com/v2/socialActions/{commentUrn}/comments"
            url = url.replace("{commentUrn}", comment_urn)
            
            headers = {
                'Authorization': f'Bearer {self.linkedin_access_token}',
                'Content-Type': 'application/json',
                'X-Restli-Protocol-Version': '2.0.0'
            }
            
            payload = {
                "actor": self.linkedin_user_urn,
                "message": {
                    "text": reply_text
                }
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            
            logger.info(f"✅ LinkedIn reply sent to comment {comment_urn}")
            return True, "Reply sent successfully"
        
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to reply to LinkedIn comment: {e}")
            return False, f"Error: {str(e)}"
    
    def send_linkedin_message(self, recipient_urn, message):
        """
        Send a LinkedIn message
        
        Args:
            recipient_urn: LinkedIn person URN
            message: Message text
        
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            url = "https://api.linkedin.com/v2/messages"
            
            headers = {
                'Authorization': f'Bearer {self.linkedin_access_token}',
                'Content-Type': 'application/json',
                'X-Restli-Protocol-Version': '2.0.0'
            }
            
            payload = {
                "recipients": [recipient_urn],
                "subject": "Thank you for your interest!",
                "body": message
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            
            logger.info(f"✅ LinkedIn message sent to {recipient_urn}")
            return True, "Message sent successfully"
        
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to send LinkedIn message: {e}")
            return False, f"Error: {str(e)}"
    
    # ==================== UNIFIED REPLY SYSTEM ====================
    
    def send_auto_reply(self, comment_id, platform, reply_text):
        """
        Send automated reply based on platform
        
        Args:
            comment_id: Comment identifier
            platform: 'instagram' or 'linkedin'
            reply_text: Text to reply with
        
        Returns:
            dict: Result with success status and message
        """
        result = {
            'comment_id': comment_id,
            'platform': platform,
            'reply_sent': False,
            'message': ''
        }
        
        try:
            if platform.lower() == 'instagram':
                success, message = self.reply_instagram_comment(comment_id, reply_text)
            elif platform.lower() == 'linkedin':
                success, message = self.reply_linkedin_comment(comment_id, reply_text)
            else:
                success = False
                message = f"Unsupported platform: {platform}"
            
            result['reply_sent'] = success
            result['message'] = message
            
            # Track the reply in database
            if success:
                comment = self.db.get_comment(comment_id)
                if comment:
                    self.db.track_interaction(
                        user_id=comment['user_id'],
                        interaction_type='reply',
                        comment_id=comment_id,
                        interaction_data={
                            'platform': platform,
                            'reply_text': reply_text
                        }
                    )
            
            return result
        
        except Exception as e:
            logger.error(f"❌ Error in send_auto_reply: {e}")
            result['message'] = str(e)
            return result
    
    def send_dm_to_lead(self, lead_id):
        """
        Send DM to a high-scoring lead
        
        Args:
            lead_id: Lead identifier
        
        Returns:
            dict: Result with success status
        """
        try:
            lead = self.db.get_lead(lead_id)
            if not lead:
                return {'success': False, 'message': 'Lead not found'}
            
            if lead['dm_sent']:
                return {'success': False, 'message': 'DM already sent to this lead'}
            
            # Get comment to determine platform
            comment = self.db.get_comment(lead['source_comment_id'])
            if not comment:
                return {'success': False, 'message': 'Source comment not found'}
            
            platform = comment['platform']
            user_id = lead['user_id']
            
            # Craft personalized DM message
            dm_message = self.craft_dm_message(lead['lead_score'])
            
            # Send DM based on platform
            if platform.lower() == 'instagram':
                success, message = self.send_instagram_dm(user_id, dm_message)
            elif platform.lower() == 'linkedin':
                success, message = self.send_linkedin_message(user_id, dm_message)
            else:
                return {'success': False, 'message': f'Unsupported platform: {platform}'}
            
            # Mark DM as sent in database
            if success:
                self.db.mark_dm_sent(lead_id)
                self.db.track_interaction(
                    user_id=user_id,
                    interaction_type='dm',
                    lead_id=lead_id,
                    interaction_data={
                        'platform': platform,
                        'message': dm_message,
                        'lead_score': lead['lead_score']
                    }
                )
                logger.info(f"✅ DM sent to lead {lead_id}")
            
            return {
                'success': success,
                'message': message,
                'lead_id': lead_id,
                'platform': platform
            }
        
        except Exception as e:
            logger.error(f"❌ Error sending DM to lead: {e}")
            return {'success': False, 'message': str(e)}
    
    def craft_dm_message(self, lead_score):
        """Craft a personalized DM message based on lead score"""
        if lead_score >= 90:
            return (
                "Hi there! 👋\n\n"
                "We noticed your strong interest in our services, and we'd love to connect with you personally! "
                "🌟 As a valued potential client, we'd like to offer you a priority consultation to discuss "
                "how we can help achieve your goals.\n\n"
                "📞 Call us at: 9115706096\n"
                "🌐 Visit: www.craftingbrain.com\n\n"
                "When would be a good time for a quick chat? Looking forward to speaking with you soon! 🚀"
            )
        elif lead_score >= 70:
            return (
                "Hello! 👋\n\n"
                "Thank you for your interest in what we do! We'd love to provide you with more detailed "
                "information about our services and how we can help you.\n\n"
                "📞 Give us a call: 9115706096\n"
                "🌐 Learn more: www.craftingbrain.com\n\n"
                "Feel free to reach out anytime. We're here to help! 💡"
            )
        else:
            return (
                "Hi! 👋\n\n"
                "Thanks for reaching out! We're excited to help you learn more about our services.\n\n"
                "📞 Contact: 9115706096\n"
                "🌐 Website: www.craftingbrain.com\n\n"
                "Don't hesitate to get in touch if you have any questions! 🙌"
            )
    
    def process_high_value_leads(self, min_score=70, batch_size=10):
        """
        Process high-value leads and send DMs
        
        Args:
            min_score: Minimum lead score threshold
            batch_size: Number of leads to process in one batch
        
        Returns:
            dict: Summary of DMs sent
        """
        try:
            leads = self.db.get_high_score_leads(min_score=min_score, limit=batch_size)
            
            results = {
                'total_leads': len(leads),
                'dms_sent': 0,
                'failed': 0,
                'details': []
            }
            
            for lead in leads:
                # Add delay between DMs to avoid rate limiting
                time.sleep(2)
                
                result = self.send_dm_to_lead(lead['lead_id'])
                
                if result['success']:
                    results['dms_sent'] += 1
                else:
                    results['failed'] += 1
                
                results['details'].append(result)
            
            logger.info(f"✅ Processed {results['total_leads']} leads, sent {results['dms_sent']} DMs")
            return results
        
        except Exception as e:
            logger.error(f"❌ Error processing high-value leads: {e}")
            return {'error': str(e)}


if __name__ == "__main__":
    # Test auto-reply system
    reply_system = AutoReplySystem()
    
    print("=== Testing Auto-Reply System ===\n")
    
    # Test crafting DM messages for different score ranges
    print("High-score DM (90+):")
    print(reply_system.craft_dm_message(95))
    print("\n" + "="*50 + "\n")
    
    print("Medium-score DM (70-89):")
    print(reply_system.craft_dm_message(75))
    print("\n" + "="*50 + "\n")
    
    print("Low-score DM (<70):")
    print(reply_system.craft_dm_message(60))