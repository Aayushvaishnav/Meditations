from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter
from starlette.background import BackgroundTask
from starlette.responses import FileResponse
from starlette.types import Receive, Scope, Send

from app import db
from app.backup import create_backup

router = APIRouter(prefix="/api/backup", tags=["backup"])


class BackupResponse(FileResponse):
    def __init__(self, directory: TemporaryDirectory, filename: str) -> None:
        self.directory = directory
        super().__init__(
            Path(directory.name) / "backup.db",
            media_type="application/vnd.sqlite3",
            filename=filename,
            headers={"Cache-Control": "no-store"},
            background=BackgroundTask(directory.cleanup),
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.directory.cleanup()


@router.post(
    "",
    response_class=FileResponse,
    description=(
        "Download a complete SQLite backup, including app_settings and stored provider "
        "credentials. Treat the downloaded file as sensitive. No filesystem paths are accepted."
    ),
)
async def download_backup() -> FileResponse:
    directory = TemporaryDirectory(prefix="journal-backup-")
    try:
        await create_backup(db.get_engine(), Path(directory.name) / "backup.db")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return BackupResponse(directory, f"journal-backup-{timestamp}.db")
    except BaseException:
        directory.cleanup()
        raise
