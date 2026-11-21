"""Unit tests for morphology inducer registry (WP5.8, M5-PLAN §6, Gate 37)."""

import pytest

from langpipe.morphology.adapters.unsegmented import UnsegmentedInducer
from langpipe.morphology.registry import (
    METHOD_UNSEGMENTED,
    MORPHOLOGY_INDUCERS,
    UnsupportedMethod,
    get_morphology_inducer,
    morphology_induction_methods,
)


def test_registry_contains_unsegmented() -> None:
    methods = morphology_induction_methods()
    assert "unsegmented@0.1.0" in methods


def test_get_morphology_inducer_exact_version() -> None:
    inducer = get_morphology_inducer("unsegmented@0.1.0")
    assert isinstance(inducer, UnsegmentedInducer)
    assert inducer.name == "unsegmented"
    assert inducer.version == "0.1.0"


def test_get_morphology_inducer_bare_name() -> None:
    inducer = get_morphology_inducer(METHOD_UNSEGMENTED)
    assert isinstance(inducer, UnsegmentedInducer)
    assert inducer.name == "unsegmented"
    assert inducer.version == "0.1.0"


def test_get_morphology_inducer_unknown_raises_unsupported_method() -> None:
    with pytest.raises(UnsupportedMethod) as excinfo:
        get_morphology_inducer("unknown_inducer")
    assert "unsupported morphology induction method" in str(excinfo.value)

    with pytest.raises(UnsupportedMethod):
        get_morphology_inducer("unsegmented@9.9.9")


def test_morphology_registry_instance_lookup() -> None:
    inducer = MORPHOLOGY_INDUCERS.get("unsegmented")
    assert isinstance(inducer, UnsegmentedInducer)

    with pytest.raises(UnsupportedMethod):
        MORPHOLOGY_INDUCERS.get("nonexistent")
