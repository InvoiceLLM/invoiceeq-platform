"""Real file listing/download for connectors that have a live OAuth app
configured. Google Drive has been live-smoke-tested against the real API
(see feature_9_connectors.md); the Salesforce functions below are coded
against Salesforce's documented REST API but not yet exercised against a
real org -- no Connected App exists to test with (see
routers/connectors.py::has_real_credentials). Both stay gated behind that
same check, so neither runs for a tenant until real credentials exist.
"""
from typing import Optional

import httpx

GOOGLE_DRIVE_FILES_API = "https://www.googleapis.com/drive/v3/files"
SALESFORCE_API_VERSION = "v59.0"


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


def list_salesforce_files(access_token: str, instance_url: str) -> list[dict]:
    """Lists PDF files (Salesforce Files / ContentVersion) visible to the
    connected user. Salesforce has no folder hierarchy equivalent to Drive's
    (Files live in Libraries or attached to records instead), so this is a
    flat list -- folder_id from the router is intentionally not accepted
    here; a future pass can scope this to a chosen Library if needed.
    """
    query = (
        "SELECT Id, Title, FileExtension, ContentSize FROM ContentVersion "
        "WHERE FileType = 'PDF' AND IsLatest = true "
        "ORDER BY CreatedDate DESC LIMIT 100"
    )
    url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/query"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = httpx.get(url, params={"q": query}, headers=headers, timeout=10.0)
    response.raise_for_status()

    return [
        {
            "id": r["Id"],
            "name": f"{r['Title']}.{r['FileExtension']}" if r.get("FileExtension") else r["Title"],
            "type": "file",
            "size_bytes": int(r.get("ContentSize") or 0),
        }
        for r in response.json().get("records", [])
    ]


def download_salesforce_file(access_token: str, instance_url: str, file_id: str) -> bytes:
    """Downloads the raw bytes of a Salesforce File (ContentVersion.VersionData)."""
    url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/sobjects/ContentVersion/{file_id}/VersionData"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = httpx.get(url, headers=headers, timeout=30.0)
    response.raise_for_status()
    return response.content
