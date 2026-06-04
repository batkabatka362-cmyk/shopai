"""Confidence Calibrator Engine — W963-39.

Reads per-engine outcome history from the approval queue +
computes a CALIBRATED confidence threshold per engine. The
W963-29 confidence_auto_approver uses a global threshold;
this engine derives per-engine thresholds so each engine's
trust level matches its actual track record.

Calibration logic:
  For each engine in the queue:
    1. Pull queue.engine_outcome_stats
    2. positive_ratio = positive / (positive + negative)
    3. sample = total outcomes
    4. CALIBRATION:
       - if sample < min_sample (5): unknown (use global)
       - if positive_ratio >= 0.95: relaxed (threshold 0.6)
       - if positive_ratio >= 0.80: standard (threshold 0.8)
       - if positive_ratio >= 0.60: cautious (threshold 0.9)
       - else:                       blocked (threshold 1.1, never autotrust)

Output: per-engine calibrated_threshold dict that
confidence_auto_approver can consume via env-var override
or direct API.

Bible scoring:
  Q3 (AI self-learning): system tunes its own trust thresh
     based on observed outcomes. The deterministic baseline
     future LLM brain layers on top of.
  Q4 (resilience): engines that degrade fall back to
     cautious/blocked automatically.

CLI:
  shopai calibrate                     -- view per-engine thresholds
  shopai calibrate --store STORE       -- per-store scope
  shopai calibrate --min-sample 10
  shopai calibrate --json
"""
from .flow import ConfidenceCalibratorEngine

__all__ = ["ConfidenceCalibratorEngine"]
