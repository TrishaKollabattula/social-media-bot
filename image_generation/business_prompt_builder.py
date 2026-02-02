# image_generation/business_prompt_builder.py
# ✅ Creates rich, business-specific prompts for image generation (AGENCY-GRADE)
# ✅ Integrates survey data into prompts
# ✅ Dynamic industry mapping (from frontend/DynamoDB)
# ✅ Uses business_visual_profiles.py anti-AI rules + industry visual approach
# ✅ Forces typography-led, realistic, premium corporate output
# ✅ Hard-bans AI-poster artifacts (fake charts, stock collage, glossy gradient wallpaper, warped text)

import logging
from typing import Dict, Optional, List, Any

from image_generation.business_visual_profiles import (
    get_visual_profile,
    get_visual_profile_key,
    build_anti_ai_block,
)

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# 1) High-control style guides (AGENCY-GRADE defaults)
#    These are intentionally conservative; real brands are not "glossy".
# -------------------------------------------------------------------
BUSINESS_STYLES = {
    "technology": {
        "visual_theme": "minimal, modern, product-first, credibility-focused",
        "color_palette": "clean neutrals + 1 brand accent, controlled gradients only if brand uses it",
        "font_style": "modern sans-serif, strong hierarchy, 1–2 font families max",
        "imagery": "product UI only if real; otherwise abstract minimal shapes, subtle patterns",
    },
    "education": {
        "visual_theme": "trustworthy, structured, clarity-first, outcome-oriented",
        "color_palette": "clean light background + brand accents, high contrast for readability",
        "font_style": "highly readable sans-serif, clear hierarchy, minimal decoration",
        "imagery": "learning outcomes, clean icons, subtle academic motifs (no stock collage)",
    },
    "edtech": {
        "visual_theme": "modern learning, premium clarity, aspirational but professional",
        "color_palette": "brand-led accents with white/neutral base, controlled saturation",
        "font_style": "bold headline sans-serif + readable body sans-serif",
        "imagery": "clean UI motifs, learning icons, progress metaphors (minimal, not childish)",
    },
    "saas": {
        "visual_theme": "enterprise-grade, efficiency, outcomes, no fluff",
        "color_palette": "neutrals + brand accent, modern grays, minimal gradients",
        "font_style": "clean sans-serif, tight hierarchy, product/UX typography vibe",
        "imagery": "dashboard/UI only if clean and realistic; otherwise abstract product shapes",
    },
    "healthcare": {
        "visual_theme": "clinical trust, calm confidence, professional realism",
        "color_palette": "soft neutrals + medical blues/greens, no neon",
        "font_style": "clean sans-serif or subtle serif headline (optional), highly readable body",
        "imagery": "minimal healthcare icons, clean spacing; avoid fake stock-doctor montage",
    },
    "finance": {
        "visual_theme": "secure, premium, authoritative, conservative",
        "color_palette": "deep neutrals + gold/blue/green accents, minimal gradients",
        "font_style": "premium typography (serif headline optional) + clean sans body",
        "imagery": "NO decorative charts; only clean numbers and minimal icons",
    },
    "retail": {
        "visual_theme": "product hero, premium lifestyle, clean offer hierarchy",
        "color_palette": "brand-led + neutral base, controlled saturation",
        "font_style": "bold headline + clean offer typography, minimal extra fonts",
        "imagery": "product hero shot look (realistic), real shadows, real textures",
    },
    "real_estate": {
        "visual_theme": "premium, spacious, lifestyle-forward, trustworthy",
        "color_palette": "warm neutrals, whites, charcoals, gold accents (subtle)",
        "font_style": "premium modern sans-serif, spacious typography",
        "imagery": "natural light interiors, subtle icons, no fake glossy renders",
    },
    "restaurant": {
        "visual_theme": "appetite-led, clean menu typography, premium food vibe",
        "color_palette": "warm neutrals + 1–2 food-friendly accents, no neon",
        "font_style": "bold headline + readable menu body, minimal fonts",
        "imagery": "food hero with realistic shadows; avoid cluttered collages",
    },
    "b2b": {
        "visual_theme": "enterprise credibility, results-driven, minimal premium",
        "color_palette": "corporate neutrals + brand accent",
        "font_style": "authoritative sans-serif, clean hierarchy",
        "imagery": "icons + numbers + clean layout; avoid random people visuals",
    },
    "b2c": {
        "visual_theme": "simple, relatable, modern, still premium",
        "color_palette": "brand-led, controlled saturation, clean base",
        "font_style": "friendly but sharp sans-serif, readable body",
        "imagery": "product/use-case icons; avoid stock collage",
    },
}

DEFAULT_STYLE_KEY = "technology"


# -------------------------------------------------------------------
# 2) Utilities
# -------------------------------------------------------------------
def _safe_lower(v: Any) -> str:
    return str(v).strip().lower() if v is not None else ""


def _style_key_from_profile_key(profile_key: str) -> str:
    pk = _safe_lower(profile_key)

    if pk == "edtech":
        return "edtech"
    if pk in ("technology_saas",):
        return "saas"
    if pk in ("healthcare_medical",):
        return "healthcare"
    if pk in ("finance_banking",):
        return "finance"
    if pk in ("real_estate",):
        return "real_estate"
    if pk in ("food_beverage",):
        return "restaurant"
    if pk in ("ecommerce_product", "retail_fashion"):
        return "retail"
    if pk in ("fitness_wellness",):
        return "b2c"

    return DEFAULT_STYLE_KEY


def _extract_brand_colors(company_context: Optional[Dict]) -> Optional[Any]:
    if not company_context:
        return None
    return (
        company_context.get("brand_colors")
        or company_context.get("color_theme")
        or company_context.get("color_palette")
    )


def _truncate(val: Any, n: int) -> str:
    s = str(val) if val is not None else ""
    s = " ".join(s.split())
    return (s[:n] + "...") if len(s) > n else s


def _format_colors(colors: Any) -> str:
    if not colors:
        return ""
    if isinstance(colors, list):
        cleaned = [str(c).strip() for c in colors if str(c).strip()]
        return ", ".join(cleaned[:8])
    return str(colors).strip()


# -------------------------------------------------------------------
# 3) Prompt blocks (high control, low fluff)
# -------------------------------------------------------------------
def build_business_context_block(company_context: Optional[Dict]) -> str:
    if not company_context:
        return (
            "BUSINESS CONTEXT\n"
            "------------------------------------------------------------\n"
            "Use a generic premium business style.\n"
            "No gimmicks. No stock collage. Typography-led.\n"
            "------------------------------------------------------------"
        )

    raw_business_type = company_context.get("business_type", "general")
    profile_key = get_visual_profile_key(raw_business_type)

    company_name = company_context.get("company_name") or company_context.get("brand_name")
    products = company_context.get("products_services") or company_context.get("services")
    audience = company_context.get("target_audience") or company_context.get("audience")
    usp = company_context.get("unique_selling_points")
    values = company_context.get("brand_values")
    tagline = company_context.get("tagline")

    lines = [
        "BUSINESS CONTEXT",
        "------------------------------------------------------------",
    ]
    if company_name:
        lines.append(f"Company: {company_name}")
    lines.append(f"Industry (raw): {_truncate(raw_business_type, 70)}")
    lines.append(f"Industry (mapped): {profile_key}")

    if products:
        lines.append(f"Offerings: {_truncate(products, 170)}")
    if audience:
        lines.append(f"Audience: {_truncate(audience, 140)}")
    if usp:
        lines.append(f"Value prop: {_truncate(usp, 140)}")
    if values:
        lines.append(f"Brand values: {_truncate(values, 140)}")
    if tagline:
        lines.append(f"Tagline: {_truncate(tagline, 90)}")

    lines.append("------------------------------------------------------------")
    return "\n".join(lines)


def build_visual_branding_block(company_context: Optional[Dict]) -> str:
    raw_business_type = (company_context or {}).get("business_type", "general")
    profile_key = get_visual_profile_key(raw_business_type)
    profile = get_visual_profile(raw_business_type)

    style_key = _style_key_from_profile_key(profile_key)
    style_guide = BUSINESS_STYLES.get(style_key, BUSINESS_STYLES[DEFAULT_STYLE_KEY])

    brand_colors = _format_colors(_extract_brand_colors(company_context))

    lines = [
        "VISUAL DIRECTION",
        "------------------------------------------------------------",
        f"Profile: {profile_key}",
        f"Approach: {profile.get('visual_approach', 'mixed')}",
        f"Photo style: {profile.get('photography_style', 'professional')}",
        f"Illustration style: {profile.get('illustration_style', 'minimal')}",
        f"Tone: {profile.get('tone', 'professional')}",
        "",
        f"Theme: {style_guide['visual_theme']}",
        f"Typography: {style_guide['font_style']}",
        f"Imagery: {style_guide['imagery']}",
    ]

    if brand_colors:
        lines.append(f"Brand colors (use these): {brand_colors}")
        lines.append("Color rule: neutral base + brand accent(s). Keep saturation controlled.")
    else:
        lines.append(f"Fallback palette: {style_guide.get('color_palette')}")

    if company_context and company_context.get("has_logo"):
        cn = company_context.get("company_name") or "the brand"
        lines.append(f"Logo: include {cn} logo/brand mark subtly (corner or header).")

    composition = profile.get("composition")
    prefer = profile.get("prefer") or []
    avoid = profile.get("avoid") or []
    if composition:
        lines.append(f"Composition: {composition}")
    if prefer:
        lines.append(f"Prefer: {', '.join(prefer[:10])}")
    if avoid:
        lines.append(f"Avoid: {', '.join(avoid[:10])}")

    lines.append("------------------------------------------------------------")
    return "\n".join(lines)


def build_content_block(slide_number: int, slide_title: str, slide_body: Any, theme: str) -> str:
    lines = [
        "CONTENT",
        "------------------------------------------------------------",
        f"Theme: {theme}",
        f"Slide: {slide_number}",
        "",
        "Headline (exact):",
        slide_title.strip(),
        "",
        "Key points (short, crisp):",
    ]

    if isinstance(slide_body, list):
        for p in slide_body:
            s = str(p).strip()
            if s:
                lines.append(f"- {s}")
    else:
        body_text = str(slide_body) if slide_body is not None else ""
        body_text = body_text.strip()
        if body_text:
            if "\n" in body_text:
                for line in body_text.split("\n"):
                    s = line.strip()
                    if s:
                        lines.append(f"- {s}")
            else:
                lines.append(f"- {body_text}")

    lines.append("------------------------------------------------------------")
    return "\n".join(lines)


def build_design_system_block(template_visual_hint: str, profile_key: str) -> str:
    """
    This is the MAIN control lever that forces agency-grade layouts.
    """
    return "\n".join([
        "DESIGN SYSTEM (NON-NEGOTIABLE)",
        "------------------------------------------------------------",
        "Canvas: 1080x1350 Instagram portrait",
        f"Industry profile: {profile_key}",
        f"Template direction: {template_visual_hint}",
        "",
        "Layout rules:",
        "- Strict grid alignment (consistent left edges, equal spacing).",
        "- Clear hierarchy: Headline > subhead > bullets > CTA.",
        "- 1–2 font families MAX. Consistent weights. No random font mixing.",
        "- Mobile readability: headline must be readable in 1 second.",
        "- Use whitespace generously. Avoid clutter.",
        "- Use 3–5 bullets max. Keep copy tight.",
        "",
        "CTA placement:",
        "- Bottom strip or footer area: website/phone/handle if provided.",
        "- CTA must be subtle and clean, not loud banners.",
        "------------------------------------------------------------",
    ])


def build_hard_bans_block(profile_key: str) -> str:
    """
    These bans specifically prevent the Lenskart-style AI poster patterns.
    """
    return "\n".join([
        "HARD BANS (FAIL IF VIOLATED)",
        "------------------------------------------------------------",
        "- No stock-people collage. Avoid humans unless explicitly required.",
        "- No fake charts/candlesticks/random finance UI used as decoration.",
        "- No random dashboards unless the business is SaaS AND UI is clean + realistic.",
        "- No glossy gradient wallpaper. No plastic 3D. No over-shiny effects.",
        "- No warped text, gibberish, unreadable micro-text.",
        "- No clutter: no floating icons everywhere, no random shapes without purpose.",
        "- Avoid AI 'poster' look. Must look agency-designed.",
        "------------------------------------------------------------",
    ])


def build_quality_requirements_block(profile_key: str) -> str:
    lines = [
        "QUALITY TARGET",
        "------------------------------------------------------------",
        "Target score: 9.5+/10 (post-ready brand creative).",
        "Must look real, premium, and designed by a professional designer.",
        "Crisp typography, realistic shadows, subtle texture (paper grain/soft noise).",
        "No uncanny visuals, no fake-perfect symmetry, no template vibes.",
        "------------------------------------------------------------",
        "",
        # ✅ Dynamic anti-AI rules from visual profiles
        build_anti_ai_block(profile_key).strip(),
    ]
    return "\n".join(lines)


def build_business_specific_notes(company_context: Optional[Dict], content_type: str, profile_key: str) -> str:
    if not company_context:
        return ""

    company_name = company_context.get("company_name") or company_context.get("brand_name")
    audience = company_context.get("target_audience") or company_context.get("audience")
    values = company_context.get("brand_values")
    usp = company_context.get("unique_selling_points")
    website = company_context.get("website")
    phone = company_context.get("phone")

    lines = [
        "BUSINESS NOTES",
        "------------------------------------------------------------",
    ]
    if company_name:
        lines.append(f"For brand: {company_name}")
    if audience:
        lines.append(f"Design for: {_truncate(audience, 160)}")
    if values:
        lines.append(f"Reflect values: {_truncate(values, 160)}")
    if usp and str(content_type).lower() == "promotional":
        lines.append(f"Highlight USP: {_truncate(usp, 160)}")

    # Industry-specific fine tuning
    if profile_key == "edtech":
        lines.extend([
            "",
            "EdTech nuance:",
            "- Outcome-driven headline. Clear benefit. No childish illustrations.",
            "- Premium learning vibe, not cartoonish.",
        ])
    elif profile_key == "technology_saas":
        lines.extend([
            "",
            "SaaS/Tech nuance:",
            "- Emphasize efficiency/results. Use minimal UI motifs only.",
            "- Avoid noisy interface screenshots and fake graphs.",
        ])
    elif profile_key == "healthcare_medical":
        lines.extend([
            "",
            "Healthcare nuance:",
            "- Trust-first. Calm and clean. Avoid 'stock doctor' clichés.",
        ])
    elif profile_key == "finance_banking":
        lines.extend([
            "",
            "Finance nuance:",
            "- Authoritative, conservative. Numbers + icons > charts.",
            "- No decorative candlesticks unless real trading brand content requires it.",
        ])
    elif profile_key in ("ecommerce_product", "retail_fashion"):
        lines.extend([
            "",
            "Retail/E-comm nuance:",
            "- Product is hero. Realistic texture and shadows.",
            "- Offer typography must be perfect and readable.",
        ])
    elif profile_key == "real_estate":
        lines.extend([
            "",
            "Real estate nuance:",
            "- Spacious, premium. Natural light look. Minimal icon set.",
        ])
    elif profile_key == "food_beverage":
        lines.extend([
            "",
            "Food nuance:",
            "- Appetite-led. Keep layout clean, avoid cluttered food collage.",
        ])

    # Contact info for footer CTA
    footer_bits = []
    if website:
        footer_bits.append(f"Website: {website}")
    if phone:
        footer_bits.append(f"Phone: {phone}")
    if footer_bits:
        lines.append("")
        lines.append("Footer CTA (include cleanly): " + " | ".join(footer_bits))

    lines.append("------------------------------------------------------------")
    return "\n".join(lines)


# -------------------------------------------------------------------
# 4) MAIN API
# -------------------------------------------------------------------
def create_rich_image_prompt(
    slide_number: int,
    slide_title: str,
    slide_body: Any,
    theme: str,
    company_context: Optional[Dict],
    content_type: str = "Informative",
    template_visual_hint: str = "typography-led minimal layout",
) -> str:
    """
    MAIN FUNCTION: Create comprehensive, business-specific image prompt.
    ✅ Uses dynamic industry mapping
    ✅ Adds strict design system + hard bans
    ✅ Adds anti-AI rules per industry
    """

    raw_business_type = (company_context or {}).get("business_type", "general")
    profile_key = get_visual_profile_key(raw_business_type)

    sections: List[str] = []
    sections.append("CREATE ONE PREMIUM INSTAGRAM IMAGE (SINGLE POST)")
    sections.append("=" * 80)

    # Keep it tight + directive
    sections.append(build_business_context_block(company_context))
    sections.append(build_visual_branding_block(company_context))
    sections.append(build_content_block(slide_number, slide_title, slide_body, theme))

    # The real control blocks
    sections.append(build_design_system_block(template_visual_hint, profile_key))
    sections.append(build_hard_bans_block(profile_key))
    sections.append(build_quality_requirements_block(profile_key))

    business_notes = build_business_specific_notes(company_context, content_type, profile_key)
    if business_notes:
        sections.append(business_notes)

    # Final instruction: avoid extra generation noise
    sections.append("FINAL OUTPUT REQUIREMENT")
    sections.append("------------------------------------------------------------")
    sections.append("- Output must be a finished, post-ready creative.")
    sections.append("- Must look like an agency-designed brand post (NOT AI poster).")
    sections.append("- Text must be clean and readable. No artifacts.")
    sections.append("------------------------------------------------------------")
    sections.append("=" * 80)

    final_prompt = "\n".join(sections)

    # Logging
    logger.info("\n" + "=" * 80)
    logger.info(f"📝 RICH PROMPT CREATED FOR SLIDE {slide_number}")
    logger.info("=" * 80)
    logger.info(f"Prompt length: {len(final_prompt)} characters")
    logger.info(f"Business context: {'RICH' if company_context else 'GENERIC'}")
    if company_context:
        logger.info(f"Company: {company_context.get('company_name', 'N/A')}")
        logger.info(f"Industry RAW: {raw_business_type}")
        logger.info(f"Industry MAPPED: {profile_key}")
        logger.info(f"Has colors: {bool(_extract_brand_colors(company_context))}")
        logger.info(f"Has logo: {company_context.get('has_logo', False)}")
    logger.info("=" * 80 + "\n")

    return final_prompt


def create_prompts_for_all_slides(
    slides_data: List[Dict],
    theme: str,
    company_context: Optional[Dict],
    content_type: str = "Informative",
    template_visual_hint: str = "typography-led minimal layout",
) -> List[str]:
    """
    Create prompts for all slides in a carousel.
    """
    prompts: List[str] = []

    for i, slide in enumerate(slides_data, start=1):
        slide_title = slide.get("title") or slide.get("header", f"Slide {i}")
        slide_body = slide.get("body", [])

        prompt = create_rich_image_prompt(
            slide_number=i,
            slide_title=slide_title,
            slide_body=slide_body,
            theme=theme,
            company_context=company_context,
            content_type=content_type,
            template_visual_hint=template_visual_hint,
        )
        prompts.append(prompt)

    logger.info(f"✅ Created {len(prompts)} rich prompts for carousel")
    return prompts