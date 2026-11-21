from __future__ import annotations

import pytest
from pydantic import ValidationError

from langpipe.domain.errors import AlignmentFailed
from langpipe.evaluation.alignment import (
    GoldAlignment,
    GoldGroup,
    GoldTokenSelector,
    evaluate_links,
)


def _selectors(count: int) -> tuple[GoldTokenSelector, ...]:
    return tuple(GoldTokenSelector(member=0, ordinal=i) for i in range(count))


def _group(**changes: object) -> GoldGroup:
    values: dict[str, object] = {
        "id": "g1",
        "group_id": "group-g1",
        "source_normalization_version": "norm@1",
        "target_normalization_version": "norm@1",
        "source_tokenizer_version": "tok@1",
        "target_tokenizer_version": "tok@1",
        "source_tokens": _selectors(3),
        "target_tokens": _selectors(3),
        "sure_links": ((0, 0), (1, 1)),
        "possible_links": ((0, 0), (1, 1), (2, 2)),
        "authority": "human",
    }
    values.update(changes)
    return GoldGroup(**values)


def test_hand_calculated_precision_recall_f1_aer() -> None:
    metrics = evaluate_links({(0, 0), (2, 2), (2, 1)}, GoldAlignment(groups=(_group(),)))
    assert metrics.precision == pytest.approx(2 / 3)
    assert metrics.recall == pytest.approx(1 / 2)
    assert metrics.f1 == pytest.approx(4 / 7)
    assert metrics.aer == pytest.approx(2 / 5)


def test_perfect_sure_set() -> None:
    group = _group(
        source_tokens=_selectors(2),
        target_tokens=_selectors(2),
        sure_links=((0, 0),),
        possible_links=((0, 0),),
    )
    metrics = evaluate_links({(0, 0)}, GoldAlignment(groups=(group,)))
    assert (metrics.precision, metrics.recall, metrics.f1, metrics.aer) == (1, 1, 1, 0)


def test_empty_predictions_with_nonempty_gold() -> None:
    metrics = evaluate_links(set(), GoldAlignment(groups=(_group(),)))
    assert metrics.precision is None and metrics.recall == 0.0 and metrics.f1 is None
    assert metrics.aer == 1.0 and "precision_undefined" in metrics.reasons


def test_both_link_sets_empty() -> None:
    group = _group(sure_links=(), possible_links=())
    metrics = evaluate_links(set(), GoldAlignment(groups=(group,)))
    assert (metrics.precision, metrics.recall, metrics.f1, metrics.aer) == (None, None, None, None)
    assert {"precision_undefined", "recall_undefined", "aer_undefined"} <= set(metrics.reasons)


def test_sure_must_be_subset_of_possible() -> None:
    with pytest.raises(ValidationError):
        _group(possible_links=())


def test_duplicate_gold_entries_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _group(sure_links=((0, 0), (0, 0)))
    with pytest.raises(ValidationError):
        _group(annotated_null_source=(2, 2))


def test_out_of_bounds_prediction_is_rejected() -> None:
    with pytest.raises(AlignmentFailed, match="invalid_gold"):
        evaluate_links({(3, 0)}, GoldAlignment(groups=(_group(),)))


@pytest.mark.parametrize(
    ("predicted", "expected_source", "expected_target", "expected_precision"),
    [
        ({(0, 0)}, (1, 0, 0), (1, 0, 0), 1.0),  # correct link and explicit nulls
        (set(), (1, 1, 0), (1, 1, 0), 0.5),  # missed link predicts both sides as null
        ({(0, 0), (1, 0), (0, 1)}, (0, 0, 1), (0, 0, 1), None),  # linked annotated nulls
        ({(0, 0), (2, 2)}, (1, 0, 0), (1, 0, 0), 1.0),  # unannotated tokens do not score
    ],
)
def test_null_confusion_matrix_and_unannotated_tokens(
    predicted: set[tuple[int, int]],
    expected_source: tuple[int, int, int],
    expected_target: tuple[int, int, int],
    expected_precision: float | None,
) -> None:
    group = _group(
        sure_links=((0, 0),),
        possible_links=((0, 0),),
        annotated_null_source=(1,),
        annotated_null_target=(1,),
    )
    metrics = evaluate_links(predicted, GoldAlignment(groups=(group,)))
    assert (
        metrics.null_source_tp,
        metrics.null_source_fp,
        metrics.null_source_fn,
    ) == expected_source
    assert (
        metrics.null_target_tp,
        metrics.null_target_fp,
        metrics.null_target_fn,
    ) == expected_target
    assert metrics.null_source_total == metrics.null_target_total == 3
    assert metrics.null_source_annotated == metrics.null_target_annotated == 2
    assert metrics.null_source_precision == metrics.null_target_precision == expected_precision


def test_empty_sure_set_with_nonempty_predictions() -> None:
    group = _group(sure_links=(), possible_links=())
    metrics = evaluate_links({(0, 0)}, GoldAlignment(groups=(group,)))
    assert metrics.total_predicted == 1
    assert metrics.total_sure == metrics.total_possible == 0
    assert metrics.precision == 0.0
    assert metrics.recall is None and metrics.f1 is None
    assert metrics.aer == 1.0


def test_contradictory_null_link_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _group(annotated_null_source=(0,))


def test_micro_aggregates_unequal_groups_and_discloses_metric_groups() -> None:
    groups = (
        _group(
            id="small",
            source_tokens=_selectors(1),
            target_tokens=_selectors(1),
            sure_links=((0, 0),),
            possible_links=((0, 0),),
        ),
        _group(
            id="large",
            source_tokens=_selectors(4),
            target_tokens=_selectors(4),
            sure_links=((0, 0), (1, 1)),
            possible_links=((0, 0), (1, 1), (2, 2), (3, 3)),
        ),
        _group(
            id="undefined",
            source_tokens=_selectors(1),
            target_tokens=_selectors(1),
            sure_links=(),
            possible_links=(),
        ),
    )
    metrics = evaluate_links({(0, 0), (1, 1), (3, 4), (4, 4)}, GoldAlignment(groups=groups))
    assert metrics.total_sure == 3 and metrics.total_possible == 5
    assert metrics.total_predicted == 4 and metrics.sure_hits == 2 and metrics.possible_hits == 3
    assert metrics.precision == pytest.approx(3 / 4)
    assert metrics.recall == pytest.approx(2 / 3)
    assert metrics.f1 == pytest.approx(12 / 17)
    assert metrics.aer == pytest.approx(2 / 7)
    assert metrics.precision_groups == ("small", "large")
    assert metrics.recall_groups == ("small", "large")
    assert metrics.aer_groups == ("small", "large")


def test_duplicate_prediction_links_are_normalized_as_a_set() -> None:
    gold = GoldAlignment(groups=(_group(),))
    unique = evaluate_links({(0, 0), (2, 2)}, gold)
    repeated_input = [(0, 0), (2, 2), (0, 0), (2, 2)]
    normalized = set(repeated_input)
    repeated = evaluate_links(normalized, gold)
    assert repeated == unique


def test_defined_zero_precision_and_recall_has_zero_f1() -> None:
    group = _group(
        source_tokens=_selectors(2),
        target_tokens=_selectors(2),
        sure_links=((0, 0),),
        possible_links=((0, 0),),
    )
    metrics = evaluate_links({(0, 1)}, GoldAlignment(groups=(group,)))
    assert metrics.precision == 0.0 and metrics.recall == 0.0 and metrics.f1 == 0.0
