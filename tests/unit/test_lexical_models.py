"""WP4.1 unit tests: lexical domain models (Concept, Lexeme, FormLexemeLink, Sense).

Contracts under test (ADR-0013, M4-PLAN §6 WP4.1):
- prefixed opaque ids and the `LifecycleStatus` default `candidate`;
- `Sense.glosses` carry language-tagged meaning hypotheses, never target-language forms;
- `form_lexeme` is a many-to-many join, so one orthographic form may back many lexemes;
- `Lexeme` carries no paradigm, slot or morphology fields in Milestone 4 (ADR-0013 §2);
- frozen models, `extra="forbid"`, UTC-only datetimes, JSON roundtrips.
"""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import BaseModel, ValidationError

from langpipe.domain.enums import LifecycleStatus
from langpipe.domain.ids import ID_PATTERN, IdPrefix, new_id
from langpipe.domain.models import Concept, FormLexemeLink, Lexeme, Sense
from langpipe.domain.models.base import DomainModel
from langpipe.domain.models.lexical import LexicalScoreBreakdown

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _concept(**overrides: object) -> Concept:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.CONCEPT),
        "canonical_label": "canoa",
        "run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    values.update(overrides)
    return Concept(**values)  # type: ignore[arg-type]


def _lexeme(**overrides: object) -> Lexeme:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.LEXEME),
        "language": "mzr",
        "run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    values.update(overrides)
    return Lexeme(**values)  # type: ignore[arg-type]


def _link(**overrides: object) -> FormLexemeLink:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.FORM_LEXEME),
        "form_id": new_id(IdPrefix.FORM),
        "lexeme_id": new_id(IdPrefix.LEXEME),
        "run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    values.update(overrides)
    return FormLexemeLink(**values)  # type: ignore[arg-type]


def _sense(**overrides: object) -> Sense:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.SENSE),
        "lexeme_id": new_id(IdPrefix.LEXEME),
        "run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    values.update(overrides)
    return Sense(**values)  # type: ignore[arg-type]


def _breakdown(**overrides: object) -> LexicalScoreBreakdown:
    values: dict[str, object] = {
        "policy_version": "lexical-v1",
        "overall": 0.5,
    }
    values.update(overrides)
    return LexicalScoreBreakdown(**values)  # type: ignore[arg-type]


ALL_MODELS = (_concept, _lexeme, _link, _sense)


@pytest.mark.parametrize(
    ("factory", "prefix"),
    [
        (_concept, IdPrefix.CONCEPT),
        (_lexeme, IdPrefix.LEXEME),
        (_link, IdPrefix.FORM_LEXEME),
        (_sense, IdPrefix.SENSE),
    ],
)
def test_ids_carry_plan_prefixes(factory, prefix: IdPrefix) -> None:
    model = factory()
    assert ID_PATTERN.match(model.id) is not None
    assert model.id.startswith(f"{prefix.value}_")
    assert new_id(prefix).startswith(f"{prefix.value}_")


@pytest.mark.parametrize(
    ("factory", "field", "prefix"),
    [
        (_concept, "run_id", IdPrefix.RUN),
        (_lexeme, "run_id", IdPrefix.RUN),
        (_lexeme, "lemma_form_id", IdPrefix.FORM),
        (_link, "form_id", IdPrefix.FORM),
        (_link, "lexeme_id", IdPrefix.LEXEME),
        (_sense, "lexeme_id", IdPrefix.LEXEME),
        (_sense, "concept_id", IdPrefix.CONCEPT),
    ],
)
def test_foreign_ids_are_rejected(factory, field: str, prefix: IdPrefix) -> None:
    wrong = new_id(IdPrefix.SEGMENT) if prefix is not IdPrefix.SEGMENT else new_id(IdPrefix.SOURCE)
    with pytest.raises(ValidationError):
        factory(**{field: wrong})


@pytest.mark.parametrize("factory", ALL_MODELS)
def test_models_are_frozen_domain_models(factory) -> None:
    model = factory()
    assert isinstance(model, DomainModel)
    with pytest.raises(ValidationError):
        model.created_at = NOW  # type: ignore[misc]


@pytest.mark.parametrize("factory", ALL_MODELS)
def test_extra_fields_are_forbidden(factory) -> None:
    with pytest.raises(ValidationError):
        factory(unexpected_field=1)


@pytest.mark.parametrize("factory", ALL_MODELS)
def test_naive_and_non_utc_datetimes_are_rejected(factory) -> None:
    with pytest.raises(ValidationError):
        factory(created_at=datetime(2026, 1, 1))
    with pytest.raises(ValidationError):
        factory(created_at=datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))))


@pytest.mark.parametrize(
    ("factory", "model"),
    [
        (_concept, Concept),
        (_lexeme, Lexeme),
        (_link, FormLexemeLink),
        (_sense, Sense),
    ],
)
def test_json_roundtrip(factory, model: type[DomainModel]) -> None:
    original = factory(
        run_id=new_id(IdPrefix.RUN),
        created_at=NOW,
    )
    if model is Lexeme:
        original = _lexeme(score_breakdown=_breakdown())
    elif model is Sense:
        original = _sense(glosses={"por": ["canoa", "embarcação"]}, score_breakdown=_breakdown())
    elif model is Concept:
        original = _concept(concepticon_id="1234", external_urn="urn:langpipe:concept:1")
    dumped = original.model_dump(mode="json")
    assert isinstance(dumped, dict)
    restored = model.model_validate(dumped)
    assert restored == original
    # Roundtrip through canonical JSON text as well.
    assert model.model_validate_json(json.dumps(dumped)) == original


@pytest.mark.parametrize("factory", ALL_MODELS)
def test_schema_names(factory) -> None:
    model = factory()
    assert isinstance(model.SCHEMA_NAME, str)
    assert model.SCHEMA_VERSION == 1


def test_schema_names_are_unique() -> None:
    names = [model.SCHEMA_NAME for model in (Concept, Lexeme, FormLexemeLink, Sense)]
    assert names == ["concept", "lexeme", "form-lexeme-link", "sense"]


def test_concept_defaults_to_local_and_optional_external_mappings() -> None:
    concept = _concept()
    assert concept.concept_type == "local"
    assert concept.concepticon_id is None
    assert concept.external_urn is None
    assert concept.canonical_label == "canoa"

    mapped = _concept(concept_type="concepticon", concepticon_id="1234")
    assert mapped.concept_type == "concepticon"
    assert mapped.concepticon_id == "1234"

    with pytest.raises(ValidationError):
        _concept(canonical_label="")
    with pytest.raises(ValidationError):
        _concept(canonical_label=None)


def test_lexume_defaults_are_candidate_and_tags_optional() -> None:
    lexeme = _lexeme()
    assert lexeme.language == "mzr"
    assert lexeme.status is LifecycleStatus.CANDIDATE
    assert lexeme.lemma_form_id is None
    assert lexeme.pos is None
    assert lexeme.register is None
    assert lexeme.domain is None
    assert lexeme.score_breakdown is None

    tagged = _lexeme(pos="noun", register="informal", domain="food")
    assert tagged.pos == "noun"
    assert tagged.register == "informal"
    assert tagged.domain == "food"

    rejected = _lexeme(status=LifecycleStatus.REJECTED)
    assert rejected.status is LifecycleStatus.REJECTED
    with pytest.raises(ValidationError):
        _lexeme(language="")


def test_lexeme_language_uses_the_shared_lang_code_syntax() -> None:
    # Same constraint as Form.language, Segment.language and Sense.glosses keys
    # (domain/models/base.py LANG_CODE): a three-letter lowercase tag, syntax only.
    assert _lexeme(language="mzr").language == "mzr"
    assert _lexeme(language="por").language == "por"
    for bad in ("", "marubo", "MZR", "Mzr", "mz", "mz-r", "mz rr", " marubo", "pt-BR"):
        with pytest.raises(ValidationError):
            _lexeme(language=bad)


def test_lexeme_carries_no_morphology_or_paradigm_fields() -> None:
    # ADR-0013 §2: morphology belongs to Milestone 5; invariant 7 of M4 scope fences.
    forbidden = ("paradigm", "paradigms", "slot", "feature", "morph", "morpheme", "inflection")
    for name in Lexeme.model_fields:
        assert not any(token in name.lower() for token in forbidden), name


def test_form_lexeme_link_is_many_to_many_join() -> None:
    form_id = new_id(IdPrefix.FORM)
    first = _lexeme(id=new_id(IdPrefix.LEXEME))
    second = _lexeme(id=new_id(IdPrefix.LEXEME))
    links = [
        _link(form_id=form_id, lexeme_id=first.id, role="primary_lemma"),
        _link(form_id=form_id, lexeme_id=second.id, role="variant"),
    ]
    assert links[0].form_id == links[1].form_id == form_id
    assert links[0].lexeme_id != links[1].lexeme_id
    assert {link.role for link in links} == {"primary_lemma", "variant"}

    assert _link().role is None
    assert _link(role=None).role is None


def test_sense_glosses_are_meaning_hypotheses() -> None:
    sense = _sense(glosses={"por": ["canoa", "embarcação"]})
    assert sense.glosses == {"por": ["canoa", "embarcação"]}
    assert _sense().glosses == {}

    multi = _sense(glosses={"por": ["canoa"], "eng": ["canoe"], "mzr": ["mabi ñekʉ"]})
    assert sorted(multi.glosses) == ["eng", "mzr", "por"]


def test_sense_status_and_tags() -> None:
    sense = _sense()
    assert sense.status is LifecycleStatus.CANDIDATE
    assert sense.domain is None
    assert sense.register is None
    assert sense.concept_id is None
    assert sense.score_breakdown is None

    tagged = _sense(domain="ritual", register="traditional", status=LifecycleStatus.SUPPORTED)
    assert tagged.domain == "ritual"
    assert tagged.register == "traditional"
    assert tagged.status is LifecycleStatus.SUPPORTED


def test_score_breakdown_is_a_frozen_value_object() -> None:
    breakdown = _breakdown()
    assert isinstance(breakdown, BaseModel)
    assert isinstance(breakdown, LexicalScoreBreakdown)
    assert not isinstance(breakdown, DomainModel)
    assert breakdown.policy_version == "lexical-v1"
    assert breakdown.overall == 0.5
    assert breakdown.components == {}
    assert breakdown.penalties == {}
    assert breakdown.independence_groups == []

    with pytest.raises(ValidationError):
        breakdown.overall = 1.0  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _breakdown(unknown=1)
    with pytest.raises(ValidationError):
        _breakdown(policy_version="")


def test_score_breakdown_rejects_nonfinite_and_boolean_scores() -> None:
    _breakdown(overall=0.0)
    _breakdown(overall=-1.5)
    for bad in (float("inf"), float("-inf"), float("nan"), True, False):
        with pytest.raises(ValidationError):
            _breakdown(overall=bad)
        with pytest.raises(ValidationError):
            _breakdown(components={"alignment": bad})
        with pytest.raises(ValidationError):
            _breakdown(penalties={"single_register": bad})


def test_score_breakdown_components_and_independence_groups_roundtrip() -> None:
    breakdown = _breakdown(
        overall=0.62,
        components={"alignment_support": 0.8, "source_diversity": 0.4},
        penalties={"single_register": 0.1},
        independence_groups=["src/pilot-01", "src/wordlist-03"],
    )
    payload = json.dumps(breakdown.model_dump(mode="json"))
    assert LexicalScoreBreakdown.model_validate_json(payload) == breakdown


def test_score_breakdown_nests_in_lexeme_and_sense() -> None:
    breakdown = _breakdown(
        overall=0.75, components={"alignment": 0.9}, independence_groups=["src/pilot-01"]
    )
    lexeme = _lexeme(score_breakdown=breakdown)
    sense = _sense(score_breakdown=breakdown)
    assert lexeme.score_breakdown == breakdown
    assert sense.score_breakdown == breakdown
    assert lexeme.model_dump(mode="json")["score_breakdown"]["overall"] == 0.75
    assert Sense.model_validate_json(sense.model_dump_json()) == sense
