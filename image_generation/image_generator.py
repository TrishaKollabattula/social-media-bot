from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import time
import requests
from PIL import Image
from io import BytesIO
import os
import logging
import uuid
import boto3
import re
from selenium.common.exceptions import WebDriverException, StaleElementReferenceException, TimeoutException, NoSuchElementException
from dotenv import load_dotenv
from reportlab.pdfgen import canvas
import tempfile

from .utils import content_type_styles, get_content_details

# Load environment variables
load_dotenv()
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
CHROME_PROFILE_PATH1 = os.getenv("CHROME_PROFILE_PATH1")
LOGO_PATH = "logo.png"  # Path to the logo file

# Validate environment variables
if not CHROME_PROFILE_PATH1:
    raise ValueError("CHROME_PROFILE_PATH environment variable not set.")
if not AWS_REGION or not S3_BUCKET_NAME:
    raise ValueError("AWS_REGION or S3_BUCKET_NAME environment variable not set.")
if not os.path.exists(LOGO_PATH):
    raise ValueError(f"Logo file not found at {LOGO_PATH}")

# Initialize S3 client
s3 = boto3.client("s3", region_name=AWS_REGION)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ImageGenerator:
    def __init__(self):
        self.max_iterations = 5  # Maximum feedback iterations per image
        self.score_threshold = 9  # Target score for image quality
        self.max_retries = 3    # Maximum retries for critical operations

    def generate_image_prompt(self, subtopic, content_type, style_idx, theme, include_footer=False):
        """
        Generate a dynamic image prompt based on content type and theme, ensuring full image generation.
        """
        title = subtopic["title"]
        details = subtopic["details"]
        style = content_type_styles[content_type]
        layout = style["layouts"][style_idx % len(style["layouts"])]
        prompt = (
            f"Generate a complete, high-quality image instantly: {style['action']} '{theme}' with a {layout} layout and {style['Spellings']}."
            f" Ensure the image is fully rendered, with no cut-off elements, partial rendering, or missing sections. "
            f" Use a {style['palette']}, a {style['font']}, and {style['theme_adjustment']}, and include {style['visual_elements']}."
            f" Incorporate the details: '{details}'."
            f"Ensure the image is dynamic, with smooth color gradients, intricate details, and deep texture layers that create a realistic feel. "
            f"Focus on natural lighting and shadows to enhance depth and dimension in the image. "
            f"Please generate this image as fast as possible but nicely, avoiding AI artifacts like unnatural gradients or perfect symmetry. "
            f"Instead, focus on organic textures and imperfections to give it a hand-crafted, realistic aesthetic. "
            f"Ensure that all elements align with the theme and are visually cohesive. image should be such a way that its score should be 9 when my feedback runs"
        )

        if include_footer:
            footer_text = "CraftingBrain 2025 | Call: 9115076096 | craftingbrain.com"
            prompt += (
                f" Add a footer to the generated image (do not generate a new image) with the text '{footer_text}' in white on a black strip, "
                f"with a yellow line above the footer. Ensure correct spelling and correct phone number that is call:9115076096"
            )

        return prompt

    def wait_for_image_generation(self, driver, timeout=400):
        """
        Wait for image generation to complete by checking for new images with extended timeout.
        """
        logging.info("Waiting for image generation to complete...")
        start_time = time.time()
        initial_images = driver.find_elements(By.TAG_NAME, "img")
        initial_count = len(initial_images)
        
        while time.time() - start_time < timeout:
            time.sleep(10)  # Reduced check interval for efficiency
            current_images = driver.find_elements(By.TAG_NAME, "img")
            current_count = len(current_images)
            
            if current_count > initial_count:
                logging.info("New image detected, waiting for full load...")
                time.sleep(45)  # Adjusted wait for full render
                try:
                    img = current_images[-1]
                    img_src = img.get_attribute("src")
                    if img_src and "data:image" not in img_src:
                        response = requests.head(img_src, timeout=10)
                        if response.status_code == 200 and img.size[0] > 200 and img.size[1] > 200:  # Stricter size check
                            logging.info("Image fully loaded and validated.")
                            return True
                except (Exception, requests.RequestException) as e:
                    logging.warning(f"Error validating image load: {e}")
            
            loading_indicators = driver.find_elements(By.XPATH, "//*[contains(@class, 'loading') or contains(@class, 'spinner') or contains(text(), 'Generating') or contains(text(), 'Creating')]")
            if not loading_indicators and current_count > 0:
                logging.info("Image generation complete (no loading indicators).")
                return True
                
            driver.refresh()
            time.sleep(10)
        
        logging.warning(f"Image generation timeout after {timeout} seconds.")
        return False

    def wait_for_send_button_ready(self, driver, timeout=60):
        """
        Wait for the send button to be ready and clickable.
        """
        try:
            send_button = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='send-button' or contains(@class, 'send') or @aria-label='Send message']"))
            )
            if send_button.get_attribute("disabled") is None:
                logging.info("Send button is ready and enabled.")
                return True
            logging.warning("Send button found but disabled.")
            return False
        except TimeoutException:
            logging.warning("Send button not found or not clickable within timeout.")
            return False

    def check_message_sent(self, driver, original_message_count):
        """
        Check if the message was sent by comparing message count.
        """
        try:
            time.sleep(3)  # Reduced wait for UI update
            current_messages = driver.find_elements(By.XPATH, "//div[contains(@class, 'message') or @data-message-author-role]")
            if len(current_messages) > original_message_count:
                logging.info("Message successfully sent.")
                return True
            logging.warning("Message may not have been sent.")
            return False
        except Exception as e:
            logging.warning(f"Could not verify message sent: {e}")
            return False

    def submit_prompt(self, driver, prompt, max_retries=5):
        """
        Submit a prompt to ChatGPT with enhanced retry mechanism.
        """
        for attempt in range(max_retries):
            try:
                initial_messages = driver.find_elements(By.XPATH, "//div[contains(@class, 'message') or @data-message-author-role]")
                initial_count = len(initial_messages)
                
                input_field = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.XPATH, "//div[@role='textbox' or @id='prompt-textarea']"))
                )
                logging.info("Input field located and clickable.")

                driver.execute_script("arguments[0].innerText = '';", input_field)
                driver.execute_script("arguments[0].click();", input_field)
                driver.execute_script("arguments[0].innerText = arguments[1];", input_field, prompt)
                
                if not self.wait_for_send_button_ready(driver):
                    logging.warning("Send button not ready, refreshing page...")
                    driver.refresh()
                    time.sleep(30)
                    input_field = WebDriverWait(driver, 30).until(
                        EC.element_to_be_clickable((By.XPATH, "//div[@role='textbox' or @id='prompt-textarea']"))
                    )
                    driver.execute_script("arguments[0].innerText = arguments[1];", input_field, prompt)
                    if not self.wait_for_send_button_ready(driver):
                        logging.error("Send button still not ready after refresh.")
                        continue
                
                input_field.send_keys(Keys.ENTER)
                logging.info("Prompt submitted via Enter key.")
                
                if self.check_message_sent(driver, initial_count):
                    logging.info("Prompt submission verified.")
                    time.sleep(5)  # Reduced delay
                    return True
                
                try:
                    send_button = driver.find_element(By.XPATH, "//button[@data-testid='send-button' or contains(@class, 'send') or @aria-label='Send message']")
                    if send_button.get_attribute("disabled") is None:
                        driver.execute_script("arguments[0].click();", send_button)
                        logging.info("Clicked send button directly.")
                        if self.check_message_sent(driver, initial_count):
                            logging.info("Message sent via button click.")
                            time.sleep(5)
                            return True
                except Exception as e:
                    logging.warning(f"Could not click send button: {e}")
                
            except (StaleElementReferenceException, NoSuchElementException, Exception) as e:
                logging.warning(f"Attempt {attempt + 1} failed: {e}")
                time.sleep(5)
                if attempt < max_retries - 1:
                    driver.refresh()
                    time.sleep(20)
                    try:
                        WebDriverWait(driver, 30).until(
                            EC.element_to_be_clickable((By.XPATH, "//div[@role='textbox' or @id='prompt-textarea']"))
                        )
                        logging.info("Page refreshed, input field ready.")
                    except TimeoutException:
                        logging.error("Input field not ready after refresh.")
                        continue
                        
        logging.error(f"Failed to submit prompt after {max_retries} attempts.")
        return False

    def download_image(self, img_src, max_retries=5):
        """
        Download an image from a URL with increased retries.
        """
        for attempt in range(max_retries):
            try:
                response = requests.get(img_src, timeout=15)
                if response.status_code == 200:
                    img = Image.open(BytesIO(response.content))
                    if img.size[0] > 200 and img.size[1] > 200:  # Stricter size check
                        logging.info("Image downloaded successfully.")
                        return response.content
                    logging.warning(f"Image too small, likely incomplete. Attempt {attempt + 1}/{max_retries}")
                else:
                    logging.warning(f"Failed to download image: Status {response.status_code}. Attempt {attempt + 1}/{max_retries}")
            except (Exception, requests.RequestException) as e:
                logging.warning(f"Error downloading image: {e}. Attempt {attempt + 1}/{max_retries}")
            time.sleep(5)
        logging.error(f"Failed to download image after {max_retries} retries.")
        return None

    def extract_score(self, feedback_text):
        """
        Extract the final score out of 10 from feedback text, prioritizing the last valid score.
        """
        if not feedback_text:
            logging.warning("Feedback text is empty.")
            return None

        scores = []
        patterns = [
            r'\b(\d{1,2})/10\b',
            r'\b(\d{1,2})\s*/\s*10\b',
            r'\bScore:?\s*(\d{1,2})/10\b',
            r'\b(\d{1,2})\s*out\s*of\s*10\b',
            r'\brating:?\s*(\d{1,2})/10\b',
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, feedback_text, re.IGNORECASE)
            for match in matches:
                try:
                    score = int(match.group(1))
                    if 0 <= score <= 10:
                        scores.append(score)
                except ValueError:
                    logging.warning(f"Failed to convert score '{match.group(1)}' in: {feedback_text[:100]}...")

        if scores:
            # Return the last valid score as the final evaluation
            final_score = scores[-1]
            logging.info(f"Extracted final score: {final_score}/10")
            return final_score
        logging.warning(f"No valid score found: {feedback_text[:100]}...")
        return None

    def add_logo_to_image(self, image_content):
        """
        Add the logo to the image at the top-right corner.
        """
        try:
            image = Image.open(BytesIO(image_content)).convert("RGBA")
            logo = Image.open(LOGO_PATH).convert("RGBA")

            logo_width = int(image.width * 0.1)
            logo_height = int(logo.height * (logo_width / logo.width))
            logo = logo.resize((logo_width, logo_height), Image.LANCZOS)

            padding = 10
            position = (image.width - logo_width - padding, padding)

            new_image = Image.new("RGBA", image.size)
            new_image.paste(image, (0, 0))
            new_image.paste(logo, position, logo)

            buffer = BytesIO()
            new_image.convert("RGB").save(buffer, format="PNG")
            return buffer.getvalue()
        except Exception as e:
            logging.error(f"Error adding logo: {e}")
            return image_content

    def generate_images(self, theme, content_type, num_images, subtopics):
        """
        Generate images per subtopic, save to S3, create a PDF, and return the PDF URL.
        """
        try:
            content_details = get_content_details()
            num_subtopics = min(num_images, len(subtopics), 10)  # Cap at 10 for scalability

            if num_subtopics < 1:
                logging.error("Number of subtopics must be at least 1.")
                print("❌ No PDF generated: Number of subtopics must be at least 1.")
                return []

            options = Options()
            options.add_argument(f"user-data-dir={CHROME_PROFILE_PATH1}")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--profile-directory=Profile 2")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)
            options.add_argument("--start-maximized")

            logging.info("Initializing ChromeDriver...")
            driver = None
            for retry in range(self.max_retries):
                try:
                    from webdriver_manager.chrome import ChromeDriverManager
                    from selenium.webdriver.chrome.service import Service
                    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
                    break
                except WebDriverException as e:
                    logging.error(f"ChromeDriver initialization failed (Attempt {retry + 1}/{self.max_retries}): {e}")
                    time.sleep(10)
            if not driver:
                logging.error("Failed to initialize ChromeDriver after all retries.")
                print("❌ Failed to initialize ChromeDriver.")
                return []

            image_urls = []

            try:
                logging.info("Opening ChatGPT...")
                driver.get("https://chatgpt.com")
                WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.XPATH, "//div[@role='textbox' or @id='prompt-textarea']"))
                )
                logging.info("Initial input field ready.")

                images_generated = 0
                for idx, subtopic in enumerate(subtopics[:num_subtopics], start=1):
                    attempts = 0
                    include_footer = (content_type.lower() == "promotional")
                    current_prompt = self.generate_image_prompt(subtopic, content_type, idx-1, theme, include_footer=False)
                    clean_title = re.sub(r'^\d+\.\s*[a-z]\)\s*\*\*', '', subtopic['title'], flags=re.IGNORECASE)
                    clean_title = re.sub(r'\*\*.*$', '', clean_title).strip()

                    best_subtopic_image = {
                        "score": 0,
                        "image_content": None,
                        "filename": f"images/image_{idx}_{uuid.uuid4().hex}.png",
                        "prompt": current_prompt
                    }

                    logging.info(f"Generating image for subtopic {idx}: {subtopic['title']}")
                    logging.info(f"Initial prompt: {current_prompt}")

                    while images_generated < num_images and best_subtopic_image["score"] < self.score_threshold and attempts < self.max_iterations:
                        if not self.submit_prompt(driver, current_prompt):
                            logging.error(f"Failed to submit prompt for subtopic {idx}, attempt {attempts + 1}")
                            attempts += 1
                            continue

                        if not self.wait_for_image_generation(driver, 400):
                            logging.warning(f"Image generation timeout for subtopic {idx}, attempt {attempts + 1}")
                            driver.refresh()
                            time.sleep(30)
                            try:
                                WebDriverWait(driver, 30).until(
                                    EC.element_to_be_clickable((By.XPATH, "//div[@role='textbox' or @id='prompt-textarea']"))
                                )
                                logging.info("Page refreshed and input field ready.")
                            except TimeoutException:
                                logging.error("Input field not ready after refresh.")
                                attempts += 1
                                continue

                        img_tags = driver.find_elements(By.TAG_NAME, "img")
                        if not img_tags:
                            logging.error(f"No image found for subtopic {idx}, attempt {attempts + 1}")
                            attempts += 1
                            feedback_prompt = (
                                f"As an expert editor, evaluate the image generation attempt for prompt: '{current_prompt}'. "
                                f"The image failed to generate. Assess the prompt's clarity, specificity, and alignment with the theme '{theme}'. "
                                f"Check for issues causing incomplete generation (e.g., vague instructions, missing details)."
                                f"Provide a score out of 10 (integer) and suggest a revised prompt to ensure a complete, high-quality image to the above image."
                            )
                            if not self.submit_prompt(driver, feedback_prompt):
                                continue
                            time.sleep(40)
                            feedback_elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'message')]")
                            feedback_text = " ".join([elem.text for elem in feedback_elements[-2:] if elem.text])
                            score = self.extract_score(feedback_text)
                            logging.info(f"Feedback for subtopic {idx}, attempt {attempts}: {feedback_text}, Score: {score}")

                            if score is None:
                                score = 5
                            revised_prompt_match = re.search(r"(?:Revised prompt|Improved prompt|New prompt):?\s*[\"']?([^\"'\n]+)[\"']?", feedback_text, re.IGNORECASE | re.MULTILINE)
                            current_prompt = revised_prompt_match.group(1).strip("'\".,") if revised_prompt_match else (
                                f"Generate instantly: {current_prompt} Ensure a complete image with vivid colors, intricate details, and full alignment with '{theme}'."
                            )
                            logging.info(f"Revised prompt for subtopic {idx}, attempt {attempts + 1}: {current_prompt}")
                            continue

                        img_src = img_tags[-1].get_attribute("src")
                        logging.info(f"Image URL found: {img_src}")

                        for retry in range(self.max_retries):
                            image_content = self.download_image(img_src)
                            if image_content:
                                break
                            logging.warning(f"Image download failed for subtopic {idx}, retry {retry + 1}/{self.max_retries}")
                            time.sleep(5)
                        if not image_content:
                            logging.error(f"Failed to download image for subtopic {idx} after retries")
                            attempts += 1
                            continue

                        feedback_prompt = (
                            f"As an expert editor for social media, evaluate the generated image for prompt: '{current_prompt}'. "
                            f"Assess creativity (innovative design, visual appeal), clarity (alignment with '{theme}'), engagement (audience attention), "
                            f"and completeness (ensure no half-generated sections). "
                            f"Check for spelling/grammar errors in any text and ensure the image is fully rendered. "
                            f"Provide a score out of 10 (integer). If the score is below 9 or the image is incomplete, "
                            f"suggest specific improvements for layout, colors, typography, or composition to ensure a complete, high-quality image to the above image."
                        )
                        if not self.submit_prompt(driver, feedback_prompt):
                            attempts += 1
                            continue
                        time.sleep(40)
                        feedback_elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'message')]")
                        feedback_text = " ".join([elem.text for elem in feedback_elements[-2:] if elem.text])
                        score = self.extract_score(feedback_text)
                        logging.info(f"Feedback for subtopic {idx}, attempt {attempts + 1}: {feedback_text}, Score: {score}")

                        if score is None:
                            score = 5
                        if score > best_subtopic_image["score"]:
                            best_subtopic_image["score"] = score
                            best_subtopic_image["image_content"] = image_content
                            best_subtopic_image["prompt"] = current_prompt

                        if score >= self.score_threshold:
                            logging.info(f"Image for subtopic {idx} meets quality threshold: {score}/10")
                            break

                        attempts += 1
                        revised_prompt_match = re.search(r"(?:Revised prompt|Improved prompt|New prompt):?\s*[\"']?([^\"'\n]+)[\"']?", feedback_text, re.IGNORECASE | re.MULTILINE)
                        current_prompt = revised_prompt_match.group(1).strip("'\".,") if revised_prompt_match else (
                            f"Generate instantly: {current_prompt} Ensure full image rendering with vivid colors, intricate details, and strong theme alignment."
                        )
                        logging.info(f"Revised prompt for subtopic {idx}, attempt {attempts + 1}: {current_prompt}")

                    if best_subtopic_image["image_content"] and best_subtopic_image["score"] >= self.score_threshold:
                        if content_type.lower() == "promotional":
                            final_prompt = self.generate_image_prompt(subtopic, content_type, idx-1, theme, include_footer=True)
                            logging.info(f"Generating final image with footer for subtopic {idx}")
                            if not self.submit_prompt(driver, final_prompt):
                                continue
                            time.sleep(120)  # Reduced from 180
                            if not self.submit_prompt(driver, "Processing final image, please wait."):
                                continue
                            time.sleep(40)  # Reduced from 60

                            img_tags = driver.find_elements(By.TAG_NAME, "img")
                            if img_tags:
                                img_src = img_tags[-1].get_attribute("src")
                                for retry in range(self.max_retries):
                                    image_content = self.download_image(img_src)
                                    if image_content:
                                        break
                                    logging.warning(f"Final image download failed for subtopic {idx}, retry {retry + 1}/{self.max_retries}")
                                    time.sleep(5)
                                if image_content:
                                    best_subtopic_image["image_content"] = image_content
                                    logging.info(f"Final image with footer generated for subtopic {idx}.")
                                else:
                                    logging.warning(f"Failed to download final image with footer for subtopic {idx}.")

                        final_image_content = self.add_logo_to_image(best_subtopic_image["image_content"])
                        buffer = BytesIO(final_image_content)
                        for retry in range(self.max_retries):
                            try:
                                s3.upload_fileobj(buffer, S3_BUCKET_NAME, best_subtopic_image["filename"], ExtraArgs={'ContentType': 'image/png'})
                                break
                            except Exception as e:
                                logging.warning(f"S3 upload failed (Attempt {retry + 1}/{self.max_retries}): {e}")
                                time.sleep(5)
                        image_url = f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{best_subtopic_image['filename']}"
                        logging.info(f"Image for subtopic {idx} uploaded to S3: {image_url}")
                        image_urls.append(image_url)
                        images_generated += 1
                    else:
                        logging.warning(f"No acceptable image generated for subtopic {idx}.")

                if image_urls:
                    pdf_buffer = BytesIO()
                    c = canvas.Canvas(pdf_buffer, pagesize=(595, 842))
                    images_added = 0
                    for idx, image_url in enumerate(image_urls, start=1):
                        try:
                            for retry in range(self.max_retries):
                                response = requests.get(image_url, timeout=15)
                                if response.status_code == 200:
                                    break
                                logging.warning(f"Failed to download image from S3 (Attempt {retry + 1}/{self.max_retries}): {image_url}")
                                time.sleep(5)
                            if response.status_code != 200:
                                logging.error(f"Failed to download image from S3 after retries: {image_url}")
                                continue
                            img_content = response.content
                            img = Image.open(BytesIO(img_content))
                            img_width, img_height = img.size
                            scale = min(595 / img_width, 842 / img_height)
                            new_width = int(img_width * scale)
                            new_height = int(img_height * scale)
                            x_position = (595 - new_width) / 2
                            y_position = (842 - new_height) / 2
                            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
                                tmp_file_path = tmp_file.name
                                img.save(tmp_file_path, format="PNG")
                                tmp_file.close()
                            if not os.path.exists(tmp_file_path):
                                logging.error(f"Temporary file not found: {tmp_file_path}")
                                continue
                            if images_added > 0:
                                c.showPage()
                            c.setFillColorRGB(0, 0, 0)
                            c.rect(0, 0, 595, 842, fill=1)
                            c.drawImage(tmp_file_path, x_position, y_position, width=new_width, height=new_height)
                            images_added += 1
                            logging.debug(f"Image {idx} added to PDF")
                            os.unlink(tmp_file_path)
                        except Exception as e:
                            logging.error(f"Failed to process image {image_url} for PDF: {e}")
                            continue
                    c.showPage()
                    c.save()
                    pdf_buffer.seek(0)

                    if images_added == 0:
                        logging.error("No images added to PDF.")
                        print("❌ No images added to the PDF.")
                        return []

                    pdf_filename = f"pdfs/IMG_{uuid.uuid4().hex[:8]}.pdf"
                    for retry in range(self.max_retries):
                        try:
                            s3.upload_fileobj(pdf_buffer, S3_BUCKET_NAME, pdf_filename, ExtraArgs={'ContentType': 'application/pdf'})
                            break
                        except Exception as e:
                            logging.warning(f"S3 PDF upload failed (Attempt {retry + 1}/{self.max_retries}): {e}")
                            time.sleep(5)
                    pdf_url = f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{pdf_filename}"
                    logging.info(f"PDF with {images_added} images uploaded to S3: {pdf_url}")
                    print(f"✅ PDF with {images_added} images saved to S3: {pdf_url}")
                    return [pdf_url]
                else:
                    logging.warning("No images generated successfully.")
                    print("❌ No PDF generated.")
                    return []

            except Exception as e:
                logging.error(f"Error during image generation: {e}")
                print(f"❌ Failed to save PDF to S3: {str(e)}")
                return []

            finally:
                if driver:
                    logging.info("Closing browser...")
                    driver.quit()
                    logging.info("Browser closed.")

        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            print(f"❌ Failed to save PDF to S3: {str(e)}")
            if driver:
                driver.quit()
            return []