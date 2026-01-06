

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
    """Ultra-robust image generator with aggressive feedback retry and circuit breakers"""
    
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
        
        # ✅ OPTIMIZED TIMING - Faster but still reliable
        self.GENERATION_TIMEOUT = 300  # 5 minutes per attempt (was 10)
        self.POLL_INTERVAL = 1.0  # Check every 1 second for faster detection (was 2)
        self.POST_GENERATION_WAIT = 3  # Wait 3s after detecting image (was 5)
        self.PRE_FEEDBACK_WAIT = 5  # Wait 5s before sending feedback (was 8)
        self.FEEDBACK_RESPONSE_WAIT = 30  # Wait 30s for feedback response (was 20)
        self.PROGRESS_LOG_INTERVAL = 10  # Log progress every 10 seconds (was 15)
        self.IMAGE_TIMEOUT = 12 * 60  # 12 minutes max per image
        self.ITERATION_CLEANUP_DELAY = 2  # Wait 2s between iterations to ensure clean state
        
        # Track which submission method works
        self.preferred_submit_method: Optional[str] = None
        
        # ✅ Circuit breaker configuration
        self.max_consecutive_failures = 2  # Max failures before aborting slide
        self.max_feedback_failures = 3  # Max feedback failures before aborting

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

    # ✅ NEW: Browser health check
    def check_browser_health(self, driver) -> bool:
        """Verify browser is still responsive and on ChatGPT"""
        try:
            # Try to execute simple JS
            state = driver.execute_script("return document.readyState")
            if state != "complete":
                logging.warning("⚠️ Page not fully loaded")
            
            # Check if still on ChatGPT
            current_url = driver.current_url
            if "chatgpt.com" not in current_url:
                logging.error(f"❌ Browser navigated away: {current_url}")
                return False
            
            return True
        except Exception as e:
            logging.error(f"❌ Browser not responsive: {e}")
            return False

    # ✅ NEW: Clean browser state between iterations
    def clean_browser_state(self, driver) -> bool:
        """Ensure browser is in clean state for next iteration"""
        try:
            logging.info("   🧹 Cleaning browser state...")
            
            # Dismiss any popups/overlays
            _dismiss_overlays(driver)
            
            # Scroll to bottom to ensure we're at latest messages
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            except:
                pass
            
            # Small delay to let UI settle
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
        
        # Get approach
        photo_vs_illustration = spec.get("photography_vs_illustration", {})
        approach = photo_vs_illustration.get(profile.get("business_type", "default"), "mixed_50_50")
        
        # Build prompt with proper formatting
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
        
        # Add photography/illustration requirements
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
        
        # Visual elements
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
        
        # Brand colors
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
        
        # Visual hint
        visual_hint = subtopic.get('visual_hint', '')
        if visual_hint:
            prompt_lines.extend([
                "=" * 60,
                "CONTENT TEAM GUIDANCE:",
                "=" * 60,
                visual_hint,
                "",
            ])
        
        # Anti-AI tactics
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
        
        # Quality standards
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
        
        # Avoid/prefer lists
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

    # ✅ FIXED: Validates new message appeared
    def request_comprehensive_feedback(self, driver, template_spec: Dict, business_profile: Dict, slide_structure_type: str, attempt_number: int) -> Tuple[Dict[str, int], List[str]]:
        """Request multi-dimensional feedback with business context - VALIDATES response"""
        logging.info(f"🤔 Requesting comprehensive feedback (Attempt #{attempt_number})...")
        
        # ✅ Count messages BEFORE requesting feedback
        messages_before = len(driver.find_elements(By.XPATH, "//div[@data-message-author-role='assistant']"))
        logging.info(f"   📊 Messages before feedback: {messages_before}")
        
        time.sleep(self.PRE_FEEDBACK_WAIT)
        
        criteria = template_spec.get('feedback_criteria', [])
        criteria_text = "\n".join([f"   • {c}" for c in criteria])
        
        # Build feedback prompt
        feedback_lines = [
            f"Evaluate the image you just generated. This is attempt #{attempt_number}.",
            "",
            "=" * 60,
            "CONTEXT:",
            "=" * 60,
            f"Business: {business_profile.get('business_type', 'general')}",
            f"Template: {template_spec.get('composition', 'visual layout')}",
            f"Slide Type: {slide_structure_type}",
            "",
            "=" * 60,
            "EVALUATE ON 4 DIMENSIONS (score each 1-10):",
            "=" * 60,
            "",
            "1. OVERALL QUALITY Score: X/10",
            "   • Technical excellence (lighting, composition, resolution)",
            "   • Professional polish",
            "",
            "2. TEMPLATE FIT Score: X/10",
            criteria_text if criteria_text else "   • Matches template requirements",
            "",
            "3. BUSINESS APPROPRIATENESS Score: X/10",
            f"   • Matches {business_profile.get('tone', 'professional')} tone?",
            f"   • Fits {business_profile.get('business_type', 'industry')} industry?",
            "",
            "4. ANTI-AI SUCCESS Score: X/10 (CRITICAL)",
            "   • Does it look REAL, not AI-generated?",
            "   • Natural imperfections that prove authenticity?",
            "",
            "=" * 60,
            "FORMAT YOUR RESPONSE:",
            "=" * 60,
            "Overall Quality Score: X/10",
            "Template Fit Score: X/10",
            "Business Fit Score: X/10",
            "Anti-AI Score: X/10",
            "",
            "COMPOSITE SCORE: (average of all 4) X/10",
            "",
            "If ANY score is below 9, provide SPECIFIC improvements:",
            "• What exactly needs to change?",
            "• How to reach 9+ on all dimensions?",
            "",
            "Be brutally honest and specific."
        ]
        
        feedback_prompt = "\n".join(feedback_lines)
        
        logging.info(f"\n{'─'*60}")
        logging.info(f"📤 SUBMITTING FEEDBACK REQUEST PROMPT ({len(feedback_prompt)} chars)")
        logging.info(f"{'─'*60}")
        
        if not self.submit_prompt_robust(driver, feedback_prompt, max_retries=self.max_retries, prompt_type="FEEDBACK REQUEST"):
            logging.error("❌ Failed to submit feedback request")
            return {}, []
        
        logging.info(f"✅ Feedback prompt submitted, waiting for response...")
        
        # ✅ Wait for NEW message with timeout
        max_wait = self.FEEDBACK_RESPONSE_WAIT
        start = time.time()
        new_message_appeared = False
        
        while time.time() - start < max_wait:
            current_messages = len(driver.find_elements(By.XPATH, "//div[@data-message-author-role='assistant']"))
            if current_messages > messages_before:
                time.sleep(2)  # Let it fully render
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
            
            feedback_text = "\n".join([m.text for m in messages[-2:] if m.text])
            logging.info(f"   📄 Feedback received: {len(feedback_text)} chars")
            
            # ✅ Check for error indicators
            error_indicators = ["I apologize", "I can't", "I'm unable", "error", "something went wrong"]
            if any(err in feedback_text.lower() for err in error_indicators):
                logging.warning(f"⚠️ Feedback contains error: {feedback_text[:200]}")
                return {}, []
            
            scores = {}
            match = re.search(r"Overall.*?Quality.*?Score:?\s*(\d{1,2})\s*/\s*10", feedback_text, re.IGNORECASE)
            if match:
                scores['overall'] = int(match.group(1))
            match = re.search(r"Template.*?Fit.*?Score:?\s*(\d{1,2})\s*/\s*10", feedback_text, re.IGNORECASE)
            if match:
                scores['template'] = int(match.group(1))
            match = re.search(r"Business.*?(Fit|Appropriateness).*?Score:?\s*(\d{1,2})\s*/\s*10", feedback_text, re.IGNORECASE)
            if match:
                scores['business'] = int(match.group(2))
            match = re.search(r"Anti-AI.*?Score:?\s*(\d{1,2})\s*/\s*10", feedback_text, re.IGNORECASE)
            if match:
                scores['anti_ai'] = int(match.group(1))
            match = re.search(r"Composite.*?Score:?\s*(\d{1,2}(?:\.\d)?)\s*/\s*10", feedback_text, re.IGNORECASE)
            if match:
                scores['composite'] = float(match.group(1))
            
            if 'composite' not in scores and len(scores) >= 3:
                scores['composite'] = sum(scores.values()) / len(scores)
            
            if scores:
                logging.info(f"📊 SCORES:")
                for dimension, score in scores.items():
                    logging.info(f"   {dimension.capitalize()}: {score}/10")
            else:
                logging.warning("⚠️ Could not extract scores")
            
            improvements = []
            keywords = [
                "improve", "enhance", "fix", "adjust", "change", "add", "remove",
                "ai-generated", "fake", "unrealistic", "generic",
                "template", "business", "missing",
            ]
            
            for line in feedback_text.split("\n"):
                clean_line = line.strip()
                if any(k in clean_line.lower() for k in keywords):
                    clean = re.sub(r'^[\d\.\-\*\•\-\>]+\s*', '', clean_line)
                    if clean and len(clean) > 25:
                        improvements.append(clean)
            
            if not improvements and scores.get('composite', 0) < 9:
                if scores.get('overall', 10) < 9:
                    improvements.append("Improve overall technical quality and polish")
                if scores.get('template', 10) < 9:
                    improvements.append(f"Better match template requirements")
                if scores.get('business', 10) < 9:
                    improvements.append(f"Make more appropriate for {business_profile.get('business_type', 'business')} industry")
                if scores.get('anti_ai', 10) < 9:
                    improvements.append("Add natural imperfections - real textures, asymmetry")
            
            logging.info(f"✅ Extracted {len(improvements)} improvements")
            for imp in improvements[:3]:
                logging.info(f"   • {imp[:80]}...")
            
            return scores, improvements
            
        except Exception as e:
            logging.error(f"❌ Error extracting feedback: {e}")
            return {}, []

    def generate_improved_prompt(self, accumulated_feedback: List[str], scores_history: List[Dict], subtopic: Dict[str,str], template_spec: Dict, business_profile: Dict, slide_structure_type: str, theme: str, attempt: int) -> str:
        """Generate improvement prompt with proper formatting"""
        
        if scores_history:
            last_scores = scores_history[-1]
            weakest_dim = min(last_scores.items(), key=lambda x: x[1] if x[0] != 'composite' else 10)
            weakest_name, weakest_score = weakest_dim
        else:
            weakest_name, weakest_score = "overall", 0
        
        recent_feedback = "\n".join([f"• {fb}" for fb in accumulated_feedback[-5:]])
        
        prompt_lines = [
            f"REGENERATE with improvements (Attempt #{attempt}):",
            "",
            "=" * 60,
            "PREVIOUS SCORES:",
            "=" * 60,
        ]
        
        if scores_history:
            for i, score_set in enumerate(scores_history[-2:], start=max(1, len(scores_history)-1)):
                score_line = f"Attempt {i}: Composite={score_set.get('composite', 0):.1f}/10"
                prompt_lines.append(score_line)
        
        prompt_lines.extend([
            "",
            "=" * 60,
            f"WEAKEST: {weakest_name.upper()} ({weakest_score}/10)",
            "=" * 60,
            "",
            "=" * 60,
            "CRITICAL FIXES:",
            "=" * 60,
            recent_feedback,
            "",
            "=" * 60,
            "CONTEXT:",
            "=" * 60,
            f"Business: {business_profile.get('business_type', 'general')}",
            f"Template: {template_spec.get('composition', 'layout')}",
            f"Theme: {theme}",
            f"Content: {subtopic.get('title', 'slide')}",
            "",
            "=" * 60,
            "REQUIREMENTS:",
            "=" * 60,
            "APPLY ALL FIXES ABOVE.",
            f"TARGET: 9+/10 on ALL dimensions, especially {weakest_name.upper()}.",
            "Make it look REAL, professional, industry-appropriate.",
        ])
        
        prompt = "\n".join(prompt_lines)
        logging.info(f"✅ Improvement prompt: {len(prompt)} chars, {prompt.count(chr(10)) + 1} lines")
        
        return prompt

    def submit_prompt_robust(self, driver, prompt: str, max_retries: int = 3, prompt_type: str = "prompt") -> bool:
        """Submit prompt with proper multi-line formatting - OPTIMIZED"""
        
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
                
                # Try clipboard paste first (best for formatting)
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
                
                # Fallback: line-by-line typing
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
                
                # Submit
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

    # ✅ FIXED: Better detection + clean state capture
    def wait_for_real_image(self, driver) -> bool:
        """
        ULTRA-ROBUST image detection with FRESH state capture each call
        """
        logging.info("⏳ Waiting for image generation...")
        
        # ✅ Small delay to let previous operations complete
        time.sleep(1.5)
        
        # ✅ Scroll to bottom to ensure we see latest content
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
        except:
            pass
        
        start_time = time.time()
        last_log_time = start_time
        
        # ✅ Capture CURRENT state RIGHT NOW (not stale from previous iteration)
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
        
        # ✅ Do one immediate check in case image loaded super fast
        try:
            quick_check_imgs = driver.find_elements(By.TAG_NAME, "img")
            for img in quick_check_imgs:
                src = img.get_attribute("src")
                if src and "backend-api/estuary/content" in src and src not in initial_img_srcs:
                    if ("id=file_" in src or "id%3Dfile_" in src) and ("sig=" in src or "sig%3D" in src):
                        logging.info(f"   ⚡ Image already present! URL: {src[:120]}...")
                        time.sleep(self.POST_GENERATION_WAIT)
                        logging.info("✅ Image generation complete (instant)")
                        return True
        except Exception as e:
            logging.debug(f"Quick check error: {e}")
        
        check_count = 0
        last_detailed_log = start_time
        
        while time.time() - start_time < self.GENERATION_TIMEOUT:
            check_count += 1
            
            # Progress logging
            if time.time() - last_log_time >= self.PROGRESS_LOG_INTERVAL:
                elapsed = int(time.time() - start_time)
                logging.info(f"   ⏱️  Still waiting... ({elapsed}s elapsed, check #{check_count})")
                last_log_time = time.time()
            
            # Detailed logging every 15 seconds (more frequent for debugging)
            if time.time() - last_detailed_log >= 15:
                try:
                    all_imgs = driver.find_elements(By.TAG_NAME, "img")
                    new_imgs = []
                    chatgpt_imgs = []
                    
                    for img in all_imgs:
                        src = img.get_attribute("src")
                        if src and src not in initial_img_srcs:
                            new_imgs.append(src[:80])
                            if "backend-api" in src or "chatgpt.com" in src:
                                chatgpt_imgs.append(src)
                    
                    if new_imgs:
                        logging.info(f"   🔍 New images detected ({len(new_imgs)}):")
                        for src in new_imgs[:5]:
                            logging.info(f"      • {src}...")
                    
                    if chatgpt_imgs:
                        logging.info(f"   🎯 ChatGPT API images found: {len(chatgpt_imgs)}")
                        for src in chatgpt_imgs:
                            has_file = "id=file_" in src or "id%3Dfile_" in src
                            has_sig = "sig=" in src or "sig%3D" in src or "&amp;sig=" in src
                            logging.info(f"      🔗 URL check: file_id={has_file}, signature={has_sig}")
                    else:
                        logging.info(f"   ℹ️  No ChatGPT API images detected yet...")
                        
                except Exception as e:
                    logging.debug(f"Detailed logging error: {e}")
                last_detailed_log = time.time()
            
            try:
                # ✅ Check for error messages first
                messages = driver.find_elements(By.XPATH, "//div[@data-message-author-role='assistant']")
                current_message_count = len(messages)
                
                if current_message_count > initial_message_count:
                    latest_message = messages[-1]
                    latest_text = latest_message.text.lower()
                    
                    error_indicators = [
                        "i apologize",
                        "i can't",
                        "i'm unable",
                        "error generating",
                        "something went wrong",
                        "try again",
                        "content policy"
                    ]
                    
                    if any(err in latest_text for err in error_indicators):
                        logging.error(f"❌ ChatGPT error detected: {latest_text[:150]}")
                        return False
                
                # ✅ Strategy 1: Look for backend-api/estuary/content URLs (CURRENT ChatGPT pattern)
                # Check ALL images on page, not just in latest message
                imgs = driver.find_elements(By.TAG_NAME, "img")
                
                logging.debug(f"   🔍 Checking {len(imgs)} total images...")
                
                for img in imgs:
                    try:
                        src = img.get_attribute("src")
                        if not src:
                            continue
                            
                        # Skip if we've seen this image before
                        if src in initial_img_srcs:
                            continue
                        
                        # Check for ChatGPT backend API pattern
                        if "backend-api/estuary/content" in src or "backend-api%2Festuary%2Fcontent" in src:
                            # Verify it has the required parameters (check both & and &amp; versions)
                            has_file_id = "id=file_" in src or "id%3Dfile_" in src
                            has_signature = "sig=" in src or "sig%3D" in src or "&amp;sig=" in src
                            
                            if has_file_id and has_signature:
                                logging.info(f"   ✅ Found ChatGPT API image URL!")
                                logging.info(f"   🔗 URL: {src[:120]}...")
                                
                                # Wait a bit for image to fully load
                                logging.info(f"   ⏳ Waiting {self.POST_GENERATION_WAIT}s for image to render...")
                                time.sleep(self.POST_GENERATION_WAIT)
                                
                                # Try to verify it loaded, but don't fail if we can't check
                                try:
                                    is_complete = driver.execute_script(
                                        "return arguments[0].complete && arguments[0].naturalHeight > 0", 
                                        img
                                    )
                                    if is_complete:
                                        logging.info("   ✅ Image fully rendered and loaded")
                                    else:
                                        logging.info("   ⚠️ Image URL present but may still be rendering (continuing anyway)")
                                except Exception as check_error:
                                    logging.info(f"   ⚠️ Could not verify image load state: {check_error} (continuing anyway)")
                                
                                logging.info("✅ Image generation complete (ChatGPT API)")
                                return True
                    except Exception as e:
                        logging.debug(f"   Error checking image: {e}")
                        continue
                
                # Strategy 2: Look for blob URLs
                for img in imgs:
                    try:
                        src = img.get_attribute("src")
                        if src and "blob:" in src and src not in initial_img_srcs:
                            logging.info(f"   ✅ Found blob: URL! Waiting {self.POST_GENERATION_WAIT}s...")
                            time.sleep(self.POST_GENERATION_WAIT)
                            logging.info("✅ Image generation complete (blob)")
                            return True
                    except:
                        continue
                
                # Strategy 3: Look for data URLs
                for img in imgs:
                    try:
                        src = img.get_attribute("src")
                        if src and src.startswith("data:image") and len(src) > 10000:
                            if src not in initial_img_srcs:
                                logging.info(f"   ✅ Found data: URL! Waiting {self.POST_GENERATION_WAIT}s...")
                                time.sleep(self.POST_GENERATION_WAIT)
                                logging.info("✅ Image generation complete (data)")
                                return True
                    except:
                        continue
                
                # Strategy 4: Look for DALL-E URLs
                for img in imgs:
                    try:
                        src = img.get_attribute("src")
                        if src and ("oaidalleapiprodscus" in src or "dalle" in src.lower()):
                            if src not in initial_img_srcs:
                                logging.info(f"   ✅ Found DALL-E URL! Waiting {self.POST_GENERATION_WAIT}s...")
                                time.sleep(self.POST_GENERATION_WAIT)
                                logging.info("✅ Image generation complete (DALL-E)")
                                return True
                    except:
                        continue
                
                # Strategy 5: Look for ANY new substantial image in latest message
                if messages and len(messages) > initial_message_count:
                    latest_message = messages[-1]
                    try:
                        msg_imgs = latest_message.find_elements(By.TAG_NAME, "img")
                        for img in msg_imgs:
                            src = img.get_attribute("src")
                            if src and src not in initial_img_srcs:
                                # Check if it's an actual content image (not icon/avatar)
                                try:
                                    width = img.get_attribute("width") or img.size.get('width', 0)
                                    height = img.get_attribute("height") or img.size.get('height', 0)
                                    if isinstance(width, str):
                                        width = int(width) if width.isdigit() else 0
                                    if isinstance(height, str):
                                        height = int(height) if height.isdigit() else 0
                                    
                                    if width > 200 and height > 200:
                                        logging.info(f"   ✅ Found new image ({width}x{height})! Waiting {self.POST_GENERATION_WAIT}s...")
                                        time.sleep(self.POST_GENERATION_WAIT)
                                        logging.info("✅ Image generation complete (new)")
                                        return True
                                except:
                                    # Fallback: if URL looks substantial (long URL)
                                    if len(src) > 100:
                                        logging.info(f"   ✅ Found new image! Waiting {self.POST_GENERATION_WAIT}s...")
                                        time.sleep(self.POST_GENERATION_WAIT)
                                        logging.info("✅ Image generation complete (new)")
                                        return True
                    except:
                        pass
                
            except Exception as e:
                logging.debug(f"   ⚠️ Check error: {e}")
            
            time.sleep(self.POLL_INTERVAL)
        
        logging.error(f"❌ Image timeout after {int(time.time() - start_time)}s")
        return False

    def download_image(self, driver, img_element=None) -> Optional[bytes]:
        """Download image - tries multiple methods"""
        try:
            if img_element is None:
                # ✅ NEW: Look for the image we just detected (backend-api URL)
                logging.info("   🔍 Finding the generated image...")
                
                # Try to find ChatGPT backend API images first
                imgs = driver.find_elements(By.TAG_NAME, "img")
                chatgpt_images = []
                chatgpt_images_maybe = []
                
                for img in imgs:
                    try:
                        src = img.get_attribute("src")
                        if src and ("backend-api/estuary/content" in src or "backend-api%2Festuary%2Fcontent" in src):
                            # Verify it has required parameters
                            has_file_id = "id=file_" in src or "id%3Dfile_" in src
                            has_signature = "sig=" in src or "sig%3D" in src or "&amp;sig=" in src
                            
                            if has_file_id and has_signature:
                                # Try to verify it's loaded
                                try:
                                    is_complete = driver.execute_script(
                                        "return arguments[0].complete && arguments[0].naturalHeight > 0", 
                                        img
                                    )
                                    if is_complete:
                                        chatgpt_images.append(img)
                                    else:
                                        # Image URL exists but may still be loading - keep as backup
                                        chatgpt_images_maybe.append(img)
                                except:
                                    # Can't verify - keep as backup
                                    chatgpt_images_maybe.append(img)
                    except:
                        continue
                
                # Use fully loaded images first, then unverified ones
                all_candidates = chatgpt_images + chatgpt_images_maybe
                
                if all_candidates:
                    # Get the most recent one (last in list)
                    img_element = all_candidates[-1]
                    if img_element in chatgpt_images:
                        logging.info(f"   ✅ Found fully loaded ChatGPT API image ({len(all_candidates)} total)")
                    else:
                        logging.info(f"   ✅ Found ChatGPT API image (load state unverified, {len(all_candidates)} total)")
                else:
                    # Fallback: look for assistant messages
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
                    
                    # Find largest image (likely the generated one, not icons)
                    img_element = max(imgs, key=lambda img: (img.size.get('width', 0) * img.size.get('height', 0)))
            
            src = img_element.get_attribute("src")
            if not src:
                logging.error("   ❌ Image has no src")
                return None
            
            logging.info(f"   📥 Downloading image from: {src[:100]}...")
            
            # Method 1: ChatGPT backend-api/estuary/content URL
            if "backend-api/estuary/content" in src or "chatgpt.com" in src:
                logging.info(f"   🔄 Using ChatGPT API fetch...")
                try:
                    # Use Selenium to fetch since it has auth cookies
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
            
            # Method 2: Blob URL - use JavaScript fetch
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
            
            # Method 3: Data URL - direct extraction
            elif src.startswith("data:image"):
                base64_data = src.split(",", 1)[1]
                return base64.b64decode(base64_data)
            
            # Method 4: Regular HTTPS URL - download with requests
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

    # ✅✅✅ MAIN GENERATION - LOOP FULLY FIXED ✅✅✅
    def generate_images(self, theme: str, content_type: str, num_images: int, subtopics: List[Dict[str,str]], user_id: Optional[str] = None, meme_mode: bool = False, create_pdf: bool = False, creative_overlay_level: int = 1) -> List[str]:
        """Generate images with FIXED iteration loop - NO ERRORS"""
        
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
            # Load configs
            content_details = self.load_content_details()
            
            # ✅ SMART TEMPLATE SELECTION
            if content_details:
                template_id = content_details.get("template_id", "listicle")
                content_type_from_details = content_details.get("content_type", content_type)
                
                # ✅ If template_id is generic or missing, infer from content_type
                if not template_id or template_id == "listicle":
                    # Map content types to appropriate templates
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
                    
                    # Try to infer from content_type
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
                # No content details - try to infer from content_type
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
            
            # Initialize driver
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
            
            # ✅✅✅ GENERATE EACH IMAGE WITH FULLY FIXED LOOP ✅✅✅
            for idx, sub in enumerate(subtopics[:num_images], start=1):
                slide_key = f"slide_{idx}"
                slide_data = slides.get(slide_key, {})
                slide_structure_type = slide_data.get("structure_type", "general")
                if slide_data.get("visual_hint"):
                    sub["visual_hint"] = slide_data["visual_hint"]
                
                logging.info(f"\n{'='*80}")
                logging.info(f"🎨 IMAGE {idx}/{num_images}: {sub.get('title','')}")
                logging.info(f"{'='*80}")
                
                # ✅ Per-image timeout
                image_start_time = time.time()
                
                attempts = 0
                self.accumulated_feedback = []
                scores_history = []
                
                # ✅ Circuit breakers
                consecutive_failures = 0
                feedback_failures = 0
                
                # ✅ Generate initial prompt ONCE before loop
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
                
                # ✅✅✅ ITERATION LOOP - FULLY PROTECTED & STATE-MANAGED ✅✅✅
                while attempts < self.max_iterations and best["composite_score"] < self.score_threshold:
                    # ✅ 1. PER-IMAGE TIMEOUT CHECK
                    if time.time() - image_start_time > self.IMAGE_TIMEOUT:
                        logging.error(f"❌ Image #{idx} timeout ({self.IMAGE_TIMEOUT/60:.1f}min), using best result")
                        break
                    
                    # ✅ 2. BROWSER HEALTH CHECK
                    if not self.check_browser_health(driver):
                        logging.error("❌ Browser unhealthy, aborting slide")
                        break
                    
                    attempts += 1
                    logging.info(f"\n{'─'*80}")
                    logging.info(f"🔄 ATTEMPT {attempts}/{self.max_iterations}")
                    logging.info(f"{'─'*80}")
                    
                    # ✅ 3. SUBMIT IMAGE GENERATION PROMPT
                    logging.info(f"📤 STEP 1: Submitting IMAGE GENERATION prompt...")
                    if not self.submit_prompt_robust(driver, current_prompt, max_retries=self.max_retries, prompt_type="IMAGE GENERATION"):
                        logging.error("❌ Submit failed")
                        consecutive_failures += 1
                        if consecutive_failures >= self.max_consecutive_failures:
                            logging.error(f"❌ {consecutive_failures} consecutive submit failures, aborting")
                            break
                        continue
                    
                    # ✅ 4. WAIT FOR IMAGE with fresh state capture each time
                    logging.info(f"⏳ STEP 2: Waiting for image to be generated...")
                    if not self.wait_for_real_image(driver):
                        logging.warning(f"⚠️ Image generation failed/timeout")
                        consecutive_failures += 1
                        if consecutive_failures >= self.max_consecutive_failures:
                            logging.error(f"❌ {consecutive_failures} consecutive image failures, aborting")
                            break
                        continue
                    
                    # ✅ Small delay to ensure DOM is fully updated
                    time.sleep(2)
                    
                    # ✅ 5. DOWNLOAD IMAGE (with retry if needed)
                    logging.info(f"💾 STEP 3: Downloading image...")
                    content = self.download_image(driver)
                    
                    # If download failed, try one more time after a longer wait
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
                    
                    # ✅ SUCCESS - Reset failure counter
                    consecutive_failures = 0
                    logging.info(f"✅ Downloaded {len(content)/1024:.1f} KB")
                    
                    # ✅ 6. REQUEST FEEDBACK (THIS SENDS THE FEEDBACK PROMPT)
                    logging.info(f"\n{'─'*40}")
                    logging.info(f"📊 STEP 4: Requesting FEEDBACK (sending feedback prompt)...")
                    logging.info(f"{'─'*40}")
                    
                    scores, improvements = self.request_comprehensive_feedback(
                        driver, template_spec, business_profile, slide_structure_type, attempts
                    )
                    
                    if not scores:
                        feedback_failures += 1
                        logging.warning(f"⚠️ Feedback failure #{feedback_failures}")
                        if feedback_failures >= self.max_feedback_failures:
                            logging.error(f"❌ {feedback_failures} feedback failures, using best result")
                            break
                        # Use default scores to continue
                        scores = {"composite": 6, "overall": 6, "template": 6, "business": 6, "anti_ai": 6}
                    else:
                        feedback_failures = 0  # Reset on success
                        logging.info(f"✅ FEEDBACK RECEIVED!")
                    
                    composite = scores.get("composite", sum(v for k,v in scores.items() if k != "composite") / max(len(scores)-1, 1))
                    scores["composite"] = composite
                    scores_history.append(scores)
                    
                    logging.info(f"📊 COMPOSITE: {composite:.1f}/10")
                    
                    # Track best
                    if composite > best["composite_score"]:
                        best.update({
                            "composite_score": composite,
                            "scores": scores,
                            "image": content
                        })
                        logging.info(f"🎯 New best: {composite:.1f}/10")
                    
                    # Check if done
                    all_pass = all(v >= 9 for k, v in scores.items() if k != "composite")
                    if composite >= self.score_threshold and all_pass:
                        logging.info(f"🎉 THRESHOLD MET! Score: {composite:.1f}/10")
                        break
                    
                    # Add feedback for next iteration
                    if improvements:
                        self.accumulated_feedback.extend(improvements)
                        logging.info(f"📝 Added {len(improvements)} improvement points")
                    
                    # ✅ 7. PREPARE FOR NEXT ITERATION (if needed)
                    if attempts < self.max_iterations and composite < self.score_threshold:
                        logging.info(f"\n{'═'*80}")
                        logging.info(f"🔄 PREPARING FOR ATTEMPT {attempts + 1}/{self.max_iterations}")
                        logging.info(f"{'═'*80}")
                        
                        # Clean browser state
                        self.clean_browser_state(driver)
                        
                        # Generate improved prompt for NEXT iteration
                        logging.info(f"✍️  Generating IMPROVED image generation prompt based on feedback...")
                        current_prompt = self.generate_improved_prompt(
                            self.accumulated_feedback, scores_history, sub, 
                            template_spec, business_profile, slide_structure_type,
                            theme, attempts + 1
                        )
                        logging.info(f"✅ Improved prompt ready ({len(current_prompt)} chars)\n")
                    else:
                        if composite >= self.score_threshold:
                            logging.info(f"✅ Score threshold reached, stopping iterations")
                        else:
                            logging.info(f"✅ Max iterations reached, using best result")
                
                # Upload best image for this slide
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
            
            # Metrics
            if all_metrics:
                self.log_generation_metrics(template_id, business_type, all_metrics)
            
            # PDF
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