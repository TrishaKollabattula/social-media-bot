# refresh_engagement.py - Flask endpoint for manual engagement refresh

from flask import Blueprint, request, jsonify
import requests
import logging
import boto3
import os
from datetime import datetime

refresh_bp = Blueprint('refresh_engagement', __name__)

AWS_REGION = os.getenv("AWS_REGION")
HUBSPOT_API_URL = os.getenv("HUBSPOT_API_URL")
API_VERSION = "202507"

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION) if AWS_REGION else None
social_tokens_table = dynamodb.Table("SocialTokens") if dynamodb else None

logging.basicConfig(level=logging.INFO)


@refresh_bp.route('/api/refresh-engagement', methods=['POST'])
def refresh_engagement():
    """
    Manually refresh engagement metrics for a user's recent LinkedIn posts
    
    Request body:
    {
        "user_id": "vi8ekk"
    }
    
    Returns:
    {
        "success": true,
        "message": "Refreshed engagement for 3 posts",
        "updated": 3,
        "total_posts": 5,
        "analytics": {...}
    }
    """
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({'error': 'user_id is required'}), 400
        
        logging.info(f"🔄 Manual engagement refresh requested for user: {user_id}")
        
        # Get user's LinkedIn credentials
        linkedin_creds = get_user_linkedin_credentials(user_id)
        
        if not linkedin_creds:
            return jsonify({
                'error': 'LinkedIn credentials not found. Please connect LinkedIn in the UI.'
            }), 404
        
        access_token = linkedin_creds.get('access_token')
        
        if not access_token:
            return jsonify({
                'error': 'LinkedIn access token missing. Please reconnect LinkedIn.'
            }), 400
        
        # Get user's recent LinkedIn posts
        recent_posts = get_user_recent_linkedin_posts(user_id)
        
        if not recent_posts:
            return jsonify({
                'success': True,
                'message': 'No recent LinkedIn posts to update',
                'updated': 0,
                'total_posts': 0
            }), 200
        
        logging.info(f"📊 Found {len(recent_posts)} recent posts for user {user_id}")
        
        updated_count = 0
        errors = []
        
        # Refresh engagement for each post
        for post in recent_posts[:10]:  # Limit to 10 most recent
            deal_id = post.get('deal_id')
            post_urn = post.get('post_urn')
            
            if not deal_id or not post_urn:
                logging.warning(f"⚠️ Missing deal_id or post_urn for post")
                continue
            
            try:
                # Fetch fresh analytics from LinkedIn API
                analytics = fetch_linkedin_post_analytics(post_urn, access_token)
                
                if analytics:
                    # Update HubSpot
                    success = update_engagement_in_hubspot(
                        deal_id,
                        analytics['impressions'],
                        analytics['likes'],
                        analytics['comments'],
                        analytics['shares'],
                        analytics['clicks']
                    )
                    
                    if success:
                        updated_count += 1
                        logging.info(f"✅ Updated engagement for post {post_urn}")
                    else:
                        errors.append(f"Failed to update HubSpot for {post_urn}")
                else:
                    errors.append(f"No analytics available for {post_urn}")
                    
            except Exception as e:
                error_msg = f"Error processing post {post_urn}: {str(e)}"
                logging.error(f"❌ {error_msg}")
                errors.append(error_msg)
                continue
        
        # Get updated analytics to return
        updated_analytics = get_user_analytics(user_id)
        
        response = {
            'success': True,
            'message': f'Refreshed engagement for {updated_count} posts',
            'updated': updated_count,
            'total_posts': len(recent_posts),
            'analytics': updated_analytics,
            'errors': errors if errors else None
        }
        
        logging.info(f"✅ Refresh complete: {updated_count}/{len(recent_posts)} posts updated")
        
        return jsonify(response), 200
        
    except Exception as e:
        logging.error(f"❌ Error refreshing engagement: {str(e)}")
        return jsonify({'error': str(e)}), 500


def get_user_linkedin_credentials(user_id):
    """Get LinkedIn credentials from DynamoDB"""
    try:
        if not social_tokens_table:
            return None
        
        response = social_tokens_table.get_item(
            Key={
                'user_id': user_id,
                'platform': 'linkedin'
            }
        )
        
        if 'Item' in response:
            item = response['Item']
            return {
                'access_token': item.get('linkedin_access_token'),
                'user_id': user_id
            }
        
        return None
        
    except Exception as e:
        logging.error(f"Error getting LinkedIn credentials: {e}")
        return None


def get_user_recent_linkedin_posts(user_id):
    """Get user's recent LinkedIn posts with deal_id and post_urn"""
    try:
        if not HUBSPOT_API_URL:
            return []
        
        # Get analytics from HubSpot
        response = requests.get(
            f"{HUBSPOT_API_URL}/crm/analytics",
            params={'user_id': user_id},
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            recent_posts = data.get('recent_posts', [])
            
            # Filter LinkedIn posts
            linkedin_posts = []
            for post in recent_posts:
                if post.get('platform') == 'LinkedIn' and post.get('post_urn'):
                    linkedin_posts.append({
                        'deal_id': post.get('deal_id'),
                        'post_urn': post.get('post_urn'),
                        'created_at': post.get('created_at')
                    })
            
            # Sort by created date (most recent first)
            linkedin_posts.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            
            return linkedin_posts
        
        return []
        
    except Exception as e:
        logging.error(f"Error getting recent posts: {e}")
        return []


def fetch_linkedin_post_analytics(post_urn, access_token):
    """Fetch analytics from LinkedIn API"""
    try:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": API_VERSION,
            "X-Restli-Protocol-Version": "2.0.0"
        }
        
        # Ensure correct URN format
        if not post_urn.startswith("urn:li:share:"):
            post_urn = f"urn:li:share:{post_urn}"
        
        # Get share statistics
        stats_url = f"https://api.linkedin.com/rest/socialMetadata/{post_urn}"
        
        response = requests.get(stats_url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            return {
                "impressions": data.get("impressionCount", 0),
                "likes": data.get("likeCount", 0),
                "comments": data.get("commentCount", 0),
                "shares": data.get("shareCount", 0),
                "clicks": data.get("clickCount", 0)
            }
        
        logging.warning(f"⚠️ LinkedIn API returned {response.status_code}")
        return None
        
    except Exception as e:
        logging.error(f"Error fetching LinkedIn analytics: {e}")
        return None


def update_engagement_in_hubspot(deal_id, impressions, likes, comments, shares, clicks):
    """Update engagement in HubSpot"""
    try:
        if not HUBSPOT_API_URL:
            return False
        
        payload = {
            "deal_id": deal_id,
            "impressions": impressions,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "clicks": clicks
        }
        
        response = requests.post(
            f"{HUBSPOT_API_URL}/crm/engagement",
            json=payload,
            timeout=10
        )
        
        return response.status_code == 200
        
    except Exception as e:
        logging.error(f"Error updating HubSpot engagement: {e}")
        return False


def get_user_analytics(user_id):
    """Get updated analytics for user"""
    try:
        if not HUBSPOT_API_URL:
            return None
        
        response = requests.get(
            f"{HUBSPOT_API_URL}/crm/analytics",
            params={'user_id': user_id},
            timeout=15
        )
        
        if response.status_code == 200:
            return response.json()
        
        return None
        
    except Exception as e:
        logging.error(f"Error getting analytics: {e}")
        return None