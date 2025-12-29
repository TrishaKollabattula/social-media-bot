# content_handler.py - CONFIRMED WORKING WITH MEME MODE

import json
import logging
import os
from datetime import datetime
from dotenv import load_dotenv
import boto3
from image_generation.image_generator import ImageGenerator
from social_media.instagram_post import post_carousel_to_instagram
from social_media.twitter_post import post_content_to_twitter
from social_media.linkedin_post import post_to_linkedin_for_user
from content_generation.content_generator import ContentGenerator as PracharikContentGenerator

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
s3 = boto3.client("s3", region_name=AWS_REGION)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ContentGenerator:
    def __init__(self):
        self.image_generator = ImageGenerator()
        self.pracharik_generator = PracharikContentGenerator()

    def load_content_details(self):
        """Load content details from the generated JSON file"""
        try:
            with open("content_details.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            raise Exception("content_details.json not found.")
        except json.JSONDecodeError:
            raise Exception("Error decoding content_details.json.")

    def filter_image_urls(self, image_urls):
        """Filters out non-image URLs from the list"""
        if not image_urls:
            return []
        valid_image_urls = [url for url in image_urls if url.lower().endswith(('.jpg', '.jpeg', '.png', '.pdf'))]
        logger.info(f"Filtered URLs for social media: {valid_image_urls}")
        return valid_image_urls

    def extract_business_context(self, data):
        """Extract business context from request data"""
        business_context = {}
        
        if data.get("businessType"):
            business_context["business_type"] = data.get("businessType")
        
        if data.get("businessName"):
            business_context["business_name"] = data.get("businessName")
            
        if data.get("targetAudience"):
            business_context["target_audience"] = data.get("targetAudience")
            
        if data.get("productsServices"):
            business_context["products_services"] = data.get("productsServices")
            
        if data.get("industry"):
            business_context["industry"] = data.get("industry")
            
        # Auto-detect business type from theme if not provided
        if not business_context:
            theme = data.get("prompt", "").lower()
            if any(word in theme for word in ["restaurant", "food", "dosa", "meal", "dining"]):
                business_context["business_type"] = "restaurant"
            elif any(word in theme for word in ["fitness", "gym", "workout", "training"]):
                business_context["business_type"] = "fitness"
            elif any(word in theme for word in ["education", "course", "learning", "teach"]):
                business_context["business_type"] = "education"
            elif any(word in theme for word in ["tech", "software", "app", "digital"]):
                business_context["business_type"] = "technology"
            else:
                business_context["business_type"] = "general"
                
        return business_context if business_context else None

    def generate(self, context):
        try:
            request = context["request"]
            data = json.loads(request["body"])

            # Extract parameters
            theme = data.get("prompt") or data.get("marketing_theme")
            content_type = data.get("contentType", "Informative")
            num_images = int(data.get("numImages", 1))
            platforms = data.get("platforms", {})

            # 🎭 Extract meme mode toggle
            meme_mode = data.get("meme_mode", False) or data.get("meme", False)
            if isinstance(meme_mode, str):
                meme_mode = meme_mode.lower() in ['true', '1', 'yes']

            # Get user ID
            headers = request.get("headers", {}) or {}
            def hget(key, default=None):
                for k, v in headers.items():
                    if k.lower() == key.lower():
                        return v
                return default

            qs = request.get("queryStringParameters", {}) or {}

            user_id = None
            if "claims" in context and context["claims"]:
                user_id = context["claims"].get("username") or context["claims"].get("user_id")
            if not user_id:
                user_id = data.get("user_id") or data.get("username")
            if not user_id:
                user_id = hget("X-User-Id")
            if not user_id:
                user_id = qs.get("app_user")

            if not user_id:
                logger.error("❌ No user_id found!")
                return {"error": "User authentication required", "status": "error"}
            
            logger.info(f"=== CONTENT GENERATION START ===")
            logger.info(f"👤 User ID: {user_id}")
            logger.info(f"📝 Theme: {theme}")
            logger.info(f"🎨 Content Type: {content_type}")
            logger.info(f"🖼️ Number of Images: {num_images}")
            logger.info(f"🎭 Meme Mode: {'ENABLED ✅' if meme_mode else 'DISABLED'}")
            
            business_context = self.extract_business_context(data)
            
            if not theme or not content_type:
                return {"error": "Missing theme or content type"}

            logger.info(f"Generating content using Pracharik system")
            
            if business_context:
                logger.info(f"Business Type: {business_context.get('business_type', 'Unknown')}")
                logger.info(f"Company: {business_context.get('business_name', 'Unknown')}")

            # Store the prompt to S3
            try:
                today = datetime.today().strftime('%Y-%m-%d')
                s3.put_object(
                    Bucket=S3_BUCKET_NAME,
                    Key=f"user_prompts/{today}_prompt.txt",
                    Body=theme.encode('utf-8')
                )
                logger.info(f"✅ Stored user-submitted prompt for {today}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to store prompt to S3: {str(e)}")

            # Generate content using Pracharik system
            platforms_list = []
            if isinstance(platforms, dict):
                platforms_list = [platform for platform, enabled in platforms.items() if enabled]
            elif isinstance(platforms, list):
                platforms_list = platforms
            
            logger.info(f"📝 Calling Pracharik content generator...")
            
            # 🎭 Pass meme_mode to content generator
            content_result = self.pracharik_generator.generate_complete_content(
                theme=theme,
                content_type=content_type,
                num_subtopics=num_images,
                platforms=platforms_list,
                company_context=business_context,
                user_id=user_id,  # ✅ Pass user_id
                meme_mode=meme_mode  # 🎭 Pass meme_mode
            )
            
            logger.info(f"✅ Pracharik content generation completed")

            # Save user_id to content_details.json
            if user_id:
                try:
                    with open("content_details.json", "r", encoding="utf-8") as f:
                        content_details_temp = json.load(f)
                    
                    content_details_temp['user_id'] = user_id
                    content_details_temp['meme_mode'] = meme_mode  # 🎭 Save meme mode
                    
                    with open("content_details.json", "w", encoding="utf-8") as f:
                        json.dump(content_details_temp, f, indent=2, ensure_ascii=False)
                    
                    logger.info(f"✅ Saved user_id {user_id} and meme_mode={meme_mode} to content_details.json")
                except Exception as e:
                    logger.error(f"❌ Failed to save user_id: {e}")

            # Load the generated content details
            content_details = self.load_content_details()
            
            subtopics = content_details.get("subtopics", [])
            slide_contents = content_details.get("slide_contents", {})
            captions_dict = content_details.get("captions", {})
            single_caption = captions_dict.get("post_caption", "Default caption for the post")
            image_prompts = content_details.get("image_prompts", [])

            logger.info(f"📝 Caption length: {len(single_caption)} characters")
            
            # Format subtopics for image generation
            transformed_subtopics = []
            for i, subtopic in enumerate(subtopics):
                # subtopic is a dict, not a string title
                slide_key = f"slide_{i+1}"
                slide = slide_contents.get(slide_key, {})
                details = " ".join(slide.get('body', [])) if slide else subtopic.get('body', '')
                image_prompt = image_prompts[i] if i < len(image_prompts) else details
                transformed_subtopics.append({
                    "title": subtopic.get('header') or subtopic.get('title'),
                    "details": details,
                    "captions": [single_caption],
                    "image_prompt": image_prompt
                })

            logger.info(f"🎨 Starting image generation for {len(transformed_subtopics)} images...")

            # 🎭 Generate images with meme toggle
            image_urls = self.image_generator.generate_images(
                theme=theme,
                content_type=content_type,
                num_images=num_images,
                subtopics=transformed_subtopics,
                user_id=user_id,
                meme_mode=meme_mode  # 🎭 Pass meme mode flag
            )
            logger.info(f"✅ Generated image URLs: {image_urls}")

            # Filter URLs
            filtered_urls = self.filter_image_urls(image_urls)
            logger.info(f"✅ Filtered URLs for social media: {filtered_urls}")

            # Separate PDFs and images
            pdf_urls = [url for url in filtered_urls if url.lower().endswith('.pdf')]
            image_only_urls = [url for url in filtered_urls if not url.lower().endswith('.pdf')]

            logger.info(f"📄 PDF URLs: {pdf_urls}")
            logger.info(f"🖼️ Image URLs: {image_only_urls}")

            # POST TO SOCIAL PLATFORMS
            social_results = {}

            # Instagram posting
            if platforms.get("instagram"):
                try:
                    if image_only_urls:
                        instagram_result = post_carousel_to_instagram(
                            image_urls=image_only_urls,
                            caption=single_caption,
                            num_images=len(image_only_urls)
                        )
                        social_results["instagram"] = instagram_result
                        logger.info(f"✅ Instagram: {instagram_result}")
                    else:
                        social_results["instagram"] = {"status": "skipped", "message": "No image URLs available"}
                        logger.warning("⚠️ No images for Instagram")
                except Exception as e:
                    social_results["instagram"] = {"status": "error", "message": str(e)}
                    logger.error(f"❌ Instagram failed: {e}")

            # Twitter posting
            if platforms.get("twitter") or platforms.get("x"):
                try:
                    twitter_image = image_only_urls[0] if image_only_urls else None
                    if twitter_image:
                        twitter_result = post_content_to_twitter(
                            image_urls=[twitter_image],
                            caption=single_caption,
                            num_images=1
                        )
                        social_results["twitter"] = twitter_result
                        logger.info(f"✅ Twitter: {twitter_result}")
                    else:
                        social_results["twitter"] = {"status": "skipped", "message": "No image URLs available"}
                except Exception as e:
                    social_results["twitter"] = {"status": "error", "message": str(e)}
                    logger.error(f"❌ Twitter failed: {e}")

            # LinkedIn posting
            if platforms.get("linkedin"):
                try:
                    logger.info(f"🔵 Starting LinkedIn posting for user: {user_id}")
                    
                    pdf_url_to_post = pdf_urls[0] if pdf_urls else None
                    
                    success, message = post_to_linkedin_for_user(
                        user_id=user_id,
                        s3_url=pdf_url_to_post,
                        caption=single_caption
                    )
                    
                    social_results["linkedin"] = {
                        "success": success,
                        "message": message,
                        "posted_url": pdf_url_to_post,
                        "user_id": user_id
                    }
                    
                    if success:
                        logger.info(f"✅ LinkedIn: {message}")
                    else:
                        logger.error(f"❌ LinkedIn: {message}")
                    
                except Exception as e:
                    social_results["linkedin"] = {
                        "success": False,
                        "message": f"Error: {str(e)}",
                        "user_id": user_id
                    }
                    logger.error(f"❌ LinkedIn posting exception: {e}")
                    import traceback
                    logger.error(traceback.format_exc())

            # PREPARE RESPONSE
            successful_posts = 0
            for platform, result in social_results.items():
                if isinstance(result, dict):
                    if result.get("success") or result.get("status") == "success":
                        successful_posts += 1
                elif isinstance(result, list):
                    successful_posts += sum(1 for r in result if isinstance(r, dict) and r.get("success"))

            response_data = {
                "message": "Success - Generated with Pracharik AI",
                "image_urls": image_only_urls,
                "pdf_url": pdf_urls[0] if pdf_urls else None,
                "all_urls": filtered_urls,
                "caption": single_caption,
                "social_results": social_results,
                "generation_metadata": content_details.get("generation_metadata", {}),
                "platform_optimizations": content_details.get("platform_optimizations", {}),
                "business_context": {
                    "business_type": business_context.get("business_type") if business_context else None,
                    "company_name": business_context.get("business_name") if business_context else None
                },
                "content_type": content_type,
                "num_images_generated": len(image_only_urls),
                "num_pdfs_generated": len(pdf_urls),
                "user_id": user_id,
                "successful_posts": successful_posts,
                "meme_mode_used": meme_mode  # 🎭 Include in response
            }

            logger.info(f"=== CONTENT GENERATION COMPLETE ===")
            logger.info(f"✅ Generated {len(image_only_urls)} images and {len(pdf_urls)} PDFs")
            logger.info(f"✅ Posted to {successful_posts} platforms")
            logger.info(f"🎭 Meme Mode: {'ENABLED ✅' if meme_mode else 'DISABLED'}")
            logger.info(f"👤 User ID: {user_id}")
            
            return response_data

        except Exception as e:
            logger.error(f"❌ Content generation failed: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {"error": f"Content generation failed: {str(e)}", "success": False}