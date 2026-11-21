"""Offline tests for scripts/deepseek_search.py.

The script is a standalone ops client, so it is imported by path rather than as a package
module. Nothing here touches the network: only the pure parsing/formatting helpers are
exercised.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "deepseek_search.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("deepseek_search", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass() can resolve the module namespace.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ds = _load()

ANTHROPIC_BODY = {
    "content": [
        {"type": "thinking", "thinking": ""},
        {
            "type": "text",
            "text": "Two sources were found for the query.",
            "citations": [
                {
                    "type": "web_search_result_location",
                    "url": "https://a.example/x",
                    "cited_text": "excerpt A",
                },
                {
                    "type": "web_search_result_location",
                    "url": "https://b.example/y",
                    "cited_text": "excerpt B",
                },
            ],
        },
        {
            "type": "web_search_tool_result",
            "content": [
                {
                    "type": "web_search_result",
                    "url": "https://a.example/x",
                    "title": "A",
                    "page_age": "2024-01-01",
                },
                {
                    "type": "web_search_result",
                    "url": "https://b.example/y",
                    "title": "B",
                    "page_age": None,
                },
                {  # duplicate URL across two searches must collapse
                    "type": "web_search_result",
                    "url": "https://a.example/x",
                    "title": "A again",
                },
                {"type": "web_search_result", "url": "", "title": "dropped"},
            ],
        },
    ]
}


def test_parse_anthropic_response_dedupes_and_joins_snippets() -> None:
    report = ds.parse_anthropic_response(ANTHROPIC_BODY)

    assert [hit.url for hit in report.hits] == ["https://a.example/x", "https://b.example/y"]
    assert report.hits[0].title == "A"
    assert report.hits[0].snippet == "excerpt A"
    assert report.hits[0].page_age == "2024-01-01"
    assert report.hits[1].snippet == "excerpt B"
    assert report.answer == "Two sources were found for the query."
    assert report.mode == "server-tool"


def test_parse_anthropic_response_empty_body() -> None:
    report = ds.parse_anthropic_response({})

    assert report.hits == []
    assert report.answer == ""


def test_parse_tools_response_maps_fields_and_skips_missing_urls() -> None:
    body = {
        "results": [
            {
                "url": "https://c.example/z",
                "title": "C",
                "snippet": "short",
                "summary": "longer summary",
                "authority": 3,
                "date": "2026-06-01T00:00:00+00:00",
            },
            {"title": "no url"},
        ]
    }

    report = ds.parse_tools_response(body)

    assert len(report.hits) == 1
    hit = report.hits[0]
    assert (hit.url, hit.title, hit.snippet, hit.summary) == (
        "https://c.example/z",
        "C",
        "short",
        "longer summary",
    )
    assert hit.authority == 3
    assert report.mode == "tools"


def test_format_report_numbers_hits_and_marks_empty() -> None:
    report = ds.parse_anthropic_response(ANTHROPIC_BODY)

    text = ds.format_report(report)

    assert "1. A" in text
    assert "https://b.example/y" in text
    assert "Two sources were found" in text
    assert ds.format_report(ds.SearchReport()).strip() == "(no results)"


def test_api_key_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    assert ds.api_key_from_env() == "sk-test"


def test_api_key_missing_exits_with_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="DEEPSEEK_API_KEY"):
        ds.api_key_from_env()


# --------------------------------------------------------------------------- #
# Billing gate: free window, paid confirmation
# --------------------------------------------------------------------------- #

import io  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

BEFORE_FREE_WINDOW_END = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
AFTER_FREE_WINDOW_END = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def test_free_window_ends_at_beijing_midnight() -> None:
    assert datetime(2026, 10, 31, 16, 0, tzinfo=UTC) == ds.FREE_WINDOW_ENDS_UTC
    assert ds.free_window_remaining(BEFORE_FREE_WINDOW_END) > timedelta(0)
    assert ds.free_window_remaining(AFTER_FREE_WINDOW_END) < timedelta(0)


def test_requires_paid_confirmation_only_outside_window_or_when_billed() -> None:
    assert not ds.requires_paid_confirmation(now=BEFORE_FREE_WINDOW_END)
    assert ds.requires_paid_confirmation(now=AFTER_FREE_WINDOW_END)
    # the raw /v1/tools endpoints are billed even inside the free window
    assert ds.requires_paid_confirmation(billed_always=True, now=BEFORE_FREE_WINDOW_END)


def test_estimated_cost_uses_documented_rate() -> None:
    assert ds.estimated_cost_usd(1000) == 0.75
    assert ds.estimated_cost_usd(40) == 0.03


def test_confirm_billing_is_a_noop_inside_the_free_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_prompt: str) -> str:
        raise AssertionError("must not prompt inside the free window")

    ds.confirm_billing(5, now=BEFORE_FREE_WINDOW_END, ask=fail)


def test_confirm_billing_asks_after_the_window_and_can_abort() -> None:
    prompts: list[str] = []

    def decline(prompt: str) -> str:
        prompts.append(prompt)
        return "n"

    with pytest.raises(SystemExit, match="aborted"):
        ds.confirm_billing(3, now=AFTER_FREE_WINDOW_END, ask=decline, interactive=True)
    assert prompts and "2026-11-01 00:00 Beijing" in prompts[0]
    assert "$0.0022" in prompts[0]  # 3 requests at $0.75/1k = $0.00225

    ds.confirm_billing(3, now=AFTER_FREE_WINDOW_END, ask=lambda _prompt: "y", interactive=True)


def test_confirm_billing_refuses_non_interactive_after_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("y"))

    with pytest.raises(SystemExit, match="non-interactive"):
        ds.confirm_billing(1, now=AFTER_FREE_WINDOW_END)


def test_confirm_billing_yes_paid_authorizes_without_a_prompt(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ds.confirm_billing(2, now=AFTER_FREE_WINDOW_END, assume_yes=True)

    assert "Proceeding (--yes-paid)" in capsys.readouterr().err


def test_announce_billing_status_reports_window_and_paid_modes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ds.announce_billing_status(4, now=BEFORE_FREE_WINDOW_END)
    inside = capsys.readouterr().err
    assert "free until 2026-10-31 16:00 UTC" in inside

    # after the window the gate itself carries the warning, so nothing is double-printed
    ds.announce_billing_status(4, now=AFTER_FREE_WINDOW_END)
    assert capsys.readouterr().err == ""
    ds.announce_billing_status(1, billed_always=True, now=BEFORE_FREE_WINDOW_END)
    assert capsys.readouterr().err == ""
