"""WP5.0 (C-3) tests: the pydantic `register` shadow warning is filtered, and only that one.

Field `register` on `Lexeme`, `Sense` and `EvidenceItem` is a persisted contract
(database column, JSON key, golden snapshots); it stays, and pydantic's shadowing report
for exactly those models is ignored in `domain/models/base.py`. These tests prove the
domain model import is warning-free and that the filter does not swallow anything else.
"""

import subprocess
import sys


def test_importing_lexical_and_evidence_models_raises_no_warnings() -> None:
    # A subprocess, because the models are normally imported during test collection and a
    # cached re-import would not re-run class creation. `-W error::UserWarning` is the same
    # escalation the WP5.0 acceptance pytest call uses.
    result = subprocess.run(
        [
            sys.executable,
            "-W",
            "error::UserWarning",
            "-c",
            "import langpipe.domain.models.lexical, langpipe.domain.models.evidence",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_filter_is_narrow_to_the_named_models() -> None:
    # Same shadowed attribute, different model name: the warning must escalate to an error
    # under -W error::UserWarning because base.py's ignore filter matches only Lexeme, Sense
    # and EvidenceItem. We run in a subprocess to avoid pytest's WarningsRecorder filter
    # overriding module-level filters.
    probe = (
        "import langpipe.domain.models\n"
        "from langpipe.domain.models.base import DomainModel\n"
        "class ShadowProbeRegister(DomainModel):\n"
        "    register: str | None = None\n"
    )
    result = subprocess.run(
        [sys.executable, "-W", "error::UserWarning", "-c", probe],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert 'Field name "register" in "ShadowProbeRegister" shadows' in result.stderr
