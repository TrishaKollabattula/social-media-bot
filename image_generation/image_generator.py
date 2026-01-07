from __future__ import annotations

import os
import re
import time
import uuid
import base64
import logging
import tempfile
import threading
from io import BytesIO
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import json
from image_generation.business_visual_profiles import BUSINESS_VISUAL_PROFILES, ANTI_AI_UNIVERSAL_RULES
from image_generation.image_templates import TEMPLATE_VISUAL_SPECS

import requests
from PIL import Image

import boto3
from boto3.dynamodb.conditions import Key

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    WebDriverException,
    TimeoutException,
    StaleElementReferenceException,
)

from dotenv import load_dotenv

# Import from utils
try:
    from .utils import content_type_styles, get_content_details
except ImportError:
    content_type_styles = {
        "Informative": {
            "layouts": ["grid with icons", "flowchart", "annotated diagram"],
            "palette": "dark background with yellow highlights, white text",
            "font": "clean sans-serif font",
            "theme_adjustment": "Include meaningful explanatory visuals",
            "action": "Create an infographic-style image that explains"
        },
        "Inspirational": {
            "layouts": ["centered text with background image", "quote with border"],
            "palette": "black background with yellow text",
            "font": "bold decorative font",
            "theme_adjustment": "Use imagery that uplifts and aligns with the theme",
            "action": "Create an inspirational image about"
        },
        "Educational": {
            "layouts": ["step-by-step guide", "mind map"],
            "palette": "dark mode with yellow bullet points",
            "font": "educational readable font",
            "theme_adjustment": "Use educational icons and explanation cues",
            "action": "Create an educational image for"
        },
        "Promotional": {
            "layouts": ["product spotlight", "call-to-action banner"],
            "palette": "black background with yellow CTA, white content",
            "font": "bold marketing font",
            "theme_adjustment": "Showcase the theme with branding elements",
            "action": "Create a promotional image that promotes"
        }
    }

load_dotenv()
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
CHROME_PROFILE_PATH1 = os.getenv("CHROME_PROFILE_PATH1")
CHROME_PROFILE_PATH2 = os.getenv("CHROME_PROFILE_PATH2")
FALLBACK_LOGO_PATH = "logo.png"

if not CHROME_PROFILE_PATH1:
    raise ValueError("CHROME_PROFILE_PATH1 environment variable not set.")
if not AWS_REGION or not S3_BUCKET_NAME:
    raise ValueError("AWS_REGION or S3_BUCKET_NAME environment variable not set.")

s3 = boto3.client("s3", region_name=AWS_REGION)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
user_survey_table = dynamodb.Table("UserSurveyData")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# UI Selectors - More comprehensive
COMPOSER_SELECTORS = [
    "//textarea[@id='prompt-textarea']",
    "//div[@id='prompt-textarea']",
    "//textarea[contains(@placeholder,'Message')]",
    "//div[@contenteditable='true' and @role='textbox']",
    "//div[contains(@class,'ProseMirror')][@contenteditable='true']",
]
SEND_BUTTON_SELECTORS = [
    "//button[@data-testid='send-button']",
    "//button[@data-testid='fruitjuice-send-button']",
    "//button[@aria-label='Send message']",
    "//button[@aria-label='Send prompt']",
    "//button[contains(@class,'send')]",
    "//button[contains(text(),'Send')]",
    "//button[contains(@class, 'absolute') and contains(@class, 'bottom')]//span[contains(., 'Send')]/..",
    "//form//button[@type='button']",
    "//button[.//svg]",
]
MESSAGE_BLOCK_SELECTORS = [
    "//div[@data-message-author-role='assistant']",
    "//div[@data-message-author-role='user']",
    "//article",
    "//div[contains(@class,'message')]",
]

def _dismiss_overlays(driver):
    """Dismiss any overlays, modals, or popups that might block interaction"""
    try:
        overlay_selectors = [
            "//button[@aria-label='Close']",
            "//button[contains(text(), 'Dismiss')]",
            "//button[contains(text(), 'Got it')]",
            "//button[contains(text(), 'OK')]",
            "//div[@role='dialog']//button",
        ]
        
        for selector in overlay_selectors:
            try:
                buttons = driver.find_elements(By.XPATH, selector)
                for btn in buttons:
                    if btn.is_displayed():
                        btn.click()
                        logging.info(f"   ✓ Dismissed overlay/modal")
                        time.sleep(0.5)
                        return True
            except:
                continue
    except Exception as e:
        logging.debug(f"Overlay dismiss check: {e}")
    return False

def _find_any(driver, xpaths, timeout=10):
    """Find first present element"""
    for xp in xpaths:
        try:
            elem = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xp))
            )
            return elem
        except Exception:
            continue
    raise TimeoutException(f"None of selectors found: {xpaths[:2]}...")

def _find_clickable(driver, xpaths, timeout=10):
    """Find first clickable element"""
    for xp in xpaths:
        try:
            elem = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, xp))
            )
            return elem
        except Exception:
            continue
    raise TimeoutException(f"None clickable: {xpaths[:2]}...")

def _count_messages(driver):
    total = 0
    for xp in MESSAGE_BLOCK_SELECTORS:
        try:
            total += len(driver.find_elements(By.XPATH, xp))
        except:
            pass
    return total

DEFAULT_SUBTOPICS = [
    {"title": "Hands-on Projects", "details": "Build a portfolio with Python, ML, DL and cloud deployment."},
    {"title": "Mentors 8+ yrs", "details": "Learn from industry experts with real-world experience."},
    {"title": "Curriculum Overview", "details": "AI, ML, DL, MLOps, prompt engineering, agents."},
]

def expand_subtopics(theme: str, n: int, given: List[Dict[str, str]]) -> List[Dict[str, str]]:
    out = list(given or [])
    seen = {(s.get("title","").lower(), s.get("details","").lower()) for s in out}
    i = 0
    while len(out) < n:
        cand = DEFAULT_SUBTOPICS[i % len(DEFAULT_SUBTOPICS)]
        key = (cand["title"].lower(), cand["details"].lower())
        if key not in seen:
            out.append(cand)
            seen.add(key)
        i += 1
    return out[:n]

class ChromeProfileManager:
    _lock = threading.Lock()
    _profile_locks = {CHROME_PROFILE_PATH1: threading.Lock()}
    _profile_status = {CHROME_PROFILE_PATH1: False}
    
    if CHROME_PROFILE_PATH2:
        _profile_locks[CHROME_PROFILE_PATH2] = threading.Lock()
        _profile_status[CHROME_PROFILE_PATH2] = False

    @classmethod
    def acquire_profile(cls):
        with cls._lock:
            if not cls._profile_status[CHROME_PROFILE_PATH1]:
                if cls._profile_locks[CHROME_PROFILE_PATH1].acquire(blocking=False):
                    cls._profile_status[CHROME_PROFILE_PATH1] = True
                    logging.info("🔓 Acquired Chrome Profile 1")
                    return CHROME_PROFILE_PATH1, cls._profile_locks[CHROME_PROFILE_PATH1]
            if CHROME_PROFILE_PATH2 and not cls._profile_status.get(CHROME_PROFILE_PATH2, True):
                if cls._profile_locks[CHROME_PROFILE_PATH2].acquire(blocking=False):
                    cls._profile_status[CHROME_PROFILE_PATH2] = True
                    logging.info("🔓 Acquired Chrome Profile 2")
                    return CHROME_PROFILE_PATH2, cls._profile_locks[CHROME_PROFILE_PATH2]
            logging.warning("⚠️ All Chrome profiles busy")
            return None, None

    @classmethod
    def release_profile(cls, profile_path, lock_object):
        with cls._lock:
            if profile_path in cls._profile_status:
                cls._profile_status[profile_path] = False
                lock_object.release()
                logging.info("🔒 Released Chrome Profile")


class ImageGenerator:
    """Ultra-robust image generator with enhanced feedback loop"""
    
    def __init__(self):
        self.max_iterations = int(os.getenv("IMG_MAX_ITERS", "6"))
        self.score_threshold = int(os.getenv("IMG_SCORE_THRESHOLD", "9"))
        self.max_retries = int(os.getenv("IMG_MAX_RETRIES", "3"))
        
        self.image_sizes = ["1080x1350", "1080x1080"]
        self.current_batch_size: Optional[str] = None
        
        self.user_logo_path: Optional[str] = None
        self.chrome_profile_path: Optional[str] = None
        self.profile_lock: Optional[threading.Lock] = None
        
        self.accumulated_feedback: List[str] = []
        self.last_pdf_url: Optional[str] = None
        
        # Optimized timing
        self.GENERATION_TIMEOUT = 300  # 5 minutes per attempt
        self.POLL_INTERVAL = 1.0  # Check every 1 second
        self.POST_GENERATION_WAIT = 3  # Wait 3s after detecting image
        self.PRE_FEEDBACK_WAIT = 5  # Wait 5s before sending feedback
        self.FEEDBACK_RESPONSE_WAIT = 30  # Wait 30s for feedback response
        self.PROGRESS_LOG_INTERVAL = 10  # Log progress every 10 seconds
        self.IMAGE_TIMEOUT = 12 * 60  # 12 minutes max per image
        self.ITERATION_CLEANUP_DELAY = 2  # Wait 2s between iterations
        
        # Track which submission method works
        self.preferred_submit_method: Optional[str] = None
        
        # Circuit breaker configuration
        self.max_consecutive_failures = 2
        self.max_feedback_failures = 3

    def parse_dynamodb_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        parsed = {}
        for k, v in item.items():
            if isinstance(v, dict):
                if "S" in v: parsed[k] = v["S"]
                elif "N" in v:
                    try: parsed[k] = float(v["N"])
                    except Exception: parsed[k] = v["N"]
                elif "BOOL" in v: parsed[k] = v["BOOL"]
                elif "M" in v: parsed[k] = self.parse_dynamodb_item(v["M"])
                elif "L" in v: parsed[k] = [self.parse_dynamodb_item({"v": i})["v"] for i in v["L"]]
            else:
                parsed[k] = v
        return parsed

    def get_user_survey_data(self, user_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not user_id:
            logging.warning("⚠️ No user_id provided for survey data")
            return None
        try:
            resp = user_survey_table.query(
                KeyConditionExpression=Key("userId").eq(user_id),
                ScanIndexForward=False,
                Limit=1,
            )
            if resp.get("Items"):
                parsed = self.parse_dynamodb_item(resp["Items"][0])
                answers = parsed.get("answers") if isinstance(parsed.get("answers"), dict) else {}
                answers["business_type"] = parsed.get("business_type", answers.get("business_type", "general"))
                
                logging.info(f"✅ Survey data loaded: {answers.get('business_type', 'unknown')}")
                
                has_logo = parsed.get("has_logo", False)
                if isinstance(has_logo, str): has_logo = has_logo.lower() == "true"
                logo_url = parsed.get("logo_s3_url")
                if has_logo and logo_url and str(logo_url).startswith("http"):
                    self.user_logo_path = self._download_logo(logo_url, user_id) or (FALLBACK_LOGO_PATH if os.path.exists(FALLBACK_LOGO_PATH) else None)
                elif os.path.exists(FALLBACK_LOGO_PATH):
                    self.user_logo_path = FALLBACK_LOGO_PATH
                return answers
            else:
                logging.warning("⚠️ No survey data found for user")
        except Exception as e:
            logging.warning(f"⚠️ Survey fetch failed: {e}")
        return None

    def _download_logo(self, url: str, user_id: str) -> Optional[str]:
        try:
            r = requests.get(url, timeout=20)
            if r.status_code != 200: return None
            img = Image.open(BytesIO(r.content)).convert("RGBA")
            fn = f"user_logo_{user_id}_{uuid.uuid4().hex[:8]}.png"
            img.save(fn, "PNG")
            return fn if os.path.exists(fn) else None
        except Exception:
            return None

    def build_personalized_context(self, survey: Optional[Dict[str, Any]], theme="") -> Tuple[str, Dict[str, Any], str]:
        if not survey:
            logging.warning("⚠️ No survey data - using defaults")
            return "", {}, "general"
        visual_prefs: Dict[str, Any] = {}
        business_type = survey.get("business_type", "general")
        
        colors = survey.get("brand_colors") or survey.get("colors")
        if colors:
            if isinstance(colors, list): visual_prefs["colors"] = colors
            else: visual_prefs["colors"] = [str(colors)]
        
        logging.info(f"📊 Personalization: type={business_type}, colors={visual_prefs.get('colors', 'none')}")
        
        return "", visual_prefs, str(business_type)

    def get_size_for_image(self, idx: int, n: int) -> str:
        if self.current_batch_size is None or idx == 1:
            self.current_batch_size = self.image_sizes[((idx - 1)//3) % len(self.image_sizes)]
        return self.current_batch_size

    def load_content_details(self, content_path="content_details.json") -> Optional[Dict]:
        """Load content generation template data"""
        try:
            if not os.path.exists(content_path):
                logging.warning(f"⚠️ Content details not found: {content_path}")
                return None
            with open(content_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logging.info(f"✅ Loaded content details:")
            logging.info(f"   Template: {data.get('template_used', 'unknown')}")
            logging.info(f"   Slides: {len(data.get('slide_contents', {}))}")
            return {
                "template_id": data.get("template_used"),
                "template_name": data.get("template_name"),
                "slides": data.get("slide_contents", {}),
                "theme": data.get("theme"),
                "content_type": data.get("content_type")
            }
        except Exception as e:
            logging.error(f"❌ Failed to load content details: {e}")
            return None

    def check_browser_health(self, driver) -> bool:
        """Verify browser is still responsive and on ChatGPT"""
        try:
            state = driver.execute_script("return document.readyState")
            if state != "complete":
                logging.warning("⚠️ Page not fully loaded")
            
            current_url = driver.current_url
            if "chatgpt.com" not in current_url:
                logging.error(f"❌ Browser navigated away: {current_url}")
                return False
            
            return True
        except Exception as e:
            logging.error(f"❌ Browser not responsive: {e}")
            return False

    def clean_browser_state(self, driver) -> bool:
        """Ensure browser is in clean state for next iteration"""
        try:
            logging.info("   🧹 Cleaning browser state...")
            
            _dismiss_overlays(driver)
            
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            except:
                pass
            
            time.sleep(self.ITERATION_CLEANUP_DELAY)
            
            logging.info("   ✅ Browser state cleaned")
            return True
            
        except Exception as e:
            logging.warning(f"   ⚠️ State cleaning failed: {e}")
            return False

    def generate_initial_prompt(self, subtopic: Dict[str,str], template_spec: Dict, business_profile: Dict, slide_structure_type: str, idx: int, theme: str, visual_prefs: Dict[str,Any]) -> str:
        """Generate intelligent, business-specific, anti-AI prompt with PROPER FORMATTING"""
        
        logging.info(f"\n{'─'*80}")
        logging.info(f"🎨 GENERATING PROMPT FOR SLIDE #{idx}")
        logging.info(f"{'─'*80}")
        
        spec = template_spec
        profile = business_profile
        size = self.get_size_for_image(idx, 1)
        
        photo_vs_illustration = spec.get("photography_vs_illustration", {})
        approach = photo_vs_illustration.get(profile.get("business_type", "default"), "mixed_50_50")
        
        prompt_lines = [
            f"Generate a {size} Instagram carousel image for slide #{idx}.",
            "",
            "=" * 60,
            "BUSINESS CONTEXT:",
            "=" * 60,
            f"Industry: {profile.get('business_type', 'general')}",
            f"Visual Approach: {profile.get('visual_approach', 'professional quality')}",
            f"Tone: {profile.get('tone', 'professional')}",
            "",
            "=" * 60,
            "CONTENT:",
            "=" * 60,
            f"Template: {spec.get('composition', 'visual layout')}",
            f"Slide Type: {slide_structure_type}",
            f"Theme: {theme}",
            f"Title: {subtopic.get('title', 'content')}",
            f"Details: {subtopic.get('details', '')}",
            "",
        ]
        
        prompt_lines.append("=" * 60)
        if "photo_100" in approach or "dslr_required" in profile.get('visual_approach', ''):
            prompt_lines.extend([
                "PHOTOGRAPHY REQUIREMENTS (MANDATORY):",
                "=" * 60,
                f"• DSLR Quality: {profile.get('photography_style', 'professional camera quality')}",
                f"• Real Camera Characteristics: natural bokeh, lens imperfections",
                f"• Authentic Lighting: {', '.join(ANTI_AI_UNIVERSAL_RULES['photography_authenticity'][:3])}",
                f"• Real Textures: show material authenticity",
                f"• Natural Imperfections: slight asymmetry, environmental context",
                "",
            ])
        elif "illustration" in approach:
            prompt_lines.extend([
                "ILLUSTRATION REQUIREMENTS:",
                "=" * 60,
                f"• Style: {profile.get('illustration_style', 'hand-crafted quality')}",
                f"• Hand-crafted Feel: {', '.join(ANTI_AI_UNIVERSAL_RULES['illustration_authenticity'][:3])}",
                f"• Organic Elements: line weight variation, natural shapes",
                f"• Texture: add paper grain or brush strokes",
                "",
            ])
        else:
            prompt_lines.extend([
                "MIXED APPROACH:",
                "=" * 60,
                f"• Photography Elements: {profile.get('photography_style', 'DSLR quality')}",
                f"• Illustration Elements: {profile.get('illustration_style', 'hand-crafted style')}",
                f"• Blend naturally with depth layering",
                "",
            ])
        
        visual_elements = spec.get('visual_elements', {}).get(
            profile.get('business_type', 'default'),
            spec.get('visual_elements', {}).get('default', ['text overlay', 'clean background', 'focal point'])
        )
        
        prompt_lines.extend([
            "=" * 60,
            "COMPOSITION:",
            "=" * 60,
            f"• Layout: {spec.get('layout_priority', 'balanced visual hierarchy')}",
            f"• Required Elements: {', '.join(visual_elements)}",
            f"• Text Placement: {spec.get('text_placement', 'clear readable positioning')}",
            f"• Overall Feel: {profile.get('composition', 'professional and engaging')}",
            "",
        ])
        
        colors = visual_prefs.get("colors", [])
        if colors:
            prompt_lines.extend([
                "=" * 60,
                "BRAND COLORS:",
                "=" * 60,
                f"• Primary Colors: {', '.join(colors)}",
                f"• Usage: {spec.get('color_usage', 'accent strategic placement')}",
                "",
            ])
        
        visual_hint = subtopic.get('visual_hint', '')
        if visual_hint:
            prompt_lines.extend([
                "=" * 60,
                "CONTENT TEAM GUIDANCE:",
                "=" * 60,
                visual_hint,
                "",
            ])
        
        anti_ai_tactics = spec.get('anti_ai_emphasis', [])
        profile_anti_ai = profile.get('anti_ai_tactics', [])
        
        prompt_lines.extend([
            "=" * 60,
            "ANTI-AI-AESTHETIC REQUIREMENTS (CRITICAL):",
            "=" * 60,
        ])
        
        for tactic in anti_ai_tactics[:3]:
            prompt_lines.append(f"• {tactic}")
        for tactic in profile_anti_ai[:2]:
            prompt_lines.append(f"• {tactic}")
        
        prompt_lines.extend([
            f"• {ANTI_AI_UNIVERSAL_RULES['always_include'][0]}",
            f"• AVOID: {', '.join(ANTI_AI_UNIVERSAL_RULES['always_avoid'][:3])}",
            "",
        ])
        
        prompt_lines.extend([
            "=" * 60,
            "QUALITY STANDARDS:",
            "=" * 60,
            "• Must NOT look AI-generated",
            f"• Professional {profile.get('visual_approach', 'quality')} quality",
            f"• Industry-appropriate: {profile.get('tone', 'professional')} tone",
            "• Natural imperfections that prove authenticity",
            "• Target: 9+/10 on overall quality AND business fit",
            "",
        ])
        
        avoid_list = profile.get('avoid', [])
        if avoid_list:
            prompt_lines.extend([
                "=" * 60,
                "STRICTLY AVOID:",
                "=" * 60,
            ])
            for item in avoid_list:
                prompt_lines.append(f"• {item}")
            prompt_lines.append("")
        
        prefer_list = profile.get('prefer', [])
        if prefer_list:
            prompt_lines.extend([
                "=" * 60,
                "STRONGLY PREFER:",
                "=" * 60,
            ])
            for item in prefer_list:
                prompt_lines.append(f"• {item}")
            prompt_lines.append("")
        
        prompt = "\n".join(prompt_lines)
        
        line_count = prompt.count('\n') + 1
        logging.info(f"✅ PROMPT GENERATED: {len(prompt)} chars, {line_count} lines\n")
        
        return prompt

    def _is_generated_image_url(self, src: str) -> bool:
        """Helper to identify generated image URLs"""
        if not src:
            return False
        
        # ChatGPT backend API
        if "backend-api/estuary/content" in src or "backend-api%2Festuary%2Fcontent" in src:
            has_file_id = "id=file_" in src or "id%3Dfile_" in src
            has_signature = "sig=" in src or "sig%3D" in src or "&amp;sig=" in src
            return has_file_id and has_signature
        
        # Blob URLs
        if "blob:" in src:
            return True
        
        # Data URLs (substantial size)
        if src.startswith("data:image") and len(src) > 10000:
            return True
        
        # DALL-E URLs
        if "oaidalleapiprodscus" in src or "dalle" in src.lower():
            return True
        
        return False

    def wait_for_real_image(self, driver) -> Tuple[bool, Optional[str]]:
        """
        ENHANCED: Returns both success status AND image source URL
        """
        logging.info("⏳ Waiting for image generation...")
        
        time.sleep(1.5)
        
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
        except:
            pass
        
        start_time = time.time()
        last_log_time = start_time
        
        # Capture CURRENT state
        initial_img_srcs = set()
        initial_message_count = 0
        try:
            imgs = driver.find_elements(By.TAG_NAME, "img")
            for img in imgs:
                src = img.get_attribute("src")
                if src:
                    initial_img_srcs.add(src)
            initial_message_count = len(driver.find_elements(By.XPATH, "//div[@data-message-author-role='assistant']"))
            logging.info(f"   📊 Baseline: {len(initial_img_srcs)} images, {initial_message_count} messages")
        except Exception as e:
            logging.warning(f"   ⚠️ Could not capture baseline: {e}")
        
        # Quick check for instant images
        try:
            quick_check_imgs = driver.find_elements(By.TAG_NAME, "img")
            for img in quick_check_imgs:
                src = img.get_attribute("src")
                if src and self._is_generated_image_url(src) and src not in initial_img_srcs:
                    logging.info(f"   ⚡ Image already present! URL: {src[:120]}...")
                    time.sleep(self.POST_GENERATION_WAIT)
                    logging.info("✅ Image generation complete (instant)")
                    return True, src
        except Exception as e:
            logging.debug(f"Quick check error: {e}")
        
        check_count = 0
        last_detailed_log = start_time
        
        while time.time() - start_time < self.GENERATION_TIMEOUT:
            check_count += 1
            
            if time.time() - last_log_time >= self.PROGRESS_LOG_INTERVAL:
                elapsed = int(time.time() - start_time)
                logging.info(f"   ⏱️  Still waiting... ({elapsed}s elapsed, check #{check_count})")
                last_log_time = time.time()
            
            # Detailed IMG TAG inspection
            if time.time() - last_detailed_log >= 15:
                try:
                    all_imgs = driver.find_elements(By.TAG_NAME, "img")
                    new_imgs = []
                    chatgpt_imgs = []
                    
                    logging.info(f"   🔍 SCANNING {len(all_imgs)} <img> TAGS:")
                    
                    for idx, img in enumerate(all_imgs):
                        src = img.get_attribute("src")
                        alt = img.get_attribute("alt")
                        width = img.size.get('width', 0)
                        height = img.size.get('height', 0)
                        
                        if src and src not in initial_img_srcs:
                            new_imgs.append(src[:80])
                            
                            logging.info(f"      [{idx}] NEW IMG TAG:")
                            logging.info(f"          src: {src[:100]}")
                            logging.info(f"          alt: {alt}")
                            logging.info(f"          size: {width}x{height}")
                            
                            if "backend-api" in src or "chatgpt.com" in src:
                                chatgpt_imgs.append(src)
                    
                    if chatgpt_imgs:
                        logging.info(f"   🎯 Found {len(chatgpt_imgs)} ChatGPT API images")
                    else:
                        logging.info(f"   ℹ️  No ChatGPT API images detected yet...")
                        
                except Exception as e:
                    logging.debug(f"Detailed logging error: {e}")
                last_detailed_log = time.time()
            
            try:
                # Check for error messages
                messages = driver.find_elements(By.XPATH, "//div[@data-message-author-role='assistant']")
                current_message_count = len(messages)
                
                if current_message_count > initial_message_count:
                    latest_message = messages[-1]
                    latest_text = latest_message.text.lower()
                    
                    error_indicators = [
                        "i apologize", "i can't", "i'm unable", "error generating",
                        "something went wrong", "try again", "content policy"
                    ]
                    
                    if any(err in latest_text for err in error_indicators):
                        logging.error(f"❌ ChatGPT error detected: {latest_text[:150]}")
                        return False, None
                
                # SCAN ALL IMG TAGS
                imgs = driver.find_elements(By.TAG_NAME, "img")
                
                for img in imgs:
                    try:
                        src = img.get_attribute("src")
                        if not src or src in initial_img_srcs:
                            continue
                        
                        if self._is_generated_image_url(src):
                            logging.info(f"   ✅ Found generated image in <img> tag!")
                            logging.info(f"   🔗 URL: {src[:120]}...")
                            
                            width = img.size.get('width', 0)
                            height = img.size.get('height', 0)
                            
                            if width > 100 and height > 100:
                                logging.info(f"   📐 Size verified: {width}x{height}")
                                time.sleep(self.POST_GENERATION_WAIT)
                                
                                try:
                                    is_complete = driver.execute_script(
                                        "return arguments[0].complete && arguments[0].naturalHeight > 0", 
                                        img
                                    )
                                    if is_complete:
                                        logging.info("   ✅ Image fully rendered")
                                    else:
                                        logging.info("   ⚠️ Image still rendering (continuing anyway)")
                                except:
                                    pass
                                
                                logging.info("✅ Image generation complete")
                                return True, src
                        
                    except Exception as e:
                        logging.debug(f"   Error checking img: {e}")
                        continue
                
            except Exception as e:
                logging.debug(f"   ⚠️ Check error: {e}")
            
            time.sleep(self.POLL_INTERVAL)
        
        logging.error(f"❌ Image timeout after {int(time.time() - start_time)}s")
        return False, None

    def _extract_scores_from_feedback(self, feedback_text: str) -> Dict[str, float]:
        """Enhanced score extraction with multiple patterns"""
        scores = {}
        
        patterns = [
            (r"Overall.*?Quality.*?Score:?\s*(\d{1,2})\s*/\s*10", 'overall'),
            (r"Template.*?Fit.*?Score:?\s*(\d{1,2})\s*/\s*10", 'template'),
            (r"Business.*?(Fit|Appropriateness).*?Score:?\s*(\d{1,2})\s*/\s*10", 'business'),
            (r"Anti-AI.*?Score:?\s*(\d{1,2})\s*/\s*10", 'anti_ai'),
            (r"Composite.*?Score:?\s*(\d{1,2}(?:\.\d)?)\s*/\s*10", 'composite'),
        ]
        
        for pattern, key in patterns:
            match = re.search(pattern, feedback_text, re.IGNORECASE)
            if match:
                score_str = match.group(match.lastindex)
                try:
                    scores[key] = float(score_str)
                except ValueError:
                    pass
        
        if not scores.get('overall'):
            match = re.search(r"(?:^|\n).*?Overall.*?(\d{1,2})\s*/\s*10", feedback_text, re.IGNORECASE | re.MULTILINE)
            if match:
                scores['overall'] = int(match.group(1))
        
        if 'composite' not in scores and len(scores) >= 3:
            scores['composite'] = sum(scores.values()) / len(scores)
        
        return scores

    def _extract_improvements_from_feedback(self, feedback_text: str) -> List[str]:
        """Enhanced improvement extraction with better parsing"""
        improvements = []
        
        improvement_keywords = [
            "improve", "enhance", "fix", "adjust", "change", "add", "remove",
            "should", "need", "must", "consider", "try",
            "ai-generated", "fake", "unrealistic", "generic", "sterile",
            "template", "business", "missing", "wrong", "issue", "problem"
        ]
        
        lines = feedback_text.split("\n")
        
        in_improvement_section = False
        for line in lines:
            clean_line = line.strip()
            
            if any(header in clean_line.lower() for header in ["what's wrong", "how to fix", "improvements", "priority fixes", "issues", "problems", "detailed feedback"]):
                in_improvement_section = True
                continue
            
            if len(clean_line) < 20:
                continue
            
            if "/10" in clean_line:
                continue
            
            if any(keyword in clean_line.lower() for keyword in improvement_keywords) or in_improvement_section:
                clean = re.sub(r'^[\d\.\-\*\•\>\-]+\s*', '', clean_line)
                clean = clean.strip()
                
                if clean and len(clean) > 25:
                    clean = re.sub(r'\d+/10', '', clean)
                    improvements.append(clean)
            
            if clean_line.startswith("=") or clean_line.isupper():
                in_improvement_section = False
        
        seen = set()
        unique_improvements = []
        for imp in improvements:
            imp_lower = imp.lower()
            if imp_lower not in seen:
                seen.add(imp_lower)
                unique_improvements.append(imp)
        
        return unique_improvements[:10]

    def request_comprehensive_feedback(self, driver, template_spec: Dict, business_profile: Dict, slide_structure_type: str, attempt_number: int, image_src_url: Optional[str] = None) -> Tuple[Dict[str, int], List[str]]:
        """
        ENHANCED: Request feedback with EXPLICIT image reference
        """
        logging.info(f"🤔 Requesting comprehensive feedback (Attempt #{attempt_number})...")
        
        messages_before = len(driver.find_elements(By.XPATH, "//div[@data-message-author-role='assistant']"))
        logging.info(f"   📊 Messages before feedback: {messages_before}")
        
        time.sleep(self.PRE_FEEDBACK_WAIT)
        
        criteria = template_spec.get('feedback_criteria', [])
        criteria_text = "\n".join([f"   • {c}" for c in criteria])
        
        feedback_lines = [
            f"Look at the image you just generated above (attempt #{attempt_number}).",
            "",
        ]
        
        if image_src_url:
            feedback_lines.extend([
                "⚠️ IMPORTANT: Evaluate the MOST RECENT image in this conversation.",
                f"(The image source contains: {image_src_url[:50]}...)",
                "",
            ])
        else:
            feedback_lines.extend([
                "⚠️ IMPORTANT: Evaluate the MOST RECENT image you generated.",
                "Scroll up if needed to see it clearly.",
                "",
            ])
        
        feedback_lines.extend([
            "=" * 60,
            "CONTEXT:",
            "=" * 60,
            f"Business: {business_profile.get('business_type', 'general')}",
            f"Template: {template_spec.get('composition', 'visual layout')}",
            f"Slide Type: {slide_structure_type}",
            f"Attempt Number: {attempt_number}",
            "",
            "=" * 60,
            "YOUR TASK: EVALUATE ON 4 DIMENSIONS",
            "=" * 60,
            "",
            "Score each dimension from 1-10 where:",
            "• 1-3 = Poor/Unacceptable",
            "• 4-6 = Needs improvement",
            "• 7-8 = Good but not great",
            "• 9-10 = Excellent/Professional",
            "",
            "DIMENSION 1: OVERALL QUALITY (Technical Excellence)",
            "Score: __/10",
            "Criteria:",
            "   • Lighting quality (natural, well-balanced)",
            "   • Composition (rule of thirds, visual hierarchy)",
            "   • Resolution and sharpness",
            "   • Color grading (professional, not oversaturated)",
            "   • Professional polish",
            "",
            "DIMENSION 2: TEMPLATE FIT (Structural Accuracy)",
            "Score: __/10",
            "Criteria:",
            criteria_text if criteria_text else "   • Matches template layout requirements",
            f"   • Follows {template_spec.get('composition', 'composition')} guidelines",
            "   • Text placement is correct",
            "   • Visual elements are in right positions",
            "",
            "DIMENSION 3: BUSINESS APPROPRIATENESS (Industry Fit)",
            "Score: __/10",
            "Criteria:",
            f"   • Matches {business_profile.get('tone', 'professional')} tone?",
            f"   • Appropriate for {business_profile.get('business_type', 'industry')} industry?",
            f"   • Visual style fits {business_profile.get('visual_approach', 'brand')}?",
            "   • Colors and fonts match brand expectations?",
            "",
            "DIMENSION 4: ANTI-AI SUCCESS (Authenticity) ⚠️ CRITICAL",
            "Score: __/10",
            "Criteria:",
            "   • Does it look REAL, not AI-generated?",
            "   • Has natural imperfections (asymmetry, texture variation)?",
            "   • Lighting has realistic qualities (not perfect)?",
            "   • Textures look authentic (not plastic/CGI)?",
            "   • Environmental context feels genuine?",
            "   • AVOID: Perfect symmetry, sterile look, uncanny valley",
            "",
            "=" * 60,
            "REQUIRED OUTPUT FORMAT:",
            "=" * 60,
            "",
            "Overall Quality Score: X/10",
            "Template Fit Score: X/10",
            "Business Fit Score: X/10",
            "Anti-AI Score: X/10",
            "",
            "COMPOSITE SCORE: X.X/10 (average of all 4)",
            "",
            "=" * 60,
            "DETAILED FEEDBACK:",
            "=" * 60,
            "",
            "If ANY score is below 9, provide SPECIFIC, ACTIONABLE improvements:",
            "",
            "What's wrong:",
            "• [Be specific about the problem]",
            "",
            "How to fix it:",
            "• [Exact changes needed]",
            "",
            "Priority fixes (most important first):",
            "1. [First fix]",
            "2. [Second fix]",
            "3. [Third fix]",
            "",
            "Be brutally honest. Don't sugarcoat. We need 9+/10 on ALL dimensions.",
        ])
        
        feedback_prompt = "\n".join(feedback_lines)
        
        logging.info(f"\n{'─'*60}")
        logging.info(f"📤 SUBMITTING DETAILED FEEDBACK REQUEST")
        logging.info(f"   Prompt size: {len(feedback_prompt)} chars")
        logging.info(f"   Image URL included: {'Yes' if image_src_url else 'No'}")
        logging.info(f"{'─'*60}")
        
        if not self.submit_prompt_robust(driver, feedback_prompt, max_retries=self.max_retries, prompt_type="FEEDBACK REQUEST"):
            logging.error("❌ Failed to submit feedback request")
            return {}, []
        
        logging.info(f"✅ Feedback prompt submitted, waiting for response...")
        
        max_wait = self.FEEDBACK_RESPONSE_WAIT
        start = time.time()
        new_message_appeared = False
        
        while time.time() - start < max_wait:
            current_messages = len(driver.find_elements(By.XPATH, "//div[@data-message-author-role='assistant']"))
            if current_messages > messages_before:
                time.sleep(2)
                new_message_appeared = True
                logging.info(f"   ✅ Feedback response received (total messages: {current_messages})")
                break
            time.sleep(2)
        
        if not new_message_appeared:
            logging.error(f"❌ Feedback response timeout after {max_wait}s")
            return {}, []
        
        try:
            messages = driver.find_elements(By.XPATH, "//div[@data-message-author-role='assistant']")
            if not messages:
                logging.warning("⚠️ No feedback messages found")
                return {}, []
            
            feedback_text = messages[-1].text
            logging.info(f"   📄 Feedback received: {len(feedback_text)} chars")
            
            logging.info(f"\n{'─'*60}")
            logging.info(f"📝 FEEDBACK PREVIEW:")
            logging.info(feedback_text[:300] + "..." if len(feedback_text) > 300 else feedback_text)
            logging.info(f"{'─'*60}\n")
            
            error_indicators = ["I apologize", "I can't", "I'm unable", "error", "something went wrong"]
            if any(err in feedback_text.lower() for err in error_indicators):
                logging.warning(f"⚠️ Feedback contains error: {feedback_text[:200]}")
                return {}, []
            
            scores = self._extract_scores_from_feedback(feedback_text)
            improvements = self._extract_improvements_from_feedback(feedback_text)
            
            if scores:
                logging.info(f"\n{'─'*60}")
                logging.info(f"📊 EXTRACTED SCORES:")
                logging.info(f"{'─'*60}")
                for dimension, score in scores.items():
                    emoji = "✅" if score >= 9 else "⚠️" if score >= 7 else "❌"
                    logging.info(f"   {emoji} {dimension.capitalize()}: {score}/10")
                logging.info(f"{'─'*60}\n")
            else:
                logging.warning("⚠️ Could not extract scores from feedback")
            
            if improvements:
                logging.info(f"\n{'─'*60}")
                logging.info(f"📝 EXTRACTED IMPROVEMENTS ({len(improvements)} total):")
                logging.info(f"{'─'*60}")
                for i, imp in enumerate(improvements[:5], 1):
                    logging.info(f"   {i}. {imp[:100]}{'...' if len(imp) > 100 else ''}")
                if len(improvements) > 5:
                    logging.info(f"   ... and {len(improvements) - 5} more")
                logging.info(f"{'─'*60}\n")
            
            return scores, improvements
            
        except Exception as e:
            logging.error(f"❌ Error extracting feedback: {e}", exc_info=True)
            return {}, []

    def generate_improved_prompt(self, accumulated_feedback: List[str], scores_history: List[Dict], subtopic: Dict[str,str], template_spec: Dict, business_profile: Dict, slide_structure_type: str, theme: str, attempt: int) -> str:
        """
        ENHANCED: Generate improvement prompt with DETAILED analysis
        """
        
        if scores_history:
            last_scores = scores_history[-1]
            dimension_scores = {k: v for k, v in last_scores.items() if k != 'composite'}
            
            if dimension_scores:
                weakest_dim, weakest_score = min(dimension_scores.items(), key=lambda x: x[1])
            else:
                weakest_dim, weakest_score = "overall", 0
        else:
            weakest_dim, weakest_score = "overall", 0
        
        recent_feedback = accumulated_feedback[-8:]
        
        prompt_lines = [
            f"REGENERATE the image with improvements (Attempt #{attempt}):",
            "",
            "⚠️ CRITICAL: This is an ITERATIVE REFINEMENT.",
            "Build on the previous attempt - don't start from scratch.",
            "",
            "=" * 60,
            "PREVIOUS PERFORMANCE:",
            "=" * 60,
        ]
        
        if scores_history:
            for i, score_set in enumerate(scores_history[-3:], start=max(1, len(scores_history)-2)):
                composite = score_set.get('composite', 0)
                overall = score_set.get('overall', 0)
                template = score_set.get('template', 0)
                business = score_set.get('business', 0)
                anti_ai = score_set.get('anti_ai', 0)
                
                status = "✅" if composite >= 9 else "⚠️" if composite >= 7 else "❌"
                
                prompt_lines.append(
                    f"Attempt {i}: {status} Composite={composite:.1f}/10 "
                    f"(Quality={overall}, Template={template}, Business={business}, Anti-AI={anti_ai})"
                )
        
        prompt_lines.extend([
            "",
            "=" * 60,
            f"🎯 WEAKEST DIMENSION: {weakest_dim.upper().replace('_', '-')} ({weakest_score}/10)",
            "=" * 60,
            f"This is your PRIMARY FOCUS for this regeneration.",
            "",
        ])
        
        dimension_focus = {
            'overall': [
                "Improve lighting quality (more natural, less artificial)",
                "Enhance composition (better visual hierarchy, rule of thirds)",
                "Increase sharpness and resolution",
                "Better color grading (avoid oversaturation)",
            ],
            'template': [
                f"Follow {template_spec.get('composition', 'template')} layout more precisely",
                "Position text elements exactly as specified",
                "Include all required visual elements",
                f"Match {template_spec.get('layout_priority', 'layout')} structure",
            ],
            'business': [
                f"Better match {business_profile.get('tone', 'professional')} tone",
                f"More appropriate for {business_profile.get('business_type', 'industry')} industry",
                f"Use {business_profile.get('visual_approach', 'brand')} visual approach",
                "Align with brand expectations",
            ],
            'anti_ai': [
                "Add MORE natural imperfections (asymmetry, texture variation)",
                "Make lighting more realistic (not perfect studio lighting)",
                "Include environmental context and depth cues",
                "Show material authenticity (real textures, not CGI)",
                "Add subtle randomness and organic qualities",
            ],
        }
        
        focus_fixes = dimension_focus.get(weakest_dim, [])
        if focus_fixes:
            prompt_lines.extend([
                f"TO FIX {weakest_dim.upper()}:",
            ])
            for fix in focus_fixes:
                prompt_lines.append(f"   • {fix}")
            prompt_lines.append("")
        
        prompt_lines.extend([
            "=" * 60,
            "ALL FEEDBACK FROM PREVIOUS ATTEMPTS:",
            "=" * 60,
        ])
        
        if recent_feedback:
            for i, fb in enumerate(recent_feedback, 1):
                prompt_lines.append(f"{i}. {fb}")
        else:
            prompt_lines.append("(No specific feedback yet)")
        
        prompt_lines.extend([
            "",
            "=" * 60,
            "ORIGINAL CONTENT (DO NOT CHANGE):",
            "=" * 60,
            f"Business: {business_profile.get('business_type', 'general')}",
            f"Template: {template_spec.get('composition', 'layout')}",
            f"Slide Type: {slide_structure_type}",
            f"Theme: {theme}",
            f"Title: {subtopic.get('title', 'content')}",
            f"Details: {subtopic.get('details', '')}",
            "",
            "=" * 60,
            "YOUR TASK:",
            "=" * 60,
            f"1. Keep the same CONTENT and THEME",
            f"2. Apply ALL fixes above, especially for {weakest_dim.upper()}",
            f"3. Target: 9+/10 on ALL dimensions",
            f"4. Make it look REAL, professional, and industry-appropriate",
            "",
            "Focus on INCREMENTAL IMPROVEMENT, not radical redesign.",
            "Fix the specific issues identified in the feedback.",
        ])
        
        prompt = "\n".join(prompt_lines)
        
        logging.info(f"\n{'═'*80}")
        logging.info(f"✍️  IMPROVED PROMPT GENERATED:")
        logging.info(f"   Total size: {len(prompt)} chars, {prompt.count(chr(10)) + 1} lines")
        logging.info(f"   Primary focus: {weakest_dim.upper()} ({weakest_score}/10)")
        logging.info(f"   Feedback points: {len(recent_feedback)}")
        logging.info(f"{'═'*80}\n")
        
        return prompt

    def submit_prompt_robust(self, driver, prompt: str, max_retries: int = 3, prompt_type: str = "prompt") -> bool:
        """Submit prompt with proper multi-line formatting"""
        
        if not prompt or len(prompt) < 100:
            logging.error(f"❌ Prompt too short ({len(prompt)} chars)!")
            return False
        
        line_count = prompt.count('\n') + 1
        logging.info(f"📝 Submitting {prompt_type}: {len(prompt)} chars, {line_count} lines")
        
        for attempt in range(max_retries):
            try:
                logging.info(f"   🔄 Attempt {attempt + 1}/{max_retries}...")
                
                current_url = driver.current_url
                if "chatgpt.com" not in current_url:
                    logging.warning(f"⚠️ Not on ChatGPT! Redirecting...")
                    driver.get("https://chatgpt.com/chat")
                    time.sleep(8)
                
                _dismiss_overlays(driver)
                
                composer = _find_any(driver, COMPOSER_SELECTORS, timeout=10)
                
                try:
                    composer.clear()
                except:
                    composer.send_keys(Keys.CONTROL + "a")
                    composer.send_keys(Keys.DELETE)
                
                time.sleep(0.3)
                
                submission_successful = False
                try:
                    logging.info(f"      📋 Clipboard paste...")
                    
                    driver.execute_script("""
                        const text = arguments[0];
                        const element = arguments[1];
                        element.focus();
                        navigator.clipboard.writeText(text).then(() => {
                            const pasteEvent = new ClipboardEvent('paste', {
                                clipboardData: new DataTransfer(),
                                bubbles: true,
                                cancelable: true
                            });
                            pasteEvent.clipboardData.setData('text/plain', text);
                            element.dispatchEvent(pasteEvent);
                        });
                    """, prompt, composer)
                    
                    time.sleep(1.5)
                    
                    typed_value = composer.get_attribute("value") or composer.text or ""
                    
                    if len(typed_value) >= len(prompt) * 0.75:
                        logging.info(f"      ✅ Pasted {len(typed_value)} chars")
                        submission_successful = True
                    else:
                        raise Exception("Paste incomplete")
                        
                except Exception as e:
                    logging.warning(f"      ⚠️ Paste failed: {e}")
                
                if not submission_successful:
                    try:
                        logging.info(f"      ⌨️  Line-by-line typing...")
                        
                        composer.send_keys(Keys.CONTROL + "a")
                        composer.send_keys(Keys.DELETE)
                        time.sleep(0.2)
                        
                        lines = prompt.split('\n')
                        for line_idx, line in enumerate(lines):
                            if line:
                                composer.send_keys(line)
                            if line_idx < len(lines) - 1:
                                composer.send_keys(Keys.SHIFT, Keys.ENTER)
                                time.sleep(0.03)
                        
                        time.sleep(0.8)
                        submission_successful = True
                        
                    except Exception as e:
                        logging.warning(f"      ⚠️ Typing failed: {e}")
                
                if not submission_successful:
                    logging.error(f"   ❌ Typing failed")
                    continue
                
                time.sleep(0.5)
                submitted = False
                
                if self.preferred_submit_method == "enter":
                    try:
                        composer.send_keys(Keys.ENTER)
                        submitted = True
                    except:
                        pass
                
                if not submitted:
                    try:
                        send_btn = _find_clickable(driver, SEND_BUTTON_SELECTORS, timeout=6)
                        send_btn.click()
                        submitted = True
                        self.preferred_submit_method = "button"
                    except:
                        pass
                
                if not submitted:
                    try:
                        composer.send_keys(Keys.ENTER)
                        submitted = True
                        self.preferred_submit_method = "enter"
                    except:
                        pass
                
                if submitted:
                    logging.info("   ✅ Submitted!\n")
                    time.sleep(1.5)
                    return True
                    
            except Exception as e:
                logging.warning(f"   ⚠️ Error: {e}")
                time.sleep(1.5)
        
        logging.error("❌ All submit attempts failed")
        return False

    def download_image(self, driver, img_element=None) -> Optional[bytes]:
        """Download image - tries multiple methods"""
        try:
            if img_element is None:
                logging.info("   🔍 Finding the generated image...")
                
                imgs = driver.find_elements(By.TAG_NAME, "img")
                chatgpt_images = []
                chatgpt_images_maybe = []
                
                for img in imgs:
                    try:
                        src = img.get_attribute("src")
                        if src and ("backend-api/estuary/content" in src or "backend-api%2Festuary%2Fcontent" in src):
                            has_file_id = "id=file_" in src or "id%3Dfile_" in src
                            has_signature = "sig=" in src or "sig%3D" in src or "&amp;sig=" in src
                            
                            if has_file_id and has_signature:
                                try:
                                    is_complete = driver.execute_script(
                                        "return arguments[0].complete && arguments[0].naturalHeight > 0", 
                                        img
                                    )
                                    if is_complete:
                                        chatgpt_images.append(img)
                                    else:
                                        chatgpt_images_maybe.append(img)
                                except:
                                    chatgpt_images_maybe.append(img)
                    except:
                        continue
                
                all_candidates = chatgpt_images + chatgpt_images_maybe
                
                if all_candidates:
                    img_element = all_candidates[-1]
                    if img_element in chatgpt_images:
                        logging.info(f"   ✅ Found fully loaded ChatGPT API image ({len(all_candidates)} total)")
                    else:
                        logging.info(f"   ✅ Found ChatGPT API image (load state unverified, {len(all_candidates)} total)")
                else:
                    logging.info("   🔍 Fallback: Looking in assistant messages...")
                    assistant_messages = driver.find_elements(By.XPATH, "//div[@data-message-author-role='assistant']")
                    if not assistant_messages:
                        logging.error("   ❌ No assistant messages found AND no ChatGPT images found")
                        return None
                    
                    latest_message = assistant_messages[-1]
                    imgs = latest_message.find_elements(By.TAG_NAME, "img")
                    if not imgs:
                        logging.error("   ❌ No images in latest message")
                        return None
                    
                    img_element = max(imgs, key=lambda img: (img.size.get('width', 0) * img.size.get('height', 0)))
            
            src = img_element.get_attribute("src")
            if not src:
                logging.error("   ❌ Image has no src")
                return None
            
            logging.info(f"   📥 Downloading image from: {src[:100]}...")
            
            if "backend-api/estuary/content" in src or "chatgpt.com" in src:
                logging.info(f"   🔄 Using ChatGPT API fetch...")
                try:
                    script = """
                        return new Promise((resolve, reject) => {
                            fetch(arguments[0], {
                                credentials: 'include',
                                headers: {
                                    'Accept': 'image/*'
                                }
                            })
                            .then(r => r.blob())
                            .then(blob => {
                                const reader = new FileReader();
                                reader.onloadend = () => resolve(reader.result);
                                reader.onerror = reject;
                                reader.readAsDataURL(blob);
                            })
                            .catch(reject);
                        });
                    """
                    data_url = driver.execute_async_script(script, src)
                    
                    if data_url and data_url.startswith("data:"):
                        base64_data = data_url.split(",", 1)[1]
                        content = base64.b64decode(base64_data)
                        logging.info(f"   ✅ Downloaded {len(content)/1024:.1f} KB via ChatGPT API")
                        return content
                except Exception as e:
                    logging.warning(f"   ⚠️ ChatGPT API fetch failed: {e}")
            
            if "blob:" in src:
                script = """
                    return new Promise((resolve, reject) => {
                        fetch(arguments[0])
                            .then(r => r.blob())
                            .then(blob => {
                                const reader = new FileReader();
                                reader.onloadend = () => resolve(reader.result);
                                reader.onerror = reject;
                                reader.readAsDataURL(blob);
                            })
                            .catch(reject);
                    });
                """
                data_url = driver.execute_async_script(script, src)
                
                if data_url and data_url.startswith("data:"):
                    base64_data = data_url.split(",", 1)[1]
                    return base64.b64decode(base64_data)
            
            elif src.startswith("data:image"):
                base64_data = src.split(",", 1)[1]
                return base64.b64decode(base64_data)
            
            elif src.startswith("http"):
                response = requests.get(src, timeout=30)
                if response.status_code == 200:
                    return response.content
            
            logging.error(f"   ❌ Could not download from URL type: {src[:50]}")
            return None
            
        except Exception as e:
            logging.error(f"❌ Download failed: {e}")
            return None

    def add_logo_to_image(self, image_bytes: bytes) -> bytes:
        """Add logo overlay to image"""
        try:
            if not self.user_logo_path:
                return image_bytes
            
            img = Image.open(BytesIO(image_bytes)).convert("RGBA")
            logo = Image.open(self.user_logo_path).convert("RGBA")
            
            logo_width = int(img.width * 0.1)
            logo_height = int(logo.height * (logo_width / logo.width))
            logo = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
            
            padding = 20
            position = (img.width - logo_width - padding, img.height - logo_height - padding)
            
            img.paste(logo, position, logo)
            
            output = BytesIO()
            img.convert("RGB").save(output, format="PNG")
            return output.getvalue()
            
        except Exception as e:
            logging.warning(f"⚠️ Logo overlay failed: {e}")
            return image_bytes

    def create_pdf_from_s3_images(self, image_urls: List[str]) -> Optional[str]:
        """Create PDF from S3 images"""
        try:
            logging.info("📄 Creating PDF...")
            
            images = []
            for url in image_urls:
                resp = requests.get(url, timeout=30)
                if resp.status_code == 200:
                    images.append(Image.open(BytesIO(resp.content)))
            
            if not images:
                return None
            
            pdf_filename = f"carousel_{uuid.uuid4().hex[:8]}.pdf"
            pdf_path = f"/tmp/{pdf_filename}"
            
            rgb_images = []
            for img in images:
                if img.mode == "RGBA":
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    bg.paste(img, mask=img.split()[3])
                    rgb_images.append(bg)
                else:
                    rgb_images.append(img.convert("RGB"))
            
            if rgb_images:
                rgb_images[0].save(
                    pdf_path,
                    save_all=True,
                    append_images=rgb_images[1:],
                    resolution=100.0,
                    quality=95,
                    optimize=True
                )
            
            s3_key = f"pdfs/{pdf_filename}"
            with open(pdf_path, "rb") as f:
                s3.upload_fileobj(f, S3_BUCKET_NAME, s3_key, 
                                ExtraArgs={"ContentType": "application/pdf"})
            
            pdf_url = f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
            logging.info(f"✅ PDF: {pdf_url}")
            
            os.unlink(pdf_path)
            return pdf_url
            
        except Exception as e:
            logging.error(f"❌ PDF failed: {e}")
            return None

    def log_generation_metrics(self, template_id: str, business_type: str, metrics: List[Dict]):
        """Log comprehensive metrics"""
        total_slides = len(metrics)
        total_attempts = sum(m['attempts'] for m in metrics)
        avg_attempts = total_attempts / total_slides if total_slides else 0
        avg_composite = sum(m['final_composite'] for m in metrics) / total_slides if total_slides else 0
        
        logging.info(f"\n{'='*80}")
        logging.info(f"📊 GENERATION METRICS")
        logging.info(f"{'='*80}")
        logging.info(f"Template: {template_id}")
        logging.info(f"Business: {business_type}")
        logging.info(f"Total slides: {total_slides}")
        logging.info(f"Avg attempts: {avg_attempts:.1f}")
        logging.info(f"Avg composite: {avg_composite:.2f}/10")
        logging.info(f"{'='*80}\n")

    def generate_images(self, theme: str, content_type: str, num_images: int, subtopics: List[Dict[str,str]], user_id: Optional[str] = None, meme_mode: bool = False, create_pdf: bool = False, creative_overlay_level: int = 1) -> List[str]:
        """
        MAIN METHOD: Generate images with enhanced feedback loop
        """
        
        logging.info(f"\n{'='*80}")
        logging.info(f"🚀 STARTING IMAGE GENERATION")
        logging.info(f"{'='*80}")
        logging.info(f"Theme: {theme}")
        logging.info(f"Images: {num_images}")
        logging.info(f"{'='*80}\n")
        
        self.chrome_profile_path, self.profile_lock = ChromeProfileManager.acquire_profile()
        if not self.chrome_profile_path:
            logging.error("❌ No Chrome profile")
            return []
        
        image_urls: List[str] = []
        driver = None
        
        try:
            content_details = self.load_content_details()
            
            if content_details:
                template_id = content_details.get("template_id", "listicle")
                content_type_from_details = content_details.get("content_type", content_type)
                
                if not template_id or template_id == "listicle":
                    content_type_to_template = {
                        "Informative": "how_to",
                        "Educational": "tutorial",
                        "Inspirational": "motivational",
                        "Promotional": "product_showcase",
                        "Story": "story_arc",
                        "Tips": "tips_tricks",
                        "Comparison": "comparison",
                        "Tutorial": "tutorial",
                        "Case Study": "case_study",
                    }
                    
                    inferred_template = content_type_to_template.get(
                        content_type_from_details, 
                        content_type_to_template.get(content_type, "listicle")
                    )
                    
                    if inferred_template != "listicle":
                        logging.info(f"   📋 Inferred template '{inferred_template}' from content type '{content_type_from_details}'")
                        template_id = inferred_template
                    else:
                        logging.info(f"   📋 Using default template 'listicle'")
                else:
                    logging.info(f"   📋 Using specified template '{template_id}'")
            else:
                content_type_to_template = {
                    "Informative": "how_to",
                    "Educational": "tutorial", 
                    "Inspirational": "motivational",
                    "Promotional": "product_showcase",
                }
                template_id = content_type_to_template.get(content_type, "listicle")
                logging.info(f"   📋 No content details, inferred template '{template_id}' from type '{content_type}'")
            
            template_spec = TEMPLATE_VISUAL_SPECS.get(template_id, TEMPLATE_VISUAL_SPECS.get("listicle", {}))
            
            logging.info(f"✅ Template: {template_id}")
            logging.info(f"✅ Content Type: {content_type}")
            logging.info(f"✅ Visual Spec: {template_spec.get('composition', 'default')}")
            
            survey = self.get_user_survey_data(user_id)
            user_context, visual_prefs, business_type = self.build_personalized_context(survey, theme)
            
            business_profile = BUSINESS_VISUAL_PROFILES.get(business_type)
            if not business_profile:
                business_profile = BUSINESS_VISUAL_PROFILES.get("technology_saas", {})
            if not business_profile.get("business_type"):
                business_profile["business_type"] = business_type
            
            slides = content_details.get("slides", {}) if content_details else {}
            subtopics = expand_subtopics(theme, num_images, subtopics or [])
            
            try:
                from webdriver_manager.chrome import ChromeDriverManager
                from selenium.webdriver.chrome.service import Service
                options = Options()
                options.add_argument(f"user-data-dir={self.chrome_profile_path}")
                options.add_argument("--disable-blink-features=AutomationControlled")
                options.add_experimental_option("excludeSwitches", ["enable-automation"])
                options.add_argument("--start-maximized")
                driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            except WebDriverException as e:
                logging.error(f"❌ ChromeDriver failed: {e}")
                return []
            
            driver.get("https://chatgpt.com/chat")
            
            logging.info("⏳ Waiting for ChatGPT...")
            try:
                WebDriverWait(driver, 60).until(lambda d: _find_any(d, COMPOSER_SELECTORS, timeout=5))
                logging.info("   ✓ Composer found")
            except:
                logging.error("❌ Composer not found")
                return []
            
            time.sleep(3)
            logging.info("✅ ChatGPT ready\n")
            
            all_metrics = []
            
            # GENERATE EACH IMAGE
            for idx, sub in enumerate(subtopics[:num_images], start=1):
                slide_key = f"slide_{idx}"
                slide_data = slides.get(slide_key, {})
                slide_structure_type = slide_data.get("structure_type", "general")
                if slide_data.get("visual_hint"):
                    sub["visual_hint"] = slide_data["visual_hint"]
                
                logging.info(f"\n{'='*80}")
                logging.info(f"🎨 IMAGE {idx}/{num_images}: {sub.get('title','')}")
                logging.info(f"{'='*80}")
                
                image_start_time = time.time()
                
                attempts = 0
                self.accumulated_feedback = []
                scores_history = []
                
                consecutive_failures = 0
                feedback_failures = 0
                
                current_prompt = self.generate_initial_prompt(
                    sub, template_spec, business_profile, slide_structure_type, 
                    idx, theme, visual_prefs
                )
                
                if len(current_prompt) < 500:
                    logging.error(f"❌ Prompt too short!")
                    continue
                
                best = {
                    "composite_score": 0,
                    "scores": {},
                    "image": None,
                    "filename": f"images/{business_type}_{template_id}_{idx}_{uuid.uuid4().hex}.png"
                }
                
                # ITERATION LOOP
                while attempts < self.max_iterations and best["composite_score"] < self.score_threshold:
                    if time.time() - image_start_time > self.IMAGE_TIMEOUT:
                        logging.error(f"❌ Image #{idx} timeout ({self.IMAGE_TIMEOUT/60:.1f}min), using best result")
                        break
                    
                    if not self.check_browser_health(driver):
                        logging.error("❌ Browser unhealthy, aborting slide")
                        break
                    
                    attempts += 1
                    logging.info(f"\n{'─'*80}")
                    logging.info(f"🔄 ATTEMPT {attempts}/{self.max_iterations}")
                    logging.info(f"{'─'*80}")
                    
                    # STEP 1: Submit prompt
                    logging.info(f"📤 STEP 1: Submitting IMAGE GENERATION prompt...")
                    if not self.submit_prompt_robust(driver, current_prompt, max_retries=self.max_retries, prompt_type="IMAGE GENERATION"):
                        logging.error("❌ Submit failed")
                        consecutive_failures += 1
                        if consecutive_failures >= self.max_consecutive_failures:
                            logging.error(f"❌ {consecutive_failures} consecutive submit failures, aborting")
                            break
                        continue
                    
                    # STEP 2: Wait for image (RETURNS URL NOW)
                    logging.info(f"⏳ STEP 2: Waiting for image to be generated...")
                    image_detected, image_src_url = self.wait_for_real_image(driver)
                    
                    if not image_detected:
                        logging.warning(f"⚠️ Image generation failed/timeout")
                        consecutive_failures += 1
                        if consecutive_failures >= self.max_consecutive_failures:
                            logging.error(f"❌ {consecutive_failures} consecutive image failures, aborting")
                            break
                        continue
                    
                    time.sleep(2)
                    
                    # STEP 3: Download
                    logging.info(f"💾 STEP 3: Downloading image...")
                    content = self.download_image(driver)
                    
                    if not content:
                        logging.warning("   ⚠️ First download attempt failed, waiting 3s and retrying...")
                        time.sleep(3)
                        content = self.download_image(driver)
                    
                    if not content:
                        logging.warning("⚠️ Download failed")
                        consecutive_failures += 1
                        if consecutive_failures >= self.max_consecutive_failures:
                            logging.error(f"❌ {consecutive_failures} consecutive download failures, aborting")
                            break
                        continue
                    
                    consecutive_failures = 0
                    logging.info(f"✅ Downloaded {len(content)/1024:.1f} KB")
                    
                    # STEP 4: Request feedback (WITH IMAGE URL)
                    logging.info(f"\n{'─'*40}")
                    logging.info(f"📊 STEP 4: Requesting DETAILED FEEDBACK...")
                    logging.info(f"{'─'*40}")
                    
                    scores, improvements = self.request_comprehensive_feedback(
                        driver, template_spec, business_profile, slide_structure_type, 
                        attempts, image_src_url  # ✅ Pass image URL
                    )
                    
                    if not scores:
                        feedback_failures += 1
                        logging.warning(f"⚠️ Feedback failure #{feedback_failures}")
                        if feedback_failures >= self.max_feedback_failures:
                            logging.error(f"❌ {feedback_failures} feedback failures, using best result")
                            break
                        scores = {"composite": 6, "overall": 6, "template": 6, "business": 6, "anti_ai": 6}
                    else:
                        feedback_failures = 0
                        logging.info(f"✅ FEEDBACK RECEIVED!")
                    
                    composite = scores.get("composite", sum(v for k,v in scores.items() if k != "composite") / max(len(scores)-1, 1))
                    scores["composite"] = composite
                    scores_history.append(scores)
                    
                    logging.info(f"📊 COMPOSITE: {composite:.1f}/10")
                    
                    if composite > best["composite_score"]:
                        best.update({
                            "composite_score": composite,
                            "scores": scores,
                            "image": content
                        })
                        logging.info(f"🎯 New best: {composite:.1f}/10")
                    
                    all_pass = all(v >= 9 for k, v in scores.items() if k != "composite")
                    if composite >= self.score_threshold and all_pass:
                        logging.info(f"🎉 THRESHOLD MET! Score: {composite:.1f}/10")
                        break
                    
                    if improvements:
                        self.accumulated_feedback.extend(improvements)
                        logging.info(f"📝 Added {len(improvements)} improvement points")
                    
                    # PREPARE FOR NEXT ITERATION
                    if attempts < self.max_iterations and composite < self.score_threshold:
                        logging.info(f"\n{'═'*80}")
                        logging.info(f"🔄 PREPARING FOR ATTEMPT {attempts + 1}/{self.max_iterations}")
                        logging.info(f"{'═'*80}")
                        
                        self.clean_browser_state(driver)
                        
                        logging.info(f"✍️  Generating IMPROVED prompt...")
                        current_prompt = self.generate_improved_prompt(
                            self.accumulated_feedback, scores_history, sub, 
                            template_spec, business_profile, slide_structure_type,
                            theme, attempts + 1
                        )
                        logging.info(f"✅ Improved prompt ready ({len(current_prompt)} chars)\n")
                    else:
                        if composite >= self.score_threshold:
                            logging.info(f"✅ Score threshold reached")
                        else:
                            logging.info(f"✅ Max iterations reached")
                
                # Upload best
                if best["image"]:
                    logging.info(f"\n📤 Uploading...")
                    logging.info(f"   Score: {best['composite_score']:.1f}/10")
                    logging.info(f"   Attempts: {attempts}")
                    
                    final_bytes = self.add_logo_to_image(best["image"])
                    buf = BytesIO(final_bytes)
                    s3.upload_fileobj(buf, S3_BUCKET_NAME, best["filename"], 
                                    ExtraArgs={"ContentType":"image/png"})
                    url = f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{best['filename']}"
                    image_urls.append(url)
                    
                    all_metrics.append({
                        "slide": idx,
                        "attempts": attempts,
                        "final_composite": best["composite_score"],
                        "final_scores": best["scores"]
                    })
                    
                    logging.info(f"✅ {url}")
                else:
                    logging.warning(f"⚠️ No image for slide {idx}")
            
            if all_metrics:
                self.log_generation_metrics(template_id, business_type, all_metrics)
            
            if create_pdf and image_urls:
                self.last_pdf_url = self.create_pdf_from_s3_images(image_urls)
            
            logging.info(f"\n{'='*80}")
            logging.info(f"✅ COMPLETE! {len(image_urls)} images")
            logging.info(f"{'='*80}\n")
            
            return image_urls
            
        except Exception as e:
            logging.error(f"❌ Error: {e}", exc_info=True)
            return []
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            if self.user_logo_path and self.user_logo_path != FALLBACK_LOGO_PATH:
                try:
                    os.unlink(self.user_logo_path)
                except:
                    pass
            if self.chrome_profile_path and self.profile_lock:
                ChromeProfileManager.release_profile(self.chrome_profile_path, self.profile_lock)