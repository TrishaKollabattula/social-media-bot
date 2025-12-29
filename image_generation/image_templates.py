# image_templates.py
# Template-to-business visual mapping and feedback criteria
from image_generation.business_visual_profiles import BUSINESS_VISUAL_PROFILES, ANTI_AI_UNIVERSAL_RULES

TEMPLATE_VISUAL_SPECS = {
    "listicle": {
        "visual_style": "numbered_list, icons_per_item, scannable_layout",
        "composition": "vertical list, each item with icon and number, clean spacing, white or light background",
        "feedback_criteria": [
            "Each item visually distinct",
            "Consistent iconography",
            "Clear number markers",
            "No AI-artifacts or generic faces"
        ],
        "anti_ai_rules": ANTI_AI_UNIVERSAL_RULES,
        "business_overrides": {}
    },
    "stats_showcase": {
        "visual_style": "infographic, bold numbers, data highlights",
        "composition": "large numbers, supporting icons, minimal text, data callouts",
        "feedback_criteria": [
            "Numbers are prominent",
            "Data visualized cleanly",
            "No chartjunk or fake graphs",
            "No AI-artifacts"
        ],
        "anti_ai_rules": ANTI_AI_UNIVERSAL_RULES,
        "business_overrides": {}
    },
    "problem_solution": {
        "visual_style": "split layout, before-after, problem on left, solution on right",
        "composition": "left side problem, right side solution, contrasting colors, icons for each side",
        "feedback_criteria": [
            "Clear separation of problem and solution",
            "Visual contrast between sides",
            "No AI-artifacts"
        ],
        "anti_ai_rules": ANTI_AI_UNIVERSAL_RULES,
        "business_overrides": {}
    },
    "step_by_step": {
        "visual_style": "stepwise, arrows, progress bar, sequential cues",
        "composition": "steps in sequence, arrows or progress bar, each step with icon",
        "feedback_criteria": [
            "Steps are visually ordered",
            "Progression is clear",
            "No AI-artifacts"
        ],
        "anti_ai_rules": ANTI_AI_UNIVERSAL_RULES,
        "business_overrides": {}
    },
    "myth_vs_fact": {
        "visual_style": "side-by-side, myth in red, fact in green, icons",
        "composition": "left side myth, right side fact, color cues, icons for each",
        "feedback_criteria": [
            "Myth and fact are visually distinct",
            "Color cues are clear",
            "No AI-artifacts"
        ],
        "anti_ai_rules": ANTI_AI_UNIVERSAL_RULES,
        "business_overrides": {}
    },
    # ...add all other template keys as needed...
}
