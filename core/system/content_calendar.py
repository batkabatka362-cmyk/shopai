"""Content Calendar — schedules and plans content publishing."""
from __future__ import annotations
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("content.calendar")


class ContentCalendar:
    """Plans and schedules content for the store."""

    def generate_calendar(self, products: list[dict],
                          weeks: int = 4) -> dict[str, Any]:
        """Generate a content calendar for upcoming weeks."""
        calendar = []
        product_cycle = list(products)

        for week in range(1, weeks + 1):
            week_plan = {"week": week, "items": []}

            # Monday: Product feature blog post
            p = product_cycle[week % len(product_cycle)] if product_cycle else {}
            week_plan["items"].append({
                "day": "Monday",
                "type": "blog_post",
                "title": "Product Spotlight: {}".format(p.get("title", "Featured Product")[:30]),
                "status": "planned",
            })

            # Wednesday: Social media post
            week_plan["items"].append({
                "day": "Wednesday",
                "type": "social_media",
                "title": "Instagram + Facebook post for top product",
                "status": "planned",
            })

            # Friday: Email to subscribers
            topics = ["New arrivals", "Weekend sale", "Tips & tricks", "Customer spotlight"]
            week_plan["items"].append({
                "day": "Friday",
                "type": "email",
                "title": topics[(week - 1) % len(topics)],
                "status": "planned",
            })

            # Weekend: SEO content
            if week <= 2:
                week_plan["items"].append({
                    "day": "Saturday",
                    "type": "seo_page",
                    "title": "Buying guide: How to choose the right product",
                    "status": "planned",
                })

            calendar.append(week_plan)

        total_items = sum(len(w["items"]) for w in calendar)
        return {
            "weeks": weeks,
            "total_items": total_items,
            "calendar": calendar,
            "by_type": {
                "blog_post": weeks,
                "social_media": weeks,
                "email": weeks,
                "seo_page": min(weeks, 2),
            },
        }

    def get_stats(self) -> dict[str, Any]:
        return {"calendars_generated": 1}


_instance = None
def get_content_calendar():
    global _instance
    if _instance is None:
        _instance = ContentCalendar()
    return _instance
