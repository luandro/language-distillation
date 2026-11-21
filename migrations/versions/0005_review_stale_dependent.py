"""Review staleness: admit the stale_dependent lineage kind (ADR-0014).

Revision ID: 0005_review_stale_dependent
Revises: 0004_m4_lexical_and_review
Create Date: 2026-10-16

M4-PLAN §WP4.8 (C10). The review service flags directly dependent records as stale with a
`stale_dependent` lineage edge (child -> parent, ADR-0014). The kind vocabulary of
`ck_lineage_edge_kind` (0001) is extended in place: only the constraint is replaced — no
stored row changes meaning. The migration never imports application code; the value tuple
is a literal copy of the domain enum.

Downgrade restores the 0001 vocabulary and refuses while any `stale_dependent` edge
survives. The refusal runs before any DDL and is transactional, so a refusal leaves the
schema and every row in place.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_review_stale_dependent"
down_revision: str | None = "0004_m4_lexical_and_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS_0001 = (
    "derived_from",
    "generated_from",
    "normalized_from",
    "extracted_from",
    "imported_from",
    "supersedes",
)
_KINDS_WITH_STALE_DEPENDENT = (*_KINDS_0001, "stale_dependent")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.drop_constraint("ck_lineage_edge_kind", "lineage_edge", type_="check")
    op.create_check_constraint(
        "ck_lineage_edge_kind",
        "lineage_edge",
        f"kind IN ({_in_list(_KINDS_WITH_STALE_DEPENDENT)})",
    )


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.execute(
        sa.text("SELECT count(*) FROM lineage_edge WHERE kind = 'stale_dependent'")
    ).scalar_one()
    if count:
        raise RuntimeError(f"downgrade 0005 refused: {count} stale_dependent lineage edges survive")
    op.drop_constraint("ck_lineage_edge_kind", "lineage_edge", type_="check")
    op.create_check_constraint(
        "ck_lineage_edge_kind",
        "lineage_edge",
        f"kind IN ({_in_list(_KINDS_0001)})",
    )
