# ADR-0004: Eflomal as cold-start token alignment baseline

**Status:** Accepted as baseline, not permanent winner

## Context
The pilot language may be poorly represented in pretrained multilingual encoders. A statistical baseline can be measured locally.

## Decision
Implement token alignment behind an adapter and use eflomal first. Neural aligners remain experimental until they beat the baseline on target-language gold data without critical regressions.

## Consequences
Architecture stays tool-neutral and historical alignment runs coexist. Exact comparative performance claims remain locally testable hypotheses.
