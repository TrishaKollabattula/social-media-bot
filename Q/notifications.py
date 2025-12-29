# Q/notifications.py — SMTP email notifications for job status updates
import os
import logging
import boto3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
DDB_USERS_TABLE = os.getenv("USERS_TABLE", "Users")

# Email configuration
EMAIL_ENABLED = os.getenv("EMAIL_NOTIFICATIONS", "true").lower() in ("1", "true", "yes")
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "smtp")
EMAIL_FROM = os.getenv("EMAIL_FROM", "noreply@craftingbrain.com")

# SMTP configuration
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() in ("1", "true", "yes")

log = logging.getLogger("Q.notifications")
log.setLevel(logging.INFO)

_ddb = boto3.resource("dynamodb", region_name=AWS_REGION)

def _get_user_email(username: str) -> Optional[str]:
    """Fetch user's email from DynamoDB Users table (PK = username)."""
    try:
        table = _ddb.Table(DDB_USERS_TABLE)
        resp = table.get_item(Key={"username": username})
        item = resp.get("Item")
        if not item:
            log.warning(f"Users[{username}] not found")
            return None
        email = item.get("email")
        if not email:
            log.warning(f"Users[{username}] has no 'email' field")
        return email
    except Exception as e:
        log.error(f"DDB lookup failed: {e}")
        return None

def _send_email_smtp(to_addr: str, subject: str, html: str, plain_text: str = None):
    """Send email via SMTP (Gmail)."""
    if not EMAIL_ENABLED:
        log.info(f"[DRY-RUN] Email to {to_addr}: {subject}")
        return

    if not SMTP_USER or not SMTP_PASS:
        log.error("SMTP_USER or SMTP_PASS not configured. Skipping email.")
        return

    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['From'] = EMAIL_FROM
        msg['To'] = to_addr
        msg['Subject'] = subject

        # Add plain text version
        if plain_text:
            part1 = MIMEText(plain_text, 'plain')
            msg.attach(part1)

        # Add HTML version
        part2 = MIMEText(html, 'html')
        msg.attach(part2)

        # Connect to SMTP server
        if SMTP_USE_SSL:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
            if SMTP_USE_TLS:
                server.starttls()

        # Login and send
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()

        log.info(f"✅ Email sent to {to_addr}: {subject}")

    except smtplib.SMTPAuthenticationError:
        log.error("❌ SMTP Authentication failed. Check SMTP_USER and SMTP_PASS.")
        log.error("   For Gmail: Use an App Password, not your regular password.")
        log.error("   Generate one at: https://myaccount.google.com/apppasswords")
    except Exception as e:
        log.error(f"❌ SMTP send_email failed: {e}")

def _build_queued_html(job_id: str, position: int, prompt_excerpt: str) -> tuple:
    """Build HTML and plain text for queued notification."""
    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9f9f9; border-radius: 10px;">
            <h2 style="color: #FFD700; text-align: center;">🎉 Your Request is Queued!</h2>
            <div style="background-color: white; padding: 20px; border-radius: 8px; margin-top: 20px;">
                <p>Dear Valued User,</p>
                <p>Thank you for using <strong>CraftingBrain</strong>! We've received your content generation request and it's been successfully added to our processing queue.</p>
                
                <div style="background-color: #f0f8ff; padding: 15px; border-left: 4px solid #FFD700; margin: 20px 0;">
                    <p><strong>📋 Job ID:</strong> {job_id}</p>
                    <p><strong>🎯 Your Theme:</strong> {prompt_excerpt}...</p>
                    <p><strong>📊 Queue Position:</strong> {position}</p>
                </div>

                <p><strong>What happens next?</strong></p>
                <ul>
                    <li>Your request is currently in position <strong>#{position}</strong> in our queue</li>
                    <li>We're processing requests in the order they were received</li>
                    <li>You'll receive another email when your content is ready</li>
                    <li>Estimated processing time: <strong>{position * 3} minutes</strong></li>
                </ul>

                <p style="margin-top: 20px;">Our AI is working hard to create amazing content for you! Please be patient while we generate high-quality images and content tailored to your theme.</p>

                <div style="background-color: #fff3cd; padding: 15px; border-radius: 5px; margin-top: 20px;">
                    <p style="margin: 0;"><strong>💡 Pro Tip:</strong> You can track your job status in real-time using the Job ID above in your dashboard.</p>
                </div>
            </div>

            <div style="text-align: center; margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd;">
                <p style="color: #666; font-size: 14px;">Thank you for choosing CraftingBrain!</p>
                <p style="color: #666; font-size: 12px;">For support, contact: <a href="tel:9115706096">9115706096</a> | <a href="http://www.craftingbrain.com">www.craftingbrain.com</a></p>
            </div>
        </div>
    </body>
    </html>
    """

    plain = f"""
    Your Request is Queued!

    Dear Valued User,

    Thank you for using CraftingBrain! We've received your content generation request.

    Job ID: {job_id}
    Your Theme: {prompt_excerpt}...
    Queue Position: {position}
    Estimated Time: {position * 3} minutes

    What happens next?
    - Your request is currently in position #{position}
    - We're processing requests in order
    - You'll receive another email when your content is ready

    Thank you for choosing CraftingBrain!
    Support: 9115706096 | www.craftingbrain.com
    """

    return html, plain

def _build_completed_html(job_id: str, result: Dict[str, Any]) -> tuple:
    """Build HTML and plain text for completed notification."""
    images = result.get("image_urls", [])
    pdf = result.get("pdf_url")
    
    # Build image links
    image_links = ""
    if images:
        image_items = "".join([f'<li><a href="{url}" style="color: #FFD700; text-decoration: none;">{url}</a></li>' for url in images])
        image_links = f"<p><strong>🖼️ Generated Images:</strong></p><ul>{image_items}</ul>"
    
    # Build PDF link
    pdf_link = ""
    if pdf:
        pdf_link = f'<p><strong>📄 PDF Document:</strong> <a href="{pdf}" style="color: #FFD700; text-decoration: none;">{pdf}</a></p>'

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9f9f9; border-radius: 10px;">
            <h2 style="color: #28a745; text-align: center;">✅ Your Content is Ready!</h2>
            <div style="background-color: white; padding: 20px; border-radius: 8px; margin-top: 20px;">
                <p>Dear Valued User,</p>
                <p>Great news! Your content generation request has been <strong>completed successfully</strong>! 🎉</p>
                
                <div style="background-color: #d4edda; padding: 15px; border-left: 4px solid #28a745; margin: 20px 0;">
                    <p><strong>✅ Status:</strong> Completed</p>
                    <p><strong>📋 Job ID:</strong> {job_id}</p>
                </div>

                <p><strong>Your Generated Content:</strong></p>
                {pdf_link}
                {image_links}

                <div style="background-color: #d1ecf1; padding: 15px; border-radius: 5px; margin-top: 20px;">
                    <p style="margin: 0;"><strong>📥 Next Steps:</strong></p>
                    <ul style="margin: 10px 0;">
                        <li>Click the links above to download your content</li>
                        <li>Share your amazing content on social media</li>
                        <li>Create more content anytime!</li>
                    </ul>
                </div>

                <p style="margin-top: 20px;">Thank you for using CraftingBrain! We hope you love your AI-generated content. 💛</p>
            </div>

            <div style="text-align: center; margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd;">
                <p style="color: #666; font-size: 14px;">Happy Creating!</p>
                <p style="color: #666; font-size: 12px;">For support, contact: <a href="tel:9115706096">9115706096</a> | <a href="http://www.craftingbrain.com">www.craftingbrain.com</a></p>
            </div>
        </div>
    </body>
    </html>
    """

    plain = f"""
    Your Content is Ready!

    Dear Valued User,

    Great news! Your content generation has been completed successfully!

    Status: Completed
    Job ID: {job_id}

    Your Generated Content:
    {f"PDF: {pdf}" if pdf else ""}
    {"Images: " + ", ".join(images) if images else ""}

    Thank you for using CraftingBrain!
    Support: 9115706096 | www.craftingbrain.com
    """

    return html, plain

def _build_failed_html(job_id: str, error_msg: str) -> tuple:
    """Build HTML and plain text for failed notification."""
    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9f9f9; border-radius: 10px;">
            <h2 style="color: #dc3545; text-align: center;">⚠️ Job Processing Failed</h2>
            <div style="background-color: white; padding: 20px; border-radius: 8px; margin-top: 20px;">
                <p>Dear Valued User,</p>
                <p>We're sorry, but we encountered an issue while processing your content generation request.</p>
                
                <div style="background-color: #f8d7da; padding: 15px; border-left: 4px solid #dc3545; margin: 20px 0;">
                    <p><strong>❌ Status:</strong> Failed</p>
                    <p><strong>📋 Job ID:</strong> {job_id}</p>
                    <p><strong>🔍 Issue:</strong> {error_msg}</p>
                </div>

                <p><strong>What you can do:</strong></p>
                <ul>
                    <li>Try submitting your request again</li>
                    <li>If the issue persists, contact our support team</li>
                    <li>Check if all required fields were filled correctly</li>
                </ul>

                <div style="background-color: #fff3cd; padding: 15px; border-radius: 5px; margin-top: 20px;">
                    <p style="margin: 0;"><strong>📞 Need Help?</strong></p>
                    <p style="margin: 5px 0;">Our support team is here to help!</p>
                    <p style="margin: 5px 0;">Call: <strong>9115706096</strong></p>
                    <p style="margin: 5px 0;">Visit: <a href="http://www.craftingbrain.com">www.craftingbrain.com</a></p>
                </div>

                <p style="margin-top: 20px;">We apologize for the inconvenience and appreciate your patience.</p>
            </div>

            <div style="text-align: center; margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd;">
                <p style="color: #666; font-size: 14px;">CraftingBrain Support Team</p>
                <p style="color: #666; font-size: 12px;">Call: <a href="tel:9115706096">9115706096</a> | <a href="http://www.craftingbrain.com">www.craftingbrain.com</a></p>
            </div>
        </div>
    </body>
    </html>
    """

    plain = f"""
    Job Processing Failed

    Dear Valued User,

    We're sorry, but we encountered an issue while processing your request.

    Status: Failed
    Job ID: {job_id}
    Issue: {error_msg}

    What you can do:
    - Try submitting your request again
    - Contact our support team if the issue persists
    - Check if all required fields were filled correctly

    Need Help?
    Call: 9115706096
    Visit: www.craftingbrain.com

    We apologize for the inconvenience.

    CraftingBrain Support Team
    """

    return html, plain

# Main notification functions
def notify_job_queued(job_id: str, user_email: str, position: int, prompt_excerpt: str):
    """Send email notification when job is queued."""
    try:
        if not user_email:
            log.warning(f"No email provided for job {job_id}. Skipping notification.")
            return

        subject = f"[CraftingBrain] Your Request is Queued - Job #{job_id[:8]}"
        html, plain = _build_queued_html(job_id, position, prompt_excerpt)
        _send_email_smtp(user_email, subject, html, plain)

    except Exception as e:
        log.error(f"notify_job_queued error: {e}")

def notify_job_completed(job_id: str, result: Dict[str, Any], user_id: str):
    """Send email notification when job completes successfully."""
    try:
        user_email = _get_user_email(user_id)
        if not user_email:
            log.warning(f"No email found for user {user_id}. Skipping notification.")
            return

        subject = f"[CraftingBrain] Your Content is Ready! - Job #{job_id[:8]}"
        html, plain = _build_completed_html(job_id, result)
        _send_email_smtp(user_email, subject, html, plain)

    except Exception as e:
        log.error(f"notify_job_completed error: {e}")

def notify_job_failed(job_id: str, error_msg: str, user_id: str):
    """Send email notification when job fails."""
    try:
        user_email = _get_user_email(user_id)
        if not user_email:
            log.warning(f"No email found for user {user_id}. Skipping notification.")
            return

        subject = f"[CraftingBrain] Job Processing Issue - Job #{job_id[:8]}"
        html, plain = _build_failed_html(job_id, error_msg)
        _send_email_smtp(user_email, subject, html, plain)

    except Exception as e:
        log.error(f"notify_job_failed error: {e}")

# Helper function for error message formatting
def get_friendly_error_message(raw: Any) -> str:
    """Map raw errors to a user-friendly message for UI/email."""
    msg = str(raw) if raw is not None else "Unknown error"
    lowered = msg.lower()
    
    if "no user_id" in lowered or "authentication" in lowered:
        return "User authentication required. Please sign in again."
    if "groq" in lowered or "api key" in lowered or "unauthorized" in lowered:
        return "Content engine is unavailable. Please try again later."
    if "sqs" in lowered or "queue" in lowered:
        return "Queue service is temporarily unavailable. Please try again."
    if "timeout" in lowered:
        return "The job took too long. Try again with fewer images."
    if "rate" in lowered or "throttle" in lowered:
        return "Too many requests. Please try again in a few minutes."
    if "linkedin" in lowered:
        return "LinkedIn posting failed. Please reconnect your account."
    if "image generation" in lowered or "selenium" in lowered or "chromedriver" in lowered:
        return "Image generator encountered an issue. Please try again."
    
    return "We couldn't complete the job. Please try again or contact support."