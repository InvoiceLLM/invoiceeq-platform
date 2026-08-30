"""Real file listing/download/upload for connectors that have a live OAuth
app configured. Google Drive has been live-smoke-tested against the real API
(see feature_9_connectors.md) and stays gated behind
routers/connectors.py::has_real_credentials, so it does not run for a
tenant until real credentials exist.

Salesforce (`list_salesforce_libraries`/`list_salesforce_files`/
`verify_salesforce_instance`/`download_salesforce_file`, plus
`SALESFORCE_API_VERSION`) was removed 2026-08-28 -- see Gap 334. Google
Drive is now the only connector.

Gap 338 (2026-08-30) added the write direction -- `upload_google_drive_file`
and `find_or_create_google_drive_folder` -- for the `drive_archive` output
destination. Read the folder note on that function before changing it: what
this app may write to is constrained by the `drive.file` scope, not by what
the user can see in their own Drive.
"""
import json
from typing import Optional
from uuid import uuid4

import httpx

GOOGLE_DRIVE_FILES_API = "https://www.googleapis.com/drive/v3/files"
# Uploads go to a different host path than metadata calls (Google's
# documented /upload prefix); posting bytes to the plain files endpoint
# silently creates an empty file with the right name, which is worse than an
# error.
GOOGLE_DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
GOOGLE_DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


def list_google_drive_files(access_token: str, folder_id: Optional[str] = None) -> list[dict]:
    """Lists PDFs and folders directly under folder_id (or the Drive root)."""
    parent = folder_id or "root"
    query = (
        "trashed = false and "
        "(mimeType = 'application/pdf' or mimeType = 'application/vnd.google-apps.folder') and "
        f"'{parent}' in parents"
    )
    params = {"q": query, "fields": "files(id,name,mimeType,size)", "pageSize": 100}
    headers = {"Authorization": f"Bearer {access_token}"}

    response = httpx.get(GOOGLE_DRIVE_FILES_API, params=params, headers=headers, timeout=10.0)
    response.raise_for_status()

    return [
        {
            "id": f["id"],
            "name": f["name"],
            "type": "folder" if f["mimeType"] == "application/vnd.google-apps.folder" else "file",
            "size_bytes": int(f.get("size", 0)),
        }
        for f in response.json().get("files", [])
    ]


def download_google_drive_file(access_token: str, file_id: str) -> bytes:
    """Downloads the raw bytes of a Drive file via alt=media."""
    url = f"{GOOGLE_DRIVE_FILES_API}/{file_id}"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = httpx.get(url, params={"alt": "media"}, headers=headers, timeout=30.0)
    response.raise_for_status()
    return response.content


def upload_google_drive_file(
    access_token: str,
    folder_id: Optional[str],
    filename: str,
    content_bytes: bytes,
    mime_type: str,
) -> dict:
    """Creates a new Drive file with these bytes, in `folder_id` (or My Drive).

    Gap 338. One request, using Google's `multipart/related` upload form: the
    JSON metadata part and the media part travel together, so there is no
    window in which a named-but-empty file exists. (The two-step
    create-then-PATCH-media alternative has exactly that window, and a failure
    in its second half leaves a 0-byte file in the tenant's Drive that looks
    like a successful archive.)

    Always creates -- never updates in place. Two approvals of the same
    invoice therefore leave two dated files rather than one silently
    overwritten; an archive that can lose an earlier version is not an
    archive. `name` is not unique in Drive, so this needs no de-duplication
    call.

    Raises `httpx.HTTPStatusError` on a non-2xx, which is how the caller
    learns about an inadequate scope (403) or a revoked token (401). It is
    deliberately not swallowed here -- see
    services/workflow_outputs.py::deliver_drive_archive(), which is the layer
    that must never raise.
    """
    metadata: dict = {"name": filename}
    if folder_id:
        metadata["parents"] = [folder_id]

    boundary = f"invoiceeq{uuid4().hex}"
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        b"Content-Type: application/json; charset=UTF-8\r\n\r\n",
        json.dumps(metadata).encode("utf-8"),
        f"\r\n--{boundary}\r\n".encode(),
        f"Content-Type: {mime_type}\r\n\r\n".encode(),
        content_bytes,
        f"\r\n--{boundary}--\r\n".encode(),
    ])

    response = httpx.post(
        GOOGLE_DRIVE_UPLOAD_API,
        params={"uploadType": "multipart", "fields": "id,name,webViewLink"},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        content=body,
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()


def find_or_create_google_drive_folder(
    access_token: str, name: str, parent_id: Optional[str] = None
) -> str:
    """Returns the id of the app's own folder called `name`, creating it once.

    **Why the archive gets its own folder instead of writing into the folder
    the tenant already picked for ingestion.** The write scope this app asks
    for is `drive.file`, which grants access only to files this app created.
    A folder the *user* created -- the one they chose in the connector
    browser, or `TenantAutopilotConfig.source_ref` -- is not app-created, so
    naming it as a `parents` entry is rejected by Drive. The alternative would
    be requesting the bare `drive` scope, i.e. asking every tenant for
    read/write access to the whole of their Drive in order to drop two files
    in it. That trade was refused; a dedicated app-owned folder is the cost of
    the narrower scope, and it is the right cost.

    The lookup uses `files.list`, which under `drive.file` returns only
    app-accessible files -- so this can only ever find a folder this app made,
    never shadow a user folder of the same name. `createdTime asc` makes the
    choice deterministic if two concurrent approvals ever race and create two.
    """
    query = (
        f"name = '{name}' and mimeType = '{GOOGLE_DRIVE_FOLDER_MIME_TYPE}' "
        "and trashed = false"
    )
    if parent_id:
        query += f" and '{parent_id}' in parents"

    headers = {"Authorization": f"Bearer {access_token}"}
    response = httpx.get(
        GOOGLE_DRIVE_FILES_API,
        params={
            "q": query,
            "fields": "files(id,name)",
            "orderBy": "createdTime",
            "pageSize": 10,
        },
        headers=headers,
        timeout=10.0,
    )
    response.raise_for_status()
    existing = response.json().get("files") or []
    if existing:
        return existing[0]["id"]

    metadata: dict = {"name": name, "mimeType": GOOGLE_DRIVE_FOLDER_MIME_TYPE}
    if parent_id:
        metadata["parents"] = [parent_id]
    created = httpx.post(
        GOOGLE_DRIVE_FILES_API,
        params={"fields": "id,name"},
        headers=headers,
        json=metadata,
        timeout=10.0,
    )
    created.raise_for_status()
    return created.json()["id"]
