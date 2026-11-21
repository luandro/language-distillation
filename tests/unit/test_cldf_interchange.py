"""CLDF interchange unit contracts (WP4.10, WP4.10-CLDF-SPEC §6.1).

Covers the pure and memory-backend parts of the CLDF importer, the ``cldf_lexical``
inducer and the CLDF exporter: snapshot normalization, the pure inducer mapping,
containment, the exporter's pure builders, the round-trip, determinism, pycldf
validation and the CLI surface. Governance behaviour over PostgreSQL lives in
``tests/service/test_cldf_governance.py``.

Fixtures are CLDF datasets written by pycldf into ``tmp_path`` in the test itself
(WP4.10-CLDF-SPEC §6) and registered through the normal source registry path.
"""

import json
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pycldf
import pytest
from typer.testing import CliRunner

from langpipe.app_context import AppContext
from langpipe.cldf.exporter import (
    CLDFExporter,
    ExportEntry,
    ExportSense,
    build_attribution,
    build_rows,
    resolve_headword,
)
from langpipe.cldf.importer import CLDFImporter, check_containment, snapshot_from_dataset
from langpipe.cli.app import app
from langpipe.cli.context import reset_context_factory, set_context_factory
from langpipe.domain.enums import (
    AccessClass,
    EntityType,
    EvidenceKind,
    EvidencePolarity,
    LifecycleStatus,
    LineageKind,
    PolicyMode,
    ReviewDecisionKind,
    ReviewTaskType,
    RunIoRole,
    SourceType,
)
from langpipe.domain.errors import SchemaViolation
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.domain.models.lexical import Lexeme, Sense
from langpipe.domain.models.source import Provenance, SourcePolicy
from langpipe.ingestion.registration import register_source
from langpipe.lexicon.adapters.cldf import CLDFLexicalInducer
from langpipe.lexicon.base import LexicalInductionInput
from langpipe.lineage import revocation_impact
from langpipe.review.authority import ReviewAuthorityRegistry
from langpipe.review.service import ReviewService
from tests.contract.builders import (
    make_evidence,
    make_form,
    make_policy,
    make_run,
    make_source,
    unique_run_key,
)
from tests.service.manifests import state_counts, write_manifest

NFD = unicodedata.normalize
NOW = datetime(2026, 1, 1, tzinfo=UTC)
SECRET_FORMS = ("kupa", "maní", "fogo", "bowl", "container", "water", "fire", "stone")

MEDIA_TYPES = {".json": "application/json", ".csv": "text/csv", ".bib": "application/x-bibtex"}
SOURCE_COL = {
    "name": "Source",
    "datatype": "string",
    "separator": ";",
    "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#source",
}


def _STR(name: str) -> dict[str, str]:
    return {"name": name, "datatype": "string"}


def _write_dataset(directory: Path, kind: str) -> None:
    """Write one qaa/por CLDF dataset (Wordlist or Dictionary) into ``directory``."""
    from pycldf.sources import Source

    directory.mkdir(parents=True, exist_ok=True)
    ds: pycldf.Dataset = (
        pycldf.Wordlist.in_dir(directory)
        if kind == "wordlist"
        else pycldf.Dictionary.in_dir(directory)
    )
    ds.add_component("LanguageTable")
    ds.add_sources(Source("misc", "src-a", title="Source A", note="Citation A"))
    rows: dict[str, list[dict[str, object]]] = {}
    if kind == "wordlist":
        ds.add_component("ParameterTable")
        ds.add_columns("ParameterTable", _STR("Concepticon_ID"))
        rows["FormTable"] = [
            {
                "ID": "f1",
                "Language_ID": "lang1",
                "Parameter_ID": "agua",
                "Form": NFD("NFD", "maní"),
                "Source": ["src-a"],
            },
            {"ID": "f2", "Language_ID": "lang1", "Parameter_ID": "fogo", "Form": "kupa"},
            {"ID": "f3", "Language_ID": "lang1", "Parameter_ID": "pedra", "Form": "kupa"},
            {"ID": "f4", "Language_ID": "lang2", "Parameter_ID": "fogo", "Form": "fogo"},
        ]
        rows["ParameterTable"] = [
            {"ID": "agua", "Name": "water", "Concepticon_ID": "1234"},
            {"ID": "fogo", "Name": "fire"},
            {"ID": "pedra", "Name": "stone"},
        ]
    else:
        ds.add_columns("EntryTable", SOURCE_COL)
        ds.add_columns(
            "SenseTable",
            SOURCE_COL,
            _STR("Glosses"),
            _STR("Concept_Label"),
            _STR("Concepticon_ID"),
            _STR("Domain"),
            _STR("Register"),
            _STR("Status"),
        )
        rows["EntryTable"] = [
            {
                "ID": "e1",
                "Language_ID": "lang1",
                "Headword": "kupa",
                "Part_Of_Speech": "n.",
                "Source": ["src-a"],
            },
            {"ID": "e2", "Language_ID": "lang1", "Headword": "kupa", "Source": ["src-a"]},
        ]
        rows["SenseTable"] = [
            {"ID": "s1", "Entry_ID": "e1", "Description": "bowl", "Source": ["src-a"]},
            {"ID": "s2", "Entry_ID": "e2", "Description": "container", "Source": ["src-a"]},
        ]
    ds.write(
        **rows,
        LanguageTable=[
            {"ID": "lang1", "ISO639P3code": "qaa", "Name": "Qaa"},
            {"ID": "lang2", "ISO639P3code": "por", "Name": "Por"},
        ],
    )


def _register_dataset(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    *,
    source_type: str = "wordlist",
    mode: str = "direct",
    allow: tuple[str, ...] = ("redistribute_derived",),
    restrictions: dict[str, object] | None = None,
    subdirectory: str | None = None,
) -> str:
    """Register one written CLDF dataset under ``tmp_path/ds/<key>`` as a normal source."""
    relative = subdirectory if subdirectory is not None else f"ds/{key}"
    directory = tmp_path / relative
    _write_dataset(directory, "wordlist" if source_type == "wordlist" else "dictionary")
    if mode == "exclude":
        objects: list[dict[str, str]] = []
    else:
        objects = [
            {"path": f"{relative}/{path.name}", "media_type": MEDIA_TYPES[path.suffix]}
            for path in sorted(directory.iterdir())
        ]
    policy: dict[str, object] = {
        "mode": mode,
        "access_class": "public",
        "authority": "test-authority",
        "allow": list(allow),
    }
    if restrictions is not None:
        policy["restrictions"] = restrictions
    data = {
        "manifest_version": 1,
        "key": key,
        "title": f"Dataset {key}",
        "source_type": source_type,
        "languages": ["qaa", "por"],
        "provenance": {"acquired_from": "test", "rights_holder": "Holders", "notes": "SECRETNOTE"},
        "acquired_at": "2026-01-01T00:00:00+00:00",
        "policy": policy,
        "objects": objects,
    }
    return register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml")).source.key


def _snapshot_payload(
    ctx: AppContext, tmp_path: Path, key: str, **kwargs: str
) -> dict[str, object]:
    """Run one governed extraction and return the stored snapshot payload."""
    result = CLDFImporter(ctx).extract(_register_dataset(ctx, tmp_path, key, **kwargs))
    return json.loads(ctx.artifact_store.read_bytes(result.snapshot.sha256))


def _induce(payload: dict[str, object], *table_paths: str) -> tuple[object, dict[str, str]]:
    """Induce over a snapshot with real generated ids pinned to each table object."""
    table_objects = {path: new_id(IdPrefix.SOURCE_OBJECT) for path in table_paths}
    data = json.dumps(
        {**payload, "source_key": "fixture-key", "table_objects": table_objects}
    ).encode("utf-8")
    output = CLDFLexicalInducer().induce(
        LexicalInductionInput(
            run_id=new_id(IdPrefix.RUN),
            target_language=str(payload["target_language"]),
            contact_language=str(payload["contact_language"]),
            data=data,
            source_id=new_id(IdPrefix.SOURCE),
            source_object_id=new_id(IdPrefix.SOURCE_OBJECT),
        )
    )
    return output, table_objects


# --- 6.1.1-6.1.3: snapshot normalization -----------------------------------------------


def test_snapshot_from_wordlist_maps_sorts_normalizes_and_skips(
    ctx: AppContext, tmp_path: Path
) -> None:
    payload = _snapshot_payload(ctx, tmp_path, "snap-wl")

    forms = [row for row in payload["rows"] if row["kind"] == "form"]  # type: ignore[union-attr]
    parameters = [row for row in payload["rows"] if row["kind"] == "parameter"]  # type: ignore[union-attr]
    # f4 is the contact-language row: skipped, counted, never a target record.
    assert [row["row_id"] for row in forms] == ["f1", "f2", "f3"]  # type: ignore[index]
    assert [row["id"] for row in parameters] == ["agua", "fogo", "pedra"]  # type: ignore[index]
    keys = [(row["table_path"], row["row_id"]) for row in payload["rows"]]  # type: ignore[index]
    assert keys == sorted(keys)
    first = forms[0]
    assert first["language"] == "qaa"  # resolved through the LanguageTable
    assert first["form"] == "maní"
    assert unicodedata.is_normalized("NFC", str(first["form"]))
    assert first["parameter_id"] == "agua"
    assert first["cldf_sources"] == ["src-a"]
    counts = payload["counts"]
    assert counts["skipped"]["other_language"] == 1  # type: ignore[index]
    assert counts["skipped"]["unmapped_language"] == 0  # type: ignore[index]


def test_snapshot_from_dictionary_keeps_homonyms(ctx: AppContext, tmp_path: Path) -> None:
    payload = _snapshot_payload(ctx, tmp_path, "snap-dict", source_type="dictionary")

    entries = [row for row in payload["rows"] if row["kind"] == "entry"]  # type: ignore[union-attr]
    senses = [row for row in payload["rows"] if row["kind"] == "sense"]  # type: ignore[union-attr]
    # Two homonymous entries stay two records (Invariant 7).
    assert [row["row_id"] for row in entries] == ["e1", "e2"]  # type: ignore[index]
    assert [row["headword"] for row in entries] == ["kupa", "kupa"]  # type: ignore[index]
    assert entries[0]["pos"] == "n."  # type: ignore[index]
    assert [row["entry_id"] for row in senses] == ["e1", "e2"]  # type: ignore[index]


def test_snapshot_ignores_upstream_status_columns(ctx: AppContext, tmp_path: Path) -> None:
    directory = tmp_path / "ds" / "snap-status"
    from pycldf.sources import Source

    directory.mkdir(parents=True)
    ds = pycldf.Wordlist.in_dir(directory)
    ds.add_component("LanguageTable")
    ds.add_sources(Source("misc", "src-a", title="T"))
    ds.add_columns("FormTable", _STR("Status"), _STR("Validated"))
    ds.write(
        FormTable=[
            {
                "ID": "f1",
                "Language_ID": "lang1",
                "Parameter_ID": "agua",
                "Form": "kupa",
                "Status": "validated",
                "Validated": "true",
            }
        ],
        LanguageTable=[{"ID": "lang1", "ISO639P3code": "qaa"}],
    )

    loaded = pycldf.Dataset.from_metadata(next(directory.glob("*metadata.json")))
    payload = snapshot_from_dataset(loaded, "qaa", "por")

    assert payload["rows"] == [
        {
            "kind": "form",
            "row_id": "f1",
            "table_path": "forms.csv",
            "language": "qaa",
            "form": "kupa",
            "parameter_id": "agua",
            "cldf_sources": [],
        }
    ]


# --- 6.1.4-6.1.6: the pure inducer -------------------------------------------------------


def test_cldf_inducer_on_wordlist(ctx: AppContext, tmp_path: Path) -> None:
    payload = _snapshot_payload(ctx, tmp_path, "ind-wl")
    output, _objects = _induce(payload, "forms.csv", "parameters.csv")

    # One lexeme per distinct form: maní (one sense) and kupa (two senses).
    assert len(output.lexemes) == 2
    counts = sorted(
        sum(1 for sense in output.senses if sense.lexeme_id == lexeme.id)
        for lexeme in output.lexemes
    )
    assert counts == [1, 2]
    # One sense per row, glossed with the parameter name in the contact language.
    assert all(
        list(sense.glosses) == ["por"] and len(sense.glosses["por"]) == 1 for sense in output.senses
    )
    # Concepts are recorded upstream claims, not minted ones.
    concepts = {concept.canonical_label: concept for concept in output.concepts}
    assert set(concepts) == {"water", "fire", "stone"}
    assert concepts["water"].concepticon_id == "1234"
    assert concepts["water"].external_urn == "cldf:fixture-key:parameter:agua"
    assert concepts["fire"].concepticon_id is None
    assert concepts["water"].concept_type == "cldf_parameter"
    # Machine scoring never validates (Invariant 3); no form is minted.
    assert all(
        lexeme.status in (LifecycleStatus.CANDIDATE, LifecycleStatus.SUPPORTED)
        for lexeme in output.lexemes
    )
    assert all(
        sense.status in (LifecycleStatus.CANDIDATE, LifecycleStatus.SUPPORTED)
        for sense in output.senses
    )
    assert all(lexeme.lemma_form_id is None for lexeme in output.lexemes)
    assert output.form_links == []
    # The evidence claim key is `headword` — the exporter's single lookup.
    assert all("headword" in (item.claim or {}) for item in output.evidence_items)
    assert {item.claim["headword"] for item in output.evidence_items} == {"maní", "kupa"}  # type: ignore[index]


def test_cldf_inducer_on_dictionary(ctx: AppContext, tmp_path: Path) -> None:
    payload = _snapshot_payload(ctx, tmp_path, "ind-dict", source_type="dictionary")
    output, _objects = _induce(payload, "entries.csv", "senses.csv")

    # One lexeme per EntryTable row: homonyms stay separate (Invariant 7).
    assert len(output.lexemes) == 2
    assert all(lexeme.lemma_form_id is None for lexeme in output.lexemes)
    # `pos` is copied over as an observed upstream assertion.
    assert sorted(str(lexeme.pos) for lexeme in output.lexemes if lexeme.pos) == ["n."]
    # Each SenseTable row is one sense glossed in the contact language.
    assert len(output.senses) == 2
    assert {next(iter(sense.glosses.values()))[0] for sense in output.senses} == {
        "bowl",
        "container",
    }
    assert output.concepts == []
    assert all("headword" in (item.claim or {}) for item in output.evidence_items)


def test_cldf_inducer_lineage_edges(ctx: AppContext, tmp_path: Path) -> None:
    payload = _snapshot_payload(ctx, tmp_path, "lin-wl")
    output, objects = _induce(payload, "forms.csv", "parameters.csv", "languages.csv")

    parents: dict[str, set[str]] = {}
    for edge in output.lineage_edges:
        parents.setdefault(edge.from_id, set()).add(edge.to_id)
    # Every evidence item is derived_from its row's CSV object.
    for item in output.evidence_items:
        assert objects["forms.csv"] in parents[item.id]
    # Every concept is derived_from the ParameterTable object.
    for concept in output.concepts:
        assert objects["parameters.csv"] in parents[concept.id]
    evidence_by_target: dict[str, set[str]] = {}
    for item in output.evidence_items:
        evidence_by_target.setdefault(item.target_id, set()).add(item.id)
    for lexeme in output.lexemes:
        # The wordlist pattern: run, row object and evidence.
        assert any(parent.startswith("run_") for parent in parents[lexeme.id])
        assert objects["forms.csv"] in parents[lexeme.id]
        assert evidence_by_target.get(lexeme.id, set()) <= parents[lexeme.id]
    for sense in output.senses:
        assert any(parent.startswith("run_") for parent in parents[sense.id])
        assert sense.lexeme_id in parents[sense.id]
        assert evidence_by_target.get(sense.id, set()) <= parents[sense.id]


# --- 6.1.7: containment -------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    ["../x.csv", "/abs/x.csv", "http://example.com/x.csv", "https://example.com/x.csv"],
)
def test_containment_rejects_escaping_urls(url: str) -> None:
    metadata = {"tables": [{"url": url, "tableSchema": {"columns": []}}]}
    with pytest.raises(SchemaViolation):
        check_containment(metadata, {"forms.csv", "Wordlist-metadata.json"})


def test_containment_accepts_registered_relative_paths() -> None:
    metadata = {
        "dc:source": "sources.bib",
        "tables": [{"url": "forms.csv"}, {"url": "languages.csv"}],
    }
    check_containment(metadata, {"forms.csv", "languages.csv", "sources.bib"})


def _no_outbound_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sentinel: any csvw fetch fails the test, recording nothing (§2.3 step 6)."""
    import csvw.utils

    def no_fetch(url: object, *args: object, **kwargs: object) -> object:
        raise AssertionError(f"outbound request during governed import: {url}")

    monkeypatch.setattr(csvw.utils, "request_get", no_fetch)


def test_containment_rejects_parser_active_indirection(tmp_path: Path) -> None:
    """External ``tableSchema``/``dialect`` strings and ``@base`` overrides fail closed.

    The csvw parser fetches a string-valued schema or dialect link over HTTP during
    ``Dataset.from_metadata``, and an ``@base`` override — group, table, schema or
    ``@context`` — re-points even registered relative urls outside the materialized
    copy. Both act before our code runs again, so containment refuses them before any
    pycldf/csvw object exists (WP4.10-CLDF-SPEC §2.3 step 6).
    """
    directory = tmp_path / "ds-indirect"
    _write_dataset(directory, "dictionary")
    metadata: dict[str, Any] = json.loads(next(directory.glob("*metadata.json")).read_text())
    registered = {path.name for path in directory.iterdir()}
    first, *rest = metadata["tables"]
    external_schema = {
        **metadata,
        "tables": [{**first, "tableSchema": "https://unapproved.invalid/schema"}, *rest],
    }
    external_dialect = {
        **metadata,
        "tables": [{**first, "dialect": "https://unapproved.invalid/dialect"}, *rest],
    }
    # Group-level (inherited) schema/dialect links are fetched just like table-level ones.
    group_schema = {**metadata, "tableSchema": "https://unapproved.invalid/schema"}
    group_dialect = {**metadata, "dialect": "https://unapproved.invalid/dialect"}
    group_base = {**metadata, "@base": "https://unapproved.invalid/"}
    outside_base = {**metadata, "@base": str(tmp_path)}
    table_base = {
        **metadata,
        "tables": [{**first, "@base": "https://unapproved.invalid/"}, *rest],
    }
    schema_base = {
        **metadata,
        "tables": [
            {**first, "tableSchema": {**first["tableSchema"], "@base": "../elsewhere"}},
            *rest,
        ],
    }
    context_base = {
        **metadata,
        "@context": ["http://www.w3.org/ns/csvw", {"@base": "https://unapproved.invalid/"}],
    }
    for hostile in (
        external_schema,
        external_dialect,
        group_schema,
        group_dialect,
        group_base,
        outside_base,
        table_base,
        schema_base,
        context_base,
    ):
        with pytest.raises(SchemaViolation):
            check_containment(hostile, registered)


def test_governed_import_makes_no_outbound_request(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The governed path parses registered inline-schema datasets and never fetches."""
    _no_outbound_request(monkeypatch)
    result = CLDFImporter(ctx).extract(_register_dataset(ctx, tmp_path, "no-fetch-src"))
    assert result.reused is False
    payload = json.loads(ctx.artifact_store.read_bytes(result.snapshot.sha256))
    assert payload["rows"]  # the fixture's forms were actually parsed


def test_nested_registered_dataset_imports_without_outbound_request(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dataset nested below the source root resolves through the registered subdirectory."""
    _no_outbound_request(monkeypatch)
    key = _register_dataset(ctx, tmp_path, "nested-src", subdirectory="ds/nested-src/inner")
    result = CLDFImporter(ctx).extract(key)
    payload = json.loads(ctx.artifact_store.read_bytes(result.snapshot.sha256))
    forms = [row["row_id"] for row in payload["rows"] if row["kind"] == "form"]  # type: ignore[union-attr]
    assert forms == ["f1", "f2", "f3"]


# --- 6.1.8: exporter table builder ----------------------------------------------------------


def _export_entry(label: str) -> ExportEntry:
    sense = ExportSense(
        id=f"sense_{label}",
        description="bowl",
        glosses_json='{"por":["bowl"]}',
        concept_label=None,
        concepticon_id=None,
        domain=None,
        register=None,
        status=LifecycleStatus.VALIDATED,
        sources=("src-a",),
    )
    return ExportEntry(
        id=f"lex_{label}",
        headword="kupa",
        pos="n.",
        status=LifecycleStatus.VALIDATED,
        sources=("src-a",),
        senses=(sense,),
    )


def test_export_table_builder() -> None:
    entries = [_export_entry("b"), _export_entry("a")]

    plain_entries, plain_senses = build_rows("qaa", entries, include_supported=False)
    assert [row["ID"] for row in plain_entries] == ["lex_a", "lex_b"]
    assert [row["ID"] for row in plain_senses] == ["sense_a", "sense_b"]
    assert all("Status" not in row for row in [*plain_entries, *plain_senses])
    assert plain_entries[0]["Headword"] == "kupa"
    assert plain_senses[0]["Description"] == "bowl"
    assert plain_senses[0]["Glosses"] == '{"por":["bowl"]}'

    supported_entries, supported_senses = build_rows("qaa", entries, include_supported=True)
    assert [row["Status"] for row in supported_entries] == ["validated", "validated"]
    assert supported_senses[0]["Status"] == "validated"


# --- 6.1.9: headword resolution --------------------------------------------------------------


def _review_lexeme(**overrides: object) -> Lexeme:
    data: dict[str, object] = {
        "id": new_id(IdPrefix.LEXEME),
        "language": "qaa",
        "run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    data.update(overrides)
    return Lexeme.model_validate(data)


def _assertion(target_id: str, headword: str, **overrides: object) -> EvidenceItem:
    data: dict[str, object] = {
        "id": new_id(IdPrefix.EVIDENCE),
        "kind": EvidenceKind.DICTIONARY_ASSERTION,
        "polarity": EvidencePolarity.SUPPORTS,
        "target_id": target_id,
        "claim": {"headword": headword},
        "run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    data.update(overrides)
    return EvidenceItem.model_validate(data)


def _sense_of(lexeme: Lexeme, **overrides: object) -> Sense:
    data: dict[str, object] = {
        "id": new_id(IdPrefix.SENSE),
        "lexeme_id": lexeme.id,
        "glosses": {"por": ["bowl"]},
        "run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    data.update(overrides)
    return Sense.model_validate(data)


def _always(_id: str) -> bool:
    return True


def _none_form(_form_id: str) -> None:
    return None


def test_headword_resolution_lemma_form_wins() -> None:
    run = make_run()
    lemma = make_form(run, text="lemma-text")
    lexeme = _review_lexeme(lemma_form_id=lemma.id)

    text, reason = resolve_headword(
        lexeme,
        (),
        get_form=lambda _id: lemma,
        evidence_for=lambda _target: [_assertion(lexeme.id, "kupa")],
        allowed=_always,
    )
    assert (text, reason) == ("lemma-text", "ok")


def test_headword_resolution_from_evidence() -> None:
    lexeme = _review_lexeme()
    sense = _sense_of(lexeme)

    # One usable assertion on the lexeme itself.
    one = [_assertion(lexeme.id, "kupa")]
    text, reason = resolve_headword(
        lexeme,
        (sense,),
        get_form=_none_form,
        evidence_for=lambda target: one if target == lexeme.id else [],
        allowed=_always,
    )
    assert (text, reason) == ("kupa", "ok")

    # Two distinct headwords: never pick one.
    two = [_assertion(lexeme.id, "kupa"), _assertion(sense.id, "kupã")]
    text, reason = resolve_headword(
        lexeme,
        (sense,),
        get_form=_none_form,
        evidence_for=lambda _target: two,
        allowed=_always,
    )
    assert (text, reason) == (None, "ambiguous_form")

    # No usable evidence at all.
    text, reason = resolve_headword(
        lexeme, (sense,), get_form=_none_form, evidence_for=lambda _target: [], allowed=_always
    )
    assert (text, reason) == (None, "no_form")


def test_export_omits_row_whose_lemma_form_is_not_allowed(ctx: AppContext, tmp_path: Path) -> None:
    """§3.2 step 3: the lemma Form is a contributing entity and must be `ALLOW`.

    A lexeme whose lemma Form descends from a source that denies
    `redistribute_derived` is omitted, and its (perfectly eligible) evidence
    headword is never used as a substitute — §3.4 fixes the form source, so a
    fallback would pick a different text source than the lemma.
    """
    repo = ctx.repo
    with repo.transaction():
        registration = make_run()
        repo.add_run(registration)
        allow_policy = make_policy(allow=("ingest", "redistribute_derived"))
        deny_policy = make_policy(allow=("ingest",))
        allow_source = make_source(allow_policy, registration.id, key="allow-src")
        deny_source = make_source(deny_policy, registration.id, key="deny-src")
        repo.add_policy(allow_policy)
        repo.add_policy(deny_policy)
        repo.add_source(allow_source)
        repo.add_source(deny_source)

        form_run = make_run(run_key=unique_run_key("form-run"))
        repo.add_run(form_run)
        lemma = repo.get_or_create_form(make_form(form_run, text="shared-form"))

        ok = _review_lexeme(run_id=form_run.id)
        ok_sense = _sense_of(ok, run_id=form_run.id)
        ok_evidence = _assertion(ok.id, "kupa", run_id=form_run.id)
        bad = _review_lexeme(lemma_form_id=lemma.id, run_id=form_run.id)
        bad_sense = _sense_of(bad, run_id=form_run.id)
        bad_evidence = _assertion(bad.id, "decoy-headword", run_id=form_run.id)
        for lexeme in (ok, bad):
            repo.add_lexeme(lexeme)
            repo.set_lexeme_status(lexeme.id, LifecycleStatus.VALIDATED)
        for sense in (ok_sense, bad_sense):
            repo.add_sense(sense)
            repo.set_sense_status(sense.id, LifecycleStatus.VALIDATED)
        for evidence in (ok_evidence, bad_evidence):
            repo.add_evidence(evidence)
        edges = [
            (ok.id, ok_evidence.id),
            (ok_sense.id, ok_evidence.id),
            (bad.id, bad_evidence.id),
            (bad_sense.id, bad_evidence.id),
            (ok_evidence.id, allow_source.id),
            (bad_evidence.id, allow_source.id),
            (lemma.id, deny_source.id),
        ]
        for from_id, to_id in edges:
            repo.add_lineage_edge(
                LineageEdge(
                    id=new_id(IdPrefix.LINEAGE),
                    from_id=from_id,
                    to_id=to_id,
                    kind=LineageKind.DERIVED_FROM,
                    run_id=form_run.id,
                    created_at=ctx.clock(),
                )
            )

    exported = tmp_path / "lemma-out"
    result = CLDFExporter(ctx).export(language="qaa", output_dir=exported)
    dataset = pycldf.Dataset.from_metadata(next(exported.glob("*metadata.json")))
    entries = {str(row["ID"]): row for row in dataset["EntryTable"]}
    # The bad row is omitted even though its own ancestry allows the operation.
    assert set(entries) == {ok.id}
    assert "decoy-headword" not in {str(row["Headword"]) for row in entries.values()}
    report = json.loads(ctx.artifact_store.read_bytes(result.report.sha256))
    assert report["omitted"]["denied"] == 1


def _contributor_world(
    ctx: AppContext, form_restrictions: dict[str, object] | None = None
) -> dict[str, Any]:
    """One validated lexeme whose actual contributors have separate sources (§3.2.6).

    ``allow-src`` (public) supplies the headword evidence, ``form-src`` (restricted)
    the lemma Form, and ``sense-src`` (public) reaches the export only through the
    surviving sense — all three are contributors and must be governed as such.
    """
    repo = ctx.repo
    with repo.transaction():
        registration = make_run()
        repo.add_run(registration)

        def governed_source(key: str, access: str, restrictions: dict[str, object] | None) -> Any:
            overrides: dict[str, object] = {
                "allow": ("ingest", "redistribute_derived"),
                "access_class": access,
            }
            if restrictions is not None:
                overrides["restrictions"] = restrictions
            policy = make_policy(**overrides)
            repo.add_policy(policy)
            source = make_source(policy, registration.id, key=key)
            repo.add_source(source)
            return source

        allow_source = governed_source("allow-src", "public", None)
        form_source = governed_source("form-src", "restricted", form_restrictions)
        sense_source = governed_source("sense-src", "public", None)

        form_run = make_run(run_key=unique_run_key("contributor-form-run"))
        repo.add_run(form_run)
        lemma = repo.get_or_create_form(make_form(form_run, text="kupa-form"))

        lexeme = _review_lexeme(lemma_form_id=lemma.id, run_id=form_run.id)
        sense = _sense_of(lexeme, run_id=form_run.id)
        headword = _assertion(lexeme.id, "kupa", run_id=form_run.id)
        sense_note = make_evidence(sense.id, form_run)
        repo.add_lexeme(lexeme)
        repo.set_lexeme_status(lexeme.id, LifecycleStatus.VALIDATED)
        repo.add_sense(sense)
        repo.set_sense_status(sense.id, LifecycleStatus.VALIDATED)
        repo.add_evidence(headword)
        repo.add_evidence(sense_note)
        for from_id, to_id in (
            (lexeme.id, headword.id),
            (sense.id, headword.id),
            (headword.id, allow_source.id),
            (sense.id, sense_note.id),
            (sense_note.id, sense_source.id),
            (lemma.id, form_source.id),
        ):
            repo.add_lineage_edge(
                LineageEdge(
                    id=new_id(IdPrefix.LINEAGE),
                    from_id=from_id,
                    to_id=to_id,
                    kind=LineageKind.DERIVED_FROM,
                    run_id=form_run.id,
                    created_at=ctx.clock(),
                )
            )
    return {
        "lexeme_id": lexeme.id,
        "sense_id": sense.id,
        "allow_source": allow_source,
        "form_source": form_source,
        "sense_source": sense_source,
    }


def test_export_governs_every_contributing_source(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sources found only through the lemma Form or a surviving sense are governed too.

    The complete contributor union drives the source count, the commit locks,
    attribution validation and emission, and the most restrictive artifact access
    class; each row cites exactly its own contributors, and revocation impact from
    any consumed source reaches the exported artifacts (WP4.10-CLDF-SPEC §§3.2.6,
    3.5, 3.6, 3.8).
    """
    world = _contributor_world(
        ctx,
        form_restrictions={
            "attribution": {
                "required": True,
                "license": "CC-BY-4.0",
                "text": "Form corpus, CC BY 4.0",
            }
        },
    )
    locked: list[list[str]] = []
    original_lock = ctx.repo.lock_sources

    def spy_lock(source_ids: object, **kwargs: object) -> None:
        locked.append(list(source_ids))  # type: ignore[arg-type]
        original_lock(source_ids, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ctx.repo, "lock_sources", spy_lock)

    exported = tmp_path / "contrib-out"
    result = CLDFExporter(ctx).export(language="qaa", output_dir=exported)

    contributors = {
        world["allow_source"].id,
        world["form_source"].id,
        world["sense_source"].id,
    }
    assert result.exported["sources"] == 3
    assert locked and set(locked[0]) == contributors
    # The restricted form source propagates to every artifact's access class.
    assert all(artifact.access_class is AccessClass.RESTRICTED for artifact in result.files)

    # Complete attribution carries every contributor's key; rows cite exactly their
    # own: the entry names its headword suppliers, the sense its sense-only source.
    metadata = json.loads(next(exported.glob("*metadata.json")).read_text())
    abouts = {entry["rdf:about"] for entry in metadata["prov:wasDerivedFrom"]}  # type: ignore[index]
    assert abouts == {
        "langpipe:source:allow-src",
        "langpipe:source:form-src",
        "langpipe:source:sense-src",
    }
    bib = (exported / "sources.bib").read_text(encoding="utf-8")
    for key in ("allow-src", "form-src", "sense-src"):
        assert key in bib
    dataset = pycldf.Dataset.from_metadata(next(exported.glob("*metadata.json")))
    entry_row = next(iter(dataset["EntryTable"]))
    assert set(entry_row["Source"]) == {"allow-src", "form-src"}
    sense_row = next(iter(dataset["SenseTable"]))
    assert set(sense_row["Source"]) == {"allow-src", "sense-src"}

    # Lineage: the entry table derives from the consumed headword entities as well,
    # so revocation impact from the form source reaches the entry, metadata and bib.
    report = json.loads(ctx.artifact_store.read_bytes(result.report.sha256))
    artifact_id_by_sha = {artifact.sha256: artifact.id for artifact in result.files}
    names = {
        entry["name"]: artifact_id_by_sha[entry["sha256"]]  # type: ignore[index]
        for entry in report["files"]  # type: ignore[union-attr]
    }
    form_reachable = set(revocation_impact(ctx.repo, world["form_source"].id).artifacts)
    for name in ("entries.csv", "Dictionary-metadata.json", "sources.bib"):
        assert names[name] in form_reachable, name
    sense_reachable = set(revocation_impact(ctx.repo, world["sense_source"].id).artifacts)
    for name in ("senses.csv", "Dictionary-metadata.json", "sources.bib"):
        assert names[name] in sense_reachable, name


def test_export_refuses_when_form_source_attribution_incomplete(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Fail closed (§3.6): a contributor requiring attribution without supplying its
    citation refuses the whole export before staging — the form source is a real
    contributor even though every eligibility decision allows the operation."""
    _contributor_world(ctx, form_restrictions={"attribution": {"required": True}})

    before = state_counts(ctx)
    output = tmp_path / "contrib-refused"
    with pytest.raises(SchemaViolation):
        CLDFExporter(ctx).export(language="qaa", output_dir=output)
    assert state_counts(ctx) == before
    assert not output.exists()
    assert not list(tmp_path.glob(".contrib-refused.staging-*"))


# --- 6.1.10: attribution builder ---------------------------------------------------------------


def _policy_pair(key: str, attribution: dict[str, object], notes: str | None = None) -> object:
    return (
        SimpleNamespace(
            key=key,
            title=f"Title {key}",
            provenance=Provenance(acquired_from="x", rights_holder="Holder", notes=notes),
        ),
        SourcePolicy.model_validate(
            {
                "id": new_id(IdPrefix.POLICY),
                "mode": PolicyMode.DIRECT,
                "access_class": "public",
                "authority": "a",
                "allow": ["ingest"],
                "deny": [],
                "restrictions": {"attribution": attribution},
                "created_at": NOW,
            }
        ),
    )


def test_attribution_single_shared_license() -> None:
    payload = build_attribution(
        [
            _policy_pair(
                "src-a",
                {
                    "required": True,
                    "license": "CC-BY-4.0",
                    "license_url": "https://creativecommons.org/licenses/by/4.0/",
                    "text": "Citation A",
                },
            )
        ]
    )

    assert payload["dc_license"] == "https://creativecommons.org/licenses/by/4.0/"
    assert payload["prov"] == [
        {
            "rdf:about": "langpipe:source:src-a",
            "dc:title": "Title src-a",
            "dc:license": "https://creativecommons.org/licenses/by/4.0/",
            "dc:rightsHolder": "Holder",
            "dc:bibliographicCitation": "Citation A",
        }
    ]
    assert payload["bib"] == [
        {
            "key": "src-a",
            "title": "Title src-a",
            "note": "Citation A",
            "howpublished": "https://creativecommons.org/licenses/by/4.0/",
        }
    ]


def test_attribution_mixed_licenses_omit_dataset_level() -> None:
    shared = {"required": True, "license": "CC-BY-4.0", "text": "Citation A"}
    other = {"required": True, "license": "CC0-1.0", "text": "Citation B"}
    payload = build_attribution([_policy_pair("src-b", other), _policy_pair("src-a", shared)])

    assert payload["dc_license"] is None
    assert payload["rdfs_comment"] is not None
    assert [entry["key"] for entry in payload["bib"]] == ["src-a", "src-b"]  # type: ignore[index]


def test_attribution_required_but_missing_text_is_refused() -> None:
    with pytest.raises(SchemaViolation):
        build_attribution([_policy_pair("src-a", {"required": True, "license": "CC-BY-4.0"})])
    with pytest.raises(SchemaViolation):
        build_attribution([_policy_pair("src-a", {"required": True, "text": "Citation A"})])


def test_attribution_never_carries_provenance_notes() -> None:
    payload = build_attribution(
        [_policy_pair("src-a", {"required": False, "license": "CC-BY-4.0"}, notes="SECRETNOTE")]
    )
    assert "SECRETNOTE" not in json.dumps(payload)


# --- 6.1.11-6.1.13: round-trip, determinism, validation -----------------------------------


@dataclass(frozen=True)
class _World:
    source_key: str
    induction_run_id: str


def _validate_all(ctx: AppContext, run_id: str, reviewer: str = "linguist") -> None:
    """Authorized human review validates every lexeme and sense of one induction run."""
    authority = ReviewAuthorityRegistry()
    authority.register(reviewer, "community_linguist", ["qaa"])
    review = ReviewService(
        ctx.repo, authority, clock=ctx.clock, new_id=ctx.new_id, code_revision=ctx.code_revision
    )
    for entity, task_type in (
        (EntityType.LEXEME, ReviewTaskType.LEMMA),
        (EntityType.SENSE, ReviewTaskType.LEXICAL_SENSE),
    ):
        for object_id in _outputs(ctx, run_id, entity):
            task = review.create_task(
                object_id, task_type=task_type, required_role="community_linguist"
            )
            result = review.record_decision(
                task.id, ReviewDecisionKind.ACCEPT, reviewer, "community_linguist"
            )
            assert result.target_status is LifecycleStatus.VALIDATED

    from langpipe.review.recalc import RecalcService

    RecalcService(ctx).recalculate(all_stale=True)


def _outputs(ctx: AppContext, run_id: str, entity: EntityType) -> list[str]:
    return sorted(
        object_id
        for object_id, role in ctx.repo.list_run_io(run_id)
        if role is RunIoRole.OUTPUT and ctx.repo.entity_type_of(object_id) is entity
    )


def _claim_pairs(ctx: AppContext, run_id: str) -> set[tuple[str, str]]:
    """The (headword, gloss) observations an induction run recorded, gloss-bearing only."""
    pairs: set[tuple[str, str]] = set()
    for evidence_id in _outputs(ctx, run_id, EntityType.EVIDENCE_ITEM):
        claim = ctx.repo.get_evidence(evidence_id).claim or {}
        gloss = claim.get("gloss")
        if gloss is not None:
            pairs.add((str(claim["headword"]), str(gloss)))
    return pairs


def _export_world(ctx: AppContext, tmp_path: Path, key: str) -> _World:
    """Registered CLDF source -> governed import -> human validation of everything."""
    source_key = _register_dataset(ctx, tmp_path, key)
    _, induction = CLDFImporter(ctx).import_dataset(source_key)
    _validate_all(ctx, induction.run.id)
    return _World(source_key=source_key, induction_run_id=induction.run.id)


def _register_directory(ctx: AppContext, tmp_path: Path, key: str, directory: Path) -> str:
    """Register an exported CLDF directory like any external dataset."""
    objects = [
        {"path": f"{directory.name}/{path.name}", "media_type": MEDIA_TYPES[path.suffix]}
        for path in sorted(directory.iterdir())
    ]
    data = {
        "manifest_version": 1,
        "key": key,
        "title": f"Reimport {key}",
        "source_type": SourceType.DICTIONARY.value,
        "languages": ["qaa", "por"],
        "provenance": {"acquired_from": "test"},
        "acquired_at": "2026-01-01T00:00:00+00:00",
        "policy": {
            "mode": "direct",
            "access_class": "public",
            "authority": "test-authority",
            "allow": ["redistribute_derived"],
        },
        "objects": objects,
    }
    register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))
    return key


def test_round_trip_export_then_import(ctx: AppContext, tmp_path: Path) -> None:
    world = _export_world(ctx, tmp_path, "rt-src")
    original_pairs = _claim_pairs(ctx, world.induction_run_id)

    exported_dir = tmp_path / "out-roundtrip"
    CLDFExporter(ctx).export(language="qaa", output_dir=exported_dir)
    # The exported dataset is registered like any external source and re-imported.
    re_key = _register_directory(ctx, tmp_path, "rt-reimport", exported_dir)
    _, re_induction = CLDFImporter(ctx).import_dataset(re_key)

    assert _claim_pairs(ctx, re_induction.run.id) == original_pairs
    # Whatever came back is machine-unvalidated knowledge again (Invariant 3).
    statuses = [
        ctx.repo.get_lexeme(object_id).status
        for object_id in _outputs(ctx, re_induction.run.id, EntityType.LEXEME)
    ]
    assert statuses
    assert all(
        status in (LifecycleStatus.CANDIDATE, LifecycleStatus.SUPPORTED) for status in statuses
    )


def test_export_is_byte_deterministic(ctx: AppContext, tmp_path: Path) -> None:
    _export_world(ctx, tmp_path, "det-src")

    first = tmp_path / "det-1"
    second = tmp_path / "det-2"
    CLDFExporter(ctx).export(language="qaa", output_dir=first)
    CLDFExporter(ctx).export(language="qaa", output_dir=second)

    assert sorted(path.name for path in first.iterdir()) == sorted(
        path.name for path in second.iterdir()
    )
    for name in (path.name for path in first.iterdir()):
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_exported_dataset_passes_pycldf_validation(ctx: AppContext, tmp_path: Path) -> None:
    _export_world(ctx, tmp_path, "val-src")

    exported = tmp_path / "val-out"
    CLDFExporter(ctx).export(language="qaa", output_dir=exported)
    dataset = pycldf.Dataset.from_metadata(next(exported.glob("*metadata.json")))
    assert dataset.validate() is True


# --- 6.1.14: CLI ---------------------------------------------------------------------------


def _cli_ctx(tmp_path: Path) -> AppContext:
    from langpipe.storage.memory import InMemoryRepository
    from langpipe.storage.objects.local import LocalContentStore

    return AppContext(
        repo=InMemoryRepository(),
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=lambda: NOW,
        new_id=new_id,
        actor="test-actor",
        code_revision="test-rev",
    )


def test_cli_cldf_export_prints_only_key_value_lines(tmp_path: Path) -> None:
    ctx = _cli_ctx(tmp_path)
    set_context_factory(lambda: ctx)
    try:
        _export_world(ctx, tmp_path, "cli-src")
        result = CliRunner().invoke(
            app, ["cldf", "export", "--language", "qaa", "--output-dir", str(tmp_path / "cli-out")]
        )
    finally:
        reset_context_factory()
    assert result.exit_code == 0, result.output
    # No fixture form or gloss may ever be printed.
    for secret in SECRET_FORMS:
        assert secret not in result.stdout + result.stderr
    fields = dict(part.split("=", 1) for part in result.stdout.split())
    assert fields["entries"] == "2"
    assert fields["senses"] == "3"
    assert fields["reused"] == "false"


def test_cli_cldf_import_prints_only_key_value_lines(tmp_path: Path) -> None:
    ctx = _cli_ctx(tmp_path)
    set_context_factory(lambda: ctx)
    try:
        key = _register_dataset(ctx, tmp_path, "cli-import")
        result = CliRunner().invoke(app, ["cldf", "import", key])
    finally:
        reset_context_factory()
    assert result.exit_code == 0, result.output
    for secret in SECRET_FORMS:
        assert secret not in result.stdout + result.stderr
    fields = dict(part.split("=", 1) for part in result.stdout.split())
    assert fields["lexemes"] == "2"
    assert fields["senses"] == "3"


def test_cli_cldf_export_all_denied_exits_nonzero(tmp_path: Path) -> None:
    ctx = _cli_ctx(tmp_path)
    set_context_factory(lambda: ctx)
    try:
        # No source allows `redistribute_derived`: nothing is eligible (D8).
        key = _register_dataset(ctx, tmp_path, "cli-deny", allow=())
        _, induction = CLDFImporter(ctx).import_dataset(key)
        assert induction.run.status.value == "succeeded"
        result = CliRunner().invoke(
            app, ["cldf", "export", "--language", "qaa", "--output-dir", str(tmp_path / "no-out")]
        )
    finally:
        reset_context_factory()
    assert result.exit_code != 0
    assert "error=NoEligibleRecords" in result.stderr
    assert not (tmp_path / "no-out").exists()
