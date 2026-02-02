# content_generation/content_generator.py - UPDATED WITH OPENAI GPT-4o-mini PRIMARY
# ✅ Uses OpenAI GPT-4o-mini for high-quality content generation
# ✅ Groq as fallback when OpenAI fails
# ✅ Dynamic, context-aware content specific to user prompts
# ✅ Maintains exact same JSON structure

import os
from typing import Dict, List, Any, Optional
import json
from datetime import datetime
import logging
import boto3
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv
from content_templates import TEMPLATES
import random

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logging.warning("⚠️ OpenAI library not installed. Run: pip install openai")

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    logging.warning("⚠️ Groq library not installed. Run: pip install groq")

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# AWS Setup
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
try:
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    user_survey_table = dynamodb.Table("UserSurveyData")
    DYNAMODB_AVAILABLE = True
    logger.info("✅ DynamoDB connected")
except Exception as e:
    logger.warning(f"⚠️ DynamoDB not available: {e}")
    DYNAMODB_AVAILABLE = False

# Content type configurations with business-specific adaptations
CONTENT_TYPES = {
    "Informative": {
        "tone": "educational and fact-based",
        "image_style": "professional modern clean photographic",
        "approach": "data-driven with clear explanations"
    },
    "Inspirational": {
        "tone": "motivational and uplifting",
        "image_style": "bright vibrant inspiring photographic",
        "approach": "emotional with success stories"
    },
    "Promotional": {
        "tone": "persuasive and compelling",
        "image_style": "bold dynamic professional photographic",
        "approach": "benefit-focused with clear value"
    },
    "Educational": {
        "tone": "instructional and clear",
        "image_style": "structured clean photographic",
        "approach": "step-by-step with practical examples"
    },
    "Engaging": {
        "tone": "conversational and interactive",
        "image_style": "modern trendy photographic or meme-style",
        "approach": "community-focused with viral potential"
    }
}

# Business type specific styling
BUSINESS_STYLES = {
    "technology": {
        "visual_theme": "modern, tech-forward, innovative",
        "color_palette": "blues, teals, vibrant gradients",
        "font_style": "clean sans-serif, futuristic",
        "imagery": "digital interfaces, abstract tech patterns"
    },
    "education": {
        "visual_theme": "friendly, approachable, trustworthy",
        "color_palette": "warm oranges, yellows, blues",
        "font_style": "rounded, readable, welcoming",
        "imagery": "students, learning environments, growth"
    },
    "edtech": {
        "visual_theme": "innovative yet accessible, modern education",
        "color_palette": "bright blues, greens, educational warmth",
        "font_style": "modern sans-serif, clean and readable",
        "imagery": "digital learning, student success, technology in education"
    },
    "healthcare": {
        "visual_theme": "professional, caring, trustworthy",
        "color_palette": "calming blues, greens, medical whites",
        "font_style": "professional serif or clean sans",
        "imagery": "health professionals, wellness, care"
    },
    "finance": {
        "visual_theme": "professional, secure, premium",
        "color_palette": "deep blues, gold accents, trust colors",
        "font_style": "elegant serif, professional sans",
        "imagery": "growth charts, security, success"
    },
    "retail": {
        "visual_theme": "attractive, lifestyle-focused, aspirational",
        "color_palette": "product-focused, lifestyle colors",
        "font_style": "modern, trendy, attention-grabbing",
        "imagery": "products, lifestyle shots, customer joy"
    },
    "saas": {
        "visual_theme": "professional, efficient, modern",
        "color_palette": "tech blues, productive greens, clean whites",
        "font_style": "clean sans-serif, professional",
        "imagery": "dashboards, productivity, solutions"
    },
    "restaurant": {
        "visual_theme": "appetizing, inviting, warm",
        "color_palette": "food colors, warm tones, appetite appeal",
        "font_style": "decorative headers, readable body",
        "imagery": "food photography, dining experiences, ambiance"
    },
    "eyewear": {
        "visual_theme": "stylish, premium, modern optical",
        "color_palette": "clean whites, sophisticated blacks, brand accents",
        "font_style": "elegant modern, readable",
        "imagery": "eyewear products, lifestyle shots, clarity focus"
    },
    "general": {
        "visual_theme": "professional, versatile, modern",
        "color_palette": "balanced colors, professional tones",
        "font_style": "clean sans-serif, readable",
        "imagery": "business-appropriate, professional quality"
    }
}


class ContentGenerator:
    """Enhanced content generation engine with OpenAI GPT-4o-mini primary, Groq fallback"""

    def __init__(self):
        self.openai_client = None
        self.groq_client = None
        self.openai_available = False
        self.groq_available = False

        # Initialize OpenAI (Primary)
        if OPENAI_AVAILABLE:
            openai_key = os.getenv("OPENAI_API_KEY")
            if openai_key and len(openai_key) > 20:
                try:
                    logger.info("🔑 Initializing OpenAI GPT-4o-mini...")
                    self.openai_client = OpenAI(api_key=openai_key)
                    
                    # Quick validation test
                    test = self.openai_client.chat.completions.create(
                        messages=[{"role": "user", "content": "test"}],
                        model="gpt-4o-mini",
                        max_tokens=10
                    )
                    if test and test.choices:
                        logger.info("✅ OpenAI GPT-4o-mini validated successfully")
                        self.openai_available = True
                except Exception as e:
                    logger.warning(f"⚠️ OpenAI initialization failed: {e}")
        
        # Initialize Groq (Fallback)
        if GROQ_AVAILABLE:
            groq_key = os.getenv("GROQ_API_KEY")
            if groq_key and len(groq_key) > 20:
                try:
                    logger.info("🔑 Initializing Groq as fallback...")
                    self.groq_client = Groq(api_key=groq_key)
                    
                    # Quick validation test
                    test = self.groq_client.chat.completions.create(
                        messages=[{"role": "user", "content": "test"}],
                        model="llama-3.1-8b-instant",
                        max_tokens=10
                    )
                    if test and test.choices:
                        logger.info("✅ Groq fallback validated successfully")
                        self.groq_available = True
                except Exception as e:
                    logger.warning(f"⚠️ Groq fallback initialization failed: {e}")

        if not self.openai_available and not self.groq_available:
            logger.error("❌ No AI provider available! Content generation will use basic fallbacks.")

    def _call_ai_api(self, messages: List[Dict], temperature: float = 0.7, max_tokens: int = 2000) -> Optional[str]:
        """
        Unified AI API caller with automatic fallback
        Tries OpenAI first, falls back to Groq if needed
        """
        # Try OpenAI first
        if self.openai_available and self.openai_client:
            try:
                logger.info("🤖 Calling OpenAI GPT-4o-mini...")
                response = self.openai_client.chat.completions.create(
                    messages=messages,
                    model="gpt-4o-mini",
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                if response and response.choices:
                    content = response.choices[0].message.content.strip()
                    logger.info("✅ OpenAI generated content successfully")
                    return content
            except Exception as e:
                logger.warning(f"⚠️ OpenAI failed: {e}, trying Groq fallback...")
        
        # Fallback to Groq
        if self.groq_available and self.groq_client:
            try:
                logger.info("🔄 Calling Groq fallback...")
                response = self.groq_client.chat.completions.create(
                    messages=messages,
                    model="llama-3.1-8b-instant",
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                if response and response.choices:
                    content = response.choices[0].message.content.strip()
                    logger.info("✅ Groq fallback generated content successfully")
                    return content
            except Exception as e:
                logger.error(f"❌ Groq fallback also failed: {e}")
        
        return None

    # =====================================================================
    # ✅ ENHANCED: AI-POWERED IMAGE PROMPT GENERATION
    # =====================================================================
    def _generate_slide_overlay_content(
        self, 
        theme: str, 
        content_type: str,
        company_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """
        Generate text content that will be overlaid on carousel images.
        Returns title and body text ready for image overlay.
        """
        
        # Build business context
        business_text = ""
        if company_context:
            company_name = company_context.get('company_name', '')
            business_type = company_context.get('business_type', 'general')
            products_services = company_context.get('products_services', '')
            target_audience = company_context.get('target_audience', '')
            brand_values = company_context.get('brand_values', '')
            
            business_text = f"""
BUSINESS CONTEXT:
Company: {company_name}
Industry: {business_type}
Products/Services: {products_services}
Target Audience: {target_audience}
Brand Values: {brand_values}
"""

        content_style = CONTENT_TYPES.get(content_type, CONTENT_TYPES['Promotional'])
        
        # For single image requests, generate a compelling title and body for overlay
        ai_prompt = f"""You are creating text content that will be overlaid on a carousel image.

USER REQUEST: "{theme}"

{business_text}

CONTENT TYPE: {content_type}
TONE: {content_style['tone']}

Create text content for ONE slide with:

1. **TITLE**: A compelling, concise headline (5-10 words max)
   - Should capture attention immediately
   - Use power words relevant to the theme
   - Brand-aligned tone

2. **BODY**: Supporting text (15-25 words)
   - Explain the value/benefit clearly
   - Use simple, impactful language
   - Make it scannable and memorable

3. **CAPTION**: Instagram caption (80-120 words)
   - Engaging hook related to the theme
   - Include relevant emojis (3-5)
   - Call-to-action at the end
   - Context about the visual

Make it DIRECTLY RELEVANT to "{theme}" and professional for overlay on images.

Return ONLY valid JSON:
{{
  "title": "...",
  "body": "...",
  "caption": "..."
}}
"""

        # Call AI API with fallback
        response_content = self._call_ai_api(
            messages=[{"role": "user", "content": ai_prompt}],
            temperature=0.7,
            max_tokens=500
        )
        
        if response_content:
            try:
                content = self._extract_json(response_content)
                if content:
                    result = json.loads(content)
                    logger.info("✅ AI generated overlay text content successfully")
                    return result
            except Exception as e:
                logger.warning(f"⚠️ AI text generation parsing failed: {e}")
        
        # Fallback overlay text
        return self._create_fallback_overlay_text(theme, content_style, company_context)

    def _create_fallback_overlay_text(
        self, 
        theme: str, 
        content_style: Dict,
        company_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """Fallback overlay text when AI is unavailable"""
        
        business_name = (company_context or {}).get('company_name', '')
        
        # Create simple, clear overlay text
        title = theme.title() if len(theme) < 50 else theme[:47] + "..."
        body = f"Discover the difference with {business_name}" if business_name else "Quality and excellence in every detail"
        caption = f"✨ {theme} ✨\n\nExperience excellence.\n\n{f'📍 {business_name}' if business_name else ''}\n\n#quality #excellence #professional"
        
        return {
            "title": title,
            "body": body,
            "caption": caption
        }

    # =====================================================================
    # INTENT ROUTING (IMAGE vs CAROUSEL)
    # =====================================================================
    def detect_intent(self, theme: str) -> str:
        """
        Detect whether user wants an "image request" or a "carousel topic".
        Returns: 'image' or 'carousel'
        """
        t = (theme or "").strip().lower()

        # Strong image markers
        image_markers = [
            "generate", "create", "make", "draw", "design", "image", "photo", "picture",
            "poster", "logo", "banner", "flyer", "thumbnail", "avatar", "illustration",
            "character", "portrait", "3d", "render", "realistic", "4k", "hd", "penguin"
        ]

        if any(k in t for k in image_markers):
            return "image"

        return "carousel"

    def normalize_image_request(self, theme: str) -> Dict[str, str]:
        """Convert theme into a clean image brief."""
        raw = (theme or "").strip()
        cleaned = (
            raw.replace("geberate", "generate")
               .replace("genearte", "generate")
               .replace("genrate", "generate")
               .strip()
        )
        if len(cleaned) < 10:
            cleaned = f"Generate an image based on: {raw}"
        return {"title": "Image Request", "body": cleaned}

    def generate_image_mode_content(
        self,
        theme: str,
        content_type: str,
        company_context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        platforms: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        ✅ Generate text content for overlay on carousel images
        This is used when user wants a single image with text overlay
        """
        img = self.normalize_image_request(theme)
        company_name = (company_context or {}).get("company_name")
        
        # Generate overlay text content
        overlay_content = self._generate_slide_overlay_content(
            theme, content_type, company_context
        )
        
        slide_title = overlay_content["title"]
        slide_body = [overlay_content["body"]]

        out = {
            "status": "success",
            "user_id": user_id,
            "theme": theme,
            "content_type": content_type,
            "template_used": "single_image",
            "template_name": "Single Image Brief",
            "subtopics": [
                {"title": slide_title, "body": overlay_content["body"]}
            ],
            "slide_contents": {
                "slide_1": {
                    "title": slide_title,
                    "body": slide_body,
                    "structure_type": "text_overlay",
                    "visual_hint": "clean_typography, readable_text, professional_layout"
                }
            },
            "captions": {
                "post_caption": overlay_content["caption"]
            },
            "summary": [f"1. {slide_title}: {overlay_content['body']}"],
            "business_context": company_context or {"business_type": "general"},
            "meme_mode": False,
            "generation_metadata": {
                "timestamp": datetime.now().isoformat(),
                "platforms": platforms or ["instagram"],
                "intent": "image",
                "business_type": (company_context or {}).get("business_type", "generic"),
                "company_name": (company_context or {}).get("company_name"),
                "personalization_level": "high" if company_context else "generic",
                "ai_provider": "openai" if self.openai_available else ("groq" if self.groq_available else "fallback")
            }
        }
        return out

    # =====================================================================
    # DynamoDB helpers (unchanged)
    # =====================================================================
    def _parse_dynamodb_item(self, item):
        parsed = {}
        for key, value in item.items():
            if isinstance(value, dict):
                if 'S' in value:
                    parsed[key] = value['S']
                elif 'NULL' in value:
                    parsed[key] = None
                elif 'N' in value:
                    parsed[key] = float(value['N'])
                elif 'BOOL' in value:
                    parsed[key] = value['BOOL']
                elif 'M' in value:
                    parsed[key] = self._parse_dynamodb_item(value['M'])
                elif 'L' in value:
                    parsed[key] = [self._parse_dynamodb_item({'item': v})['item'] for v in value['L']]
            else:
                parsed[key] = value
        return parsed

    def get_user_business_data(self, user_id: str):
        if not DYNAMODB_AVAILABLE or not user_id:
            return None

        try:
            logger.info(f"📊 Fetching comprehensive data for: {user_id}")

            response = user_survey_table.query(
                KeyConditionExpression=Key('userId').eq(user_id),
                ScanIndexForward=False,
                Limit=1
            )

            if 'Items' in response and len(response['Items']) > 0:
                item = response['Items'][0]

                if any(isinstance(v, dict) and ('S' in v or 'N' in v or 'BOOL' in v) for v in item.values()):
                    item = self._parse_dynamodb_item(item)

                answers = item.get('answers') if isinstance(item.get('answers'), dict) else item

                brand_name = self._extract_field(answers, ['brand_name', 'company_name', 'business_name'])
                tone = self._extract_field(answers, ['tone', 'brand_tone', 'communication_tone'])
                
                color_theme_raw = self._extract_field(answers, ['color_theme', 'brand_colors', 'colors'])
                color_theme = None
                if isinstance(color_theme_raw, list):
                    color_theme = ", ".join([str(c) for c in color_theme_raw])
                elif isinstance(color_theme_raw, str) and color_theme_raw.strip():
                    raw = color_theme_raw.strip()
                    if raw.startswith("[") and raw.endswith("]"):
                        try:
                            parsed = json.loads(raw)
                            if isinstance(parsed, list):
                                color_theme = ", ".join([str(c) for c in parsed])
                            else:
                                color_theme = raw
                        except Exception:
                            color_theme = raw
                    else:
                        color_theme = raw

                goals_raw = self._extract_field(answers, ['goals', 'business_goals', 'content_goals'])
                if isinstance(goals_raw, list):
                    goals = ', '.join([str(g) for g in goals_raw])
                else:
                    goals = goals_raw
                
                business_type_raw = (
                    self._extract_field(
                        answers,
                        ['industry', 'business_type', 'industry_type', 'property_specialization']
                    )
                    or item.get('business_type')
                    or 'general'
                )

                if isinstance(business_type_raw, list) and business_type_raw:
                    business_type_raw = business_type_raw[0]

                business_type = str(business_type_raw).lower()

                # Normalize business types
                if any(k in business_type for k in ['residential', 'property', 'real estate', 'real_estate']):
                    business_type = 'real_estate'
                elif any(k in business_type for k in ['eye', 'glasses', 'optical', 'lens', 'spectacle']):
                    business_type = 'eyewear'

                business_data = {
                    'business_type': business_type.lower(),
                    'company_name': brand_name or self._extract_field(answers, ['company_name', 'business_name']),
                    'brand_name': brand_name,
                    'tone': tone,
                    'color_theme': color_theme,
                    'goals': goals,
                    'frequency': self._extract_field(answers, ['frequency', 'post_frequency']),
                    'products_services': self._extract_field(answers, ['products_services', 'services', 'offerings', 'what_you_offer', 'product_types']),
                    'target_audience': self._extract_field(answers, ['target_audience', 'primary_audience', 'audience', 'customers', 'main_customers']),
                    'brand_colors': color_theme,
                    'brand_values': self._extract_field(answers, ['key_messages', 'brand_values', 'values', 'mission', 'core_values']),
                    'unique_selling_points': self._extract_field(answers, ['usp', 'unique_selling_points', 'differentiators', 'what_makes_unique']),
                    'phone': self._extract_field(answers, ['phone', 'contact_number', 'mobile', 'contact_phone']),
                    'website': self._extract_field(answers, ['website', 'website_url', 'url', 'web_address', 'contact_details']),
                    'email': self._extract_field(answers, ['email', 'contact_email', 'business_email']),
                    'address': self._extract_field(answers, ['address', 'location', 'business_address']),
                    'tagline': self._extract_field(answers, ['tagline', 'slogan', 'brand_tagline']),
                    'has_logo': item.get('has_logo', False),
                    'logo_s3_url': item.get('logo_s3_url', ''),
                    'ai_images': item.get('ai_images', True),
                    'post_schedule_time': self._extract_field(answers, ['post_schedule_time', 'schedule_time']),
                    'raw_answers': answers
                }

                if not business_data.get('brand_colors') and business_data.get('color_theme'):
                    business_data['brand_colors'] = business_data['color_theme']
    
                if isinstance(business_data['has_logo'], str):
                    business_data['has_logo'] = business_data['has_logo'].lower() == 'true'

                logger.info(f"✅ Loaded comprehensive profile:")
                logger.info(f"   Brand: {business_data.get('brand_name', 'N/A')}")
                logger.info(f"   Business Type: {business_data.get('business_type', 'N/A')}")
                logger.info(f"   Tone: {business_data.get('tone', 'N/A')}")
                logger.info(f"   Products/Services: {business_data.get('products_services', 'N/A')}")
                
                return business_data

            logger.warning(f"⚠️ No data found for {user_id}")
            return None

        except Exception as e:
            logger.error(f"❌ Error fetching data: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def _extract_field(self, data, field_options):
        for field in field_options:
            if field in data:
                value = data[field]
                if value and str(value).strip() and str(value).lower() not in ['null', 'none', '', 'n/a']:
                    return value
        return None

    # =====================================================================
    # Business context block
    # =====================================================================
    def create_business_context_block(self, company_context: Optional[Dict], content_type: str) -> str:
        if not company_context:
            return "BUSINESS CONTEXT: General business content (no specific profile available)"

        business_type = company_context.get('business_type', 'general').lower()
        company_name = company_context.get('company_name', 'the company')
        style_guide = BUSINESS_STYLES.get(business_type, BUSINESS_STYLES.get('general'))

        context_parts = []
        context_parts.append("=" * 80)
        context_parts.append("BUSINESS PROFILE & CONTEXT")
        context_parts.append("=" * 80)

        if company_name:
            context_parts.append(f"\n🏢 COMPANY: {company_name}")

        context_parts.append(f"📊 INDUSTRY: {business_type.upper()}")

        if company_context.get('products_services'):
            context_parts.append(f"\n💼 WHAT THEY OFFER:")
            context_parts.append(f"{company_context['products_services']}")

        if company_context.get('target_audience'):
            context_parts.append(f"\n👥 TARGET AUDIENCE:")
            context_parts.append(f"{company_context['target_audience']}")

        if company_context.get('unique_selling_points'):
            context_parts.append(f"\n⭐ UNIQUE VALUE:")
            context_parts.append(f"{company_context['unique_selling_points']}")

        if company_context.get('brand_values'):
            context_parts.append(f"\n💎 BRAND VALUES:")
            context_parts.append(f"{company_context['brand_values']}")

        if company_context.get('tagline'):
            context_parts.append(f"\n🎯 TAGLINE: {company_context['tagline']}")

        context_parts.append(f"\n🎨 VISUAL BRANDING:")
        if company_context.get('brand_colors'):
            context_parts.append(f"   Colors: {company_context['brand_colors']}")
        else:
            context_parts.append(f"   Colors: {style_guide['color_palette']}")

        if company_context.get('has_logo'):
            context_parts.append(f"   Logo: Available (include brand logo in design)")

        context_parts.append(f"   Theme: {style_guide['visual_theme']}")
        context_parts.append(f"   Font Style: {style_guide['font_style']}")
        context_parts.append(f"   Imagery: {style_guide['imagery']}")

        content_config = CONTENT_TYPES.get(content_type, {})
        context_parts.append(f"\n📝 CONTENT TONE:")
        context_parts.append(f"   Style: {content_config.get('tone', 'professional')}")
        context_parts.append(f"   Approach: {content_config.get('approach', 'informative')}")

        context_parts.append("=" * 80)
        return "\n".join(context_parts)

    # =====================================================================
    # Template selection
    # =====================================================================
    def select_template(self, theme, content_type, business_context, num_slides):
        try:
            business_type = (business_context or {}).get('business_type', '').lower() if business_context else ''
            candidates = []

            for tid, t in TEMPLATES.items():
                if content_type in t['content_types']:
                    min_slides, max_slides = t['slides']
                    if min_slides <= num_slides <= max_slides:
                        candidates.append((tid, t))

            if business_type in ['b2b', 'technology', 'enterprise', 'saas']:
                for tid, t in candidates:
                    if 'stats' in tid or 'case_study' in tid:
                        return tid, t
            elif business_type in ['b2c', 'retail', 'consumer', 'restaurant', 'eyewear']:
                for tid, t in candidates:
                    if 'listicle' in tid or 'quick_tips' in tid:
                        return tid, t
            elif business_type in ['education', 'edtech']:
                for tid, t in candidates:
                    if 'step_by_step' in tid or 'faq' in tid:
                        return tid, t

            theme_lc = (theme or '').lower()
            for tid, t in candidates:
                if any(k in theme_lc for k in tid.split('_')):
                    return tid, t

            if candidates:
                return random.choice(candidates)

        except Exception as e:
            logger.warning(f"Template selection error: {e}")

        return 'listicle', TEMPLATES['listicle']

    # =====================================================================
    # AI generation functions
    # =====================================================================
    def _generate_subtopics(self, theme, content_type, num_subtopics, company_context, meme_mode, template=None):
        """
        Generate text content for carousel slides that will be overlaid on images.
        Each subtopic contains title + body text ready for image overlay.
        """
        
        # Build rich business context
        business_context_text = ""
        if company_context:
            brand_name = company_context.get('brand_name') or company_context.get('company_name', 'the company')
            business_type = company_context.get('business_type', 'general')
            tone = company_context.get('tone', 'professional')
            goals = company_context.get('goals', '')
            products = company_context.get('products_services', '')
            audience = company_context.get('target_audience', '')
            values = company_context.get('brand_values', '')

            business_context_text = f"""
BUSINESS PROFILE:
- Brand Name: {brand_name}
- Industry: {business_type}
- Brand Tone: {tone}
- Content Goals: {goals}
- What They Offer: {products}
- Target Audience: {audience}
- Brand Values: {values}
"""

        # CAROUSEL SLIDE TEXT GENERATION PROMPT
        prompt = f"""You are creating text content for a {num_subtopics}-slide Instagram carousel. Each slide will have an IMAGE with TEXT OVERLAID on it.

{business_context_text}

CAROUSEL THEME: "{theme}"
CONTENT TYPE: {content_type}

TASK: Create {num_subtopics} slides with overlay-ready text content.

Each slide needs:
1. **TITLE**: Eye-catching headline (6-12 words max)
   - Should be scannable and memorable
   - Use numbers, power words, or questions
   - Brand-aligned tone: {company_context.get('tone', 'professional') if company_context else 'professional'}

2. **BODY**: Supporting text (15-30 words)
   - Explain the key point clearly
   - Use bullet points if listing features
   - Keep it concise for readability on images

REQUIREMENTS:
✅ Each slide must be DIRECTLY about "{theme}"
✅ Each slide covers a DIFFERENT angle/benefit/aspect
✅ Titles must be SPECIFIC, not generic
✅ Body text must be SHORT and SCANNABLE
✅ Use natural, human language
✅ Consider the target audience: {company_context.get('target_audience', 'general audience') if company_context else 'general audience'}

EXAMPLES OF GOOD CAROUSEL SLIDES:

For "get your best specs in best price" (Eyewear):

Slide 1:
Title: "Premium Lenses at 40% Lower Cost"
Body: "Direct manufacturing means no middleman markups. Same quality as luxury optical stores, significantly better prices."

Slide 2:
Title: "Free Eye Test with Every Purchase"
Body: "Professional eye examination included. Know your exact prescription before choosing your perfect frames."

Slide 3:
Title: "1000+ Frame Styles to Choose From"
Body: "Classic to trendy, formal to casual. Find frames that match your personality and lifestyle perfectly."

For "hiring freshers for software roles" (Tech):

Slide 1:
Title: "Learn From Senior Engineers Daily"
Body: "Paired with experienced mentors. Get code reviews, career guidance, and hands-on project experience from day one."

Slide 2:
Title: "Work on Real Products, Not Tutorials"
Body: "Build features used by millions of users. Ship code to production in your first month with us."

FORMAT:
Return ONLY a valid JSON array:
[
  {{"title": "Slide 1 title", "body": "Slide 1 body text"}},
  {{"title": "Slide 2 title", "body": "Slide 2 body text"}},
  ...
]

Make every slide DIRECTLY RELEVANT and SCANNABLE for image overlay."""

        # Call AI API with fallback
        response_content = self._call_ai_api(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.75,
            max_tokens=2500
        )
        
        if response_content:
            try:
                content = self._extract_json(response_content)
                if content:
                    subtopics = json.loads(content)
                    
                    # Validate: titles not too long
                    long_titles = [s for s in subtopics if len(s.get('title', '').split()) > 15]
                    if len(long_titles) > len(subtopics) * 0.3:
                        logger.warning(f"⚠️ Too many long titles, retrying...")
                        raise Exception("Titles too long for overlay")
                    
                    # Validate: body text not too long
                    long_bodies = [s for s in subtopics if len(s.get('body', '').split()) > 40]
                    if len(long_bodies) > len(subtopics) * 0.3:
                        logger.warning(f"⚠️ Body text too long, retrying...")
                        raise Exception("Body text too long for overlay")
                    
                    # Validate diversity
                    titles = [s.get('title', '') for s in subtopics]
                    if len(set(titles)) < len(titles) * 0.9:
                        logger.warning("⚠️ Subtopics not diverse enough, retrying...")
                        raise Exception("Low diversity detected")
                    
                    logger.info(f"✅ Generated {len(subtopics)} overlay-ready carousel slides")
                    return subtopics[:num_subtopics]
                    
            except Exception as e:
                logger.warning(f"⚠️ AI carousel generation failed: {e}, using fallback")

        return self._create_fallback_subtopics(theme, content_type, num_subtopics, company_context)

    def _create_fallback_subtopics(self, theme, content_type, num_subtopics, company_context=None):
        """Create overlay-ready fallback subtopics with short, scannable text"""
        
        theme_lower = (theme or "").lower()
        business_type = (company_context or {}).get('business_type', 'general').lower()
        business_name = (company_context or {}).get('brand_name') or (company_context or {}).get('company_name', '')
        products = (company_context or {}).get('products_services', '')
        
        # Detect context from theme
        if any(word in theme_lower for word in ['price', 'cost', 'affordable', 'cheap', 'deal', 'offer', 'discount']):
            # Price/value context - short overlay text
            angles = [
                ("Best Prices, Premium Quality", f"Get top-tier products without the premium price tag. Quality you can trust at prices you'll love."),
                ("No Hidden Fees or Charges", f"What you see is what you pay. Transparent pricing with everything included upfront."),
                ("Price Match Guarantee", f"Found it cheaper elsewhere? We'll match the price. Your satisfaction is our priority."),
                ("Bundle & Save Up to 30%", f"Combine items for maximum value. More products, bigger savings."),
                ("Limited Time Special Offers", f"Exclusive deals and flash sales. Don't miss out on incredible savings."),
            ]
        elif any(word in theme_lower for word in ['hiring', 'recruit', 'candidate', 'job', 'talent', 'employee', 'fresher']):
            # Hiring context
            angles = [
                ("Skills Matter More Than Degrees", f"We evaluate what you can do, not where you studied. Real ability beats credentials."),
                ("Fast-Track Interview Process", f"Quick decisions, clear communication. Hear back within a week."),
                ("Competitive Pay & Benefits", f"Market-leading compensation plus health, wellness, and growth perks."),
                ("Learn While You Earn", f"Structured training programs and mentorship. Grow your career with us."),
                ("Flexible Work Options Available", f"Remote, hybrid, or in-office. We support your preferred work style."),
            ]
        elif any(word in theme_lower for word in ['specs', 'glasses', 'eyewear', 'lens', 'frames']):
            # Eyewear specific
            angles = [
                ("1000+ Styles to Choose From", f"Classic to trendy, formal to casual. Find your perfect look."),
                ("Free Eye Test Included", f"Professional examination with every purchase. Know your prescription."),
                ("Premium Lenses, Lower Prices", f"Direct manufacturing eliminates middlemen. Save up to 40% on quality lenses."),
                ("Try Before You Buy", f"Virtual try-on or home trial. See how they look before committing."),
                ("1-Year Warranty on All Frames", f"Quality guaranteed. Free repairs or replacement if issues arise."),
            ]
        elif any(word in theme_lower for word in ['product', 'feature', 'launch', 'new', 'release']):
            # Product context
            angles = [
                ("Key Features That Matter", f"Practical capabilities designed for real-world use. Solve actual problems."),
                ("Get Started in Minutes", f"Simple setup, intuitive interface. No technical expertise required."),
                ("Proven Results From Users", f"Join thousands of satisfied customers. See real success stories."),
                ("Premium Quality, Fair Pricing", f"Professional-grade without the premium markup. Value you deserve."),
                ("Free Updates & Support", f"Continuous improvements included. Dedicated team ready to help."),
            ]
        else:
            # Generic but contextual
            product_name = products if products else (business_name if business_name else theme)
            angles = [
                (f"Why Choose {product_name}?", f"Unique advantages that set us apart. Quality and value combined."),
                ("Save Time, Boost Efficiency", f"Streamlined solutions for faster results. Do more in less time."),
                ("Quality You Can Trust", f"Premium standards, reliable performance. Excellence in every detail."),
                ("Easy to Get Started", f"Simple implementation, user-friendly. Begin your journey today."),
                ("Proven Track Record", f"Trusted by satisfied customers. Join our growing community."),
            ]
        
        subtopics = []
        for i in range(min(num_subtopics, len(angles))):
            angle_title, angle_body = angles[i]
            subtopics.append({
                'title': angle_title,
                'body': angle_body
            })
        
        # Add more if needed
        while len(subtopics) < num_subtopics:
            subtopics.append({
                'title': f"Benefit #{len(subtopics) + 1}",
                'body': f"Another valuable reason to choose {theme}. Quality and excellence."
            })
        
        logger.info(f"✅ Created {len(subtopics)} overlay-ready fallback slides")
        return subtopics

    def generate_slide_content(self, subtopic, content_type, template, structure_type, visual_hint, company_context=None):
        """Generate individual slide content"""
        title = subtopic.get('header') or subtopic.get('title')
        body = subtopic.get('body')

        business_text = ""
        if company_context:
            business_text = f"""
Business: {company_context.get('company_name', 'the company')}
Industry: {company_context.get('business_type', 'general')}
Target Audience: {company_context.get('target_audience', 'general audience')}
"""

        prompt = f"""Generate carousel slide content.

{business_text}

Slide Topic: {title}
Description: {body}

Template: {template['name']}
Visual Style: {visual_hint}
Content Type: {content_type}

Text Limits: 
- Title: Max {template['text_limits']['title']} words
- Body: Max {template['text_limits']['body']} words

Create punchy, Instagram-optimized content that's specific to the business context.

Output format (JSON only):
{{
  "title": "...",
  "body": ["line1", "line2", "line3"]
}}
"""

        response_content = self._call_ai_api(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300
        )
        
        if response_content:
            try:
                content = self._extract_json(response_content)
                if content:
                    slide = json.loads(content)
                    slide['structure_type'] = structure_type
                    slide['visual_hint'] = visual_hint
                    return slide
            except Exception as e:
                logger.warning(f"Slide content generation failed: {e}")

        return {"title": title, "body": [body], "structure_type": structure_type, "visual_hint": visual_hint}

    def _generate_caption(self, subtopics_data, theme, content_type, company_context, template=None):
        """Generate contextual, engaging social media caption"""
        
        titles = []
        for sub in subtopics_data:
            title = sub.get('title') or sub.get('header', '')
            if title and title not in titles:
                titles.append(title)
        
        hashtags = self._generate_hashtags(theme, content_type, company_context)
        hashtags_text = " ".join(hashtags)

        brand_tone = 'professional'
        cta = "💬 What are your thoughts? Share in the comments!"
        
        if company_context:
            brand_tone = company_context.get('tone', 'professional')
            website = company_context.get('website') or company_context.get('contact_details')
            phone = company_context.get('phone')
            brand_name = company_context.get('brand_name') or company_context.get('company_name')
            
            if website:
                # Extract clean website URL
                website_clean = website.split('\n')[0].strip() if '\n' in website else website.strip()
                cta = f"🌐 Learn more: {website_clean}"
            elif phone:
                cta = f"📞 Contact us: {phone}"
            elif brand_name:
                cta = f"✨ Follow {brand_name} for more insights!"

        business_text = ""
        if company_context:
            business_text = f"""
BRAND PROFILE:
- Name: {company_context.get('brand_name') or company_context.get('company_name', '')}
- Industry: {company_context.get('business_type', '')}
- Products/Services: {company_context.get('products_services', '')}
- Tone: {brand_tone}
- Target Audience: {company_context.get('target_audience', '')}
- Goals: {company_context.get('goals', '')}
"""

        slides_summary = "\n".join([f"→ {title}" for title in titles[:5]])
        
        caption_prompt = f"""Write a compelling social media caption for this carousel.

THEME: "{theme}"

{business_text}

CAROUSEL COVERS:
{slides_summary}

REQUIREMENTS:
- Tone: {brand_tone} (authentic to this brand)
- Length: 100-180 words
- Style: Natural, conversational, human-written
- Hook: Start with attention-grabbing statement about "{theme}"
- Value: Explain why this carousel matters to the audience
- Engagement: Encourage swipe-through
- Emojis: Use 3-5 relevant emojis naturally
- End with: {cta}
- Add: {hashtags_text}

AVOID:
❌ Generic AI phrases like "Game-changer", "Revolutionizing"
❌ Excessive exclamation marks
❌ Starting with "Are you ready to..."

Make it SPECIFIC to "{theme}" and this business."""

        response_content = self._call_ai_api(
            messages=[{"role": "user", "content": caption_prompt}],
            temperature=0.7,
            max_tokens=400
        )
        
        if response_content:
            caption = response_content.strip()
            
            # Ensure hashtags and CTA are included
            if not any(h in caption for h in hashtags[:3]):
                caption += f"\n\n{hashtags_text}"
            
            if cta not in caption and '🌐' not in caption and '📞' not in caption:
                caption += f"\n\n{cta}"
            
            logger.info("✅ Generated contextual caption")
            return caption

        # Fallback caption
        hook = f"🎯 {theme}"
        if brand_tone == 'casual':
            hook = f"Hey! Check this out → {theme}"
        elif brand_tone == 'premium':
            hook = f"✨ Discover: {theme}"
        
        return f"{hook}\n\nSwipe to explore more! 👉\n\n{hashtags_text}\n\n{cta}"

    def _generate_hashtags(self, theme: str, content_type: str, company_context: Optional[Dict] = None) -> List[str]:
        """Generate contextual, relevant hashtags"""
        base = []
        
        if company_context:
            brand_name = company_context.get('brand_name') or company_context.get('company_name')
            if brand_name:
                clean_name = brand_name.replace(' ', '')
                base.append(f"#{clean_name}")
            
            business_type = company_context.get('business_type', '').lower()
            if business_type and business_type != 'general':
                base.append(f"#{business_type.capitalize()}")
            
            goals = company_context.get('goals', '')
            if goals:
                if 'product update' in goals.lower():
                    base.extend(['#ProductUpdate', '#NewFeature'])
                if 'education' in goals.lower():
                    base.extend(['#LearnWithUs', '#EducationalContent'])
                if 'offer' in goals.lower() or 'promotion' in goals.lower():
                    base.extend(['#SpecialOffer', '#LimitedTime'])

        # Extract keywords from theme
        words = [w for w in (theme or "").replace(",", " ").replace("-", " ").split() 
                 if len(w) > 3 and w.lower() not in ['with', 'from', 'this', 'that', 'your', 'their', 'about', 'have', 'more', 'best']]
        theme_tags = [f"#{w.capitalize()}" for w in words[:5]]

        type_tags = {
            "Informative": ["#DidYouKnow", "#LearnMore", "#Knowledge"],
            "Inspirational": ["#Motivation", "#Success", "#Inspiration"],
            "Promotional": ["#NewLaunch", "#CheckItOut", "#Trending"],
            "Educational": ["#Tutorial", "#HowTo", "#SkillUp"],
            "Engaging": ["#Discussion", "#CommunityFirst", "#LetsTalk"]
        }

        content_tags = type_tags.get(content_type, ["#ContentCreation"])
        
        all_tags = base + theme_tags + content_tags
        unique_tags = []
        seen = set()
        for tag in all_tags:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                unique_tags.append(tag)
                seen.add(tag_lower)
        
        return unique_tags[:12]

    # =====================================================================
    # MAIN ENTRY (WITH INTENT ROUTING)
    # =====================================================================
    def generate_complete_content(
        self,
        theme: str,
        content_type: str,
        num_subtopics: int,
        platforms: List[str],
        company_context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        meme_mode: bool = False
    ) -> Dict[str, Any]:

        logger.info(f"🎨 Generating content: {content_type}")
        logger.info(f"👤 User: {user_id}")
        logger.info(f"📝 Theme: {theme}")

        # Fetch business data if needed
        if user_id and not company_context:
            company_context = self.get_user_business_data(user_id)

        # ✅ Intent routing
        intent = self.detect_intent(theme)
        if intent == "image":
            logger.info("🖼️ Intent detected: SINGLE IMAGE with text overlay")
            content_output = self.generate_image_mode_content(
                theme=theme,
                content_type=content_type,
                company_context=company_context,
                user_id=user_id,
                platforms=platforms
            )
            try:
                with open("content_details.json", "w") as f:
                    json.dump(content_output, f, indent=4)
                logger.info("✅ Saved content_details.json (single image with text overlay)")
            except Exception as e:
                logger.error(f"Failed to save: {e}")
            return content_output

        # Carousel pipeline
        logger.info("📸 Intent detected: CAROUSEL with multiple slides")
        if company_context:
            logger.info("✅ Using business profile:")
            logger.info(f"   Company: {company_context.get('company_name', 'N/A')}")
            logger.info(f"   Industry: {company_context.get('business_type', 'N/A')}")
            logger.info(f"   Products: {company_context.get('products_services', 'N/A')}")
        else:
            logger.warning("⚠️ No business context available - using generic approach")

        # Select template
        template_id, template = self.select_template(theme, content_type, company_context, num_subtopics)
        logger.info(f"🧩 Template: {template_id} ({template['name']})")

        # Generate diverse subtopics
        subtopics_data = self._generate_subtopics(
            theme, content_type, num_subtopics, company_context, meme_mode, template
        )

        # Build slide contents
        slide_contents = {}
        for i, subtopic in enumerate(subtopics_data):
            slide_key = f"slide_{i+1}"
            
            slide_title = subtopic.get('title') or subtopic.get('header') or theme
            slide_body = subtopic.get('body', f'Content for slide {i+1}')
            
            if isinstance(slide_body, str):
                slide_body = [slide_body]
            
            slide_contents[slide_key] = {
                "title": slide_title,
                "body": slide_body,
                "structure_type": "text_overlay",  # Mark as text for overlay on images
                "visual_hint": "clean_typography, scannable_text, professional_layout"
            }

        # Generate caption
        post_caption = self._generate_caption(subtopics_data, theme, content_type, company_context, template)
        
        # Create summary
        summary = []
        for i, sub in enumerate(subtopics_data, 1):
            title = sub.get('title') or sub.get('header') or theme
            summary.append(f"{i}. {title}")

        # Format subtopics
        formatted_subtopics = []
        for sub in subtopics_data:
            formatted_subtopics.append({
                "title": sub.get('title') or sub.get('header') or theme,
                "body": sub.get('body', 'Content description')
            })

        content_output = {
            "status": "success",
            "user_id": user_id,
            "theme": theme,
            "content_type": content_type,
            "template_used": template_id,
            "template_name": template['name'],
            "subtopics": formatted_subtopics,
            "slide_contents": slide_contents,
            "captions": {"post_caption": post_caption},
            "summary": summary,
            "business_context": company_context or {"business_type": "general"},
            "meme_mode": meme_mode,
            "generation_metadata": {
                "timestamp": datetime.now().isoformat(),
                "platforms": platforms,
                "intent": "carousel",
                "business_type": company_context.get('business_type') if company_context else 'general',
                "company_name": company_context.get('company_name') if company_context else 'N/A',
                "has_logo": company_context.get('has_logo', False) if company_context else False,
                "has_colors": bool(company_context.get('brand_colors')) if company_context else False,
                "has_target_audience": bool(company_context.get('target_audience')) if company_context else False,
                "personalization_level": "high" if company_context else "generic",
                "ai_provider": "openai" if self.openai_available else ("groq" if self.groq_available else "fallback")
            }
        }

        try:
            with open("content_details.json", "w") as f:
                json.dump(content_output, f, indent=4)
            logger.info("✅ Saved content_details.json with full business context")
        except Exception as e:
            logger.error(f"Failed to save: {e}")

        return content_output

    # =====================================================================
    # Helper methods
    # =====================================================================
    def _create_summary(self, subtopics_data: List[Dict]) -> List[str]:
        summary = []
        for i, sub in enumerate(subtopics_data, 1):
            header = sub.get('header') or sub.get('title')
            key_points = sub.get('key_points', [])
            if key_points and isinstance(key_points, list) and len(key_points) > 0:
                point = key_points[0]
            else:
                point = header
            summary.append(f"{i}. {header}: {point}")
        return summary[:3]

    def _extract_json(self, text):
        """Extract JSON from AI response"""
        import re
        match = re.search(r'(\[.*?\]|\{.*?\})', text, re.DOTALL)
        if match:
            return match.group(1)
        return None