#!/usr/bin/env python3
"""Slice the implementation plan into one brief file per task.

Each brief is what a junior implementer reads. It contains the task's own text
from the plan, plus the global constraints that apply to it, so a brief is
self-sufficient: the implementer needs the brief and the repo, not the plan
and not the coordinator's context.

Usage:
    .venv/bin/python scripts/slice_plan_briefs.py
    .venv/bin/python scripts/slice_plan_briefs.py --plan PATH --outdir DIR
    .venv/bin/python scripts/slice_plan_briefs.py --list
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_PLAN = (
    ROOT / "docs" / "superpowers" / "plans" / ("2026-10-20-dictionary-session-and-print-edition.md")
)
DEFAULT_OUTDIR = ROOT / "var" / "task-briefs"

TASK_RE = re.compile(r"^## Task (\d+): (.+)$", re.MULTILINE)


def split_tasks(plan_text: str) -> list[tuple[int, str, str]]:
    """Return [(number, title, body), ...] for each task in the plan."""
    matches = list(TASK_RE.finditer(plan_text))
    tasks: list[tuple[int, str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(plan_text)
        body = plan_text[start:end]
        # Stop before the appendices, which belong to the plan, not to a task.
        body = re.split(r"\n## Appendix", body)[0]
        tasks.append((int(match.group(1)), match.group(2).strip(), body.rstrip()))
    return tasks


def extract_global_constraints(plan_text: str) -> str:
    """Return the Global Constraints section verbatim."""
    match = re.search(r"^## Global Constraints\n(.*?)(?=^## )", plan_text, re.MULTILINE | re.DOTALL)
    if not match:
        return ""
    body = match.group(1).strip()
    return "## Global Constraints (apply to every task)\n\n" + body


def build_brief(number: int, title: str, body: str, constraints: str) -> str:
    """Assemble a self-sufficient brief for one task."""
    return f"""# Task {number}: {title}

You are implementing Task {number} of the dictionary session + print edition.

**Source of truth:** the approved design at
`docs/superpowers/specs/2026-10-20-dictionary-session-and-print-edition-design.md`
and the full plan at
`docs/superpowers/plans/2026-10-20-dictionary-session-and-print-edition.md`.

**Working directory:** `{ROOT}`

{constraints}

---

## Your task

{body}

---

## Before you begin

- If anything in the task text is unclear, ask before starting. Do not guess.
- Read the files you are about to change. The plan's `file:line` references are
  accurate as of the plan's writing; verify them before editing.
- The task's steps are already in TDD order: write the failing test, run it to
  see it fail, implement, run it to see it pass, commit.

## When you finish

- Run the task's own verification commands and paste their real output.
- Commit with the message the task specifies.
- Report: what you changed, what the verification output was, and anything that
  surprised you. If a step did not work as written, say so — do not paper over it.
"""


REVIEW_TEMPLATE = """# Review task: {title}

You are the REVIEWER for Task {number} of the dictionary session + print edition.
The implementer has finished. Your job is to check the work against the task's
own acceptance criteria — not to rewrite the code, and not to rubber-stamp it.

**Working directory:** `{root}`

**The task brief the implementer was given:** `{brief_path}`

Read it first. It contains the task's full text, the global constraints, and the
exact acceptance criteria and verification commands.

## What to do

1. Read the brief.
2. Read every file the task changed. **Read only those files** plus anything
   they directly depend on — do not go exploring the repository.
3. **Run the task's verification commands yourself.** Do not trust the
   implementer's report — reproduce the result. If a test fails, that is a
   finding, not a curiosity.
4. Check each acceptance criterion against the actual code, not against the
   implementer's summary.
5. Check the global constraints in the brief still hold. These are the traps:
   - WeasyPrint drops `string-set` on flex/grid items — a `display: flex`
     wrapper around the headword empties the running head, silently.
   - `string-set` belongs on `.headword`, not on the block-level `.entry`.
   - Top-level `const` in a classic `<script>` is NOT on `window`. Use bare
     `I18N` / `State` guarded by `typeof`, never `window.I18N`.
   - The combining-mark regex must be written `/[\\u0300-\\u036f]/g`.
   - The `ex:` tail must be cut BEFORE splitting on `;`.
   - The formats route maps `/formats/<lang>/<rest>` UNDER `formats/`.
   - Letter bucketing must use the normalized key, never `headword[0].upper()`.
6. Do not report style preferences as findings. Report only defects that would
   make the task fail its own acceptance criteria, or that would break a
   constraint the brief states.
7. **If you cannot verify something, say so in FAILURES rather than assuming
   it passes.** An unverified criterion is not a met criterion.

## Output format

Reply with EXACTLY this and nothing else:

```
CRITERIA: <number of acceptance criteria met, out of the total>
FAILURES:
<one line per failing criterion: what is wrong, where (file:line), and what it should be>
VERDICT: PASS or FAIL
```

If every criterion is met, `FAILURES` must be the single word `none`.
"""


def build_review_brief(number: int, title: str, root: Path, brief_path: Path) -> str:
    """Assemble the review brief for one task."""
    return REVIEW_TEMPLATE.format(
        number=number,
        title=title,
        root=root,
        brief_path=brief_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--list", action="store_true", help="list tasks and exit")
    args = parser.parse_args()

    if not args.plan.exists():
        print(f"plan not found: {args.plan}")
        return 1

    plan_text = args.plan.read_text(encoding="utf-8")
    tasks = split_tasks(plan_text)
    constraints = extract_global_constraints(plan_text)

    if args.list:
        for number, title, _ in tasks:
            print(f"  Task {number:2d}: {title}")
        print(f"\n{len(tasks)} tasks")
        return 0

    args.outdir.mkdir(parents=True, exist_ok=True)
    for number, title, body in tasks:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
        path = args.outdir / f"task-{number:02d}-{slug}.md"
        path.write_text(build_brief(number, title, body, constraints), encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}  ({path.stat().st_size} bytes)")

        review_path = args.outdir / f"task-{number:02d}-REVIEW.md"
        review_path.write_text(build_review_brief(number, title, ROOT, path), encoding="utf-8")
        print(f"wrote {review_path.relative_to(ROOT)}  ({review_path.stat().st_size} bytes)")

    print(f"\n{len(tasks)} briefs + {len(tasks)} review briefs in {args.outdir.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
