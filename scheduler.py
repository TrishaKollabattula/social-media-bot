import os
import json
import time
import boto3
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pytz
import schedule
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
import openai
import logging

try:
    from content_handler import ContentHandler as ContentGenerator
except ImportError:
    from content_handler import ContentGenerator

# Import Instagram, LinkedIn, and Twitter posting functions
from social_media.instagram_post import post_carousel_to_instagram
from social_media.linkedin_post import post_content_to_linkedin, post_pdf_to_linkedin, post_image_to_linkedin
from social_media.twitter_post import post_content_to_twitter  # ✅ Added Twitter import

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
AWS_REGION = os.getenv("AWS_REGION")
INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID")
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN")
# Updated to use ORG_URN for organization posting
LINKEDIN_ORG_URN = os.getenv("LINKEDIN_ORG_URN", "urn:li:organization:99331065")
CHROME_PROFILE_PATH1 = os.getenv("CHROME_PROFILE_PATH1")
S3_PROMPT_KEY_PREFIX = "user_prompts"
IMAGES_FOLDER = "images/"

# Validate environment variables
required_env_vars = [
    OPENAI_API_KEY,
    S3_BUCKET_NAME,
    AWS_REGION,
    INSTAGRAM_USER_ID,
    INSTAGRAM_ACCESS_TOKEN,
    LINKEDIN_ACCESS_TOKEN,
    LINKEDIN_ORG_URN,
    CHROME_PROFILE_PATH1
]
if not all(required_env_vars):
    logger.error("Missing required environment variables")
    raise ValueError("Missing required environment variables")

# Validate Chrome profile path
if not os.path.exists(CHROME_PROFILE_PATH1):
    logger.error(f"Chrome profile path does not exist: {CHROME_PROFILE_PATH1}")
    raise ValueError(f"Chrome profile path does not exist: {CHROME_PROFILE_PATH1}")

client = openai.OpenAI(api_key=OPENAI_API_KEY)
s3 = boto3.client("s3", region_name=AWS_REGION)

def delete_yesterday_prompt():
    tz = pytz.timezone("Asia/Kolkata")
    yesterday = (datetime.now(tz) - timedelta(days=1)).strftime('%Y-%m-%d')
    prompt_key = f"{S3_PROMPT_KEY_PREFIX}/{yesterday}_prompt.txt"
    try:
        s3.delete_object(Bucket=S3_BUCKET_NAME, Key=prompt_key)
        logger.info(f"🗑️ Deleted yesterday's prompt: {prompt_key}")
    except s3.exceptions.NoSuchKey:
        logger.info(f"✅ No prompt to delete for {yesterday}.")
    except Exception as e:
        logger.error(f"❌ Error deleting prompt: {e}")

def setup_selenium_driver():
    options = Options()
    options.add_argument(f"user-data-dir={CHROME_PROFILE_PATH1}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    # Explicitly disable headless mode to avoid detection
    # options.add_argument("--headless=new")  # Uncomment if headless mode is needed
    try:
        logger.info("Initializing ChromeDriver with webdriver_manager")
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )
        logger.info("ChromeDriver initialized successfully")
        return driver
    except WebDriverException as e:
        logger.error(f"Failed to initialize ChromeDriver: {e}")
        raise

def fetch_trending_from_chatgpt():
    driver = setup_selenium_driver()
    try:
        logger.info("Navigating to ChatGPT")
        driver.get("https://chat.openai.com/chat")
        input_field = WebDriverWait(driver, 40).until(
            EC.presence_of_element_located((By.XPATH, "//*[@id='prompt-textarea']"))
        )
        logger.info("Input field located, sending prompt")
        input_field.click()
        input_field.send_keys("List the top 10 non-sensitive trending topics in India for today focused on technology, AI, data science, and machine learning. Exclude political, religious, or controversial topics.")
        input_field.send_keys(Keys.RETURN)
        time.sleep(25)  # Adjust based on response time
        message_blocks = driver.find_elements(By.XPATH, "//div[contains(@data-message-author-role,'assistant')]")
        if not message_blocks:
            logger.error("❌ No assistant response found.")
            return ""
        response = message_blocks[-1].text.strip()
        logger.info(f"✅ Raw assistant text: {response}")
        return response
    except TimeoutException as e:
        logger.error(f"Timeout while fetching trending topics: {e}")
        return ""
    except WebDriverException as e:
        logger.error(f"WebDriver error while fetching trending topics: {e}")
        return ""
    finally:
        try:
            driver.quit()
            logger.info("WebDriver closed")
        except Exception as e:
            logger.warning(f"Error closing WebDriver: {e}")

def choose_best_topic(response):
    lines = [line.strip() for line in response.split("\n") if line.strip()]
    relevant_keywords = [
        "AI", "Artificial Intelligence", "machine learning", "data", "Google", "GPT", "tech", "robot", "analytics"
    ]
    # Keywords to identify header-like lines to exclude
    header_indicators = ["top 10", "here are", "summary insights"]

    def is_valid_topic(line):
        # Exclude lines that are headers or summaries
        return not any(indicator.lower() in line.lower() for indicator in header_indicators) and len(line) > 20

    def score(topic):
        # Score based on keywords and presence of specific terms (e.g., proper nouns)
        keyword_score = sum(1 for kw in relevant_keywords if kw.lower() in topic.lower())
        # Boost score for topics with specific names (e.g., "Sarvam.ai", "Kruti")
        specific_score = 2 if any(word[0].isupper() for word in topic.split()) else 0
        return keyword_score + specific_score

    # Filter valid topic lines
    valid_topics = [line for line in lines if is_valid_topic(line)]
    if not valid_topics:
        logger.warning("No valid topics found, using fallback")
        fallback = "Explore the future of GenAI and its role in data science."
        logger.info(f"🎯 Selected Topic (Fallback): {fallback}")
        return fallback

    # Score and sort valid topics
    scored_topics = [(line, score(line)) for line in valid_topics]
    logger.info(f"Scored topics: {scored_topics}")
    scored = sorted(scored_topics, key=lambda x: x[1], reverse=True)
    selected = scored[0][0]
    logger.info(f"🎯 Selected Topic: {selected}")
    return selected

def generate_molded_prompt(selected_topic):
    return f"Create an engaging and informative social media post about '{selected_topic}' and how it's influencing Data Science and Machine Learning trends in India and how it's influencing Data Science and Machine Learning trends in India Make it informative and educational for tech professionals and enthusiasts."

def store_prompt_in_s3(prompt):
    today = datetime.now(pytz.timezone("Asia/Kolkata")).strftime('%Y-%m-%d')
    prompt_key = f"{S3_PROMPT_KEY_PREFIX}/{today}_prompt.txt"
    try:
        s3.put_object(Bucket=S3_BUCKET_NAME, Key=prompt_key, Body=prompt.encode('utf-8'))
        logger.info(f"✅ Prompt stored: {prompt_key}")
    except Exception as e:
        logger.error(f"❌ Error storing prompt: {e}")
        raise

def wait_for_s3_object(bucket, key, timeout=300, interval=5):
    """Wait until the S3 object is available."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            s3.head_object(Bucket=bucket, Key=key)
            logger.info(f"S3 object {key} is available")
            return True
        except s3.exceptions.ClientError:
            logger.info(f"Waiting for S3 object {key}...")
            time.sleep(interval)
    logger.error(f"S3 object {key} not available after {timeout} seconds")
    return False

def load_caption_from_content_details():
    """
    Load caption from content_details.json summary.
    Returns a formatted caption or default message.
    """
    try:
        with open("content_details.json", 'r') as file:
            data = json.load(file)
            summary = data.get('summary', [])
            if summary:
                # Format as paragraph instead of bullet points
                caption = " ".join(summary)  # Join with spaces instead of newlines
                caption += "\n\n#DataScience #AI #MachineLearning #TechTrends #Innovation"
                logger.info(f"Loaded caption from summary: {caption[:100]}...")
                return caption
            else:
                # Fallback to default caption
                default_caption = "🚀 Explore the latest insights in Data Science and AI! #DataScience #AI #Innovation"
                logger.info("No summary found, using default caption")
                return default_caption
    except FileNotFoundError:
        logger.warning("content_details.json not found, using default caption")
        return "🚀 Check out our latest insights! #DataScience #AI #Innovation"
    except json.JSONDecodeError:
        logger.error("Invalid JSON in content_details.json, using default caption")
        return "🚀 Check out our latest insights! #DataScience #AI #Innovation"

def scheduler_task():
    logger.info("🚀 Scheduler started.")
    trending_response = fetch_trending_from_chatgpt()
    selected_topic = choose_best_topic(trending_response)
    logger.info(f"🎯 Selected Topic: {selected_topic}")

    molded_prompt = generate_molded_prompt(selected_topic)
    logger.info(f"✍️ Molded Prompt: {molded_prompt}")

    store_prompt_in_s3(molded_prompt)

    num_images = 2  # Explicitly set num_images
    content_generator = ContentGenerator()
    try:
        image_result = content_generator.generate({
            "request": {
                "body": json.dumps({
                    "prompt": molded_prompt,
                    "contentType": "Informative",
                    "numImages": num_images,
                    "platforms": {
                        "instagram": True,
                        "linkedin": True,
                        "twitter": True,  # ✅ Added Twitter platform
                        "linkedin_access_token": LINKEDIN_ACCESS_TOKEN,
                        "linkedin_person_urn": LINKEDIN_ORG_URN  # Using org URN
                    }
                })
            }
        })
        logger.info(f"🖼️ Generated image result: {image_result}")
    except Exception as e:
        logger.error(f"❌ Content generation failed: {e}")
        return

    # Load caption from content_details.json with fallback to original logic
    final_caption = molded_prompt  # Fallback caption
    try:
        with open("content_details.json", "r") as f:
            content_details = json.load(f)
            captions = content_details.get("captions", {})
            
            # Try original logic first
            if "post_caption" in captions:
                final_caption = captions["post_caption"]
                logger.info(f"✅ Using post_caption from content_details.json")
            else:
                # Use new caption loading logic
                final_caption = load_caption_from_content_details()
                logger.info(f"✅ Using summary-based caption from content_details.json")
    except Exception as e:
        logger.error(f"⚠ Failed to load caption, using molded prompt: {e}")
        final_caption = molded_prompt

    # Extract and filter image URLs
    image_urls = []
    if isinstance(image_result, tuple):
        response_data = image_result[0] if len(image_result) > 0 else {}
    else:
        response_data = image_result

    image_urls = response_data.get("image_urls", []) if isinstance(response_data.get("image_urls"), list) else []
    image_urls = [
        url for url in image_urls
        if url.startswith(f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{IMAGES_FOLDER}")
        or "AWSAccessKeyId" in url
    ]
    logger.info(f"Filtered image_urls: {image_urls}")

    # Verify images are available in S3
    if image_urls:
        image_keys = [
            url.split(f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/")[1]
            if url.startswith(f"https://{S3_BUCKET_NAME}")
            else url.split("Key=")[1].split("&")[0]
            for url in image_urls
        ]
        for key in image_keys:
            if not wait_for_s3_object(S3_BUCKET_NAME, key):
                logger.error(f"Image {key} not available in S3")
                return
    else:
        # Fallback to latest S3 images
        try:
            response_s3 = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix=IMAGES_FOLDER)
            image_keys = [obj['Key'] for obj in response_s3.get('Contents', []) if obj['Key'] != IMAGES_FOLDER]
            if not image_keys:
                logger.error("No images found in S3 for social media posts")
                return
            sorted_keys = sorted(response_s3['Contents'], key=lambda x: x['LastModified'], reverse=True)
            selected_keys = [obj['Key'] for obj in sorted_keys if obj['Key'] != IMAGES_FOLDER][:num_images]
            image_urls = [f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{key}" for key in selected_keys]
            logger.info(f"Fetched image_urls from S3: {image_urls}")
        except Exception as e:
            logger.error(f"Failed to fetch images from S3: {str(e)}")
            return

    # =================== POST TO ALL PLATFORMS ===================

    # # 1. Post to Instagram
    # if image_urls:
    #     logger.info(f"📸 Posting {num_images} generated images to Instagram...")
    #     try:
    #         ig_result = post_carousel_to_instagram(
    #             image_urls=image_urls,
    #             caption=final_caption,
    #             num_images=num_images
    #         )
    #         logger.info(f"✅ [INSTAGRAM POST RESULT] {ig_result}")
    #     except Exception as e:
    #         logger.error(f"❌ Failed to post to Instagram: {e}")
    # else:
    #     logger.error("No valid image URLs for Instagram post")

    # 2. Post to Twitter
    logger.info("🐦 Posting to Twitter...")
    try:
        twitter_result = post_content_to_twitter(caption=final_caption)
        logger.info(f"✅ [TWITTER POST RESULT] {twitter_result}")
    except Exception as e:
        logger.error(f"❌ Failed to post to Twitter: {e}")

    # 3. Post to LinkedIn - ONLY POST PDF, NOT INDIVIDUAL IMAGES
    pdf_url = response_data.get("pdf_url")
    linkedin_results = []
    
    # Post PDF if available
    if pdf_url and pdf_url.startswith(f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/pdfs/"):
        logger.info(f"📄 [DEBUG] Posting PDF to LinkedIn: {pdf_url}")
        try:
            success, message = post_pdf_to_linkedin(
                s3_pdf_url=pdf_url,
                caption=f"{final_caption} (PDF with {len(image_urls)} images)",
                access_token=LINKEDIN_ACCESS_TOKEN,
                org_urn=LINKEDIN_ORG_URN  # Using org URN
            )
            linkedin_results.append({"success": success, "message": message, "type": "pdf"})
            logger.info(f"📄 LinkedIn PDF result: {success} - {message}")
        except Exception as e:
            logger.error(f"Failed to post PDF to LinkedIn: {str(e)}")
            linkedin_results.append({"success": False, "message": f"Error: {str(e)}", "type": "pdf"})
    else:
        # If no PDF available, try to find and post the latest PDF from S3
        logger.info("🔍 No PDF URL in response, searching for latest PDF in S3...")
        try:
            response_s3 = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix="pdfs/")
            pdf_keys = [obj['Key'] for obj in response_s3.get('Contents', []) if obj['Key'].endswith('.pdf')]
            
            if pdf_keys:
                # Get the most recent PDF
                sorted_pdfs = sorted(response_s3['Contents'], key=lambda x: x['LastModified'], reverse=True)
                latest_pdf_key = next((obj['Key'] for obj in sorted_pdfs if obj['Key'].endswith('.pdf')), None)
                
                if latest_pdf_key:
                    latest_pdf_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{latest_pdf_key}"
                    logger.info(f"📄 Found latest PDF in S3, posting to LinkedIn: {latest_pdf_url}")
                    
                    success, message = post_pdf_to_linkedin(
                        s3_pdf_url=latest_pdf_url,
                        caption=final_caption,
                        access_token=LINKEDIN_ACCESS_TOKEN,
                        org_urn=LINKEDIN_ORG_URN
                    )
                    linkedin_results.append({"success": success, "message": message, "type": "pdf_from_s3"})
                    logger.info(f"📄 LinkedIn PDF from S3 result: {success} - {message}")
                else:
                    logger.warning("⚠️ No PDF files found in S3 pdfs/ folder")
            else:
                logger.warning("⚠️ No PDF files found in S3 pdfs/ folder")
        except Exception as e:
            logger.error(f"Failed to search for PDF in S3: {str(e)}")
            linkedin_results.append({"success": False, "message": f"S3 PDF search error: {str(e)}", "type": "pdf_search_error"})

    if linkedin_results:
        response_data["linkedin_results"] = linkedin_results
        logger.info(f"✅ [LINKEDIN POST RESULTS] {linkedin_results}")
    else:
        logger.warning("⚠️ No LinkedIn posts were attempted")

    logger.info("🎉 All social media posting tasks completed!")

def run_scheduler():
    schedule.every().day.at("18:03").do(delete_yesterday_prompt)
    schedule.every().day.at("23:12").do(scheduler_task)
    logger.info("✅ Scheduler loop is running...")
    logger.info(f"🔗 Using LinkedIn Organization URN: {LINKEDIN_ORG_URN}")
    logger.info("📱 Platforms enabled: Instagram, Twitter, LinkedIn")
    while True:
        schedule.run_pending()
        time.sleep(60)

# Task schedule for daily social media posts
logger.info("Creating Task Schedule for daily social media posts:")
task_schedule = {
    "name": "Daily Social Media Post",
    "prompt": "Generate and post images to Instagram, Twitter, and LinkedIn based on trending topics in India related to Data Science and Machine Learning.",
    "cadence": "daily",
    "time_of_day": "18:05",#18:05, 23:16
    "platforms": ["Instagram", "Twitter", "LinkedIn"],
    "day_of_week": 1,
    "day_of_month": 1,
    "day_of_year": 1
}

if __name__ == "__main__":
    run_scheduler()