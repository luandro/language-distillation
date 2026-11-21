"""Synthetic Data Generation & Grounding Validation Subsystem.

Provides pluggable LLM provider abstraction (Poolside, OpenAI, Mock),
strict morphological and lexical grounding against LKB (Invariant 9),
and zero-hallucination synthetic corpus compilation.
"""

from __future__ import annotations

from langpipe.synthesis.generator import SyntheticPhrase, SyntheticPipeline
from langpipe.synthesis.grounding import GroundingReport, GroundingValidator
from langpipe.synthesis.providers import (
    LLMProvider,
    MockProvider,
    OpenAIProvider,
    PoolsideProvider,
    get_provider,
)

__all__ = [
    "GroundingReport",
    "GroundingValidator",
    "LLMProvider",
    "MockProvider",
    "OpenAIProvider",
    "PoolsideProvider",
    "SyntheticPhrase",
    "SyntheticPipeline",
    "get_provider",
]
