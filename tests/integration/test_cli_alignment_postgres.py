"""Alignment CLI against the disposable PostgreSQL integration database (WP3.10)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from langpipe.cli.app import app
from langpipe.cli.context import reset_context_factory
from tests.service.manifests import manifest_data, write_manifest, write_origin_file

pytestmark = pytest.mark.integration


def _fields(line: str) -> dict[str, str]:
    return dict(token.split("=", 1) for token in line.split())


def _prepare_sources_and_segments(
    runner: CliRunner, tmp_path: Path
) -> tuple[list[str], dict[str, str]]:
    source_ids: list[str] = []
    payloads = (
        ("qaa", b"ref\tqaa\nR1\talpha beta\nR2\tgamma delta epsilon\n"),
        ("por", b"ref\tpor\nR1\tuma casa grande\nR2\toutro dia bonito novo\n"),
    )
    for language, text_bytes in payloads:
        key = f"alignment-{language}"
        relative = f"texts/{key}.tsv"
        write_origin_file(tmp_path, relative, text_bytes)
        data = manifest_data(
            key=key,
            objects=[{"path": relative, "media_type": "text/tab-separated-values"}],
        )
        data["languages"] = [language]
        manifest = write_manifest(tmp_path, data, name=f"{key}.yaml")
        added = runner.invoke(app, ["source", "add", str(manifest)])
        assert added.exit_code == 0, added.output
        source_id = _fields(added.stdout.strip())["source_id"]
        source_ids.append(source_id)
        ingested = runner.invoke(app, ["source", "ingest", source_id])
        assert ingested.exit_code == 0, ingested.output
        extracted = runner.invoke(app, ["extract", source_id])
        assert extracted.exit_code == 0, extracted.output
        normalized = runner.invoke(app, ["normalize", source_id])
        assert normalized.exit_code == 0, normalized.output

    aligned = runner.invoke(
        app,
        ["align", "segments", source_ids[0], source_ids[1], "--namespace", "refs"],
    )
    assert aligned.exit_code == 0, aligned.output
    fields = _fields(aligned.stdout.strip())
    assert set(fields) == {
        "run_id",
        "report_id",
        "alignments",
        "unmatched_source",
        "unmatched_target",
        "reused",
    }
    assert fields["run_id"].startswith("run_")
    assert fields["report_id"].startswith("artifact_")
    assert fields["reused"] == "false"
    assert int(fields["alignments"]) == 2
    assert int(fields["unmatched_source"]) == 0
    assert int(fields["unmatched_target"]) == 0
    return source_ids, fields


def test_cli_alignment_two_sources_postgres(
    clean_db: None, pg_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_context_factory()
    monkeypatch.setenv("LANGPIPE_DATABASE_URL", pg_url)
    monkeypatch.setenv("LANGPIPE_DATA_DIR", str(tmp_path / "data"))
    runner = CliRunner()

    source_ids, _fields_map = _prepare_sources_and_segments(runner, tmp_path)

    denied_key = "alignment-denied"
    denied_relative = f"texts/{denied_key}.txt"
    denied_text = "governance-secret-token"
    write_origin_file(tmp_path, denied_relative, f"{denied_text}\n".encode())
    denied_data = manifest_data(
        key=denied_key,
        objects=[{"path": denied_relative, "media_type": "text/plain"}],
        deny=["align"],
    )
    denied_data["languages"] = ["mzr"]
    denied_manifest = write_manifest(tmp_path, denied_data, name=f"{denied_key}.yaml")
    denied_added = runner.invoke(app, ["source", "add", str(denied_manifest)])
    assert denied_added.exit_code == 0, denied_added.output
    denied_id = _fields(denied_added.stdout.strip())["source_id"]
    assert denied_id not in source_ids
    for args in (
        ["source", "ingest", denied_id],
        ["extract", denied_id],
        ["normalize", denied_id],
    ):
        prepared = runner.invoke(app, args)
        assert prepared.exit_code == 0, prepared.output

    denied_alignment = runner.invoke(
        app,
        ["align", "segments", source_ids[0], denied_id, "--namespace", "refs"],
    )
    assert denied_alignment.exit_code == 3
    output = denied_alignment.stdout + denied_alignment.stderr
    for leak in ("alpha", "beta", "uma", "casa", denied_text):
        assert leak not in output


@pytest.mark.native_alignment
def test_cli_token_alignment_two_sources_postgres(
    clean_db: None, pg_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from langpipe.cli.context import get_context

    reset_context_factory()
    monkeypatch.setenv("LANGPIPE_DATABASE_URL", pg_url)
    monkeypatch.setenv("LANGPIPE_DATA_DIR", str(tmp_path / "data"))
    runner = CliRunner()

    source_ids, fields = _prepare_sources_and_segments(runner, tmp_path)
    assert int(fields["alignments"]) >= 1

    for s_id in source_ids:
        tokenized = runner.invoke(app, ["tokenize", s_id])
        assert tokenized.exit_code == 0, tokenized.output

    token_aligned = runner.invoke(
        app,
        ["align", "tokens", fields["run_id"]],
    )
    assert token_aligned.exit_code == 0, token_aligned.output
    t_fields = _fields(token_aligned.stdout.strip())
    assert set(t_fields) == {
        "run_id",
        "report_id",
        "edges",
        "unaligned_source",
        "unaligned_target",
        "skipped_groups",
        "reused",
    }
    assert t_fields["run_id"].startswith("run_")
    assert t_fields["report_id"].startswith("artifact_")
    assert t_fields["reused"] == "false"
    assert int(t_fields["edges"]) > 0

    ctx = get_context()
    edges = ctx.repo.list_token_alignment_edges_for_run(t_fields["run_id"])
    assert len(edges) == int(t_fields["edges"])
    assert len(edges) > 0

    sal_groups = ctx.repo.list_segment_alignments_for_run(fields["run_id"])
    active_sal = [g for g in sal_groups if g.status.value in ("structural", "approved")]
    source_seg_ids = {s_id for g in active_sal for s_id in g.source_segment_ids}
    target_seg_ids = {s_id for g in active_sal for s_id in g.target_segment_ids}

    # Verify edge endpoints belong to the selected token occurrences
    for edge in edges:
        src_tok = ctx.repo.get_token(edge.source_token_id)
        tgt_tok = ctx.repo.get_token(edge.target_token_id)
        assert src_tok.segment_id in source_seg_ids
        assert tgt_tok.segment_id in target_seg_ids
        assert edge.direction.value in ("forward", "reverse", "symmetrized")
