"""Video Marketing Engine — storyboard planner.

Plans visual storyboard scenes with visual descriptions,
audio cues, and timing for each scene.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def plan_storyboard(
    script: dict[str, Any],
    product: dict[str, Any],
    video_type: str,
    duration_seconds: int,
) -> dict[str, Any]:
    """Plan a visual storyboard from the script.

    Args:
        script: Generated script dict (hook, body, cta).
        product: Product info dict.
        video_type: Type of video.
        duration_seconds: Total duration.

    Returns:
        Structured dict with storyboard scenes.
    """
    try:
        prod = copy.deepcopy(product)
        product_name = str(prod.get("title", "Product"))
        features = list(prod.get("features", []))

        scenes: list[dict[str, Any]] = []

        # Scene 1: Hook
        hook_duration = min(5, max(3, duration_seconds // 6))
        scenes.append({
            "scene": 1,
            "visual": _get_hook_visual(video_type, product_name),
            "audio": str(script.get("hook", "")),
            "duration": hook_duration,
        })

        # Middle scenes: Body (split into 2-4 scenes)
        body_duration = duration_seconds - hook_duration - min(5, duration_seconds // 4)
        body_scene_count = min(4, max(2, body_duration // 10))
        scene_duration = max(3, body_duration // body_scene_count)

        body_text = str(script.get("body", ""))
        body_sentences = [s.strip() for s in body_text.split(".") if s.strip()]

        for i in range(body_scene_count):
            scene_num = i + 2

            # Assign visual based on video type and scene position
            if i < len(features):
                visual = f"Close-up of {product_name} highlighting {features[i]}"
            elif video_type == "tutorial":
                visual = f"Hands demonstrating step {i + 1} with {product_name}"
            elif video_type == "testimonial":
                visual = f"Customer using {product_name} in everyday setting"
            else:
                visual = f"{product_name} shown from angle {i + 1}"

            # Assign audio from body sentences
            if i < len(body_sentences):
                audio = body_sentences[i] + "."
            else:
                audio = ""

            # Last body scene gets remaining duration
            if i == body_scene_count - 1:
                this_duration = body_duration - (scene_duration * (body_scene_count - 1))
            else:
                this_duration = scene_duration

            scenes.append({
                "scene": scene_num,
                "visual": visual,
                "audio": audio,
                "duration": max(3, this_duration),
            })

        # Final scene: CTA
        cta_duration = duration_seconds - sum(s["duration"] for s in scenes)
        cta_duration = max(3, cta_duration)
        scenes.append({
            "scene": len(scenes) + 1,
            "visual": f"{product_name} with brand logo and purchase link overlay",
            "audio": str(script.get("cta", "")),
            "duration": cta_duration,
        })

        return {
            "status": "success",
            "storyboard": scenes,
        }
    except Exception as exc:
        return {
            "status": "error",
            "storyboard": [],
            "error": f"Storyboard planning failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_hook_visual(video_type: str, product_name: str) -> str:
    """Get opening visual description based on video type."""
    visuals: dict[str, str] = {
        "product_demo": f"Dynamic reveal of {product_name} with dramatic lighting",
        "tutorial": f"Top-down shot of {product_name} and accessories laid out",
        "testimonial": "Customer speaking directly to camera, warm lighting",
        "ad": f"Fast-paced montage of {product_name} in action",
        "unboxing": f"Sealed {product_name} package on clean surface",
    }
    return visuals.get(video_type, f"Opening shot of {product_name}")
