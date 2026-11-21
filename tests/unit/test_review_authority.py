"""Review authority registry contracts (WP4.8, ADR-0013 §4).

The registry is the lightweight, reversible stand-in for community governance
configuration: reviewer id, role, language scope, optional domain scope. Tests pin
the matching semantics, including the fail-closed domain behavior, and the
profile-driven construction that replaces built-in fixture reviewers: no identity
holds authority unless a language profile configuration grants it.
"""

import pytest

from langpipe.languages import base as languages_base
from langpipe.languages.base import LanguageProfile, ReviewAuthorityGrant
from langpipe.review.authority import ReviewAuthorityRegistry, registry_from_profiles


def _registry_with_domain_scoped_elder() -> ReviewAuthorityRegistry:
    registry = ReviewAuthorityRegistry()
    registry.register("elder_1", "native_speaker_elder", ["mzr"], domains=["ritual"])
    return registry


def test_matching_role_language_and_open_domain_authorizes() -> None:
    registry = ReviewAuthorityRegistry()
    registry.register("linguist_1", "community_linguist", ["mzr", "qaa"])
    assert registry.is_authorized("linguist_1", "community_linguist", "mzr")
    assert registry.is_authorized("linguist_1", "community_linguist", "qaa", domain="household")


def test_unknown_reviewer_is_rejected() -> None:
    registry = ReviewAuthorityRegistry()
    assert not registry.is_authorized("stranger", "community_linguist", "mzr")


def test_wrong_role_is_rejected() -> None:
    registry = ReviewAuthorityRegistry()
    registry.register("linguist_1", "community_linguist", ["mzr"])
    assert not registry.is_authorized("linguist_1", "native_speaker_elder", "mzr")


def test_language_outside_scope_is_rejected() -> None:
    registry = ReviewAuthorityRegistry()
    registry.register("linguist_1", "community_linguist", ["mzr"])
    assert not registry.is_authorized("linguist_1", "community_linguist", "por")


def test_unrestricted_domains_accept_any_concrete_domain() -> None:
    unrestricted = ReviewAuthorityRegistry()
    unrestricted.register("linguist_1", "community_linguist", ["mzr"])
    assert unrestricted.is_authorized("linguist_1", "community_linguist", "mzr", domain="ritual")


def test_domain_scoped_authorization_accepts_only_listed_domain() -> None:
    registry = _registry_with_domain_scoped_elder()
    assert registry.is_authorized("elder_1", "native_speaker_elder", "mzr", domain="ritual")
    assert not registry.is_authorized("elder_1", "native_speaker_elder", "mzr", domain="household")


def test_domain_scoped_authorization_rejects_untagged_object() -> None:
    # Fail closed: a reviewer scoped to named domains says nothing about an untagged object.
    registry = _registry_with_domain_scoped_elder()
    assert not registry.is_authorized("elder_1", "native_speaker_elder", "mzr", domain=None)


def test_second_registration_extends_a_reviewer() -> None:
    registry = ReviewAuthorityRegistry()
    registry.register("linguist_1", "community_linguist", ["mzr"])
    registry.register("linguist_1", "editorial_steward", ["qaa"])
    assert registry.is_authorized("linguist_1", "community_linguist", "mzr")
    assert registry.is_authorized("linguist_1", "editorial_steward", "qaa")
    # The first authorization does not leak into the second role or language.
    assert not registry.is_authorized("linguist_1", "editorial_steward", "mzr")


def test_register_copies_the_given_sequences() -> None:
    registry = ReviewAuthorityRegistry()
    languages = ["mzr"]
    domains = ["ritual"]
    registry.register("linguist_1", "community_linguist", languages, domains)
    languages.append("por")
    domains.append("household")
    assert registry.is_authorized("linguist_1", "community_linguist", "mzr", domain="ritual")
    assert not registry.is_authorized("linguist_1", "community_linguist", "por")
    assert not registry.is_authorized("linguist_1", "community_linguist", "mzr", domain="household")


def test_holds_role_matches_any_language_scope() -> None:
    # Language-less targets (concepts) cannot be scoped by language; a reviewer counts
    # for them only when some authorization carries the role at all.
    registry = ReviewAuthorityRegistry()
    registry.register("elder_1", "native_speaker_elder", ["mzr"])
    assert registry.holds_role("elder_1", "native_speaker_elder")
    assert not registry.holds_role("elder_1", "community_linguist")
    assert not registry.holds_role("stranger", "native_speaker_elder")


@pytest.mark.parametrize("reviewer_id", ["", "  "])
def test_blank_reviewer_id_is_rejected(reviewer_id: str) -> None:
    registry = ReviewAuthorityRegistry()
    with pytest.raises(ValueError):
        registry.register(reviewer_id, "community_linguist", ["mzr"])


@pytest.mark.parametrize("role", ["", "  "])
def test_blank_role_is_rejected(role: str) -> None:
    registry = ReviewAuthorityRegistry()
    with pytest.raises(ValueError):
        registry.register("linguist_1", role, ["mzr"])


def test_empty_registry_rejects_everything() -> None:
    registry = ReviewAuthorityRegistry()
    assert not registry.is_authorized("linguist_1", "community_linguist", "mzr")


# --- profile-driven construction (ADR-0013 §4, no built-in fixture authority) ------------


def _profile_with(*grants: ReviewAuthorityGrant, language: str = "mzr") -> LanguageProfile:
    return LanguageProfile(
        language,
        "test_profile",
        "0.1.0",
        "default_text@0.1.0",
        "whitespace_punct@0.1.0",
        review_authority=grants,
    )


def test_registry_from_profiles_registers_configured_grants() -> None:
    profiles = {
        "mzr": _profile_with(
            ReviewAuthorityGrant(
                reviewer_id="linguist_1",
                role="community_linguist",
                languages=("mzr",),
            ),
            ReviewAuthorityGrant(
                reviewer_id="elder_1",
                role="native_speaker_elder",
                languages=("mzr",),
                domains=("ritual",),
            ),
        ),
    }
    registry = registry_from_profiles(profiles)
    assert registry.is_authorized("linguist_1", "community_linguist", "mzr", domain="ritual")
    assert registry.is_authorized("elder_1", "native_speaker_elder", "mzr", domain="ritual")
    # The domain-scoped grant stays inside its configured boundaries.
    assert not registry.is_authorized("elder_1", "native_speaker_elder", "mzr", domain="household")
    assert not registry.is_authorized("elder_1", "native_speaker_elder", "mzr", domain=None)
    assert not registry.is_authorized("linguist_1", "community_linguist", "por")


def test_registry_from_profiles_default_deny_when_unconfigured() -> None:
    # No grants configured anywhere: every combination is denied. No built-in fixture
    # identity confers operational authority.
    profiles = {"mzr": _profile_with()}
    registry = registry_from_profiles(profiles)
    assert not registry.is_authorized("test_reviewer", "community_linguist", "mzr")
    assert not registry.is_authorized("linguist_1", "community_linguist", "mzr")
    assert not registry.is_authorized("steward_1", "editorial_steward", "mzr")


def test_registry_from_profiles_of_empty_mapping_denies_everything() -> None:
    registry = registry_from_profiles({})
    assert not registry.is_authorized("anyone", "community_linguist", "mzr")


def test_registry_from_profiles_reads_registered_profiles_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Late binding: the default is resolved at call time, so a process that (re)loads
    # language profile configuration is honored on the next command, not only at import.
    profiles = {
        "mzr": _profile_with(
            ReviewAuthorityGrant(
                reviewer_id="linguist_1", role="community_linguist", languages=("mzr",)
            )
        )
    }
    monkeypatch.setattr(languages_base, "LANGUAGE_PROFILES", profiles)
    registry = registry_from_profiles()
    assert registry.is_authorized("linguist_1", "community_linguist", "mzr")
    assert not registry.is_authorized("stranger", "community_linguist", "mzr")
