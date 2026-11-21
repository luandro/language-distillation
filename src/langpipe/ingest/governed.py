"""Helpers shared by every governed extraction entry point (WP4.10 §2.3, ADR-0007).

The wordlist extractor (WP4.6) and the CLDF importer (WP4.10) enforce the same
governance sequence, so its steps live here once instead of being copied: the
`Operation.EXTRACT` gate, the target/contact language resolution and the verified
raw-byte read. Order is part of the contract and is owned by the callers; this module
owns none of it — each helper is a single step of that sequence.
"""

from __future__ import annotations

import logging

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AuditEventType,
    Operation,
    PolicyDecision,
    SourceStatus,
)
from langpipe.domain.errors import ObjectMissing, PolicyDenied, SchemaViolation
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.run import AuditEvent
from langpipe.domain.models.source import Source, SourceObject
from langpipe.governance import effective_policy
from langpipe.governance.policy import resolve
from langpipe.lexicon.adapters.wordlist import DEFAULT_CONTACT_LANGUAGE
from langpipe.logging import log_event

logger = logging.getLogger(__name__)


def _resolve_languages(
    source: Source, target_language: str | None, contact_language: str | None
) -> tuple[str, str]:
    """The target and contact languages of one wordlist extraction.

    The target defaults to the source's first declared language, exactly like Stage 2's
    language resolution; the contact defaults to the source's other language when it
    declares exactly two, else the generic default. An explicit target must be a language of
    the source; a contact language need not be declared by the source, because a wordlist
    may gloss in a language it does not otherwise contain. The two must differ: a
    translation language is never the target language (Invariant 9).
    """
    if target_language is None:
        target = source.languages[0]
    elif target_language not in source.languages:
        raise SchemaViolation()
    else:
        target = target_language
    if contact_language is None:
        others = [language for language in source.languages if language != target]
        contact = others[0] if len(others) == 1 else DEFAULT_CONTACT_LANGUAGE
    else:
        contact = contact_language
    if contact == target:
        raise SchemaViolation()
    return target, contact


def _require_extract_allowed(ctx: AppContext, source_id: str) -> None:
    """One audit event and `PolicyDenied` for a source that may not be extracted.

    A revoked source is denied here alongside a non-allow decision, mirroring Stage 2: a
    denial writes no run row, no artifact, no lineage edge and reads no bytes.
    """
    try:
        with ctx.repo.transaction():
            ctx.repo.lock_sources([source_id])
            source = ctx.repo.get_source(source_id)
            decision = resolve(effective_policy(ctx.repo, source), Operation.EXTRACT)
            if source.status is SourceStatus.REVOKED or decision is not PolicyDecision.ALLOW:
                raise PolicyDenied(source_id, Operation.EXTRACT, decision)
    except PolicyDenied as exc:
        _record_denial(ctx, source_id, Operation.EXTRACT, exc.decision)
        raise


def _record_denial(
    ctx: AppContext, subject_id: str, operation: Operation, decision: PolicyDecision
) -> None:
    # Mirrors the M2 denial events: identifiers and enum values only, never content.
    with ctx.repo.transaction():
        ctx.repo.add_audit_event(
            AuditEvent(
                id=ctx.new_id(IdPrefix.AUDIT),
                event_type=AuditEventType.POLICY_DENIED,
                actor=ctx.actor,
                subject_id=subject_id,
                run_id=None,
                details={"operation": operation.value, "decision": decision.value},
                occurred_at=ctx.clock(),
            )
        )
    log_event(
        logger,
        "policy.denied",
        level=logging.WARNING,
        source_id=subject_id,
        operation=operation.value,
        decision=decision.value,
    )


def _read_verified(ctx: AppContext, obj: SourceObject) -> bytes:
    """Read one object's raw bytes after its blob row and stored digest both check out.

    Two independent checks, in order: ingestion must have produced a blob row for the
    registered digest, and the stored object must still hash to that digest. Only then are
    the bytes read, so a mismatched rewrite of the immutable store fails closed with the
    typed integrity error and never yields content to decode.
    """
    if ctx.repo.get_raw_blob(obj.sha256) is None:
        raise ObjectMissing(obj.sha256)
    ctx.raw_store.verify(obj.sha256)
    return ctx.raw_store.read_bytes(obj.sha256)
