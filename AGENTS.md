# AGENTS.md

## Purpose

This repository implements an **evidence-first language resource distillation pipeline** for extremely low-resource languages.

The canonical product is a versioned, auditable **Language Knowledge Base (LKB)**. A trained language model is a downstream consumer and is never the source of linguistic truth.

## Non-negotiable invariants

1. **Raw sources are immutable.**
2. **Observation and inference are different entities.** Never overwrite an observed fact with a linguistic interpretation.
3. **Hypotheses are not facts.** Machine confidence never silently promotes a hypothesis to `validated`.
4. **Every derived object must retain lineage to its evidence and processing run.**
5. **Source governance is enforced in code, not only documented.**
6. **A source present in the repository is authorized for processing and training.** Licenses, ownership, rights holders, and register labels are recorded metadata, never gates (ADR-0025). Only an explicit `exclude` policy blocks a source entirely.
7. **Unknown or ambiguous linguistic analyses must remain representable.**
8. **Related-language evidence may create hypotheses, never target-language truth.**
9. **Do not use an LLM to invent target-language morphology or lexical forms.**
10. **No third-party API receives restricted material unless source policy explicitly permits it.**
11. **Every persisted format change requires migration, tests, and documentation.**
12. **Architectural decisions are not made silently.** Record significant reversals or additions as ADRs.

## Documentation routing

Read only the documents relevant to the task.

| If you are changing… | Read first |
|---|---|
| product scope / user-facing goal | `docs/PRODUCT.md` |
| subsystem boundaries / storage / module layout | `docs/ARCHITECTURE.md` |
| entities, relations, IDs, statuses, lineage | `docs/DOMAIN-MODEL.md` |
| evidence scoring / promotion semantics | `docs/EVIDENCE-AND-CONFIDENCE.md` |
| pipeline inputs/outputs/stage behavior | `docs/PIPELINE-CONTRACTS.md` |
| morphology, morphemes, paradigms, clitics | `docs/MORPHOLOGY.md` |
| source rights, access, revocation, exports | `docs/GOVERNANCE.md` |
| human review queues or decisions | `docs/REVIEW-WORKFLOW.md` |
| metrics, benchmarks, promotion gates | `docs/EVALUATION.md` |
| development environment / testing / milestones | `docs/DEVELOPMENT.md` |
| schema implementation | `docs/SCHEMAS.md` |
| golden test fixture | `docs/GOLDEN-FIXTURE.md` |
| language-specific behavior | `docs/languages/<iso>.md` |
| universal resource harvesting / web spidering | `docs/research/universal_sources_registry.json`, `src/langpipe/harvest/` |
| synthetic parallel data generation & Clef judge | `docs/adr/0020-clef-pivot-quality-judge.md`, `src/langpipe/synthesis/` |
| lexicon audit, gloss classification, reverse index | `docs/adr/0021-lexicon-audit-and-consumer-views.md`, `src/langpipe/lexicon/` |
| NMT / LoRA fine-tuning & evaluation | `notebooks/Marubo_NLLB_600M_Finetune.ipynb`, `src/langpipe/cli/synth.py` |
| CLDF interchange & export formats | `docs/adr/0003-cldf-interchange.md`, `docs/implementation/WP4.10-CLDF-SPEC.md` |
| available skill guidelines | `.skills/` |
| previous architectural decision | `docs/adr/` |
| implementing a milestone work package | `docs/implementation/` (e.g. `docs/implementation/M1-PLAN.md`) |

Do **not** read every document for every task.

## Normative language

The words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are normative.

Working assumptions in language profiles are not universal architecture rules.

## Architecture rules

- PostgreSQL is the canonical persistence baseline. See ADR-0002.
- The logical language/morphology graph is projected from explicit relational entities and edges. Do not introduce a graph database without an ADR.
- CLDF, Xigt, LIFT, CoNLL-U, EAF, and TextGrid are interchange formats, not the canonical source of internal state.
- All processing stages produce explicit versioned artifacts or rows; stages must not write through multiple semantic layers at once.
- An aligner produces **alignment evidence**, not dictionary truth.
- A morphology inducer produces **MorphAnalysis candidates**, not validated morphemes.
- A generator consumes only eligible knowledge; it must not read quarantined raw sources.

## State rules

Inference-bearing entities use the lifecycle defined in `docs/DOMAIN-MODEL.md`:

`candidate → supported → validated` or `rejected`; `deprecated` is terminal for superseded objects.

Only permitted validation authorities may create `validated` status.

## Development discipline

Agents MUST use **XERJ** as the primary exploration and verification mechanism before editing unfamiliar code, and MUST invoke **Clef** validation protocols whenever dealing with synthetic parallel data, dictionary lemmas, or lexical audits. Citing `file:line` from XERJ is mandatory.

Before coding:

1. inspect existing code and tests using `xerj def` and `xerj search`;
2. identify the exact contract being implemented;
3. check relevant ADRs;
4. write/update tests first for behavior changes;
5. do not expand scope without recording it.

Before declaring work complete:

- run unit tests relevant to the change;
- run schema/serialization tests if persisted entities changed;
- run golden fixture tests if pipeline semantics changed;
- run governance tests if eligibility/access/lineage changed;
- run migrations forward and backward when migrations changed;
- update affected docs/ADR;
- state any remaining uncertainty.

## Expected tooling baseline

Unless the existing repository already establishes an alternative:

- Python 3.12+
- `uv`
- Pydantic v2
- SQLAlchemy 2 + Alembic
- PostgreSQL 16+
- Typer
- pytest + Hypothesis where useful
- Ruff
- mypy or pyright

Do not switch foundational tools casually; use an ADR.

## Testing priorities

Highest-risk behavior deserves tests first:

1. raw source immutability;
2. policy enforcement;
3. lineage propagation;
4. trace-id presence on training rows, and `exclude` blocking a source;
5. ambiguity preservation;
6. deterministic IDs / idempotent reruns;
7. exact graph semantics;
8. revocation impact analysis.

## Language-specific code

Language-specific behavior MUST be isolated behind a language profile/adapter. Generic pipeline code MUST NOT contain Marúbo-specific rules.

The initial Marúbo profile is documented at `docs/languages/mzr.md`.

## Unresolved behavior

If a required behavior is marked **OPEN** in the docs:

- do not invent a permanent architecture;
- implement the smallest reversible abstraction needed;
- add a focused TODO linked to the relevant document;
- if the decision affects interfaces or stored data, create an ADR proposal.

## Scope for the first implementation

Prioritize the evidence substrate before linguistic automation:

1. source registry and governance;
2. immutable raw ingestion;
3. extraction/normalization records;
4. segments and token occurrences;
5. runs/artifacts/lineage;
6. parallel segment representation;
7. alignment evidence;
8. CLDF import/export scaffolding;
9. golden fixture.

Do not rush into synthetic generation or model training before the evidence graph is stable.

## XERJ and Clef (Core Tooling Mandate)

This project mandates **XERJ** and **Clef** for all tasks:

1. **XERJ (Code and Concept Search):**
   - Before writing code that touches unfamiliar territory: `xerj def "<symbol>"` for go-to-definition, or `xerj search "<plain words>"` for ranked, definition-first passages.
   - Index the repo with `xerj autoindex <folder>`.
   - **Always cite `file:line`** for any code, model, or contract you rely on.

2. **Clef (Linguistic Quality, Semantic Plausibility, and Lexicon Audit):**
   - Clef enforces the 3-layer quality filter (ADR-0020 & ADR-0021): L0 Grounding Guard, L1 Structural & TAM Alignment, and L2 Pivot-Side Semantic Plausibility.
   - Any synthetic parallel generation MUST pass through Clef batch sampling: `uv run langpipe synth batch`.
   - Any lexicon cleanup or dictionary export MUST pass through Clef gloss classification: `src/langpipe/lexicon/audit/clef_gloss.py`.
   - Target-language surface forms must NEVER be leaked to uncalibrated external APIs.

### Row checking and adjudication

Verifying candidate rows or citation conflicts against the printed page follows `.skills/row-adjudication/SKILL.md`. Rules:

1. **XERJ gives context, never a vote.** Use it (or the in-script index in `scripts/recover_chant_orthography.py`) to show where else a refrain is printed. Majority vote across sources or readers never resolves a conflict.
2. **Clef only where invariant 10 allows.** Local L0/L1 may see Marúbo forms; L2 and any network Clef see Portuguese only. Clef cannot read pixels.
3. **Pixels are read by two independent free or cheap readers** (benchmarked; see `reader_benchmark.md` in the skill), never bulk by Claude or Codex: two different readers, or one reader at two zoom levels plus a deterministic OCR check. Claude is allowed only for a calibration audit of at most 20 rows or the final disputed residue. Disputed and low-confidence rows get a 400 dpi zoom round. Judge the print only, no phonology.
4. **Machine reads are evidence, not promotion.** Record reader and crop provenance; never rewrite `src`; evidence-only is the default (filling `clean_src` is an owner choice); promotion goes through `langpipe review decide`. A row whose print matches no candidate is stored as an observation of the printed form, `clean_src` null, listed for review.
5. **Pre-flight the source policy.** Send crops to a third-party vision model only when `var/external/<src>/policy.yaml` says `access_class: public`; otherwise stop and ask.
6. **"None of the candidates" is a valid outcome.** Keep the row an unresolved conflict and store the printed form as an observation (reader, crop path), `clean_src` null, listed for the owner.
7. **List owner decisions explicitly** (agreed picks, remaining disagreements, none-of-the-candidates rows) instead of applying them.
