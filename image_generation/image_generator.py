# image_generation/image_generator.py
# ✅ FIXED: Comprehensive prompt generation with validation
# ✅ Added extensive logging to debug prompt generation
# ✅ Better fallbacks for missing business/template data

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
from reportlab.pdfgen import canvas

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
    "//button[.//svg]",  # Buttons with SVG icons (common for send buttons)
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
        # Try to find and close common overlays
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
                        time.sleep(1)
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
    """Ultra-robust image generator with aggressive feedback retry"""
    
    def __init__(self):
        self.max_iterations = int(os.getenv("IMG_MAX_ITERS", "6"))
        self.score_threshold = int(os.getenv("IMG_SCORE_THRESHOLD", "9"))
        self.max_retries = int(os.getenv("IMG_MAX_RETRIES", "5"))
        
        self.image_sizes = ["1080x1350", "1080x1080"]
        self.current_batch_size: Optional[str] = None
        
        self.user_logo_path: Optional[str] = None
        self.chrome_profile_path: Optional[str] = None
        self.profile_lock: Optional[threading.Lock] = None
        
        self.accumulated_feedback: List[str] = []
        self.last_pdf_url: Optional[str] = None
        
        # Enhanced timing
        self.GENERATION_TIMEOUT = 480
        self.MIN_IMAGE_SIZE_KB = 50
        self.STABLE_CHECKS = 12
        self.POLL_INTERVAL = 2.0
        self.POST_GENERATION_WAIT = 35
        self.PRE_FEEDBACK_WAIT = 10
        self.FEEDBACK_RESPONSE_WAIT = 25
        
        # Track which submission method works
        self.preferred_submit_method: Optional[str] = None

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

    def generate_initial_prompt(self, subtopic: Dict[str,str], template_spec: Dict, business_profile: Dict, slide_structure_type: str, idx: int, theme: str, visual_prefs: Dict[str,Any]) -> str:
        """Generate intelligent, business-specific, anti-AI prompt"""
        
        # ✅ VALIDATION: Check what we have
        logging.info(f"\n{'─'*80}")
        logging.info(f"🎨 GENERATING PROMPT FOR SLIDE #{idx}")
        logging.info(f"{'─'*80}")
        logging.info(f"📋 Input data:")
        logging.info(f"   • Business type: {business_profile.get('business_type', '❌ MISSING')}")
        logging.info(f"   • Template composition: {template_spec.get('composition', '❌ MISSING')}")
        logging.info(f"   • Theme: {theme or '❌ MISSING'}")
        logging.info(f"   • Subtopic title: {subtopic.get('title', '❌ MISSING')}")
        logging.info(f"   • Subtopic details: {subtopic.get('details', '❌ MISSING')}")
        logging.info(f"   • Slide structure: {slide_structure_type}")
        logging.info(f"   • Brand colors: {visual_prefs.get('colors', 'none')}")
        
        # Validate critical fields
        if not business_profile.get('business_type'):
            logging.error("❌ CRITICAL: business_type missing - prompt will be generic!")
        if not template_spec.get('composition'):
            logging.error("❌ CRITICAL: template composition missing!")
        if not theme:
            logging.warning("⚠️ WARNING: theme is empty")
        
        spec = template_spec
        profile = business_profile
        size = self.get_size_for_image(idx, 1)
        
        # Get approach
        photo_vs_illustration = spec.get("photography_vs_illustration", {})
        approach = photo_vs_illustration.get(profile.get("business_type", "default"), "mixed_50_50")
        
        logging.info(f"   • Visual approach: {approach}")
        
        # ✅ BUILD COMPREHENSIVE PROMPT
        prompt = (
            f"Generate a {size} Instagram carousel image for slide #{idx}.\n\n"
            f"BUSINESS CONTEXT:\n"
            f"- Industry: {profile.get('business_type', 'general')}\n"
            f"- Visual approach: {profile.get('visual_approach', 'professional quality')}\n"
            f"- Tone: {profile.get('tone', 'professional')}\n\n"
            f"CONTENT:\n"
            f"- Template: {spec.get('composition', 'visual layout')}\n"
            f"- Slide type: {slide_structure_type}\n"
            f"- Theme: {theme}\n"
            f"- Title: {subtopic.get('title', 'content')}\n"
            f"- Details: {subtopic.get('details', '')}\n\n"
        )
        
        # Add photography/illustration requirements
        if "photo_100" in approach or "dslr_required" in profile.get('visual_approach', ''):
            prompt += (
                f"PHOTOGRAPHY REQUIREMENTS (MANDATORY):\n"
                f"- DSLR quality: {profile.get('photography_style', 'professional camera quality')}\n"
                f"- Real camera characteristics: natural bokeh, lens imperfections\n"
                f"- Authentic lighting: {', '.join(ANTI_AI_UNIVERSAL_RULES['photography_authenticity'][:3])}\n"
                f"- Real textures: show material authenticity (fabric, wood, metal, skin)\n"
                f"- Natural imperfections: slight asymmetry, environmental context\n\n"
            )
        elif "illustration" in approach:
            prompt += (
                f"ILLUSTRATION REQUIREMENTS:\n"
                f"- Style: {profile.get('illustration_style', 'hand-crafted quality')}\n"
                f"- Hand-crafted feel: {', '.join(ANTI_AI_UNIVERSAL_RULES['illustration_authenticity'][:3])}\n"
                f"- Organic elements: line weight variation, natural shapes\n"
                f"- Texture: add paper grain or brush strokes\n\n"
            )
        else:
            prompt += (
                f"MIXED APPROACH:\n"
                f"- Photography elements: {profile.get('photography_style', 'DSLR quality')}\n"
                f"- Illustration elements: {profile.get('illustration_style', 'hand-crafted style')}\n"
                f"- Blend naturally with depth layering\n\n"
            )
        
        # ✅ SAFE: Access visual_elements with proper fallback
        visual_elements = spec.get('visual_elements', {}).get(
            profile.get('business_type', 'default'),
            spec.get('visual_elements', {}).get('default', ['text overlay', 'clean background', 'focal point'])
        )
        
        prompt += (
            f"COMPOSITION:\n"
            f"- Layout: {spec.get('layout_priority', 'balanced visual hierarchy')}\n"
            f"- Required elements: {', '.join(visual_elements)}\n"
            f"- Text placement: {spec.get('text_placement', 'clear readable positioning')}\n"
            f"- Overall feel: {profile.get('composition', 'professional and engaging')}\n\n"
        )
        
        # Add brand colors if available
        colors = visual_prefs.get("colors", [])
        if colors:
            prompt += (
                f"BRAND COLORS:\n"
                f"- Primary: {', '.join(colors)}\n"
                f"- Usage: {spec.get('color_usage', 'accent strategic placement')}\n"
                f"- Apply subtly - avoid AI-gradient look\n\n"
            )
        
        # Add visual hint if provided
        visual_hint = subtopic.get('visual_hint', '')
        if visual_hint:
            prompt += f"CONTENT TEAM GUIDANCE: {visual_hint}\n\n"
        
        # Anti-AI tactics
        anti_ai_tactics = spec.get('anti_ai_emphasis', [])
        profile_anti_ai = profile.get('anti_ai_tactics', [])
        prompt += (
            f"ANTI-AI-AESTHETIC REQUIREMENTS (CRITICAL):\n"
        )
        for tactic in anti_ai_tactics[:3]:
            prompt += f"- {tactic}\n"
        for tactic in profile_anti_ai[:2]:
            prompt += f"- {tactic}\n"
        prompt += f"- {ANTI_AI_UNIVERSAL_RULES['always_include'][0]}\n"
        prompt += f"- AVOID: {', '.join(ANTI_AI_UNIVERSAL_RULES['always_avoid'][:3])}\n\n"
        
        # Quality standards
        prompt += (
            f"QUALITY STANDARDS:\n"
            f"- Must NOT look AI-generated\n"
            f"- Professional {profile.get('visual_approach', 'quality')} quality\n"
            f"- Industry-appropriate: {profile.get('tone', 'professional')} tone\n"
            f"- Natural imperfections that prove authenticity\n"
            f"- Target: 9+/10 on overall quality AND business fit\n\n"
        )
        
        # Add avoid/prefer lists
        avoid_list = profile.get('avoid', [])
        if avoid_list:
            prompt += f"STRICTLY AVOID: {', '.join(avoid_list)}\n\n"
        prefer_list = profile.get('prefer', [])
        if prefer_list:
            prompt += f"STRONGLY PREFER: {', '.join(prefer_list)}\n"
        
        # ✅ VALIDATION: Log final prompt
        logging.info(f"{'─'*80}")
        logging.info(f"✅ PROMPT GENERATED:")
        logging.info(f"   • Total length: {len(prompt)} characters")
        logging.info(f"   • First 200 chars: {prompt[:200]}...")
        logging.info(f"   • Last 200 chars: ...{prompt[-200:]}")
        logging.info(f"{'─'*80}\n")
        
        return prompt

    def request_comprehensive_feedback(self, driver, template_spec: Dict, business_profile: Dict, slide_structure_type: str, attempt_number: int) -> Tuple[Dict[str, int], List[str]]:
        """Request multi-dimensional feedback with business context"""
        logging.info(f"🤔 Requesting comprehensive feedback (Attempt #{attempt_number})...")
        time.sleep(self.PRE_FEEDBACK_WAIT)
        criteria = template_spec.get('feedback_criteria', [])
        criteria_text = "\n".join([f"   • {c}" for c in criteria])
        business_avoid = business_profile.get('avoid', [])
        business_prefer = business_profile.get('prefer', [])
        feedback_prompt = (
            f"Evaluate the image you just generated. This is attempt #{attempt_number}.\n\n"
            f"CONTEXT:\n"
            f"- Business: {business_profile.get('business_type', 'general')}\n"
            f"- Template: {template_spec.get('composition', 'visual layout')}\n"
            f"- Slide type: {slide_structure_type}\n"
            f"- Required approach: {business_profile.get('visual_approach', 'professional')}\n\n"
            f"EVALUATE ON 4 DIMENSIONS (score each 1-10):\n\n"
            f"1. OVERALL QUALITY Score: X/10\n"
            f"   - Technical excellence (lighting, composition, resolution)\n"
            f"   - Professional polish\n"
            f"   - Visual appeal\n\n"
            f"2. TEMPLATE FIT Score: X/10\n"
            f"   Template criteria:\n{criteria_text}\n\n"
            f"3. BUSINESS APPROPRIATENESS Score: X/10\n"
            f"   - Matches {business_profile.get('tone', 'professional')} tone?\n"
            f"   - Fits {business_profile.get('business_type', 'industry')} industry?\n"
            f"   - Avoids: {', '.join(business_avoid[:3]) if business_avoid else 'generic stock aesthetics'}?\n"
            f"   - Includes: {', '.join(business_prefer[:3]) if business_prefer else 'industry-appropriate elements'}?\n\n"
            f"4. ANTI-AI SUCCESS Score: X/10 (CRITICAL)\n"
            f"   - Does it look REAL, not AI-generated?\n"
            f"   - Are there natural imperfections that prove authenticity?\n"
            f"   - Are textures realistic (not AI-smooth)?\n"
            f"   - Does it avoid AI-aesthetic red flags (perfect symmetry, unnatural gradients, generic composition)?\n\n"
            f"FORMAT YOUR RESPONSE:\n"
            f"Overall Quality Score: X/10\n"
            f"Template Fit Score: X/10\n"
            f"Business Fit Score: X/10\n"
            f"Anti-AI Score: X/10\n\n"
            f"COMPOSITE SCORE: (average of all 4) X/10\n\n"
            f"If ANY score is below 9, provide SPECIFIC, ACTIONABLE improvements:\n"
            f"- What exactly looks AI-generated or fake?\n"
            f"- Which template requirements are not met?\n"
            f"- What business context is missing or wrong?\n"
            f"- What needs to change to reach 9+ on all dimensions?\n\n"
            f"Be brutally honest and specific. I need 9+ on ALL dimensions."
        )
        if not self.submit_prompt_robust(driver, feedback_prompt, max_retries=self.max_retries):
            logging.error("❌ Failed to submit feedback request")
            return {}, []
        time.sleep(self.FEEDBACK_RESPONSE_WAIT)
        try:
            messages = driver.find_elements(By.XPATH, "//div[@data-message-author-role='assistant']")
            if not messages:
                logging.warning("⚠️ No feedback messages found")
                return {}, []
            feedback_text = "\n".join([m.text for m in messages[-2:] if m.text])
            logging.info(f"   📄 Feedback text length: {len(feedback_text)} chars")
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
                logging.warning("⚠️ Could not extract any scores")
            improvements = []
            keywords = [
                "improve", "enhance", "fix", "adjust", "change", "add", "remove",
                "ai-generated", "fake", "unrealistic", "too perfect", "generic",
                "template", "business", "inappropriate", "missing", "violation",
                "smooth", "gradient", "symmetry", "texture", "natural", "authentic"
            ]
            for line in feedback_text.split("\n"):
                clean_line = line.strip()
                if any(k in clean_line.lower() for k in keywords):
                    clean = re.sub(r'^[\d\.\-\*\•\-\>]+\s*', '', clean_line)
                    if clean and len(clean) > 25:
                        improvements.append(clean)
            if not improvements and scores.get('composite', 0) < 9:
                improvements = []
                if scores.get('overall', 10) < 9:
                    improvements.append("Improve overall technical quality and professional polish")
                if scores.get('template', 10) < 9:
                    improvements.append(f"Better match {template_spec.get('composition', 'template')} requirements")
                if scores.get('business', 10) < 9:
                    improvements.append(f"Make more appropriate for {business_profile.get('business_type', 'business')} industry")
                if scores.get('anti_ai', 10) < 9:
                    improvements.append("Add natural imperfections to look less AI-generated - real textures, asymmetry, organic variation")
            logging.info(f"✅ Extracted {len(improvements)} improvements")
            for imp in improvements[:5]:
                logging.info(f"   • {imp[:100]}...")
            return scores, improvements
        except Exception as e:
            logging.error(f"❌ Error extracting feedback: {e}")
            return {}, []

    def generate_improved_prompt(self, accumulated_feedback: List[str], scores_history: List[Dict], subtopic: Dict[str,str], template_spec: Dict, business_profile: Dict, slide_structure_type: str, theme: str, attempt: int) -> str:
        """Generate improvement prompt prioritizing weakest dimension"""
        if scores_history:
            last_scores = scores_history[-1]
            weakest_dim = min(last_scores.items(), key=lambda x: x[1] if x[0] != 'composite' else 10)
            weakest_name, weakest_score = weakest_dim
        else:
            weakest_name, weakest_score = "overall", 0
        recent_feedback = "\n".join([f"• {fb}" for fb in accumulated_feedback[-5:]])
        dimension_focus = {
            "overall": "Focus on technical excellence: lighting, composition, resolution, professional polish",
            "template": f"Strictly follow {template_spec.get('composition', 'template')} requirements and layout",
            "business": f"Make unmistakably appropriate for {business_profile.get('business_type', 'industry')} with {business_profile.get('tone', 'professional')} tone",
            "anti_ai": "CRITICAL: Add natural imperfections, real textures, organic variation - must not look AI-generated"
        }
        prompt = (
            f"REGENERATE with targeted improvements (Attempt #{attempt}):\n\n"
            f"PREVIOUS SCORES:\n"
        )
        if scores_history:
            for i, score_set in enumerate(scores_history[-2:], start=len(scores_history)-1):
                prompt += f"Attempt {i}: "
                for dim, score in score_set.items():
                    if dim != 'composite':
                        prompt += f"{dim.capitalize()}={score}/10, "
                prompt += f"Composite={score_set.get('composite', 0):.1f}/10\n"
        prompt += (
            f"\nWEAKEST DIMENSION: {weakest_name.upper()} ({weakest_score}/10)\n"
            f"PRIMARY FOCUS: {dimension_focus.get(weakest_name, 'overall improvement')}\n\n"
            f"CRITICAL FIXES NEEDED:\n{recent_feedback}\n\n"
            f"CONTEXT (don't change):\n"
            f"- Business: {business_profile.get('business_type', 'general')}\n"
            f"- Template: {template_spec.get('composition', 'visual layout')}\n"
            f"- Slide type: {slide_structure_type}\n"
            f"- Theme: {theme}\n"
            f"- Content: {subtopic.get('title', 'slide content')}\n\n"
        )
        if weakest_name == "overall":
            prompt += (
                f"TECHNICAL REQUIREMENTS:\n"
                f"- Perfect lighting: natural sources, proper shadows, no artificial glare\n"
                f"- Sharp focus: DSLR quality, proper depth of field\n"
                f"- Professional composition: rule of thirds, visual hierarchy\n"
                f"- High resolution: crisp details, no pixelation\n\n"
            )
        elif weakest_name == "template":
            visual_elements = template_spec.get('visual_elements', {}).get(
                business_profile.get('business_type', 'default'),
                template_spec.get('visual_elements', {}).get('default', [])
            )
            prompt += (
                f"TEMPLATE ENFORCEMENT:\n"
                f"- Layout: {template_spec.get('layout_priority', 'balanced hierarchy')} (non-negotiable)\n"
                f"- Required elements: {', '.join(visual_elements)}\n"
                f"- Text placement: {template_spec.get('text_placement', 'clear positioning')}\n"
                f"- Composition type: {template_spec.get('composition', 'professional layout')}\n"
                f"- Meet ALL criteria: {', '.join(template_spec.get('feedback_criteria', ['professional quality'])[:3])}\n\n"
            )
        elif weakest_name == "business":
            prompt += (
                f"BUSINESS APPROPRIATENESS:\n"
                f"- Industry: {business_profile.get('business_type', 'general')} (make this OBVIOUS)\n"
                f"- Tone: {business_profile.get('tone', 'professional')} (every element should reflect this)\n"
                f"- Visual approach: {business_profile.get('visual_approach', 'professional quality')}\n"
                f"- AVOID: {', '.join(business_profile.get('avoid', ['generic stock aesthetics']))}\n"
                f"- INCLUDE: {', '.join(business_profile.get('prefer', ['industry-appropriate elements']))}\n\n"
            )
        elif weakest_name == "anti_ai":
            prompt += (
                f"ANTI-AI AUTHENTICITY (CRITICAL):\n"
                f"- Natural imperfections: slight asymmetry, organic variation, real-world chaos\n"
                f"- Real textures: visible grain, pores, fabric weave, wood grain, material authenticity\n"
                f"- Natural lighting: imperfect shadows, hotspots, ambient variations\n"
                f"- Avoid AI red flags: perfect gradients, unnatural smoothness, sterile composition\n"
                f"- Add humanity: hand-drawn elements, environmental context, moment-in-time feel\n"
                f"- {', '.join(business_profile.get('anti_ai_tactics', [])[:2])}\n\n"
            )
        prompt += (
            f"APPLY ALL FIXES ABOVE.\n"
            f"TARGET: 9+/10 on ALL dimensions, especially {weakest_name.upper()}.\n"
            f"Make it look REAL, professionally crafted, industry-appropriate.\n"
            f"This MUST reach threshold this attempt."
        )
        
        logging.info(f"✅ Improvement prompt generated: {len(prompt)} chars")
        
        return prompt

    def log_generation_metrics(self, template_id: str, business_type: str, metrics: List[Dict]):
        """Log comprehensive generation metrics"""
        total_slides = len(metrics)
        total_attempts = sum(m['attempts'] for m in metrics)
        avg_attempts = total_attempts / total_slides if total_slides else 0
        avg_composite = sum(m['final_composite'] for m in metrics) / total_slides if total_slides else 0
        dimension_avgs = {}
        for dim in ['overall', 'template', 'business', 'anti_ai']:
            scores = [m['final_scores'].get(dim, 0) for m in metrics]
            dimension_avgs[dim] = sum(scores) / len(scores) if scores else 0
        logging.info(f"\n{'='*80}")
        logging.info(f"📊 GENERATION METRICS")
        logging.info(f"{'='*80}")
        logging.info(f"Template: {template_id}")
        logging.info(f"Business: {business_type}")
        logging.info(f"Total slides: {total_slides}")
        logging.info(f"Total attempts: {total_attempts}")
        logging.info(f"Avg attempts per slide: {avg_attempts:.1f}")
        logging.info(f"\n🎯 AVERAGE SCORES:")
        logging.info(f"   Composite: {avg_composite:.2f}/10")
        for dim, score in dimension_avgs.items():
            logging.info(f"   {dim.capitalize()}: {score:.2f}/10")
        lowest_dim = min(dimension_avgs.items(), key=lambda x: x[1])
        if lowest_dim[1] < 8.5:
            logging.warning(f"\n⚠️ AREA FOR IMPROVEMENT: {lowest_dim[0]} (avg: {lowest_dim[1]:.2f}/10)")
        logging.info(f"{'='*80}\n")

    def submit_prompt_robust(self, driver, prompt: str, max_retries: int = 5) -> bool:
        """Submit prompt with ultra-robust retry logic and validation"""
        
        # ✅ VALIDATE: Check prompt before submission
        if not prompt or len(prompt) < 100:
            logging.error(f"❌ CRITICAL: Prompt too short ({len(prompt)} chars)! Something is wrong!")
            logging.error(f"   Prompt: {prompt}")
            return False
        
        logging.info(f"📝 Preparing to submit {len(prompt)}-char prompt...")
        
        for attempt in range(max_retries):
            try:
                logging.info(f"   • Submit attempt {attempt + 1}/{max_retries}...")
                
                # ✅ VALIDATE: Check we're still on ChatGPT
                current_url = driver.current_url
                if "chatgpt.com" not in current_url:
                    logging.warning(f"⚠️ Not on ChatGPT page! URL: {current_url}")
                    driver.get("https://chatgpt.com/chat")
                    time.sleep(10)
                
                # ✅ DISMISS: Check for and dismiss any overlays first
                _dismiss_overlays(driver)
                
                # Find composer
                composer = _find_any(driver, COMPOSER_SELECTORS, timeout=15)
                
                # Clear any existing content
                try:
                    composer.clear()
                except:
                    # If clear() fails, try selecting all and deleting
                    composer.send_keys(Keys.CONTROL + "a")
                    composer.send_keys(Keys.DELETE)
                
                time.sleep(0.5)
                
                # Type prompt in smaller chunks to avoid UI lag
                chunk_size = 500
                for i in range(0, len(prompt), chunk_size):
                    chunk = prompt[i:i+chunk_size]
                    composer.send_keys(chunk)
                    time.sleep(0.2)
                
                time.sleep(2)  # Longer wait for UI to process
                
                # ✅ VERIFY: Check what was actually typed
                typed_value = composer.get_attribute("value") or composer.text or ""
                actual_len = len(typed_value)
                expected_len = len(prompt)
                
                logging.info(f"   📊 Typed {actual_len}/{expected_len} chars ({actual_len/expected_len*100:.1f}%)")
                
                if actual_len < expected_len * 0.85:  # Allow 15% margin for whitespace differences
                    logging.warning(f"⚠️ Too few chars typed - retrying...")
                    continue
                
                # Try multiple methods to submit
                submitted = False
                
                # If we know what worked before, try that first
                if self.preferred_submit_method == "enter":
                    try:
                        logging.info(f"   ⌨️ Using preferred method: Enter key...")
                        composer.send_keys(Keys.ENTER)
                        time.sleep(1)
                        logging.info(f"   ✅ Enter key pressed")
                        submitted = True
                    except Exception as e:
                        logging.warning(f"   ⚠️ Preferred method failed: {e}")
                
                # METHOD 1: Find and click send button (if not already submitted)
                if not submitted:
                    try:
                        logging.info(f"   🔘 Method 1: Looking for send button...")
                        send_btn = _find_clickable(driver, SEND_BUTTON_SELECTORS, timeout=8)
                        send_btn.click()
                        logging.info(f"   ✅ Send button clicked")
                        submitted = True
                        self.preferred_submit_method = "button"  # Remember for next time
                    except Exception as e:
                        logging.warning(f"   ⚠️ Send button not found: {e}")
                
                # METHOD 2: Press Enter (Shift+Enter for newline, Enter for send)
                if not submitted:
                    try:
                        logging.info(f"   ⌨️ Method 2: Trying Enter key...")
                        composer.send_keys(Keys.ENTER)
                        time.sleep(1)
                        logging.info(f"   ✅ Enter key pressed")
                        submitted = True
                        self.preferred_submit_method = "enter"  # Remember for next time
                    except Exception as e:
                        logging.warning(f"   ⚠️ Enter key failed: {e}")
                
                # METHOD 3: Try JavaScript click on button
                if not submitted:
                    try:
                        logging.info(f"   🔧 Method 3: JavaScript click...")
                        button = driver.find_element(By.XPATH, "//button[@data-testid='send-button']")
                        driver.execute_script("arguments[0].click();", button)
                        logging.info(f"   ✅ JavaScript click executed")
                        submitted = True
                    except Exception as e:
                        logging.warning(f"   ⚠️ JavaScript click failed: {e}")
                
                # METHOD 4: Try alternative button selectors with JS
                if not submitted:
                    try:
                        logging.info(f"   🔧 Method 4: Alternative button with JS...")
                        # Try to find any button that looks like a send button
                        buttons = driver.find_elements(By.TAG_NAME, "button")
                        for btn in buttons:
                            aria_label = btn.get_attribute("aria-label") or ""
                            data_testid = btn.get_attribute("data-testid") or ""
                            if "send" in aria_label.lower() or "send" in data_testid.lower():
                                driver.execute_script("arguments[0].click();", btn)
                                logging.info(f"   ✅ Found and clicked send button via JS")
                                submitted = True
                                break
                    except Exception as e:
                        logging.warning(f"   ⚠️ Alternative button search failed: {e}")
                
                if submitted:
                    logging.info("✅ Prompt submitted successfully")
                    time.sleep(2)  # Wait for submission to process
                    return True
                else:
                    logging.warning(f"⚠️ All submission methods failed for attempt {attempt + 1}")
                    
                    # ✅ DEBUG: Take screenshot on failure
                    try:
                        screenshot_path = f"/tmp/submit_fail_attempt_{attempt + 1}.png"
                        driver.save_screenshot(screenshot_path)
                        logging.info(f"   📸 Screenshot saved: {screenshot_path}")
                    except Exception as e:
                        logging.debug(f"   Screenshot failed: {e}")
                    
            except Exception as e:
                logging.warning(f"⚠️ Submit attempt {attempt + 1} failed: {e}")
                time.sleep(2)
                
        logging.error("❌ All submit attempts failed")
        return False

    def wait_for_real_image(self, driver) -> bool:
        """Wait for image generation with robust polling"""
        logging.info("⏳ Waiting for image generation...")
        start_time = time.time()
        
        while time.time() - start_time < self.GENERATION_TIMEOUT:
            try:
                imgs = driver.find_elements(By.TAG_NAME, "img")
                for img in imgs:
                    src = img.get_attribute("src")
                    if src and "blob:" in src:
                        time.sleep(self.POST_GENERATION_WAIT)
                        logging.info("✅ Image generation complete")
                        return True
            except Exception as e:
                logging.debug(f"Polling error: {e}")
            
            time.sleep(self.POLL_INTERVAL)
        
        logging.error("❌ Image generation timeout")
        return False

    def download_image(self, driver, img_element) -> Optional[bytes]:
        """Download image from blob URL"""
        try:
            src = img_element.get_attribute("src")
            if not src or "blob:" not in src:
                return None
            
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
            logging.info("📄 Creating PDF from images...")
            
            images = []
            for url in image_urls:
                resp = requests.get(url, timeout=30)
                if resp.status_code == 200:
                    images.append(Image.open(BytesIO(resp.content)))
            
            if not images:
                logging.error("❌ No images downloaded for PDF")
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
            logging.info(f"✅ PDF created: {pdf_url}")
            
            os.unlink(pdf_path)
            
            return pdf_url
            
        except Exception as e:
            logging.error(f"❌ PDF creation failed: {e}")
            return None

    def generate_images(self, theme: str, content_type: str, num_images: int, subtopics: List[Dict[str,str]], user_id: Optional[str] = None, meme_mode: bool = False, create_pdf: bool = False, creative_overlay_level: int = 1) -> List[str]:
        """Generate images with comprehensive intelligence and validation"""
        
        # ✅ START: Log generation request
        logging.info(f"\n{'='*80}")
        logging.info(f"🚀 STARTING IMAGE GENERATION")
        logging.info(f"{'='*80}")
        logging.info(f"Request parameters:")
        logging.info(f"   • Theme: {theme}")
        logging.info(f"   • Content type: {content_type}")
        logging.info(f"   • Num images: {num_images}")
        logging.info(f"   • User ID: {user_id or 'None'}")
        logging.info(f"   • Subtopics: {len(subtopics)}")
        logging.info(f"{'='*80}\n")
        
        self.chrome_profile_path, self.profile_lock = ChromeProfileManager.acquire_profile()
        if not self.chrome_profile_path:
            logging.error("❌ No Chrome profile available")
            return []
        image_urls: List[str] = []
        driver = None
        try:
            # Load content details
            content_details = self.load_content_details()
            if not content_details:
                logging.warning("⚠️ No template data found, using fallback")
                template_id = "listicle"
            else:
                template_id = content_details.get("template_id", "listicle")
                logging.info(f"📋 Using template: {template_id}")
            
            # Get template spec
            template_spec = TEMPLATE_VISUAL_SPECS.get(template_id, TEMPLATE_VISUAL_SPECS.get("listicle", {}))
            if not template_spec:
                logging.error("❌ CRITICAL: No template spec found! Using empty dict")
                template_spec = {"composition": "listicle layout", "visual_elements": {"default": ["text", "background"]}}
            
            # Get user survey data
            survey = self.get_user_survey_data(user_id)
            user_context, visual_prefs, business_type = self.build_personalized_context(survey, theme)
            
            # Get business profile
            business_profile = BUSINESS_VISUAL_PROFILES.get(business_type)
            if not business_profile:
                logging.warning(f"⚠️ No profile for {business_type}, using technology_saas as default")
                business_profile = BUSINESS_VISUAL_PROFILES.get("technology_saas", {})
            
            # Ensure business_type is set
            if not business_profile.get("business_type"):
                business_profile["business_type"] = business_type
            
            logging.info(f"🎨 Business profile loaded:")
            logging.info(f"   • Type: {business_profile.get('business_type', 'MISSING')}")
            logging.info(f"   • Approach: {business_profile.get('visual_approach', 'MISSING')}")
            logging.info(f"   • Tone: {business_profile.get('tone', 'MISSING')}")
            
            # Get slides data
            slides = content_details.get("slides", {}) if content_details else {}
            subtopics = expand_subtopics(theme, num_images, subtopics or [])
            self.current_batch_size = None
            
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
            
            # ✅ WAIT: Multiple checks to ensure ChatGPT is fully ready
            logging.info("⏳ Waiting for ChatGPT to be ready...")
            
            # Check 1: Wait for composer to exist
            try:
                WebDriverWait(driver, 60).until(lambda d: _find_any(d, COMPOSER_SELECTORS, timeout=5))
                logging.info("   ✓ Composer found")
            except Exception as e:
                logging.error(f"❌ Composer not found: {e}")
                return []
            
            # Check 2: Wait for page to be interactive
            time.sleep(5)
            
            # Check 3: Try to interact with composer
            try:
                test_composer = _find_any(driver, COMPOSER_SELECTORS, timeout=10)
                test_composer.send_keys(" ")  # Type a space
                test_composer.send_keys(Keys.BACKSPACE)  # Delete it
                logging.info("   ✓ Composer is interactive")
            except Exception as e:
                logging.warning(f"⚠️ Composer interaction test failed: {e}")
            
            # Check 4: Ensure no loading overlays
            time.sleep(3)
            
            logging.info("✅ ChatGPT ready\n")
            
            all_metrics = []
            
            # Generate each image
            for idx, sub in enumerate(subtopics[:num_images], start=1):
                slide_key = f"slide_{idx}"
                slide_data = slides.get(slide_key, {})
                slide_structure_type = slide_data.get("structure_type", "general")
                if slide_data.get("visual_hint"):
                    sub["visual_hint"] = slide_data["visual_hint"]
                
                logging.info(f"\n{'='*80}")
                logging.info(f"🎨 IMAGE {idx}/{num_images}: {sub.get('title','')}")
                logging.info(f"📋 Template: {template_id} | Structure: {slide_structure_type}")
                logging.info(f"🏢 Business: {business_type} | Approach: {business_profile.get('visual_approach', 'professional')}")
                logging.info(f"{'='*80}")
                
                attempts = 0
                self.accumulated_feedback = []
                scores_history = []
                
                # ✅ GENERATE INITIAL PROMPT
                current_prompt = self.generate_initial_prompt(
                    sub, template_spec, business_profile, slide_structure_type, 
                    idx, theme, visual_prefs
                )
                
                # ✅ VALIDATE: Ensure prompt is substantial
                if len(current_prompt) < 500:
                    logging.error(f"❌ CRITICAL: Initial prompt too short ({len(current_prompt)} chars)!")
                    logging.error(f"This indicates missing business_profile or template_spec data!")
                    logging.error(f"Prompt preview: {current_prompt[:200]}")
                    continue
                
                best = {
                    "composite_score": 0,
                    "scores": {},
                    "image": None,
                    "filename": f"images/{business_type}_{template_id}_{idx}_{uuid.uuid4().hex}.png"
                }
                
                # Iteration loop
                while attempts < self.max_iterations and best["composite_score"] < self.score_threshold:
                    attempts += 1
                    logging.info(f"\n{'─'*80}")
                    logging.info(f"🔄 ATTEMPT {attempts}/{self.max_iterations}")
                    logging.info(f"{'─'*80}")
                    
                    # Try to submit prompt
                    submission_success = False
                    for submit_retry in range(3):  # Try up to 3 times with page refresh
                        if self.submit_prompt_robust(driver, current_prompt):
                            submission_success = True
                            break
                        else:
                            if submit_retry < 2:  # Don't refresh on last attempt
                                logging.warning(f"⚠️ Submission failed, refreshing page and retrying ({submit_retry + 1}/3)...")
                                driver.refresh()
                                time.sleep(10)
                                # Wait for composer again
                                try:
                                    _find_any(driver, COMPOSER_SELECTORS, timeout=20)
                                    logging.info("   ✓ Page refreshed, composer ready")
                                except:
                                    logging.error("   ❌ Composer not found after refresh")
                                    break
                    
                    if not submission_success:
                        logging.error("❌ Failed to submit prompt after all retries, skipping to next image...")
                        break  # Exit attempt loop for this image
                    
                    if not self.wait_for_real_image(driver):
                        logging.warning("⚠️ Image timeout, refreshing...")
                        driver.refresh()
                        time.sleep(15)
                        continue
                    
                    logging.info("💾 Downloading image...")
                    imgs = driver.find_elements(By.TAG_NAME, "img")
                    if not imgs:
                        logging.warning("⚠️ No images found")
                        continue
                    
                    content = self.download_image(driver, imgs[-1])
                    if not content:
                        logging.warning("⚠️ Failed to download")
                        continue
                    
                    logging.info(f"✅ Downloaded {len(content)/1024:.1f} KB")
                    
                    scores, improvements = self.request_comprehensive_feedback(
                        driver, template_spec, business_profile, slide_structure_type, attempts
                    )
                    
                    if not scores:
                        scores = {"composite": 6, "overall": 6, "template": 6, "business": 6, "anti_ai": 6}
                        logging.warning("⚠️ Using default scores")
                    
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
                    
                    all_dimensions_pass = all(
                        v >= getattr(self, 'dimension_threshold', 9)
                        for k, v in scores.items() if k != "composite"
                    )
                    
                    if composite >= self.score_threshold and all_dimensions_pass:
                        logging.info(f"🎉 ALL THRESHOLDS MET! Composite: {composite:.1f}, All dims >= {getattr(self, 'dimension_threshold', 9)}")
                        break
                    elif composite >= self.score_threshold:
                        logging.info(f"⚠️ Composite met but dimensions low: {[k for k,v in scores.items() if k!='composite' and v<getattr(self, 'dimension_threshold', 9)]}")
                    
                    if improvements:
                        self.accumulated_feedback.extend(improvements)
                        logging.info(f"📝 Total feedback items: {len(self.accumulated_feedback)}")
                    
                    if attempts < self.max_iterations:
                        current_prompt = self.generate_improved_prompt(
                            self.accumulated_feedback, scores_history, sub, 
                            template_spec, business_profile, slide_structure_type,
                            theme, attempts + 1
                        )
                
                # Upload best image
                if best["image"]:
                    logging.info(f"\n📤 Uploading final image...")
                    logging.info(f"   Final composite: {best['composite_score']:.1f}/10")
                    logging.info(f"   Final scores: {best['scores']}")
                    
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
                    
                    logging.info(f"✅ Uploaded: {url}")
                else:
                    logging.warning(f"⚠️ No image for slide {idx}")
            
            # Log metrics
            if all_metrics:
                self.log_generation_metrics(template_id, business_type, all_metrics)
            
            # Create PDF if requested
            if create_pdf and image_urls:
                logging.info("\n📄 Creating PDF...")
                self.last_pdf_url = self.create_pdf_from_s3_images(image_urls)
                if self.last_pdf_url:
                    logging.info(f"✅ PDF: {self.last_pdf_url}")
            
            logging.info(f"\n{'='*80}")
            logging.info(f"✅ COMPLETE! Generated {len(image_urls)} images")
            logging.info(f"{'='*80}\n")
            
            return image_urls
            
        except Exception as e:
            logging.error(f"❌ Generation error: {e}", exc_info=True)
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