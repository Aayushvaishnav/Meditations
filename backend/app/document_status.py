"""Read-only indexing receipts for the current persisted journal document."""

from __future__ import annotations

from datetime import date as Date, datetime
from typing import Literal

from sqlalchemy import text
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.search import journal_doc_id, vec_available


class JournalDocumentStatus(SQLModel):
    date: Date
    entry_exists: bool
    updated_at: datetime | None
    keyword: Literal["ready", "missing", "not_applicable"]
    semantic: Literal["ready", "missing", "unavailable", "not_applicable"]


async def journal_document_status(
    session: AsyncSession, day: Date,
) -> JournalDocumentStatus:
    available = vec_available()
    # One statement gives source and receipts the same SQLite read snapshot
    vector_exists = (
        "EXISTS (SELECT 1 FROM vec_entries WHERE doc_id = :doc_id)"
        if available else "0"
    )
    row = (await session.execute(text(f"""
        SELECT j.updated_at, j.raw_markdown,
            (SELECT count(*) FROM fts_entries WHERE doc_id = :doc_id) = 1
            AND EXISTS (
                SELECT 1 FROM fts_entries
                WHERE doc_id = :doc_id AND kind = 'journal' AND content = j.raw_markdown
            ) AS keyword_current,
            EXISTS (
                SELECT 1 FROM search_vector_state
                WHERE doc_id = :doc_id AND state = 'ready'
            ) AND {vector_exists} AS vector_current
        FROM journal_entries AS j WHERE j.date = :day
    """), {"doc_id": journal_doc_id(day), "day": day.isoformat()})).first()
    status = JournalDocumentStatus(
        date=day,
        entry_exists=row is not None,
        updated_at=row.updated_at if row is not None else None,
        keyword="not_applicable",
        semantic="not_applicable",
    )
    if row is None or not row.raw_markdown.strip():
        return status

    status.keyword = "ready" if row.keyword_current else "missing"
    if not available:
        status.semantic = "unavailable"
    else:
        # Vectors have no content field; FTS and the receipt establish freshness
        status.semantic = "ready" if row.keyword_current and row.vector_current else "missing"
    return status
