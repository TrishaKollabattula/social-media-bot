# business_visual_profiles.py
# Industry-specific visual identity profiles and anti-AI rules

BUSINESS_VISUAL_PROFILES = {
    "edtech": {
        "visual_approach": "illustration_preferred",
        "photography_style": "bright_classroom_energy",
        "color_psychology": "vibrant_optimistic",
        "illustration_style": "modern_flat_friendly",
        "tone": "encouraging_approachable",
        "avoid": ["corporate_stiff", "dark_moody", "overly_polished"],
        "prefer": ["hand_drawn_elements", "learning_icons", "student_focused"],
        "composition": "energetic_dynamic",
        "anti_ai_tactics": [
            "Add subtle imperfections like hand-drawn elements",
            "Use natural classroom/study settings",
            "Include diverse, authentic student imagery",
            "Avoid perfect symmetry, add organic layouts"
        ]
    },
    "ecommerce_product": {
        "visual_approach": "dslr_photography_required",
        "photography_style": "product_hero_shot",
        "color_psychology": "clean_premium",
        "illustration_style": "none",
        "tone": "aspirational_desirable",
        "avoid": ["illustrations", "cartoons", "abstract"],
        "prefer": ["studio_lighting", "texture_detail", "lifestyle_context"],
        "composition": "product_centered_balanced",
        "anti_ai_tactics": [
            "DSLR bokeh with natural lens characteristics",
            "Real shadows and reflections",
            "Natural lighting imperfections",
            "Authentic product textures and materials",
            "Slight color variations (not perfect gradients)"
        ]
    },
    "technology_saas": {
        "visual_approach": "mixed_illustration_and_photo",
        "photography_style": "modern_workspace_tech",
        "color_psychology": "professional_innovative",
        "illustration_style": "3d_isometric_clean",
        "tone": "innovative_trustworthy",
        "avoid": ["outdated_tech", "generic_stock_photos"],
        "prefer": ["modern_ui_screenshots", "abstract_data_viz", "team_collaboration"],
        "composition": "geometric_structured",
        "anti_ai_tactics": [
            "Mix real UI elements with illustrations",
            "Use authentic workspace photography",
            "Include real code/data in visualizations",
            "Natural screen glare and reflections"
        ]
    },
    "healthcare_medical": {
        "visual_approach": "photography_with_illustrations",
        "photography_style": "professional_empathetic",
        "color_psychology": "calm_trustworthy",
        "illustration_style": "medical_anatomical_accurate",
        "tone": "professional_caring",
        "avoid": ["cartoonish", "overly_clinical_cold", "stock_doctor_photos"],
        "prefer": ["authentic_patient_care", "medical_equipment_detail", "infographic_clarity"],
        "composition": "balanced_informative",
        "anti_ai_tactics": [
            "Real medical equipment with natural wear",
            "Authentic clinical environments",
            "Natural lighting in healthcare settings",
            "Genuine human connection moments"
        ]
    },
    "finance_banking": {
        "visual_approach": "mixed_photo_and_abstract",
        "photography_style": "professional_trustworthy",
        "color_psychology": "stable_secure",
        "illustration_style": "abstract_data_driven",
        "tone": "authoritative_reliable",
        "avoid": ["playful_casual", "overly_complex_charts"],
        "prefer": ["clean_data_visualization", "professional_handshakes", "secure_imagery"],
        "composition": "structured_hierarchical",
        "anti_ai_tactics": [
            "Real financial data visualizations",
            "Natural office environments",
            "Authentic professional interactions",
            "Subtle texture in graphics (paper, screen grain)"
        ]
    },
    "food_beverage": {
        "visual_approach": "dslr_photography_required",
        "photography_style": "food_styling_appetizing",
        "color_psychology": "warm_appetizing",
        "illustration_style": "minimal_accents_only",
        "tone": "indulgent_fresh",
        "avoid": ["over_processed_look", "artificial_colors", "cartoon_food"],
        "prefer": ["macro_detail", "steam_and_freshness", "natural_ingredients"],
        "composition": "hero_shot_appetizing",
        "anti_ai_tactics": [
            "CRITICAL: Real food texture (crust, condensation, imperfections)",
            "Natural lighting with soft shadows",
            "Slight asymmetry in plating",
            "Authentic garnish and steam effects",
            "Real wood/ceramic surface textures"
        ]
    },
    "real_estate": {
        "visual_approach": "dslr_photography_required",
        "photography_style": "architectural_lifestyle",
        "color_psychology": "aspirational_warm",
        "illustration_style": "floor_plans_only",
        "tone": "aspirational_welcoming",
        "avoid": ["overly_staged", "empty_cold_spaces"],
        "prefer": ["natural_light_emphasis", "lifestyle_staging", "architectural_detail"],
        "composition": "balanced_spacious",
        "anti_ai_tactics": [
            "Real architectural photography techniques",
            "Natural sunlight and shadows",
            "Authentic interior styling imperfections",
            "Real materials and textures (wood grain, fabric)",
            "Natural perspective (not perfect symmetry)"
        ]
    },
    "retail_fashion": {
        "visual_approach": "dslr_photography_required",
        "photography_style": "editorial_lifestyle",
        "color_psychology": "trendy_aspirational",
        "illustration_style": "pattern_accents_only",
        "tone": "stylish_confident",
        "avoid": ["catalog_boring", "generic_mannequins"],
        "prefer": ["lifestyle_context", "fabric_texture_detail", "movement_dynamic"],
        "composition": "editorial_dynamic",
        "anti_ai_tactics": [
            "CRITICAL: Real fabric texture and drape",
            "Natural movement and wrinkles",
            "Authentic skin tones and textures",
            "Real accessories and styling",
            "Natural lighting with depth"
        ]
    },
    "fitness_wellness": {
        "visual_approach": "photography_with_motion",
        "photography_style": "active_energetic",
        "color_psychology": "energetic_healthy",
        "illustration_style": "anatomical_fitness_graphics",
        "tone": "motivational_achievable",
        "avoid": ["unrealistic_bodies", "overly_polished_gym"],
        "prefer": ["real_workout_moments", "sweat_and_effort", "diverse_body_types"],
        "composition": "dynamic_energetic",
        "anti_ai_tactics": [
            "Real athletic movement blur",
            "Authentic sweat and skin texture",
            "Natural muscle definition (not CGI)",
            "Real gym/outdoor environments with wear",
            "Genuine effort expressions"
        ]
    },
    "travel_hospitality": {
        "visual_approach": "dslr_photography_required",
        "photography_style": "destination_experiential",
        "color_psychology": "wanderlust_inviting",
        "illustration_style": "map_accents_only",
        "tone": "adventurous_welcoming",
        "avoid": ["tourist_cliche", "overly_edited_skies"],
        "prefer": ["golden_hour_natural", "local_culture_authentic", "experiential_moments"],
        "composition": "expansive_immersive",
        "anti_ai_tactics": [
            "Real location photography with natural imperfections",
            "Authentic cultural elements",
            "Natural weather and lighting conditions",
            "Real people experiencing destinations",
            "Environmental texture and atmosphere"
        ]
    },
    "manufacturing_industrial": {
        "visual_approach": "photography_technical",
        "photography_style": "industrial_detailed",
        "color_psychology": "professional_powerful",
        "illustration_style": "technical_diagrams",
        "tone": "precise_capable",
        "avoid": ["generic_factory_stock", "overly_clean_unrealistic"],
        "prefer": ["machinery_detail", "process_in_action", "quality_focus"],
        "composition": "technical_precise",
        "anti_ai_tactics": [
            "Real industrial environments with authentic wear",
            "Actual machinery with proper details",
            "Natural workshop lighting",
            "Real material textures (metal, oil, dust)",
            "Authentic industrial processes"
        ]
    },
    "entertainment_media": {
        "visual_approach": "mixed_creative_bold",
        "photography_style": "cinematic_dramatic",
        "color_psychology": "bold_attention_grabbing",
        "illustration_style": "stylized_artistic",
        "tone": "exciting_engaging",
        "avoid": ["generic_posters", "overused_effects"],
        "prefer": ["dynamic_composition", "bold_typography", "emotional_impact"],
        "composition": "cinematic_impactful",
        "anti_ai_tactics": [
            "Film grain and authentic camera effects",
            "Real lighting setups (practical effects)",
            "Natural color grading (not over-processed)",
            "Authentic performance capture",
            "Organic artistic elements"
        ]
    }
}

ANTI_AI_UNIVERSAL_RULES = {
    "always_include": [
        "Natural imperfections: slight asymmetry, organic variation",
        "Real-world physics: proper shadows, reflections, depth of field",
        "Material authenticity: visible texture, grain, wear",
        "Environmental context: natural lighting conditions, atmospheric effects",
        "Human elements: authentic expressions, natural poses, real interactions"
    ],
    "always_avoid": [
        "Perfect symmetry and artificial balance",
        "Overly smooth gradients and surfaces",
        "Unnatural color saturation or HDR effects",
        "Generic stock photo aesthetics",
        "Sterile, overly-clean compositions",
        "Floating elements without proper shadows",
        "Uncanny valley human features",
        "Repetitive patterns without variation"
    ],
    "photography_authenticity": [
        "Add natural lens characteristics: slight vignetting, chromatic aberration",
        "Include depth of field bokeh with natural lens behavior",
        "Show natural lighting imperfections: hotspots, shadows, ambient bounce",
        "Capture authentic moment-in-time feel (not posed/staged)",
        "Include environmental context clues"
    ],
    "illustration_authenticity": [
        "Add hand-drawn imperfections: line weight variation, slight wobbles",
        "Use organic color transitions (not perfect gradients)",
        "Include texture overlays: paper grain, brush strokes",
        "Vary element sizes and positions naturally",
        "Add depth through overlapping and layering"
    ]
}
