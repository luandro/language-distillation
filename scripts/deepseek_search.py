#!/usr/bin/env python3
"""DeepSeek Search & Fetch client.

Docs: https://api-docs.deepseek.com/guides/search/

Two backends:

``server-tool`` (default)
    An Anthropic-compatible ``/messages`` call carrying the ``web_search_20250305``
    server tool, i.e. the same path DeepSeek Harness uses. DeepSeek documents these
    server-side search calls as *free of charge until 2026-11-01 00:00 Beijing*.
    Only the supporting model turn is billed.

``tools``
    The raw ``POST /v1/tools/search`` and ``POST /v1/tools/fetch`` endpoints. Richer
    payloads (summary, content, authority) but billed at $0.75 per 1,000 successful
    requests, so it is not the free window.

The API key is read from ``DEEPSEEK_API_KEY``. Nothing is logged or persisted.

Examples
--------
::

    uv run python scripts/deepseek_search.py search "Marubo Panoan corpus" --count 10
    uv run python scripts/deepseek_search.py search "AILLA marubo" --mode tools --json
    uv run python scripts/deepseek_search.py fetch https://example.org/page
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic/v1"
DEFAULT_MODEL = "deepseek-v4-flash"
ANTHROPIC_VERSION = "2023-06-01"
USER_AGENT = "langpipe-deepseek-search/0.1"
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})

#: DeepSeek documents server-side tool calls as free until 2026-11-01 00:00 Beijing (UTC+8).
FREE_WINDOW_ENDS_UTC = datetime(2026, 10, 31, 16, 0, tzinfo=UTC)
#: Raw ``/v1/tools*`` endpoints are billed per successful request today.
PAID_PRICE_PER_1K_REQUESTS_USD = 0.75


@dataclass(frozen=True)
class SearchHit:
    """One normalized search result."""

    url: str
    title: str = ""
    snippet: str = ""
    page_age: str = ""
    summary: str = ""
    authority: int = -1
    date: str = ""


@dataclass
class SearchReport:
    """Normalized result of one search request."""

    hits: list[SearchHit] = field(default_factory=list)
    answer: str = ""
    mode: str = "server-tool"


def api_key_from_env(environ: dict[str, str] | None = None) -> str:
    """Return the API key or exit with a clear message."""
    env = os.environ if environ is None else environ
    key = env.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "DEEPSEEK_API_KEY is not set. Export it (it is already in ~/.zshrc) or pass it "
            "through the DSH credentials service, then retry."
        )
    return key


def utcnow() -> datetime:
    """Current UTC time, isolated so the free-window logic is testable."""
    return datetime.now(UTC)


def free_window_remaining(now: datetime | None = None) -> timedelta:
    """Time left in DeepSeek's free server-tool window (negative once it has ended)."""
    return FREE_WINDOW_ENDS_UTC - (now or utcnow())


def requires_paid_confirmation(*, billed_always: bool = False, now: datetime | None = None) -> bool:
    """True when a run would be charged and therefore needs an explicit go-ahead."""
    return billed_always or free_window_remaining(now) <= timedelta(0)


def estimated_cost_usd(requests: int) -> float:
    """Rough charge for ``requests`` successful requests at the documented rate."""
    return requests * PAID_PRICE_PER_1K_REQUESTS_USD / 1000.0


def billing_message(requests: int, *, billed_always: bool = False) -> str:
    """Human-readable warning shown before any request that may be charged."""
    cost = estimated_cost_usd(requests)
    if billed_always:
        reason = (
            "The raw /v1/tools endpoints are billed at "
            f"${PAID_PRICE_PER_1K_REQUESTS_USD:.2f} per 1,000 successful requests."
        )
    else:
        beijing = FREE_WINDOW_ENDS_UTC + timedelta(hours=8)
        reason = (
            "DeepSeek's free window for server-side search ended on "
            f"{FREE_WINDOW_ENDS_UTC:%Y-%m-%d %H:%M} UTC "
            f"({beijing:%Y-%m-%d %H:%M} Beijing)."
        )
    return (
        f"{reason} This run makes {requests} search request(s), about ${cost:.4f}."
    )


def confirm_billing(
    requests: int,
    *,
    billed_always: bool = False,
    assume_yes: bool = False,
    now: datetime | None = None,
    ask: Callable[[str], str] = input,
    interactive: bool | None = None,
) -> None:
    """Require explicit consent before spending money on DeepSeek requests.

    Inside the free window and for free modes this is a no-op. Once the window closes (or for
    the already-billed ``tools`` mode) an interactive run asks, a piped/non-interactive run is
    refused, and ``--yes-paid`` records the consent non-interactively.
    """
    if not requires_paid_confirmation(billed_always=billed_always, now=now):
        return
    message = billing_message(requests, billed_always=billed_always)
    if assume_yes:
        print(f"{message} Proceeding (--yes-paid).", file=sys.stderr)
        return
    if not (sys.stdin.isatty() if interactive is None else interactive):
        raise SystemExit(
            f"{message} Refusing to spend money in a non-interactive shell; "
            "re-run with --yes-paid to authorize this charge."
        )
    answer = ask(f"{message} Continue and be charged? [y/N] ")
    if answer.strip().lower() not in {"y", "yes"}:
        raise SystemExit("aborted: no billed DeepSeek requests were made")


def announce_billing_status(
    requests: int, *, billed_always: bool = False, now: datetime | None = None
) -> None:
    """Print the free-window status line; billed runs get their warning from the gate."""
    if requires_paid_confirmation(billed_always=billed_always, now=now):
        return
    remaining = free_window_remaining(now)
    print(
        "[deepseek] server-tool search is free until "
        f"{FREE_WINDOW_ENDS_UTC:%Y-%m-%d %H:%M} UTC "
        f"({remaining.days}d {remaining.seconds // 3600}h left); "
        "after that the harness asks before charging.",
        file=sys.stderr,
    )


class ApiError(RuntimeError):
    """A non-retryable HTTP failure returned by the API."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


def _post_json(
    url: str, payload: dict[str, Any], api_key: str, timeout: float = 120.0
) -> dict[str, Any]:
    """POST JSON with bounded retries on transient failures; return the parsed body."""
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "authorization": f"Bearer {api_key}",
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
        "user-agent": USER_AGENT,
    }
    delays = (2.0, 6.0)
    last: str = ""
    for attempt in range(len(delays) + 1):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https base
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", "replace")[:400]
            last = message
            if exc.code not in RETRY_STATUSES or attempt == len(delays):
                raise ApiError(exc.code, message) from exc
            time.sleep(delays[attempt])
        except urllib.error.URLError as exc:
            last = str(exc.reason)
            if attempt == len(delays):
                raise ApiError(0, last) from exc
            time.sleep(delays[attempt])
    raise ApiError(0, last)


def citation_snippets(blocks: list[dict[str, Any]]) -> dict[str, str]:
    """Map cited URL to the excerpt DeepSeek attached to a text citation."""
    snippets: dict[str, str] = {}
    for block in blocks:
        if block.get("type") != "text":
            continue
        for citation in block.get("citations") or []:
            url = citation.get("url") or ""
            text = citation.get("cited_text") or ""
            if url and text:
                snippets.setdefault(str(url), str(text))
    return snippets


def parse_anthropic_response(response: dict[str, Any]) -> SearchReport:
    """Map a DeepSeek Anthropic-compatible Messages body to a normalized report."""
    blocks = response.get("content") or []
    snippets = citation_snippets(blocks)
    seen: set[str] = set()
    hits: list[SearchHit] = []
    for block in blocks:
        if block.get("type") != "web_search_tool_result":
            continue
        for item in block.get("content") or []:
            url = str(item.get("url") or "")
            if item.get("type") != "web_search_result" or not url or url in seen:
                continue
            seen.add(url)
            hits.append(
                SearchHit(
                    url=url,
                    title=str(item.get("title") or ""),
                    snippet=snippets.get(url, ""),
                    page_age=str(item.get("page_age") or ""),
                )
            )
    answer = "\n".join(
        str(block.get("text") or "") for block in blocks if block.get("type") == "text"
    ).strip()
    return SearchReport(hits=hits, answer=answer, mode="server-tool")


def parse_tools_response(response: dict[str, Any]) -> SearchReport:
    """Map a raw ``/v1/tools/search`` body to a normalized report."""
    hits = [
        SearchHit(
            url=str(item.get("url") or ""),
            title=str(item.get("title") or ""),
            snippet=str(item.get("snippet") or ""),
            summary=str(item.get("summary") or ""),
            authority=int(item.get("authority", -1)),
            date=str(item.get("date") or ""),
        )
        for item in response.get("results") or []
        if item.get("url")
    ]
    return SearchReport(hits=hits, mode="tools")


def server_tool_search(
    query: str,
    count: int = 10,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str = DEFAULT_MODEL,
    include_content: bool = False,
) -> SearchReport:
    """Search through the free server-side web_search tool."""
    key = api_key or api_key_from_env()
    endpoint = (
        base_url
        or os.environ.get("DEEPSEEK_SEARCH_BASE_URL")
        or DEFAULT_ANTHROPIC_BASE_URL
    )
    prompt = (
        f"Search the web for: {query}. "
        f"Report the {count} best sources with title and URL."
    )
    if include_content:
        prompt += " Quote the relevant passage from each page."
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [
            {"type": "web_search_20250305", "name": "web_search", "max_uses": max(1, min(count, 5))}
        ],
    }
    return parse_anthropic_response(_post_json(f"{endpoint.rstrip('/')}/messages", payload, key))


def tools_search(
    query: str,
    count: int = 10,
    api_key: str | None = None,
    base_url: str | None = None,
    include_content: bool = False,
) -> SearchReport:
    """Search through the billed raw ``/v1/tools/search`` endpoint."""
    key = api_key or api_key_from_env()
    root = (base_url or os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    payload = {"query": query, "count": max(1, min(count, 50)), "need_content": include_content}
    return parse_tools_response(_post_json(f"{root}/v1/tools/search", payload, key))


def tools_fetch(
    url: str, api_key: str | None = None, base_url: str | None = None
) -> dict[str, Any]:
    """Fetch one page through the billed raw ``/v1/tools/fetch`` endpoint."""
    key = api_key or api_key_from_env()
    root = (base_url or os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    return _post_json(f"{root}/v1/tools/fetch", {"url": url}, key)


def format_report(report: SearchReport) -> str:
    """Render a report as plain text for a terminal."""
    lines: list[str] = []
    for index, hit in enumerate(report.hits, start=1):
        title = hit.title or "(untitled)"
        lines.append(f"{index}. {title}")
        lines.append(f"   {hit.url}")
        if hit.snippet:
            lines.append(f"   {hit.snippet[:280]}")
        if hit.summary:
            lines.append(f"   {hit.summary[:280]}")
        extras = [
            f"authority={hit.authority}" if hit.authority >= 0 else "",
            hit.date,
            hit.page_age,
        ]
        extra = " ".join(part for part in extras if part)
        if extra:
            lines.append(f"   [{extra}]")
    if report.answer:
        lines.append("")
        lines.append(report.answer)
    if not report.hits:
        lines.append("(no results)")
    return "\n".join(lines)


def _research_argv(args: argparse.Namespace) -> list[str]:
    """Rebuild a ``lang_research.py`` argument vector from parsed ``research`` options."""
    argv = ["--iso", args.iso]
    for flag, value in (
        ("--name", args.name),
        ("--family", args.family),
        ("--lanes", args.lanes),
        ("--outdir", str(args.outdir) if args.outdir else ""),
    ):
        if value:
            argv += [flag, value]
    for alias in args.alias:
        argv += ["--alias", alias]
    argv += ["--count", str(args.count)]
    if args.max_queries:
        argv += ["--max-queries", str(args.max_queries)]
    if args.dry_run:
        argv.append("--dry-run")
    if args.yes_paid:
        argv.append("--yes-paid")
    argv += ["--sleep", str(args.sleep)]
    return argv


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    parser = argparse.ArgumentParser(
        description="DeepSeek Search & Fetch client (warns and asks before billing)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="search the web")
    search.add_argument("query")
    search.add_argument("--count", type=int, default=10)
    search.add_argument("--mode", choices=("server-tool", "tools"), default="server-tool")
    search.add_argument("--model", default=DEFAULT_MODEL)
    search.add_argument("--include-content", action="store_true")
    search.add_argument("--json", action="store_true", help="emit the normalized report as JSON")
    search.add_argument(
        "--yes-paid", action="store_true", help="authorize billing without an interactive prompt"
    )

    fetch = sub.add_parser("fetch", help="fetch one page as Markdown")
    fetch.add_argument("url")
    fetch.add_argument("--json", action="store_true")
    fetch.add_argument(
        "--yes-paid", action="store_true", help="authorize billing without an interactive prompt"
    )

    research = sub.add_parser(
        "research",
        help="multi-lane resource sweep for one language (delegates to scripts/lang_research.py)",
    )
    research.add_argument("--iso", required=True, help="ISO 639-3 code, e.g. mpu")
    research.add_argument("--name", default="", help="language name when no profile exists")
    research.add_argument("--family", default="", help="language family when no profile exists")
    research.add_argument(
        "--alias", action="append", default=[], help="extra query name (repeatable)"
    )
    research.add_argument("--lanes", default="", help="comma-separated lanes (default: all)")
    research.add_argument("--count", type=int, default=8, help="results per query (1-10)")
    research.add_argument("--max-queries", type=int, default=0, help="cap queries (0 = all)")
    research.add_argument("--outdir", type=Path, default=None)
    research.add_argument("--dry-run", action="store_true", help="print queries and exit")
    research.add_argument("--sleep", type=float, default=0.25)
    research.add_argument(
        "--yes-paid", action="store_true", help="authorize billing without an interactive prompt"
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "research":
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from lang_research import main as lang_research_main

            return lang_research_main(_research_argv(args))

        billed_always = args.command == "fetch" or getattr(args, "mode", "") == "tools"
        announce_billing_status(1, billed_always=billed_always)
        confirm_billing(1, billed_always=billed_always, assume_yes=args.yes_paid)

        if args.command == "search":
            if args.mode == "tools":
                report = tools_search(
                    args.query, args.count, include_content=args.include_content
                )
            else:
                report = server_tool_search(
                    args.query, args.count, model=args.model, include_content=args.include_content
                )
            if args.json:
                print(
                    json.dumps(
                        {
                            "mode": report.mode,
                            "answer": report.answer,
                            "hits": [hit.__dict__ for hit in report.hits],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(format_report(report))
            return 0
        page = tools_fetch(args.url)
        if args.json:
            print(json.dumps(page, ensure_ascii=False, indent=2))
        else:
            print(page.get("title", ""))
            print(page.get("content", ""))
        return 0
    except ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
