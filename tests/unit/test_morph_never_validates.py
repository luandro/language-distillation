"""AST scan and property tests verifying machine code never constructs or returns validated (WP5.8).

Invariant 3: Machine confidence NEVER promotes a hypothesis to `validated`.
Only authorized human review may create `validated` status.
"""

import ast
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from langpipe.domain.enums import LifecycleStatus
from langpipe.morphology.scoring import score_allomorph, score_analysis, score_morpheme

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "langpipe"


def test_ast_scan_no_construction_of_validated_in_morphology_and_igt() -> None:
    """AST scan: verify no expression constructs or returns LifecycleStatus.VALIDATED

    in `src/langpipe/morphology/` or `src/langpipe/igt/`.
    """
    targets = [
        _SRC_ROOT / "morphology",
        _SRC_ROOT / "igt",
    ]
    violations: list[str] = []

    for target_dir in targets:
        assert target_dir.exists(), f"Target directory {target_dir} must exist"
        for py_path in sorted(target_dir.rglob("*.py")):
            rel = py_path.relative_to(_SRC_ROOT)
            tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))

            for node in ast.walk(tree):
                # 1. Check keyword arguments: e.g. status=...VALIDATED or status="validated"
                if isinstance(node, ast.keyword) and node.arg == "status":
                    val = node.value
                    if isinstance(val, ast.Attribute) and val.attr == "VALIDATED":
                        violations.append(f"{rel}:{node.lineno} keyword arg status=...VALIDATED")
                    elif isinstance(val, ast.Constant) and val.value == "validated":
                        violations.append(f"{rel}:{node.lineno} keyword arg status='validated'")

                # 2. Check assignment to attribute or name 'status' with VALIDATED
                if isinstance(node, ast.Assign):
                    val = node.value
                    is_val_attr = isinstance(val, ast.Attribute) and val.attr == "VALIDATED"
                    is_val_const = isinstance(val, ast.Constant) and val.value == "validated"
                    if is_val_attr or is_val_const:
                        for target in node.targets:
                            if isinstance(target, ast.Name) and target.id == "status":
                                violations.append(
                                    f"{rel}:{node.lineno} assignment status = VALIDATED"
                                )
                            elif isinstance(target, ast.Attribute) and target.attr == "status":
                                violations.append(
                                    f"{rel}:{node.lineno} assignment ...status = VALIDATED"
                                )

                # 3. Check returns: returning VALIDATED directly or inside a tuple
                if isinstance(node, ast.Return) and node.value is not None:
                    ret_val = node.value
                    if isinstance(ret_val, ast.Attribute) and ret_val.attr == "VALIDATED":
                        violations.append(f"{rel}:{node.lineno} returns VALIDATED")
                    elif isinstance(ret_val, ast.Tuple):
                        for elt in ret_val.elts:
                            if isinstance(elt, ast.Attribute) and elt.attr == "VALIDATED":
                                violations.append(
                                    f"{rel}:{node.lineno} returns tuple with VALIDATED"
                                )

    assert not violations, (
        "Invariant 3 violation: machine code in morphology/ or igt/ must never construct "
        "or return LifecycleStatus.VALIDATED:\n" + "\n".join(violations)
    )


# --- Property tests: morph-v1 never returns validated under any input ---


@given(
    igt_support=st.integers(min_value=0, max_value=1000),
    igt_independence=st.integers(min_value=0, max_value=1000),
    form_diversity=st.integers(min_value=0, max_value=1000),
    projection_support=st.integers(min_value=0, max_value=1000),
    boundary_mark_support=st.integers(min_value=0, max_value=1000),
    cross_method_agreement=st.integers(min_value=0, max_value=1000),
    contradiction=st.integers(min_value=0, max_value=1000),
)
def test_property_score_morpheme_never_returns_validated(
    igt_support: int,
    igt_independence: int,
    form_diversity: int,
    projection_support: int,
    boundary_mark_support: int,
    cross_method_agreement: int,
    contradiction: int,
) -> None:
    status, breakdown = score_morpheme(
        igt_support=igt_support,
        igt_independence=igt_independence,
        form_diversity=form_diversity,
        projection_support=projection_support,
        boundary_mark_support=boundary_mark_support,
        cross_method_agreement=cross_method_agreement,
        contradiction=contradiction,
    )
    assert status != LifecycleStatus.VALIDATED
    assert status in (LifecycleStatus.CANDIDATE, LifecycleStatus.SUPPORTED)
    assert 0.0 <= breakdown.overall <= 1.0


@given(
    igt_support=st.integers(min_value=0, max_value=1000),
    igt_independence=st.integers(min_value=0, max_value=1000),
    form_diversity=st.integers(min_value=0, max_value=1000),
    projection_support=st.integers(min_value=0, max_value=1000),
    boundary_mark_support=st.integers(min_value=0, max_value=1000),
    cross_method_agreement=st.integers(min_value=0, max_value=1000),
    contradiction=st.integers(min_value=0, max_value=1000),
)
def test_property_score_allomorph_never_returns_validated(
    igt_support: int,
    igt_independence: int,
    form_diversity: int,
    projection_support: int,
    boundary_mark_support: int,
    cross_method_agreement: int,
    contradiction: int,
) -> None:
    status, breakdown = score_allomorph(
        igt_support=igt_support,
        igt_independence=igt_independence,
        form_diversity=form_diversity,
        projection_support=projection_support,
        boundary_mark_support=boundary_mark_support,
        cross_method_agreement=cross_method_agreement,
        contradiction=contradiction,
    )
    assert status != LifecycleStatus.VALIDATED
    assert status in (LifecycleStatus.CANDIDATE, LifecycleStatus.SUPPORTED)
    assert 0.0 <= breakdown.overall <= 1.0


@given(
    method=st.sampled_from(["igt_assertion", "igt_assertion@0.1.0", "unsegmented@0.1.0", "custom"]),
    morpheme_statuses=st.lists(
        st.sampled_from(
            [LifecycleStatus.CANDIDATE, LifecycleStatus.SUPPORTED, LifecycleStatus.VALIDATED]
        ),
        max_size=5,
    ),
    unknown_segment=st.integers(min_value=0, max_value=10),
    contradiction=st.integers(min_value=0, max_value=10),
    ambiguity=st.integers(min_value=0, max_value=10),
    distinct_signatures=st.integers(min_value=1, max_value=10),
)
def test_property_score_analysis_never_returns_validated(
    method: str,
    morpheme_statuses: list[LifecycleStatus],
    unknown_segment: int,
    contradiction: int,
    ambiguity: int,
    distinct_signatures: int,
) -> None:
    status, breakdown = score_analysis(
        method=method,
        linked_morpheme_statuses=morpheme_statuses,
        unknown_segment=unknown_segment,
        contradiction=contradiction,
        ambiguity=ambiguity,
        distinct_signatures_on_token=distinct_signatures,
    )
    assert status != LifecycleStatus.VALIDATED
    assert status in (LifecycleStatus.CANDIDATE, LifecycleStatus.SUPPORTED)
    assert 0.0 <= breakdown.overall <= 1.0
