"""AST test: single governance door guard (WP5.5, ADR-0018 §6).

All policy decision paths must go through `governance.approvals.effective_policy`.
No module outside `src/langpipe/governance/` and `src/langpipe/storage/` may call `get_policy`.
"""

import ast
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "langpipe"


def test_no_get_policy_calls_outside_governance_and_storage() -> None:
    violations: list[str] = []

    for path in sorted(_SRC_ROOT.rglob("*.py")):
        rel = path.relative_to(_SRC_ROOT)
        # governance/ and storage/ are permitted to read static policies
        if rel.parts[0] in ("governance", "storage"):
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func = node.func
            called_name: str | None = None
            if isinstance(func, ast.Attribute) and func.attr == "get_policy":
                called_name = func.attr
            elif isinstance(func, ast.Name) and func.id == "get_policy":
                called_name = func.id

            if called_name is not None:
                violations.append(f"{rel}:{node.lineno} calls {called_name}()")

    assert not violations, (
        "Single door violation (ADR-0018 §6): policy decisions must go through "
        "langpipe.governance.approvals.effective_policy, not direct get_policy calls:\n"
        + "\n".join(violations)
    )
