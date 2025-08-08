import json
import logging
import os
import time
from io import BytesIO
import requests
import uuid
import subprocess
from datetime import datetime
from dotenv import load_dotenv
import boto3
from image_generation.image_generator import ImageGenerator
from social_media.instagram_post import post_carousel_to_instagram
from social_media.twitter_post import post_content_to_twitter
from social_media.linkedin_post import post_content_to_linkedin
from social_media.facebook_post import post_images_to_facebook  # ✅ Updated import

# Load environment variables
load_dotenv()

CONTENT_GENERATOR_PATH = "content_generation/content_generator.py"

# S3 Setup
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
s3 = boto3.client("s3", region_name=AWS_REGION)

# Social Media Posting Class
class ContentGenerator:
    def __init__(self):
        self.image_generator = ImageGenerator()

    def run_content_generator(self, theme, num_subtopics, content_type):
        command = f"python {CONTENT_GENERATOR_PATH} --theme \"{theme}\" --num_subtopics {num_subtopics} --content_type {content_type}"
        try:
            subprocess.run(command, shell=True, check=True)
        except subprocess.CalledProcessError as e:
            raise Exception(f"Content generation failed: {e}")

    def load_content_details(self):
        try:
            with open("content_details.json", "r") as f:
                return json.load(f)
        except FileNotFoundError:
            raise Exception("content_details.json not found. Ensure content_generator.py ran successfully.")
        except json.JSONDecodeError:
            raise Exception("Error decoding content_details.json.")

    def filter_image_urls(self, image_urls):
        """Filters out non-image URLs from the list of image URLs."""
        valid_image_urls = [url for url in image_urls if url.lower().endswith(('.jpg', '.jpeg', '.png'))]
        logging.info(f"Filtered image URLs for social media: {valid_image_urls}")
        return valid_image_urls

    def generate(self, context):
        try:
            request = context["request"]
            data = json.loads(request["body"])
            theme = data.get("prompt")
            content_type = data.get("contentType")
            num_images = int(data.get("numImages", 1))
            platforms = data.get("platforms", {})

            if not theme or not content_type:
                return {"error": "Missing theme or content type."}, 400

            # Store the prompt to S3
            try:
                today = datetime.today().strftime('%Y-%m-%d')
                s3.put_object(
                    Bucket=S3_BUCKET_NAME,
                    Key=f"user_prompts/{today}_prompt.txt",
                    Body=theme.encode('utf-8')
                )
                print(f"✅ Stored user-submitted prompt for {today}")
            except Exception as e:
                print(f"❌ Failed to store prompt to S3: {str(e)}")

            # Generate content
            self.run_content_generator(theme, num_images, content_type)

            # Load generated content
            content_details = self.load_content_details()
            subtopics = content_details.get("subtopics", [])
            slide_contents = content_details.get("slide_contents", {})

            captions_dict = content_details.get("captions", {})
            single_caption = captions_dict.get("post_caption", "Default caption for the post")

            # Format subtopics for image generation
            transformed_subtopics = []
            for sub in subtopics:
                title = sub
                slide = slide_contents.get(sub, [])
                details = " ".join(slide) if slide else title
                transformed_subtopics.append({
                    "title": title,
                    "details": details,
                    "captions": [single_caption]
                })

            # Generate images
            image_urls = self.image_generator.generate_images(theme, content_type, num_images, transformed_subtopics)
            logging.info(f"Generated image URLs: {image_urls}")

            # Filter out any non-image URLs
            image_urls = self.filter_image_urls(image_urls)
            logging.info(f"Filtered image URLs for social media: {image_urls}")

            # Upload images to S3 and get their URLs
            s3_image_urls = []
            for img_url in image_urls:
                img_content = requests.get(img_url).content
                img_name = f"images/{uuid.uuid4().hex}.png"
                s3.upload_fileobj(BytesIO(img_content), S3_BUCKET_NAME, img_name, ExtraArgs={'ContentType': 'image/png'})
                s3_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{img_name}"
                s3_image_urls.append(s3_url)
                logging.info(f"Image uploaded to S3: {s3_url}")

            # Post to social platforms
            social_results = {}

            # Instagram posting
            if platforms.get("instagram"):
                try:
                    ig_result = post_carousel_to_instagram(
                        image_urls=s3_image_urls,
                        caption=single_caption,
                        num_images=num_images
                    )
                    social_results["instagram"] = ig_result
                except Exception as e:
                    social_results["instagram"] = {"status": "error", "message": str(e)}

            # Twitter posting
            if platforms.get("twitter") or platforms.get("x"):
                try:
                    twitter_image = s3_image_urls[0] if s3_image_urls else None
                    twitter_result = post_content_to_twitter(
                        image_urls=[twitter_image] if twitter_image else None,
                        caption=single_caption,
                        num_images=1
                    )
                    social_results["twitter"] = twitter_result
                except Exception as e:
                    social_results["twitter"] = {"status": "error", "message": str(e)}

            # LinkedIn posting
            if platforms.get("linkedin"):
                try:
                    linkedin_results = []
                    for idx, image_url in enumerate(s3_image_urls, 1):
                        success, message = post_content_to_linkedin(
                            caption=f"{single_caption} (Image {idx})",
                            access_token=os.getenv("LINKEDIN_ACCESS_TOKEN"),
                            user_urn=os.getenv("LINKEDIN_USER_URN")
                        )
                        linkedin_results.append({"success": success, "message": message, "image_url": image_url})
                    social_results["linkedin"] = linkedin_results
                except Exception as e:
                    social_results["linkedin"] = {"status": "error", "message": str(e)}

            # ✅ Facebook posting
            if platforms.get("facebook"):
                try:
                    facebook_result = post_images_to_facebook(
                        image_urls=s3_image_urls,
                        caption=single_caption,
                        num_images=num_images
                    )
                    social_results["facebook"] = facebook_result
                    logging.info(f"✅ Facebook posting result: {facebook_result}")
                except Exception as e:
                    social_results["facebook"] = {"status": "error", "message": f"Failed to post to Facebook: {str(e)}"}

            return {
                "message": "Success",
                "image_urls": s3_image_urls,
                "caption": single_caption,
                "social_results": social_results
            }

        except Exception as e:
            return {"error": str(e)}, 500