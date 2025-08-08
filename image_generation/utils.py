import json
import re

# Enhanced styles for different content types to guide image generation
content_type_styles = {
    "Informative": {
        "layouts": [
            "modern grid layout with strategic icon placement and clean visual hierarchy",
            "sleek flowchart with directional arrows and contemporary design elements",
            "professional annotated diagram with callouts and data visualization"
        ],
        "Spellings" : "ensure all correct spellings",
        "palette": "sophisticated dark navy (#1a1a2e) background with vibrant golden yellow (#ffd700) accents, crisp white (#ffffff) text, and subtle blue (#16213e) secondary elements with a size 1024 × 1536",
        "font": "modern sans-serif typography with clear hierarchy - bold headings and clean body text",
        "theme_adjustment": "Include data visualization elements, professional icons, charts, and technical graphics with modern design aesthetics",
        "action": "Design a stunning professional infographic that clearly explains",
        "style_consistency": "Maintain consistent dark theme with yellow accents, modern typography, and professional layout structure across all images",
        "visual_elements": "Use geometric shapes, data charts, professional icons, and clean line graphics"
    },
    "Inspirational": {
        "layouts": [
            "centered motivational text with powerful background imagery and dramatic composition",
            "elegant quote design with decorative borders and inspiring visual elements",
            "dynamic asymmetrical layout with uplifting imagery and bold typography"
        ],
        "Spellings" : "ensure all correct spellings",
        "palette": "deep black (#000000) background with radiant golden yellow (#ffd700) text, warm amber (#ffb347) highlights, and dramatic lighting effects with a size of 1024 × 1536",
        "font": "bold, inspiring serif or decorative font with elegant spacing and visual impact",
        "theme_adjustment": "Incorporate uplifting imagery, success symbols, growth metaphors, inspirational quotes, and motivational visual elements",
        "action": "Create an emotionally powerful and visually striking inspirational image about",
        "style_consistency": "Maintain consistent black and gold color scheme, inspirational typography, and uplifting visual mood across all images",
        "visual_elements": "Use motivational symbols, upward arrows, light rays, success imagery, and inspiring quotes"
    },
    "Educational": {
        "layouts": [
            "structured step-by-step visual guide with numbered sequences and learning flow",
            "comprehensive mind map with branching connections and educational hierarchy",
            "classroom-style poster layout with learning modules and clear information organization"
        ],
        "Spellings" : "ensure all correct spellings",
        "palette": "clean dark charcoal (#2c2c2c) background with bright yellow (#ffd700) highlights, educational blue (#4a90e2) accents, and white (#ffffff) content areas with a size of 1024 × 1536",
        "font": "highly readable educational font with clear differentiation between headers, body text, and captions",
        "theme_adjustment": "Include educational icons, learning symbols, academic visual cues, progress indicators, and knowledge-building elements",
        "action": "Design a comprehensive educational visual that effectively teaches",
        "style_consistency": "Maintain consistent educational color scheme, structured layout, and academic presentation style across all images",
        "visual_elements": "Use educational icons, progress bars, bullet points, academic symbols, and learning indicators"
    },
    "Promotional": {
        "layouts": [
            "dynamic product spotlight with attention-grabbing focal points and marketing appeal",
            "compelling call-to-action banner with strategic placement and persuasive design",
            "modern marketing composition with brand elements and conversion-focused layout",
        ],
        "Spellings" : "ensure all correct spellings",
        "palette": "bold black (#000000) background with electric yellow (#ffd700) call-to-action elements, crisp white (#ffffff) content, and strategic color blocking with a size of 1024 × 1536",
        "font": "bold, attention-grabbing marketing font with strong visual hierarchy and persuasive typography",
        "theme_adjustment": "Showcase promotional elements, brand positioning, value propositions, compelling visual hooks, and marketing appeal",
        "action": "Create a high-impact promotional design that showcases and effectively promotes",
        "style_consistency": "Maintain consistent brand colors, marketing typography, and promotional design elements across all images",
        "visual_elements": "Use promotional badges, call-to-action buttons, brand elements, value proposition highlights, and marketing graphics"
    }
}

def clean_text(text):
    """
    Remove special characters from text, keeping only alphanumeric characters and spaces.
    
    Args:
        text (str): The input text to clean.
    
    Returns:
        str: Cleaned text with only alphanumeric characters and spaces.
    """
    return re.sub(r'[^a-zA-Z0-9\s]', '', text)

def get_content_details():
    """
    Load and parse content details from content_details.json.
    
    Returns:
        dict: A dictionary containing theme, number of subtopics, content type, and subtopics.
    
    Raises:
        FileNotFoundError: If content_details.json is not found.
        json.JSONDecodeError: If content_details.json cannot be decoded.
    """
    try:
        with open("content_details.json", "r") as f:
            content = json.load(f)
        return {
            "theme": content.get("theme", "Unknown Theme"),
            "num_subtopics": len(content.get("subtopics", [])),
            "content_type": content.get("content_type", "Educational"),
            "subtopics": [
                {
                    "title": subtopic,
                    "details": content["slide_contents"].get(subtopic, [subtopic.split(". ")[1] if ". " in subtopic else subtopic])[0],
                    "captions": content["captions"].get(subtopic, ["Default Caption"])
                }
                for subtopic in content.get("subtopics", [])
            ]
        }
    except FileNotFoundError:
        raise Exception("content_details.json not found.")
    except json.JSONDecodeError:
        raise Exception("Error decoding content_details.json.")