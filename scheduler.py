# scheduler.py  — safe mode (non-blocking, queue-friendly)

import os
import json
import time
import logging
from datetime import datetime
from typing import List, Dict, Any

import boto3
import schedule
from dotenv import load_dotenv

# ────────────────────────────────────────────────────────────────────────────────
# Logging
# ────────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("scheduler")

# ────────────────────────────────────────────────────────────────────────────────
# Env & AWS clients (safe-mode, won’t crash if table missing)
# ────────────────────────────────────────────────────────────────────────────────
load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
DYNAMODB_SURVEY_TABLE = os.getenv("DYNAMODB_SURVEY_TABLE", "UserSurveyData")

try:
    session = boto3.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=AWS_REGION,
    )
    dynamodb = session.resource("dynamodb")
    dynamo_client = session.client("dynamodb")
    survey_tbl = dynamodb.Table(DYNAMODB_SURVEY_TABLE)

    # Confirm table exists (but don’t crash import if it doesn’t)
    dynamo_client.describe_table(TableName=DYNAMODB_SURVEY_TABLE)
    logger.info(f"Scheduler using table: {DYNAMODB_SURVEY_TABLE} (region={AWS_REGION})")
except Exception as e:
    logger.error(f"[Scheduler] DynamoDB not ready ({DYNAMODB_SURVEY_TABLE}): {e}")
    survey_tbl = None

# ────────────────────────────────────────────────────────────────────────────────
# Optional downstream modules (wrapped to avoid import errors)
# ────────────────────────────────────────────────────────────────────────────────
try:
    # Your normal content generator
    from content_handler import ContentGenerator
except Exception:
    # Fallback shim so this file runs even if content_handler changes
    class ContentGenerator:
        def generate(self, ctx: Dict[str, Any]):
            logger.info("[Scheduler] ContentGenerator shim used; returning empty result.")
            return {"image_urls": []}

# Social posting imports kept optional; skip if they’re not available
try:
    from social_media.instagram_post import post_carousel_to_instagram
except Exception:
    def post_carousel_to_instagram(*args, **kwargs):
        logger.info("[Scheduler] Instagram post skipped (module not available).")
        return {"status": "skipped"}

try:
    from social_media.linkedin_post import post_pdf_to_linkedin
except Exception:
    def post_pdf_to_linkedin(*args, **kwargs):
        logger.info("[Scheduler] LinkedIn PDF post skipped (module not available).")
        return {"status": "skipped"}

try:
    from social_media.twitter_post import post_content_to_twitter
except Exception:
    def post_content_to_twitter(*args, **kwargs):
        logger.info("[Scheduler] Twitter post skipped (module not available).")
        return {"status": "skipped"}


class DynamicScheduler:
    def __init__(self):
        self.active_schedules: Dict[str, Any] = {}
        # Lightweight topic bank so we don’t need Selenium/ChatGPT right now
        self.business_trending_topics = {
            "Technology": [
                "AI advancements", "Machine Learning trends", "Cloud computing",
                "Cybersecurity", "Blockchain", "IoT innovations",
                "5G technology", "Software development", "Tech startups",
                "Digital transformation",
            ],
            "Healthcare": [
                "Telemedicine", "Health tech", "Medical innovations",
                "Wellness trends", "Digital health", "Healthcare analytics",
                "Medical devices", "Patient care", "Health awareness",
                "Medical research",
            ],
            "Finance": [
                "Fintech", "Digital banking", "Investment trends", "Cryptocurrency",
                "Financial literacy", "Market analysis", "Insurance tech",
                "Payment solutions", "Economic trends", "Financial planning",
            ],
            "Education": [
                "EdTech", "Online learning", "Digital education", "Educational tools",
                "Student engagement", "Learning analytics", "Virtual classrooms",
                "Educational content", "Skills development", "Academic trends",
            ],
            "Retail": [
                "E-commerce", "Retail technology", "Customer experience",
                "Online shopping", "Retail analytics", "Supply chain",
                "Digital marketing", "Consumer trends", "Retail innovation",
                "Sales strategies",
            ],
            "Real Estate": [
                "PropTech", "Real estate trends", "Property investment", "Smart homes",
                "Real estate analytics", "Market insights", "Property management",
                "Urban development", "Housing market", "Real estate technology",
            ],
            "Manufacturing": [
                "Industry 4.0", "Smart manufacturing", "Automation",
                "Supply chain optimization", "Manufacturing tech",
                "Production efficiency", "Quality control", "Industrial IoT",
                "Lean manufacturing", "Sustainable manufacturing",
            ],
            "Entertainment": [
                "Streaming technology", "Content creation", "Digital entertainment",
                "Gaming industry", "Media trends", "Creative technology",
                "Entertainment platforms", "Virtual events", "Content marketing",
                "Digital media",
            ],
        }

    # ───────────────────────────────────────────────────────────────────
    # Data fetch (SAFE)
    # ───────────────────────────────────────────────────────────────────
    def fetch_user_preferences(self) -> List[Dict[str, Any]]:
        """Fetch all user preferences from DynamoDB (safe-mode)."""
        if survey_tbl is None:
            logger.warning("UserSurveyData table not available; skipping schedules.")
            return []

        try:
            resp = survey_tbl.scan()
            items = resp.get("Items", [])
            users: List[Dict[str, Any]] = []

            for item in items:
                try:
                    answers = item.get("answers", "{}")
                    if isinstance(answers, str):
                        # Try JSON first, then ast as fallback
                        try:
                            answers = json.loads(answers.replace("'", '"'))
                        except Exception:
                            import ast as _ast
                            try:
                                answers = _ast.literal_eval(answers)
                            except Exception:
                                answers = {}

                    users.append(
                        {
                            "userId": item.get("userId"),
                            "business_type": item.get("business_type", "Technology"),
                            "schedule_time": answers.get("schedule_time", "18:00"),
                            "content_preferences": answers.get("content_preferences", ""),
                            "platforms": answers.get("platforms", ["instagram", "linkedin"]),
                            "num_images": answers.get("num_images", 2),
                            "content_type": answers.get("content_type", "Informative"),
                            "timezone": answers.get("timezone", "Asia/Kolkata"),
                        }
                    )
                except Exception as e:
                    logger.error(f"Processing user {item.get('userId', '?')} failed: {e}")

            logger.info(f"Fetched {len(users)} user preferences")
            return users

        except Exception as e:
            logger.error(f"Error fetching user preferences: {e}")
            return []

    # ───────────────────────────────────────────────────────────────────
    # Topic utilities (no Selenium/ChatGPT right now)
    # ───────────────────────────────────────────────────────────────────
    def get_trending_topics_for_business(self, business_type: str) -> List[str]:
        base = self.business_trending_topics.get(
            business_type, self.business_trending_topics["Technology"]
        )
        current = [
            f"Latest {business_type.lower()} innovations",
            f"{business_type} market trends 2025",
            f"Future of {business_type.lower()}",
            f"{business_type} digital transformation",
            f"Emerging {business_type.lower()} technologies",
        ]
        return base + current

    def fetch_trending_from_chatgpt(self, business_type: str) -> str:
        """Disabled for now to keep scheduler lightweight."""
        return ""  # returning empty will force fallback topics

    def choose_best_topic(self, response: str, business_type: str) -> str:
        if not response.strip():
            return self.get_trending_topics_for_business(business_type)[0]
        # If you re-enable ChatGPT in future, add parsing/scoring logic here.
        return response.strip().splitlines()[0]

    def generate_molded_prompt(
        self, selected_topic: str, business_type: str, content_preferences: str
    ) -> str:
        base = (
            f"Create an engaging, industry-relevant post about '{selected_topic}' "
            f"for the {business_type} sector. "
        )
        if content_preferences:
            base += f"Emphasize {content_preferences}. "
        base += "Provide actionable insights and clear value."
        return base

    # ───────────────────────────────────────────────────────────────────
    # Execution (kept simple; all external calls are try/except)
    # ───────────────────────────────────────────────────────────────────
    def execute_user_schedule(self, user_cfg: Dict[str, Any]) -> None:
        try:
            user_id = user_cfg.get("userId")
            biz = user_cfg.get("business_type", "Technology")

            logger.info(f"Running schedule for {user_id} ({biz})")

            trending = self.fetch_trending_from_chatgpt(biz)
            topic = self.choose_best_topic(trending, biz)
            prompt = self.generate_molded_prompt(
                topic, biz, user_cfg.get("content_preferences", "")
            )
            logger.info(f"[{user_id}] Prompt: {prompt}")

            # Generate content via your existing pipeline
            gen = ContentGenerator()
            request_body = {
                "prompt": prompt,
                "contentType": user_cfg.get("content_type", "Informative"),
                "numImages": user_cfg.get("num_images", 2),
                "platforms": {
                    "instagram": "instagram" in user_cfg.get("platforms", []),
                    "linkedin": "linkedin" in user_cfg.get("platforms", []),
                    "twitter": "twitter" in user_cfg.get("platforms", []),
                },
            }

            result = gen.generate({"request": {"body": json.dumps(request_body)}})
            data = result[0] if isinstance(result, tuple) else result
            image_urls = data.get("image_urls", []) or []
            logger.info(f"[{user_id}] Images generated: {len(image_urls)}")

            # Optional posting — fully guarded
            caption = prompt
            if "instagram" in user_cfg.get("platforms", []) and image_urls:
                try:
                    post_carousel_to_instagram(image_urls, caption)
                except Exception as e:
                    logger.error(f"[{user_id}] Instagram post failed: {e}")

            if "linkedin" in user_cfg.get("platforms", []):
                # Safe-mode: skip PDF creation & posting to avoid extra deps
                logger.info(f"[{user_id}] LinkedIn posting skipped in safe-mode.")

            if "twitter" in user_cfg.get("platforms", []) and image_urls:
                try:
                    post_content_to_twitter(image_urls[0], caption)
                except Exception as e:
                    logger.error(f"[{user_id}] Twitter post failed: {e}")

            logger.info(f"[{user_id}] Schedule completed.")

        except Exception as e:
            logger.error(f"execute_user_schedule error: {e}")

    # ───────────────────────────────────────────────────────────────────
    # Scheduling
    # ───────────────────────────────────────────────────────────────────
    def setup_dynamic_schedules(self) -> None:
        users = self.fetch_user_preferences()
        schedule.clear()

        if not users:
            logger.info("No users found; no schedules set.")
            return

        for user in users:
            try:
                t = user.get("schedule_time", "18:00")
                hh, mm = map(int, t.split(":"))
                when = f"{hh:02d}:{mm:02d}"

                def make_task(cfg):
                    return lambda: self.execute_user_schedule(cfg)

                schedule.every().day.at(when).do(make_task(user))
                logger.info(
                    f"Scheduled user={user.get('userId')} at {when} ({user.get('timezone','')})"
                )
            except Exception as e:
                logger.error(
                    f"Failed to schedule user={user.get('userId','?')} : {e}"
                )

        logger.info(f"Setup {len(users)} dynamic schedules")

    def run_scheduler(self) -> None:
        logger.info("Starting Dynamic Business Scheduler")
        self.setup_dynamic_schedules()

        # Refresh schedules every hour to pick up new/changed users
        schedule.every().hour.do(self.setup_dynamic_schedules)

        logger.info("Dynamic scheduler is running...")
        while True:
            schedule.run_pending()
            time.sleep(60)


# Standalone runner (optional)
if __name__ == "__main__":
    DynamicScheduler().run_scheduler()
