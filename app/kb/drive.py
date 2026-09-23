"""Lecture d'un Drive partagé (lecture seule) pour la base de connaissances."""

import logging
import time
from typing import Any

import httpx

from app.kb.types import DriveFile

logger = logging.getLogger(__name__)

DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
FOLDER_MIME = "application/vnd.google-apps.folder"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Fichiers Google natifs : pas de binaire à télécharger, il faut les exporter.
GOOGLE_EXPORTS = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.spreadsheet": XLSX_MIME,
}

_FIELDS = "nextPageToken,files(id,name,mimeType,parents,modifiedTime,size,md5Checksum,webViewLink,trashed)"


class DriveError(RuntimeError):
    pass


class DriveClient:
    def __init__(self, drive_id: str) -> None:
        self._drive_id = drive_id
        self._credentials = None

    def _token(self) -> str:
        import google.auth
        import google.auth.transport.requests

        if self._credentials is None:
            self._credentials, _ = google.auth.default(scopes=[DRIVE_SCOPE])
        if not self._credentials.valid:
            self._credentials.refresh(google.auth.transport.requests.Request())
        return self._credentials.token

    def _get(self, url: str, params: dict[str, Any]) -> httpx.Response:
        last: httpx.Response | None = None
        for attempt in range(4):
            with httpx.Client(timeout=120.0) as client:
                last = client.get(url, params=params, headers={"Authorization": f"Bearer {self._token()}"})
            if last.status_code not in (429, 500, 502, 503, 504):
                break
            time.sleep(2**attempt)
        assert last is not None
        if last.is_error:
            raise DriveError(f"Drive {last.status_code}: {last.text[:300]}")
        return last

    def list_files(self) -> list[DriveFile]:
        """Tous les fichiers du Drive partagé (sous-dossiers compris), hors corbeille."""
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "corpora": "drive",
                "driveId": self._drive_id,
                "includeItemsFromAllDrives": "true",
                "supportsAllDrives": "true",
                "q": "trashed=false",
                "pageSize": 1000,
                "fields": _FIELDS,
            }
            if page_token:
                params["pageToken"] = page_token
            data = self._get(f"{DRIVE_API}/files", params).json()
            items += data.get("files", [])
            page_token = data.get("nextPageToken")
            if not page_token:
                break

        by_id = {item["id"]: item for item in items}

        def path_of(item: dict[str, Any]) -> str:
            parts: list[str] = []
            seen: set[str] = set()
            current: dict[str, Any] | None = item
            while current is not None and current["id"] not in seen:
                seen.add(current["id"])
                parts.append(current["name"])
                parent_id = (current.get("parents") or [None])[0]
                current = by_id.get(parent_id) if parent_id else None
            return "/".join(reversed(parts))

        files = [
            DriveFile(
                id=item["id"],
                name=item["name"],
                mime_type=item["mimeType"],
                path=path_of(item),
                modified_time=item.get("modifiedTime", ""),
                web_link=item.get("webViewLink") or f"https://drive.google.com/file/d/{item['id']}/view",
                md5=item.get("md5Checksum"),
                size=int(item["size"]) if item.get("size") else None,
            )
            for item in items
            if item["mimeType"] != FOLDER_MIME
        ]
        return sorted(files, key=lambda f: f.path)

    def fetch(self, file: DriveFile) -> tuple[bytes, str]:
        """Contenu du fichier et type MIME effectif (celui de l'export pour un fichier Google)."""
        export_mime = GOOGLE_EXPORTS.get(file.mime_type)
        if export_mime:
            response = self._get(
                f"{DRIVE_API}/files/{file.id}/export",
                {"mimeType": export_mime, "supportsAllDrives": "true"},
            )
            return response.content, export_mime
        response = self._get(f"{DRIVE_API}/files/{file.id}", {"alt": "media", "supportsAllDrives": "true"})
        return response.content, file.mime_type
