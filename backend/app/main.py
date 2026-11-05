from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.webhooks import capture as webhook_capture
from app.webhooks.router import router as webhook_router
from app import db
from app.config import get_app_settings
from app.routers import (
    agents,
    ai_settings,
    backup,
    data_export,
    focus,
    habits,
    insights,
    journal,
    lists,
    preferences,
    scores,
    search,
    tasks,
    time_blocks,
    calendar,
    calendar_connections,
    calendar_imports,
)


@asynccontextmanager
async def lifespan(application: FastAPI):
    if not db.engine_initialized():  # tests pre-initialise an in-memory engine
        settings = get_app_settings()
        db.init_engine(f"sqlite+aiosqlite:///{settings.journal_db_path}")
    worker = None
    calendar_worker = None
    webhook_worker = None
    try:
        await db.init_db()
        from app.calendar_sync.connections import require_verification_on_startup
        from app.calendar_sync.dependencies import create_manager

        application.state.calendar_connection_manager = create_manager(db.get_engine())
        async with db.get_sessionmaker()() as session:
            await require_verification_on_startup(session)
        from app import search

        async with db.get_sessionmaker()() as session:
            await search.backfill_missing(session)
        if get_app_settings().journal_scheduled_reviews:
            from app.review_scheduler import serve

            worker = asyncio.create_task(serve(db.get_sessionmaker()))
        from app.calendar_sync.queue_worker import QueueWorker, serve as serve_calendar

        application.state.calendar_queue_worker = QueueWorker(
            db.get_sessionmaker(), application.state.calendar_connection_manager,
        )

        calendar_worker = asyncio.create_task(serve_calendar(
            db.get_sessionmaker(), application.state.calendar_connection_manager,
            worker=application.state.calendar_queue_worker,
        ))
        from app.webhooks.service import create_service, serve as serve_webhooks

        application.state.webhook_service = create_service(db.get_engine(), db.get_sessionmaker())
        webhook_worker = asyncio.create_task(serve_webhooks(application.state.webhook_service))
        yield
    finally:
        workers = [task for task in (worker, calendar_worker, webhook_worker) if task is not None]
        for task in workers:
            task.cancel()
        try:
            await asyncio.gather(*workers, return_exceptions=True)
        finally:
            from app.search import shutdown_embeddings

            try:
                await shutdown_embeddings()
            finally:
                await db.dispose_engine()


app = FastAPI(title="Journal API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost", "http://tauri.localhost"],
    # dev servers may drift ports (5173 busy -> 5174, ...); allow any localhost port
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    webhook_router,
    backup.router,
    data_export.router,
    lists.router,
    tasks.router,
    time_blocks.router,
    calendar.router,
    calendar_connections.router,
    calendar_imports.router,
    focus.router,
    habits.router,
    journal.router,
    scores.router,
    ai_settings.router,
    agents.router,
    search.router,
    insights.router,
    preferences.router,
):
    app.include_router(router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
