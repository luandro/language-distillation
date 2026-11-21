"""Derived full-phrase training rows (ADR-0026).

A derived row is the deterministic concatenation of consecutive, verified-corresponding
attested line rows from one harvested source: a printed *stanza* (one block of the source
paper's two-column table) or a *sentence* (consecutive numbered lines up to the next sentence
end on both sides). Text is never rewritten, normalised beyond the member rows' own NFC,
translated or invented; the only added character is the recorded separator. Derived rows are
TRAIN-ONLY and carry ordered, source-qualified ``member_refs`` so leakage checks can follow
them back to the line rows (and to val/test/chant-benchmark membership).

The harvested files, their provenance strings and the layout page range are data owned by the
language profile (``LanguageProfile.harvested_sources``); this module only reads them, so no
language- or corpus-specific identifier is encoded here.

Builder: ``.venv/bin/python -m langpipe.synthesis.derived_rows build --lang <iso>``
(deterministic: no clocks, no randomness; the run id is a hash of the derivation version and
input checksums).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langpipe.languages.base import DerivedSource, HarvestedSources, profile_for

SCHEMA_VERSION = 1
DERIVATION_VERSION = "1.0.0"
SEPARATOR = " "
CHANT_REGISTER = "ritual_chant"
SPLIT_CONSTRAINT = "train_only"
UNIT_KINDS = ("stanza", "sentence")
DERIVED_GLOB = "*_derived.jsonl"
REPORT_FILE = "derived_build_report.json"
MAX_STANZA_LINES = 12

_SENTENCE_END = re.compile(r"[.!?][’”\"')\]]*\d*$")
_TRAILING_FOOTNOTE = re.compile(r"[^\W\d_][’”\"')\]]*\d+$|[.,;:!?][’”\"')\]]*\d+$")
_ZENODO_REF = re.compile(r"^(?P<prefix>.+):\((?P<n>\d+)\)$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: malformed JSON") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{path}:{number}: record is not an object")
        rows.append(record)
    return rows


def run_id_for(*parts: str) -> str:
    """Deterministic run id from the derivation version and the input checksums."""
    digest = hashlib.sha256("\0".join((DERIVATION_VERSION, *parts)).encode()).hexdigest()
    return f"derive_{digest[:16]}"


def _concat(members: list[dict[str, Any]]) -> tuple[str, str]:
    src = SEPARATOR.join(unicodedata.normalize("NFC", str(m["src"]).strip()) for m in members)
    tgt = SEPARATOR.join(unicodedata.normalize("NFC", str(m["tgt"]).strip()) for m in members)
    return src, tgt


def _record(
    *,
    row_id: str,
    unit_kind: str,
    members: list[dict[str, Any]],
    provenance: str,
    lang: str,
    source: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    src, tgt = _concat(members)
    return {
        "schema_version": SCHEMA_VERSION,
        "id": row_id,
        "lang": lang,
        "src": src,
        "tgt": tgt,
        "unit_kind": unit_kind,
        "register": CHANT_REGISTER,
        "split_constraint": SPLIT_CONSTRAINT,
        "member_refs": [{"provenance": provenance, "ref": str(m["ref"])} for m in members],
        "separator": SEPARATOR,
        "line_count": len(members),
        "source": source,
        "derivation": {"version": DERIVATION_VERSION, "run_id": run_id},
    }


# --------------------------------------------------------------------------- Wenía stanzas


def _load_split_helpers(script: Path) -> tuple[Callable[..., Any], Callable[..., Any]]:
    spec = importlib.util.spec_from_file_location("_langpipe_extract_pairs", script)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.split_table_row, module.is_table_row


def wenia_blocks(
    layout_text: str,
    rows: list[dict[str, Any]],
    split_table_row: Callable[[str], tuple[str | None, str, str] | None],
    is_table_row: Callable[[str, str], bool],
    page_range: tuple[int, int],
) -> list[dict[str, Any]]:
    """Group the harvested stanza line rows into printed blocks.

    The source paper is re-read with the extractor's own row test, so a row index matches the
    harvested ``qc.page``/``qc.row``. A block ends at a blank line, at any non-table text line
    (a heading, a footnote, or a one-cell line whose other side is missing) or at a page end.
    Every accepted line must equal its harvested row's translation, else ``ValueError``: no
    block is built from lines that cannot be verified against the extraction.
    Returns ``[{"page", "rows", "end"}]`` where ``end`` is ``blank|unpaired|page_end``.
    """
    by_loc = {(r["qc"]["page"], r["qc"]["row"]): r for r in rows}
    blocks: list[dict[str, Any]] = []
    for page_number, page in enumerate(layout_text.split("\f"), start=1):
        if not page_range[0] <= page_number <= page_range[1]:
            continue
        current: list[dict[str, Any]] = []
        row_index = 0

        def close(end: str, page_number: int = page_number) -> None:
            nonlocal current
            if current:
                blocks.append({"page": page_number, "rows": current, "end": end})
            current = []

        for line in page.split("\n"):
            if not line.strip():
                close("blank")
                continue
            split = split_table_row(line)
            if split is None or not is_table_row(split[1], split[2]):
                close("unpaired")
                continue
            row_index += 1
            row = by_loc.get((page_number, row_index))
            if row is None:
                raise ValueError(f"page {page_number} row {row_index}: no harvested row")
            expected = row["qc"].get("tgt_raw") or row["tgt"]
            if split[2] != expected:
                raise ValueError(f"page {page_number} row {row_index}: translation differs")
            current.append(row)
        close("page_end")
        harvested = sum(1 for key in by_loc if key[0] == page_number)
        if harvested != row_index:
            raise ValueError(f"page {page_number}: {row_index} layout rows, {harvested} harvested")
    return blocks


# --------------------------------------------------------------------------- stanza units


def build_wenia_stanzas(
    rows: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    *,
    source_file: str,
    source_sha256: str,
    pdf_sha256: str,
    provenance: str,
    lang: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(derived records, skipped blocks)`` for the printed stanza blocks."""
    run_id = run_id_for(source_sha256, pdf_sha256)
    built: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for block in blocks:
        members = block["rows"]
        first, last = members[0]["qc"]["row"], members[-1]["qc"]["row"]
        page = block["page"]
        where = f"p{page}:l{first}-l{last}"
        reason = None
        if len(members) == 1:
            reason = "single_line_block"
        elif len(members) > MAX_STANZA_LINES:
            reason = "over_max_lines"
        elif any(m["qc"].get("tgt_residual") for m in members):
            reason = "translation_ocr_residue"
        elif any(m["qc"].get("src_flags") for m in members):
            reason = "source_qc_flag"
        if reason:
            skipped.append(
                {"where": where, "lines": len(members), "reason": reason, "end": block["end"]}
            )
            continue
        built.append(
            _record(
                row_id=f"derived:cesarino-2018:{where}",
                unit_kind="stanza",
                members=members,
                provenance=provenance,
                lang=lang,
                source={
                    "file": source_file,
                    "sha256": source_sha256,
                    "layout_pdf_sha256": pdf_sha256,
                    "location": f"pdftotext -layout page {page}, rows {first}-{last}",
                    "block_end": block["end"],
                },
                run_id=run_id,
            )
        )
    return built, skipped


# --------------------------------------------------------------------------- sentence units


def _ends_sentence(text: str) -> bool:
    return _SENTENCE_END.search(text.strip()) is not None


def build_zenodo_sentences(
    rows: list[dict[str, Any]],
    *,
    source_file: str,
    source_sha256: str,
    provenance: str,
    lang: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge consecutive numbered lines up to a sentence end on BOTH sides.

    A unit closes only where the target-language line and the contact-language line both end a
    sentence, so the merged sides correspond. Lines must be consecutively numbered; a gap, a
    trailing footnote digit, or an unfinished tail is skipped with its reason, never repaired.
    """
    run_id = run_id_for(source_sha256)
    built: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    def numbered(row: dict[str, Any]) -> tuple[str, int]:
        match = _ZENODO_REF.match(str(row["ref"]))
        if match is None:
            raise ValueError(f"unexpected Zenodo ref {row['ref']!r}")
        return match["prefix"], int(match["n"])

    def flush(members: list[dict[str, Any]], closed: bool) -> None:
        if not members:
            return
        first, last = numbered(members[0])[1], numbered(members[-1])[1]
        where = f"({first})-({last})" if first != last else f"({first})"
        numbers = [numbered(m)[1] for m in members]
        reason = None
        if not closed:
            reason = "unterminated_tail"
        elif numbers != list(range(first, last + 1)):
            reason = "non_consecutive_lines"
        elif any(
            _TRAILING_FOOTNOTE.search(f"{m['src']}") or _TRAILING_FOOTNOTE.search(f"{m['tgt']}")
            for m in members
        ):
            reason = "footnote_digit_residue"
        if reason:
            skipped.append({"where": where, "lines": len(members), "reason": reason})
            return
        prefix = numbered(members[0])[0]
        built.append(
            _record(
                row_id=f"derived:{prefix}:{where}",
                unit_kind="sentence",
                members=members,
                provenance=provenance,
                lang=lang,
                source={
                    "file": source_file,
                    "sha256": source_sha256,
                    "location": f"{prefix} lines {where}",
                },
                run_id=run_id,
            )
        )

    current: list[dict[str, Any]] = []
    for row in rows:
        current.append(row)
        if _ends_sentence(str(row["src"])) and _ends_sentence(str(row["tgt"])):
            flush(current, closed=True)
            current = []
    flush(current, closed=False)
    return built, skipped


# --------------------------------------------------------------------------- loading / building


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> str:
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode()).hexdigest()


def _sources_for(lang: str) -> tuple[DerivedSource, DerivedSource, HarvestedSources]:
    """Return the profile's ``(stanza, sentence, sources)``; fail loudly when unset."""
    sources: HarvestedSources = profile_for(lang).harvested_sources
    if sources.stanza is None or sources.sentence is None:
        raise ValueError(
            f"language profile {lang!r} declares no stanza and sentence harvested sources; "
            "derived rows cannot be built for it"
        )
    return sources.stanza, sources.sentence, sources


def build_all(
    harvested_dir: Path,
    *,
    lang: str,
    pdf: Path | None = None,
    extract_script: Path | None = None,
    layout_text: str | None = None,
) -> dict[str, Any]:
    """Build both derived files into ``harvested_dir``; return the report (also written).

    The harvested file names, provenance strings and layout page range come from the language
    profile's ``harvested_sources``; ``lang`` therefore selects the data, not the code.
    """
    stanza, sentence, sources = _sources_for(lang)
    pages = sources.stanza_pages
    if pages is None:
        raise ValueError(
            f"language profile {lang!r} declares a stanza source without the layout page range; "
            "the harvested rows cannot be verified against the printed page"
        )
    stanza_path = harvested_dir / stanza.lines_file
    sentence_path = harvested_dir / sentence.lines_file
    pdf = pdf or Path(sources.stanza_pdf)
    extract_script = extract_script or Path("scripts/extract_pairs.py")
    if layout_text is None:
        layout_text = subprocess.run(
            ["pdftotext", "-layout", str(pdf), "-"], check=True, capture_output=True, text=True
        ).stdout
    split_fn, table_fn = _load_split_helpers(extract_script)
    stanza_rows = _read_jsonl(stanza_path)
    blocks = wenia_blocks(layout_text, stanza_rows, split_fn, table_fn, page_range=pages)
    stanzas, stanza_skipped = build_wenia_stanzas(
        stanza_rows,
        blocks,
        source_file=stanza_path.as_posix(),
        source_sha256=_sha256(stanza_path),
        pdf_sha256=_sha256(pdf),
        provenance=stanza.provenance,
        lang=lang,
    )
    sentence_rows = _read_jsonl(sentence_path)
    sentences, sentence_skipped = build_zenodo_sentences(
        sentence_rows,
        source_file=sentence_path.as_posix(),
        source_sha256=_sha256(sentence_path),
        provenance=sentence.provenance,
        lang=lang,
    )
    out_sha = {
        stanza.derived_file: write_jsonl(harvested_dir / stanza.derived_file, stanzas),
        sentence.derived_file: write_jsonl(harvested_dir / sentence.derived_file, sentences),
    }
    report = {
        "derivation_version": DERIVATION_VERSION,
        "separator": SEPARATOR,
        "wenia": {
            "blocks": len(blocks),
            "built": len(stanzas),
            "skipped": stanza_skipped,
            "blocks_ended_by_unpaired_line": sum(1 for b in blocks if b["end"] == "unpaired"),
        },
        "zenodo": {
            "lines": len(sentence_rows),
            "built": len(sentences),
            "skipped": sentence_skipped,
        },
        "output_sha256": out_sha,
    }
    (harvested_dir / REPORT_FILE).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


# --------------------------------------------------------------------------- loader


def load_derived_rows(
    harvested_dir: Path | str = "exports/harvested_parallel", lang_code: str = ""
) -> list[dict[str, Any]]:
    """Load derived rows as exporter rows; never as plain attested single-line rows.

    Every record is validated: wrong schema version, an empty side, a split constraint other
    than ``train_only``, an unknown unit kind or empty ``member_refs`` raises ``ValueError``.
    Rows carry ``is_derived=True`` and ``is_attested=False`` and a ``derived`` metadata object
    that the writers copy into every output record.
    """
    directory = Path(harvested_dir)
    if not directory.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(directory.glob(DERIVED_GLOB)):
        for number, rec in enumerate(_read_jsonl(path), start=1):
            where = f"{path}:{number}"
            if rec.get("schema_version") != SCHEMA_VERSION:
                raise ValueError(
                    f"{where}: unsupported schema_version {rec.get('schema_version')!r}"
                )
            if rec.get("split_constraint") != SPLIT_CONSTRAINT:
                raise ValueError(f"{where}: split_constraint must be {SPLIT_CONSTRAINT!r}")
            if rec.get("unit_kind") not in UNIT_KINDS:
                raise ValueError(f"{where}: unknown unit_kind {rec.get('unit_kind')!r}")
            members = rec.get("member_refs")
            if not isinstance(members, list) or not members:
                raise ValueError(f"{where}: member_refs must be a non-empty list")
            for member in members:
                if not (member.get("provenance") and member.get("ref")):
                    raise ValueError(f"{where}: member_refs need provenance and ref")
            src = unicodedata.normalize("NFC", str(rec.get("src") or "").strip())
            tgt = unicodedata.normalize("NFC", str(rec.get("tgt") or "").strip())
            if not (src and tgt and rec.get("id")):
                raise ValueError(f"{where}: empty source, target or id")
            declared = rec.get("lang")
            if lang_code and declared and declared != lang_code:
                continue
            out.append(
                {
                    "source_ref": rec["id"],
                    "target_text": src,
                    "reference_text": tgt,
                    "provenance": members[0]["provenance"],
                    "is_attested": False,
                    "is_derived": True,
                    "english": "",
                    "register": str(rec.get("register") or CHANT_REGISTER),
                    "derived": {
                        "schema_version": rec["schema_version"],
                        "unit_kind": rec["unit_kind"],
                        "split_constraint": rec["split_constraint"],
                        "member_refs": members,
                        "separator": rec.get("separator", SEPARATOR),
                        "derivation": rec.get("derivation", {}),
                    },
                }
            )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="build the *_derived.jsonl files")
    build.add_argument("--lang", required=True, help="ISO 639-3 code of the target language")
    build.add_argument("--harvested-dir", default="exports/harvested_parallel")
    build.add_argument("--pdf", default=None, help="layout PDF (defaults to the profile's)")
    build.add_argument("--extract-script", default="scripts/extract_pairs.py")
    args = parser.parse_args(argv)
    report = build_all(
        Path(args.harvested_dir),
        lang=args.lang,
        pdf=Path(args.pdf) if args.pdf else None,
        extract_script=Path(args.extract_script),
    )
    print(json.dumps({k: v for k, v in report.items() if k != "wenia"}, ensure_ascii=False))
    print(
        json.dumps(
            {k: (v if k != "skipped" else len(v)) for k, v in report["wenia"].items()},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
