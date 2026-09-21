"""drop users.can_send_invoices (BE Gap 720)

Revision ID: c1d2e3f4a720
Revises: d6e7f8a9b0c1
Create Date: 2026-09-21

WHY THIS COLUMN GOES. BE Gap 405 added `users.can_send_invoices` as a fourth
per-user permission. On Admin -> Users the grants render as one line ("Trainer,
Auditor, Loader, Send Invoices"), so a flag that was really an outbound
*visibility* control read as a fourth role. The founder's ruling (2026-09-21) is
that this product has Loader / Trainer / Auditor plus the Admin role, and
nothing else.

WHAT STILL GUARDS OUTBOUND, so this is a removal and not a hole:
    prepare (upload / build)  can_load + Tenant.send_invoices_enabled
    confirm-send              can_audit  (BE Gap 721 additionally refuses an
                              API key on the actions_no_send policy)
    mark-paid                 can_audit, and only from status SENT
The person who prepares an invoice still cannot be the one who issues it.

DEPLOY ORDER MATTERS. The code that stops reading this column ships in the
commit *before* this migration, and this migration is merged only once that
deploy is live. Azure Container Apps keeps the previous revision serving while
the new one starts and runs `alembic upgrade head`, so dropping the column in
the same release would leave old code SELECTing a column that no longer exists
-- every user lookup, and therefore every login, failing for the length of the
rollout.

WHAT IS LOST, AND HOW IT IS KEPT. `downgrade()` re-creates the column, but not
which users held the grant: that is data, and a dropped column takes its data
with it. So `upgrade()` reads the affected rows and logs them before dropping,
which puts the list in the deploy logs where it can be read back if this is ever
reversed. Deliberately a log line and not a backup table -- a table nobody has
agreed to keep is a second thing to forget about, and the audience for this is a
person reading the release, once.
"""
from typing import Sequence, Union
import logging

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a720"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    bind = op.get_bind()

    # Read before dropping. Wrapped: a failure to *log* must never fail the
    # migration, or a deploy stops for the sake of a diagnostic.
    try:
        rows = bind.execute(
            sa.text(
                "SELECT email, role, tenant_id FROM users WHERE can_send_invoices = true"
            )
        ).fetchall()
        if rows:
            logger.warning(
                "BE Gap 720: dropping users.can_send_invoices. %d user(s) held it "
                "and will now rely on can_load + the tenant's Send Invoices toggle "
                "to prepare an outbound invoice, and on can_audit to send it: %s",
                len(rows),
                "; ".join(f"{r[0]} (role={r[1]}, tenant={r[2]})" for r in rows),
            )
        else:
            logger.info(
                "BE Gap 720: dropping users.can_send_invoices. No user held it."
            )
    except Exception as exc:  # pragma: no cover - diagnostics only
        logger.warning("BE Gap 720: could not list holders before the drop: %s", exc)

    op.drop_column("users", "can_send_invoices")


def downgrade() -> None:
    # Restores the SHAPE, not the grants: every row comes back False, which is
    # the same fail-closed default Gap 405's own migration (dfcfbb60ef1c) chose.
    # Re-granting is manual, from the list `upgrade()` logged.
    op.add_column(
        "users",
        sa.Column(
            "can_send_invoices",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
