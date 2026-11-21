"""`langpipe source` commands: register, ingest, verify and show a source (metadata only)."""

import json
from pathlib import Path
from typing import Annotated

import typer

from langpipe.cli.context import get_context, guarded
from langpipe.domain.enums import ApprovalAction, Operation
from langpipe.governance import (
    effective_policy,
    get_source_policy,
    record_approval,
)
from langpipe.ingestion.ingest import ingest_source, resolve_source
from langpipe.ingestion.registration import register_source
from langpipe.ingestion.verify import verify_source
from langpipe.review.authority import ROLE_GOVERNANCE_STEWARD

source_app = typer.Typer(no_args_is_help=True)


def _flag(value: bool) -> str:
    return "true" if value else "false"


@source_app.command("add")
@guarded
def add(manifest_path: Path) -> None:
    result = register_source(get_context(), manifest_path)
    typer.echo(
        f"source_id={result.source.id} key={result.source.key} objects={len(result.objects)} "
        f"run_id={result.run.id} reused={_flag(result.reused)}"
    )


@source_app.command("ingest")
@guarded
def ingest(source_ref: str) -> None:
    result = ingest_source(get_context(), source_ref)
    report_id = result.report.id if result.report is not None else "none"
    typer.echo(
        f"source_id={result.source.id} run_id={result.run.id} blobs={len(result.blobs)} "
        f"report_id={report_id} reused={_flag(result.reused)}"
    )


@source_app.command("verify")
@guarded
def verify(source_ref: str) -> None:
    checks = verify_source(get_context(), source_ref)
    for check in checks:
        typer.echo(
            f"source_object_id={check.source_object_id} sha256={check.sha256} status={check.status}"
        )
    if any(check.status != "ok" for check in checks):
        raise typer.Exit(code=5)


@source_app.command("show")
@guarded
def show(source_ref: str) -> None:
    # Metadata only: the title and object paths are printed here and nowhere else.
    ctx = get_context()
    source = resolve_source(ctx, source_ref)
    eff = effective_policy(ctx.repo, source)
    payload = {
        "source": source.model_dump(mode="json"),
        "policy": get_source_policy(ctx.repo, source).model_dump(mode="json"),
        "effective_approved_operations": [op.value for op in eff.approved_operations],
        "objects": [obj.model_dump(mode="json") for obj in ctx.repo.list_source_objects(source.id)],
    }
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


@source_app.command("approve")
@guarded
def approve(
    source_ref: Annotated[str, typer.Option("--source", help="Source ID or key")],
    operation: Annotated[Operation, typer.Option("--operation", help="Operation to approve")],
    approver: Annotated[str, typer.Option("--approver", help="Approver ID")],
    role: Annotated[str, typer.Option("--role", help="Approver role")] = ROLE_GOVERNANCE_STEWARD,
    basis: Annotated[str, typer.Option("--basis", help="Approval justification")] = "",
) -> None:
    ctx = get_context()
    source = resolve_source(ctx, source_ref)
    app = record_approval(
        ctx.repo,
        source_id=source.id,
        operation=operation,
        action=ApprovalAction.GRANT,
        approver_id=approver,
        basis=basis,
        approver_role=role,
        code_revision=ctx.code_revision,
    )
    typer.echo(
        f"approval_id={app.id} source_id={app.source_id} "
        f"operation={app.operation.value} action={app.action.value}"
    )


@source_app.command("withdraw-approval")
@guarded
def withdraw_approval(
    source_ref: Annotated[str, typer.Option("--source", help="Source ID or key")],
    operation: Annotated[Operation, typer.Option("--operation", help="Operation to withdraw")],
    approver: Annotated[str, typer.Option("--approver", help="Approver ID")],
    role: Annotated[str, typer.Option("--role", help="Approver role")] = ROLE_GOVERNANCE_STEWARD,
    basis: Annotated[str, typer.Option("--basis", help="Withdrawal justification")] = "",
) -> None:
    ctx = get_context()
    source = resolve_source(ctx, source_ref)
    app = record_approval(
        ctx.repo,
        source_id=source.id,
        operation=operation,
        action=ApprovalAction.WITHDRAW,
        approver_id=approver,
        basis=basis,
        approver_role=role,
        code_revision=ctx.code_revision,
    )
    typer.echo(
        f"approval_id={app.id} source_id={app.source_id} "
        f"operation={app.operation.value} action={app.action.value}"
    )
