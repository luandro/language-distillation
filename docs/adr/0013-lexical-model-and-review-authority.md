# ADR-0013: Lexical domain model, relation mapping, and review authority

**Status:** Accepted (under delegated authority, owner ratification pending)

## Context

Milestone 4 delivers lexical evidence: `Lexeme`, `Sense`, `Concept`, EvidenceItem enrichment, lexical candidate induction, CLDF import/export, and the human review queue (`docs/DEVELOPMENT.md:75`).

Several structural and governance questions require architectural decisions:
1. **Ambiguity preservation**: `docs/DOMAIN-MODEL.md:76` states "A Form may relate to zero, one or multiple Lexeme hypotheses." One orthographic Form may represent multiple homophonous or polysemous Lexemes.
2. **Concept representation**: Concepts may be language-internal semantic clusters or mapped to external standards like Concepticon.
3. **M4 vs M5 boundary**: `docs/DOMAIN-MODEL.md` links feature bundles and `Paradigm` to lexemes, but morphology induction is formally scheduled for Milestone 5.
4. **Review authority configuration**: `docs/REVIEW-WORKFLOW.md` states "Not every reviewer validates every object. Roles are configured per community/language", but leaves the configuration mechanism unspecified.
5. **Promotion semantics**: Invariant 3 dictates that machine confidence never silently promotes a hypothesis to `validated`.

## Decision

1. **Relational Entities & Multiplicity**:
   - `Lexeme`: Represents an induced or curated lexical unit, with language tag, optional lemma `Form` reference, part-of-speech tag hypothesis, lifecycle status (`candidate`, `supported`, `validated`, `rejected`, `deprecated`), register/domain tags, and run lineage.
   - `form_lexeme`: An explicit relational join table (`form_id`, `lexeme_id`, `role`, `run_id`, `created_at`) supporting an arbitrary many-to-many relationship between orthographic `Form`s and `Lexeme`s.
   - `Sense`: Attached to one `Lexeme` (`lexeme_id`), with glosses/translations (e.g. Portuguese translations treated strictly as gloss hypotheses about meaning, never target-language forms per Invariants 8 and 9), optional `concept_id`, domain/register tags, status, and run lineage.
   - `Concept`: Represents a semantic referent. Concepts are `local` by default (`concept_type="local"`, language-specific label), with an optional external mapping (e.g. `concepticon_id`, `external_urn`).

2. **Strict Scope Fence (No Morphological Paradigms in M4)**:
   - `Lexeme` in M4 MUST NOT include paradigm references, slot definitions, or inflectional feature bundles. Paradigms, morphemes, allomorphs, and feature assignments belong exclusively to Milestone 5.

3. **Evidence & Score Breakdown Enrichment**:
   - `EvidenceItem` records link to `Lexeme` or `Sense` via `target_id`.
   - Score breakdowns are versioned (`policy_version="lexical-v1"`), retaining raw component weights (e.g. alignment support, source diversity, wordlist support) and independence groups.
   - Automated scoring policies can promote from `candidate` to `supported` only. Related-language evidence alone can never promote target-language knowledge.
   - Promoting to `validated` is strictly restricted to authorized human review decisions.

4. **Review Authority Configuration (Reversible Abstraction)**:
   - Rather than creating an unvetted database-backed permissions/roles subsystem, review authority is configured via a structured language profile registry (`ReviewAuthorityRegistry`).
   - The registry maps reviewer identifier, role (e.g. `community_linguist`, `native_speaker_elder`, `editorial_steward`), and permitted language/domain scope.
   - `ReviewService` validates the acting reviewer against this registry before committing state transitions to `validated` or `rejected`.

5. **Review Queue Scoping**:
   - The queue schema supports standard task types (`ReviewTaskType`), but M4 services and CLI restrict task generation to lexical task types: `lexical_sense`, `lemma`, `register_domain`, and `governance_export`.
   - Decisions are immutable (`ReviewDecision`). Recording a decision creates a new decision entity, applies the state transition, updates the target object's score breakdown, and flags directly dependent items as stale.

6. **CLDF Interchange Layer**:
   - Uses `pycldf` for standard CLDF Wordlist/Dictionary reading and writing (ADR-0003).
   - CLDF imports must pass through the source registry and immutable raw store under ADR-0007.
   - CLDF exports filter strictly by governance and lifecycle status: by default only `validated` records are exported; an explicit `--include-supported` flag enables exporting `supported` records with a status column. `distill_only` source prose/sentences are forbidden from appearing in exports.

## Consequences

- Ambiguity is preserved relationally from day one.
- Invariants 3, 5, 7, 8, and 9 are strictly enforced in domain models and services.
- The review authority mechanism remains lightweight and easily replaced with a full community governance model when specified, without database schema rewrites.
- Milestone 4 stays cleanly decoupled from Milestone 5 morphology models.

## Alternatives Rejected

- **One-to-many Form-to-Lexeme foreign key on Form**: Prevents a Form from belonging to multiple Lexemes, destroying polysemous representation.
- **Prematurely embedding Paradigm/Features in Lexeme**: Violates milestone separation and invites heuristic morphology guessing.
- **Database RBAC roles tables**: Premature permanent schema design for review workflows before community requirements are defined.
- **Direct machine validation**: Violates Invariant 3.
