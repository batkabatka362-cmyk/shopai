"""Customer Layer — configuration."""

CUSTOMER_LAYER_CONFIG = {
    "engines": [
        "customer_segmentation",
        "churn_prediction",
        "sentiment_analysis",
        "review_management",
        "customer_support",
        "chatbot",
        "audience_targeting",
    ],
    "required_engines": [
        "customer_segmentation",
        "audience_targeting",
    ],
    "optional_engines": [
        "churn_prediction",
        "sentiment_analysis",
        "review_management",
        "customer_support",
        "chatbot",
    ],
    "parallel_groups": [
        ["churn_prediction", "sentiment_analysis"],
        ["customer_support", "chatbot"],
    ],
}
