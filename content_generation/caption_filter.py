#caption_filter.py
class CaptionFilter:
    @staticmethod
    def filter_content(content_list, max_length=120, min_length=40, keywords=None):
        filtered = []
        for content in content_list:
            content = " ".join(content.split())  # Clean extra whitespace and line breaks
            word_count = len(content.split())
            if min_length <= word_count <= max_length:
                filtered.append(content)
            else:
                print(f"Content filtered out due to length: {word_count} words")
        return filtered[:1]  # Return one valid content item

    @staticmethod
    def filter_captions(captions, max_length=180, min_length=80, keywords=None):
        filtered = []
        for caption in captions:
            caption = " ".join(caption.split())  # Clean extra whitespace and line breaks
            word_count = len(caption.split())
            if min_length <= word_count <= max_length:
                filtered.append(caption)
            else:
                print(f"Caption filtered out due to length: {word_count} words")
        return filtered[:1]  # Return one valid caption

if __name__ == "__main__":
    captions = [
        "Explore generative AI’s impact on innovation! 🌟 #ArtificialIntelligence #TechFuture",
        "AI transforms industries with creative solutions! 🚀 #GenerativeAI #Innovation",
        "Discover AI’s role in shaping tomorrow! 🌍 #AIRevolution #TechTrends"
    ]
    filtered = CaptionFilter.filter_captions(captions, min_length=10)
    print(filtered)