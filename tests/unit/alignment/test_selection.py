"""WP3.5 run selection: explicit M2 run pins with unique-only defaults (ADR-0011 §4).

Every alignment side pins one succeeded normalization run (and, for Stage 5, one
succeeded tokenization run). Defaults are unique-only: zero applicable runs are an
input error, multiple runs raise ``AmbiguousInput``; there is no "latest" selection
and no mixture of generations. Resolution walks the existing run I/O graph only:
source -> extraction runs -> raw segments -> normalization runs -> tokenization runs.
"""

from pathlib import Path

import pytest

from langpipe.alignment.base import AlignmentSide
from langpipe.alignment.selection import resolve_alignment_side
from langpipe.app_context import AppContext
from langpipe.domain.enums import RunStage
from langpipe.domain.errors import AmbiguousInput, InvalidLineage, NotFound, SchemaViolation
from langpipe.extraction.service import ExtractionResult, extract_source
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import RegistrationResult, register_source
from langpipe.normalization.service import normalize_extraction
from langpipe.tokenization.service import tokenize_normalization
from tests.service.manifests import manifest_data, write_manifest, write_origin_file

PLAIN = "text/plain"
TSV = "text/tab-separated-values"


def _register(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    objects: list[dict[str, str]],
    *,
    languages: tuple[str, ...] = ("qaa",),
    source_type: str = "monolingual_text",
) -> RegistrationResult:
    data = manifest_data(key=key, objects=objects)
    data["source_type"] = source_type
    data["languages"] = list(languages)
    return register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))


def _extract_text(
    ctx: AppContext, tmp_path: Path, key: str, text: str
) -> tuple[RegistrationResult, ExtractionResult]:
    relative = f"texts/{key}.txt"
    write_origin_file(tmp_path, relative, text.encode("utf-8"))
    registered = _register(ctx, tmp_path, key, [{"path": relative, "media_type": PLAIN}])
    ingest_source(ctx, registered.source.id)
    return registered, extract_source(ctx, registered.source.id)


def _extract_bilingual(
    ctx: AppContext, tmp_path: Path, key: str, rows: list[tuple[str, str, str]]
) -> tuple[RegistrationResult, ExtractionResult]:
    relative = f"texts/{key}.tsv"
    content = "ref\tqaa\tpor\n" + "".join(f"{ref}\t{qaa}\t{por}\n" for ref, qaa, por in rows)
    write_origin_file(tmp_path, relative, content.encode("utf-8"))
    registered = _register(
        ctx,
        tmp_path,
        key,
        [{"path": relative, "media_type": TSV}],
        languages=("qaa", "por"),
        source_type="parallel_text",
    )
    ingest_source(ctx, registered.source.id)
    return registered, extract_source(ctx, registered.source.id)


def test_unique_run_default(ctx: AppContext, tmp_path: Path) -> None:
    registered, extraction = _extract_text(ctx, tmp_path, "sel-unique", "kanu mabi tesa")
    normalization = normalize_extraction(ctx, extraction.run.id)

    side = resolve_alignment_side(ctx, registered.source.id, None, None, None)

    assert side == AlignmentSide(
        source_id=registered.source.id,
        language="qaa",
        normalization_run_id=normalization.run.id,
        tokenization_run_id=None,
    )


def test_ambiguous_run_requires_pin(ctx: AppContext, tmp_path: Path) -> None:
    registered, extraction = _extract_text(ctx, tmp_path, "sel-amb", "kanu mabi")
    first = normalize_extraction(ctx, extraction.run.id)
    # A second normalization generation over the same extraction needs a different config;
    # the profiles override provides one without changing any input.
    second = normalize_extraction(ctx, extraction.run.id, profiles={"qaa": "unicode_nfc"})

    with pytest.raises(AmbiguousInput) as exc_info:
        resolve_alignment_side(ctx, registered.source.id, None, None, None)
    assert exc_info.value.stage is RunStage.NORMALIZATION
    assert exc_info.value.count == 2

    side = resolve_alignment_side(ctx, registered.source.id, None, second.run.id, None)
    assert side.normalization_run_id == second.run.id
    assert side.normalization_run_id != first.run.id


def test_no_mixed_generations(ctx: AppContext, tmp_path: Path) -> None:
    registered, generation_one = _extract_text(ctx, tmp_path, "sel-gen", "kanu mabi")
    # A second extraction with a changed config is a new generation; it is never silently
    # preferred over the first, and the two are not merged into one selection.
    generation_two = extract_source(ctx, registered.source.id, language="qaa")
    first = normalize_extraction(ctx, generation_one.run.id)
    normalize_extraction(ctx, generation_two.run.id)

    with pytest.raises(AmbiguousInput) as exc_info:
        resolve_alignment_side(ctx, registered.source.id, None, None, None)
    assert exc_info.value.count == 2

    # Pinning selects exactly the pinned generation, not the latest one.
    side = resolve_alignment_side(ctx, registered.source.id, None, first.run.id, None)
    assert side.normalization_run_id == first.run.id


def test_side_language_must_be_explicit_if_ambiguous(ctx: AppContext, tmp_path: Path) -> None:
    registered, extraction = _extract_bilingual(
        ctx, tmp_path, "sel-lang", [("T.1", "kanu mabi.", "O homem vê a canoa.")]
    )
    normalize_extraction(ctx, extraction.run.id)

    with pytest.raises(AmbiguousInput) as exc_info:
        resolve_alignment_side(ctx, registered.source.id, None, None, None)
    assert exc_info.value.stage is RunStage.SEGMENT_ALIGNMENT
    assert exc_info.value.count == 2

    source_side = resolve_alignment_side(ctx, registered.source.id, "qaa", None, None)
    target_side = resolve_alignment_side(ctx, registered.source.id, "por", None, None)
    assert source_side.language == "qaa"
    assert target_side.language == "por"

    # An explicit language the source does not declare is invalid before any selection.
    with pytest.raises(SchemaViolation):
        resolve_alignment_side(ctx, registered.source.id, "mzr", None, None)


def test_token_run_must_consume_selected_normalization(ctx: AppContext, tmp_path: Path) -> None:
    registered, extraction = _extract_text(ctx, tmp_path, "sel-tok", "kanu mabi tesa")
    normalization_a = normalize_extraction(ctx, extraction.run.id)
    tokenization_a = tokenize_normalization(ctx, normalization_a.run.id)

    side = resolve_alignment_side(
        ctx, registered.source.id, None, normalization_a.run.id, tokenization_a.run.id
    )
    assert side.tokenization_run_id == tokenization_a.run.id

    # A tokenization run of a different normalization generation does not match the
    # selected normalization run, even though it belongs to the same source.
    normalization_b = normalize_extraction(ctx, extraction.run.id, profiles={"qaa": "unicode_nfc"})
    tokenization_b = tokenize_normalization(ctx, normalization_b.run.id)
    with pytest.raises(InvalidLineage):
        resolve_alignment_side(
            ctx, registered.source.id, None, normalization_a.run.id, tokenization_b.run.id
        )

    side_b = resolve_alignment_side(
        ctx, registered.source.id, None, normalization_b.run.id, tokenization_b.run.id
    )
    assert side_b.tokenization_run_id == tokenization_b.run.id


def test_bilingual_same_source_allowed(ctx: AppContext, tmp_path: Path) -> None:
    registered, extraction = _extract_bilingual(
        ctx,
        tmp_path,
        "sel-bilingual",
        [
            ("T.1", "kanu mabi.", "O homem vê a canoa."),
            ("T.2", "mabi-ki nawa.", "A canoa foi ao rio."),
        ],
    )
    normalization = normalize_extraction(ctx, extraction.run.id)

    source_side = resolve_alignment_side(ctx, registered.source.id, "qaa", None, None)
    target_side = resolve_alignment_side(ctx, registered.source.id, "por", None, None)

    # Two language sides of one registered bilingual source are permitted (ADR-0011 §1);
    # both sides pin the same normalization run and differ only in language.
    assert source_side.source_id == target_side.source_id == registered.source.id
    assert source_side.normalization_run_id == target_side.normalization_run_id
    assert source_side.normalization_run_id == normalization.run.id
    assert source_side.language != target_side.language


def test_pinned_run_from_other_source_is_invalid(ctx: AppContext, tmp_path: Path) -> None:
    registered_a, extraction_a = _extract_text(ctx, tmp_path, "sel-owner-a", "kanu mabi")
    registered_b, extraction_b = _extract_text(ctx, tmp_path, "sel-owner-b", "wesa tesa")
    normalization_b = normalize_extraction(ctx, extraction_b.run.id)
    normalize_extraction(ctx, extraction_a.run.id)

    with pytest.raises(InvalidLineage):
        resolve_alignment_side(ctx, registered_a.source.id, None, normalization_b.run.id, None)


def test_no_applicable_run_is_not_found(ctx: AppContext, tmp_path: Path) -> None:
    registered, _extraction = _extract_text(ctx, tmp_path, "sel-empty", "kanu mabi")
    # Extracted but never normalized: zero applicable normalization runs is an input error.
    with pytest.raises(NotFound):
        resolve_alignment_side(ctx, registered.source.id, None, None, None)
