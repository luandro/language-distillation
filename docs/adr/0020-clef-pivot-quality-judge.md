# ADR-0020: Clef as a pivot-side quality and plausibility judge for synthetic data

**Status:** Accepted

## Context

When generating synthetic parallel data for extremely low-resource languages (e.g. Marúbo `mzr`), token-level grounding against the Language Knowledge Base (LKB) enforces Invariant 9 (zero invented stems or affixes). However, lexical grounding alone does not guarantee semantic plausibility or natural world-knowledge coherence. For instance, combinations of attested stems such as `yapa-n vaki yamama-katsai` ("peixe-ERG criança matar-FUT" -> "O peixe matará o menino") violate predicate-argument selectional restrictions and world knowledge, resulting in nonsensical output.

Furthermore, ADR-0006 restricts decision models from acting as final uncalibrated authorities on unseen target-language text, and Invariant 10 strictly governs third-party data egress.

## Decision

1. **Three-layer Evaluation Hierarchy:**
   - **L0: Grounding Guard (Mandatory Hard Gate):** Every token must decompose into attested LKB stems and affixes. Lexical hallucinations trigger immediate `rejected` status.
   - **L1: Deterministic Structural Checks:** Token alignment between target phrase and Leipzig IGT, case marking consistency (ERG vs ABS), and TAM suffix vs Portuguese translation alignment (e.g. negation `-ma` requiring Portuguese negation, future `-katsai` requiring future inflection).
   - **L2: Clef Pivot-Side Plausibility Judge:** Evaluates the semantic frame in the pivot language (Portuguese). Checks agent animacy, patient compatibility, predicate selectional restrictions, and world-knowledge plausibility.

2. **Pivot-Only Egress and Governance (ADR-0006 & Invariant 10):**
   - The Clef decision model operates strictly on pivot-language frames (`agente`, `paciente`, `verbo`, `traducao`, `glosa`), avoiding transmission of restricted target-language surface forms to external uncalibrated APIs.
   - Offline `HeuristicClefJudge` is the default local baseline, enabling zero-network CI and isolated execution.

3. **Explicit Quarantining Semantics ("Put Aside"):**
   - Candidate synthetic phrases that fail selectional restrictions or semantic plausibility are assigned `QualityStatus.QUARANTINED` with structured `FailureReason` codes (`selectional_violation`, `semantic_implausibility`, `tam_mismatch`, `gloss_mismatch`).
   - Quarantined phrases are segregated from trainable datasets (`synthetic_trainable.json`) and isolated in dedicated inspection views in the web interface.

4. **Lifecycle and Authority Invariants (Invariants 2, 3, 4):**
   - Machine confidence never promotes synthetic phrases to `validated`.
   - Automated evaluation yields only `passed_automated`, `needs_review`, `quarantined`, or `rejected`.
   - Promotion to `validated` is strictly reserved for authorized human reviewers per `docs/REVIEW-WORKFLOW.md`.

## Consequences

- Nonsensical or semantically inverted synthetic phrases are immediately detected and set aside.
- Downstream training exports receive only semantically plausible, structurally aligned, and lexically grounded phrases.
- Full provenance and audit trail: each judgment record carries deterministic judgment IDs, checks, raw probabilities/critiques, and failure reasons.
- The web interface exposes quality breakdown tabs (Passed, Quarantined, All) with reason chips and interactive audit capabilities.

## Alternatives Rejected

- **Relying solely on lexical grounding (L0):** Permitted semantically absurd sentences ("peixe mata menino", "carne come criança") that degrade model quality.
- **Using an uncalibrated target-language neural judge:** Directly violated ADR-0006 by assuming calibration on unseen target-language grammar.
- **Silently dropping failed phrases:** Violated Invariant 4 (lineage and auditability); rejected phrases must be explicitly quarantined and preserved for review.
