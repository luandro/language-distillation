# CLAUDE.md

## Authority and Purpose

This repository implements an **evidence-first language resource distillation pipeline** for extremely low-resource languages, yielding a versioned, auditable **Language Knowledge Base (LKB)**.

**All agent operations MUST strictly adhere to [AGENTS.md](AGENTS.md).** `AGENTS.md` is the canonical constitution and system specification for this repository.

## Non-Negotiable Core Invariants

1. **Raw sources are immutable** (`var/external/` and `var/raw/`).
2. **Observation and inference are distinct entities.** Never overwrite observed facts with interpretations.
3. **Hypotheses are not facts.** Machine confidence never silently promotes an object to `validated`.
4. **Lineage is preserved for every derived object** to its evidence and processing run.
5. **Source governance is enforced in code.**
6. **A source present in the repository is authorized for processing and training.** Licenses, ownership, and register labels are recorded metadata, never gates (ADR-0025). Only an explicit `exclude` blocks a source entirely.
7. **Unknown or ambiguous linguistic analyses MUST remain representable.**
8. **Related-language evidence creates hypotheses, NEVER target-language truth.**
9. **Zero LLM hallucinations:** Do NOT use an LLM to invent target-language morphology or lexical forms.
10. **Data privacy & egress:** No third-party API receives restricted material unless source policy explicitly permits it.
11. **Persisted format changes require migration, tests, and documentation.**
12. **Architectural decisions are recorded as ADRs.**

## Mandatory Verification & Search Tooling

- **XERJ is Mandatory for Code Search:**
  Always use `xerj def "<symbol>"` for definition lookup and `xerj search "<plain words>"` for ranked passages. Cite `file:line` for any code or contract relied upon. Never guess or hallucinate code paths.
- **Clef is Mandatory for Linguistic & Synthetic Data Quality:**
  Any synthetic parallel data or lexical induction MUST be validated through Clef (L0 lexical grounding guard, L1 structural/TAM check, L2 pivot-side semantic plausibility judge per ADR-0020 and ADR-0021). Target-language forms must never be sent to uncalibrated third-party APIs.

## Tooling Baseline & Environment

- **Python:** 3.12+ managed via `uv`
- **Core CLI:** `uv run langpipe <command>`
- **Database:** PostgreSQL 16+ (SQLAlchemy 2 + Alembic)
- **Code Quality:** `uv run ruff check .` and `uv run mypy src/`
- **Test Suite:** `uv run pytest` (unit, integration, golden fixture tests)

## Skills

Skill definitions for specific subsystems live in `.skills/` (and `.claude/skills/`):
- `xerj`: Definition-first code search over local repository indices
- `clef`: Semantic plausibility judge, structural checker, and lexicon audit
- `harvest`: Universal indigenous resource harvesting and academic spidering
- `language-distillation`: End-to-end LKB pipeline architecture and invariants
- `nmt-finetuning`: NLLB-200 600M LoRA bidirectional fine-tuning and evaluation
- `hallmark`: Anti-AI-slop design and UI architecture
- `impeccable`: Design and engineering quality guardrails
