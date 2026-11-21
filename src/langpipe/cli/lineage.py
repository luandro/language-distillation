"""`langpipe lineage` commands: impact analysis over the lineage graph."""

import typer

from langpipe.cli.context import get_context, guarded
from langpipe.domain.errors import InvalidId
from langpipe.domain.ids import is_id
from langpipe.lineage.impact import impact_of
from langpipe.lineage.knowledge_impact import revocation_impact

lineage_app = typer.Typer(no_args_is_help=True)


@lineage_app.command("descendants")
@guarded
def descendants(object_id: str) -> None:
    if not is_id(object_id):
        raise InvalidId()
    for entry in impact_of(get_context().repo, object_id):
        typer.echo(
            f"depth={entry.depth} object_id={entry.object_id} entity_type={entry.entity_type.value}"
        )


@lineage_app.command("impact")
@lineage_app.command("revocation-impact")
@guarded
def impact(source_id: str) -> None:
    """Summarize downstream lineage impact of revoking source_id."""
    if not is_id(source_id):
        raise InvalidId()
    res = revocation_impact(get_context().repo, source_id)
    typer.echo(f"source_id={res.source_id} revoked={str(res.revoked).lower()} total={res.total}")
    for et, ids in sorted(res.by_type.items(), key=lambda item: item[0].value):
        if ids:
            typer.echo(f"  {et.value}={len(ids)}")
