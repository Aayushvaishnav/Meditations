"""Transactional capture; no network or vault access on source writes."""

import json
from typing import Any
from datetime import date, datetime

from sqlalchemy import event, inspect, select, text
from sqlalchemy.orm import Session

from app.models import (
    Task,
    TimeBlock,
    WebhookEndpoint,
    WebhookDelivery,
    new_id,
    utc_now,
)


def scalar(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    if isinstance(value, date):
        return value.isoformat()
    return value


def enqueue(
    session: Session,
    kind: str,
    entity: Task | TimeBlock,
    task: Task,
    endpoints: list[WebhookEndpoint],
) -> None:
    key = ("task:" if isinstance(entity, Task) else "time_block:") + entity.id
    version = session.execute(
        text(
            "INSERT INTO webhook_versions(entity_id,version) VALUES (:id,1) "
            "ON CONFLICT(entity_id) DO UPDATE SET version=version+1 RETURNING version"
        ),
        {"id": key},
    ).scalar_one()
    event_id = new_id()
    fields = (
        ("id", "list_id", "status", "due_date", "deadline_date", "completed_at")
        if isinstance(entity, Task)
        else (
            "id",
            "task_id",
            "kind",
            "timezone",
            "start_at",
            "end_at",
            "start_date",
            "end_date",
        )
    )
    data = {name: scalar(getattr(entity, name)) for name in fields}
    data["list_id"] = task.list_id
    if isinstance(entity, Task):
        data["deadline"] = (
            {"kind": "timed", "at": scalar(task.due_date)}
            if task.due_date
            else {"kind": "date", "date": scalar(task.deadline_date)}
            if task.deadline_date
            else {"kind": "none"}
        )
    occurred_at = scalar(utc_now())
    for endpoint in endpoints:
        scope = json.loads(endpoint.scope)
        if kind not in json.loads(endpoint.events):
            continue
        if scope["kind"] == "lists" and task.list_id not in scope["list_ids"]:
            continue
        payload = dict(data)
        if endpoint.include_titles:
            payload["title"] = task.title
        envelope = dict(
            schema_version=1,
            id=event_id,
            type=kind,
            entity_id=entity.id,
            entity_version=version,
            occurred_at=occurred_at,
            data=payload,
        )
        session.add(
            WebhookDelivery(
                endpoint_id=endpoint.id,
                event_id=event_id,
                event_type=kind,
                entity_id=entity.id,
                entity_version=version,
                payload=json.dumps(envelope, separators=(",", ":")),
            )
        )


@event.listens_for(Session, "before_flush")
def capture(session: Session, flush_context: Any, instances: Any) -> None:
    changed = list(session.new | session.dirty | session.deleted)
    if not any(isinstance(obj, (Task, TimeBlock)) for obj in changed):
        return
    if not inspect(session.connection()).has_table("webhook_endpoints"):
        return
    # Serialize endpoint selection with configuration changes before reading privacy policy
    session.execute(text("UPDATE webhook_endpoints SET enabled=enabled WHERE 0"))
    endpoints = session.scalars(
        select(WebhookEndpoint).where(WebhookEndpoint.enabled == True)
    ).all()
    # Include database-cascaded block deletions from recursive task deletion
    deleted_tasks = {obj.id: obj for obj in session.deleted if isinstance(obj, Task)}
    frontier = set(deleted_tasks)
    while frontier:
        children = session.scalars(
            select(Task).where(Task.parent_id.in_(frontier))
        ).all()
        frontier = {t.id for t in children} - deleted_tasks.keys()
        deleted_tasks.update({t.id: t for t in children})
    blocks = {obj.id: obj for obj in session.deleted if isinstance(obj, TimeBlock)}
    if deleted_tasks:
        blocks.update(
            {
                b.id: b
                for b in session.scalars(
                    select(TimeBlock).where(TimeBlock.task_id.in_(deleted_tasks))
                )
            }
        )
    for block in blocks.values():
        task = deleted_tasks.get(block.task_id) or session.get(Task, block.task_id)
        if task:
            enqueue(session, "time_block.deleted", block, task, endpoints)
    for obj in changed:
        if isinstance(obj, TimeBlock) and obj.id not in blocks:
            if obj in session.new or session.is_modified(
                obj, include_collections=False
            ):
                task = session.get(Task, obj.task_id) or next(
                    (
                        t
                        for t in session.new
                        if isinstance(t, Task) and t.id == obj.task_id
                    ),
                    None,
                )
                if task:
                    enqueue(
                        session,
                        "time_block.created"
                        if obj in session.new
                        else "time_block.updated",
                        obj,
                        task,
                        endpoints,
                    )
        elif (
            isinstance(obj, Task)
            and obj not in session.deleted
            and obj.status == "completed"
        ):
            if obj in session.new or inspect(obj).attrs.status.history.has_changes():
                enqueue(session, "task.completed", obj, obj, endpoints)
