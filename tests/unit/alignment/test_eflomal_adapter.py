import os
import subprocess
import tempfile
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

import pytest

from langpipe.alignment.adapters.eflomal import EflomalAligner
from langpipe.alignment.base import AlignmentConfig, IndexLink, TokenGroup
from langpipe.alignment.registry import TOKEN_ALIGNERS, resolve_aligner
from langpipe.domain.enums import Symmetrization
from langpipe.domain.errors import AlignmentFailed
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.observation import TokenOccurrence

adapter_module = import_module("langpipe.alignment.adapters.eflomal")
_real_probe_backend = adapter_module._probe_backend


@pytest.fixture(autouse=True)
def native_backend_stub(monkeypatch):
    """Keep adapter unit tests independent of the optional native extra."""
    monkeypatch.setattr(adapter_module, "_probe_backend", lambda: "2.0.0")


def token(surface: str, ordinal: int, form_id: str | None = None) -> TokenOccurrence:
    return TokenOccurrence(
        id=new_id(IdPrefix.TOKEN),
        segment_id=new_id(IdPrefix.SEGMENT),
        run_id=new_id(IdPrefix.RUN),
        ordinal=ordinal,
        raw_surface=surface,
        normalized_surface=surface,
        tokenizer="basic@0.1.0",
        form_id=form_id,
        created_at=datetime.now(UTC),
    )


def config(**kwargs) -> AlignmentConfig:
    return AlignmentConfig(namespace="test", symmetrization=Symmetrization.INTERSECTION, **kwargs)


def fake_runner(monkeypatch, *, forward="0-0\n", reverse="0-0\n", on_call=None):
    def run(command, *, env, timeout, capture_output, check, shell):
        assert shell is False
        if on_call:
            on_call(command, env)
        root = Path(command[-2])
        (root / "forward").write_text(forward, encoding="utf-8")
        (root / "reverse").write_text(reverse, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(adapter_module.subprocess, "run", run)


def test_batch_not_per_group_training(monkeypatch):
    calls = []
    fake_runner(
        monkeypatch,
        forward="0-0\n0-0\n0-0\n",
        reverse="0-0\n0-0\n0-0\n",
        on_call=lambda *x: calls.append(x),
    )
    groups = tuple(TokenGroup(f"sal_{i}", (token("a", 0),), (token("b", 0),)) for i in range(3))
    assert len(EflomalAligner().align(groups, config()).groups) == 3
    assert len(calls) == 1


def test_flatten_occurrences_not_forms(monkeypatch):
    seen = []

    def capture(cmd, env):
        root = Path(cmd[-2])
        seen.append(__import__("json").loads((root / "source.json").read_text(encoding="utf-8")))

    fake_runner(monkeypatch, forward="0-0\n", reverse="0-0\n", on_call=capture)
    f = new_id(IdPrefix.FORM)
    group = TokenGroup(
        "sal_x", (token("same", 0, f), token("same", 1, f)), (token("z", 0), token("z", 1))
    )
    EflomalAligner().align((group,), config())
    # Input is held in private files; repeated occurrence surfaces are not collapsed.
    assert seen == [["same same"]]


def test_reverse_indices_not_swapped(monkeypatch):
    fake_runner(monkeypatch, forward="0-0\n", reverse="1-0\n")
    group = TokenGroup("sal_x", (token("a", 0), token("b", 1)), (token("c", 0),))
    links = EflomalAligner().align((group,), config()).groups[0]
    assert links.reverse == (IndexLink(1, 0),)
    assert links.forward != links.reverse


def test_empty_output_line_preserved(monkeypatch):
    fake_runner(monkeypatch, forward="0-0\n\n0-0\n", reverse="0-0\n\n0-0\n")
    groups = tuple(TokenGroup(f"sal_{i}", (token(str(i), 0),), (token("y", 0),)) for i in range(3))
    output = EflomalAligner().align(groups, config()).groups
    assert output[1].forward == ()
    assert output[2].forward == (IndexLink(0, 0),)


@pytest.mark.parametrize(
    "forward,reverse",
    [
        ("2-0\n", "0-0\n"),
        ("-1-0\n", "0-0\n"),
        ("True-0\n", "0-0\n"),
        ("0-0\n", "0-0\n0-0\n"),
        ("0-0\n", "0-1\n"),
        ("0-0\n", "a-0\n"),
        ("0-0\n", ""),
    ],
)
def test_out_of_range_bool_negative_and_extra_lines_rejected(monkeypatch, forward, reverse):
    fake_runner(monkeypatch, forward=forward, reverse=reverse)
    group = TokenGroup("sal_x", (token("a", 0),), (token("b", 0),))
    with pytest.raises(AlignmentFailed) as exc:
        EflomalAligner().align((group,), config())
    assert exc.value.code == "invalid_adapter_output"


def test_duplicate_links_deduplicated(monkeypatch):
    fake_runner(monkeypatch, forward="0-0 0-0\n", reverse="0-0\n")
    output = EflomalAligner().align(
        (TokenGroup("sal_x", (token("a", 0),), (token("b", 0),)),), config()
    )
    assert output.groups[0].forward == (IndexLink(0, 0),)


def test_no_null_tokens_created(monkeypatch):
    calls = []
    fake_runner(monkeypatch, on_call=lambda *x: calls.append(x))
    groups = (TokenGroup("empty", (), (token("b", 0),)),)
    assert EflomalAligner().align(groups, config()).groups == ()
    assert calls == []
    fake_runner(monkeypatch, forward="\n", reverse="\n")
    group = TokenGroup("sal_x", (token("a", 0), token("unlinked", 1)), (token("b", 0),))
    links = EflomalAligner().align((group,), config()).groups[0]
    for direction in (links.forward, links.reverse):
        assert all(link.source_index != -1 and link.target_index != -1 for link in direction)
        assert all(link.source_index < 2 and link.target_index < 1 for link in direction)
        assert all(link.source_index != 1 for link in direction)


def test_scores_remain_null(monkeypatch):
    fake_runner(monkeypatch)
    output = EflomalAligner().align(
        (TokenGroup("sal_x", (token("a", 0),), (token("b", 0),)),), config()
    )
    for links in (output.groups[0].forward, output.groups[0].reverse):
        assert all(link.score is None and dict(link.raw_scores) == {} for link in links)
    assert output.backend.options["scores"] == "score_unavailable"
    assert output.backend.options["score_model"] == 0


def test_timeout_and_stderr_redacted(monkeypatch, caplog):
    group = TokenGroup("sal_x", (token("a", 0),), (token("b", 0),))

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("child", 1, stderr=b"secret source")

    monkeypatch.setattr(adapter_module.subprocess, "run", timeout)
    with pytest.raises(AlignmentFailed) as raised:
        EflomalAligner().align((group,), config())
    assert raised.value.code == "backend_timeout"
    assert "secret source" not in repr(raised.value) and raised.value.__cause__ is None
    assert raised.value.__context__ is None or raised.value.__suppress_context__

    def failed(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 7, b"secret source", b"secret source")

    monkeypatch.setattr(adapter_module.subprocess, "run", failed)
    with pytest.raises(AlignmentFailed) as raised:
        EflomalAligner().align((group,), config())
    assert raised.value.code == "backend_failed"
    assert "secret source" not in repr(raised.value) and raised.value.__cause__ is None
    assert raised.value.__context__ is None or raised.value.__suppress_context__
    assert "secret source" not in caplog.text


def test_private_temp_files_cleanup(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    observed = []

    def inspect(command, env):
        root = Path(command[-2])
        observed.append(root)
        assert root.is_relative_to(tmp_path)
        assert root.stat().st_mode & 0o777 == 0o700
        assert (root / "source.json").stat().st_mode & 0o777 == 0o600
        assert (root / "target.json").stat().st_mode & 0o777 == 0o600

    fake_runner(monkeypatch, on_call=inspect)
    group = TokenGroup("sal_x", (token("a", 0),), (token("b", 0),))
    EflomalAligner().align((group,), config())
    assert observed and not observed[0].exists()

    def explode(command, *, env, timeout, capture_output, check, shell):
        observed.append(Path(command[-2]))
        raise RuntimeError("secret")

    monkeypatch.setattr(adapter_module.subprocess, "run", explode)
    with pytest.raises(AlignmentFailed):
        EflomalAligner().align((group,), config())
    assert not observed[-1].exists()


def test_mock_never_registered():
    assert TOKEN_ALIGNERS.get("eflomal@0.1.0").name == "eflomal"
    with pytest.raises(AlignmentFailed) as exc:
        resolve_aligner(TOKEN_ALIGNERS, "mock@0.1.0")
    assert exc.value.code == "unknown_method"


@pytest.mark.parametrize(
    "probe_failure", ["missing_distribution", "missing_module", "wrong_version"]
)
def test_missing_native_never_falls_back(monkeypatch, probe_failure):
    monkeypatch.setattr(adapter_module, "_probe_backend", _real_probe_backend)
    calls = []
    fake_runner(monkeypatch, on_call=lambda *args: calls.append(args))
    if probe_failure == "missing_distribution":

        def missing_version(name):
            assert name == "eflomal"
            raise adapter_module.importlib.metadata.PackageNotFoundError(name)

        monkeypatch.setattr(adapter_module.importlib.metadata, "version", missing_version)
    elif probe_failure == "missing_module":
        monkeypatch.setattr(adapter_module.importlib.metadata, "version", lambda name: "2.0.0")
        monkeypatch.setattr(adapter_module.importlib.util, "find_spec", lambda name: None)
    else:
        monkeypatch.setattr(adapter_module.importlib.metadata, "version", lambda name: "2.0.1")

    with pytest.raises(AlignmentFailed) as exc:
        EflomalAligner().align((TokenGroup("sal_x", (token("a", 0),), (token("b", 0),)),), config())
    assert exc.value.code == "backend_unavailable"
    assert calls == []


@pytest.mark.parametrize("side", ["source", "target"])
def test_token_limit_1024_rejected(monkeypatch, side):
    calls = []
    fake_runner(monkeypatch, on_call=lambda *args: calls.append(args))
    valid = tuple(token("x", i) for i in range(1023))
    invalid = tuple(token("x", i) for i in range(1024))
    group = TokenGroup(
        "sal_x", invalid if side == "source" else valid, invalid if side == "target" else valid
    )
    with pytest.raises(AlignmentFailed) as exc:
        EflomalAligner().align((group,), config())
    assert exc.value.code == "invalid_adapter_output" and not calls


def test_1023_tokens_accepted(monkeypatch):
    fake_runner(monkeypatch, forward="\n", reverse="\n")
    group = TokenGroup("sal_x", tuple(token("x", i) for i in range(1023)), (token("y", 0),))
    assert len(EflomalAligner().align((group,), config()).groups) == 1


@pytest.mark.parametrize("surface", ["a b", "a\tb", "\x00", "", "\u200b"])
def test_invalid_surfaces_rejected(monkeypatch, surface):
    calls = []
    fake_runner(monkeypatch, on_call=lambda *args: calls.append(args))
    bad = TokenOccurrence.model_construct(
        id=new_id(IdPrefix.TOKEN),
        segment_id=new_id(IdPrefix.SEGMENT),
        run_id=new_id(IdPrefix.RUN),
        ordinal=0,
        raw_surface=surface,
        normalized_surface=surface,
        tokenizer="basic@0.1.0",
        form_id=None,
        created_at=datetime.now(UTC),
    )
    group = TokenGroup("sal_x", (bad,), (token("b", 0),))
    with pytest.raises(AlignmentFailed) as exc:
        EflomalAligner().align((group,), config())
    assert exc.value.code == "invalid_adapter_output" and not calls


def test_unsupported_seed_before_native_call(monkeypatch):
    calls = []
    fake_runner(monkeypatch, on_call=lambda *args: calls.append(args))
    with pytest.raises(AlignmentFailed) as exc:
        EflomalAligner().align((TokenGroup("sal_x", (), ()),), config(random_seed=4))
    assert exc.value.code == "unsupported_seed" and calls == []


def test_effective_metadata_and_child_environment(monkeypatch):
    before = dict(os.environ)
    seen = []
    fake_runner(monkeypatch, on_call=lambda command, env: seen.append((command, dict(env))))
    output = EflomalAligner().align(
        (TokenGroup("sal_x", (token("a", 0),), (token("b", 0),)),), config(threads=4)
    )
    options = output.backend.options
    assert output.backend.version == "2.0.0"
    assert options == {
        "model": 3,
        "n_samplers": 1,
        "threads": 4,
        "omp_dynamic": False,
        "omp_max_active_levels": 1,
        "timeout_seconds": 300.0,
        "score_model": 0,
        "random_seed": None,
        "randomness": "stochastic_unseeded",
        "native_preprocessing": "lowercase",
        "scores": "score_unavailable",
    }
    assert seen[0][1]["OMP_NUM_THREADS"] == "4"
    assert seen[0][1]["OMP_DYNAMIC"] == "FALSE" and seen[0][1]["OMP_MAX_ACTIVE_LEVELS"] == "1"
    assert dict(os.environ) == before
