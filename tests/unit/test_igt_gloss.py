"""WP5.6 unit tests: Leipzig rule 4 gloss splitting (``igt/gloss.py``).

Contracts under test (M5-PLAN §7.6):
- a gloss equal to a profile `unknown_gloss_markers` entry is UNKNOWN and splits
  nothing;
- the gloss splits on ``.`` into components;
- components matching `grammatical_label_pattern` are grammatical labels, kept
  verbatim (``3SG`` is one label, never decomposed);
- every other component is a contact-language lexical gloss;
- nothing is normalised: the source strings come back as written.
"""

import pytest
from pydantic import ValidationError

from langpipe.igt.gloss import SplitGlossResult, split_gloss
from langpipe.languages.base import MorphologyProfile


def test_unknown_gloss_markers_short_circuit() -> None:
    profile = MorphologyProfile()
    for marker in ("***", "?", "??"):
        result = split_gloss(marker, profile)
        assert result == SplitGlossResult(
            source_gloss=marker, is_unknown=True, grammatical_labels=(), lexical_glosses=()
        )
    assert split_gloss("?*", profile).is_unknown is False  # not an exact marker


def test_single_lexical_and_single_label() -> None:
    result = split_gloss("ir.PST", MorphologyProfile())
    assert result.source_gloss == "ir.PST"
    assert result.is_unknown is False
    assert result.lexical_glosses == ("ir",)
    assert result.grammatical_labels == ("PST",)


def test_fully_grammatical_gloss_has_no_lexical_gloss() -> None:
    result = split_gloss("3SG.PST", MorphologyProfile())
    assert result.grammatical_labels == ("3SG", "PST")
    assert result.lexical_glosses == ()


def test_3sg_is_one_label_not_decomposed() -> None:
    result = split_gloss("3SG", MorphologyProfile())
    assert result.grammatical_labels == ("3SG",)
    assert result.lexical_glosses == ()


def test_lowercase_and_mixed_case_components_are_lexical() -> None:
    result = split_gloss("Peg.People.ERG", MorphologyProfile())
    # "Peg"/"People" keep their casing verbatim; only the label pattern decides.
    assert result.lexical_glosses == ("Peg", "People")
    assert result.grammatical_labels == ("ERG",)


def test_gloss_without_dot_is_single_component() -> None:
    result = split_gloss("canoa-ERG", MorphologyProfile())
    assert result.lexical_glosses == ("canoa-ERG",)
    assert result.grammatical_labels == ()


def test_empty_gloss_splits_to_no_components() -> None:
    result = split_gloss("", MorphologyProfile())
    assert result.lexical_glosses == ()
    assert result.grammatical_labels == ()
    assert result.is_unknown is False


def test_trailing_leading_doubled_dots_skip_empty_components() -> None:
    profile = MorphologyProfile()
    assert split_gloss("ir.", profile).lexical_glosses == ("ir",)
    assert split_gloss("ir.", profile).grammatical_labels == ()
    assert split_gloss(".PST", profile).lexical_glosses == ()
    assert split_gloss(".PST", profile).grammatical_labels == ("PST",)
    assert split_gloss("ir..PST", profile).lexical_glosses == ("ir",)
    assert split_gloss("ir..PST", profile).grammatical_labels == ("PST",)


def test_profile_governs_pattern_and_unknown_markers() -> None:
    profile = MorphologyProfile(
        unknown_gloss_markers=("NODATA",),
        grammatical_label_pattern=r"^v[0-9]+$",
    )
    result = split_gloss("V4.v2", profile)
    # Case-sensitive by profile: "V4" is lexical, "v2" matches the pattern.
    assert result.grammatical_labels == ("v2",)
    assert result.lexical_glosses == ("V4",)
    assert split_gloss("NODATA", profile).is_unknown is True
    assert split_gloss("NODATA.item", profile).is_unknown is False  # not an exact marker


def test_profile_defaults_to_generic_when_omitted() -> None:
    # Spec contract: profile is optional; None selects the generic defaults.
    assert split_gloss("ir.PST") == split_gloss("ir.PST", None)
    assert split_gloss("ir.PST").grammatical_labels == ("PST",)
    assert split_gloss("?", profile=None).is_unknown is True


def test_result_is_frozen() -> None:
    result = split_gloss("ir.PST", MorphologyProfile())
    with pytest.raises(ValidationError):
        result.is_unknown = True  # type: ignore[misc]
