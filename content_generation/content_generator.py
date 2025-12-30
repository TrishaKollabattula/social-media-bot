# content_generation/content_generator.py - ENV VARIABLE FIXED
# ✅ Groq API key from environment only
# ✅ Supports ALL 5 content types perfectly
# ✅ User business data integration
# ✅ Meme mode support

import os
from typing import Dict, List, Any, Optional
import json
from datetime import datetime
import logging
import boto3
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv
from .content_templates import TEMPLATES
import random

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

# Content type configurations
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


class ContentGenerator:
    """Production content generation engine"""

    def __init__(self):
        self.client = None
        self.api_key_valid = False

        if not GROQ_AVAILABLE:
            logger.error("❌ Groq not installed")
            return

        # ✅ ENV ONLY
        api_key = os.getenv("GROQ_API_KEY")

        if not api_key:
            logger.error("❌ GROQ_API_KEY not found in environment variables!")
            logger.error("   Please add GROQ_API_KEY=your_key_here to your .env file")
            return

        if "..." in api_key or len(api_key) < 20:
            logger.error("❌ Invalid GROQ_API_KEY format in environment")
            return

        try:
            logger.info("🔑 Initializing Groq with API key from ENV...")
            self.client = Groq(api_key=api_key)

            # Test API key validity
            test = self.client.chat.completions.create(
                messages=[{"role": "user", "content": "test"}],
                model="llama-3.1-8b-instant",
                max_tokens=10
            )

            if test and test.choices:
                logger.info("✅ Groq API key validated successfully")
                self.api_key_valid = True

        except Exception as e:
            logger.error(f"❌ Groq initialization failed: {e}")
            logger.error("   Check your GROQ_API_KEY in environment / .env file")


    def _parse_dynamodb_item(self, item):
        """Parse DynamoDB response"""
        parsed = {}
        for key, value in item.items():
            if isinstance(value, dict):
                if 'S' in value:
                    parsed[key] = value['S']
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
        """Fetch complete business data from UserSurveyData"""
        if not DYNAMODB_AVAILABLE or not user_id:
            return None

        try:
            logger.info(f"📊 Fetching data for: {user_id}")

            response = user_survey_table.query(
                KeyConditionExpression=Key('userId').eq(user_id),
                ScanIndexForward=False,
                Limit=1
            )

            if 'Items' in response and len(response['Items']) > 0:
                item = response['Items'][0]

                # Parse if needed
                if any(isinstance(v, dict) and ('S' in v or 'N' in v or 'BOOL' in v) for v in item.values()):
                    item = self._parse_dynamodb_item(item)

                answers = item.get('answers', {})

                business_data = {
                    'business_type': item.get('business_type', 'general'),
                    'company_name': self._extract_field(answers, ['company_name', 'business_name']),
                    'products_services': self._extract_field(answers, ['products_services', 'services', 'offerings']),
                    'target_audience': self._extract_field(answers, ['target_audience', 'primary_audience', 'audience']),
                    'brand_colors': self._extract_field(answers, ['brand_colors', 'color_theme', 'colors']),
                    'brand_values': self._extract_field(answers, ['key_messages', 'brand_values', 'values']),
                    'phone': self._extract_field(answers, ['phone', 'contact_number', 'mobile']),
                    'website': self._extract_field(answers, ['website', 'website_url', 'url']),
                    'has_logo': item.get('has_logo', False),
                    'logo_s3_url': item.get('logo_s3_url', '')
                }
#commit
                # Convert has_logo to boolean
                if isinstance(business_data['has_logo'], str):
                    business_data['has_logo'] = business_data['has_logo'].lower() == 'true'

                logger.info(f"✅ Loaded: {business_data['business_type']}")
                if business_data.get('company_name'):
                    logger.info(f"   Company: {business_data['company_name']}")
                if business_data.get('brand_colors'):
                    logger.info(f"   Colors: {business_data['brand_colors']}")

                return business_data

            logger.warning(f"⚠️ No data found for {user_id}")
            return None

        except Exception as e:
            logger.error(f"❌ Error fetching data: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def _extract_field(self, data, field_options):
        """Extract field with multiple name options"""
        for field in field_options:
            if field in data:
                value = data[field]
                if value and str(value).strip() and str(value).lower() not in ['null', 'none', '']:
                    return value
        return None

    def get_branding_context(self, company_context):
        """
        Validate and extract branding info, use defaults if missing.
        """
        branding = {
            "logo": company_context.get("logo_s3_url") if company_context and company_context.get("has_logo") else None,
            "colors": company_context.get("brand_colors") if company_context and company_context.get("brand_colors") else "#ffd700, #000000",
            "fonts": company_context.get("fonts") if company_context and company_context.get("fonts") else "sans-serif",
            "style": company_context.get("image_style") if company_context and company_context.get("image_style") else "modern, clean, professional"
        }
        return branding

    def select_template(self, theme, content_type, business_context, num_slides):
        """
        Selects the best template based on content_type, business_type, and num_slides.
        Fallback: 'listicle'.
        """
        try:
            business_type = (business_context or {}).get('business_type', '').lower() if business_context else ''
            candidates = []
            for tid, t in TEMPLATES.items():
                if content_type in t['content_types']:
                    min_slides, max_slides = t['slides']
                    if min_slides <= num_slides <= max_slides:
                        candidates.append((tid, t))
            # Prefer by business_type
            if business_type in ['b2b', 'technology', 'enterprise']:
                for tid, t in candidates:
                    if 'stats' in tid or 'case_study' in tid:
                        return tid, t
            elif business_type in ['b2c', 'retail', 'consumer']:
                for tid, t in candidates:
                    if 'listicle' in tid or 'quick_tips' in tid:
                        return tid, t
            # Prefer by theme keywords
            theme_lc = (theme or '').lower()
            for tid, t in candidates:
                if any(k in theme_lc for k in tid.split('_')):
                    return tid, t
            if candidates:
                return random.choice(candidates)
        except Exception as e:
            logger.warning(f"Template selection error: {e}")
        # Fallback
        return 'listicle', TEMPLATES['listicle']

    def validate_content_quality(self, subtopics, slide_contents, template):
        """
        Validate text length, uniqueness, structure, and non-empty values.
        """
        issues = []
        # Check structure
        expected = template['structure']
        if len(subtopics) != len(expected):
            issues.append(f"Subtopic count {len(subtopics)} != template structure {len(expected)}")
        # Check text limits and empties
        for idx, (sub, struct) in enumerate(zip(subtopics, expected)):
            title = sub.get('header') or sub.get('title')
            body = sub.get('body')
            if not title or not body:
                issues.append(f"Empty title/body at slide {idx+1}")
            if len(title.split()) > template['text_limits']['title']:
                issues.append(f"Title too long at slide {idx+1}")
            if len(body.split()) > template['text_limits']['body']:
                issues.append(f"Body too long at slide {idx+1}")
        # Check uniqueness (basic keyword overlap)
        titles = [sub.get('header') or sub.get('title') for sub in subtopics]
        if len(set(titles)) < len(titles):
            issues.append("Duplicate or similar subtopic titles detected")
        # Check slide_contents
        for k, v in slide_contents.items():
            if not v or not v.get('title') or not v.get('body'):
                issues.append(f"Empty slide content for {k}")
        return (len(issues) == 0), issues

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
        logger.info(f"🎨 Generating: {content_type}")
        logger.info(f"🎭 Meme: {'ON' if meme_mode else 'OFF'}")
        logger.info(f"👤 User: {user_id}")
        if user_id and not company_context:
            company_context = self.get_user_business_data(user_id)
        # --- TEMPLATE SELECTION ---
        try:
            template_id, template = self.select_template(theme, content_type, company_context, num_subtopics)
            logger.info(f"🧩 Template selected: {template_id} ({template['name']})")
        except Exception as e:
            logger.warning(f"Template selection failed: {e}")
            template_id, template = 'listicle', TEMPLATES['listicle']
        # --- SUBTOPIC GENERATION ---
        for attempt in range(2):
            subtopics_data = self._generate_subtopics(
                theme, content_type, num_subtopics, company_context, meme_mode, template
            )
            # Enforce template structure order
            for i, struct in enumerate(template['structure'][:num_subtopics]):
                if i < len(subtopics_data):
                    subtopics_data[i]['structure_type'] = struct
            # --- SLIDE CONTENT GENERATION ---
            slide_contents = {}
            for i, subtopic in enumerate(subtopics_data):
                slide_key = f"slide_{i+1}"
                slide_contents[slide_key] = self.generate_slide_content(
                    subtopic, content_type, template, template['structure'][i], template['visual_hints']
                )
                slide_contents[slide_key]['structure_type'] = template['structure'][i]
                slide_contents[slide_key]['visual_hint'] = template['visual_hints']
            # --- VALIDATION ---
            valid, issues = self.validate_content_quality(subtopics_data, slide_contents, template)
            logger.info(f"Validation: {'PASS' if valid else 'FAIL'}; Issues: {issues}")
            if valid or attempt == 1:
                break
        # --- CAPTION GENERATION ---
        post_caption = self._generate_caption(subtopics_data, theme, content_type, company_context, template)
        summary = self._create_summary(subtopics_data)
        # --- JSON OUTPUT ---
        content_output = {
            "status": "success" if valid else "warning",
            "user_id": user_id,
            "theme": theme,
            "content_type": content_type,
            "template_used": template_id,
            "template_name": template['name'],
            "subtopics": subtopics_data,
            "slide_contents": slide_contents,
            "captions": {"post_caption": post_caption},
            "summary": summary,
            "business_context": company_context,
            "meme_mode": meme_mode,
            "generation_metadata": {
                "timestamp": datetime.now().isoformat(),
                "platforms": platforms,
                "business_type": company_context.get('business_type', 'N/A') if company_context else 'N/A',
                "has_logo": company_context.get('has_logo', False) if company_context else False,
                "has_colors": bool(company_context.get('brand_colors')) if company_context else False,
                "groq_used": self.api_key_valid,
                "user_id": user_id,
                "template_structure": template['structure'],
                "content_type": content_type,
                "validation_passed": valid
            }
        }
        try:
            with open("content_details.json", "w") as f:
                json.dump(content_output, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save content_details.json: {e}")
        logger.info(f"✅ Content generated!")
        return content_output

    def _generate_subtopics(self, theme, content_type, num_subtopics, company_context, meme_mode, template=None):
        """
        Generate subtopics using Groq, guided by template structure.
        """
        if not self.api_key_valid or not template:
            return self._create_fallback_subtopics(theme, content_type, num_subtopics)
        structure = template['structure'][:num_subtopics]
        prompt = (
            f"Generate {num_subtopics} DISTINCTLY DIFFERENT subtopics following this structure: {structure}.\n"
            f"Each subtopic must offer a UNIQUE ANGLE - no overlapping ideas.\n"
            f"For '{theme}' in {content_type} style.\n"
            f"Requirements:\n"
            f"- Each subtopic should be 1-2 sentences max\n"
            f"- Focus on different: timeframes, perspectives, use cases, benefits, challenges\n"
            f"- Avoid: similar concepts, generic statements, repetitive phrasing\n"
            f"- Make scannable and Instagram-carousel friendly\n"
            f"Return a JSON array: [{{'header':..., 'body':...}}] in the same order as structure."
        )
        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant",
                temperature=0.8,
                max_tokens=2000
            )
            content = response.choices[0].message.content.strip()
            content = self._extract_json(content)
            if content:
                subtopics = json.loads(content)
                # Enforce order and uniqueness
                for i, struct in enumerate(structure):
                    if i < len(subtopics):
                        subtopics[i]['structure_type'] = struct
                return subtopics[:num_subtopics]
        except Exception as e:
            logger.warning(f"Subtopic generation failed: {e}")
        return self._create_fallback_subtopics(theme, content_type, num_subtopics)

    def generate_slide_content(self, subtopic, content_type, template, structure_type, visual_hint):
        """
        Generate slide content with template constraints.
        """
        title = subtopic.get('header') or subtopic.get('title')
        body = subtopic.get('body')
        prompt = (
            f"Generate slide content for: {title}\n"
            f"Template: {template['name']}\n"
            f"Visual hint: {visual_hint}\n"
            f"Text limits: Title max {template['text_limits']['title']} words, Body max {template['text_limits']['body']} words\n"
            f"Style: {content_type}\n"
            f"Make it punchy, visual-ready, and Instagram-optimized.\n"
            f"Output JSON: {{'title':..., 'body': ['line1', 'line2']}}"
        )
        try:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant",
                temperature=0.7,
                max_tokens=300
            )
            content = response.choices[0].message.content.strip()
            content = self._extract_json(content)
            if content:
                slide = json.loads(content)
                slide['structure_type'] = structure_type
                slide['visual_hint'] = visual_hint
                return slide
        except Exception as e:
            logger.warning(f"Slide content generation failed: {e}")
        # Fallback
        return {"title": title, "body": [body], "structure_type": structure_type, "visual_hint": visual_hint}

    def _generate_caption(self, subtopics_data, theme, content_type, company_context, template=None):
        """
        Generate caption referencing template narrative arc and CTA.
        """
        headers = [sub['header'] for sub in subtopics_data]
        hashtags = self._generate_hashtags(theme, content_type)
        hashtags_text = " ".join(hashtags)
        cta_map = {
            "stats_showcase": "📊 Which stat surprised you most?",
            "problem_solution": "Ready to solve this? DM us to get started!",
            "step_by_step": "Which step will you try first? Comment below!",
            "myth_vs_fact": "Did any myth surprise you? Share your thoughts!",
            "listicle": "Which point resonates most? Save for later!",
            "comparison": "Which side are you on? Vote below!",
            "transformation": "Inspired by this journey? Start yours today!",
            "quick_tips": "Got a favorite tip? Let us know!",
            "trend_analysis": "Where do you see this trend going?",
            "common_mistakes": "Have you made any of these mistakes?",
            "case_study": "Want results like this? Contact us!",
            "faq_format": "Got more questions? Drop them below!"
        }
        cta = cta_map.get(template['name'].lower().replace(' ', '_'), "What do you think? Comment below!") if template else "What do you think? Comment below!"
        if self.api_key_valid and self.client:
            try:
                response = self.client.chat.completions.create(
                    messages=[{
                        "role": "user",
                        "content": f"Write a social media caption for '{theme}' using the following narrative arc: {template['structure'] if template else ''}. Slides: {', '.join(headers)}. CTA: {cta}. {CONTENT_TYPES[content_type]['tone']} tone, 300-400 words, emojis, hashtags: {hashtags_text}"
                    }],
                    model="llama-3.1-8b-instant",
                    temperature=0.7,
                    max_tokens=500
                )
                if response and response.choices:
                    caption = response.choices[0].message.content.strip()
                    if not any(h in caption for h in hashtags[:3]):
                        caption += f" {hashtags_text}"
                    return caption
            except Exception as e:
                logger.warning(f"Caption generation failed: {e}")
        return f"Exploring {theme} and discovering insights. {hashtags_text} {cta}"

    def _generate_hashtags(self, theme: str, content_type: str) -> List[str]:
        """Generate hashtags"""
        base = ["#CraftingBrain", f"#{content_type}"]
        theme_words = theme.replace(" ", "").split()
        theme_tags = [f"#{w.capitalize()}" for w in theme_words if len(w) > 3]

        type_tags = {
            "Informative": ["#Education", "#Knowledge"],
            "Inspirational": ["#Motivation", "#Success"],
            "Promotional": ["#Business", "#Innovation"],
            "Educational": ["#Tutorial", "#Learning"],
            "Engaging": ["#Viral", "#Trending"]
        }

        content_tags = type_tags.get(content_type, ["#Content"])
        all_tags = base + theme_tags + content_tags
        return list(dict.fromkeys(all_tags))[:10]

    def _create_summary(self, subtopics_data: List[Dict]) -> List[str]:
        """Create summary"""
        summary = []
        for i, sub in enumerate(subtopics_data, 1):
            key_points = sub.get('key_points', [])
            header = sub.get('header') or sub.get('title')
            if key_points and isinstance(key_points, list) and len(key_points) > 0:
                point = key_points[0]
            else:
                point = header
            summary.append(f"{i}. {header}: {point}")
        return summary[:3]

    def _extract_json(self, text):
        """Extract JSON from Groq response text."""
        import re
        match = re.search(r'(\[.*?\]|\{.*?\})', text, re.DOTALL)
        if match:
            return match.group(1)
        return None

    def _create_fallback_subtopics(self, theme, content_type, num_subtopics):
        """Fallback: create simple subtopics if Groq fails."""
        subtopics = []
        for i in range(num_subtopics):
            subtopics.append({
                'header': f'{theme} - Point {i+1}',
                'body': f'Key idea about {theme} for slide {i+1}.',
                'key_points': [f'Highlight {i+1}'],
                'structure_type': f'auto_{i+1}'
            })
        return subtopics