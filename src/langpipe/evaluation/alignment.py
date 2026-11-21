"""Gold alignment matrices and corpus-level alignment metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from pydantic import Field, model_validator

from langpipe.domain.errors import AlignmentFailed
from langpipe.domain.models.base import DomainModel


class GoldTokenSelector(DomainModel):
    """Stable selector for one occurrence in a group's ordered side."""

    member: int = Field(ge=0)
    ordinal: int = Field(ge=0)
    token_id: str | None = None


class GoldSegmentMemberSelector(DomainModel):
    """Portable identity for one ordered segment member in a frozen fixture."""

    source_object_path: str
    locator: dict[str, str | int]


class GoldGroupLocatorSelector(DomainModel):
    """ID-independent group selector, scoped to a coordinate namespace and side roles."""

    namespace: str = Field(min_length=1)
    source_members: tuple[GoldSegmentMemberSelector, ...] = Field(min_length=1)
    target_members: tuple[GoldSegmentMemberSelector, ...] = Field(min_length=1)


class GoldGroup(DomainModel):
    """One frozen, ordered annotation matrix."""

    id: str
    group_id: str | None = None
    group_key: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    locator_selector: GoldGroupLocatorSelector | None = None
    source_normalization_version: str
    target_normalization_version: str
    source_tokenizer_version: str
    target_tokenizer_version: str
    source_tokens: tuple[GoldTokenSelector, ...]
    target_tokens: tuple[GoldTokenSelector, ...]
    sure_links: tuple[tuple[int, int], ...]
    possible_links: tuple[tuple[int, int], ...]
    annotated_null_source: tuple[int, ...] = ()
    annotated_null_target: tuple[int, ...] = ()
    split: str = "test"
    authority: str

    @model_validator(mode="after")
    def _validate_annotations(self) -> GoldGroup:
        if (
            sum(
                value is not None
                for value in (self.group_id, self.group_key, self.locator_selector)
            )
            != 1
        ):
            raise ValueError("gold group needs exactly one group selector")
        if not self.source_tokens or not self.target_tokens:
            raise ValueError("gold selectors must be non-empty")
        for side in (self.source_tokens, self.target_tokens):
            positions = [(s.member, s.ordinal) for s in side]
            if positions != sorted(positions) or len(positions) != len(set(positions)):
                raise ValueError("gold selectors must be unique and strictly ordered")
        if len(set(self.sure_links)) != len(self.sure_links):
            raise ValueError("duplicate sure links")
        if len(set(self.possible_links)) != len(self.possible_links):
            raise ValueError("duplicate possible links")
        if not set(self.sure_links) <= set(self.possible_links):
            raise ValueError("sure links must be possible links")
        if len(set(self.annotated_null_source)) != len(self.annotated_null_source):
            raise ValueError("duplicate source null indices")
        if len(set(self.annotated_null_target)) != len(self.annotated_null_target):
            raise ValueError("duplicate target null indices")
        for link in (*self.sure_links, *self.possible_links):
            if (
                len(link) != 2
                or not 0 <= link[0] < len(self.source_tokens)
                or not 0 <= link[1] < len(self.target_tokens)
            ):
                raise ValueError("gold link is out of bounds")
        for indices, count, linked, label in (
            (
                self.annotated_null_source,
                len(self.source_tokens),
                {i for i, _ in (*self.sure_links, *self.possible_links)},
                "source",
            ),
            (
                self.annotated_null_target,
                len(self.target_tokens),
                {j for _, j in (*self.sure_links, *self.possible_links)},
                "target",
            ),
        ):
            if any(not 0 <= index < count for index in indices):
                raise ValueError(f"{label} null index is out of bounds")
            if set(indices) & linked:
                raise ValueError(f"{label} null index contradicts a link")
        return self


class GoldAlignment(DomainModel):
    SCHEMA_NAME: ClassVar[str | None] = "alignment-gold"
    SCHEMA_VERSION: ClassVar[int] = 1

    groups: tuple[GoldGroup, ...]

    @model_validator(mode="after")
    def _groups_unique(self) -> GoldAlignment:
        ids = [g.id for g in self.groups]
        if len(ids) != len(set(ids)):
            raise ValueError("gold group IDs must be unique")
        return self


@dataclass(frozen=True)
class AlignmentMetrics:
    total_predicted: int
    total_sure: int
    total_possible: int
    sure_hits: int
    possible_hits: int
    precision: float | None
    recall: float | None
    f1: float | None
    aer: float | None
    null_source_tp: int
    null_source_fp: int
    null_source_fn: int
    null_source_precision: float | None
    null_source_recall: float | None
    null_source_annotated: int
    null_source_total: int
    null_target_tp: int
    null_target_fp: int
    null_target_fn: int
    null_target_precision: float | None
    null_target_recall: float | None
    null_target_annotated: int
    null_target_total: int
    evaluated_groups: int
    precision_groups: tuple[str, ...]
    recall_groups: tuple[str, ...]
    aer_groups: tuple[str, ...]
    null_source_groups: tuple[str, ...]
    null_target_groups: tuple[str, ...]
    reasons: tuple[str, ...]


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def evaluate_links(predicted: set[tuple[int, int]], gold: GoldAlignment) -> AlignmentMetrics:
    """Micro-evaluate predictions over ordered group-local matrices."""
    total_a = total_s = total_p = sure_hits = possible_hits = 0
    ns_tp = ns_fp = ns_fn = nt_tp = nt_fp = nt_fn = 0
    ns_annotated = nt_annotated = ns_total = nt_total = 0
    src_offset = tgt_offset = 0
    reasons: set[str] = set()
    p_groups: list[str] = []
    r_groups: list[str] = []
    aer_groups: list[str] = []
    ns_groups: list[str] = []
    nt_groups: list[str] = []
    validated: set[tuple[int, int]] = set()
    for group in gold.groups:
        sure, possible = set(group.sure_links), set(group.possible_links)
        local_a = {
            (i - src_offset, j - tgt_offset)
            for i, j in predicted
            if src_offset <= i < src_offset + len(group.source_tokens)
            and tgt_offset <= j < tgt_offset + len(group.target_tokens)
        }
        validated.update((i + src_offset, j + tgt_offset) for i, j in local_a)
        a_count = len(local_a)
        sh, ph = len(local_a & sure), len(local_a & possible)
        total_a += a_count
        total_s += len(sure)
        total_p += len(possible)
        sure_hits += sh
        possible_hits += ph
        if a_count:
            p_groups.append(group.id)
        if sure:
            r_groups.append(group.id)
        if a_count or sure:
            aer_groups.append(group.id)
        src_linked = {i for i, _ in local_a}
        tgt_linked = {j for _, j in local_a}
        src_linked_gold = {i for i, _ in sure | possible}
        tgt_linked_gold = {j for _, j in sure | possible}
        for nulls, linked_gold, linked_pred, side in (
            (set(group.annotated_null_source), src_linked_gold, src_linked, "source"),
            (set(group.annotated_null_target), tgt_linked_gold, tgt_linked, "target"),
        ):
            annotated = nulls | linked_gold
            tp, fp, fn = (
                len(nulls - linked_pred),
                len(linked_gold - linked_pred),
                len(nulls & linked_pred),
            )
            if side == "source":
                ns_tp += tp
                ns_fp += fp
                ns_fn += fn
                ns_annotated += len(annotated)
                ns_total += len(group.source_tokens)
                if annotated:
                    ns_groups.append(group.id)
            else:
                nt_tp += tp
                nt_fp += fp
                nt_fn += fn
                nt_annotated += len(annotated)
                nt_total += len(group.target_tokens)
                if annotated:
                    nt_groups.append(group.id)
        src_offset += len(group.source_tokens)
        tgt_offset += len(group.target_tokens)
    if validated != predicted:
        raise AlignmentFailed("invalid_gold")
    precision = _ratio(possible_hits, total_a)
    recall = _ratio(sure_hits, total_s)
    aer_denominator = total_a + total_s
    aer = None if aer_denominator == 0 else 1 - (sure_hits + possible_hits) / aer_denominator
    nsp, nsr = _ratio(ns_tp, ns_tp + ns_fp), _ratio(ns_tp, ns_tp + ns_fn)
    ntp, ntr = _ratio(nt_tp, nt_tp + nt_fp), _ratio(nt_tp, nt_tp + nt_fn)
    if precision is None:
        reasons.add("precision_undefined")
    if recall is None:
        reasons.add("recall_undefined")
    if aer is None:
        reasons.add("aer_undefined")
    if nsp is None or nsr is None:
        reasons.add("null_source_coverage_incomplete")
    if ntp is None or ntr is None:
        reasons.add("null_target_coverage_incomplete")
    return AlignmentMetrics(
        total_a,
        total_s,
        total_p,
        sure_hits,
        possible_hits,
        precision,
        recall,
        _f1(precision, recall),
        aer,
        ns_tp,
        ns_fp,
        ns_fn,
        nsp,
        nsr,
        ns_annotated,
        ns_total,
        nt_tp,
        nt_fp,
        nt_fn,
        ntp,
        ntr,
        nt_annotated,
        nt_total,
        len(gold.groups),
        tuple(p_groups),
        tuple(r_groups),
        tuple(aer_groups),
        tuple(ns_groups),
        tuple(nt_groups),
        tuple(sorted(reasons)),
    )
