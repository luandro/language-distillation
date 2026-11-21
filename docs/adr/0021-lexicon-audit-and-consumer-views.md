# ADR-0021: Lexicon audit, lexical class taxonomy, and consumer-scoped views

**Status:** Accepted

## Context

When extracting lexical entries from bilingual texts (such as biblical translations, ethnographic field notes, and bilingual glossaries), the raw extraction inevitably ingests non-lemma material into the lexical registry. For Marúbo (`mzr`), lexical extraction from eBible texts yielded 1,099 entries, of which over 140 were proper names (e.g., *Judas*, *Noemi*, *Elimeleque*, *Simão*, *Pedro*, *Nilo*, *Israel*), more than 60 were inflected wordforms with clitics (e.g., *davipa*, *jesusvere*, *israelrasĩní*), and several were transcription artifacts (e.g., *3tíi*, *10tíi*).

Treating proper names and inflected forms as bare lemmas creates critical downstream failure modes:
1. **Synthetic Generation Pollution:** The synthetic prompt generator selects biblical proper nouns or inflected words as verbal/nominal stems, producing nonsensical or ungrammatical phrases.
2. **Grounding Weakness (Invariant 9):** If inflected forms (e.g. *davipa*) are in the lemma lexicon, the grounding validator accepts them as bare roots, masking compound morphological errors and violating target-language morphology rules.
3. **Lexicographical Inaccuracy:** A published or exported dictionary cannot present proper names or inflected surface forms as canonical dictionary headwords.

However, non-negotiable architectural invariants constrain how this must be resolved:
- **Invariant 1 & 2 (Raw Immutability & Observation vs. Inference):** Raw textual occurrences and extracted observation records must never be deleted or mutated.
- **Invariant 4 (Lineage):** Every classification decision must retain full audit lineage.
- **Invariant 10 (Egress Governance):** Model-assisted audit must not leak restricted target-language surface text to uncalibrated third-party APIs.
- **Generic Code Separation:** Language-specific phonotactics and orthographic conventions must be isolated behind language profiles (`docs/languages/<iso>.md`), not hardcoded in generic pipeline modules.

## Decision

1. **Explicit Lexical Class Taxonomy:**
   We define a formal classification schema (`LexicalClass`):
   - `LEMMA`: Canonical dictionary headword / native lexical stem.
   - `PROPER_NOUN`: Anthroponym, toponym, ethnonym, or proper name (Onomasticon).
   - `INFLECTED_FORM`: Surface wordform with bound affixes or clitics.
   - `MULTIWORD`: Multi-token phrase or expression.
   - `ARTIFACT`: OCR artifact, stray punctuation, or number prefix.
   - `UNKNOWN`: Unresolved lexical status.

2. **Fine-Grained Use Scopes (`UseScope`):**
   Rather than binary deletion, each entry is assigned explicit operational scopes:
   - `GROUNDING`: Permitted as a root/stem in token-level grounding validation.
   - `SYNTHESIS_PROMPT`: Permitted as vocabulary for synthetic prompt generation.
   - `DICTIONARY_EXPORT`: Eligible for canonical lemma dictionary exports.
   - `ONOMASTICON`: Eligible for proper name registers and named-entity gazetteers.

3. **Three-Layer Audit Subsystem:**
   - **Layer 1: Deterministic Rules:** Inspects surface orthography, regex patterns (digits, multiwords), language-profile foreign phonotactics (e.g. non-native letters `b, d, f, g, j, l, q, z`), known conventional names, and known name+clitic combinations.
   - **Layer 2: Pivot-Side Clef Gloss Evaluator:** Inspects Portuguese glosses exclusively (zero target-language egress under Invariant 10). Flags proper noun semantics (names, titles, places) and grammatical definitions.
   - **Layer 3: Deterministic Decision Table:** Combines signals from Layers 1 & 2 to determine `LexicalClass`, assign structured `AuditFlag`s, and compute `use_scopes`. Machine classification excludes or scopes entries, but human-validated entries are never overridden.

4. **Language Profile Isolation:**
   All language-specific rules, phonotactic exclusions, conventional names, and affix inventories are placed in `src/langpipe/languages/<iso>/lexicon_profile.py`. Generic pipeline modules (`src/langpipe/lexicon/audit/`) consume the abstract `LexiconProfile` protocol.

5. **Consumer-Scoped Views (`LexiconView`):**
   Subsystems access the lexicon via scoped views:
   - `clean`: Only genuine lemmas (`use_scopes` containing `GROUNDING` and `SYNTHESIS_PROMPT`).
   - `names`: Proper nouns and onomasticon entries.
   - `quarantine`: Quarantined entries (artifacts, foreign names, clitic forms excluded from active lemma synthesis).
   - `all`: The complete audited inventory.

   `GroundingValidator` and `SyntheticPipeline` are updated to consume `LexiconView.load(view="clean")` by default, guaranteeing Invariant 9 compliance without altering raw observations.

## Consequences

- The active Marúbo lexicon is cleanly separated: 892 genuine lemmas, 142 proper names, 63 inflected forms, and 2 artifacts.
- Synthetic generation and grounding are strictly protected from proper-name or inflected-root hallucinations.
- Raw sources and extraction records remain immutable and intact with full lineage.
- Downstream UI and API endpoints expose dedicated views (`clean`, `names`, `quarantine`, `all`) with interactive audit metrics.

## Alternatives Rejected

- **Hard-deleting proper nouns from the database:** Direct violation of Invariant 1 (Raw sources are immutable) and Invariant 2 (Observation and inference are different entities).
- **Evaluating target-language words directly with external LLMs:** Violation of Invariant 10 (Source governance / restricted egress) and ADR-0006 (Decision models restricted from uncalibrated target-language authority).
- **Hardcoding Marúbo phonotactics in generic audit code:** Violation of language-profile isolation rules (`AGENTS.md`).
