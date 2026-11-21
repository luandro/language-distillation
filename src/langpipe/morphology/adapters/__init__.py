"""Morphology induction adapters."""

from langpipe.morphology.adapters.igt_assertion import IgtAssertionInducer
from langpipe.morphology.adapters.unsegmented import UnsegmentedInducer

__all__ = [
    "IgtAssertionInducer",
    "UnsegmentedInducer",
]
