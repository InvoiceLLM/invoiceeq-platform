"""Real file listing/download for connectors that have a live OAuth app
configured. Google Drive has been live-smoke-tested against the real API
(see feature_9_connectors.md) and stays gated behind
routers/connectors.py::has_real_credentials, so it does not run for a
tenant until real credentials exist.

Salesforce (`list_salesforce_libraries`/`list_salesforce_files`/
`verify_salesforce_instance`/`download_salesforce_file`, plus
`SALESFORCE_API_VERSION`) was removed 2026-08-28 -- see Gap 334. Google
Drive is now the only connector.
"""
from typing import Optional

import httpx

GOOGLE_DRIVE_FILES_API = "https://www.googleapis.com/drive/v3/files"


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
