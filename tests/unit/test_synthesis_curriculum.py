"""Unit tests for stratified curriculum generator (WP 2.2)."""

from __future__ import annotations

from langpipe.synthesis.curriculum import (
    CurriculumDistribution,
    StratifiedCurriculumGenerator,
)
from langpipe.synthesis.grammar import GrammarClauseType
from tests.fixtures.artifacts import requires_built_lexicon


def test_curriculum_distribution_counts():
    dist = CurriculumDistribution()
    counts = dist.compute_counts(total=100)

    assert sum(counts.values()) == 100
    assert counts[GrammarClauseType.TRANSITIVE] >= 25
    assert counts[GrammarClauseType.INTRANSITIVE] >= 20
    assert counts[GrammarClauseType.NEGATION] >= 10
    assert counts[GrammarClauseType.INTERROGATIVE] >= 8
    assert counts[GrammarClauseType.IMPERATIVE] >= 8
    assert counts[GrammarClauseType.POSSESSION] >= 8


@requires_built_lexicon
def test_stratified_curriculum_generator_diversity():
    generator = StratifiedCurriculumGenerator(lang_code="mzr")
    batch = generator.generate_batch(total_count=60, seed=42)

    assert len(batch) == 60

    clause_types = {item["clause_type"] for item in batch}
    # All 6 clause types should be present in the generated batch
    assert GrammarClauseType.TRANSITIVE.value in clause_types
    assert GrammarClauseType.INTRANSITIVE.value in clause_types
    assert GrammarClauseType.INTERROGATIVE.value in clause_types
    assert GrammarClauseType.IMPERATIVE.value in clause_types
    assert GrammarClauseType.POSSESSION.value in clause_types

    # Every item should have required keys
    for item in batch:
        assert "target" in item and len(item["target"]) > 0
        assert "portuguese" in item and len(item["portuguese"]) > 0
        assert "igt" in item and len(item["igt"]) > 0
        assert item["valid"] is True
        assert item["quality"]["status"] == "passed"


def test_stratified_curriculum_determinism():
    generator = StratifiedCurriculumGenerator(lang_code="mzr")
    batch_a = generator.generate_batch(total_count=20, seed=123)
    batch_b = generator.generate_batch(total_count=20, seed=123)

    assert [p["target"] for p in batch_a] == [p["target"] for p in batch_b]
