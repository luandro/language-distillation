#!/usr/bin/env python3
"""Interactive Web Server for Javari LKB & Synthetic Phrase Generation.

Serves the responsive dictionary UI with curved scrollbars (#FC4847)
and provides live endpoints for generating and validating synthetic phrases.
"""

from __future__ import annotations

import json
import os
import re
import sys
import zlib
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Ensure repository root is in python path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from langpipe.synthesis.clef import get_clef_judge  # noqa: E402
from langpipe.synthesis.generator import SyntheticPipeline  # noqa: E402
from langpipe.synthesis.grounding import GroundingValidator  # noqa: E402
from langpipe.synthesis.providers import get_provider  # noqa: E402
from langpipe.synthesis.quality import QualityStatus  # noqa: E402

WEB_DIR = ROOT / "exports" / "web"
EXPORTS_DIR = ROOT / "exports"
SYNTHETIC_STORE = ROOT / "exports" / "synthetic_phrases.json"
MZR_SYNTHETIC_STORE = ROOT / "exports" / "mzr" / "synthetic_phrases.json"

# The Exports tab advertises artifacts that live in `exports/<lang>/formats/`,
# not in the static root (`exports/web/`). The `/formats/<lang>/<rest>` route
# maps `<rest>` UNDER `formats/`, so the CLDF metadata file is reachable at
# `/formats/mzr/cldf/Dictionary-metadata.json`.
FORMATS_ROOTS = {
    lang: (ROOT / "exports" / lang / "formats") for lang in ("mzr", "mcf", "mpu", "xor", "knm")
}

# Session payloads are rebuilt only when the source export's mtime changes.
_SESSION_CACHE: dict[str, tuple[float, dict]] = {}


class SyntheticLKBRequestHandler(SimpleHTTPRequestHandler):
    """Handles both static file serving and synthetic phrase generation APIs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def _send_json(self, data: dict | list, status: int = HTTPStatus.OK) -> None:
        blob = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(blob)

    # -- dictionary session -------------------------------------------------

    def _build_session(self, lang: str, view: str) -> dict:
        """Build (and cache) the dictionary session payload."""
        from langpipe.lexicon.audit.view import LexiconView
        from langpipe.lexicon.dictionary.session import DictionarySessionBuilder

        source = EXPORTS_DIR / lang / "dictionary.json"
        mtime = source.stat().st_mtime if source.exists() else 0.0
        cache_key = f"{lang}:{view}"
        cached = _SESSION_CACHE.get(cache_key)
        if cached and cached[0] == mtime:
            return cached[1]

        view_obj = LexiconView.load(lang_code=lang, view=view)
        raw = view_obj.raw_data or {}
        builder = DictionarySessionBuilder(
            target_lang=lang,
            target_name=raw.get("language_name", lang),
            contact_lang=raw.get("contact_language", "por"),
            language_family=raw.get("language_family", ""),
            glottocode=raw.get("glottocode", ""),
            territory=raw.get("territory", ""),
        )
        session = builder.build(
            view_obj.entries,
            morphology=raw.get("morphology", []),
            parallel_sentences=raw.get("parallel_sentences", []),
            # The published view is the lemma set; the audited inflected forms
            # live only in the full lexicon, so they must be read from there.
            forms_source=raw.get("lexicon", []),
        )

        session["reverse"] = self._load_reverse(lang)

        _SESSION_CACHE[cache_key] = (mtime, session)
        return session

    @staticmethod
    def _load_reverse(lang: str) -> list[dict]:
        """Read the reverse (contact -> target) index, building it if absent."""
        reverse_file = EXPORTS_DIR / lang / "dictionary.reverse.json"
        if not reverse_file.exists():
            from langpipe.lexicon.audit.view import LexiconView
            from langpipe.lexicon.reverse import ReverseLexiconIndex

            clean_view = LexiconView.load(lang_code=lang, view="clean")
            index = ReverseLexiconIndex(contact_language="por").build_from_lexicon(
                clean_view.entries
            )
            index.save_json(reverse_file, metadata={"language_code": lang})

        with open(reverse_file, encoding="utf-8") as f:
            return json.load(f).get("entries", [])

    # -- static artifacts ---------------------------------------------------

    def _serve_formats(self, parsed_path: str) -> bool:
        """Serve files under exports/<lang>/formats/. Returns True if handled.

        The route maps `/formats/<lang>/<rest>` to `exports/<lang>/formats/<rest>`.
        Two independent checks keep the served path inside the format root: the
        request must not contain a `..` segment, and the resolved target must
        still live under the resolved root (which also catches absolute paths
        and symlinks that escape the root).
        """
        parts = [p for p in parsed_path.strip("/").split("/") if p]
        if len(parts) < 3 or parts[0] != "formats":
            return False

        lang = parts[1]
        root = FORMATS_ROOTS.get(lang)
        if root is None:
            return False

        relative = Path(*parts[2:])
        if ".." in relative.parts:
            return False

        try:
            resolved_root = root.resolve()
            target = (root / relative).resolve()
            target.relative_to(resolved_root)
        except (ValueError, OSError):
            return False

        if not target.is_file():
            return False

        content_type = "application/octet-stream"
        if target.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif target.suffix == ".json":
            content_type = "application/json; charset=utf-8"
        elif target.suffix == ".pdf":
            content_type = "application/pdf"
        elif target.suffix in (".xml", ".lift"):
            content_type = "application/xml"

        blob = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(blob)
        return True

    @staticmethod
    def _pdf_page_count(pdf_path: Path) -> int:
        """Count the pages of a PDF without a third-party PDF library.

        WeasyPrint writes the page tree inside compressed object streams, so the
        `/Type /Page` markers are only visible after inflating them. `pdfinfo`
        is not assumed to exist on the server host.
        """
        try:
            data = pdf_path.read_bytes()
        except OSError:
            return 0

        chunks = [data]
        for match in re.finditer(rb"stream\r?\n", data):
            start = match.end()
            end = data.find(b"endstream", start)
            if end == -1:
                continue
            try:
                chunks.append(zlib.decompress(data[start:end]))
            except zlib.error:
                continue

        joined = b"\n".join(chunks)
        pages = re.search(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", joined, re.S)
        if pages:
            return int(pages.group(1))
        return len(re.findall(rb"/Type\s*/Page[^s]", joined))

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            has_poolside = bool(os.environ.get("POOLSIDE_API_KEY"))
            has_openai = bool(os.environ.get("OPENAI_API_KEY"))
            self._send_json(
                {
                    "providers": [
                        {
                            "id": "poolside",
                            "name": "Poolside Foundation Models",
                            "default_model": "poolside/laguna-s-2.1",
                            "available_models": ["poolside/laguna-s-2.1", "poolside/laguna-xs-2.1"],
                            "active": has_poolside,
                            "key_configured": has_poolside,
                        },
                        {
                            "id": "openai",
                            "name": "OpenAI",
                            "default_model": "gpt-4o-mini",
                            "available_models": ["gpt-4o-mini", "gpt-4o"],
                            "active": has_openai,
                            "key_configured": has_openai,
                        },
                        {
                            "id": "mock",
                            "name": "Deterministic Grounded Mock (Offline)",
                            "default_model": "mock-grounded-v1",
                            "available_models": ["mock-grounded-v1"],
                            "active": True,
                            "key_configured": True,
                        },
                    ],
                    "active_provider": "poolside" if has_poolside else "mock",
                }
            )
            return

        elif parsed.path == "/api/synthetic":
            query_params = parse_qs(parsed.query)
            status_filter = query_params.get("status", ["all"])[0].lower()

            all_phrases = []
            if SYNTHETIC_STORE.exists():
                try:
                    with open(SYNTHETIC_STORE, encoding="utf-8") as f:
                        data = json.load(f)
                        all_phrases = data.get("phrases", [])
                except Exception:
                    all_phrases = []

            # Compute quality counts
            passed_count = sum(
                1 for p in all_phrases if p.get("valid") and not p.get("quarantined")
            )
            quarantined_count = sum(1 for p in all_phrases if p.get("quarantined"))
            needs_review_count = sum(
                1
                for p in all_phrases
                if p.get("quality", {}).get("status") == QualityStatus.NEEDS_REVIEW.value
            )

            # Filter
            if status_filter == "passed":
                filtered = [p for p in all_phrases if p.get("valid") and not p.get("quarantined")]
            elif status_filter == "quarantined":
                filtered = [p for p in all_phrases if p.get("quarantined")]
            elif status_filter == "needs_review":
                filtered = [
                    p
                    for p in all_phrases
                    if p.get("quality", {}).get("status") == QualityStatus.NEEDS_REVIEW.value
                ]
            else:
                filtered = all_phrases

            self._send_json(
                {
                    "language": "mzr",
                    "total": len(all_phrases),
                    "passed_count": passed_count,
                    "quarantined_count": quarantined_count,
                    "needs_review_count": needs_review_count,
                    "active_filter": status_filter,
                    "phrases": filtered,
                }
            )
            return

        elif parsed.path == "/api/dictionary":
            query_params = parse_qs(parsed.query)
            lang = query_params.get("lang", ["mzr"])[0].lower()
            view_mode = query_params.get("view", ["clean"])[0].lower()
            search_query = query_params.get("search", [""])[0].strip().lower()

            try:
                from langpipe.lexicon.audit.view import LexiconView

                # Load counts across all views
                counts = {}
                for vm in ["clean", "names", "quarantine", "all"]:
                    v = LexiconView.load(lang_code=lang, view=vm)
                    counts[vm] = len(v.entries)

                # Load current view
                view_obj = LexiconView.load(lang_code=lang, view=view_mode)
                entries = []
                for e in view_obj.entries:
                    hw = e.get("headword", "")
                    glosses = e.get("glosses_por", []) or e.get("glosses", [])
                    pos = e.get("pos", "noun")
                    status = e.get("status", "supported")
                    prov = e.get("provenance", "")
                    audit = e.get("audit", {})

                    if search_query:
                        match = (
                            search_query in hw.lower()
                            or any(search_query in g.lower() for g in glosses)
                            or search_query in pos.lower()
                        )
                        if not match:
                            continue

                    entries.append(
                        {
                            "headword": hw,
                            "pos": pos,
                            "glosses": glosses,
                            "status": status,
                            "provenance": prov,
                            "example": e.get("example", ""),
                            "trans": e.get("trans", ""),
                            "citations": e.get("citations", []),
                            "semantics": e.get("semantics", {}),
                            "lexical_class": audit.get("lexical_class", "lemma"),
                            "proper_noun_kind": audit.get("proper_noun_kind"),
                            "audit_flags": audit.get("flags", []),
                            "use_scopes": audit.get("use_scopes", []),
                            "reasons": audit.get("reasons", []),
                        }
                    )

                self._send_json(
                    {
                        "language": lang,
                        "view": view_mode,
                        "total": len(entries),
                        "counts": counts,
                        "entries": entries,
                    }
                )
            except Exception as e:
                self._send_json(
                    {"status": "error", "message": str(e)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return

        elif parsed.path == "/api/dictionary/reverse":
            query_params = parse_qs(parsed.query)
            lang = query_params.get("lang", ["mzr"])[0].lower()
            search_query = query_params.get("search", [""])[0].strip()

            try:
                reverse_file = EXPORTS_DIR / lang / "dictionary.reverse.json"
                if not reverse_file.exists():
                    from langpipe.lexicon.audit.view import LexiconView
                    from langpipe.lexicon.reverse import ReverseLexiconIndex

                    clean_view = LexiconView.load(lang_code=lang, view="clean")
                    rev_index = ReverseLexiconIndex(contact_language="por").build_from_lexicon(
                        clean_view.entries
                    )
                    rev_index.save_json(reverse_file, metadata={"language_code": lang})

                with open(reverse_file, encoding="utf-8") as f:
                    data = json.load(f)

                entries = data.get("entries", [])
                if search_query:
                    from langpipe.lexicon.reverse import normalize_search_key

                    norm_q = normalize_search_key(search_query)
                    entries = [
                        e
                        for e in entries
                        if norm_q in e.get("normalized_key", "")
                        or norm_q in normalize_search_key(e.get("contact_headword", ""))
                        or any(
                            norm_q in normalize_search_key(s.get("target_headword", ""))
                            for s in e.get("senses", [])
                        )
                    ]

                self._send_json(
                    {
                        "language": lang,
                        "total": len(entries),
                        "metadata": data.get("metadata", {}),
                        "entries": entries,
                    }
                )
            except Exception as e:
                self._send_json(
                    {"status": "error", "message": str(e)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return

        elif parsed.path == "/api/dictionary/session":
            query_params = parse_qs(parsed.query)
            lang = query_params.get("lang", ["mzr"])[0].lower()
            view_mode = query_params.get("view", ["clean"])[0].lower()
            try:
                self._send_json(self._build_session(lang, view_mode))
            except Exception as e:
                self._send_json(
                    {"status": "error", "message": str(e)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return

        if self._serve_formats(parsed.path):
            return

        # Fallback to static file serving
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}

        if parsed.path == "/api/generate":
            lang = req_data.get("lang", "mzr")
            count = min(int(req_data.get("count", 5)), 50)
            provider_type = req_data.get("provider", "poolside")
            model = req_data.get("model")
            api_key = req_data.get("api_key")

            try:
                provider = get_provider(
                    provider_name=provider_type,
                    api_key=api_key if api_key and not api_key.startswith("••") else None,
                    model_name=model,
                )
                pipeline = SyntheticPipeline(lang_code=lang, provider=provider)
                new_phrases = pipeline.generate_phrases(count=count)
                new_dicts = [p.to_dict() for p in new_phrases]

                # Load existing and append
                existing_phrases = []
                if SYNTHETIC_STORE.exists():
                    try:
                        with open(SYNTHETIC_STORE, encoding="utf-8") as f:
                            existing_data = json.load(f)
                            existing_phrases = existing_data.get("phrases", [])
                    except Exception:
                        existing_phrases = []

                all_phrases = new_dicts + existing_phrases
                passed_count = sum(
                    1 for p in all_phrases if p.get("valid") and not p.get("quarantined")
                )
                quarantined_count = sum(1 for p in all_phrases if p.get("quarantined"))

                saved_blob = {
                    "language": lang,
                    "total": len(all_phrases),
                    "passed_count": passed_count,
                    "quarantined_count": quarantined_count,
                    "phrases": all_phrases,
                }
                with open(SYNTHETIC_STORE, "w", encoding="utf-8") as f:
                    json.dump(saved_blob, f, indent=2, ensure_ascii=False)
                with open(MZR_SYNTHETIC_STORE, "w", encoding="utf-8") as f:
                    json.dump(saved_blob, f, indent=2, ensure_ascii=False)

                self._send_json(
                    {
                        "status": "success",
                        "generated_count": len(new_dicts),
                        "valid_count": sum(1 for p in new_dicts if p["valid"]),
                        "quarantined_count": sum(1 for p in new_dicts if p.get("quarantined")),
                        "new_phrases": new_dicts,
                        "total_phrases": len(all_phrases),
                    }
                )
            except Exception as e:
                self._send_json(
                    {"status": "error", "message": str(e)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return

        elif parsed.path == "/api/judge":
            lang = req_data.get("lang", "mzr")
            judge_name = req_data.get("judge", "heuristic")

            try:
                judge = get_clef_judge(judge_name, lang_code=lang)
                validator = GroundingValidator(lang_code=lang)

                all_phrases = []
                if SYNTHETIC_STORE.exists():
                    with open(SYNTHETIC_STORE, encoding="utf-8") as f:
                        data = json.load(f)
                        all_phrases = data.get("phrases", [])

                passed_count = 0
                quarantined_count = 0

                for p in all_phrases:
                    target_text = p.get("target_phrase", "")
                    igt = p.get("igt_gloss", "")
                    pt = p.get("portuguese_translation", "")

                    grounding = validator.validate(target_text)
                    judgment = judge.judge_phrase(
                        target_phrase=target_text,
                        igt_gloss=igt,
                        portuguese_translation=pt,
                        grounding_report=grounding,
                    )
                    p["quality"] = judgment.to_dict()
                    is_quarantined = judgment.status in (
                        QualityStatus.QUARANTINED,
                        QualityStatus.REJECTED,
                    )
                    p["quarantined"] = is_quarantined
                    p["valid"] = grounding.valid and not is_quarantined

                    if is_quarantined:
                        quarantined_count += 1
                    else:
                        passed_count += 1

                saved_blob = {
                    "language": lang,
                    "total": len(all_phrases),
                    "passed_count": passed_count,
                    "quarantined_count": quarantined_count,
                    "phrases": all_phrases,
                }
                with open(SYNTHETIC_STORE, "w", encoding="utf-8") as f:
                    json.dump(saved_blob, f, indent=2, ensure_ascii=False)
                with open(MZR_SYNTHETIC_STORE, "w", encoding="utf-8") as f:
                    json.dump(saved_blob, f, indent=2, ensure_ascii=False)

                self._send_json(
                    {
                        "status": "success",
                        "total": len(all_phrases),
                        "passed_count": passed_count,
                        "quarantined_count": quarantined_count,
                        "phrases": all_phrases,
                    }
                )
            except Exception as e:
                self._send_json(
                    {"status": "error", "message": str(e)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return

        elif parsed.path == "/api/validate":
            lang = req_data.get("lang", "mzr")
            sentence = req_data.get("sentence", "")
            try:
                validator = GroundingValidator(lang_code=lang)
                judge = get_clef_judge("heuristic", lang_code=lang)
                report = validator.validate(sentence)
                judgment = judge.judge_phrase(
                    target_phrase=sentence,
                    igt_gloss="",
                    portuguese_translation="",
                    grounding_report=report,
                )
                self._send_json(
                    {
                        "grounding": report.to_dict(),
                        "quality": judgment.to_dict(),
                    }
                )
            except Exception as e:
                self._send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
            return

        elif parsed.path == "/api/synthetic/export":
            lang = req_data.get("lang", "mzr")
            try:
                from langpipe.synthesis.export_dataset import DatasetExporter

                synth_file = EXPORTS_DIR / lang / "synthetic_phrases.json"
                phrases = []
                if synth_file.exists():
                    with open(synth_file, encoding="utf-8") as f:
                        data = json.load(f)
                        phrases = data.get("phrases", [])

                exporter = DatasetExporter(lang_code=lang)
                summary = exporter.export(synthetic_phrases=phrases)
                self._send_json({"status": "success", "summary": summary.to_dict()})
            except Exception as e:
                self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        elif parsed.path == "/api/dictionary/print":
            lang = req_data.get("lang", "mzr")
            view_mode = req_data.get("view", "clean")
            try:
                from langpipe.lexicon.audit.view import LexiconView
                from langpipe.lexicon.exporters.pdf import build_print_edition

                view_obj = LexiconView.load(lang_code=lang, view=view_mode)
                raw = view_obj.raw_data or {}
                out_dir = EXPORTS_DIR / lang / "formats"
                fonts_dir = ROOT / "assets" / "fonts"

                result = build_print_edition(
                    view_obj.entries,
                    out_dir,
                    target_lang=lang,
                    target_name=raw.get("language_name", lang),
                    contact_lang=raw.get("contact_language", "por"),
                    contact_name="Português",
                    language_family=raw.get("language_family", ""),
                    glottocode=raw.get("glottocode", ""),
                    territory=raw.get("territory", ""),
                    fonts_dir=fonts_dir if fonts_dir.exists() else None,
                    session=self._build_session(lang, view_mode),
                    morphology=raw.get("morphology", []),
                    parallel_sentences=raw.get("parallel_sentences", []),
                )

                pdf_path = Path(result["pdf"])
                self._send_json(
                    {
                        "status": "success",
                        # URL paths, not filesystem paths: the browser downloads
                        # them through the /formats/<lang>/... route.
                        "pdf": f"/formats/{lang}/dictionary_{lang}_printable.pdf",
                        "html": f"/formats/{lang}/dictionary_{lang}_printable.html",
                        "entries": len(view_obj.entries),
                        "pages": self._pdf_page_count(pdf_path),
                    }
                )
            except Exception as e:
                self._send_json(
                    {"status": "error", "message": str(e)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")


def run(port: int = 8000) -> None:
    server_address = ("", port)
    httpd = HTTPServer(server_address, SyntheticLKBRequestHandler)
    print(f"Javari LKB & Synthetic Server running at http://localhost:{port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    run(port=port)
