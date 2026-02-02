# image_generation/business_visual_profiles.py
# Industry-specific visual identity profiles + anti-AI rules (AGENCY-GRADE)
# ✅ Dynamic industry normalization + helper APIs for prompt builder
# ✅ Stronger bans to prevent "AI poster" look
# ✅ Typography-led, grid-based design defaults
# ✅ Provides: get_visual_profile_key(), get_visual_profile(), build_anti_ai_block()

from __future__ import annotations
from typing import Dict, Any, List, Optional


# -------------------------------------------------------------------
# 1) CORE VISUAL PROFILES (UPDATED FOR AGENCY-GRADE OUTPUT)
# -------------------------------------------------------------------
BUSINESS_VISUAL_PROFILES: Dict[str, Dict[str, Any]] = {
    # -------------------------
    # EDTECH / EDUCATION
    # -------------------------
    "edtech": {
        "visual_approach": "typography_led_with_minimal_illustration",
        "photography_style": "authentic_learning_environment_optional",
        "color_psychology": "optimistic_trustworthy",
        "illustration_style": "minimal_icon_system_clean",
        "tone": "confident_clear_inspiring",
        "avoid": [
            "cartoonish_children_style",
            "flashy_gradients",
            "template_poster_vibes",
            "random_ui_screens",
            "overcrowded_elements",
        ],
        "prefer": [
            "clean_grid_layout",
            "strong_typography_hierarchy",
            "minimal_icons",
            "outcome_focused_copy",
            "realistic_subtle_texture",
        ],
        "composition": "structured_modern_grid",
        "anti_ai_tactics": [
            "Use typography-led layout with strict grid alignment",
            "Use minimal icons only (consistent style, same stroke weight)",
            "Add subtle paper grain / soft noise to avoid plastic look",
            "Avoid stock student collage; if humans used, keep ONE authentic scene only",
            "Keep background mostly neutral with controlled brand accent",
        ],
    },

    # -------------------------
    # E-COMMERCE / PRODUCT / RETAIL HERO
    # -------------------------
    "ecommerce_product": {
        "visual_approach": "product_hero_photography_or_hyperreal_3d_if_needed",
        "photography_style": "product_hero_shot_real_shadows",
        "color_psychology": "clean_premium_desirable",
        "illustration_style": "none_or_minimal_badges",
        "tone": "premium_confident",
        "avoid": [
            "fake_stock_people_collage",
            "random_charts",
            "unrealistic_reflections",
            "plastic_surfaces",
            "over_shiny_gradients",
            "busy_backgrounds",
        ],
        "prefer": [
            "single_hero_product",
            "realistic_material_texture",
            "natural_shadow_falloff",
            "controlled_light",
            "minimal_offer_badges",
        ],
        "composition": "product_first_balanced_whitespace",
        "anti_ai_tactics": [
            "Realistic product texture (fabric grain, metal micro-scratches, glass reflections)",
            "Natural studio lighting imperfections (soft hotspot + falloff)",
            "Real shadows and grounded placement (no floating)",
            "Avoid perfect gradients; prefer neutral base + subtle texture",
            "Keep offer typography crisp and large enough for mobile",
        ],
    },

    # -------------------------
    # SAAS / TECHNOLOGY
    # -------------------------
    "technology_saas": {
        "visual_approach": "typography_led_minimal_ui_motifs_optional",
        "photography_style": "modern_workspace_optional_but_realistic",
        "color_psychology": "professional_innovative",
        "illustration_style": "minimal_isometric_or_flat_icons_consistent",
        "tone": "modern_trustworthy_enterprise",
        "avoid": [
            "generic_stock_photos",
            "fake_dashboards_as_decoration",
            "random_code_snippets",
            "overly_complex_charts",
            "neon_glow_everywhere",
            "template_poster_style",
        ],
        "prefer": [
            "clean_grid",
            "strong_typography",
            "minimal_shapes",
            "one_clear_visual_anchor",
            "subtle_depth_shadows",
        ],
        "composition": "geometric_structured_grid",
        "anti_ai_tactics": [
            "If UI shown, keep it minimal + realistic (clean spacing, no nonsense graphs)",
            "Use subtle screen glare / soft reflections (realistic)",
            "Add slight texture/noise overlay to avoid sterile look",
            "Avoid clutter. One hero element only.",
            "Keep typography as main hero (agency-style layout).",
        ],
    },

    # -------------------------
    # HEALTHCARE / MEDICAL
    # -------------------------
    "healthcare_medical": {
        "visual_approach": "typography_led_with_clean_medical_icons",
        "photography_style": "authentic_clinic_environment_optional",
        "color_psychology": "calm_trustworthy",
        "illustration_style": "medical_clean_iconography",
        "tone": "professional_caring",
        "avoid": [
            "stock_doctor_smile_pose",
            "cartoonish_medical",
            "overly_clinical_cold",
            "random_abstract_shapes",
            "template_poster_vibes",
        ],
        "prefer": [
            "clean_spacing",
            "minimal_icons",
            "soft_realistic_light",
            "humanity_and_trust",
            "neutral_backgrounds",
        ],
        "composition": "balanced_informative_grid",
        "anti_ai_tactics": [
            "Avoid stock-doctor clichés; if humans used, use ONE authentic candid clinic moment",
            "Use realistic lighting, slight shadow softness like real clinic lighting",
            "Use minimal medical icons (consistent style), not cartoon illustrations",
            "Add subtle paper grain / soft noise to avoid plastic look",
            "Keep composition calm, not busy",
        ],
    },

    # -------------------------
    # FINANCE / BANKING / FINTECH
    # -------------------------
    "finance_banking": {
        "visual_approach": "typography_led_premium_minimal",
        "photography_style": "professional_environment_optional",
        "color_psychology": "secure_stable_premium",
        "illustration_style": "minimal_secure_icons",
        "tone": "authoritative_reliable",
        "avoid": [
            "candlestick_charts_as_decoration",
            "random_growth_graphs",
            "crypto_bro_neon",
            "playful_casual",
            "busy_visuals",
            "template_poster_vibes",
        ],
        "prefer": [
            "premium_typography",
            "clean_numbers",
            "simple_security_icons",
            "deep_neutrals",
            "subtle_gold_or_blue_accents",
        ],
        "composition": "structured_hierarchical_whitespace",
        "anti_ai_tactics": [
            "No decorative candlesticks/graphs unless the brand is a trading platform",
            "Use premium typography + minimal iconography (lock, shield, card, vault)",
            "Add subtle texture (paper grain / soft noise) to avoid plastic look",
            "Keep gradients extremely minimal (or none)",
            "Focus on trust: clean layout, high contrast readability",
        ],
    },

    # -------------------------
    # FOOD / BEVERAGE
    # -------------------------
    "food_beverage": {
        "visual_approach": "food_hero_photography_required",
        "photography_style": "appetizing_food_styling_real_texture",
        "color_psychology": "warm_appetizing",
        "illustration_style": "minimal_labels_only",
        "tone": "fresh_indulgent",
        "avoid": [
            "over_processed_hdr_food",
            "neon_food_colors",
            "cartoon_food",
            "messy_collage",
            "fake_steam_everywhere",
        ],
        "prefer": [
            "macro_detail",
            "natural_light",
            "real_surface_texture",
            "simple_layout",
            "menu_typography_clean",
        ],
        "composition": "hero_shot_with_clean_text_area",
        "anti_ai_tactics": [
            "CRITICAL: Real food texture (crumbs, pores, condensation, imperfections)",
            "Natural light with soft shadows and falloff",
            "Slight asymmetry in plating; avoid perfect symmetry",
            "Use real table surface textures (wood, ceramic, stone)",
            "Keep copy minimal and readable; no clutter",
        ],
    },

    # -------------------------
    # REAL ESTATE
    # -------------------------
    "real_estate": {
        "visual_approach": "architectural_photography_preferred",
        "photography_style": "natural_light_lifestyle_real_interiors",
        "color_psychology": "aspirational_warm_premium",
        "illustration_style": "floorplan_only_if_needed",
        "tone": "premium_welcoming",
        "avoid": [
            "empty_cold_showroom",
            "overly_staged_unrealistic",
            "fake_wide_angle_distortion",
            "glossy_render_look",
            "busy_icons_everywhere",
        ],
        "prefer": [
            "natural_sunlight",
            "real_materials",
            "spacious_layout",
            "minimal_icons",
            "premium_typography",
        ],
        "composition": "spacious_balanced_grid",
        "anti_ai_tactics": [
            "Use real material textures (wood grain, fabric weave) with imperfections",
            "Natural sunlight + realistic shadows (not perfect symmetry)",
            "Avoid sterile renders; keep it lived-in and premium",
            "Keep icons minimal; prioritize layout and typography",
            "Add subtle grain/noise for realism",
        ],
    },

    # -------------------------
    # RETAIL / FASHION
    # -------------------------
    "retail_fashion": {
        "visual_approach": "editorial_product_or_lifestyle_photo",
        "photography_style": "editorial_lifestyle_real_skin_texture",
        "color_psychology": "trendy_premium",
        "illustration_style": "pattern_accents_only",
        "tone": "stylish_confident",
        "avoid": [
            "catalog_boring",
            "generic_mannequins",
            "over_smooth_skin",
            "plastic_fabric",
            "random_background_collage",
        ],
        "prefer": [
            "editorial_composition",
            "real_fabric_texture",
            "natural_wrinkles",
            "premium_light",
            "clean_offer_typography",
        ],
        "composition": "editorial_dynamic_clean",
        "anti_ai_tactics": [
            "CRITICAL: Real fabric texture + drape (wrinkles, stitching)",
            "Natural skin texture, avoid airbrushed plastic look",
            "Use realistic lighting and depth (not flat HDR)",
            "Avoid collage; use one hero visual only",
            "Keep typography bold but clean; no gimmicks",
        ],
    },

    # -------------------------
    # FITNESS / WELLNESS
    # -------------------------
    "fitness_wellness": {
        "visual_approach": "typography_led_with_one_authentic_action_photo_optional",
        "photography_style": "real_effort_authentic_movement",
        "color_psychology": "energetic_healthy",
        "illustration_style": "minimal_fitness_icons",
        "tone": "motivational_realistic",
        "avoid": [
            "unrealistic_bodies",
            "cgi_muscles",
            "overly_polished_gym_stock",
            "neon_glow",
            "busy_layouts",
        ],
        "prefer": [
            "authentic_motion",
            "real_sweat_texture",
            "simple_layout",
            "strong_typography",
            "clean_badges_only",
        ],
        "composition": "dynamic_but_clean_grid",
        "anti_ai_tactics": [
            "Use real movement cues (slight motion blur is okay)",
            "Avoid unreal bodies; use believable proportions",
            "Use clean typography-led layout with one hero photo max",
            "Add subtle texture/noise overlay for realism",
            "Keep composition uncluttered",
        ],
    },

    # -------------------------
    # TRAVEL / HOSPITALITY
    # -------------------------
    "travel_hospitality": {
        "visual_approach": "destination_photography_preferred",
        "photography_style": "golden_hour_natural_atmosphere",
        "color_psychology": "inviting_wanderlust",
        "illustration_style": "map_pin_accents_only",
        "tone": "welcoming_premium",
        "avoid": [
            "overly_edited_skies",
            "tourist_cliche_collage",
            "fake_hdr",
            "too_many_icons",
        ],
        "prefer": [
            "one_destination_hero",
            "atmospheric_light",
            "clean_typography",
            "minimal_cta",
            "subtle_grain",
        ],
        "composition": "expansive_with_text_safe_area",
        "anti_ai_tactics": [
            "Use natural lighting + atmosphere, avoid fake HDR",
            "Keep it one hero scene, not collage",
            "Add subtle film grain/noise for realism",
            "Use clean typography with lots of whitespace",
            "Avoid cliche tourist overlays",
        ],
    },

    # -------------------------
    # MANUFACTURING / INDUSTRIAL
    # -------------------------
    "manufacturing_industrial": {
        "visual_approach": "technical_photography_preferred",
        "photography_style": "industrial_real_wear_detail",
        "color_psychology": "capable_precise",
        "illustration_style": "technical_diagrams_minimal",
        "tone": "precise_professional",
        "avoid": [
            "generic_factory_stock",
            "too_clean_unrealistic",
            "random_icons",
            "overly_polished",
        ],
        "prefer": [
            "machinery_detail",
            "real_environment_wear",
            "controlled_typography",
            "simple_layout",
            "authentic_materials",
        ],
        "composition": "technical_grid_layout",
        "anti_ai_tactics": [
            "Show authentic wear (oil marks, dust, scratches) in a realistic way",
            "Use realistic workshop lighting with falloff",
            "Avoid sterile clean factories; show real environment",
            "Keep layout minimal, typography-led",
            "Add subtle texture/noise for realism",
        ],
    },

    # -------------------------
    # ENTERTAINMENT / MEDIA (still bold, but clean)
    # -------------------------
    "entertainment_media": {
        "visual_approach": "cinematic_typography_led",
        "photography_style": "cinematic_lighting_real_grain",
        "color_psychology": "bold_but_controlled",
        "illustration_style": "stylized_minimal",
        "tone": "exciting_premium",
        "avoid": [
            "generic_movie_poster_collage",
            "overused_glows",
            "cheap_vfx_text",
            "random_effects",
        ],
        "prefer": [
            "cinematic_lighting",
            "bold_clean_typography",
            "one_hero_scene",
            "film_grain",
            "clean_composition",
        ],
        "composition": "cinematic_impactful_with_text_safe_area",
        "anti_ai_tactics": [
            "Use film grain and realistic lighting falloff",
            "Avoid collage posters; keep one hero moment only",
            "Typography should be crisp and premium, not VFX cheesy",
            "Avoid over-processed color grading",
            "Add subtle texture overlays for realism",
        ],
    },
}

DEFAULT_PROFILE_KEY = "technology_saas"


# -------------------------------------------------------------------
# 1.1) PROFILE HARD BANS + PREFERENCES (extra guardrails)
# -------------------------------------------------------------------
PROFILE_HARD_BANS: Dict[str, List[str]] = {
    "finance_banking": [
        "NO decorative candlestick charts unless brand is trading platform",
        "NO random growth graphs as background decoration",
        "NO playful tone or meme-like styling",
    ],
    "technology_saas": [
        "NO fake dashboards with nonsense UI",
        "NO random code snippets as decoration",
    ],
    "healthcare_medical": [
        "NO stock doctor handshake images",
        "NO cartoon medical icons",
    ],
    "ecommerce_product": [
        "NO product floating without shadow",
        "NO plastic 3D surfaces",
    ],
}

PROFILE_PREFERENCES: Dict[str, List[str]] = {
    "finance_banking": [
        "premium typography, minimal icons, deep neutrals, subtle texture",
    ],
    "technology_saas": [
        "grid layout, typography-led, minimal UI motifs, subtle depth",
    ],
    "edtech": [
        "clear outcomes, typography-led, minimal icon set, clean spacing",
    ],
}


# -------------------------------------------------------------------
# 2) UNIVERSAL ANTI-AI RULES (UPGRADED)
# -------------------------------------------------------------------
ANTI_AI_UNIVERSAL_RULES: Dict[str, List[str]] = {
    "always_include": [
        "Typography realism: crisp kerning, consistent font system, clean alignment",
        "Design realism: strict grid, generous whitespace, clear hierarchy",
        "Material realism: subtle grain/texture (paper grain/soft noise), not plastic",
        "Lighting realism: soft shadow falloff, grounded objects, real depth cues",
        "Natural imperfections: slight asymmetry, organic variation, not perfect symmetry",
    ],
    "always_avoid": [
        "Warped, garbled, or unreadable text (FAIL if text is distorted)",
        "Too many fonts (max 2 font families; no random type mixing)",
        "Glossy gradient wallpaper / cheap poster sheen",
        "Stock-collage compositions with multiple random people",
        "Fake charts/candlesticks as decoration (unless truly relevant)",
        "Over-saturated HDR look, neon glows everywhere",
        "Floating elements without proper shadows",
        "Uncanny valley faces or plastic skin",
        "Cluttered layouts: too many icons, too many shapes, too many badges",
    ],
    "photography_authenticity": [
        "Natural lens behavior: slight vignetting, mild chromatic aberration (subtle)",
        "Real shadow softness and falloff (no hard cutout shadows)",
        "Avoid AI-perfect lighting; allow natural hotspots and bounce light",
        "Ground objects on surfaces with realistic contact shadows",
        "Keep one hero photo only (avoid collage)",
    ],
    "illustration_authenticity": [
        "Consistent icon system (same stroke, same corner radius, same style)",
        "Use subtle texture overlay to avoid flat vector plastic look",
        "Avoid perfect gradients; prefer flat + subtle depth",
        "Natural spacing and alignment (grid-based)",
        "Minimal shapes that support the message (not decoration)",
    ],
}


# -------------------------------------------------------------------
# 3) FRONTEND + RAW TEXT -> PROFILE KEY NORMALIZATION (UPGRADED)
# -------------------------------------------------------------------
INDUSTRY_SYNONYM_MAP: Dict[str, str] = {
    # EdTech / Education
    "edtech": "edtech",
    "ed tech": "edtech",
    "education": "edtech",
    "e-learning": "edtech",
    "elearning": "edtech",
    "coaching": "edtech",
    "training": "edtech",
    "academy": "edtech",
    "institute": "edtech",

    # SaaS / Tech
    "saas": "technology_saas",
    "software": "technology_saas",
    "software as a service": "technology_saas",
    "technology": "technology_saas",
    "tech": "technology_saas",
    "it": "technology_saas",
    "ai": "technology_saas",
    "platform": "technology_saas",
    "app": "technology_saas",
    "productivity": "technology_saas",
    "crm": "technology_saas",

    # Agency
    "agency": "technology_saas",
    "marketing agency": "technology_saas",
    "digital agency": "technology_saas",
    "creative agency": "technology_saas",
    "branding agency": "technology_saas",
    "ads": "technology_saas",

    # D2C / Ecommerce / Retail product
    "d2c": "ecommerce_product",
    "d2c / e-commerce": "ecommerce_product",
    "d2c / ecommerce": "ecommerce_product",
    "d2c/e-commerce": "ecommerce_product",
    "d2c/ecommerce": "ecommerce_product",
    "e-commerce": "ecommerce_product",
    "ecommerce": "ecommerce_product",
    "e commerce": "ecommerce_product",
    "retail": "ecommerce_product",
    "product": "ecommerce_product",
    "shop": "ecommerce_product",
    "store": "ecommerce_product",

    # Retail fashion
    "fashion": "retail_fashion",
    "boutique": "retail_fashion",
    "clothing": "retail_fashion",
    "apparel": "retail_fashion",
    "beauty": "retail_fashion",
    "cosmetics": "retail_fashion",
    "salon": "retail_fashion",

    # Real Estate
    "real estate": "real_estate",
    "realestate": "real_estate",
    "property": "real_estate",
    "builder": "real_estate",
    "construction": "real_estate",
    "interiors": "real_estate",
    "architecture": "real_estate",

    # Healthcare
    "healthcare": "healthcare_medical",
    "medical": "healthcare_medical",
    "clinic": "healthcare_medical",
    "hospital": "healthcare_medical",
    "pharma": "healthcare_medical",
    "dental": "healthcare_medical",
    "optical": "healthcare_medical",
    "diagnostic": "healthcare_medical",

    # Finance
    "finance": "finance_banking",
    "banking": "finance_banking",
    "fintech": "finance_banking",
    "investment": "finance_banking",
    "insurance": "finance_banking",
    "loan": "finance_banking",
    "mutual fund": "finance_banking",

    # Restaurant / Cafe / Food
    "restaurant": "food_beverage",
    "cafe": "food_beverage",
    "restaurant / cafe": "food_beverage",
    "restaurant/cafe": "food_beverage",
    "food": "food_beverage",
    "beverage": "food_beverage",
    "bakery": "food_beverage",

    # Fitness
    "fitness": "fitness_wellness",
    "gym": "fitness_wellness",
    "wellness": "fitness_wellness",
    "yoga": "fitness_wellness",
    "nutrition": "fitness_wellness",

    # Travel
    "travel": "travel_hospitality",
    "hospitality": "travel_hospitality",
    "hotel": "travel_hospitality",
    "tourism": "travel_hospitality",
    "resort": "travel_hospitality",

    # Manufacturing
    "manufacturing": "manufacturing_industrial",
    "industrial": "manufacturing_industrial",
    "factory": "manufacturing_industrial",
    "engineering": "manufacturing_industrial",

    # Entertainment
    "entertainment": "entertainment_media",
    "media": "entertainment_media",
    "ott": "entertainment_media",
    "studio": "entertainment_media",

    # Consulting / Professional services (maps to SaaS style for premium B2B clean)
    "consulting": "technology_saas",
    "consultant": "technology_saas",
    "law": "finance_banking",  # conservative premium style
    "legal": "finance_banking",

    # Other / Unknown
    "other": DEFAULT_PROFILE_KEY,
    "general": DEFAULT_PROFILE_KEY,
}


def _norm(s: Any) -> str:
    return str(s).strip().lower() if s is not None else ""


def get_visual_profile_key(business_type: Any) -> str:
    """
    Convert raw business_type (from DynamoDB / frontend) into a stable profile key.

    Examples:
      "EdTech" -> "edtech"
      "D2C / E-commerce" -> "ecommerce_product"
      "SaaS" -> "technology_saas"
      "Real Estate" -> "real_estate"
    """
    raw = _norm(business_type)
    if not raw:
        return DEFAULT_PROFILE_KEY

    # direct exact match in profiles
    if raw in BUSINESS_VISUAL_PROFILES:
        return raw

    # exact synonym match
    if raw in INDUSTRY_SYNONYM_MAP:
        return INDUSTRY_SYNONYM_MAP[raw]

    # contains-based fuzzy mapping
    for key, mapped in INDUSTRY_SYNONYM_MAP.items():
        if key and key in raw:
            return mapped

    return DEFAULT_PROFILE_KEY


def get_visual_profile(business_type: Any) -> Dict[str, Any]:
    """
    Get the resolved profile dict for a business type.
    Always returns a valid profile dict.
    """
    key = get_visual_profile_key(business_type)
    return BUSINESS_VISUAL_PROFILES.get(key, BUSINESS_VISUAL_PROFILES[DEFAULT_PROFILE_KEY])


# -------------------------------------------------------------------
# 4) ANTI-AI BLOCK BUILDER (used inside business_prompt_builder.py)
# -------------------------------------------------------------------
def build_anti_ai_block(profile_key: str) -> str:
    """
    Build a structured anti-AI rules block for prompts.
    """
    pk = _norm(profile_key) or DEFAULT_PROFILE_KEY
    profile = BUSINESS_VISUAL_PROFILES.get(pk, BUSINESS_VISUAL_PROFILES[DEFAULT_PROFILE_KEY])

    lines: List[str] = []
    lines.append("ANTI-AI AUTHENTICITY RULES")
    lines.append("-" * 60)

    # universal include/avoid
    lines.append("✅ ALWAYS INCLUDE:")
    for r in ANTI_AI_UNIVERSAL_RULES.get("always_include", []):
        lines.append(f"  • {r}")

    lines.append("")
    lines.append("⛔ ALWAYS AVOID:")
    for r in ANTI_AI_UNIVERSAL_RULES.get("always_avoid", []):
        lines.append(f"  • {r}")

    # photography vs illustration tips
    visual_approach = _norm(profile.get("visual_approach"))
    if "photo" in visual_approach or "photography" in visual_approach:
        lines.append("")
        lines.append("📷 PHOTOGRAPHY AUTHENTICITY:")
        for r in ANTI_AI_UNIVERSAL_RULES.get("photography_authenticity", []):
            lines.append(f"  • {r}")

    if "illustration" in visual_approach or "icon" in visual_approach:
        lines.append("")
        lines.append("🖍️ ILLUSTRATION / ICON AUTHENTICITY:")
        for r in ANTI_AI_UNIVERSAL_RULES.get("illustration_authenticity", []):
            lines.append(f"  • {r}")

    # industry tactics
    tactics = profile.get("anti_ai_tactics", []) or []
    if tactics:
        lines.append("")
        lines.append(f"🎯 INDUSTRY-SPECIFIC TACTICS ({pk}):")
        for t in tactics:
            lines.append(f"  • {t}")

    # extra hard bans
    hard_bans = PROFILE_HARD_BANS.get(pk, [])
    if hard_bans:
        lines.append("")
        lines.append(f"🚫 HARD BANS ({pk}):")
        for b in hard_bans:
            lines.append(f"  • {b}")

    prefs = PROFILE_PREFERENCES.get(pk, [])
    if prefs:
        lines.append("")
        lines.append(f"✅ PREFERENCES ({pk}):")
        for p in prefs:
            lines.append(f"  • {p}")

    lines.append("-" * 60)
    return "\n".join(lines)


# -------------------------------------------------------------------
# 5) OPTIONAL: safe list of allowed frontend industry labels
# -------------------------------------------------------------------
def allowed_frontend_industries() -> List[str]:
    return [
        "EdTech",
        "SaaS",
        "Agency",
        "D2C / E-commerce",
        "Real Estate",
        "Healthcare",
        "Finance",
        "Restaurant / Cafe",
        "Fitness",
        "Other",
    ]
