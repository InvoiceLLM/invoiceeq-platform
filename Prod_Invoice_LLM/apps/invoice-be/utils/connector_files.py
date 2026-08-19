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


def list_salesforce_libraries(access_token: str, instance_url: str) -> list[dict]:
    """Gap 262: Returns Salesforce Libraries (ContentWorkspace) as folder nodes.

    Salesforce has no hierarchical folder system like Google Drive. Instead
    files live in "Libraries" (ContentWorkspace records). Returning these as
    selectable folder nodes gives FolderTreeExplorer something to navigate
    in folder-selection mode (Autopilot config tab). The user picks a Library
    as their source folder; subsequent browsing lists PDFs inside it.
    """
    query = (
        "SELECT Id, Name FROM ContentWorkspace "
        "WHERE CreatedById != null "
        "ORDER BY Name ASC LIMIT 50"
    )
    url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/query"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = httpx.get(url, params={"q": query}, headers=headers, timeout=10.0)
    response.raise_for_status()

    return [
        {
            "id": r["Id"],
            "name": r["Name"],
            "type": "folder",
            "size_bytes": 0,
        }
        for r in response.json().get("records", [])
    ]


def list_salesforce_files(access_token: str, instance_url: str, library_id: Optional[str] = None) -> list[dict]:
    """Lists PDF files visible to the connected user.

    Gap 262: if library_id is given, scopes the query to that Library
    via ContentDocumentLink (LinkedEntityId = library_id). Without it,
    falls back to a flat query across all accessible ContentVersion rows
    (original behaviour, used when browsing without a selected library).
    """
    if library_id:
        # Files linked to a specific Library
        query = (
            f"SELECT ContentDocument.Id, ContentDocument.Title, "
            f"ContentDocument.FileExtension, ContentDocument.ContentSize "
            f"FROM ContentDocumentLink "
            f"WHERE LinkedEntityId = '{library_id}' "
            f"AND ContentDocument.FileType = 'PDF' "
            f"ORDER BY ContentDocument.CreatedDate DESC LIMIT 100"
        )
        url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/query"
        headers = {"Authorization": f"Bearer {access_token}"}
        response = httpx.get(url, params={"q": query}, headers=headers, timeout=10.0)
        response.raise_for_status()
        return [
            {
                "id": r["ContentDocument"]["Id"],
                "name": (
                    f"{r['ContentDocument']['Title']}.{r['ContentDocument']['FileExtension']}"
                    if r["ContentDocument"].get("FileExtension")
                    else r["ContentDocument"]["Title"]
                ),
                "type": "file",
                "size_bytes": int(r["ContentDocument"].get("ContentSize") or 0),
            }
            for r in response.json().get("records", [])
        ]

    # No library selected — flat list across all accessible PDFs (original behaviour)
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


def verify_salesforce_instance(access_token: str, instance_url: str) -> None:
    """Cheapest authenticated call that proves an (access_token, instance_url)
    pair is actually usable before it is stored as an active connection
    (Gap 197): the versioned REST resource index for the org, which returns a
    small JSON map of available endpoints and requires a valid bearer token.

    Returns None on success. Raises `httpx.HTTPStatusError` if the org rejects
    the token (401/403) or the version path doesn't exist, and the other
    `httpx.HTTPError` subclasses if the host doesn't resolve/connect at all --
    the caller decides what to do with each.
    """
    url = f"{instance_url.rstrip('/')}/services/data/{SALESFORCE_API_VERSION}/"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = httpx.get(url, headers=headers, timeout=10.0)
    response.raise_for_status()


def download_salesforce_file(access_token: str, instance_url: str, file_id: str) -> bytes:
    """Downloads the raw bytes of a Salesforce File (ContentVersion.VersionData)."""
    url = f"{instance_url}/services/data/{SALESFORCE_API_VERSION}/sobjects/ContentVersion/{file_id}/VersionData"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = httpx.get(url, headers=headers, timeout=30.0)
    response.raise_for_status()
    return response.content
