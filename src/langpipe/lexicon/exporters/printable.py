"""Print-ready dictionary book template (HTML + CSS) for physical publication.

Renders a scholarly two-column dictionary edition with running guide words,
small-caps part-of-speech labels, a numbered bibliography, and front/back
matter. The output is designed for WeasyPrint (see `langpipe.lexicon.exporters.pdf`)
but is also openable directly in a browser.

The template contains no entry semantics of its own: every field is read from
the session entries produced by `langpipe.lexicon.dictionary.session`.
"""

from __future__ import annotations

import html
import shutil
from pathlib import Path
from typing import Any

from langpipe.lexicon.dictionary.session import (
    BASIS_CORPUS_ONLY,
    BASIS_SOURCE_AND_CORPUS,
    BASIS_SOURCE_ASSERTION,
    DictionarySessionBuilder,
)

# The provenance parser is private to the session module, but the print edition
# must resolve the SAME works as the session's bibliography or the in-entry
# markers would point at the wrong rows. Re-implementing the parser here would
# create a second source of truth that can drift, so the session's own parser
# is imported and aliased.
from langpipe.lexicon.dictionary.session import _split_works as _session_works

FONT_FILES = {
    "400": "Charis-Regular.woff2",
    "700": "Charis-Bold.woff2",
    "italic 400": "Charis-Italic.woff2",
}

POS_LABELS = {
    "noun": "subst.",
    "verb": "verbo",
    "verb_intransitive": "verbo (intr.)",
    "verb_transitive": "verbo (trans.)",
    "adj": "adj.",
    "adjective": "adj.",
    "adv": "adv.",
    "adverb": "adv.",
    "pron": "pron.",
    "pronoun": "pron.",
    "num": "num.",
    "numeral": "num.",
    "part": "part.",
    "postp": "posp.",
    "interj": "interj.",
    "affix": "afixo",
    "clitic": "clítico",
    "root": "raiz",
    "prop": "n. próp.",
    "proper_noun": "n. próp.",
    "conj": "conj.",
    "dem": "dem.",
    "interrog": "interrog.",
    "ideo": "ideof.",
}

# Evidence markers. Every glyph here must exist in Charis SIL 7.000, or WeasyPrint
# silently falls back to DejaVu Serif and the book stops being single-typeface.
# U+25B3 WHITE UP-POINTING TRIANGLE is NOT in Charis (it has no triangle at all);
# U+25CA LOZENGE is the hollow shape that is, and reads clearly at 8.5pt.
# Verified by rendering the PDF and listing the embedded fonts with `pdffonts`.
STATUS_MARKS = {
    "validated": "✓",
    "supported": "○",
    "candidate": "◊",
}

# Which recorded basis a validated entry can rest on. The legend is generated
# from the session's own `validation_basis`, so the book cannot claim a kind of
# support the artifact does not record (ADR-0027 D10).
_SOURCE_BASIS = {BASIS_SOURCE_ASSERTION, BASIS_SOURCE_AND_CORPUS}
_CORPUS_BASIS = {BASIS_CORPUS_ONLY, BASIS_SOURCE_AND_CORPUS}

# Legacy citation aliases still present in older exports. The session builder
# reads only the canonical names, so the aliases are mapped before the session
# is built. The LIFT and CLDF exporters accept the same aliases.
LEGACY_CITATION_KEYS = {
    "source_text": "target_text",
    "trans": "reference_text",
}


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _with_canonical_citations(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return copies of `entries` whose citations use the canonical key names.

    The caller's entries are never mutated: only the copies are rewritten.
    """
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        citations = entry.get("citations") or []
        if not any(any(legacy in c for legacy in LEGACY_CITATION_KEYS) for c in citations):
            normalized.append(entry)
            continue
        copied = dict(entry)
        copied_citations: list[dict[str, Any]] = []
        for citation in citations:
            new_citation = dict(citation)
            for legacy, canonical in LEGACY_CITATION_KEYS.items():
                if not new_citation.get(canonical) and new_citation.get(legacy):
                    new_citation[canonical] = new_citation[legacy]
            copied_citations.append(new_citation)
        copied["citations"] = copied_citations
        normalized.append(copied)
    return normalized


class PrintableDictionaryExporter:
    """Generates print-ready HTML/CSS for a physical dictionary book."""

    def __init__(
        self,
        target_lang: str = "und",
        target_name: str = "Language",
        contact_lang: str = "por",
        contact_name: str = "Português",
        *,
        language_family: str = "",
        glottocode: str = "",
        territory: str = "",
        fonts_dir: Path | str | None = None,
        edition_date: str = "",
    ) -> None:
        self.target_lang = target_lang
        self.target_name = target_name
        self.contact_lang = contact_lang
        self.contact_name = contact_name
        self.language_family = language_family
        self.glottocode = glottocode
        self.territory = territory
        self.fonts_dir = Path(fonts_dir) if fonts_dir else None
        self.edition_date = edition_date

    # -- fonts --------------------------------------------------------------

    def _stage_fonts(self, out_dir: Path) -> list[str]:
        """Copy the Charis faces next to the HTML; return @font-face CSS lines."""
        if self.fonts_dir is None or not self.fonts_dir.exists():
            return []
        font_dir = out_dir / "fonts"
        font_dir.mkdir(parents=True, exist_ok=True)
        lines = []
        for descriptor, filename in FONT_FILES.items():
            source = self.fonts_dir / filename
            if not source.exists():
                continue
            shutil.copy2(source, font_dir / filename)
            weight = "700" if "700" in descriptor else "400"
            style = "italic" if descriptor.startswith("italic") else "normal"
            lines.append(
                f"@font-face {{ font-family: 'Charis'; src: url('fonts/{filename}'); "
                f"font-weight: {weight}; font-style: {style}; }}"
            )
        return lines

    # -- entry rendering ----------------------------------------------------

    def _render_example(self, example: dict[str, Any], index: int) -> str:
        target = example.get("target_text") or ""
        reference = example.get("reference_text") or ""
        ref = example.get("source_ref") or ""
        if not target and not reference:
            return ""
        parts = ['<div class="example">']
        if target:
            parts.append(f'<div class="ex-target">{_esc(target)}</div>')
        if reference:
            parts.append(f'<div class="ex-ref">{_esc(reference)}</div>')
        if ref:
            parts.append(f'<div class="ex-src">({_esc(ref)})</div>')
        parts.append("</div>")
        return "".join(parts)

    def _render_source_markers(
        self,
        entry: dict[str, Any],
        bib_index: dict[tuple[str, str], int],
        bib_labels: dict[tuple[str, str], str],
        spelled_out: set[tuple[str, str]],
    ) -> str:
        """Superscript markers pointing at the numbered bibliography.

        The first entry that cites a work spells that work out; every later
        citation of the same work carries only its bibliography number. The
        bibliography therefore keeps one de-duplicated row per work while each
        entry still points at it.
        """
        markers = []
        for key in _session_works(entry.get("provenance", "")):
            index = bib_index.get(key)
            if index is None:
                continue
            if key in spelled_out:
                text = str(index)
            else:
                spelled_out.add(key)
                text = bib_labels.get(key, key[0])
            markers.append(f'<sup class="src-ref"><a href="#bib-{index}">{_esc(text)}</a></sup>')
        if not markers:
            return ""
        return f'<div class="src-refs">{"".join(markers)}</div>'

    def _form_meta(self, form: dict[str, Any]) -> str:
        """`n. próp. · -nẽ`: the POS label plus the clitic the audit recorded."""
        tags = []
        pos = (form.get("pos") or "").lower()
        if pos:
            tags.append(POS_LABELS.get(pos, pos))
        clitic = (form.get("clitic") or "").strip()
        if clitic:
            tags.append(f"-{clitic}")
        return " · ".join(tags)

    def _render_entry(
        self,
        entry: dict[str, Any],
        bib_index: dict[tuple[str, str], int],
        bib_labels: dict[tuple[str, str], str],
        spelled_out: set[tuple[str, str]],
    ) -> str:
        glosses = entry.get("glosses") or []
        gloss_html = "; ".join(_esc(g) for g in glosses)
        pos_label = POS_LABELS.get((entry.get("pos") or "").lower(), entry.get("pos") or "")
        domain = entry.get("domain") or "general"
        domain_tag = ""
        if domain and domain != "general":
            domain_tag = (
                f'<span class="domain" data-domain="{_esc(domain)}">'
                f"{_esc(domain.replace('_', ' '))}</span>"
            )

        status = entry.get("status") or ""
        mark = STATUS_MARKS.get(status, "")
        status_html = f'<span class="status" title="{_esc(status)}">{mark}</span>' if mark else ""

        examples = [
            self._render_example(ex, i) for i, ex in enumerate((entry.get("examples") or [])[:1])
        ]
        examples_html = "".join(e for e in examples if e)

        sources_html = self._render_source_markers(entry, bib_index, bib_labels, spelled_out)

        related = entry.get("related_entry")
        related_html = ""
        if related:
            related_html = (
                f'<div class="see-also">ver <a href="#e-{_esc(related).lower()}">'
                f"{_esc(related)}</a></div>"
            )

        # Inflected surfaces hang under their base entry: they are never their
        # own headword, so the alphabetical body keeps one row per lemma.
        forms = entry.get("forms") or []
        forms_html = ""
        if forms:
            items = "".join(
                '<span class="form-item">'
                f'<span class="form-surface">{_esc(f.get("surface"))}</span>'
                f'<span class="form-meta">{_esc(self._form_meta(f))}</span>'
                "</span>"
                for f in forms
            )
            forms_html = f'<div class="forms"><span class="forms-label">Formas</span>{items}</div>'

        anchor = f"e-{entry.get('headword', '').lower()}"
        return (
            f'<div class="entry" id="{_esc(anchor)}">'
            f'<div class="entry-head">'
            f'<span class="headword">{_esc(entry.get("headword"))}</span>'
            f'<span class="pos">{_esc(pos_label)}</span>'
            f"{status_html}{domain_tag}"
            f"</div>"
            f'<div class="gloss">{gloss_html}</div>'
            f"{forms_html}{examples_html}{sources_html}{related_html}"
            f"</div>"
        )

    # -- front / back matter ------------------------------------------------

    def _render_title_page(self, title: str, session: dict[str, Any]) -> str:
        meta = session.get("meta", {})
        rows = [
            ("Língua", meta.get("target_name", "")),
            ("Código", meta.get("target_lang", "")),
            ("Glottocódigo", meta.get("glottocode", "")),
            ("Família", meta.get("language_family", "")),
            ("Território", meta.get("territory", "")),
            ("Língua de contato", meta.get("contact_name", "")),
            ("Verbetes", str(meta.get("total_entries", 0))),
        ]
        if self.edition_date:
            rows.append(("Edição", self.edition_date))
        rows_html = "".join(
            f'<div class="meta-row"><span class="meta-key">{_esc(k)}</span>'
            f'<span class="meta-val">{_esc(v)}</span></div>'
            for k, v in rows
            if v
        )
        return (
            '<div class="title-page">'
            f"<h1>{_esc(title)}</h1>"
            f'<div class="subtitle">Léxico atestado e base de conhecimento linguístico</div>'
            f'<div class="meta-table">{rows_html}</div>'
            "</div>"
        )

    def _render_status_legend(self, entries: list[dict[str, Any]]) -> str:
        """Explain the status marks, including what ✓ does *not* claim.

        The marks live in `STATUS_MARKS`; the wording is generated from the same
        list so a new mark cannot render without a definition. The basis sentence
        is generated from each entry's `validation_basis`, so the book cannot
        claim a kind of support (a named work, corpus attestation) that the
        artifact does not record, and the aggregate sentence is computed from the
        session rather than hard-coded.
        """
        terms = {
            "validated": "validado",
            "supported": "sustentado por evidência",
            "candidate": "hipótese (candidato)",
        }
        validated = [e for e in entries if (e.get("status") or "") == "validated"]
        kinds = {(e.get("validation_basis") or {}).get("kind") for e in validated}
        claims = []
        if kinds & _SOURCE_BASIS:
            claims.append("uma obra publicada nomeada na bibliografia")
        if kinds & _CORPUS_BASIS:
            claims.append("atestação do corpus")
        if claims:
            # "e em" only when there are two claims; one claim reads as prose.
            joined = " e em ".join(claims)
            basis_sentence = f"a decisão registrada apoia-se em {joined}. "
        else:
            basis_sentence = "o artefato não registra a base desta validação. "

        definitions = {
            "validated": (
                basis_sentence + "Não significa revisão humana nem consenso de especialistas, "
                "e não significa, por si, que o verbete tenha exemplo atestado."
            ),
            "supported": (
                "há evidência reunida no corpus, mas nenhuma decisão de validação registrada."
            ),
            "candidate": (
                "hipótese de trabalho. Nenhuma hipótese é promovida a fato sem decisão de "
                "revisão registrada."
            ),
        }

        rows = []
        for status, mark in STATUS_MARKS.items():
            if status not in definitions:
                continue
            rows.append(
                '<div class="legend-row">'
                f'<span class="legend-mark status">{_esc(mark)}</span>'
                f'<span class="legend-term">{_esc(terms[status])}</span>'
                f'<span class="legend-def">{_esc(definitions[status])}</span>'
                "</div>"
            )

        validated = [e for e in entries if (e.get("status") or "") == "validated"]
        attested = sum(
            1 for e in validated if (e.get("validation_basis") or {}).get("corpus_attestations")
        )
        note = ""
        if validated:
            without = len(validated) - attested
            note = (
                '<p class="legend-note">'
                f"Dos {len(validated)} verbetes com ✓, {attested} trazem exemplo atestado "
                f"no corpus e {without} registram apenas a obra de origem; onde não há "
                "exemplo impresso, não há atestação no corpus."
                "</p>"
            )

        return f'<div class="legend"><h3>Marcadores de evidência</h3>{"".join(rows)}{note}</div>'

    def _render_preface(self, session: dict[str, Any]) -> str:
        meta = session.get("meta", {})
        legend = self._render_status_legend(session.get("entries") or [])
        return (
            '<div class="preface">'
            "<h2>Prefácio</h2>"
            "<p>Este dicionário reúne os verbetes atestados na Base de Conhecimento "
            "Linguístico do Vale do Javari. Ele é uma <em>edição de evidências</em>: "
            "cada verbete registra o que foi observado na fonte e onde foi observado, "
            "sem nunca apresentar uma hipótese como fato consumado.</p>"
            f"{legend}"
            "<p>Os exemplos são citações atestadas. Onde a fonte é um texto paralelo, "
            "a referência indica o versículo. Cada verbete remete às obras de onde foi "
            "extraído: a primeira citação de uma obra traz o nome por extenso e as "
            "seguintes apenas o número correspondente na bibliografia.</p>"
            f"<p class='preface-meta'>Língua: {meta.get('target_name', '')} · "
            f"Glottocódigo: {meta.get('glottocode', '')} · "
            f"Verbetes: {meta.get('total_entries', 0)}</p>"
            "</div>"
        )

    def _render_morphology(self, session: dict[str, Any]) -> str:
        morph = session.get("morphology") or []
        if not morph:
            return ""
        rows = "".join(
            "<tr>"
            f"<td class='morpheme'>{_esc(m.get('morpheme', ''))}</td>"
            f"<td class='gloss-leipzig'>{_esc(m.get('gloss', ''))}</td>"
            f"<td class='function'>{_esc(m.get('function', ''))}</td>"
            "</tr>"
            for m in morph
        )
        return (
            '<div class="morphology">'
            "<h2>Morfemas e clíticos</h2>"
            "<table><thead><tr><th>Morfema</th><th>Glosa</th><th>Função</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            "</div>"
        )

    def _render_bibliography(self, session: dict[str, Any]) -> str:
        bibliography = session.get("bibliography") or []
        if not bibliography:
            return ""
        rows = "".join(
            f'<li id="bib-{b["index"]}"><span class="bib-label">{_esc(b["label"])}</span>'
            f'<span class="bib-count">({b["count"]} verbetes)</span></li>'
            for b in bibliography
        )
        return f'<div class="bibliography"><h2>Bibliografia</h2><ol>{rows}</ol></div>'

    def _render_domain_index(self, session: dict[str, Any]) -> str:
        domain_facet = (session.get("facets") or {}).get("domain") or []
        domain_facet = [f for f in domain_facet if f["value"] != "general"]
        if not domain_facet:
            return ""
        rows = "".join(
            f'<li><span class="dom-name">{_esc(f["value"].replace("_", " "))}</span>'
            f'<span class="dom-count">{f["count"]}</span></li>'
            for f in domain_facet
        )
        return (
            f'<div class="domain-index"><h2>Índice por domínio semântico</h2><ul>{rows}</ul></div>'
        )

    def _render_body(self, session: dict[str, Any]) -> str:
        entries = session.get("entries") or []
        letters = session.get("letters") or []
        bibliography = session.get("bibliography") or []
        bib_index = {(b["author"], b["years"]): b["index"] for b in bibliography}
        bib_labels = {(b["author"], b["years"]): b["label"] for b in bibliography}
        spelled_out: set[tuple[str, str]] = set()

        by_letter: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            by_letter.setdefault(entry["letter"], []).append(entry)

        sections = []
        for letter_info in letters:
            letter = letter_info["letter"]
            blocks = "".join(
                self._render_entry(e, bib_index, bib_labels, spelled_out)
                for e in by_letter.get(letter, [])
            )
            sections.append(
                f'<div class="letter-section" id="letter-{_esc(letter)}">'
                f'<div class="letter-heading">{_esc(letter)}</div>'
                f'<div class="entries-columns">{blocks}</div>'
                "</div>"
            )
        return "".join(sections)

    # -- public API ---------------------------------------------------------

    def export(
        self,
        lexicon_entries: list[dict[str, Any]],
        output_path: Path | str,
        title: str | None = None,
        *,
        session: dict[str, Any] | None = None,
        morphology: list[dict[str, Any]] | None = None,
        parallel_sentences: list[dict[str, Any]] | None = None,
    ) -> Path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        doc_title = title or f"Dicionário {self.target_name} – {self.contact_name}"

        if session is None:
            builder = DictionarySessionBuilder(
                target_lang=self.target_lang,
                target_name=self.target_name,
                contact_lang=self.contact_lang,
                contact_name=self.contact_name,
                language_family=self.language_family,
                glottocode=self.glottocode,
                territory=self.territory,
            )
            session = builder.build(
                _with_canonical_citations(lexicon_entries),
                morphology=morphology,
                parallel_sentences=parallel_sentences,
            )

        font_css = self._stage_fonts(out.parent)

        html_content = self._render_document(doc_title, session, font_css)
        out.write_text(html_content, encoding="utf-8")
        return out

    def _render_document(self, doc_title: str, session: dict[str, Any], font_css: list[str]) -> str:
        font_block = "\n    ".join(font_css) if font_css else ""
        font_stack = "'Charis', 'Charis SIL', 'Noto Serif', serif"
        if not font_css:
            font_stack = "'Noto Serif', serif"

        return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <title>{_esc(doc_title)}</title>
  <style>
    {font_block}

    @page {{
      size: A4 portrait;
      margin: 20mm 15mm 18mm 15mm;
      @top-left {{
        content: string(gw, first);
        font-family: {font_stack};
        font-style: italic;
        font-size: 8pt;
        color: #64748B;
      }}
      @top-right {{
        content: string(gw, last);
        font-family: {font_stack};
        font-style: italic;
        font-size: 8pt;
        color: #64748B;
      }}
      @bottom-center {{
        content: counter(page);
        font-family: {font_stack};
        font-size: 9pt;
        color: #334155;
      }}
    }}

    html {{
      font-family: {font_stack};
      font-size: 9.5pt;
      line-height: 1.32;
      color: #111827;
      background: #FFFFFF;
    }}
    body {{ margin: 0; padding: 0; }}

    /* ---- front matter ---- */
    .title-page {{
      page-break-after: always;
      text-align: center;
      padding-top: 70mm;
    }}
    .title-page h1 {{
      font-size: 25pt;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      margin: 0 0 5mm 0;
      color: #0F172A;
      font-weight: 700;
    }}
    .title-page .subtitle {{
      font-size: 12.5pt;
      font-style: italic;
      color: #475569;
    }}
    .meta-table {{
      margin: 22mm auto 0 auto;
      width: 70%;
      text-align: left;
      font-size: 9pt;
    }}
    .meta-row {{
      display: flex;
      justify-content: space-between;
      border-bottom: 0.4pt solid #E2E8F0;
      padding: 1.4mm 0;
    }}
    .meta-key {{
      color: #64748B;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 7.5pt;
      padding-top: 0.6mm;
    }}
    .meta-val {{ color: #0F172A; }}

    .preface, .morphology, .bibliography, .domain-index {{
      page-break-after: always;
    }}
    h2 {{
      font-size: 13pt;
      color: #0F172A;
      border-bottom: 1pt solid #0F172A;
      padding-bottom: 1.5mm;
      margin: 0 0 4mm 0;
      break-after: avoid;
      /* PDF outline (bookmarks) per section. Verified: WeasyPrint collects
         these into /Outlines with /Title entries. */
      bookmark-level: 1;
      bookmark-label: content(text);
    }}
    .preface p {{ text-align: justify; margin-bottom: 2.5mm; }}
    .preface-meta {{ color: #64748B; font-size: 8.5pt; }}

    /* Status legend. The marks are the same glyphs printed by every entry, so
       the reader can decode a mark without leaving the page. */
    .legend {{
      margin: 5mm 0 6mm 0;
      padding: 0 0 0 3mm;
      border-left: 1.2pt solid #CBD5E1;
      break-inside: avoid;
    }}
    .legend h3 {{
      font-size: 9pt;
      font-variant: small-caps;
      letter-spacing: 0.08em;
      color: #475569;
      margin: 0 0 2mm 0;
      font-weight: 700;
    }}
    .legend-row {{
      display: flex;
      align-items: baseline;
      margin-bottom: 1.6mm;
      font-size: 8.6pt;
      line-height: 1.3;
    }}
    .legend-mark {{
      flex: 0 0 7mm;
      color: #94A3B8;
      font-size: 9.5pt;
    }}
    .legend-term {{
      flex: 0 0 42mm;
      font-variant: small-caps;
      letter-spacing: 0.04em;
      color: #0F172A;
    }}
    .legend-def {{ color: #334155; text-align: justify; }}
    .legend-note {{
      margin-top: 2mm;
      font-size: 8pt;
      color: #475569;
      font-style: italic;
      text-align: justify;
    }}

    table {{ width: 100%; border-collapse: collapse; font-size: 8.5pt; }}
    th {{
      text-align: left;
      font-variant: small-caps;
      letter-spacing: 0.05em;
      color: #475569;
      border-bottom: 0.6pt solid #CBD5E1;
      padding: 1.2mm 2mm 1.2mm 0;
    }}
    td {{ padding: 1.2mm 2mm 1.2mm 0; border-bottom: 0.3pt solid #F1F5F9; }}
    td.morpheme {{ font-weight: 700; }}
    td.gloss-leipzig {{ font-variant: small-caps; }}

    /* ---- dictionary body ---- */
    .letter-section {{ margin-bottom: 6mm; }}
    .letter-heading {{
      font-size: 17pt;
      font-weight: 700;
      color: #0F172A;
      border-bottom: 1.5pt solid #0F172A;
      padding-bottom: 1mm;
      margin-bottom: 3mm;
      break-after: avoid;
      /* One PDF bookmark per letter, nested under the front matter. */
      bookmark-level: 2;
      bookmark-label: content(text);
    }}
    .entries-columns {{
      column-count: 2;
      column-gap: 7mm;
      column-rule: 0.4pt solid #E2E8F0;
    }}
    .entry {{
      break-inside: avoid;
      margin-bottom: 2.4mm;
    }}
    /* Guide words: string-set must sit on the headword span itself, and that
       span must NOT be a flex/grid item -- WeasyPrint 70 silently drops
       string-set for flex items. Use inline flow with margin spacing. */
    .headword {{
      string-set: gw content(text);
      font-weight: 700;
      color: #0F172A;
      font-size: 10.5pt;
    }}
    .entry-head {{ white-space: nowrap; }}
    .pos {{
      font-variant: small-caps;
      letter-spacing: 0.05em;
      color: #64748B;
      font-size: 8.5pt;
      margin-left: 1.2mm;
    }}
    .status {{ color: #94A3B8; font-size: 8.5pt; margin-left: 1mm; }}
    .domain {{
      font-variant: small-caps;
      letter-spacing: 0.05em;
      font-size: 7.5pt;
      color: #7C3AED;
      margin-left: 1mm;
    }}
    .gloss {{
      hyphens: auto;
      padding-left: 4mm;
      text-indent: -4mm;
      margin-top: 0.4mm;
    }}
    /* Inflected surfaces of the headword. They are listed here, never as their
       own headword row, so the A-Z body keeps one row per lemma. */
    .forms {{
      padding-left: 2mm;
      margin-top: 0.6mm;
      font-size: 8pt;
      color: #334155;
      hyphens: auto;
    }}
    .forms-label {{
      font-variant: small-caps;
      letter-spacing: 0.06em;
      color: #94A3B8;
      margin-right: 1.4mm;
    }}
    .form-item {{ margin-right: 2.2mm; white-space: nowrap; }}
    .form-surface {{ color: #1E293B; }}
    .form-meta {{ color: #94A3B8; font-size: 7.4pt; margin-left: 0.6mm; }}
    .example {{
      margin-top: 1mm;
      padding-left: 2mm;
      font-size: 8pt;
      line-height: 1.24;
      color: #334155;
      hyphens: auto;
    }}
    .ex-target {{ font-style: italic; color: #1E293B; }}
    .ex-ref {{ color: #475569; }}
    .ex-src {{ color: #B91C1C; font-size: 7pt; }}
    /* Source marker: the numbered bibliography reference of the entry. */
    .src-refs {{
      margin-top: 0.6mm;
      padding-left: 2mm;
      font-size: 7.5pt;
      color: #94A3B8;
    }}
    .src-ref {{ font-size: 6.8pt; line-height: 1; }}
    .src-ref a {{ color: #64748B; text-decoration: none; }}
    .see-also {{
      margin-top: 0.8mm;
      padding-left: 2mm;
      font-size: 8pt;
      font-variant: small-caps;
      letter-spacing: 0.04em;
      color: #64748B;
    }}
    .see-also a {{ color: #0F172A; text-decoration: none; }}
    .see-also a::after {{
      content: " (p. " target-counter(attr(href url), page) ")";
      color: #94A3B8;
      font-variant: normal;
    }}

    .bibliography ol {{ list-style: none; padding: 0; margin: 0; }}
    .bibliography li {{
      padding: 1.2mm 0;
      border-bottom: 0.3pt solid #F1F5F9;
      break-inside: avoid;
    }}
    .bib-label {{ font-weight: 600; color: #0F172A; }}
    .bib-count {{ color: #94A3B8; font-size: 8pt; margin-left: 2mm; }}

    .domain-index ul {{ list-style: none; padding: 0; margin: 0; }}
    .domain-index li {{
      display: flex;
      justify-content: space-between;
      padding: 1.2mm 0;
      border-bottom: 0.3pt solid #F1F5F9;
    }}
    .dom-name {{ font-variant: small-caps; letter-spacing: 0.04em; color: #0F172A; }}
    .dom-count {{ color: #94A3B8; font-size: 8.5pt; }}
  </style>
</head>
<body>
  {self._render_title_page(doc_title, session)}
  {self._render_preface(session)}
  {self._render_morphology(session)}
  {self._render_bibliography(session)}
  {self._render_body(session)}
  {self._render_domain_index(session)}
</body>
</html>
"""
