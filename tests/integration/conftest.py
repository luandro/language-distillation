"""Report sanitization for ``realdata`` tests (WP2.15, senior review items).

Restricted corpus material must never be rendered in pytest's own failure channels. Real-data
tests fail content-free by construction (IDs, counts, U+XXXX labels), but pytest additionally
renders captured stdout/stderr/log sections and — for any failing or skipping item — the
``longrepr``: exception messages, source excerpts, locals, cause/context chains and paths. For
items marked ``realdata`` both channels are sanitized on the report:

- captured sections are replaced with a content-free line count;
- a *skipped* report's ``longrepr`` keeps pytest's ``(path, lineno, reason)`` tuple shape — the
  ``-ra`` summary fold and JUnit serialization require it — but the data-bearing path and reason
  elements are replaced with fixed safe values and never restored; only the numeric line is
  retained as safe test-source metadata;
- any other ``longrepr`` is reduced to the exception type plus safe test identity (nodeid, phase
  and, when available, the crash line). Every unmarked failure detail — including every
  unexpected exception and every unmarked ``pytest.fail`` message — is discarded, because
  message text is never trusted by default.

Fixed diagnostics survive only through the explicit safe mechanism below: a message is preserved
verbatim when it begins with ``SAFE_DIAGNOSTIC_PREFIX``. Marking a message is a deliberate
per-message decision taken next to the content-free helper that builds it; ``pytest.fail`` calls
that were never reviewed for content simply lose their text (the failure still fails, with type
and location intact). pytest 9 renders ``pytest.fail(..., pytrace=False)`` as a regular
exception repr whose crash line reads ``"Failed: <message>"``; the prefix is matched against
that message part.

The captured log *records* are left intact — the in-test leak checker inspects them before any
report exists — and every non-realdata item keeps pytest's default diagnostics, so default-suite
output is unaffected. Synthetic subprocess regression tests in
``test_scriptureearth_marubo.py`` pin all of these properties, including JUnit serialization.
"""

import re
from typing import Any

import pytest

SAFE_DIAGNOSTIC_PREFIX = "[safe-diagnostic] "

# An exception type extracted from a crash message must be a dotted identifier; anything else is
# dropped rather than partially rendered.
_TYPE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")

# Fixed replacements for the data-bearing elements of a skipped report's longrepr tuple. The
# reason is arbitrary caller text and the path points wherever the skip was raised, so both are
# always replaced, never restored — including for safe-marked reasons.
_SAFE_SKIP_PATH = "<realdata>"
_SAFE_SKIP_REASON = "<realdata: skip reason redacted>"


def _redact_realdata_sections(report: Any) -> None:
    sections: list[tuple[str, str]] = []
    for name, content in report.sections:
        if name.startswith("Captured "):
            sections.append(
                (name, f"<realdata: {len(content.splitlines())} captured line(s) redacted>")
            )
        else:
            sections.append((name, content))
    report.sections = sections


def _crash_message_parts(longrepr: Any) -> tuple[str | None, str]:
    """Split a crash line ``"Type: message"`` into (type, message); message is ``""`` if absent.

    Only the part before the first ``": "`` is treated as the type; when there is no colon the
    whole line is a bare type name. The message is used solely for the safe-prefix check, never
    rendered, unless the check passes.
    """
    message = getattr(getattr(longrepr, "reprcrash", None), "message", None)
    if not isinstance(message, str):
        return None, ""
    type_part, _sep, rest = message.partition(": ")
    if not _sep:
        return message.strip() or None, ""
    return (type_part.strip() or None), rest


def _crash_line(longrepr: Any) -> int | None:
    lineno = getattr(getattr(longrepr, "reprcrash", None), "lineno", None)
    return lineno if isinstance(lineno, int) and lineno >= 0 else None


def _redact_realdata_skip_longrepr(report: Any) -> None:
    """Rewrite a skipped report's longrepr keeping pytest's ``(path, lineno, reason)`` shape.

    pytest's own consumers — the ``-ra`` summary's skip fold and JUnit's ``append_skipped`` —
    assert the 3-tuple; a plain-string replacement crashes them. The path and reason elements
    are replaced with the fixed safe values above; only the numeric line survives, like crash
    lines (safe test-source metadata). Whatever pytest put in a non-tuple longrepr is discarded
    wholesale — the tuple shape is still emitted so the summary and serialization stay valid.
    """
    longrepr = report.longrepr
    lineno: int | None = None
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        candidate = longrepr[1]
        if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate >= 0:
            lineno = candidate
    report.longrepr = (_SAFE_SKIP_PATH, lineno, _SAFE_SKIP_REASON)


def _redact_realdata_longrepr(report: Any, item: Any) -> None:
    """Reduce a failed realdata longrepr to exception type + safe test identity/location."""
    longrepr = report.longrepr
    if longrepr is None:
        return
    if isinstance(longrepr, str):
        # Plain-string longrepr (older pytest renderings of pytest.fail/pytrace=False):
        # preserve only an explicitly marked diagnostic.
        if longrepr.startswith(SAFE_DIAGNOSTIC_PREFIX):
            return
        exception_type: str | None = "Failed"
        crash_line = None
    else:
        exception_type, message = _crash_message_parts(longrepr)
        crash_line = _crash_line(longrepr)
        if exception_type == "Failed" and message.startswith(SAFE_DIAGNOSTIC_PREFIX):
            report.longrepr = message  # explicitly vetted fixed diagnostic; preserved verbatim
            return
    parts = [
        "<realdata: failure details redacted",
        f"exception={exception_type or 'unknown'}",
        f"phase={report.when}",
        f"test={item.nodeid}",
    ]
    if crash_line is not None:
        parts.append(f"crash_line={crash_line}")
    report.longrepr = " ".join(parts) + ">"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: Any, call: Any) -> Any:
    report = yield
    if "realdata" in item.keywords:
        _redact_realdata_sections(report)
        # Skipped reports are handled before exception-repr handling: their longrepr is the
        # (path, lineno, reason) tuple, whose shape pytest's summary and serialization require.
        if report.outcome == "skipped":
            _redact_realdata_skip_longrepr(report)
        else:
            _redact_realdata_longrepr(report, item)
    return report
