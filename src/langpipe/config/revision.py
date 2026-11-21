import os
import subprocess
from pathlib import Path

REVISION_ENV = "LANGPIPE_CODE_REVISION"
_GIT_REVISION_COMMAND = ["git", "rev-parse", "--short=12", "HEAD"]
# Resolve the revision of the langpipe checkout, not of the process working directory.
_PACKAGE_DIR = Path(__file__).resolve().parent


def code_revision() -> str:
    override = os.environ.get(REVISION_ENV)
    if override:
        return override
    try:
        completed = subprocess.run(
            _GIT_REVISION_COMMAND,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            cwd=_PACKAGE_DIR,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    revision = completed.stdout.strip()
    if completed.returncode != 0 or not revision:
        return "unknown"
    return revision
