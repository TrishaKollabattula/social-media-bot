import os
import time
import boto3
import requests
import tempfile
import logging
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clean_caption_for_selenium(caption):
    """Clean caption to avoid Unicode/BMP issues with ChromeDriver"""
    if not caption:
        return "Check out this AI content! #AI #MachineLearning #DataScience"
    
    # Remove emojis and non-BMP characters that cause ChromeDriver issues
    # Keep only basic ASCII + common symbols
    cleaned = re.sub(r'[^\x00-\x7F\u00A0-\u00FF\u0100-\u017F\u0180-\u024F]', '', caption)
    
    # Remove extra spaces
    cleaned = ' '.join(cleaned.split())
    
    # If too much was removed, provide fallback
    if len(cleaned.strip()) < len(caption) * 0.3:
        # Extract text content without emojis
        text_parts = []
        words = caption.split()
        for word in words:
            # Keep words that have at least some ASCII characters
            ascii_chars = ''.join(char for char in word if ord(char) < 128)
            if len(ascii_chars) > 1:  # Keep words with substantial ASCII content
                text_parts.append(ascii_chars)
        
        if text_parts:
            cleaned = ' '.join(text_parts[:15])  # Limit words to avoid being too long
        else:
            cleaned = "AI-powered content automation in action!"
    
    # Ensure we have hashtags
    if '#' not in cleaned:
        cleaned += " #AI #Technology #Automation"
    
    # Limit to Twitter's 280 character limit
    if len(cleaned) > 280:
        cleaned = cleaned[:270] + "..."
    
    return cleaned.strip()

def get_s3_image():
    """Get latest S3 image"""
    try:
        s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION"))
        bucket = os.getenv("S3_BUCKET_NAME")
        
        response = s3.list_objects_v2(Bucket=bucket, Prefix="images/")
        images = [obj for obj in response.get('Contents', []) 
                 if obj['Key'] != "images/" and obj['Key'].lower().endswith(('.jpg', '.jpeg', '.png'))]
        
        if images:
            latest = sorted(images, key=lambda x: x['LastModified'], reverse=True)[0]
            return f"https://{bucket}.s3.{os.getenv('AWS_REGION')}.amazonaws.com/{latest['Key']}"
        return None
    except Exception as e:
        logger.error(f"Error getting S3 image: {e}")
        return None

def wait_for_element(driver, selector, timeout=10, condition=EC.presence_of_element_located):
    """Wait for element with timeout"""
    try:
        element = WebDriverWait(driver, timeout).until(
            condition((By.CSS_SELECTOR, selector))
        )
        return element
    except TimeoutException:
        logger.warning(f"Timeout waiting for element: {selector}")
        return None

def safe_send_keys(element, text, max_attempts=3):
    """Safely send keys with multiple attempts to handle BMP issues"""
    
    for attempt in range(max_attempts):
        try:
            # Clear existing content
            element.clear()
            time.sleep(0.3)
            
            # Try to send keys
            element.send_keys(text)
            time.sleep(0.5)
            
            # Verify some text was entered
            current_value = element.get_attribute("value") or ""
            if len(current_value.strip()) > 0:
                logger.info(f"✅ Text entered successfully on attempt {attempt + 1}")
                return True
                
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} to send keys failed: {e}")
            time.sleep(0.5)
    
    return False

def set_tweet_text_robust(driver, tweet_element, text):
    """Set tweet text with multiple methods, handling Unicode issues"""
    
    logger.info(f"📝 Setting tweet text: '{text[:50]}...'")
    
    # Method 1: Try regular Selenium send_keys
    try:
        tweet_element.click()
        time.sleep(0.5)
        
        # Clear existing text
        tweet_element.send_keys(Keys.CONTROL + "a")
        time.sleep(0.3)
        tweet_element.send_keys(Keys.DELETE)
        time.sleep(0.3)
        
        # Type the text
        tweet_element.send_keys(text)
        time.sleep(1)
        
        # Verify text was entered
        current_text = driver.execute_script("""
            var element = arguments[0];
            return element.innerText || element.textContent || element.value || '';
        """, tweet_element)
        
        if len(current_text.strip()) > len(text) * 0.7:
            logger.info("✅ Method 1: Regular send_keys worked")
            return True
            
    except Exception as e:
        logger.info(f"Method 1 failed: {e}")
    
    # Method 2: JavaScript-based text setting (more reliable for Unicode)
    try:
        logger.info("📝 Trying JavaScript method...")
        
        success = driver.execute_script("""
            var element = arguments[0];
            var text = arguments[1];
            
            try {
                // Focus and clear
                element.focus();
                element.click();
                
                // Clear content multiple ways
                element.innerText = '';
                element.textContent = '';
                if (element.value !== undefined) {
                    element.value = '';
                }
                
                // Set new content
                element.innerText = text;
                element.textContent = text;
                if (element.value !== undefined) {
                    element.value = text;
                }
                
                // Trigger comprehensive events
                var events = ['input', 'change', 'keyup', 'keydown', 'compositionend'];
                events.forEach(function(eventType) {
                    try {
                        var event = new Event(eventType, {
                            bubbles: true,
                            cancelable: true
                        });
                        element.dispatchEvent(event);
                    } catch(e) {
                        // Ignore event errors
                    }
                });
                
                // Special InputEvent for modern frameworks
                try {
                    var inputEvent = new InputEvent('input', {
                        bubbles: true,
                        cancelable: true,
                        inputType: 'insertText',
                        data: text
                    });
                    element.dispatchEvent(inputEvent);
                } catch(e) {
                    // Fallback to simple input event
                    var simpleInput = new Event('input', {bubbles: true});
                    element.dispatchEvent(simpleInput);
                }
                
                // Keep focus
                element.focus();
                
                // Return success if text is set
                return (element.innerText && element.innerText.length > 0) || 
                       (element.textContent && element.textContent.length > 0) ||
                       (element.value && element.value.length > 0);
                       
            } catch(e) {
                return false;
            }
        """, tweet_element, text)
        
        if success:
            logger.info("✅ Method 2: JavaScript method worked")
            return True
            
    except Exception as e:
        logger.info(f"Method 2 failed: {e}")
    
    # Method 3: Character by character (slowest but most reliable)
    try:
        logger.info("📝 Trying character-by-character method...")
        
        tweet_element.click()
        time.sleep(0.5)
        
        # Clear
        tweet_element.send_keys(Keys.CONTROL + "a")
        tweet_element.send_keys(Keys.DELETE)
        time.sleep(0.5)
        
        # Type character by character, skipping problematic ones
        for char in text:
            try:
                if ord(char) < 127:  # Only ASCII characters
                    tweet_element.send_keys(char)
                    time.sleep(0.02)
                else:
                    # Skip non-ASCII characters that might cause issues
                    continue
            except:
                # Skip characters that cause issues
                continue
        
        time.sleep(1)
        
        # Check if we got some text
        current_text = driver.execute_script("""
            var element = arguments[0];
            return element.innerText || element.textContent || element.value || '';
        """, tweet_element)
        
        if len(current_text.strip()) > 5:  # At least some text
            logger.info("✅ Method 3: Character-by-character worked")
            return True
            
    except Exception as e:
        logger.info(f"Method 3 failed: {e}")
    
    logger.error("❌ All text-setting methods failed")
    return False

def upload_image_to_twitter(driver, image_path):
    """Upload image to Twitter"""
    
    logger.info("🖼️ Starting image upload...")
    
    # Try direct file input first
    file_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
    for file_input in file_inputs:
        try:
            # Make file input visible and interactable
            driver.execute_script("""
                arguments[0].style.display = 'block';
                arguments[0].style.visibility = 'visible';
                arguments[0].style.opacity = '1';
                arguments[0].style.position = 'relative';
            """, file_input)
            
            file_input.send_keys(image_path)
            time.sleep(6)
            
            # Check for image preview
            previews = driver.find_elements(By.CSS_SELECTOR, 
                '[data-testid="media"], img[src*="blob:"], [data-testid="attachments"] img, div[aria-label*="Image"]')
            
            if previews:
                logger.info(f"✅ Image uploaded successfully! Found {len(previews)} preview elements")
                return True
                
        except Exception as e:
            logger.info(f"Direct file input failed: {e}")
            continue
    
    # Try media button approach
    media_button_selectors = [
        'button[aria-label*="photo"]',
        'button[aria-label*="Add photos"]', 
        '[data-testid="attachments"] button',
        'div[aria-label*="Add photos"]'
    ]
    
    for selector in media_button_selectors:
        try:
            media_button = wait_for_element(driver, selector, timeout=5)
            if media_button:
                driver.execute_script("arguments[0].click();", media_button)
                time.sleep(3)
                
                # Now try file inputs again
                file_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
                for file_input in file_inputs:
                    try:
                        file_input.send_keys(image_path)
                        time.sleep(6)
                        
                        previews = driver.find_elements(By.CSS_SELECTOR, 
                            '[data-testid="media"], img[src*="blob:"]')
                        
                        if previews:
                            logger.info(f"✅ Image uploaded via media button! Found {len(previews)} previews")
                            return True
                    except Exception as e:
                        continue
                        
        except Exception as e:
            continue
    
    logger.error("❌ Image upload failed")
    return False

def post_to_twitter_selenium_fixed(caption="", max_attempts=2):
    """Fixed Twitter posting with Unicode handling"""
    
    for attempt in range(max_attempts):
        logger.info(f"🐦 Starting Twitter post attempt {attempt + 1}/{max_attempts}")
        
        # Get image
        image_url = get_s3_image()
        if not image_url:
            logger.error("❌ No S3 image found")
            return False
        
        # Download image
        try:
            response = requests.get(image_url, timeout=30)
            with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
                tmp.write(response.content)
                temp_path = tmp.name
            logger.info(f"📥 Image downloaded: {temp_path}")
        except Exception as e:
            logger.error(f"Failed to download image: {e}")
            return False
        
        # Clean caption for ChromeDriver compatibility
        clean_caption = clean_caption_for_selenium(caption)
        logger.info(f"📝 Cleaned caption: '{clean_caption}'")
        logger.info(f"📏 Caption length: {len(clean_caption)} characters")
        
        # Setup Chrome
        options = Options()
        chrome_profile = os.getenv('CHROME_PROFILE_PATH1')
        if chrome_profile:
            options.add_argument(f"--user-data-dir={chrome_profile}")
            options.add_argument("--profile-directory=Profile 2")
        
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        driver = None
        try:
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            logger.info("🌐 Opening Twitter...")
            driver.get("https://twitter.com/home")
            time.sleep(12)
            
            # Clear overlays
            for _ in range(3):
                try:
                    driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
                    time.sleep(1)
                except:
                    pass
            
            # Find tweet compose area
            tweet_box_selectors = [
                '[data-testid="tweetTextarea_0"]',
                '[role="textbox"]',
                'div[contenteditable="true"]'
            ]
            
            tweet_box = None
            for selector in tweet_box_selectors:
                tweet_box = wait_for_element(driver, selector, timeout=15)
                if tweet_box:
                    logger.info(f"✅ Found tweet box: {selector}")
                    break
            
            if not tweet_box:
                logger.error("❌ Could not find tweet compose area")
                continue
            
            # STEP 1: Set caption text
            logger.info("📝 Setting caption text...")
            if not set_tweet_text_robust(driver, tweet_box, clean_caption):
                logger.error("❌ Failed to set caption")
                continue
            
            # STEP 2: Upload image
            logger.info("🖼️ Uploading image...")
            if not upload_image_to_twitter(driver, temp_path):
                logger.error("❌ Failed to upload image")
                continue
            
            # STEP 3: Check if caption survived image upload
            time.sleep(3)
            current_text = driver.execute_script("""
                var elements = document.querySelectorAll('[data-testid="tweetTextarea_0"], [role="textbox"]');
                for (var i = 0; i < elements.length; i++) {
                    var text = elements[i].innerText || elements[i].textContent || elements[i].value || '';
                    if (text.length > 0) return text;
                }
                return '';
            """)
            
            logger.info(f"📝 Text after image upload: '{current_text[:50]}...'")
            
            # If caption is missing, re-enter it
            if len(current_text.strip()) < len(clean_caption) * 0.4:
                logger.warning("⚠️ Caption lost after image upload, re-entering...")
                
                # Find tweet box again
                for selector in tweet_box_selectors:
                    tweet_box = wait_for_element(driver, selector, timeout=5)
                    if tweet_box:
                        break
                
                if tweet_box:
                    set_tweet_text_robust(driver, tweet_box, clean_caption)
            
            # STEP 4: Post the tweet
            logger.info("🚀 Looking for post button...")
            
            post_button_selectors = [
                '[data-testid="tweetButtonInline"]',
                '[data-testid="tweetButton"]'
            ]
            
            posted = False
            for wait_time in range(20):  # Wait up to 20 seconds
                for selector in post_button_selectors:
                    try:
                        buttons = driver.find_elements(By.CSS_SELECTOR, selector)
                        for button in buttons:
                            if (not button.get_attribute("disabled") and 
                                button.is_displayed() and 
                                button.is_enabled()):
                                
                                logger.info(f"✅ Found enabled post button")
                                
                                # Click to post
                                driver.execute_script("arguments[0].click();", button)
                                logger.info("🚀 Tweet posted successfully!")
                                time.sleep(5)
                                posted = True
                                break
                    except:
                        continue
                
                if posted:
                    break
                time.sleep(1)
            
            if posted:
                logger.info("🎉 Twitter posting completed successfully!")
                return True
            else:
                logger.error("❌ Could not find or click post button")
                
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            
        finally:
            try:
                os.unlink(temp_path)
            except:
                pass
            
            if driver:
                time.sleep(5)
                driver.quit()
    
    logger.error(f"❌ All {max_attempts} attempts failed")
    return False

# Compatibility functions for your system
def post_image_to_twitter(image_url, access_token, access_token_secret, consumer_key, consumer_secret):
    """Legacy function for compatibility"""
    return post_content_to_twitter(image_urls=[image_url], caption="Check out this AI-generated content!")

def post_content_to_twitter(image_urls=None, caption="", num_images=1):
    """Integration function for your system"""
    try:
        success = post_to_twitter_selenium_fixed(caption)
        if success:
            return {"status": "success", "message": "Posted to Twitter with image and caption via Selenium"}
        else:
            return {"status": "error", "message": "Failed to post to Twitter via Selenium"}
    except Exception as e:
        logger.error(f"Error in post_content_to_twitter: {e}")
        return {"status": "error", "message": f"Selenium Error: {str(e)}"}

if __name__ == "__main__":
    # Test with a clean caption (no emojis that cause BMP issues)
    test_caption = """Testing Twitter automation with clean text! This system automatically posts AI-generated content with images. Perfect for social media automation and content marketing. #AI #Automation #TwitterBot #SocialMedia"""
    
    logger.info("🧪 Testing fixed Twitter Selenium implementation...")
    success = post_to_twitter_selenium_fixed(test_caption)
    
    if success:
        logger.info("🎉 SUCCESS! Check your Twitter account.")
    else:
        logger.error("❌ Failed. Check the logs above for details.")