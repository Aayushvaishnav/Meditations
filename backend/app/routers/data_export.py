from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter
from starlette.responses import FileResponse
from starlette.types import Receive, Scope, Send

from app import db
from app.data_export import create_export

router = APIRouter(prefix="/api/export", tags=["export"])


class ExportResponse(FileResponse):
    def __init__(self, directory: TemporaryDirectory, filename: str) -> None:
        self.directory = directory
        super().__init__(
            Path(directory.name) / "export.zip",
            media_type="application/zip",
            filename=filename,
            headers={"Cache-Control": "no-store"},
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Synchronous cleanup cannot be interrupted by async cancellation.
            self.directory.cleanup()


@router.post("", response_class=FileResponse)
async def download_export() -> FileResponse:
    directory = TemporaryDirectory(prefix="journal-export-")
    try:
        await create_export(db.get_engine(), Path(directory.name) / "export.zip")
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        return ExportResponse(directory, f"journal-export-{timestamp}.zip")
    except BaseException:
        directory.cleanup()
        raise
