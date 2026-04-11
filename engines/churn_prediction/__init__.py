"""Churn Prediction Engine — public API.

Predicts customer churn probability and recommends retention actions
based on purchase recency, engagement patterns, and behavioral signals.

Exports only the ChurnPredictionEngine orchestrator class.
"""
from .flow import ChurnPredictionEngine

__all__ = ["ChurnPredictionEngine"]
