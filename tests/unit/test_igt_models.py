"""WP5.2 unit tests: `IGTObservation` and its parsed layer (ADR-0017 §1).

Contracts under test:
- the observation preserves the source tiers verbatim (marker, line number, raw line);
- the parsed layer is modeled on Xigt: words, morphs inside words, gloss per morph;
- boundary markers are restricted to ``-`` and ``=``;
- `parse_status` records how faithfully the tiers were parsed;
- observations are immutable evidence: frozen, `extra="forbid"`, UTC datetimes;
- ids are `igt_`-prefixed opaque ULIDs.
"""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from langpipe.domain.enums import IgtFormat, IgtParseStatus
from langpipe.domain.ids import ID_PATTERN, IdPrefix, new_id
from langpipe.domain.models.igt import IgtMorph, IGTObservation, IgtTierLine, IgtWord

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _morph(**overrides: object) -> IgtMorph:
    values: dict[str, object] = {"ordinal": 0, "text": "mabi"}
    values.update(overrides)
    return IgtMorph(**values)  # type: ignore[arg-type]


def _word(**overrides: object) -> IgtWord:
    values: dict[str, object] = {
        "ordinal": 0,
        "text": "mabi-ki",
        "morphs": [_morph()],
    }
    values.update(overrides)
    return IgtWord(**values)  # type: ignore[arg-type]


def _observation(**overrides: object) -> IGTObservation:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.IGT_OBSERVATION),
        "source_id": new_id(IdPrefix.SOURCE),
        "source_object_id": new_id(IdPrefix.SOURCE_OBJECT),
        "run_id": new_id(IdPrefix.RUN),
        "record_ordinal": 0,
        "format": IgtFormat.TOOLBOX,
        "locator": {"ref": "T.1"},
        "tiers": [IgtTierLine(marker="\\tx", line_number=1, raw="\\tx mabi-ki")],
        "words": [_word()],
        "parse_status": IgtParseStatus.OK,
        "created_at": NOW,
    }
    values.update(overrides)
    return IGTObservation(**values)  # type: ignore[arg-type]


def test_observation_roundtrip_and_ids() -> None:
    observation = _observation()

    assert observation.SCHEMA_NAME == "igt-observation"
    assert observation.SCHEMA_VERSION == 1
    assert ID_PATTERN.fullmatch(observation.id) is not None
    assert observation.id.startswith("igt_")
    assert observation.parse_status is IgtParseStatus.OK
    assert observation.segment_id is None
    assert observation.record_ref is None
    assert observation.translations == {}
    assert observation.diagnostics == []
    restored = IGTObservation.model_validate_json(observation.model_dump_json())
    assert restored == observation


def test_observation_preserves_tiers_and_parsed_words() -> None:
    observation = _observation(
        tiers=[
            IgtTierLine(marker="\\tx", line_number=3, raw="\\tx mabi-ki"),
            IgtTierLine(marker="\\mb", line_number=4, raw="\\mb mabi-ki"),
            IgtTierLine(marker="\\ge", line_number=5, raw="\\ge Peg-People-ERG"),
        ],
        words=[
            IgtWord(
                ordinal=0,
                text="mabi-ki",
                morphs=[
                    IgtMorph(ordinal=0, text="mabi", boundary_before="-", gloss="Peg-People"),
                    IgtMorph(ordinal=1, text="ki", boundary_before=None, gloss="ERG"),
                ],
            )
        ],
        translations={"por": ["dos Povo-Alfaiate"]},
        parse_status=IgtParseStatus.OK,
    )

    # Verbatim observation layer (Invariant 2): raw lines survive untouched.
    assert observation.tiers[0].raw == "\\tx mabi-ki"
    assert observation.tiers[2].marker == "\\ge"
    assert observation.tiers[2].line_number == 5
    # Parsed layer keeps source gloss strings as-is, never mapped to a scheme.
    assert observation.words[0].morphs[0].gloss == "Peg-People"
    assert observation.words[0].morphs[1].boundary_before is None
    assert observation.translations["por"] == ["dos Povo-Alfaiate"]


def test_morph_boundary_before_is_dash_or_equals() -> None:
    assert _morph(boundary_before="=").boundary_before == "="
    assert _morph(boundary_before="-").boundary_before == "-"

    for bad in ("x", "--", "", "*"):
        with pytest.raises(ValidationError):
            _morph(boundary_before=bad)


def test_observation_record_ordinal_is_nonnegative() -> None:
    with pytest.raises(ValidationError):
        _observation(record_ordinal=-1)


def test_observation_id_prefix_is_enforced() -> None:
    with pytest.raises(ValidationError):
        _observation(id=new_id(IdPrefix.SOURCE))


def test_observation_foreign_keys_are_prefix_validated() -> None:
    # M4 convention: every cross-reference carries its own `id_field` prefix.
    with pytest.raises(ValidationError):
        _observation(source_id=new_id(IdPrefix.RUN))
    with pytest.raises(ValidationError):
        _observation(source_object_id=new_id(IdPrefix.SOURCE))
    with pytest.raises(ValidationError):
        _observation(run_id=new_id(IdPrefix.SOURCE))
    with pytest.raises(ValidationError):
        _observation(segment_id=new_id(IdPrefix.SOURCE_OBJECT))
    linked = _observation(segment_id=new_id(IdPrefix.SEGMENT))
    assert linked.segment_id is not None and linked.segment_id.startswith("seg_")


def test_observation_diagnostics_and_translation_keys_are_constrained() -> None:
    # `diagnostics` are fixed machine codes, never free text that could carry
    # source content (invariant 7); `translations` keys are language tags.
    observation = _observation(
        diagnostics=["missing_tier", "unparsed_item"],
        translations={"por": ["tradução"]},
    )
    assert observation.diagnostics == ["missing_tier", "unparsed_item"]
    assert observation.translations == {"por": ["tradução"]}

    for bad_code in ("", "TierMismatch", "has space", "9start", "dash-ed", "col:on"):
        with pytest.raises(ValidationError):
            _observation(diagnostics=[bad_code])
    for bad_key in ("pt", "POR", "por2", "pt-br", ""):
        with pytest.raises(ValidationError):
            _observation(translations={bad_key: ["x"]})


def test_observation_is_frozen_and_forbids_extra() -> None:
    observation = _observation()

    with pytest.raises(ValidationError):
        observation.parse_status = IgtParseStatus.UNPARSED
    with pytest.raises(ValidationError):
        _observation(gloss="unexpected")


@pytest.mark.parametrize(
    "status", list(IgtParseStatus), ids=[status.value for status in IgtParseStatus]
)
def test_observation_parse_status_values(status: IgtParseStatus) -> None:
    assert _observation(parse_status=status).parse_status is status


def test_observation_rejects_non_utc_datetime() -> None:
    with pytest.raises(ValidationError):
        _observation(created_at=datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=2))))
    with pytest.raises(ValidationError):
        _observation(created_at=datetime(2026, 1, 1))  # naive


def test_observation_json_schema_is_registered_shape() -> None:
    schema = IGTObservation.model_json_schema(mode="serialization")
    document = json.loads(json.dumps(schema))
    assert document["properties"]["parse_status"]["$ref"].endswith("IgtParseStatus")
