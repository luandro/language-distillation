"""M2 text processing: widen artifact kinds for extraction, normalization and tokenization reports.

Revision ID: 0002_m2_text_processing
Revises: 0001_m1_evidence_substrate
Create Date: 2026-10-12

ADR-0010. Only the `artifact.kind` check constraint changes; no tables or columns. Enum value
tuples are literal copies of the domain enums; the migration never imports application code.
Downgrade refuses (no silent deletion) when artifact rows already use the M2 kinds.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_m2_text_processing"
down_revision: str | None = "0001_m1_evidence_substrate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ARTIFACT_KINDS_M1 = (
    "ingest_report",
    "extraction_snapshot",
    "alignment_file",
    "cldf_export",
    "benchmark_report",
    "dataset",
    "other",
)
_ARTIFACT_KINDS_M2_ADDED = (
    "extraction_report",
    "extraction_error",
    "normalization_report",
    "tokenization_report",
)
_ARTIFACT_KINDS = _ARTIFACT_KINDS_M1 + _ARTIFACT_KINDS_M2_ADDED
_ARTIFACT_KIND_CHECK = "ck_artifact_kind"


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _replace_artifact_kind_check(values: tuple[str, ...]) -> None:
    op.drop_constraint(_ARTIFACT_KIND_CHECK, "artifact", type_="check")
    op.create_check_constraint(_ARTIFACT_KIND_CHECK, "artifact", f"kind IN ({_in_list(values)})")


def upgrade() -> None:
    _replace_artifact_kind_check(_ARTIFACT_KINDS)


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.execute(
        sa.text(
            f"SELECT count(*) FROM artifact WHERE kind IN ({_in_list(_ARTIFACT_KINDS_M2_ADDED)})"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(f"downgrade 0002 refused: {count} artifact rows use M2 artifact kinds")
    _replace_artifact_kind_check(_ARTIFACT_KINDS_M1)
