# image_generation/image_templates.py
# Template-to-visual mapping + dynamic business overrides + anti-AI criteria (UPDATED)

from __future__ import annotations

from typing import Dict, Any, List, Optional

from image_generation.business_visual_profiles import (
    BUSINESS_VISUAL_PROFILES,
    ANTI_AI_UNIVERSAL_RULES,
    get_visual_profile_key,
    get_visual_profile,
)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _uniq(lines: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in lines:
        x = (x or "").strip()
        if not x:
            continue
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def build_template_hint(template_id: str, business_type: Optional[str] = None) -> str:
    """
    Returns a single string that you can pass into your prompt builder as `template_visual_hint`.
    It merges:
      - template base style
      - industry-specific visual profile (dynamic from business_type)
      - universal anti-ai rules
    """
    spec = TEMPLATE_VISUAL_SPECS.get(template_id, TEMPLATE_VISUAL_SPECS["listicle"])

    profile_key = get_visual_profile_key(business_type or "technology_saas")
    profile = get_visual_profile(profile_key)

    parts = []
    parts.append(f"TEMPLATE={template_id}")
    parts.append(f"VISUAL_STYLE={spec.get('visual_style', '')}")
    parts.append(f"COMPOSITION={spec.get('composition', '')}")

    # industry additions (dynamic)
    if profile:
        parts.append(f"VISUAL_APPROACH={profile.get('visual_approach', '')}")
        parts.append(f"PHOTOGRAPHY_STYLE={profile.get('photography_style', '')}")
        parts.append(f"ILLUSTRATION_STYLE={profile.get('illustration_style', '')}")
        parts.append(f"TONE={profile.get('tone', '')}")
        parts.append(f"COMPOSITION_HINT={profile.get('composition', '')}")

        avoid = profile.get("avoid", [])
        prefer = profile.get("prefer", [])
        if avoid:
            parts.append(f"AVOID={', '.join(avoid)}")
        if prefer:
            parts.append(f"PREFER={', '.join(prefer)}")

    # universal anti-ai
    always_include = ANTI_AI_UNIVERSAL_RULES.get("always_include", [])
    always_avoid = ANTI_AI_UNIVERSAL_RULES.get("always_avoid", [])
    if always_include:
        parts.append("ANTI_AI_INCLUDE=" + "; ".join(always_include[:5]))
    if always_avoid:
        parts.append("ANTI_AI_AVOID=" + "; ".join(always_avoid[:5]))

    return " | ".join([p for p in parts if p and p.strip()])


def get_template_spec(template_id: str, business_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Returns a fully merged spec object:
      - base template spec
      - dynamic industry overrides (from business_type)
      - anti-ai rules (universal + industry tactics)
    """
    base = TEMPLATE_VISUAL_SPECS.get(template_id, TEMPLATE_VISUAL_SPECS["listicle"])

    profile_key = get_visual_profile_key(business_type or "technology_saas")
    profile = get_visual_profile(profile_key)

    merged: Dict[str, Any] = dict(base)

    # Attach dynamic industry profile + normalized key
    merged["industry_profile_key"] = profile_key
    merged["industry_profile"] = profile

    # Merge anti-ai
    merged_anti_ai = {
        "always_include": _uniq(list(ANTI_AI_UNIVERSAL_RULES.get("always_include", []))),
        "always_avoid": _uniq(list(ANTI_AI_UNIVERSAL_RULES.get("always_avoid", []))),
        "photography_authenticity": _uniq(list(ANTI_AI_UNIVERSAL_RULES.get("photography_authenticity", []))),
        "illustration_authenticity": _uniq(list(ANTI_AI_UNIVERSAL_RULES.get("illustration_authenticity", []))),
    }

    # add industry tactics (strong)
    industry_tactics = profile.get("anti_ai_tactics", []) if isinstance(profile, dict) else []
    if industry_tactics:
        merged_anti_ai["industry_tactics"] = _uniq(list(industry_tactics))

    merged["anti_ai_rules"] = merged_anti_ai

    # Merge feedback criteria: base + industry key points
    feedback = list(base.get("feedback_criteria", []))

    if isinstance(profile, dict) and profile:
        # Add a few industry-sensitive checks
        pk = profile_key
        if pk in ("ecommerce_product", "food_beverage", "retail_fashion", "real_estate"):
            feedback += [
                "Realistic lighting/shadows (not flat)",
                "Authentic texture detail (no plastic skin/materials)",
                "No fake/uncanny objects or distorted text",
            ]
        elif pk in ("technology_saas", "finance_banking", "healthcare_medical"):
            feedback += [
                "Clean professional hierarchy",
                "No generic AI stock faces",
                "UI/data elements look believable (no gibberish text)",
            ]
        elif pk in ("edtech", "fitness_wellness", "travel_hospitality", "entertainment_media"):
            feedback += [
                "Energy matches the brand (not sterile)",
                "Avoid over-polished AI look",
                "Natural imperfections present",
            ]

    merged["feedback_criteria"] = _uniq(feedback)

    # Business overrides placeholder (kept for compatibility)
    merged.setdefault("business_overrides", {})

    return merged


# -----------------------------------------------------------------------------
# TEMPLATE VISUAL SPECS (base)
# -----------------------------------------------------------------------------

TEMPLATE_VISUAL_SPECS: Dict[str, Dict[str, Any]] = {
    "listicle": {
        "visual_style": "numbered_list, icons_per_item, scannable_layout",
        "composition": "vertical list, each item with icon and number, clean spacing, white or light background",
        "feedback_criteria": [
            "Each item visually distinct",
            "Consistent iconography",
            "Clear number markers",
            "No AI-artifacts or generic faces",
            "Text is readable on mobile",
        ],
        "anti_ai_rules": ANTI_AI_UNIVERSAL_RULES,   # base universal reference
        "business_overrides": {},
    },
    "stats_showcase": {
        "visual_style": "infographic, bold numbers, data highlights",
        "composition": "large numbers, supporting icons, minimal text, data callouts",
        "feedback_criteria": [
            "Numbers are prominent",
            "Data visualized cleanly",
            "No chartjunk or fake graphs",
            "No AI-artifacts",
            "No gibberish labels",
        ],
        "anti_ai_rules": ANTI_AI_UNIVERSAL_RULES,
        "business_overrides": {},
    },
    "problem_solution": {
        "visual_style": "split layout, before-after, problem on left, solution on right",
        "composition": "left side problem, right side solution, contrasting colors, icons for each side",
        "feedback_criteria": [
            "Clear separation of problem and solution",
            "Visual contrast between sides",
            "No AI-artifacts",
            "Consistent icon style",
        ],
        "anti_ai_rules": ANTI_AI_UNIVERSAL_RULES,
        "business_overrides": {},
    },
    "step_by_step": {
        "visual_style": "stepwise, arrows, progress bar, sequential cues",
        "composition": "steps in sequence, arrows or progress bar, each step with icon",
        "feedback_criteria": [
            "Steps are visually ordered",
            "Progression is clear",
            "No AI-artifacts",
            "Icons align to steps",
        ],
        "anti_ai_rules": ANTI_AI_UNIVERSAL_RULES,
        "business_overrides": {},
    },
    "myth_vs_fact": {
        "visual_style": "side-by-side, myth vs fact, strong contrast, icons",
        "composition": "left side myth, right side fact, strong color cues, icons for each",
        "feedback_criteria": [
            "Myth and fact are visually distinct",
            "Color cues are clear",
            "No AI-artifacts",
            "No misleading visuals",
        ],
        "anti_ai_rules": ANTI_AI_UNIVERSAL_RULES,
        "business_overrides": {},
    },

    # You can add more templates here later without changing your generator:
    # "testimonial": {...}
    # "case_study": {...}
    # "product_launch": {...}
}
