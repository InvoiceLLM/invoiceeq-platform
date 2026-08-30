"""retire the "Viewer" role name (Feature 25 / Gap 337)

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-08-29

Data-only migration. Gap 337 makes the user-facing role vocabulary **Admin,
Auditor, Trainer** and moves the system's zero-permission fallback to its own
never-assignable name, `RoleMapper.NO_ROLE` == "Restricted".

`users.role` still holds the string 'Viewer' on every row written before this
change -- rows created by the Admin console's pre-provisioning path, by the
org-mismatch clamp, by the detach-on-remove path, and by Gap 335's synthetic
API-key service user. This rewrites those to 'Restricted'.

Why this is safe, and why it is nonetheless worth doing:

  * SAFE: nothing in the codebase authorises on `role == "Viewer"`. Permissions
    come from `RoleMapper.resolve_permissions()`, and both 'Viewer' (unmapped,
    falls to the NO_ROLE defaults) and 'Restricted' resolve to
    (can_train=False, can_audit=False, can_load=False). The only `role ==` checks
    in the product are against "Admin" (settings.py, billing.py, admin.py). So
    this changes a label, never an access decision -- verified by grep before
    writing.
  * WORTH DOING: without it the retired label survives in the database and keeps
    rendering in the Settings user list (`GET /api/v1/admin/users` returns
    `User.role` verbatim), which would make "Viewer" still visible to customers
    after the vocabulary was supposedly retired.

Deliberately NOT touched:
  * `audit_logs.actor_role` -- that is a historical record of the role an actor
    held *at the time they acted*. Rewriting history to match today's vocabulary
    is exactly what an audit trail must not do.
  * Any row whose role is Admin/Auditor/Trainer, or any other free-text value a
    third-party IDP may have produced (`normalize_role()` title-cases unknown
    strings). Only the exact literal 'Viewer' is in scope.

down_revision d8e9f0a1b2c3 confirmed as the single head by an actual
`alembic heads` run, not by reading files (this repo has had a multi-head
incident -- be_features_tracker.md Gap 60).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e9f0a1b2c3d4"
down_revision: Union[str, None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE users SET role = 'Restricted' WHERE role = 'Viewer'")
    )


def downgrade() -> None:
    # Exactly reversible: 'Restricted' did not exist as a stored value before
    # this migration, so every row carrying it here is one this migration wrote.
    op.execute(
        sa.text("UPDATE users SET role = 'Viewer' WHERE role = 'Restricted'")
    )
