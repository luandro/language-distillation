# Human Review Workflow

## Goal

Use human time where it changes the language resource most.

## ReviewTask

Minimum fields:
- ID;
- type;
- target object/version;
- evidence bundle;
- required authority/role;
- priority;
- reason;
- creator;
- status.

Task types include lexical sense, lemma, morphology segmentation, morpheme function, grammar construction, register/domain, alignment spot-check, governance/export and pronunciation.

## ReviewDecision

Allowed decisions:

```text
accept
reject
modify
uncertain
defer
```

Required metadata: reviewer ID/role, authority scope, timestamp, target version, decision, optional notes and replacement/superseding object if modified.

## Immutability

Review decisions are immutable. A changed opinion creates a new decision/superseding action.

## Authority

Not every reviewer validates every object. Roles are configured per community/language.

## Priority

Suggested operational priority:

```text
frequency × uncertainty × downstream impact × evidence conflict × sensitivity
```

High-priority examples include a common form with competing senses, a suffix used by thousands of analyses, a disputed case marker, a suspected restricted term, or a grammar rule used by generation.

## Presentation

Show only the context needed to decide. Morphology review should show segmentation spans and competing analyses.

## Reviewer fatigue

Batch related tasks, allow `cannot judge`, avoid low-value duplicates, and track disagreement rather than forcing consensus.

## Disagreement

Multiple valid analyses/registers may coexist. Do not resolve disagreement automatically by majority vote.

## State transition

A decision may validate/reject an object, create a corrected superseding object, add EvidenceItems and trigger dependent recalculation.

A decision writes the target status change, recomputes the target's score breakdown from current evidence, and writes `stale_dependent` lineage edges flagging the decided object's direct dependents ([ADR-0014](adr/0014-review-staleness-and-authority-config.md)). Bounded direct-dependent recalculation is implemented by `RecalcService` (WP5.14, Gate 43): recomputes each stale dependent's score breakdown under its own policy (`lexical-v1` or `morph-v1`, with status unchanged — recalculation never promotes past `supported`, and never demotes a `validated` object) and writes a `recalculated` lineage edge from the dependent to the decided object under a `HUMAN_REVIEW`-stage maintenance run. Stale rows with unresolved flags are strictly omitted from CLDF exports and counted under `omitted.stale_dependent` (`cldf-export-report` v2). Cascading recalculation beyond direct dependents remains **OPEN**.

Transition logic belongs in a domain service, not UI code.

## Implementation (M4/M5)

Scope: review over `Lexeme`, `Sense`, `Morpheme`, and `MorphAnalysis` targets (`Concept` targets are queue-only — `uncertain`/`defer` resolve the entry, lifecycle decisions are refused before any write). `create_task` accepts lexical task types (`lexical_sense`, `lemma`, `register_domain`, `governance_export`) and morphology task types (`morphology_segmentation`, `morpheme_function`).

CLI ([ADR-0013](adr/0013-lexical-model-and-review-authority.md), WP5.14):

```sh
uv run langpipe review list [--type TASK_TYPE] [--role ROLE] [--status STATUS] \
    [--min-priority FLOAT] [--language ISO] [--limit N]
uv run langpipe review decide --task-id TASK_ID --decision accept|reject|modify|uncertain|defer \
    --reviewer ID --role ROLE [--notes TEXT] [--superseding OBJECT_ID]
uv run langpipe review recalc [--object ID]... | --all-stale
```

Output is IDs, enum values and counts only — a queue listing or decision result never echoes source content.

## Authority registry

`ReviewAuthorityRegistry` (`src/langpipe/review/authority.py`) is built by `registry_from_profiles()` from `LanguageProfile.review_authority` grants (`ReviewAuthorityGrant`). Matching semantics:

- a reviewer may hold several authorizations (one per `register` call); a request is authorized when any one authorization matches role + language (+ domain);
- `domains=None` means the authorization is not domain-scoped and matches any domain;
- a domain-scoped authorization says nothing about an untagged object and fails closed;
- language-less targets (concepts) reduce authority to `holds_role` — the required role plus a real authorization somewhere;
- a registry built from profiles that configure no grants denies every reviewer.

The registry is process-local configuration, not database RBAC ([ADR-0013](adr/0013-lexical-model-and-review-authority.md) §4). The reviewer ID is an asserted `--reviewer` string checked against that configuration — there is no authentication in M4 (single-operator assumption; carry-over C-4).

## Decision effects (M4)

Exact behavior lives in `src/langpipe/review/service.py`; if the code differs from this table, the code wins. `deprecated` is terminal: no decision revives it.

| Decision | Target status effect | Task status |
|---|---|---|
| `accept` | `candidate`/`supported` → `validated` (the only path to `validated`; a `rejected` target is never revived) | `resolved` |
| `reject` | `candidate`/`supported`/`validated` → `rejected` | `resolved` |
| `modify` | requires `--superseding`: original target → `deprecated` (kept, never deleted); successor (`candidate`/`supported`, same language, same lexeme for senses) → `validated` | `resolved` |
| `uncertain` | unchanged | `resolved` |
| `defer` | unchanged | `open` |

A supplied `target_version` pins the status-of-record the reviewer saw; a task about a moved object is refused instead of decided under a stale version. Every lifecycle write recomputes the target's `lexical-v1` breakdown from current evidence, so the audit breakdown is updated, never erased.
