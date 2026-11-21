"""Local eflomal adapter. Native input uses normalized surfaces (raw fallback only for None).

Native eflomal lowercases internally; links always map to original ordered occurrences.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from langpipe.alignment.base import (
    AlignmentConfig,
    BackendMetadata,
    IndexLink,
    TokenBatchOutput,
    TokenGroup,
    TokenLinks,
)
from langpipe.domain.errors import AlignmentFailed

_LINK = re.compile(r"^(0|[1-9][0-9]*)-(0|[1-9][0-9]*)$")
_ARCHIVE_SHA256 = "b71183dcf85bf4f59f44ef7a59f5268df1c17c0c8d8093f77b220025ffdba100"
_INVALID_CHARS = {"Cc", "Cf", "Zl", "Zp", "Zs"}


def _probe_backend() -> str:
    """Return the pinned optional backend version or fail with a fixed code."""
    try:
        observed_version = importlib.metadata.version("eflomal")
    except importlib.metadata.PackageNotFoundError:
        raise AlignmentFailed("backend_unavailable") from None
    if observed_version != "2.0.0" or importlib.util.find_spec("eflomal") is None:
        raise AlignmentFailed("backend_unavailable")
    return observed_version


class EflomalAligner:
    name: ClassVar[str] = "eflomal"
    version: ClassVar[str] = "0.1.0"

    def align(self, groups: Sequence[TokenGroup], config: AlignmentConfig) -> TokenBatchOutput:
        if config.random_seed is not None:
            raise AlignmentFailed("unsupported_seed")
        active = tuple(g for g in groups if g.source_tokens and g.target_tokens)
        for group in active:
            if len(group.source_tokens) >= 1024 or len(group.target_tokens) >= 1024:
                raise AlignmentFailed("invalid_adapter_output")
            for token in (*group.source_tokens, *group.target_tokens):
                surface = (
                    token.normalized_surface
                    if token.normalized_surface is not None
                    else token.raw_surface
                )
                if not surface or any(
                    ch.isspace() or unicodedata.category(ch) in _INVALID_CHARS for ch in surface
                ):
                    raise AlignmentFailed("invalid_adapter_output")
        observed_version = _probe_backend()
        if not active:
            return TokenBatchOutput((), self._metadata(config, observed_version))

        source = [
            " ".join(
                t.normalized_surface if t.normalized_surface is not None else t.raw_surface
                for t in g.source_tokens
            )
            for g in active
        ]
        target = [
            " ".join(
                t.normalized_surface if t.normalized_surface is not None else t.raw_surface
                for t in g.target_tokens
            )
            for g in active
        ]
        try:
            with tempfile.TemporaryDirectory(prefix="langpipe-eflomal-") as temp:
                root = Path(temp)
                os.chmod(root, 0o700)
                (root / "source.json").write_text(json.dumps(source), encoding="utf-8")
                (root / "target.json").write_text(json.dumps(target), encoding="utf-8")
                os.chmod(root / "source.json", 0o600)
                os.chmod(root / "target.json", 0o600)
                env = os.environ.copy()
                env.update(
                    {
                        "OMP_NUM_THREADS": str(config.threads),
                        "OMP_DYNAMIC": "FALSE",
                        "OMP_MAX_ACTIVE_LEVELS": "1",
                    }
                )
                child = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        str(Path(__file__).with_name("_eflomal_child.py")),
                        str(root),
                        str(config.model),
                    ],
                    shell=False,
                    env=env,
                    timeout=config.timeout_seconds,
                    capture_output=True,
                    check=False,
                )
                if child.returncode != 0:
                    raise AlignmentFailed("backend_failed")
                forward_text = (root / "forward").read_text(encoding="utf-8")
                reverse_text = (root / "reverse").read_text(encoding="utf-8")
            forward_lines = _lines(forward_text, len(active))
            reverse_lines = _lines(reverse_text, len(active))
            output = []
            for group, f_line, r_line in zip(active, forward_lines, reverse_lines, strict=True):
                output.append(
                    TokenLinks(
                        group.alignment_id,
                        _parse(f_line, len(group.source_tokens), len(group.target_tokens)),
                        _parse(r_line, len(group.source_tokens), len(group.target_tokens)),
                    )
                )
            return TokenBatchOutput(tuple(output), self._metadata(config, observed_version))
        except subprocess.TimeoutExpired:
            raise AlignmentFailed("backend_timeout") from None
        except AlignmentFailed:
            raise
        except Exception:
            raise AlignmentFailed("backend_failed") from None

    def _metadata(self, config: AlignmentConfig, version: str) -> BackendMetadata:
        return BackendMetadata(
            version=version,
            archive_sha256=_ARCHIVE_SHA256,
            options={
                "model": config.model,
                "n_samplers": 1,
                "threads": config.threads,
                "omp_dynamic": False,
                "omp_max_active_levels": 1,
                "timeout_seconds": config.timeout_seconds,
                "score_model": 0,
                "random_seed": None,
                "randomness": "stochastic_unseeded",
                "native_preprocessing": "lowercase",
                "scores": "score_unavailable",
            },
            seed_supported=False,
        )


def _lines(text: str, expected: int) -> list[str]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) != expected:
        raise AlignmentFailed("invalid_adapter_output")
    return lines


def _parse(line: str, source_count: int, target_count: int) -> tuple[IndexLink, ...]:
    found: set[tuple[int, int]] = set()
    for item in line.split():
        match = _LINK.fullmatch(item)
        if match is None:
            raise AlignmentFailed("invalid_adapter_output")
        source_index, target_index = map(int, match.groups())
        if source_index >= source_count or target_index >= target_count:
            raise AlignmentFailed("invalid_adapter_output")
        found.add((source_index, target_index))
    return tuple(IndexLink(a, b) for a, b in sorted(found))
