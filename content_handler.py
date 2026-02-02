# content_handler.py - UPDATED WITH GPT PROMPT GENERATION

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
            business_context["company_name"] = data.get("businessName")
            business_context["brand_name"] = data.get("businessName")
            
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

    # ✅ NEW HELPER METHOD
    def _extract_clean_website(self, raw_website: str) -> str:
        """
        Extract clean website URL from contact_details field
        Example: "www.craftingbrain.com\n+91 6304634575" -> "https://www.craftingbrain.com"
        """
        if not raw_website:
            return None
        
        # Split by newlines and find the URL part
        lines = raw_website.split('\n')
        for line in lines:
            line = line.strip()
            # Check if line looks like a URL
            if any(marker in line.lower() for marker in ['www.', 'http://', 'https://', '.com', '.in', '.org', '.ai', '.io', '.co']):
                # Clean the URL
                url = line.strip()
                
                # Add https:// if missing
                if not url.startswith('http://') and not url.startswith('https://'):
                    url = 'https://' + url
                
                # Remove any trailing slashes
                url = url.rstrip('/')
                
                logger.info(f"✅ Extracted clean website URL: {url}")
                return url
        
        logger.warning(f"⚠️ No valid URL found in: {raw_website[:50]}...")
        return None

    def _normalize_brand_colors(self, business_context: dict) -> list[str]:
        """
        Accepts multiple schema variants and returns a clean list of hex colors.
        Supports:
        - color_theme as list OR comma-separated string
        - brand_colors / colors as list OR string
        - palette dict
        """
        if not business_context:
            return []

        def _from_string(s: str) -> list[str]:
            parts = [p.strip() for p in s.split(",")]
            return [p for p in parts if p.startswith("#")]

        # 1) color_theme (your DynamoDB field)
        v = business_context.get("color_theme")
        if isinstance(v, list) and v:
            return [c.strip() for c in v if isinstance(c, str) and c.strip().startswith("#")]
        if isinstance(v, str) and v.strip():
            colors = _from_string(v)
            if colors:
                return colors

        # 2) brand_colors / colors
        v = business_context.get("brand_colors") or business_context.get("colors")
        if isinstance(v, list) and v:
            return [c.strip() for c in v if isinstance(c, str) and c.strip().startswith("#")]
        if isinstance(v, str) and v.strip():
            colors = _from_string(v)
            if colors:
                return colors

        # 3) palette dict
        pal = business_context.get("palette")
        if isinstance(pal, dict):
            out = []
            for k in ("primary", "secondary", "accent"):
                c = pal.get(k)
                if isinstance(c, str) and c.strip().startswith("#"):
                    out.append(c.strip())
            if out:
                return out

        return []

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

            # ✅ NEW: Extract optional custom image prompt from frontend
            user_image_prompt = data.get("imagePrompt") or data.get("image_prompt") or data.get("customPrompt")
            if user_image_prompt:
                logger.info(f"🎨 Custom image prompt received: {user_image_prompt[:100]}...")

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
            
            # ✅ 1) Always start with DynamoDB business profile (source of truth)
            business_context = self.pracharik_generator.get_user_business_data(user_id)
            # 🎨 Normalize brand colors from DynamoDB profile
            brand_colors = self._normalize_brand_colors(business_context or {})

            if business_context is None:
                business_context = {}

            if brand_colors:
                # canonical fields used everywhere
                business_context["brand_colors"] = brand_colors
                business_context["colors"] = brand_colors

                # optional palette mapping
                business_context["palette"] = {
                    "primary": brand_colors[0],
                    "secondary": brand_colors[1] if len(brand_colors) > 1 else brand_colors[0],
                }

            logger.info(f"🎨 Brand Colors: {brand_colors or 'Missing'}")

            # ✅ NEW: Extract website URL from business context
            website_url = None
            if business_context:
                # Try multiple fields where website might be stored
                raw_website = (
                    business_context.get('website') or 
                    business_context.get('contact_details') or 
                    business_context.get('website_url')
                )
                
                if raw_website:
                    website_url = self._extract_clean_website(raw_website)
                    if website_url:
                        logger.info(f"🌐 Website from profile: {website_url}")
                else:
                    logger.warning("⚠️ No website found in user profile")

            # ✅ OPTIONAL: Allow frontend to override website
            frontend_website = data.get("websiteUrl") or data.get("website_url") or data.get("website")
            if frontend_website:
                website_url = frontend_website
                logger.info(f"🌐 Website overridden from frontend: {website_url}")

            # ✅ 2) Overlay request-provided fields (only if present)
            req_ctx = self.extract_business_context(data)
            if req_ctx:
                if req_ctx.get("business_type"):
                    business_context = business_context or {}
                    business_context["business_type"] = req_ctx["business_type"]

                if req_ctx.get("business_name"):
                    business_context = business_context or {}
                    business_context["company_name"] = req_ctx["business_name"]
                    business_context["brand_name"] = req_ctx["business_name"]

                if req_ctx.get("target_audience"):
                    business_context = business_context or {}
                    business_context["target_audience"] = req_ctx["target_audience"]

                if req_ctx.get("products_services"):
                    business_context = business_context or {}
                    business_context["products_services"] = req_ctx["products_services"]

                if req_ctx.get("industry"):
                    business_context = business_context or {}
                    business_context["business_type"] = req_ctx["industry"]
            
            if not theme or not content_type:
                return {"error": "Missing theme or content type"}

            logger.info(f"Generating content using Pracharik system")
            
            if business_context:
                logger.info(f"Business Type: {business_context.get('business_type', 'Unknown')}")
                logger.info(f"Company: {business_context.get('company_name', 'Unknown')}")

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
            
            content_result = self.pracharik_generator.generate_complete_content(
                theme=theme,
                content_type=content_type,
                num_subtopics=num_images,
                platforms=platforms_list,
                company_context=business_context,
                user_id=user_id,
                meme_mode=meme_mode
            )
            
            logger.info(f"✅ Pracharik content generation completed")

            # Save user_id to content_details.json
            if user_id:
                try:
                    with open("content_details.json", "r", encoding="utf-8") as f:
                        content_details_temp = json.load(f)
                    
                    content_details_temp['user_id'] = user_id
                    content_details_temp['meme_mode'] = meme_mode
                    
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

            # ✅ UPDATED: Pass new parameters to image generator
            image_urls = self.image_generator.generate_images(
                theme=theme,
                content_type=content_type,
                num_images=num_images,
                subtopics=transformed_subtopics,
                user_id=user_id,
                meme_mode=meme_mode,
                website_url=website_url,  # ✅ NEW: From DynamoDB or frontend
                user_image_prompt=user_image_prompt,  # ✅ NEW: Optional custom prompt
                content_summary=content_details.get("summary", []),  # ✅ NEW: Content context
                business_context=business_context  # ✅ NEW: Full business profile
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
                    "company_name": business_context.get("company_name") if business_context else None  # ✅ FIXED: was business_name
                },
                "content_type": content_type,
                "num_images_generated": len(image_only_urls),
                "num_pdfs_generated": len(pdf_urls),
                "user_id": user_id,
                "successful_posts": successful_posts,
                "meme_mode_used": meme_mode,
                "website_url": website_url,  # ✅ NEW: Include in response
                "custom_prompt_used": bool(user_image_prompt)  # ✅ NEW: Indicate if custom prompt was used
            }

            logger.info(f"=== CONTENT GENERATION COMPLETE ===")
            logger.info(f"✅ Generated {len(image_only_urls)} images and {len(pdf_urls)} PDFs")
            logger.info(f"✅ Posted to {successful_posts} platforms")
            logger.info(f"🎭 Meme Mode: {'ENABLED ✅' if meme_mode else 'DISABLED'}")
            logger.info(f"🌐 Website: {website_url or 'Not provided'}")
            logger.info(f"🎨 Custom Prompt: {'Yes ✅' if user_image_prompt else 'No'}")
            logger.info(f"👤 User ID: {user_id}")
            
            return response_data

        except Exception as e:
            logger.error(f"❌ Content generation failed: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {"error": f"Content generation failed: {str(e)}", "success": False}