#content_templates.py
TEMPLATES = {
    "stats_showcase": {
        "name": "Statistics Showcase",
        "slides": [5, 7],
        "content_types": ["Informative", "Educational"],
        "structure": ["hook_stat", "context", "breakdown", "breakdown", "breakdown", "impact", "cta"],
        "text_limits": {"title": 8, "body": 15},
        "visual_hints": "data_visualization, numbers_prominent, comparison_layout"
    },
    "problem_solution": {
        "name": "Problem-Agitate-Solution",
        "slides": [6, 8],
        "content_types": ["Educational", "Promotional"],
        "structure": ["problem_intro", "pain_points", "consequences", "solution_intro", "benefits", "how_it_works", "cta"],
        "text_limits": {"title": 10, "body": 18},
        "visual_hints": "before_after, transformation, pain_to_gain"
    },
    "step_by_step": {
        "name": "Step-by-Step Guide",
        "slides": [6, 10],
        "content_types": ["Educational", "Informative"],
        "structure": ["intro_hook", "step1", "step2", "step3", "step4", "step5", "bonus_tip", "cta"],
        "text_limits": {"title": 12, "body": 20},
        "visual_hints": "numbered_sequence, process_flow, actionable_steps"
    },
    "myth_vs_fact": {
        "name": "Myth vs Fact",
        "slides": [6, 8],
        "content_types": ["Educational", "Informative"],
        "structure": ["intro", "myth1_fact1", "myth2_fact2", "myth3_fact3", "why_matters", "cta"],
        "text_limits": {"title": 10, "body": 16},
        "visual_hints": "split_screen, contrast_colors, debunking_visual"
    },
    "listicle": {
        "name": "Numbered List",
        "slides": [6, 10],
        "content_types": ["Informative", "Inspirational"],
        "structure": ["hook", "item1", "item2", "item3", "item4", "item5", "bonus", "cta"],
        "text_limits": {"title": 10, "body": 18},
        "visual_hints": "numbered_list, icons_per_item, scannable_layout"
    },
    "comparison": {
        "name": "A vs B Comparison",
        "slides": [6, 8],
        "content_types": ["Informative", "Educational"],
        "structure": ["intro", "option_a_pros", "option_a_cons", "option_b_pros", "option_b_cons", "verdict", "cta"],
        "text_limits": {"title": 8, "body": 15},
        "visual_hints": "side_by_side, vs_symbol, balanced_layout"
    },
    "transformation": {
        "name": "Before/After Transformation",
        "slides": [7, 9],
        "content_types": ["Inspirational", "Promotional"],
        "structure": ["before_state", "struggle", "turning_point", "process", "progress", "after_state", "key_takeaway", "cta"],
        "text_limits": {"title": 10, "body": 18},
        "visual_hints": "transformation_visual, journey_arc, progress_indicator"
    },
    "quick_tips": {
        "name": "Quick Tips",
        "slides": [6, 8],
        "content_types": ["Educational", "Inspirational"],
        "structure": ["hook", "tip1", "tip2", "tip3", "tip4", "tip5", "cta"],
        "text_limits": {"title": 8, "body": 15},
        "visual_hints": "lightbulb_icon, bite_sized, clean_minimal"
    },
    "trend_analysis": {
        "name": "Trend Analysis",
        "slides": [7, 9],
        "content_types": ["Informative", "Educational"],
        "structure": ["trend_intro", "current_state", "key_driver1", "key_driver2", "key_driver3", "future_outlook", "action_items", "cta"],
        "text_limits": {"title": 12, "body": 20},
        "visual_hints": "charts_graphs, timeline, forward_looking"
    },
    "common_mistakes": {
        "name": "Common Mistakes to Avoid",
        "slides": [6, 8],
        "content_types": ["Educational", "Informative"],
        "structure": ["intro", "mistake1", "mistake2", "mistake3", "mistake4", "correct_approach", "cta"],
        "text_limits": {"title": 10, "body": 18},
        "visual_hints": "warning_icons, x_marks, correction_visual"
    },
    "case_study": {
        "name": "Case Study/Success Story",
        "slides": [7, 9],
        "content_types": ["Inspirational", "Promotional"],
        "structure": ["subject_intro", "challenge", "approach", "implementation", "results_metrics", "key_insights", "cta"],
        "text_limits": {"title": 12, "body": 20},
        "visual_hints": "testimonial_style, metrics_highlight, storytelling"
    },
    "faq_format": {
        "name": "FAQ Style",
        "slides": [6, 8],
        "content_types": ["Educational", "Informative"],
        "structure": ["intro", "q1_a1", "q2_a2", "q3_a3", "q4_a4", "summary", "cta"],
        "text_limits": {"title": 12, "body": 18},
        "visual_hints": "question_mark_icon, qa_layout, conversational"
    }
}
