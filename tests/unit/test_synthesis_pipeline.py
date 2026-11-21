"""Unit tests for Synthetic Data Generation and Grounding Pipeline."""

import pytest

from langpipe.synthesis.generator import SyntheticPipeline
from langpipe.synthesis.grounding import GroundingValidator
from langpipe.synthesis.providers import MockProvider, get_provider
from tests.fixtures.artifacts import requires_built_lexicon


def test_provider_factory_mock():
    provider = get_provider("mock")
    assert provider.provider_name == "Mock"
    completion = provider.complete([])
    assert "vaki" in completion


def test_provider_factory_poolside():
    provider = get_provider("poolside")
    assert provider.provider_name == "Poolside"
    assert provider.model_name == "poolside/laguna-s-2.1"
    assert "inference.poolside.ai" in provider.base_url


def test_provider_factory_unknown():
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider("nonexistent_provider")


@requires_built_lexicon
def test_grounding_validator_valid_phrase():
    validator = GroundingValidator(lang_code="mzr")
    report = validator.validate("vaki-n isu yamama-katsai")
    assert report.valid is True
    assert "vaki" in report.identified_stems
    assert "isu" in report.identified_stems
    assert "yamama" in report.identified_stems
    assert "n" in report.identified_affixes
    assert "katsai" in report.identified_affixes
    assert len(report.errors) == 0


def test_grounding_validator_rejects_hallucination():
    validator = GroundingValidator(lang_code="mzr")
    report = validator.validate("vaki-n computador yamama")
    assert report.valid is False
    assert "computador" in report.unverified_tokens
    assert any("Invariant 9" in err for err in report.errors)


def test_synthetic_pipeline_mock_execution():
    pipeline = SyntheticPipeline(lang_code="mzr", provider=MockProvider())
    phrases = pipeline.generate_phrases(count=4)
    assert len(phrases) == 4
    for p in phrases:
        assert p.target_phrase
        assert p.igt_gloss
        assert p.portuguese_translation
        assert p.provider == "Mock"
