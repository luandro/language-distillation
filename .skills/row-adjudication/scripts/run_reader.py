#!/usr/bin/env python3
"""Run one free vision reader over a worklist: pick which candidate spelling matches the print.

Benchmarked in ``reader_benchmark.md`` (tight crop + ``--prompt pick``). Readers (``--reader``):
``opencode:<provider/model>`` (free tier) or ``ollama:<model>`` (local). Stdlib only.

Input ``--worklist``: JSON list of ``{idx, candidates, <crop key>}`` (``build_worklist.py`` output,
``worklist.json`` or ``part<i>.json``); the crop key is ``--crop-key`` (default ``crop``) and
the path is relative to the working directory. ``--rows 3,5,9`` restricts the run.

Output ``--out``: raw results ``{reader, crop_key, prompt, rows: [{idx, pred, raw, sec, err}]}``,
rewritten after every row. ``--picks-out`` additionally writes the pick list that
``compare_picks.py`` reads (``[{idx, pick, conf, note}]``, ``-1`` = none, empty answer = ``-1``
with ``conf: low``).

Safety, by design:
- One process, one row at a time. There is no ``--jobs``/parallel mode and none will be added:
  OpenCode free models block the whole IP ("abusive traffic") after a burst, shared with every other
  opencode session on the machine. The opencode throttle defaults to 3 s and cannot go lower.
- On that block the run stops cleanly (exit code 3), keeps the partial ``--out``, and tells you
  to resume. Re-running the same command skips rows already read (resumable); wait for the
  block to lift (an hour or more) first.
- opencode runs from ``RUNNER_CWD`` (default ``/tmp``), outside any repo, so it loads no
  project skills.
Machine reads are evidence only: nothing here votes, promotes or rewrites ``src``/``clean_src``.
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

LETTERS = "ABCDEFGH"
MIN_OPENCODE_THROTTLE = 3.0
EXIT_BLOCKED = 3
BLOCK_MARKER = "abusive traffic"
EMPTY_NOTE = "reader gave no parseable answer (treated as none, low)"


class BlockedError(RuntimeError):
    """The free tier refused the request (IP block); stop and resume later."""


def build_prompt(candidates: list[str], mode: str, crop_kind: str = "tight") -> str:
    """Prompt listing candidates as A, B, C (``pick``: a letter; ``transcribe``: text first)."""
    listing = "\n".join(f"{LETTERS[i]}. {c}" for i, c in enumerate(candidates))
    where = (
        "The image is one line of a printed book."
        if crop_kind == "tight"
        else "The image shows printed book lines; the line to read is the one inside the "
        "highlight box, in the left (Marubo source) column."
    )
    base = (
        f"{where} The text is Marubo with diacritics (tilde on a, e, i, o as ã ẽ ĩ õ, "
        f"and acute accents á é í ó).\nCandidate spellings:\n{listing}\n"
    )
    if mode == "pick":
        return base + (
            "Which candidate matches the printed line exactly, mark for mark (tilde or accent "
            "on each word; ignore capitalization and quote marks)? Answer with only the single "
            "letter, or NONE."
        )
    return base + (
        "First transcribe the printed line exactly, keeping every tilde and accent, on a line "
        "starting 'TEXT:'. Then on a new line write 'ANSWER:' followed by the single letter of "
        "the candidate whose marks match exactly (ignore case and quotes), or NONE."
    )


def normalise_marks(text: str) -> str:
    """Case-folded NFD letters and combining marks only (drops spaces, quotes, punctuation)."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    kept = [ch for ch in decomposed if ch.isalpha() or unicodedata.combining(ch)]
    return "".join(kept)


def parse_answer(text: str, count: int, mode: str) -> int | None:
    """Candidate index, ``-1`` for NONE, ``None`` when no valid answer is found."""
    body = text.strip()
    if mode == "transcribe":
        found = re.search(r"ANSWER:\s*\**\s*([A-H]|NONE)\b", body, re.IGNORECASE)
        body = found.group(1) if found else ""
    else:
        first = next((line for line in body.splitlines() if line.strip()), "")
        body = re.sub(r"[*`\s]", "", first)
        body = re.sub(r"^answer:?", "", body, flags=re.IGNORECASE)
    if not body:
        return None
    if body.upper().startswith("NONE"):
        return -1
    letter = re.match(r"\(?([A-Ha-h])(?![a-zA-Z])", body)
    if letter and LETTERS.index(letter.group(1).upper()) < count:
        return LETTERS.index(letter.group(1).upper())
    return None


def transcription(text: str) -> str | None:
    """The ``TEXT:`` line of a transcribe-mode answer, if any."""
    found = re.search(r"^\s*TEXT:\s*(.+)$", text, re.MULTILINE)
    return found.group(1).strip() if found else None


def match_printed(printed: str, candidates: list[str]) -> int:
    """Index of the one candidate equal to ``printed`` mark for mark; ``-1`` if none/ambiguous."""
    key = normalise_marks(printed)
    hits = [i for i, c in enumerate(candidates) if normalise_marks(c) == key]
    return hits[0] if len(hits) == 1 else -1


def to_pick(row: dict[str, Any]) -> dict[str, Any]:
    """Raw result row -> ``compare_picks.py`` pick (empty answer is none, low confidence)."""
    pred = row["pred"]
    if pred is None:
        return {"idx": row["idx"], "pick": -1, "conf": "low", "note": EMPTY_NOTE}
    return {"idx": row["idx"], "pick": pred, "conf": "high"}


def clean_output(stdout: str) -> str:
    """Strip ANSI colour and opencode's ``>`` banner lines and blanks."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", stdout)
    return "\n".join(ln for ln in text.splitlines() if ln.strip() and not ln.startswith(">"))


def encode_image(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


def call_ollama(model: str, prompt: str, image: str) -> str:
    body = json.dumps(
        {
            "model": model,
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "num_predict": 200},
            "messages": [{"role": "user", "content": prompt, "images": [encode_image(image)]}],
        }
    ).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/chat", body, {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return str(json.load(resp)["message"]["content"])


def call_opencode(model: str, prompt: str, image: str) -> str:
    cwd = os.environ.get("RUNNER_CWD", "/tmp")
    proc = subprocess.run(
        ["opencode", "run", "-m", model, "-f", str(Path(image).resolve()), "--", prompt],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=cwd,
        check=False,
    )
    if BLOCK_MARKER in proc.stdout + proc.stderr:
        raise BlockedError("opencode free tier blocked (abusive traffic)")
    return clean_output(proc.stdout)


CALLERS: dict[str, Callable[[str, str, str], str]] = {
    "ollama": call_ollama,
    "opencode": call_opencode,
}


def load_done(out: Path) -> list[dict[str, Any]]:
    """Rows already read in a previous run (resume); errored rows are read again."""
    if not out.exists():
        return []
    rows = json.loads(out.read_text(encoding="utf-8")).get("rows", [])
    return [row for row in rows if not row.get("err")]


def write_results(out: Path, header: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    out.write_text(json.dumps({**header, "rows": rows}, ensure_ascii=False), encoding="utf-8")


def read_rows(
    items: list[dict[str, Any]],
    call: Callable[[str, str, str], str],
    model: str,
    args: argparse.Namespace,
    done: list[dict[str, Any]],
    header: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    """Read rows one at a time, saving after each; returns ``(rows, blocked)``."""
    rows = list(done)
    seen = {row["idx"] for row in rows}
    crop_kind = "ctx" if args.crop_key == "ctx" else "tight"
    for item in items:
        if item["idx"] in seen:
            continue
        prompt = build_prompt(item["candidates"], args.prompt, crop_kind)
        started = time.time()
        raw, err = "", None
        try:
            raw = call(model, prompt, item[args.crop_key])
        except BlockedError as exc:
            print(f"BLOCKED at idx {item['idx']}: {exc}", file=sys.stderr)
            return rows, True
        except Exception as exc:  # noqa: BLE001 - one bad row must not end the run
            err = repr(exc)
        pred = None if err else parse_answer(raw, len(item["candidates"]), args.prompt)
        if args.prompt == "transcribe" and pred is None and not err:
            printed = transcription(raw)
            pred = match_printed(printed, item["candidates"]) if printed else pred
        rows.append(
            {
                "idx": item["idx"],
                "pred": pred,
                "sec": round(time.time() - started, 2),
                "raw": raw[:1200],
                "err": err,
            }
        )
        write_results(args.out, header, rows)
        print(item["idx"], pred, round(rows[-1]["sec"], 1), file=sys.stderr, flush=True)
        time.sleep(args.throttle)
    return rows, False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--reader", required=True, help="opencode:<provider/model> | ollama:<model>"
    )
    parser.add_argument("--worklist", type=Path, required=True)
    parser.add_argument("--crop-key", default="crop", help="item key holding the crop path")
    parser.add_argument("--prompt", choices=["pick", "transcribe"], default="pick")
    parser.add_argument("--rows", help="comma-separated idx list")
    parser.add_argument("--throttle", type=float, help="seconds between rows (opencode: >= 3)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--picks-out", type=Path, help="also write a compare_picks.py pick list")
    for flag in ("--jobs", "--parallel"):
        parser.add_argument(flag, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.jobs is not None or args.parallel is not None:
        print("refused: parallel readers are not supported by design (IP block)", file=sys.stderr)
        return 2
    kind, _, model = args.reader.partition(":")
    if kind not in CALLERS or not model:
        print(f"unknown reader {args.reader!r}", file=sys.stderr)
        return 2
    if args.throttle is None:
        args.throttle = MIN_OPENCODE_THROTTLE if kind == "opencode" else 0.0
    if kind == "opencode" and args.throttle < MIN_OPENCODE_THROTTLE:
        print(f"refused: opencode throttle must be >= {MIN_OPENCODE_THROTTLE} s", file=sys.stderr)
        return 2
    items = json.loads(args.worklist.read_text(encoding="utf-8"))
    if args.rows:
        want = {int(x) for x in args.rows.split(",")}
        items = [item for item in items if item["idx"] in want]
    header = {"reader": args.reader, "crop_key": args.crop_key, "prompt": args.prompt}
    done = load_done(args.out)
    rows, blocked = read_rows(items, CALLERS[kind], model, args, done, header)
    write_results(args.out, header, rows)
    if args.picks_out:
        picks = [to_pick(row) for row in rows if not row.get("err")]
        args.picks_out.write_text(json.dumps(picks, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{args.reader}: {len(rows)}/{len(items)} rows read -> {args.out}")
    if blocked:
        print(
            "Stopped: free tier blocked this IP. Partial results saved. Wait for the block to "
            "lift (an hour or more), then re-run the same command to resume.",
            file=sys.stderr,
        )
        return EXIT_BLOCKED
    return 0


if __name__ == "__main__":
    sys.exit(main())
