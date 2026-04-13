"""Brand Identity Engine — flow orchestrator.

This is the FLOW file. It ONLY orchestrates — no business logic here.
Calls modules in sequence, passes data between them, returns unified result.

Pipeline:
  Business Data → Personality Profiler → Voice Builder → Story Crafter →
  Values Definer → Memory Writer → Output

Engine contract:
  Input:  {status, data: {business: {name, category, target_audience}, products, competitors}, meta, error}
  Output: {status, data: {personality, voice, story, values, positioning_statement}, meta: {engine}, error}
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .personality_profiler import profile_personality
from .voice_builder import build_voice
from .story_crafter import craft_story
from .values_definer import define_values
from .memory_reader import read_past_identities
from .memory_writer import write_identity_result


class BrandIdentityEngine:
    """Brand Identity Engine — orchestrator only, no logic."""

    ENGINE_NAME = "brand_identity"

    def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full brand identity pipeline.

        Args:
            input_payload: Engine-contract input dict.

        Returns:
            BrandIdentityOutput dict.
        """
        start = time.monotonic()

        # ---- Stage 0: Input validation (no mutation) ----
        try:
            payload = copy.deepcopy(input_payload)
        except Exception as exc:
            return self._fail(f"Input copy failed: {exc}", 0.0)

        if not isinstance(payload, dict):
            return self._fail("Input must be a dict", 0.0)

        if payload.get("status") == "fail":
            return self._fail(
                payload.get("error", "Upstream failure"), 0.0,
            )

        data = payload.get("data", {})
        if not isinstance(data, dict):
            return self._fail("Input 'data' must be a dict", 0.0)

        business = data.get("business", {})
        if not isinstance(business, dict) or not business.get("name"):
            return self._fail("Business info with 'name' is required", 0.0)

        products = data.get("products", [])
        competitors = data.get("competitors", [])

        # ---- Stage 1: Read past identities (non-blocking) ----
        _past = read_past_identities(limit=5)

        # ---- Stage 2: Personality Profiler ----
        personality_result = profile_personality(
            business=business,
            products=products,
            competitors=competitors,
        )
        if personality_result.get("status") == "error":
            return self._fail(
                f"Personality profiling failed: {personality_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        personality = personality_result.get("personality", {})

        # ---- Stage 3: Voice Builder ----
        voice_result = build_voice(
            personality=personality,
            business=business,
        )
        if voice_result.get("status") == "error":
            return self._fail(
                f"Voice building failed: {voice_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        voice = voice_result.get("voice", {})

        # ---- Stage 4: Story Crafter ----
        story_result = craft_story(
            personality=personality,
            business=business,
        )
        if story_result.get("status") == "error":
            return self._fail(
                f"Story crafting failed: {story_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        story = story_result.get("story", {})

        # ---- Stage 5: Values Definer ----
        values_result = define_values(
            personality=personality,
            business=business,
            competitors=competitors,
        )
        if values_result.get("status") == "error":
            return self._fail(
                f"Values definition failed: {values_result.get('error', 'unknown')}",
                time.monotonic() - start,
            )
        values_data = values_result.get("values_result", {})
        values = values_data.get("values", [])
        positioning_statement = values_data.get("positioning_statement", "")

        # ---- Stage 6: Memory Writer (non-fatal) ----
        _write_result = write_identity_result(
            personality=personality,
            voice=voice,
            story=story,
            values=values,
            positioning_statement=positioning_statement,
        )

        # ---- Stage 7: Assemble output ----
        elapsed = time.monotonic() - start

        return {
            "status": "success",
            "data": {
                "personality": {
                    "archetype": personality.get("archetype", ""),
                    "traits": personality.get("traits", []),
                },
                "voice": {
                    "tone": voice.get("tone", ""),
                    "vocabulary": voice.get("vocabulary", []),
                    "dos": voice.get("dos", []),
                    "donts": voice.get("donts", []),
                },
                "story": {
                    "origin": story.get("origin", ""),
                    "mission": story.get("mission", ""),
                    "vision": story.get("vision", ""),
                },
                "values": values,
                "positioning_statement": positioning_statement,
            },
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": None,
        }

    # -------------------------------------------------------------------
    # Error output
    # -------------------------------------------------------------------

    def _fail(self, reason: str, elapsed: float) -> dict[str, Any]:
        """Return a standardized failure output."""
        return {
            "status": "error",
            "data": None,
            "meta": {
                "engine": self.ENGINE_NAME,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_seconds": round(elapsed, 3),
            },
            "error": reason,
        }
