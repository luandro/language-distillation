"""WP5.2 unit tests: morphology domain models (ADR-0017, M5-PLAN §7.4).

Contracts under test:
- `Morpheme`/`Allomorph`/`MorphAnalysis` are hypotheses: `candidate` by default, and
  nothing in the model layer can create `validated`;
- morpheme identity is a per-run sha256 key; allomorphs are unique by `(morpheme_id, form)`
  at the storage layer and carry NFC forms (empty only as a zero allomorph);
- segments are append-only facts about one analysis: contiguous nonnegative ordinals,
  `start <= end`, zero-width only with `is_zero`, and an allomorph reference requires
  the morpheme reference;
- features are vocabulary rows keyed `(namespace, label)`; local namespaces are
  `local:<lang>` and external namespaces are only `unimorph`/`ud`;
- `MorphGold` is a frozen benchmark fixture, not linguistic truth.
"""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from langpipe.domain.enums import (
    Abstention,
    AllomorphConditioning,
    AnalysisKind,
    FeatureAssignmentBasis,
    FormBasis,
    LifecycleStatus,
    MorphRole,
    SpanRepresentation,
)
from langpipe.domain.ids import ID_PATTERN, IdPrefix, new_id
from langpipe.domain.models.lexical import LexicalScoreBreakdown
from langpipe.domain.models.morphology import (
    Allomorph,
    Feature,
    MorphAnalysis,
    Morpheme,
    MorphGold,
    MorphSegment,
    MorphSegmentFeature,
    ScoreBreakdown,
)
from langpipe.schemas.generate import render_schema, schema_filename

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SHA = "a" * 64


def _feature(**overrides: object) -> Feature:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.FEATURE),
        "namespace": "local:mzr",
        "label": "ERG",
        "definition": "source gloss label ERG",
        "defined_by": "source_gloss_label",
        "run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    values.update(overrides)
    return Feature(**values)  # type: ignore[arg-type]


def _morpheme(**overrides: object) -> Morpheme:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.MORPHEME),
        "language": "mzr",
        "role": MorphRole.ROOT,
        "canonical_form": "ki",
        "form_basis": FormBasis.SURFACE,
        "identity_key": SHA,
        "run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    values.update(overrides)
    return Morpheme(**values)  # type: ignore[arg-type]


def _allomorph(**overrides: object) -> Allomorph:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.ALLOMORPH),
        "morpheme_id": new_id(IdPrefix.MORPHEME),
        "form": "ki",
        "form_basis": FormBasis.SURFACE,
        "conditioning": AllomorphConditioning.LEXICAL,
        "run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    values.update(overrides)
    return Allomorph(**values)  # type: ignore[arg-type]


def _segment(**overrides: object) -> MorphSegment:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.MORPH_SEGMENT),
        "analysis_id": new_id(IdPrefix.MORPH_ANALYSIS),
        "ordinal": 0,
        "start": 0,
        "end": 4,
        "surface": "mabi",
        "created_at": NOW,
    }
    values.update(overrides)
    return MorphSegment(**values)  # type: ignore[arg-type]


def _analysis(**overrides: object) -> MorphAnalysis:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.MORPH_ANALYSIS),
        "target_token_id": new_id(IdPrefix.TOKEN),
        "analysis_kind": AnalysisKind.SEGMENTED,
        "method": "igt_assertion@0.1.0",
        "span_representation": SpanRepresentation.NORMALIZED,
        "surface": "mabi-ki",
        "signature": SHA,
        "run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    values.update(overrides)
    return MorphAnalysis(**values)  # type: ignore[arg-type]


def test_score_breakdown_alias_reuses_lexical_shape() -> None:
    assert ScoreBreakdown is LexicalScoreBreakdown


def test_morpheme_defaults_to_candidate_and_never_validated() -> None:
    morpheme = _morpheme()

    assert morpheme.status is LifecycleStatus.CANDIDATE
    assert morpheme.score_breakdown is None
    assert morpheme.glosses == {}
    assert morpheme.gloss_labels == []
    # Nothing here creates validation (Invariant 3): constructing with `validated`
    # is representable only as an explicit lifecycle value, never a default; the
    # machine write path is tested in WP5.9. The model must accept the full enum.
    rejected = _morpheme(id=new_id(IdPrefix.MORPHEME), status=LifecycleStatus.REJECTED)
    assert rejected.status is LifecycleStatus.REJECTED


def test_morpheme_identity_key_is_sha256() -> None:
    with pytest.raises(ValidationError):
        _morpheme(identity_key="not-a-digest")
    morpheme = _morpheme(identity_key="b" * 64)
    assert morpheme.identity_key == "b" * 64


def test_morpheme_language_and_glosses_contract() -> None:
    morpheme = _morpheme(
        glosses={"por": ["ergativo"]},
        gloss_labels=["ERG"],
    )
    assert morpheme.glosses == {"por": ["ergativo"]}
    assert morpheme.gloss_labels == ["ERG"]

    for bad in ({"pt": ["x"]}, {"por": []}, {"por": ["  "]}):
        with pytest.raises(ValidationError):
            _morpheme(glosses=bad)  # type: ignore[arg-type]


def test_morpheme_canonical_form_is_nfc() -> None:
    with pytest.raises(ValidationError):
        _morpheme(canonical_form="ká")
    assert _morpheme(canonical_form=None).canonical_form is None
    assert _morpheme(canonical_form="ká").canonical_form == "ká"


def test_allomorph_zero_form_rules() -> None:
    assert _allomorph(form="", is_zero=True).is_zero is True
    with pytest.raises(ValidationError):
        _allomorph(form="", is_zero=False)
    with pytest.raises(ValidationError):
        _allomorph(form="kí")


def test_allomorph_conditioning_values() -> None:
    for conditioning in AllomorphConditioning:
        allomorph = _allomorph(conditioning=conditioning)
        assert allomorph.conditioning is conditioning


def test_segment_ordering_and_zero_rules() -> None:
    assert _segment().surface == "mabi"
    with pytest.raises(ValidationError):
        _segment(start=5, end=4)
    with pytest.raises(ValidationError):
        _segment(start=4, end=4, is_zero=False)
    zero = _segment(start=4, end=4, is_zero=True, surface="")
    assert zero.is_zero is True
    with pytest.raises(ValidationError):
        _segment(start=-1)


def test_segment_allomorph_requires_morpheme() -> None:
    with pytest.raises(ValidationError):
        _segment(allomorph_id=new_id(IdPrefix.ALLOMORPH))
    linked = _segment(
        morpheme_id=new_id(IdPrefix.MORPHEME),
        allomorph_id=new_id(IdPrefix.ALLOMORPH),
    )
    assert linked.allomorph_id is not None


def test_segment_foreign_keys_are_prefix_validated() -> None:
    with pytest.raises(ValidationError):
        _segment(analysis_id=new_id(IdPrefix.SEGMENT))
    with pytest.raises(ValidationError):
        _segment(morpheme_id=new_id(IdPrefix.TOKEN))
    with pytest.raises(ValidationError):
        _segment(
            morpheme_id=new_id(IdPrefix.MORPHEME),
            allomorph_id=new_id(IdPrefix.MORPHEME),
        )


def test_segment_ids_and_schema_name() -> None:
    segment = _segment()
    assert segment.SCHEMA_NAME == "morph-segment"
    assert ID_PATTERN.fullmatch(segment.id) is not None
    assert segment.id.startswith("mseg_")
    assert segment.morpheme_id is None
    assert segment.role is None
    assert segment.source_gloss is None


def test_feature_namespace_pattern() -> None:
    for namespace in ("unimorph", "ud", "local:mzr"):
        assert _feature(namespace=namespace).namespace == namespace
    for bad in ("local:ab", "local:abcd", "local:MZR", "semafor", ""):
        with pytest.raises(ValidationError):
            _feature(namespace=bad)  # type: ignore[arg-type]


def test_feature_label_and_definition_are_nonempty() -> None:
    with pytest.raises(ValidationError):
        _feature(label="")
    with pytest.raises(ValidationError):
        _feature(definition="")


def test_analysis_defaults_and_abstention() -> None:
    analysis = _analysis()
    assert analysis.SCHEMA_NAME == "morph-analysis"
    assert analysis.status is LifecycleStatus.CANDIDATE
    assert analysis.abstention is None
    assert analysis.score_breakdown is None

    unsegmented = _analysis(
        analysis_kind=AnalysisKind.UNSEGMENTED,
        abstention=Abstention.INSUFFICIENT_EVIDENCE,
        signature="c" * 64,
    )
    assert unsegmented.abstention is Abstention.INSUFFICIENT_EVIDENCE
    assert unsegmented.analysis_kind is AnalysisKind.UNSEGMENTED


def test_analysis_foreign_keys_and_signature_are_typed() -> None:
    # M4 convention: cross-references carry their own `id_field` prefix and the
    # signature is a sha256 digest.
    with pytest.raises(ValidationError):
        _analysis(target_token_id=new_id(IdPrefix.SEGMENT))
    with pytest.raises(ValidationError):
        _analysis(signature="not-a-digest")
    linked = _analysis(target_token_id=new_id(IdPrefix.TOKEN))
    assert linked.target_token_id.startswith("tok_")


def test_analysis_roundtrip_and_freeze() -> None:
    analysis = _analysis(score_breakdown=ScoreBreakdown(policy_version="morph-v1", overall=0.5))
    restored = MorphAnalysis.model_validate_json(analysis.model_dump_json())
    assert restored == analysis
    with pytest.raises(ValidationError):
        analysis.status = LifecycleStatus.VALIDATED


def test_segment_feature_join_has_no_own_id() -> None:
    join = MorphSegmentFeature(
        segment_id=new_id(IdPrefix.MORPH_SEGMENT),
        feature_id=new_id(IdPrefix.FEATURE),
        basis=FeatureAssignmentBasis.IGT_GLOSS,
        created_at=NOW,
    )
    assert join.basis is FeatureAssignmentBasis.IGT_GLOSS
    assert not hasattr(join, "id")
    with pytest.raises(ValidationError):
        join.basis = FeatureAssignmentBasis.ADAPTER


def test_segment_feature_basis_values() -> None:
    for basis in FeatureAssignmentBasis:
        join = MorphSegmentFeature(
            segment_id=new_id(IdPrefix.MORPH_SEGMENT),
            feature_id=new_id(IdPrefix.FEATURE),
            basis=basis,
            created_at=NOW,
        )
        assert join.basis is basis


def test_segment_feature_join_keys_are_prefix_validated() -> None:
    with pytest.raises(ValidationError):
        MorphSegmentFeature(
            segment_id=new_id(IdPrefix.FEATURE),
            feature_id=new_id(IdPrefix.FEATURE),
            basis=FeatureAssignmentBasis.IGT_GLOSS,
            created_at=NOW,
        )
    with pytest.raises(ValidationError):
        MorphSegmentFeature(
            segment_id=new_id(IdPrefix.MORPH_SEGMENT),
            feature_id=new_id(IdPrefix.MORPH_SEGMENT),
            basis=FeatureAssignmentBasis.IGT_GLOSS,
            created_at=NOW,
        )


def test_allomorph_morpheme_id_is_prefix_validated() -> None:
    with pytest.raises(ValidationError):
        _allomorph(morpheme_id=new_id(IdPrefix.MORPH_SEGMENT))


def test_morph_gold_is_frozen_fixture() -> None:
    gold = MorphGold(
        gold_id="morph-gold-sample",
        language="mzr",
        items=[
            {
                "selector": {"igt_ref": "1"},
                "surface": "wesa-ra",
                "segments": [[0, 4], [5, 7]],
            }
        ],
        provenance={"origin": "held-out igt records"},
    )
    assert gold.SCHEMA_NAME == "morph-gold"
    assert gold.SCHEMA_VERSION == 1
    assert gold.items[0]["surface"] == "wesa-ra"
    assert gold.items[0]["segments"] == [[0, 4], [5, 7]]
    with pytest.raises(ValidationError):
        gold.language = "por"
    with pytest.raises(ValidationError):
        MorphGold(
            gold_id="x",
            language="abc-d",
            items=[],
            provenance={},
        )
    restored = MorphGold.model_validate_json(gold.model_dump_json())
    assert restored == gold


def test_morphology_models_render_registered_schema_documents() -> None:
    for model in (Feature, Morpheme, Allomorph, MorphSegment, MorphAnalysis, MorphGold):
        document = json.loads(render_schema(model))
        assert document["x-schema-name"] == model.SCHEMA_NAME
        assert document["x-schema-version"] == 1
        assert schema_filename(model) == f"{model.SCHEMA_NAME}.v1.schema.json"
