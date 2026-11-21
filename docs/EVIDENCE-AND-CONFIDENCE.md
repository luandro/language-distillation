# Evidence, Confidence, and Promotion

This document is normative.

## Principle

Confidence is a property of an **inference under a policy**, not proof of truth.

Preserve evidence components instead of storing only one opaque score.

## Evidence independence

Repeated observations from one formulaic source are not equivalent to independent corroboration.

Every EvidenceItem SHOULD carry an `independence_group`.

Promotion policies SHOULD reward independent evidence.

## Score breakdown

Example:

```yaml
score:
  policy_version: lexical-v1
  overall: 0.82
  components:
    alignment_support: 0.88
    source_diversity: 0.70
    dictionary_support: 1.00
    igt_support: 0.50
    monolingual_support: 0.75
    domain_stability: 0.80
  penalties:
    formulaic_source: 0.08
    single_register_concentration: 0.05
```

Aggregation is versioned; raw components are retained.

## Promotion

### candidate → supported
May be automatic if a versioned evidence policy passes.

### supported → validated
Requires an allowed validation basis such as:
- authorized speaker/editor;
- authoritative imported IGT/dictionary assertion when governance permits;
- approved linguistic editorial decision.

Model confidence alone MUST NOT validate.

## Contradiction

Contradictory evidence is preserved. Do not average contradiction away.

Strong support + strong contradiction should usually increase review priority.

## Related languages

Related-language evidence may suggest segmentation/features and prioritize review, but MUST NOT alone promote target-language knowledge to supported/validated.

## Domain/register

Confidence may be context-conditioned rather than one global score.

## Calibration

Any model probability treated as confidence must have a local calibration benchmark. Store model/version, benchmark, calibration method and metrics.

## Abstention

Automated components SHOULD support:

```text
insufficient_evidence
conflicting_evidence
unsupported_language_or_domain
human_review
```

## Review priority

Operational priority MAY combine:

```text
frequency × uncertainty × downstream impact × cultural sensitivity × evidence conflict
```

This is not a linguistic truth score.
