"""
Export all users, organizations, and org memberships from a Clerk account via
the Backend API, for migrating to a different Clerk account.

Why this exists: this app is switching which Clerk account it's linked to.
Clerk's Backend API has no built-in "export this account" button, and no
account-to-account transfer -- the only way to move data between two separate
Clerk accounts is to read it out of one via the API and recreate it in the
other via the API (see import_clerk_data.py, once the new account exists).

Hard limitation, not a bug in this script: Clerk never exposes password
hashes via the Backend API, to any caller, including the account owner. That
is a Clerk platform security boundary, not a permission this key is missing.
So this export can carry over identity (emails, names, org membership, roles,
metadata) but not the ability to log in with an existing password on the new
account -- users get a password-reset/magic-link email on first login there
instead. Confirmed acceptable for this migration.

Also carries over: each user's and org's *current* Clerk ID, captured
specifically so import_clerk_data.py's companion step can build an
old-id -> new-id map and this app's own Postgres rows (tenant.clerk_org_id,
users.clerk_user_id) can be repointed at the new account after import --
Clerk assigns fresh IDs on create, it does not let you choose them.

Usage:
    uv run python scripts/export_clerk_data.py
    uv run python scripts/export_clerk_data.py --secret-key sk_test_xxx --output /path/to/export.json
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CLERK_API_BASE = "https://api.clerk.com/v1"
PAGE_SIZE = 100

# infra/params.dev.secrets.json lives two levels above apps/invoice-be/scripts/
DEFAULT_SECRETS_FILE = Path(__file__).resolve().parents[3] / "infra" / "params.dev.secrets.json"


def load_secret_key(explicit: str | None) -> str:
    """Resolves the Clerk secret key: --secret-key, then CLERK_SECRET_KEY env, then the dev secrets file."""
    if explicit:
        return explicit
    if os.environ.get("CLERK_SECRET_KEY"):
        return os.environ["CLERK_SECRET_KEY"]
    if DEFAULT_SECRETS_FILE.exists():
        data = json.loads(DEFAULT_SECRETS_FILE.read_text())
        # ARM parameters file: each value is {"value": "..."}, not a raw string.
        entry = data.get("parameters", data).get("clerkSecretKey")
        key = entry.get("value") if isinstance(entry, dict) else entry
        if key:
            logger.info("Using clerkSecretKey from %s", DEFAULT_SECRETS_FILE)
            return key
    raise SystemExit(
        "No Clerk secret key found. Pass --secret-key, set CLERK_SECRET_KEY, "
        f"or ensure {DEFAULT_SECRETS_FILE} has a clerkSecretKey."
    )


def paginate(session: requests.Session, path: str, params: dict | None = None) -> list[dict]:
    """Pages through a Clerk list endpoint using limit/offset until a short page ends it."""
    items: list[dict] = []
    offset = 0
    while True:
        resp = session.get(
            f"{CLERK_API_BASE}{path}",
            params={**(params or {}), "limit": PAGE_SIZE, "offset": offset},
        )
        resp.raise_for_status()
        body = resp.json()
        # Clerk list endpoints return either a bare array or {"data": [...]}.
        page = body if isinstance(body, list) else body.get("data", [])
        items.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return items


def export_users(session: requests.Session) -> list[dict]:
    users = paginate(session, "/users")
    logger.info("Fetched %d user(s).", len(users))
    return [
        {
            "id": u["id"],
            "email_addresses": [e["email_address"] for e in u.get("email_addresses", [])],
            "primary_email_address_id": u.get("primary_email_address_id"),
            "first_name": u.get("first_name"),
            "last_name": u.get("last_name"),
            "username": u.get("username"),
            "public_metadata": u.get("public_metadata", {}),
            "private_metadata": u.get("private_metadata", {}),
            "unsafe_metadata": u.get("unsafe_metadata", {}),
            "created_at": u.get("created_at"),
        }
        for u in users
    ]


def export_organizations(session: requests.Session) -> list[dict]:
    orgs = paginate(session, "/organizations")
    logger.info("Fetched %d organization(s).", len(orgs))
    result = []
    for org in orgs:
        memberships = paginate(session, f"/organizations/{org['id']}/memberships")
        result.append(
            {
                "id": org["id"],
                "name": org.get("name"),
                "slug": org.get("slug"),
                "public_metadata": org.get("public_metadata", {}),
                "private_metadata": org.get("private_metadata", {}),
                "created_at": org.get("created_at"),
                "memberships": [
                    {
                        "user_id": m.get("public_user_data", {}).get("user_id"),
                        "email_address": m.get("public_user_data", {}).get("identifier"),
                        "role": m.get("role"),
                    }
                    for m in memberships
                ],
            }
        )
        logger.info("  org %s (%s): %d membership(s).", org.get("name"), org["id"], len(memberships))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Clerk users/organizations/memberships to JSON.")
    parser.add_argument("--secret-key", help="Clerk secret key. Defaults to CLERK_SECRET_KEY env or infra/params.dev.secrets.json.")
    parser.add_argument("--output", help="Output JSON file path. Defaults to a timestamped file next to this script.")
    args = parser.parse_args()

    secret_key = load_secret_key(args.secret_key)
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {secret_key}"})

    users = export_users(session)
    organizations = export_organizations(session)

    export = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "note": "Password hashes are never included -- Clerk does not expose them via the Backend API. "
                "Users must reset their password (or use passwordless/OTP) on first login after import.",
        "users": users,
        "organizations": organizations,
    }

    output_path = Path(args.output) if args.output else Path(__file__).parent / f"clerk_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.write_text(json.dumps(export, indent=2))

    logger.info(
        "Wrote export: %d user(s), %d organization(s) -> %s",
        len(users), len(organizations), output_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
