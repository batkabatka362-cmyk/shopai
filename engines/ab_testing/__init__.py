"""A/B Testing Engine -- designs, runs, and analyzes A/B tests.

Pipeline: Test Hypothesis -> Experiment Designer -> Sample Size Calculator ->
          Variant Builder -> Traffic Splitter -> Metric Collector ->
          Statistical Analyzer -> Winner Selector -> Risk Assessor -> Output

Models: Mistral (experiment design, statistics), Qwen (structured output),
        LLaMA (risk assessment).

Usage:
    from engines.ab_testing import ABTestingEngine

    engine = ABTestingEngine()
    result = engine.run(input_payload)
"""
from .flow import ABTestingEngine

__all__ = ["ABTestingEngine"]
