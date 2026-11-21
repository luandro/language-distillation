"""Private subprocess entry point for the pinned native adapter."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path


def main() -> int:
    os.umask(0o077)
    root = Path(sys.argv[1])
    try:
        eflomal = importlib.import_module("eflomal")
    except ImportError:
        return 20
    source = json.loads((root / "source.json").read_text(encoding="utf-8"))
    target = json.loads((root / "target.json").read_text(encoding="utf-8"))
    eflomal.Aligner(model=int(sys.argv[2]) if len(sys.argv) > 2 else 3, n_samplers=1).align(
        source,
        target,
        links_filename_fwd=str(root / "forward"),
        links_filename_rev=str(root / "reverse"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
