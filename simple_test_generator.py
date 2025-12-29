# simple_test_generator.py
"""
Test script for content generation system (template-driven).
Runs a basic content generation flow and outputs results to content_details.json.
"""
import os
import json
from content_generation import content_generator

def run_content_generation_test():
    # Example business and theme
    business_info = {
        "business_name": "CraftingBrain",
        "brand_colors": ["#FFD600", "#000000"],
        "fonts": ["Montserrat", "Roboto"],
        "logo": "logo.png",
        "business_type": "Education"
    }
    theme = "Artificial Intelligence for Business"
    platforms = ["instagram", "linkedin"]
    generator = content_generator.ContentGenerator()
    result = generator.generate_complete_content(
        theme=theme,
        content_type="Informative",
        num_subtopics=5,
        platforms=platforms,
        company_context=business_info,
        user_id=None,
        meme_mode=False
    )
    # Save output to content_details.json
    with open("content_details.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print("Content generation test complete. Output saved to content_details.json.")

def test_prompt_generation():
    # Test only prompt/template selection logic
    business_info = {
        "business_name": "CraftingBrain",
        "brand_colors": ["#FFD600", "#000000"],
        "fonts": ["Montserrat", "Roboto"],
        "logo": "logo.png",
        "business_type": "Education"
    }
    theme = "AI in Healthcare"
    platforms = ["instagram", "linkedin"]
    generator = content_generator.ContentGenerator()
    result = generator.generate_complete_content(
        theme=theme,
        content_type="Educational",
        num_subtopics=3,
        platforms=platforms,
        company_context=business_info,
        user_id=None,
        meme_mode=False
    )
    print("Prompt generation test result:")
    print(json.dumps(result, indent=2, ensure_ascii=False))

def create_test_content_details():
    # Utility to create a sample content_details.json for manual inspection
    run_content_generation_test()

def run_full_test_suite():
    print("Running full test suite...")
    run_content_generation_test()
    test_prompt_generation()
    print("Full test suite complete.")

if __name__ == "__main__":
    run_content_generation_test()
