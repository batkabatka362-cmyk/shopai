"""Marketing Layer — configuration."""

MARKETING_LAYER_CONFIG = {
    "engines": [
        "content_generation",
        "email_marketing",
        "social_media",
        "landing_page",
        "influencer",
        "affiliate",
        "video_marketing",
        "ab_testing",
    ],
    "required_engines": [
        "content_generation",
        "ab_testing",
    ],
    "optional_engines": [
        "email_marketing",
        "social_media",
        "landing_page",
        "influencer",
        "affiliate",
        "video_marketing",
    ],
    "parallel_groups": [
        ["email_marketing", "social_media", "landing_page"],
        ["influencer", "affiliate", "video_marketing"],
    ],
}
