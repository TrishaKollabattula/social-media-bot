#image_generation/utils.py
import json
import re

# ---- Fresh content type styles ----
content_type_styles = {
    "Informative": {
        "layouts": [
            "data-driven dashboard style",
            "magazine-style infographic spread",
            "timeline with icons and highlights"
        ],
        "palette": "cool blues with neon accents, crisp white text",
        "font": "sleek sans-serif with precise spacing",
        "theme_adjustment": "Highlight clarity and structured knowledge",
        "visual_elements": "charts, diagrams, annotated visuals",
        "action": "Design a visually clear informative image about"
    },
    "Inspirational": {
        "layouts": [
            "cinematic photo with bold overlay quote",
            "sunrise gradient with silhouette",
            "dynamic poster with motivational typography"
        ],
        "palette": "warm golds, deep blacks, radiant highlights",
        "font": "bold serif or display type with elegance",
        "theme_adjustment": "Evoke emotion and motivation",
        "visual_elements": "hero shots, symbolic imagery, uplifting cues",
        "action": "Create an inspiring visual about"
    },
    "Educational": {
        "layouts": [
            "step-by-step illustrated guide",
            "interactive mind map style",
            "chalkboard/whiteboard teaching scene"
        ],
        "palette": "academic neutrals with bright highlight colors",
        "font": "readable educational typeface",
        "theme_adjustment": "Make learning approachable and clear",
        "visual_elements": "icons, diagrams, study cues",
        "action": "Design an educational image for"
    },
    "Promotional": {
        "layouts": [
            "product hero spotlight",
            "bold call-to-action banner",
            "dynamic split-screen with offer highlight"
        ],
        "palette": "high contrast black + brand accent colors",
        "font": "impactful marketing sans-serif",
        "theme_adjustment": "Drive attention and conversions",
        "visual_elements": "badges, product shots, CTA buttons",
        "action": "Create a promotional image showcasing"
    },
    "Engaging": {
        "layouts": [
            "social media carousel card",
            "interactive poll-style composition",
            "attention-grabbing meme-inspired layout"
        ],
        "palette": "vibrant neon accents with dark base",
        "font": "bold playful sans-serif",
        "theme_adjustment": "Encourage interaction and shares",
        "visual_elements": "social icons, playful graphics, dynamic shapes",
        "action": "Design an engaging image about"
    }
}

# ---- Text cleaning and spelling utilities ----
def clean_text(text: str) -> str:
    corrections = {
        'artifical': 'artificial',
        'intelligance': 'intelligence',
        'machien': 'machine',
        'learnng': 'learning',
        'tecnology': 'technology',
        'educaton': 'education',
        'innovaton': 'innovation',
        'developement': 'development',
        'managment': 'management',
        'anayltics': 'analytics'
    }
    for wrong, correct in corrections.items():
        text = re.sub(r'\b' + wrong + r'\b', correct, text, flags=re.IGNORECASE)
    cleaned = re.sub(r'[^a-zA-Z0-9\s\-\.,!?]', '', text)
    return cleaned.strip()

def validate_spelling_in_prompt(prompt: str) -> str:
    spelling_emphasis = (
        " CRITICAL: Verify spelling of every word before generation. "
        "Double-check: artificial, intelligence, machine, learning, technology, education, innovation, development, analytics."
    )
    return prompt + spelling_emphasis

def enhance_prompt_for_quality(base_prompt: str, iteration=0, previous_issues=None) -> str:
    enhancements = ["SPELLING VERIFICATION REQUIRED: Check every single word for accuracy."]
    if iteration > 0:
        quality_levels = [
            "Ensure high-resolution output with crisp, clear details.",
            "Generate with maximum quality settings and perfect visual completion.",
            "Use premium design standards with zero visual artifacts or errors.",
            "Apply professional-grade rendering with absolute perfection."
        ]
        enhancements.append(quality_levels[min(iteration-1, len(quality_levels)-1)])
    if previous_issues:
        issue_fixes = {
            'spelling': "DOUBLE-CHECK ALL TEXT.",
            'incomplete': "Ensure entire image is fully rendered.",
            'clarity': "Enhance clarity with sharp, readable elements.",
            'design': "Improve design with professional layout principles.",
            'colors': "Optimize colors with proper contrast."
        }
        for issue in previous_issues:
            if issue in issue_fixes:
                enhancements.append(issue_fixes[issue])
    return f"{base_prompt} {' '.join(enhancements)}"

# ---- Content details loader ----
def get_content_details() -> dict:
    try:
        with open("content_details.json", "r", encoding='utf-8') as f:
            content = json.load(f)
        processed_subtopics = []
        for subtopic in content.get("subtopics", []):
            clean_title = clean_text(subtopic)
            slide_content = content.get("slide_contents", {}).get(subtopic, [])
            captions = content.get("captions", {}).get(subtopic, ["Default Caption"])
            if slide_content:
                details = " ".join([clean_text(item) for item in slide_content])
            else:
                details = clean_title
            processed_subtopics.append({
                "title": clean_title,
                "details": details,
                "captions": [clean_text(cap) for cap in captions]
            })
        return {
            "theme": clean_text(content.get("theme", "Unknown Theme")),
            "num_subtopics": len(processed_subtopics),
            "content_type": content.get("content_type", "Educational"),
            "subtopics": processed_subtopics
        }
    except Exception as e:
        raise Exception(f"Error processing content_details.json: {str(e)}")
