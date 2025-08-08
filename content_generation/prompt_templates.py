class PromptTemplates:
    @staticmethod
    def get_subtopics_prompt(theme, num_subtopics, content_type):
        return (
            f"Generate {num_subtopics} distinct subtopics for the theme '{theme}'. "
            f"Each subtopic must be unique, concise (under 12 words), and tailored for a {content_type.lower()} tone. "
            f"Return as a numbered list (1., 2., etc.), with no markdown (e.g., no ** or *). "
            f"Focus on vivid, image-ready concepts relevant to the theme. Avoid overlap or repetition."
        )

    @staticmethod
    def get_image_content_prompt(theme, subtopic, content_type):
        return (
            f"Create a vivid, image-ready description (50-100 words) for the subtopic '{subtopic}' under the theme '{theme}'. "
            f"Describe a specific, visually rich scene with concrete objects, colors, settings, and actions, optimized for an image generator. "
            f"Use a {content_type.lower()} tone, emphasizing engaging, clear visuals relevant to the theme. "
            f"Avoid abstract terms, copyrighted elements, or specific brand names unless provided in the theme. "
            f"Ensure the description is concise and free of repetition."
        )

    @staticmethod
    def get_captions_prompt(subtopic, content_type):
        return (
            f"Generate one engaging caption (100-150 words) for the subtopic '{subtopic}'. "
            f"Use a {content_type.lower()} tone, suitable for LinkedIn and Instagram, relevant to the theme. "
            f"Include 5-7 relevant hashtags, emojis, and focus on engaging, clear appeal. "
            f"Avoid placeholders, repeated phrases, or references to specific brands unless explicitly mentioned in the subtopic. "
            f"Ensure the caption is concise, clear, and free of redundant text."
        )

    @staticmethod
    def get_summary_prompt(theme, subtopics, captions, content_type):
        return (
            f"Summarize the theme '{theme}' with subtopics {subtopics} into 3 concise lines. "
            f"Each line under 15 words, {content_type.lower()} tone, vivid, image-friendly, no markdown."
        )