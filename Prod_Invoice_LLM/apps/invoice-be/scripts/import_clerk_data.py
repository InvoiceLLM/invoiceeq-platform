"""
Import users, organizations, and org memberships (as produced by
export_clerk_data.py) into a *different* Clerk account, as part of switching
which Clerk account this app is linked to.

Order matters: Clerk's `POST /v1/organizations` requires an existing
`created_by` user id, so every user is created first, then every
organization (created by whichever of its old members has the admin/owner
role, or its first member if none do), then every remaining membership is
added to the now-existing organization.

Hard limitation carried over from export_clerk_data.py: password hashes are
never in the export (Clerk doesn't expose them via API to anyone), so every
imported user is created via `skip_password_requirement` -- they get a
Clerk password-reset/magic-link email on first login on the new account,
they do not keep their old password.

IDs change on import -- Clerk assigns fresh ids, it does not let you choose
them. This script writes an old-id -> new-id map alongside the import so
this app's own Postgres rows (tenant.clerk_org_id, users.clerk_user_id) can
be repointed afterwards.

Usage:
    uv run python scripts/import_clerk_data.py --input scripts/clerk_export_20260807_191255.json
    uv run python scripts/import_clerk_data.py --input <export.json> --dry-run
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
DEFAULT_SECRETS_FILE = Path(__file__).resolve().parents[3] / "infra" / "params.dev.secrets.json"

# Roles Clerk treats as org-admin-equivalent -- whichever old member held one
# of these becomes the new org's created_by (Clerk requires an existing user
# to create an organization; there is no "create with no owner").
ADMIN_ROLES = {"org:admin", "admin"}


def load_secret_key(explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get("CLERK_SECRET_KEY"):
        return os.environ["CLERK_SECRET_KEY"]
    if DEFAULT_SECRETS_FILE.exists():
        data = json.loads(DEFAULT_SECRETS_FILE.read_text())
        entry = data.get("parameters", data).get("clerkSecretKey")
        key = entry.get("value") if isinstance(entry, dict) else entry
        if key:
            logger.info("Using clerkSecretKey from %s", DEFAULT_SECRETS_FILE)
            return key
    raise SystemExit(
        "No Clerk secret key found. Pass --secret-key, set CLERK_SECRET_KEY, "
        f"or ensure {DEFAULT_SECRETS_FILE} has a clerkSecretKey."
    )


def create_user(session: requests.Session, user: dict, dry_run: bool) -> str | None:
    emails = user.get("email_addresses") or []
    if not emails:
        logger.warning("Skipping user %s: no email address in export.", user["id"])
        return None

    payload = {
        "email_address": emails,
        "skip_password_requirement": True,
        "skip_password_checks": True,
    }
    if user.get("first_name"):
        payload["first_name"] = user["first_name"]
    if user.get("last_name"):
        payload["last_name"] = user["last_name"]
    if user.get("username"):
        payload["username"] = user["username"]
    if user.get("public_metadata"):
        payload["public_metadata"] = user["public_metadata"]
    if user.get("private_metadata"):
        payload["private_metadata"] = user["private_metadata"]
    if user.get("unsafe_metadata"):
        payload["unsafe_metadata"] = user["unsafe_metadata"]

    if dry_run:
        logger.info("[dry-run] would create user %s (%s)", user["id"], emails[0])
        return None

    resp = session.post(f"{CLERK_API_BASE}/users", json=payload)
    if resp.status_code >= 400:
        logger.error("Failed to create user %s (%s): %s %s", user["id"], emails[0], resp.status_code, resp.text)
        return None
    new_id = resp.json()["id"]
    logger.info("Created user %s (%s) -> %s", user["id"], emails[0], new_id)
    return new_id


def create_organization(session: requests.Session, org: dict, user_id_map: dict[str, str], dry_run: bool) -> str | None:
    memberships = org.get("memberships", [])
    creator_old_id = next(
        (m["user_id"] for m in memberships if m.get("role") in ADMIN_ROLES and m.get("user_id") in user_id_map),
        None,
    ) or next((m["user_id"] for m in memberships if m.get("user_id") in user_id_map), None)

    if not creator_old_id:
        logger.warning("Skipping org %s (%s): no importable member to act as creator.", org["id"], org.get("name"))
        return None

    creator_new_id = user_id_map[creator_old_id]
    payload = {"name": org.get("name") or org["id"], "created_by": creator_new_id}
    if org.get("public_metadata"):
        payload["public_metadata"] = org["public_metadata"]
    if org.get("private_metadata"):
        payload["private_metadata"] = org["private_metadata"]

    if dry_run:
        logger.info("[dry-run] would create org %s (%s), created_by=%s", org["id"], org.get("name"), creator_new_id)
        return None

    resp = session.post(f"{CLERK_API_BASE}/organizations", json=payload)
    if resp.status_code >= 400:
        logger.error("Failed to create org %s (%s): %s %s", org["id"], org.get("name"), resp.status_code, resp.text)
        return None
    new_org_id = resp.json()["id"]
    logger.info("Created org %s (%s) -> %s, creator %s", org["id"], org.get("name"), new_org_id, creator_new_id)

    # The creator is auto-added as an admin member by Clerk; add everyone else.
    for m in memberships:
        old_user_id = m.get("user_id")
        if old_user_id == creator_old_id or old_user_id not in user_id_map:
            continue
        add_membership(session, new_org_id, user_id_map[old_user_id], m.get("role") or "org:member", org["id"], old_user_id)

    return new_org_id


def add_membership(session: requests.Session, new_org_id: str, new_user_id: str, role: str, old_org_id: str, old_user_id: str) -> None:
    resp = session.post(
        f"{CLERK_API_BASE}/organizations/{new_org_id}/memberships",
        json={"user_id": new_user_id, "role": role},
    )
    if resp.status_code >= 400:
        logger.error(
            "Failed to add membership org=%s user=%s role=%s: %s %s",
            old_org_id, old_user_id, role, resp.status_code, resp.text,
        )
        return
    logger.info("  added membership: org %s <- user %s (role=%s)", old_org_id, old_user_id, role)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Clerk users/organizations/memberships from an export_clerk_data.py JSON file.")
    parser.add_argument("--input", required=True, help="Path to the export JSON file.")
    parser.add_argument("--secret-key", help="Clerk secret key for the TARGET account. Defaults to CLERK_SECRET_KEY env or infra/params.dev.secrets.json.")
    parser.add_argument("--output", help="Where to write the old-id -> new-id map. Defaults to a timestamped file next to this script.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be created without writing anything.")
    args = parser.parse_args()

    export = json.loads(Path(args.input).read_text())
    secret_key = load_secret_key(args.secret_key)
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {secret_key}"})

    logger.info(
        "Importing %d user(s), %d organization(s) from %s (exported %s)",
        len(export["users"]), len(export["organizations"]), args.input, export.get("exported_at"),
    )

    user_id_map: dict[str, str] = {}
    for user in export["users"]:
        new_id = create_user(session, user, args.dry_run)
        if new_id:
            user_id_map[user["id"]] = new_id

    org_id_map: dict[str, str] = {}
    for org in export["organizations"]:
        new_id = create_organization(session, org, user_id_map, args.dry_run)
        if new_id:
            org_id_map[org["id"]] = new_id

    if args.dry_run:
        logger.info("[dry-run] complete, nothing written.")
        return 0

    mapping = {
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "source_export": args.input,
        "user_id_map": user_id_map,
        "org_id_map": org_id_map,
    }
    output_path = Path(args.output) if args.output else Path(__file__).parent / f"clerk_import_map_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.write_text(json.dumps(mapping, indent=2))

    logger.info(
        "Done: %d/%d user(s), %d/%d organization(s) imported. ID map -> %s",
        len(user_id_map), len(export["users"]), len(org_id_map), len(export["organizations"]), output_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
