# image_generation/image_generator.py - COMPLETE PRODUCTION VERSION
"""
CHATGPT DESKTOP APP IMAGE GENERATOR - PRODUCTION READY
========================================================

COMPLETE WORKFLOW:
1. Launch/connect to ChatGPT Desktop app
2. For each slide:
   - STEP 1: Generate READY-TO-POST prompt → Validate → Extract COPY LOCK
   - STEP 2: Generate initial image
   - STEP 3: Evaluate image (score + issues)
   - STEP 4: Iterative regeneration (A/B/C/D variants) until threshold
   - FINAL: Polish render → Download → Logo overlay → S3 upload
3. Create PDF from all images → Upload to S3
4. Return list of S3 URLs

FEATURES:
✅ Reliable ChatGPT Desktop automation
✅ Iterative quality improvement loop
✅ Logo overlay from S3
✅ S3 upload with CDN support
✅ DynamoDB asset tracking
✅ PDF generation
✅ Comprehensive error handling
✅ Debug logging
"""

from __future__ import annotations

import os
import re
import sys
import time
import uuid
import json
import logging
import traceback
import hashlib
import subprocess
from io import BytesIO
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from dotenv import load_dotenv

from PIL import Image, ImageFilter

# ChatGPT Desktop automation
from pywinauto import Desktop, Application
from pywinauto.keyboard import send_keys
import pyperclip

# Windows registry for Downloads folder
try:
    import winreg
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False

load_dotenv()

# =========================================================================================
# LOGGING SETUP
# =========================================================================================
logger = logging.getLogger("imagegen")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# =========================================================================================
# ENV CONFIG
# =========================================================================================
# AWS
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1").strip()
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "").strip()
ASSETS_TABLE_NAME = os.getenv("ASSETS_TABLE_NAME", "PostingExpertAssets").strip()

# S3 Configuration
S3_IMAGE_PREFIX = os.getenv("S3_IMAGE_PREFIX", "images").strip().strip("/")
S3_LOGO_PREFIX = os.getenv("S3_LOGO_PREFIX", "logos").strip().strip("/")
S3_PDF_PREFIX = os.getenv("S3_PDF_PREFIX", "pdfs").strip().strip("/")
S3_PUBLIC_READ = os.getenv("S3_PUBLIC_READ", "false").lower() == "true"
S3_CDN_BASE_URL = os.getenv("S3_CDN_BASE_URL", "").strip().rstrip("/")

# Image Quality Settings
IMG_MAX_ITERS = int(os.getenv("IMG_MAX_ITERS", "10"))
IMG_FAST_TARGET_ITERS = int(os.getenv("IMG_FAST_TARGET_ITERS", "4"))
IMG_SCORE_THRESHOLD = float(os.getenv("IMG_SCORE_THRESHOLD", "8.0"))
IMG_MAX_TIME_SEC = int(os.getenv("IMG_MAX_TIME_SEC", "1800"))
IMG_PATIENCE = int(os.getenv("IMG_PATIENCE", "8"))

# Timeouts
TEXT_RESPONSE_TIMEOUT = int(os.getenv("TEXT_RESPONSE_TIMEOUT", "180"))
IMAGE_GENERATION_TIMEOUT = int(os.getenv("IMAGE_GENERATION_TIMEOUT", "600"))
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "120"))

# Download Settings
DOWNLOAD_MIN_BYTES = int(os.getenv("DOWNLOAD_MIN_BYTES", "50000"))
DOWNLOAD_RETRIES = int(os.getenv("DOWNLOAD_RETRIES", "3"))
ALLOWED_DL_EXTS = (".png", ".jpg", ".jpeg", ".webp")

# Logo Settings
LOGO_ENABLED = os.getenv("LOGO_ENABLED", "true").lower() == "true"
LOGO_MAX_W = int(os.getenv("LOGO_MAX_W", "190"))
LOGO_MAX_H = int(os.getenv("LOGO_MAX_H", "120"))
LOGO_PADDING = int(os.getenv("LOGO_PADDING", "46"))
LOGO_OPACITY = float(os.getenv("LOGO_OPACITY", "0.98"))
LOGO_MIN_ALPHA = int(os.getenv("LOGO_MIN_ALPHA", "20"))

# ChatGPT App Config
CHATGPT_EXE_PATH = os.getenv("CHATGPT_EXE_PATH", "").strip()
CHATGPT_WINDOW_TITLE = os.getenv("CHATGPT_WINDOW_TITLE", "ChatGPT").strip()

# App Behavior
APP_LAUNCH_WAIT = float(os.getenv("APP_LAUNCH_WAIT", "3.0"))
APP_FOCUS_WAIT = float(os.getenv("APP_FOCUS_WAIT", "0.5"))
APP_IDLE_CHECK_INTERVAL = float(os.getenv("APP_IDLE_CHECK_INTERVAL", "1.0"))
APP_IDLE_STABLE_COUNT = int(os.getenv("APP_IDLE_STABLE_COUNT", "3"))

# Debug
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

if DEBUG_MODE:
    logger.setLevel(logging.DEBUG)

# =========================================================================================
# DOWNLOAD DIR
# =========================================================================================
def _get_download_dir() -> str:
    """Get Windows Downloads folder (handles redirected paths)"""
    # Try registry first (most reliable)
    if HAS_WINREG:
        try:
            key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
                downloads = winreg.QueryValueEx(k, "{374DE290-123F-4565-9164-39C4925E467B}")[0]
            expanded = os.path.expandvars(downloads)
            if os.path.isdir(expanded):
                return expanded
        except Exception as e:
            logger.debug(f"Registry lookup failed: {e}")
    
    # Fallback to standard location
    default = os.path.join(os.path.expanduser("~"), "Downloads")
    if os.path.isdir(default):
        return default
    
    # Last resort: current directory
    return os.getcwd()

DOWNLOAD_DIR = _get_download_dir()
logger.info(f"📂 Download directory: {DOWNLOAD_DIR}")

# =========================================================================================
# AWS INITIALIZATION
# =========================================================================================
s3 = None
dynamodb = None
user_survey_table = None
assets_table = None

try:
    if not S3_BUCKET_NAME:
        raise RuntimeError("S3_BUCKET_NAME is not set in environment")
    
    s3 = boto3.client("s3", region_name=AWS_REGION)
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    user_survey_table = dynamodb.Table("UserSurveyData")
    assets_table = dynamodb.Table(ASSETS_TABLE_NAME)
    
    # Verify S3 bucket exists
    s3.head_bucket(Bucket=S3_BUCKET_NAME)
    logger.info(f"✅ AWS initialized: {S3_BUCKET_NAME} ({AWS_REGION})")
    
except Exception as e:
    logger.error(f"❌ AWS initialization failed: {e}")
    logger.warning("⚠️ Image upload and asset tracking will be disabled")
    s3 = None
    dynamodb = None

# =========================================================================================
# CHATGPT DESKTOP BRIDGE
# =========================================================================================
class ChatGPTDesktopBridge:
    """
    Reliable ChatGPT Desktop App automation with proper state management
    
    Handles:
    - App launch and connection
    - Message sending via clipboard
    - Response detection and extraction
    - Image download automation
    """
    
    def __init__(self):
        self.app = None
        self.window = None
        self.last_response = ""
        self._connection_attempts = 0
        
    def launch_and_connect(self) -> None:
        """Launch ChatGPT app and connect to window"""
        
        # Check if we have either EXE path or App ID
        CHATGPT_APP_ID = os.getenv("CHATGPT_APP_ID", "").strip()
        
        if not CHATGPT_EXE_PATH and not CHATGPT_APP_ID:
            raise RuntimeError(
                "Neither CHATGPT_EXE_PATH nor CHATGPT_APP_ID is set. Add to .env:\n"
                "CHATGPT_APP_ID=shell:AppsFolder\\OpenAI.ChatGPT-Desktop_2p2nqsd0c76g0!App\n"
                "OR\n"
                "CHATGPT_EXE_PATH=C:\\Program Files\\...\\ChatGPT.exe"
            )
        
        # Try connecting to existing instance first
        try:
            # For Windows Store apps, connect by title instead of path
            self.app = Application(backend="uia").connect(title_re=f".*{re.escape(CHATGPT_WINDOW_TITLE)}.*", timeout=5)
            logger.info("✅ Connected to existing ChatGPT instance")
        except Exception:
            # Launch new instance
            logger.info("🚀 Launching ChatGPT app...")
            
            if CHATGPT_APP_ID:
                # Launch via Windows Store App ID
                subprocess.run(["explorer.exe", CHATGPT_APP_ID], shell=True)
            elif CHATGPT_EXE_PATH and os.path.exists(CHATGPT_EXE_PATH):
                # Launch via EXE path
                subprocess.Popen([CHATGPT_EXE_PATH])
            else:
                raise RuntimeError(f"Cannot launch ChatGPT. Invalid path: {CHATGPT_EXE_PATH}")
            
            time.sleep(APP_LAUNCH_WAIT)
            
            # Retry connection (now by title for Store apps)
            for attempt in range(10):
                try:
                    self.app = Application(backend="uia").connect(
                        title_re=f".*{re.escape(CHATGPT_WINDOW_TITLE)}.*", 
                        timeout=3
                    )
                    logger.info(f"✅ Connected to ChatGPT (attempt {attempt + 1})")
                    break
                except Exception as e:
                    if attempt == 9:
                        raise RuntimeError(f"Failed to connect to ChatGPT after 10 attempts: {e}")
                    time.sleep(1)
    
    def _ensure_connected(self) -> None:
        """Ensure connection is still valid, reconnect if needed"""
        try:
            if self.window:
                self.window.set_focus()
                return
        except Exception:
            logger.warning("⚠️ Lost connection, reconnecting...")
            self.window = None
            self.app = None
            self.launch_and_connect()
    
    def _focus_input_box(self) -> None:
        """Focus the chat input textarea"""
        try:
            self._ensure_connected()
            
            # Click near bottom of window (where input box typically is)
            rect = self.window.rectangle()
            x = rect.left + rect.width() // 2
            y = rect.bottom - 100  # 100px from bottom
            
            self.window.click_input(coords=(x, y))
            time.sleep(0.3)
            
            # Clear any existing text with triple-click + backspace
            send_keys("{ESC}")  # Cancel any ongoing operations
            time.sleep(0.1)
            self.window.type_keys("{HOME}")  # Go to start
            time.sleep(0.1)
            send_keys("^a")  # Select all
            time.sleep(0.1)
            send_keys("{BACKSPACE}")  # Delete
            time.sleep(0.2)
            
        except Exception as e:
            logger.warning(f"⚠️ Focus input box failed: {e}")
    
    def send_message(self, message: str) -> None:
        """
        Send message to ChatGPT using clipboard paste
        Most reliable method for long prompts
        """
        if not message or not message.strip():
            raise ValueError("Message is empty")
        
        logger.info(f"📤 Sending message ({len(message)} chars)...")
        
        self._focus_input_box()
        
        # Use clipboard for reliability (handles long text and special chars)
        old_clipboard = pyperclip.paste()  # Save old clipboard
        try:
            pyperclip.copy(message)
            time.sleep(0.2)
            
            # Paste with Ctrl+V
            send_keys("^v")
            time.sleep(0.4)
            
            # Send with Enter
            send_keys("{ENTER}")
            time.sleep(1.0)
            
            logger.debug("✅ Message sent successfully")
            
        finally:
            # Restore old clipboard
            try:
                pyperclip.copy(old_clipboard)
            except:
                pass
    
    def _get_visible_text(self) -> str:
        """
        Extract all visible text from ChatGPT window
        Returns concatenated text from all text elements
        """
        try:
            all_text = []
            
            # Get all descendants and extract text
            for elem in self.window.descendants():
                try:
                    # Get control type
                    ctrl_type = elem.element_info.control_type
                    
                    # Look for text-containing elements
                    if ctrl_type in ["Edit", "Text", "Document", "Pane"]:
                        text = elem.window_text()
                        if text and len(text) > 15:  # Skip short UI labels
                            all_text.append(text.strip())
                            
                except Exception:
                    continue
            
            # Join and return
            result = "\n".join(all_text)
            
            if DEBUG_MODE and result:
                logger.debug(f"📄 Extracted {len(result)} chars from window")
            
            return result
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to get visible text: {e}")
            return ""
    
    def _extract_latest_response(self, full_text: str) -> str:
        """
        Extract the most recent assistant response from conversation text
        Tries to isolate just the latest AI response
        """
        if not full_text:
            return ""
        
        lines = full_text.split("\n")
        
        # Look for response blocks (typically longer text)
        response_lines = []
        for line in reversed(lines):
            line = line.strip()
            
            # Skip empty lines
            if not line:
                continue
            
            # Skip UI elements (short text)
            if len(line) < 20:
                continue
            
            # Add to response
            response_lines.append(line)
            
            # Stop after we have substantial content
            if len("\n".join(response_lines)) > 500:
                break
        
        # Reverse to get correct order
        response = "\n".join(reversed(response_lines))
        
        return response.strip()
    
    def wait_for_response(self, timeout: int = 180) -> str:
        """
        Wait for ChatGPT to complete its response
        
        Uses stability detection: when text stops changing, response is complete
        
        Args:
            timeout: Maximum seconds to wait
            
        Returns:
            Latest response text
        """
        logger.info(f"⏳ Waiting for response (timeout: {timeout}s)...")
        
        start_time = time.time()
        last_text = ""
        stable_count = 0
        
        while time.time() - start_time < timeout:
            # Get current window text
            current_text = self._get_visible_text()
            
            # Check if text has stabilized
            if current_text and current_text == last_text:
                stable_count += 1
                
                # Consider stable after N consecutive matches
                if stable_count >= APP_IDLE_STABLE_COUNT:
                    response = self._extract_latest_response(current_text)
                    self.last_response = response
                    
                    logger.info(f"✅ Response received ({len(response)} chars)")
                    
                    if DEBUG_MODE:
                        logger.debug(f"Response preview: {response[:200]}...")
                    
                    return response
            else:
                stable_count = 0
                last_text = current_text
            
            # Wait before next check
            time.sleep(APP_IDLE_CHECK_INTERVAL)
        
        # Timeout reached
        logger.warning(f"⚠️ Response timeout after {timeout}s")
        
        # Return whatever we have
        if last_text:
            response = self._extract_latest_response(last_text)
            self.last_response = response
            return response
        
        raise TimeoutError(f"No response received within {timeout}s")
    
    def _click_image_area(self) -> None:
        """Click in the area where generated images typically appear"""
        try:
            self._ensure_connected()
            
            rect = self.window.rectangle()
            # Click in middle-right area (where images usually are)
            x = rect.left + int(rect.width() * 0.65)
            y = rect.top + int(rect.height() * 0.55)
            
            self.window.click_input(coords=(x, y))
            time.sleep(0.5)
            
            logger.debug("🖱️ Clicked image area")
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to click image: {e}")
    
    def _find_and_click_download_button(self) -> bool:
        """
        Find and click the download button in image viewer
        Tries multiple strategies
        """
        try:
            self._ensure_connected()
            
            logger.debug("🔍 Searching for download button...")
            
            # Strategy 1: Look for button with "download" text
            for elem in self.window.descendants():
                try:
                    ctrl_type = elem.element_info.control_type
                    text = (elem.window_text() or "").lower()
                    
                    if ctrl_type == "Button":
                        if any(keyword in text for keyword in ["download", "save", "export"]):
                            logger.info(f"✅ Found download button: '{text}'")
                            elem.click_input()
                            time.sleep(1.0)
                            return True
                            
                except Exception:
                    continue
            
            # Strategy 2: Keyboard shortcut (Ctrl+S)
            logger.info("⚠️ Download button not found, trying Ctrl+S...")
            send_keys("^s")
            time.sleep(0.8)
            send_keys("{ENTER}")
            time.sleep(1.0)
            
            return True
            
        except Exception as e:
            logger.warning(f"⚠️ Download button click failed: {e}")
            return False
    
    def _get_newest_download(self, since_timestamp: float) -> Optional[str]:
        """
        Get the newest image file in Downloads folder created after given timestamp
        
        Args:
            since_timestamp: Only consider files modified after this time
            
        Returns:
            Path to newest file, or None if not found
        """
        try:
            downloads = Path(DOWNLOAD_DIR)
            
            if not downloads.exists():
                logger.warning(f"⚠️ Downloads folder not found: {DOWNLOAD_DIR}")
                return None
            
            newest_file = None
            newest_time = since_timestamp
            
            for file in downloads.iterdir():
                # Skip non-files
                if not file.is_file():
                    continue
                
                # Check extension
                if file.suffix.lower() not in ALLOWED_DL_EXTS:
                    continue
                
                # Check modification time
                try:
                    mtime = file.stat().st_mtime
                    if mtime > newest_time:
                        newest_time = mtime
                        newest_file = str(file)
                except Exception:
                    continue
            
            if newest_file:
                logger.debug(f"📥 Found newest download: {newest_file}")
            
            return newest_file
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to check downloads: {e}")
            return None
    
    def download_latest_image(self, timeout: int = 120) -> str:
        """
        Download the most recently generated image
        
        Process:
        1. Click on image to open viewer
        2. Find and click download button
        3. Wait for file to appear in Downloads folder
        
        Args:
            timeout: Maximum seconds to wait for download
            
        Returns:
            Path to downloaded file
        """
        logger.info("📥 Starting image download...")
        
        download_start = time.time()
        
        # Step 1: Click image to open viewer
        self._click_image_area()
        time.sleep(1.0)
        
        # Step 2: Click download button
        self._find_and_click_download_button()
        
        # Step 3: Wait for file to appear
        end_time = time.time() + timeout
        
        while time.time() < end_time:
            newest_file = self._get_newest_download(since_timestamp=download_start)
            
            if newest_file:
                # Check file size is reasonable
                try:
                    size = os.path.getsize(newest_file)
                    if size > DOWNLOAD_MIN_BYTES:
                        logger.info(f"✅ Downloaded: {newest_file} ({size} bytes)")
                        return newest_file
                    else:
                        logger.debug(f"⏳ File too small ({size} bytes), waiting...")
                except Exception:
                    pass
            
            time.sleep(1.0)
        
        raise TimeoutError(f"Image download timeout after {timeout}s")
    
    def close(self) -> None:
        """Close the ChatGPT app"""
        try:
            if self.window:
                self.window.close()
                logger.info("✅ ChatGPT app closed")
        except Exception:
            pass

# Global bridge instance
_BRIDGE: Optional[ChatGPTDesktopBridge] = None

def get_bridge() -> ChatGPTDesktopBridge:
    """Get or create global bridge instance"""
    global _BRIDGE
    if _BRIDGE is None:
        _BRIDGE = ChatGPTDesktopBridge()
    return _BRIDGE

# =========================================================================================
# HIGH-LEVEL WORKFLOW FUNCTIONS
# =========================================================================================
def ensure_chatgpt_ready() -> None:
    """Ensure ChatGPT app is connected and ready"""
    bridge = get_bridge()
    if bridge.window is None:
        bridge.launch_and_connect()
    else:
        bridge._ensure_connected()

def call_chatgpt_text(prompt: str, timeout: int = TEXT_RESPONSE_TIMEOUT) -> str:
    """Send text prompt and wait for response"""
    ensure_chatgpt_ready()
    bridge = get_bridge()
    bridge.send_message(prompt)
    return bridge.wait_for_response(timeout=timeout)

def call_chatgpt_image(prompt: str, timeout: int = IMAGE_GENERATION_TIMEOUT) -> None:
    """Send image generation prompt and wait for completion"""
    ensure_chatgpt_ready()
    bridge = get_bridge()
    bridge.send_message(prompt)
    bridge.wait_for_response(timeout=timeout)
    logger.info("✅ Image generation complete")

def download_generated_image(timeout: int = DOWNLOAD_TIMEOUT) -> str:
    """Download most recent image, returns local file path"""
    ensure_chatgpt_ready()
    bridge = get_bridge()
    return bridge.download_latest_image(timeout=timeout)

# =========================================================================================
# PARSING UTILITIES
# =========================================================================================
def parse_score(text: str) -> float:
    """Extract numeric score from evaluation text (X/10 or X.X/10)"""
    patterns = [
        r"score[:\s]+(\d+\.?\d*)\s*/\s*10",
        r"score[:\s]+(\d+\.?\d*)",
        r"(\d+\.?\d*)\s*/\s*10",
    ]
    
    text_lower = (text or "").lower()
    
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            try:
                score = float(match.group(1))
                # Clamp to 0-10 range
                return max(0.0, min(10.0, score))
            except ValueError:
                continue
    
    logger.warning("⚠️ Could not parse score from evaluation")
    return 0.0

def extract_issues(eval_text: str) -> str:
    """Extract issues section from evaluation response"""
    if not eval_text:
        return "No issues provided"
    
    # Try to find "Issues:" section
    match = re.search(
        r"Issues:\s*(.+?)(?:\n\s*END\s*$|\Z)", 
        eval_text, 
        flags=re.IGNORECASE | re.DOTALL
    )
    
    if match:
        return match.group(1).strip()
    
    # Fallback: return full text
    return eval_text.strip()

def is_ready_prompt_valid(text: str) -> bool:
    """
    Validate that text is a proper READY-TO-POST prompt
    
    Checks:
    - Ends with "READY"
    - Contains all required sections
    - Doesn't start with conversational phrases
    """
    if not text:
        return False
    
    text = text.strip()
    
    # Must end with READY
    if not re.search(r"(?:^|\n)READY\s*$", text, re.IGNORECASE):
        return False
    
    # Must contain required keywords
    required_keywords = [
        "final headline",
        "final subheadline",
        "bullet",
        "cta",
        "visual blueprint",
        "layout",
        "typography",
        "1080",
        "1350",
    ]
    
    text_lower = text.lower()
    if not all(keyword in text_lower for keyword in required_keywords):
        return False
    
    # Must not start with conversational fluff
    invalid_starts = [
        "got it", "sure", "i'm stepping", "i am stepping",
        "whenever you're ready", "please tell me", 
        "understood", "okay", "yes", "absolutely"
    ]
    
    if any(text_lower.startswith(phrase) for phrase in invalid_starts):
        return False
    
    return True

def build_repair_message() -> str:
    """Build message to repair invalid READY prompt"""
    return """
❌ Your last response is INVALID.

Output the complete READY-TO-POST image generation prompt NOW.

Requirements:
- NO intro, NO "Got it", NO acknowledgments, NO questions
- Output ONLY the structured prompt

Required format:
1) FINAL HEADLINE (exact text)
2) FINAL SUBHEADLINE (exact text)
3) 2-4 BULLET POINTS (exact text)
4) CTA BUTTON TEXT (exact)
5) COMPLETE VISUAL BLUEPRINT (layout, typography, spacing, colors, background, style)
6) Format: 1080×1350
7) Style: Premium, anti-AI

End with: READY
""".strip()

def extract_copy_lock(ready_prompt: str) -> Dict[str, Any]:
    """
    Extract copy elements from READY prompt
    
    Returns dict with: headline, subheadline, bullets (list), cta
    """
    text = (ready_prompt or "").strip()
    
    def grab_line(pattern: str) -> str:
        """Extract single line matching pattern"""
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        return match.group(1).strip() if match else ""
    
    # Extract headline, subheadline, CTA
    headline = grab_line(r"(?:1\)|FINAL\s*HEADLINE).*?[:\-]?\s*(.+?)(?:\n|$)")
    subheadline = grab_line(r"(?:2\)|FINAL\s*SUBHEADLINE).*?[:\-]?\s*(.+?)(?:\n|$)")
    cta = grab_line(r"(?:4\)|CTA\s*BUTTON\s*TEXT).*?[:\-]?\s*(.+?)(?:\n|$)")
    
    # Extract bullets (multi-line)
    bullets_match = re.search(
        r"(?:3\)|2-4\s*BULLET\s*POINTS).*?[:\-]?\s*(.+?)(?:\n\s*(?:4\)|CTA\s*BUTTON|COMPLETE\s*VISUAL))",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    
    bullets = []
    if bullets_match:
        bullets_text = bullets_match.group(1).strip()
        for line in bullets_text.splitlines():
            # Clean bullet formatting
            bullet = line.strip()
            bullet = bullet.lstrip("•").lstrip("-").lstrip("*").strip()
            bullet = re.sub(r"^\d+[\.)]\s*", "", bullet)  # Remove numbering
            
            if bullet and len(bullet) > 5:  # Skip empty/short lines
                bullets.append(bullet)
        
        bullets = bullets[:4]  # Max 4 bullets
    
    return {
        "headline": headline,
        "subheadline": subheadline,
        "bullets": bullets,
        "cta": cta
    }

def layout_variant_for_attempt(attempt: int) -> str:
    """Get layout variant letter (A/B/C/D) for attempt number"""
    variants = ["A", "B", "C", "D"]
    index = (attempt - 2) % 4  # Start variants from attempt 2
    return variants[index]

# =========================================================================================
# PROMPT BUILDERS
# =========================================================================================
def build_step1_prompt(
    slide_idx: int,
    company: str,
    tone: str,
    brand_colors: Optional[str],
    website: Optional[str],
    theme: str,
    slide_title: str,
    slide_points: str,
    user_custom_instructions: str = ""
) -> str:
    """
    Build STEP 1 prompt: Generate READY-TO-POST image generation prompt
    
    This is the "prompt generator" step that creates the detailed
    image generation instructions with locked copy
    """
    
    colors_line = f"Brand colors: {brand_colors}" if brand_colors else "Brand colors: Use minimal, premium palette"
    website_line = f"Website: {website}" if website else "Website: (not provided)"
    
    custom_block = ""
    if user_custom_instructions:
        custom_block = f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USER'S CUSTOM INSTRUCTIONS (MUST FOLLOW):
{user_custom_instructions}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    return f"""
You are a senior brand designer creating an image generation prompt for slide #{slide_idx}.

⚠️ CRITICAL INSTRUCTIONS:
- NO questions, NO intro, NO acknowledgments
- Output ONE complete READY-TO-POST image generation prompt
- Must end with ONLY: READY

BRAND INFORMATION:
- Company: {company}
- Tone: {tone}
- {colors_line}
- {website_line}

CAMPAIGN THEME: {theme}

SLIDE CONTENT:
- Headline: {slide_title}
- Points:
{slide_points}

NON-NEGOTIABLE RULES:
- Use the slide headline + points as BASELINE truth
- Do NOT invent claims, discounts, guarantees, or offers not in the content
- Keep copy premium, crisp, mobile-readable
- Remove words like "create", "generate" from headline
{custom_block}

OUTPUT FORMAT (REQUIRED):
1) FINAL HEADLINE (exact text - attention-grabbing, clean, professional)
2) FINAL SUBHEADLINE (exact text - supports headline)
3) 2-4 BULLET POINTS (exact text - key benefits/features)
4) CTA BUTTON TEXT (exact text - clear action)
5) COMPLETE VISUAL BLUEPRINT:
   - Layout Grid: describe top/middle/bottom structure
   - Typography: fonts, sizes, weights, hierarchy details
   - Spacing: margins, padding, alignment, whitespace strategy
   - Colors: primary, secondary, accent, background palette
   - Background: base treatment, texture, brand integration approach
   - Visual Style: aesthetic direction, photo/icon style, effects, anti-AI techniques
6) FORMAT: 1080×1350 pixels (Instagram portrait 4:5 ratio)
7) QUALITY TARGET: Premium, modern, zero AI vibes, agency-grade, mobile-optimized

Create a prompt that will generate a professional, ready-to-post image.

End with: READY
""".strip()

def build_eval_prompt(attempt_num: int) -> str:
    """Build STEP 3 evaluation prompt"""
    return f"""
🚨 ULTRA-STRICT EVALUATION - ATTEMPT #{attempt_num} 🚨

Evaluate the image above with brutal honesty.

RESPOND EXACTLY IN THIS FORMAT:

Score: X.X/10

Issues:
- Typography: [specific problem, be harsh]
- Hierarchy: [specific problem]
- Design: [specific problem]
- Brand: [specific problem]
- [Any other critical flaws]

END
""".strip()

def build_regen_prompt(
    issues: str,
    attempt_num: int,
    previous_score: float,
    copy_lock: Dict[str, Any],
    variant: str,
    aggressive: bool
) -> str:
    """
    Build STEP 4 regeneration prompt
    
    Args:
        issues: Problems from evaluation
        attempt_num: Current attempt number
        previous_score: Score from last attempt
        copy_lock: Fixed copy elements (headline, subheadline, bullets, cta)
        variant: Layout variant (A/B/C/D)
        aggressive: If True, make major changes; if False, polish only
    """
    
    headline = copy_lock.get("headline", "").strip()
    subheadline = copy_lock.get("subheadline", "").strip()
    bullets = copy_lock.get("bullets", [])
    cta = copy_lock.get("cta", "").strip()
    
    bullets_text = "\n".join([f"- {b}" for b in bullets]) if bullets else "(use bullets from previous)"
    
    if aggressive:
        mode_block = """
FAST-TARGET MODE (Major Changes):
- Make improvement VISUALLY OBVIOUS
- Try different: composition, background treatment, hero placement, color balance
- Keep premium minimal aesthetic (no gimmicks)
- Radical visual refresh while preserving copy
""".strip()
    else:
        mode_block = """
POLISH MODE (Minor Refinements):
- Keep overall composition
- Refine: kerning, letter-spacing, line-height, contrast
- Adjust: margins, padding, alignment precision
- Remove any template vibes
- Increase professional whitespace
""".strip()
    
    return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔥 REGENERATION ATTEMPT #{attempt_num} - PREVIOUS SCORE: {previous_score:.1f}/10
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚫 ABSOLUTE RULE: DO NOT CHANGE ANY COPY TEXT. USE THESE EXACT WORDS:

HEADLINE:
{headline}

SUBHEADLINE:
{subheadline}

BULLETS:
{bullets_text}

CTA:
{cta}

🎛️ REQUIRED LAYOUT VARIANT {variant}:
- Variant A: Left text column, right hero product (large), CTA under bullets
- Variant B: Top hero product, below: text block + bullets, left-aligned CTA
- Variant C: Split card - top headline/subheadline, mid bullets, bottom hero+CTA
- Variant D: Bold headline top, bullets mid-left, hero mid-right, bottom-left CTA

❌ FIX THESE SPECIFIC ISSUES:
{issues}

{mode_block}

MANDATORY REQUIREMENTS:
- Typography must be razor-sharp and sized for 1080×1350
- Use strict grid system with generous margins
- Subtle depth only (no plastic gradients, sparkles, cheap bevels)
- Professional color palette (avoid neon/oversaturated)
- Mobile-first readability

FORMAT: 1080×1350 portrait

REGENERATE THE IMAGE NOW (don't give feedback, just create the improved image)
""".strip()

def build_final_render_prompt(copy_lock: Dict[str, Any], variant: str) -> str:
    """Build final polish render prompt (no evaluation after this)"""
    
    headline = copy_lock.get("headline", "").strip()
    subheadline = copy_lock.get("subheadline", "").strip()
    bullets = copy_lock.get("bullets", [])
    cta = copy_lock.get("cta", "").strip()
    
    bullets_text = "\n".join([f"- {b}" for b in bullets]) if bullets else ""
    
    return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ FINAL DOWNLOAD RENDER (Production-Ready Polish)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

USE THIS EXACT COPY:

HEADLINE:
{headline}

SUBHEADLINE:
{subheadline}

BULLETS:
{bullets_text}

CTA:
{cta}

🎛️ LAYOUT VARIANT {variant}

GOAL:
Render the FINAL polished, production-ready image for download.

MICRO-POLISH ONLY:
- Perfect kerning and letter-spacing
- Pixel-perfect alignment
- Optimal contrast and readability
- Razor-sharp edges
- Professional spacing and margins
- Zero template vibes

Do NOT add new elements or change copy.

FORMAT: 1080×1350 portrait, ready for download
""".strip()

# =========================================================================================
# S3 & LOGO UTILITIES
# =========================================================================================
def fetch_logo_from_s3(user_id: str, business_context: Dict[str, Any]) -> Optional[bytes]:
    """
    Fetch user's logo from S3
    
    Search strategy:
    1. Try explicit logo_s3_key from business context
    2. Try logo_url if it's an s3:// URL
    3. Search S3 for files matching user_id in logos/ prefix
    
    Returns logo bytes or None
    """
    if not LOGO_ENABLED or not s3 or not user_id:
        return None
    
    logger.info(f"🔍 Searching for logo for user: {user_id}")
    
    # Strategy 1: Explicit key
    logo_key = business_context.get("logo_s3_key")
    if logo_key:
        try:
            obj = s3.get_object(Bucket=S3_BUCKET_NAME, Key=logo_key)
            data = obj["Body"].read()
            if data and len(data) > 2000:
                logger.info(f"✅ Logo found via explicit key: {logo_key}")
                return data
        except Exception as e:
            logger.debug(f"Logo not found at explicit key {logo_key}: {e}")
    
    # Strategy 2: Parse s3:// URL
    logo_url = business_context.get("logo_url", "")
    if logo_url.startswith("s3://"):
        try:
            # Parse s3://bucket/key
            parts = logo_url.replace("s3://", "").split("/", 1)
            bucket = parts[0]
            key = parts[1] if len(parts) > 1 else ""
            
            if bucket == S3_BUCKET_NAME and key:
                obj = s3.get_object(Bucket=bucket, Key=key)
                data = obj["Body"].read()
                if data and len(data) > 2000:
                    logger.info(f"✅ Logo found via s3:// URL: {key}")
                    return data
        except Exception as e:
            logger.debug(f"Logo not found via s3:// URL: {e}")
    
    # Strategy 3: Search by user_id
    sanitized_id = user_id.replace(" ", "_").replace("/", "_")
    search_prefix = f"{S3_LOGO_PREFIX}/{sanitized_id}"
    
    try:
        response = s3.list_objects_v2(
            Bucket=S3_BUCKET_NAME,
            Prefix=search_prefix,
            MaxKeys=10
        )
        
        candidates = []
        for item in response.get("Contents", []):
            key = item["Key"]
            ext = os.path.splitext(key)[1].lower()
            
            if ext in [".png", ".jpg", ".jpeg", ".webp"]:
                modified = item.get("LastModified")
                candidates.append((key, modified))
        
        if candidates:
            # Get most recent
            candidates.sort(key=lambda x: x[1], reverse=True)
            newest_key = candidates[0][0]
            
            obj = s3.get_object(Bucket=S3_BUCKET_NAME, Key=newest_key)
            data = obj["Body"].read()
            if data and len(data) > 2000:
                logger.info(f"✅ Logo found via search: {newest_key}")
                return data
                
    except Exception as e:
        logger.debug(f"Logo search failed: {e}")
    
    logger.info("⚠️ No logo found in S3")
    return None

def overlay_logo_on_image(base_img_bytes: bytes, logo_bytes: bytes) -> bytes:
    """
    Overlay logo on base image (top-right corner with shadow)
    
    Args:
        base_img_bytes: Main image PNG bytes
        logo_bytes: Logo image bytes (any format)
        
    Returns:
        Combined image as PNG bytes
    """
    try:
        # Load images
        base = Image.open(BytesIO(base_img_bytes)).convert("RGBA")
        logo = Image.open(BytesIO(logo_bytes)).convert("RGBA")
        
        # Remove white background from logo
        logo_data = logo.load()
        for y in range(logo.size[1]):
            for x in range(logo.size[0]):
                r, g, b, a = logo_data[x, y]
                # Make white/light pixels transparent
                if r > 240 and g > 240 and b > 240:
                    logo_data[x, y] = (r, g, b, 0)
                elif r > 220 and g > 220 and b > 220:
                    # Semi-transparent for near-white
                    logo_data[x, y] = (r, g, b, a // 2)
        
        # Resize logo to fit constraints
        base_w, base_h = base.size
        logo_w, logo_h = logo.size
        
        scale = min(
            LOGO_MAX_W / max(1, logo_w),
            LOGO_MAX_H / max(1, logo_h),
            1.0  # Don't upscale
        )
        
        new_w = max(1, int(logo_w * scale))
        new_h = max(1, int(logo_h * scale))
        
        if (new_w, new_h) != (logo_w, logo_h):
            logo = logo.resize((new_w, new_h), Image.LANCZOS)
        
        # Apply opacity
        if logo.mode == "RGBA":
            r, g, b, a = logo.split()
            # Apply opacity but keep some minimum
            a = a.point(lambda p: 0 if p < LOGO_MIN_ALPHA else int(p * LOGO_OPACITY))
            logo = Image.merge("RGBA", (r, g, b, a))
        
        # Position (top-right with padding)
        pos_x = max(0, base_w - logo.size[0] - LOGO_PADDING)
        pos_y = max(0, LOGO_PADDING)
        
        # Create subtle shadow
        shadow_alpha = logo.split()[3].filter(ImageFilter.GaussianBlur(radius=2))
        shadow = Image.new("RGBA", logo.size, (0, 0, 0, 0))
        shadow.putalpha(shadow_alpha)
        
        # Composite: shadow first, then logo
        base.alpha_composite(shadow, dest=(pos_x + 2, pos_y + 2))
        base.alpha_composite(logo, dest=(pos_x, pos_y))
        
        # Convert to RGB and save as PNG
        output = BytesIO()
        base.convert("RGB").save(output, format="PNG", optimize=True)
        
        logger.info("✅ Logo overlay complete")
        return output.getvalue()
        
    except Exception as e:
        logger.warning(f"⚠️ Logo overlay failed: {e}")
        return base_img_bytes

def upload_image_to_s3(
    img_bytes: bytes,
    user_id: str,
    slide_idx: int,
    theme: Optional[str] = None
) -> str:
    """
    Upload image to S3 and optionally log to DynamoDB
    
    Returns public URL or presigned URL
    """
    if not s3:
        raise RuntimeError("S3 not initialized")
    
    # Generate S3 key
    sanitized_id = user_id.replace(" ", "_").replace("/", "_")
    key = f"{S3_IMAGE_PREFIX}/slide_{sanitized_id}_{slide_idx}_{uuid.uuid4().hex}.png"
    
    # Upload
    extra_args = {"ContentType": "image/png"}
    if S3_PUBLIC_READ:
        extra_args["ACL"] = "public-read"
    
    s3.upload_fileobj(BytesIO(img_bytes), S3_BUCKET_NAME, key, ExtraArgs=extra_args)
    
    # Generate URL
    if S3_CDN_BASE_URL:
        url = f"{S3_CDN_BASE_URL}/{key}"
    elif S3_PUBLIC_READ:
        url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{key}"
    else:
        url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": S3_BUCKET_NAME, "Key": key},
            ExpiresIn=7 * 24 * 3600
        )
    
    # Log to DynamoDB
    if assets_table:
        try:
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            assets_table.put_item(Item={
                "userId": user_id,
                "createdAt": now_iso + "#" + uuid.uuid4().hex,
                "assetId": uuid.uuid4().hex,
                "type": "image",
                "s3Key": key,
                "cdnUrl": url,
                "bucket": S3_BUCKET_NAME,
                "region": AWS_REGION,
                "theme": theme or "",
                "slideIndex": slide_idx,
                "format": "png"
            })
        except Exception as e:
            logger.warning(f"⚠️ DynamoDB logging failed: {e}")
    
    logger.info(f"✅ Image uploaded: {key}")
    return url

def create_pdf_from_images(image_bytes_list: List[bytes]) -> bytes:
    """Combine multiple images into a single PDF"""
    if not image_bytes_list:
        raise RuntimeError("No images provided for PDF")
    
    pil_images = []
    for img_bytes in image_bytes_list:
        img = Image.open(BytesIO(img_bytes)).convert("RGB")
        pil_images.append(img)
    
    output = BytesIO()
    first = pil_images[0]
    rest = pil_images[1:] if len(pil_images) > 1 else []
    
    first.save(output, format="PDF", save_all=True, append_images=rest)
    
    logger.info(f"✅ PDF created ({len(pil_images)} pages)")
    return output.getvalue()

def upload_pdf_to_s3(pdf_bytes: bytes, user_id: str, theme: Optional[str] = None) -> str:
    """Upload PDF to S3 and optionally log to DynamoDB"""
    if not s3:
        raise RuntimeError("S3 not initialized")
    
    sanitized_id = user_id.replace(" ", "_").replace("/", "_")
    key = f"{S3_PDF_PREFIX}/slides_{sanitized_id}_{uuid.uuid4().hex}.pdf"
    
    extra_args = {"ContentType": "application/pdf"}
    if S3_PUBLIC_READ:
        extra_args["ACL"] = "public-read"
    
    s3.upload_fileobj(BytesIO(pdf_bytes), S3_BUCKET_NAME, key, ExtraArgs=extra_args)
    
    if S3_CDN_BASE_URL:
        url = f"{S3_CDN_BASE_URL}/{key}"
    elif S3_PUBLIC_READ:
        url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{key}"
    else:
        url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": S3_BUCKET_NAME, "Key": key},
            ExpiresIn=7 * 24 * 3600
        )
    
    # Log to DynamoDB
    if assets_table:
        try:
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            assets_table.put_item(Item={
                "userId": user_id,
                "createdAt": now_iso + "#" + uuid.uuid4().hex,
                "assetId": uuid.uuid4().hex,
                "type": "pdf",
                "s3Key": key,
                "cdnUrl": url,
                "bucket": S3_BUCKET_NAME,
                "region": AWS_REGION,
                "theme": theme or "",
                "format": "pdf"
            })
        except Exception as e:
            logger.warning(f"⚠️ DynamoDB logging failed: {e}")
    
    logger.info(f"✅ PDF uploaded: {key}")
    return url

# =========================================================================================
# CONTENT LOADING
# =========================================================================================
def load_content_details(path: str = "content_details.json") -> Dict[str, Any]:
    """Load content details from JSON file"""
    try:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Content details not found: {path}")
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        logger.info(f"✅ Loaded content details from {path}")
        return data
        
    except Exception as e:
        logger.error(f"❌ Failed to load content details: {e}")
        raise

def get_user_business_data(user_id: str) -> Dict[str, Any]:
    """Fetch user business data from DynamoDB"""
    if not user_survey_table or not user_id:
        return {}
    
    try:
        response = user_survey_table.query(
            KeyConditionExpression=Key("userId").eq(user_id),
            ScanIndexForward=False,
            Limit=1
        )
        
        if not response.get("Items"):
            return {}
        
        item = response["Items"][0]
        
        # Handle nested answers structure
        answers = item.get("answers", {})
        if not isinstance(answers, dict):
            answers = item
        
        return {
            "company_name": answers.get("company_name") or answers.get("brand_name") or user_id,
            "brand_colors": answers.get("brand_colors") or answers.get("color_theme"),
            "tone": answers.get("tone", "professional"),
            "website": answers.get("website") or answers.get("website_url"),
            "business_type": answers.get("business_type", "general"),
            "logo_s3_key": answers.get("logo_s3_key") or answers.get("logoKey"),
            "logo_url": answers.get("logo_url") or answers.get("logoUrl"),
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to fetch business data for {user_id}: {e}")
        return {}

# =========================================================================================
# MAIN IMAGE GENERATOR CLASS
# =========================================================================================
class ImageGenerator:
    """
    Production-ready image generator with ChatGPT Desktop automation
    
    Features:
    - Iterative quality improvement (generate → evaluate → regenerate)
    - COPY LOCK system (fixed text throughout iterations)
    - Layout variants (A/B/C/D) for visual diversity
    - Logo overlay
    - S3 upload with DynamoDB tracking
    - PDF generation
    """
    
    def __init__(self):
        self.max_iterations = IMG_MAX_ITERS
        self.fast_target_iters = IMG_FAST_TARGET_ITERS
        self.score_threshold = IMG_SCORE_THRESHOLD
        self.patience = IMG_PATIENCE
        
        logger.info(f"✅ ImageGenerator initialized")
        logger.info(f"   Threshold: {self.score_threshold}/10")
        logger.info(f"   Max iterations: {self.max_iterations}")
        logger.info(f"   Patience: {self.patience}")
    
    def generate_images(
        self,
        theme: str,
        content_type: str,
        num_images: int,
        subtopics: List[Dict[str, str]],
        user_id: Optional[str] = None,
        business_context: Optional[Dict[str, Any]] = None,
        user_image_prompt: Optional[str] = None,
        create_pdf: bool = True,
        **kwargs
    ) -> List[str]:
        """
        Main workflow: Generate high-quality images using ChatGPT Desktop
        
        Args:
            theme: Campaign theme
            content_type: Type of content (carousel, etc.)
            num_images: Number of images to generate
            subtopics: List of slide data (unused, loaded from content_details.json)
            user_id: User ID for S3 organization and logo lookup
            business_context: Business info (company, colors, tone, etc.)
            user_image_prompt: Optional custom instructions from user
            create_pdf: Whether to create PDF from all images
            
        Returns:
            List of S3 URLs (images + optional PDF)
        """
        
        logger.info("\n" + "=" * 100)
        logger.info("🚀 IMAGE GENERATION WORKFLOW - CHATGPT DESKTOP AUTOMATION")
        logger.info("=" * 100)
        logger.info(f"📊 Target: {num_images} images | Theme: '{theme}'")
        logger.info(f"⚙️  Quality threshold: {self.score_threshold}/10")
        logger.info(f"🔄 Max iterations per image: {self.max_iterations}")
        logger.info("=" * 100)
        
        # Load content details
        try:
            content_details = load_content_details()
        except Exception as e:
            logger.error(f"❌ Cannot proceed without content_details.json: {e}")
            return []
        
        # Get business context
        if not business_context:
            business_context = content_details.get("business_context", {})
            if not business_context and user_id:
                logger.info(f"📋 Fetching business data from DynamoDB...")
                business_context = get_user_business_data(user_id)
        
        if not business_context:
            business_context = {}
        
        # Extract business info
        company = business_context.get("company_name", user_id or "Brand")
        tone = business_context.get("tone", "professional")
        brand_colors = business_context.get("brand_colors")
        website = business_context.get("website")
        
        logger.info(f"🏢 Company: {company}")
        logger.info(f"🎨 Brand colors: {brand_colors or 'Not specified'}")
        logger.info(f"📝 Tone: {tone}")
        
        # Get slides
        slides = content_details.get("slide_contents", {})
        if not isinstance(slides, dict):
            logger.error("❌ Invalid slide_contents format in content_details.json")
            return []
        
        # Get user custom instructions
        custom_instructions = user_image_prompt or content_details.get("user_image_prompt", "")
        
        # Fetch logo
        logo_bytes = None
        if LOGO_ENABLED and user_id:
            logger.info("🔍 Searching for logo in S3...")
            logo_bytes = fetch_logo_from_s3(user_id, business_context)
            if logo_bytes:
                logger.info("✅ Logo loaded, will overlay on images")
            else:
                logger.info("⚠️  No logo found, images will be uploaded without logo")
        
        # Results
        image_urls: List[str] = []
        final_images_for_pdf: List[bytes] = []
        
        try:
            # Process each slide
            for idx in range(1, num_images + 1):
                slide_key = f"slide_{idx}"
                slide_data = slides.get(slide_key, {})
                
                if not slide_data or not isinstance(slide_data, dict):
                    logger.warning(f"⚠️  No data for {slide_key}, skipping")
                    continue
                
                # Extract slide content
                slide_title = slide_data.get("title", f"Slide {idx}")
                slide_body = slide_data.get("body", [])
                
                if isinstance(slide_body, list):
                    slide_points = "\n".join([f"- {point}" for point in slide_body])
                else:
                    slide_points = str(slide_body)
                
                logger.info("\n" + "=" * 100)
                logger.info(f"🎯 PROCESSING SLIDE {idx}/{num_images}: {slide_title}")
                logger.info("=" * 100)
                
                # ================================================================
                # STEP 1: Generate READY-TO-POST prompt
                # ================================================================
                logger.info("\n📝 STEP 1: Generating READY-TO-POST prompt...")
                
                step1_prompt = build_step1_prompt(
                    slide_idx=idx,
                    company=company,
                    tone=tone,
                    brand_colors=brand_colors,
                    website=website,
                    theme=theme,
                    slide_title=slide_title,
                    slide_points=slide_points,
                    user_custom_instructions=custom_instructions
                )
                
                step1_response = call_chatgpt_text(step1_prompt, timeout=TEXT_RESPONSE_TIMEOUT)
                
                # Validate and repair if needed
                repair_attempts = 0
                while not is_ready_prompt_valid(step1_response) and repair_attempts < 2:
                    repair_attempts += 1
                    logger.warning(f"⚠️  STEP 1 response invalid (repair attempt {repair_attempts}/2)")
                    logger.debug(f"Invalid response preview: {step1_response[:200]}...")
                    
                    step1_response = call_chatgpt_text(
                        build_repair_message(),
                        timeout=TEXT_RESPONSE_TIMEOUT
                    )
                
                if not is_ready_prompt_valid(step1_response):
                    logger.error(f"❌ STEP 1 failed for slide {idx} after repair attempts")
                    logger.debug(f"Final invalid response: {step1_response[:500]}...")
                    continue
                
                # Extract copy lock
                copy_lock = extract_copy_lock(step1_response)
                
                if not copy_lock.get("headline"):
                    logger.error(f"❌ Failed to extract copy lock for slide {idx}")
                    continue
                
                logger.info(f"✅ STEP 1 complete")
                logger.info(f"🔒 COPY LOCK extracted:")
                logger.info(f"   Headline: {copy_lock['headline'][:60]}...")
                logger.info(f"   Subheadline: {copy_lock['subheadline'][:60]}...")
                logger.info(f"   Bullets: {len(copy_lock.get('bullets', []))} items")
                logger.info(f"   CTA: {copy_lock['cta']}")
                
                # ================================================================
                # ITERATION LOOP: Generate → Evaluate → Regenerate
                # ================================================================
                best_score = 0.0
                last_score = 0.0
                last_eval_text = ""
                no_improve_count = 0
                
                attempt = 1
                threshold_hit = False
                
                loop_start_time = time.time()
                
                while attempt <= self.max_iterations:
                    # Check time limit
                    if time.time() - loop_start_time > IMG_MAX_TIME_SEC:
                        logger.warning(f"⏱️  Max time limit reached ({IMG_MAX_TIME_SEC}s)")
                        break
                    
                    logger.info(f"\n{'─' * 80}")
                    logger.info(f"🔄 ATTEMPT {attempt}/{self.max_iterations}")
                    logger.info(f"{'─' * 80}")
                    
                    # ============================================================
                    # STEP 2: Generate image
                    # ============================================================
                    if attempt == 1:
                        # Initial generation from READY prompt
                        img_prompt = "Generate the image from the READY-TO-POST prompt above. Format: 1080×1350 portrait."
                        logger.info("🎨 Generating initial image...")
                    else:
                        # Regeneration with feedback
                        issues = extract_issues(last_eval_text)
                        variant = layout_variant_for_attempt(attempt)
                        aggressive = attempt <= self.fast_target_iters
                        
                        logger.info(f"🎨 Regenerating with layout variant {variant} ({'aggressive' if aggressive else 'polish'} mode)...")
                        
                        img_prompt = build_regen_prompt(
                            issues=issues,
                            attempt_num=attempt,
                            previous_score=last_score,
                            copy_lock=copy_lock,
                            variant=variant,
                            aggressive=aggressive
                        )
                    
                    call_chatgpt_image(img_prompt, timeout=IMAGE_GENERATION_TIMEOUT)
                    
                    # ============================================================
                    # STEP 3: Evaluate image
                    # ============================================================
                    logger.info("📊 Evaluating image quality...")
                    
                    eval_prompt = build_eval_prompt(attempt)
                    eval_response = call_chatgpt_text(eval_prompt, timeout=TEXT_RESPONSE_TIMEOUT)
                    
                    last_score = parse_score(eval_response)
                    last_eval_text = eval_response
                    
                    logger.info(f"📈 Score: {last_score:.1f}/10 (best: {best_score:.1f}/10, target: {self.score_threshold:.1f}/10)")
                    
                    if DEBUG_MODE:
                        issues_preview = extract_issues(eval_response)[:200]
                        logger.debug(f"Issues: {issues_preview}...")
                    
                    # Track improvement
                    if last_score > best_score:
                        best_score = last_score
                        no_improve_count = 0
                        logger.info(f"✨ New best score: {best_score:.1f}/10")
                    else:
                        no_improve_count += 1
                        logger.info(f"⚠️  No improvement ({no_improve_count}/{self.patience})")
                    
                    # Check threshold
                    if last_score >= self.score_threshold:
                        logger.info(f"🎉 THRESHOLD REACHED: {last_score:.1f}/10 >= {self.score_threshold:.1f}/10")
                        threshold_hit = True
                        break
                    
                    # Check plateau
                    if no_improve_count >= self.patience:
                        logger.warning(f"⚠️  Plateau detected (no improvement for {no_improve_count} attempts)")
                        break
                    
                    attempt += 1
                
                # ================================================================
                # FINAL: Polish render and download
                # ================================================================
                if not threshold_hit:
                    logger.warning(f"❌ Skipping slide {idx}: best score {best_score:.1f} < threshold {self.score_threshold:.1f}")
                    continue
                
                logger.info("\n✨ Rendering final polished version...")
                
                final_variant = layout_variant_for_attempt(attempt + 1)
                final_prompt = build_final_render_prompt(copy_lock, final_variant)
                
                call_chatgpt_image(final_prompt, timeout=IMAGE_GENERATION_TIMEOUT)
                
                logger.info("📥 Downloading image...")
                
                # Download with retries
                local_path = None
                download_error = None
                
                for retry in range(1, DOWNLOAD_RETRIES + 1):
                    try:
                        local_path = download_generated_image(timeout=DOWNLOAD_TIMEOUT)
                        break
                    except Exception as e:
                        download_error = e
                        logger.warning(f"⚠️  Download attempt {retry}/{DOWNLOAD_RETRIES} failed: {e}")
                        if retry < DOWNLOAD_RETRIES:
                            time.sleep(2)
                
                if not local_path:
                    logger.error(f"❌ Download failed after {DOWNLOAD_RETRIES} retries: {download_error}")
                    continue
                
                # Read image bytes
                try:
                    with open(local_path, "rb") as f:
                        img_bytes = f.read()
                except Exception as e:
                    logger.error(f"❌ Failed to read downloaded image: {e}")
                    continue
                
                # Overlay logo if available
                if logo_bytes:
                    logger.info("🧷 Overlaying logo...")
                    img_bytes = overlay_logo_on_image(img_bytes, logo_bytes)
                
                # Upload to S3
                logger.info("☁️  Uploading to S3...")
                try:
                    s3_url = upload_image_to_s3(
                        img_bytes,
                        user_id=user_id or "anonymous",
                        slide_idx=idx,
                        theme=theme
                    )
                    
                    image_urls.append(s3_url)
                    final_images_for_pdf.append(img_bytes)
                    
                except Exception as e:
                    logger.error(f"❌ S3 upload failed: {e}")
                    continue
                
                # Clean up local file
                try:
                    os.remove(local_path)
                except:
                    pass
                
                logger.info(f"\n✅ SLIDE {idx} COMPLETE")
                logger.info(f"   Final score: {best_score:.1f}/10")
                logger.info(f"   Attempts: {attempt}")
                logger.info(f"   URL: {s3_url}")
            
            # ================================================================
            # Create PDF from all images
            # ================================================================
            if create_pdf and final_images_for_pdf:
                logger.info("\n" + "=" * 100)
                logger.info("📄 Creating PDF from all images...")
                
                try:
                    pdf_bytes = create_pdf_from_images(final_images_for_pdf)
                    pdf_url = upload_pdf_to_s3(
                        pdf_bytes,
                        user_id=user_id or "anonymous",
                        theme=theme
                    )
                    
                    image_urls.append(pdf_url)
                    logger.info(f"✅ PDF created and uploaded: {pdf_url}")
                    
                except Exception as e:
                    logger.warning(f"⚠️  PDF creation failed: {e}")
            
            # ================================================================
            # Summary
            # ================================================================
            logger.info("\n" + "=" * 100)
            logger.info(f"🎉 WORKFLOW COMPLETE")
            logger.info("=" * 100)
            logger.info(f"✅ Successfully generated: {len(final_images_for_pdf)} images")
            logger.info(f"📦 Total assets (images + PDF): {len(image_urls)}")
            logger.info(f"⏱️  Total time: {time.time() - loop_start_time:.1f}s")
            logger.info("=" * 100)
            
            return image_urls
            
        except Exception as e:
            logger.error(f"\n❌ FATAL ERROR: {e}")
            logger.error(traceback.format_exc())
            return []
        
        finally:
            # Clean up ChatGPT connection
            try:
                bridge = get_bridge()
                bridge.close()
            except:
                pass

# =========================================================================================
# CLI TESTING
# =========================================================================================
if __name__ == "__main__":
    """
    Test the image generator from command line
    
    Usage:
        python image_generator.py
    
    Make sure you have:
    1. content_details.json in the same directory
    2. .env file with all required variables
    3. ChatGPT Desktop app installed
    """
    
    logger.info("🧪 Running image generator test...")
    
    # Create generator
    generator = ImageGenerator()
    
    # Test with minimal config
    results = generator.generate_images(
        theme="Test Theme",
        content_type="carousel",
        num_images=2,  # Start with just 2 for testing
        subtopics=[],  # Will load from content_details.json
        user_id="test_user_123",
        create_pdf=True
    )
    
    # Print results
    print("\n" + "=" * 100)
    print("TEST RESULTS")
    print("=" * 100)
    print(f"Generated {len(results)} assets:")
    for i, url in enumerate(results, 1):
        print(f"  {i}. {url}")
    print("=" * 100)