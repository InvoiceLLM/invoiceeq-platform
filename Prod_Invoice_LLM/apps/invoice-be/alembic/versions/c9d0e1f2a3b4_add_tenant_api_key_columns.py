"""add API key columns to tenant (Gap 184: programmatic API authentication)

Revision ID: c9d0e1f2a3b4
Revises: f9a0b1c2d3e4
Create Date: 2026-08-12

Gap 184. The `inv_live_...` key on the frontend Security settings page was a
hardcoded string that the page also "rotated" client-side with Math.random() --
no backend concept of an API key existed at all. These columns are that concept.

Deliberately hash-only: `api_key_hash` holds a PBKDF2-HMAC-SHA256 digest derived
from the raw key with the per-key random `api_key_salt`, so the raw key is not
recoverable from the database. `api_key_prefix` is the non-secret leading slice
(`inv_live_` + 6 chars) the UI displays to identify which key is live.

All five are nullable with no server_default and no backfill: NULL means "this
tenant has never issued a key", which is true of every existing row. Generating
keys for existing tenants at migration time would create credentials nobody
asked for and that nobody can ever read (the raw value is only ever returned in
the rotate response), so issuance stays an explicit Admin action.

down_revision is f9a0b1c2d3e4 (add_submitted_by_email_to_invoice), the single
*committed* head at time of writing -- see be_features_tracker.md Gap 60 for the
multi-head incident this guards against.

CAUTION, unresolved at time of writing: other in-flight (uncommitted) work in
this same working tree adds migrations that ALSO chain off f9a0b1c2d3e4, so
there are three sibling branches off that node, not one line:
  * c1d2e3f4a5b6 (add_invoice_overdue_notified_at)
  * a2b3c4d5e6f7 (declared inside d3e4f5a6b7c8_add_dropped_inbound_emails.py --
    that file's name and its `revision` value disagree), which
    b8c1d4e7f209 (add_webhook_delivery_logs) then chains off
  * c9d0e1f2a3b4 (this one)
Whoever lands these together must re-chain them into a single line (or add a
merge revision) before running `alembic upgrade head`, or Alembic will refuse
with multiple heads. That serialisation is deliberately NOT done here --
reordering another checkpoint's migration is not this change's call to make.

This revision was itself renamed from a2b3c4d5e6f7 (which collided with the
dropped-inbound-emails migration) to c9d0e1f2a3b4; both the filename and the
`revision` value below were updated, since changing only one is precisely the
mismatch noted above.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenant", sa.Column("api_key_hash", sa.String(length=255), nullable=True))
    op.add_column("tenant", sa.Column("api_key_salt", sa.String(length=64), nullable=True))
    op.add_column("tenant", sa.Column("api_key_prefix", sa.String(length=32), nullable=True))
    op.add_column("tenant", sa.Column("api_key_rotated_at", sa.DateTime(), nullable=True))
    op.add_column("tenant", sa.Column("api_key_last_used_at", sa.DateTime(), nullable=True))
    # Lookup index: authenticating a request finds the candidate tenant by the
    # non-secret prefix, then verifies the hash. Without it every API-key
    # request would be a full table scan of `tenant`.
    op.create_index("ix_tenant_api_key_prefix", "tenant", ["api_key_prefix"])


def downgrade() -> None:
    op.drop_index("ix_tenant_api_key_prefix", table_name="tenant")
    op.drop_column("tenant", "api_key_last_used_at")
    op.drop_column("tenant", "api_key_rotated_at")
    op.drop_column("tenant", "api_key_prefix")
    op.drop_column("tenant", "api_key_salt")
    op.drop_column("tenant", "api_key_hash")
