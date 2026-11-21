"""`langpipe lexicon` commands for Stage 6 lexical induction (WP4.7)."""

from typing import Annotated

import typer

from langpipe.cli.context import get_context, guarded
from langpipe.lexicon.service import LexicalService

lexicon_app = typer.Typer(name="lexicon", help="Lexical induction and management")


def _flag(value: bool) -> str:
    return "true" if value else "false"


@lexicon_app.command("induce")
@guarded
def induce(
    run_id: Annotated[
        str, typer.Option("--run-id", help="Succeeded alignment or wordlist run id.")
    ],
    method: Annotated[str, typer.Option("--method")] = "alignment_cooccurrence@0.1.0",
    target_language: Annotated[str | None, typer.Option("--target-language")] = None,
    contact_language: Annotated[str | None, typer.Option("--contact-language")] = None,
) -> None:
    ctx = get_context()
    result = LexicalService(ctx).induce_lexicon(
        run_id,
        method=method,
        target_language=target_language,
        contact_language=contact_language,
    )
    # Identifiers and counts only; the summary never echoes source content.
    fields = [
        f"run_id={result.run.id}",
        f"lexemes={result.lexemes}",
        f"senses={result.senses}",
        f"evidence_items={result.evidence_items}",
        f"reused={_flag(result.reused)}",
    ]
    fields.extend(f"{name}={count}" for name, count in sorted(result.status_counts.items()))
    typer.echo(" ".join(fields))
