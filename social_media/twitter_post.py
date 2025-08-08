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

def extract_hashtags_from_caption(caption):
    """Extract hashtags from the original caption"""
    if not caption:
        return []
    
    # Find all hashtags in the caption
    hashtags = re.findall(r'#\w+', caption)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_hashtags = []
    for tag in hashtags:
        if tag.lower() not in seen:
            unique_hashtags.append(tag)
            seen.add(tag.lower())
    
    return unique_hashtags

def create_twitter_optimized_caption(full_caption):
    """Create Twitter-optimized caption under 280 characters with complete sentences"""
    if not full_caption:
        return "Check out this AI-generated content! #AI #Technology"
    
    # Extract hashtags from original caption
    original_hashtags = extract_hashtags_from_caption(full_caption)
    
    # Remove hashtags from text to get clean content
    clean_text = re.sub(r'#\w+', '', full_caption)
    
    # Remove emojis and special characters that cause issues
    clean_text = re.sub(r'[^\x00-\x7F\u00A0-\u00FF\u0100-\u017F\u0180-\u024F]', '', clean_text)
    
    # Clean up extra spaces and newlines
    clean_text = ' '.join(clean_text.split())
    
    # Select the best hashtags (max 5 for Twitter)
    if original_hashtags:
        # Prefer shorter hashtags and more relevant ones
        selected_hashtags = []
        priority_keywords = ['AI', 'Tech', 'Innovation', 'Automation', 'Data', 'ML', 'Science', 'Aerospace', 'Aviation']
        
        # First add priority hashtags
        for hashtag in original_hashtags:
            for keyword in priority_keywords:
                if keyword.lower() in hashtag.lower() and hashtag not in selected_hashtags:
                    selected_hashtags.append(hashtag)
                    break
        
        # Then add other hashtags up to 5 total
        for hashtag in original_hashtags:
            if hashtag not in selected_hashtags and len(selected_hashtags) < 5:
                selected_hashtags.append(hashtag)
        
        hashtag_string = ' ' + ' '.join(selected_hashtags[:5])
    else:
        # Fallback hashtags
        hashtag_string = ' #AI #Technology #Innovation'
    
    # Calculate available space for text
    max_text_length = 280 - len(hashtag_string)
    
    # If text fits, use it as is
    if len(clean_text) <= max_text_length:
        return clean_text + hashtag_string
    
    # Try to fit complete sentences
    sentences = clean_text.split('.')
    fitted_text = ""
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
            
        potential_text = fitted_text + (" " if fitted_text else "") + sentence + "."
        
        if len(potential_text) <= max_text_length:
            fitted_text = potential_text
        else:
            break
    
    # If we got at least one complete sentence, use it
    if fitted_text.strip():
        return fitted_text.strip() + hashtag_string
    
    # If no complete sentence fits, create a summary from key phrases
    # Extract the most important phrases (first part of each sentence)
    key_phrases = []
    for sentence in sentences[:3]:  # Look at first 3 sentences
        sentence = sentence.strip()
        if sentence:
            # Take the main clause (before any commas or semicolons)
            main_clause = sentence.split(',')[0].split(';')[0].strip()
            if len(main_clause) > 10:  # Only meaningful phrases
                key_phrases.append(main_clause)
    
    # Combine key phrases into a coherent summary
    if key_phrases:
        summary = key_phrases[0]  # Start with the first key phrase
        
        for phrase in key_phrases[1:]:
            potential_summary = summary + ", " + phrase.lower()
            if len(potential_summary) <= max_text_length - 20:  # Leave room for proper ending
                summary = potential_summary
            else:
                break
        
        # Add a proper ending
        if not summary.endswith('.'):
            summary += "."
            
        if len(summary) <= max_text_length:
            return summary + hashtag_string
    
    # Final fallback: Take first meaningful words and make a complete sentence
    words = clean_text.split()
    summary_words = []
    
    for word in words[:20]:  # Look at first 20 words
        potential_length = len(' '.join(summary_words + [word])) + len(hashtag_string) + 1
        if potential_length < 280:
            summary_words.append(word)
        else:
            break
    
    if summary_words:
        summary = ' '.join(summary_words)
        # Ensure it ends properly
        if not summary.endswith('.'):
            summary += "."
        return summary + hashtag_string
    
    # Ultimate fallback
    return "AI-powered content automation in action!" + hashtag_string

def clean_caption_for_selenium(caption):
    """Enhanced caption cleaning with Twitter optimization - no truncation dots"""
    if not caption:
        return "Check out this AI content! #AI #MachineLearning #DataScience"
    
    # Use the Twitter optimizer
    twitter_optimized = create_twitter_optimized_caption(caption)
    
    # Additional safety cleaning for ChromeDriver
    # Remove any remaining problematic characters
    cleaned = re.sub(r'[^\x00-\x7F\u00A0-\u00FF\u0100-\u017F\u0180-\u024F]', '', twitter_optimized)
    cleaned = ' '.join(cleaned.split())  # Remove extra whitespace
    
    # Ensure we have some content
    if len(cleaned.strip()) < 10:
        cleaned = "AI-powered content automation in action! #AI #Technology #Automation"
    
    # Final length check - create proper sentence if too long
    if len(cleaned) > 280:
        words = cleaned.split()
        # Find a good cutoff point
        for i in range(len(words)-1, 0, -1):
            test_text = ' '.join(words[:i])
            if len(test_text) <= 270 and not test_text.endswith('#'):
                # Make sure it ends properly
                if not test_text.endswith('.'):
                    test_text += "."
                # Add one hashtag if space allows
                if len(test_text) <= 275:
                    test_text += " #AI"
                cleaned = test_text
                break
    
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

def post_to_twitter_selenium_main(caption="", max_attempts=2):
    """Main Twitter posting function with robust error handling"""
    
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

# Legacy compatibility functions for your existing system
def post_image_to_twitter(image_url, access_token, access_token_secret, consumer_key, consumer_secret):
    """Legacy function for compatibility with old system calls"""
    return post_content_to_twitter(image_urls=[image_url], caption="Check out this AI-generated content! #AI #Automation")

def post_content_to_twitter(image_urls=None, caption="", num_images=1):
    """Main integration function that your lambda_function.py calls"""
    try:
        logger.info(f"🐦 Twitter posting requested with caption: '{caption[:50]}...'")
        success = post_to_twitter_selenium_main(caption)
        
        if success:
            logger.info("✅ Twitter posting completed successfully")
            return {"status": "success", "message": "Posted to Twitter with image and caption via Selenium automation"}
        else:
            logger.error("❌ Twitter posting failed")
            return {"status": "error", "message": "Failed to post to Twitter via Selenium automation"}
            
    except Exception as e:
        logger.error(f"❌ Error in post_content_to_twitter: {e}")
        return {"status": "error", "message": f"Twitter Selenium Error: {str(e)}"}

if __name__ == "__main__":
    # Test the implementation
    test_caption = """Testing the final Twitter automation system! This AI-powered tool automatically generates and posts content with images to social media platforms. Perfect for content marketing and social media management. #AI #Automation #TwitterBot #SocialMedia #ContentMarketing"""
    
    logger.info("🧪 Testing final Twitter implementation...")
    success = post_to_twitter_selenium_main(test_caption)
    
    if success:
        logger.info("🎉 SUCCESS! Check your Twitter account for the posted tweet.")
    else:
        logger.error("❌ Test failed. Check the logs above for details.")