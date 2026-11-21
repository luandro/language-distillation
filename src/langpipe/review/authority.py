"""Review authority registry (M4-PLAN §6 WP4.8, ADR-0013 §4).

The lightweight, reversible stand-in for community governance configuration: who may
review, in which role, over which languages and (optionally) domains. Deliberately not
database RBAC (ADR-0013 §4, rejected alternative): the registry is an in-memory,
process-local configuration object built from structured language profile data
(`ReviewAuthorityGrant`), which a fuller community governance model can replace
without schema changes.

Authority is configuration, never fixture data: a registry built from profiles that
configure no grants denies everything. Matching semantics:

* a reviewer may hold several authorizations (one per `register` call); a request is
  authorized when any one authorization matches role, language and domain;
* `domains=None` means the authorization is not domain-scoped and matches any domain;
* a domain-scoped authorization says nothing about an untagged object and fails closed.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from langpipe.languages import base as languages_base
from langpipe.languages.base import LanguageProfile

# ADR-0018 §4: the only role that may record a source-use approval. Identity stays an
# unauthenticated, asserted string checked against this same process-local registry
# (C-4 backlog); `record_approval` (governance.approvals) gates on this exact role.
ROLE_GOVERNANCE_STEWARD = "governance_steward"


@dataclass(frozen=True)
class ReviewerAuthorization:
    """One reviewer's permitted role and language/domain scope."""

    reviewer_id: str
    role: str
    languages: set[str] = field(default_factory=set)
    domains: set[str] | None = None  # None = all domains


class ReviewAuthorityRegistry:
    """Maps reviewer ids to their authorized role/language/domain combinations."""

    def __init__(self) -> None:
        self._authorizations: dict[str, list[ReviewerAuthorization]] = {}

    def register(
        self,
        reviewer_id: str,
        role: str,
        languages: Sequence[str],
        domains: Sequence[str] | None = None,
    ) -> None:
        """Add one authorization. Re-registering a role replaces that authorization."""
        if not reviewer_id.strip():
            raise ValueError("reviewer_id must be nonempty")
        if not role.strip():
            raise ValueError("role must be nonempty")
        scope = set(languages)
        domain_scope = None if domains is None else set(domains)
        authorizations = self._authorizations.setdefault(reviewer_id, [])
        replacement = ReviewerAuthorization(
            reviewer_id=reviewer_id, role=role, languages=scope, domains=domain_scope
        )
        authorizations[:] = [existing for existing in authorizations if existing.role != role] + [
            replacement
        ]

    def is_authorized(
        self, reviewer_id: str, role: str, language: str, domain: str | None = None
    ) -> bool:
        """True when some authorization of the reviewer covers role, language and domain."""
        for authorization in self._authorizations.get(reviewer_id, ()):
            if authorization.role != role:
                continue
            if language not in authorization.languages:
                continue
            if authorization.domains is not None and (
                domain is None or domain not in authorization.domains
            ):
                continue
            return True
        return False

    def holds_role(self, reviewer_id: str, role: str) -> bool:
        """True when the reviewer holds `role` in any language scope.

        For targets no registry scope can name — language-less objects such as
        concepts — authority reduces to the required role plus a real authorization
        somewhere, instead of an always-false language match.
        """
        return any(
            authorization.role == role
            for authorization in self._authorizations.get(reviewer_id, ())
        )


def registry_from_profiles(
    profiles: Mapping[str, LanguageProfile] | None = None,
) -> ReviewAuthorityRegistry:
    """Build the registry from structured language profile configuration (ADR-0013 §4).

    The default reads the registered profiles at call time, so a process that loads
    profile configuration is honored on the next command. Profiles without grants
    contribute nothing: an unconfigured deployment denies every reviewer (M4-PLAN C3).
    """
    if profiles is None:
        profiles = languages_base.LANGUAGE_PROFILES
    registry = ReviewAuthorityRegistry()
    for profile in profiles.values():
        for grant in profile.review_authority:
            registry.register(
                grant.reviewer_id,
                grant.role,
                grant.languages,
                None if grant.domains is None else list(grant.domains),
            )
    return registry


__all__ = [
    "ROLE_GOVERNANCE_STEWARD",
    "ReviewAuthorityRegistry",
    "ReviewerAuthorization",
    "registry_from_profiles",
]
