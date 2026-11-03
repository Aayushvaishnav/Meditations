"""Outgoing automation privacy, transactions, lifecycle and offline delivery."""

import hashlib
import hmac
import json
from datetime import date

import httpx
import pytest
from sqlalchemy import select

from app import db
from app.main import app
from app.models import Task, TimeBlock, WebhookDelivery, WebhookVersion, utc_now
from app.webhooks.service import Service


class Vault:
    def __init__(self):
        self.values = {}
        self.calls = []

    async def put(self, key, value):
        self.calls.append(("put", key))
        self.values[key] = value

    async def get(self, key):
        self.calls.append(("get", key))
        return self.values.get(key)

    async def delete(self, key):
        self.calls.append(("delete", key))
        self.values.pop(key, None)


@pytest.fixture(autouse=True)
def idle_worker(monkeypatch):
    from app.webhooks import service
    import asyncio

    async def idle(svc):
        await asyncio.Event().wait()

    monkeypatch.setattr(service, "serve", idle)


@pytest.fixture
def configured(client):
    svc = app.state.webhook_service
    svc.store = Vault()
    return client, svc


def endpoint(client, **values):
    response = client.post(
        "/api/webhooks",
        json=dict(
            name="Workflow",
            url="http://127.0.0.1:9999/hook",
            secret="secret-canary",
            **values,
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()


def task(client, **values):
    r = client.post(
        "/api/tasks",
        json=dict(title="private-title", description="private-description", **values),
    )
    assert r.status_code == 201, r.text
    return r.json()


def block(client, task_id):
    r = client.post(
        "/api/time-blocks",
        json=dict(
            task_id=task_id,
            start_at="2026-11-01T10:00:00",
            end_at="2026-11-01T11:00:00",
        ),
    )
    assert r.status_code == 201, r.text
    return r.json()


def deliveries(client, ep):
    return client.get("/api/webhooks/" + ep["id"] + "/deliveries").json()


def run(client, operation):
    return client.portal.call(operation)


def test_capture_privacy_versions_cascades_and_no_vault_on_saves(configured):
    client, svc = configured
    ep = endpoint(client)
    t = task(client)
    child = task(client, parent_id=t["id"])
    b = block(client, child["id"])
    assert (
        client.patch(
            "/api/tasks/" + child["id"], json={"status": "completed"}
        ).status_code
        == 200
    )
    assert client.delete("/api/tasks/" + t["id"]).status_code == 204
    rows = deliveries(client, ep)
    assert {r["event_type"] for r in rows} == {
        "time_block.created",
        "time_block.deleted",
        "task.completed",
    }
    versions = sorted(r["entity_version"] for r in rows if r["entity_id"] == b["id"])
    assert versions == [1, 2]
    assert len(svc.store.calls) == 1

    async def check():
        async with db.get_sessionmaker()() as session:
            raw = "\n".join(
                d.payload for d in await session.scalars(select(WebhookDelivery))
            )
            assert "private-title" not in raw
            assert "private-description" not in raw
            assert "secret-canary" not in raw
            payload = json.loads(
                (
                    await session.scalars(
                        select(WebhookDelivery).where(
                            WebhookDelivery.event_type == "time_block.created"
                        )
                    )
                )
                .one()
                .payload
            )
            assert payload["schema_version"] == 1
            assert payload["data"]["kind"] == "timed"
            assert payload["data"]["start_at"].endswith("Z")

    run(client, check)


def test_scope_title_selection_and_list_delete(configured):
    client, svc = configured
    listing = client.post("/api/lists", json={"name": "One"}).json()
    ep = endpoint(
        client,
        scope={"kind": "lists", "list_ids": [listing["id"]]},
        include_titles=True,
        events=["time_block.deleted"],
    )
    block(client, task(client)["id"])
    block(client, task(client, list_id=listing["id"])["id"])
    assert deliveries(client, ep) == []
    assert client.delete("/api/lists/" + listing["id"]).status_code == 204
    assert deliveries(client, ep) == []
    assert len(client.get("/api/time-blocks").json()) == 2
    assert (
        client.delete(
            "/api/time-blocks/" + client.get("/api/time-blocks").json()[0]["id"]
        ).status_code
        == 204
    )
    assert deliveries(client, ep) == []


@pytest.mark.parametrize(
    "url",
    [
        "http://u:p@localhost/hook",
        "http://localhost/hook?token=canary",
        "https://localhost/#secret",
        "file:///tmp/a",
        "http://localhost:invalid",
    ],
)
def test_unsafe_urls_no_echo(configured, url):
    client, _ = configured
    response = client.post(
        "/api/webhooks", json={"name": "x", "url": url, "secret": "secret-canary"}
    )
    assert response.status_code == 422
    assert "canary" not in response.text


def test_validation_never_echoes_secret(configured):
    client, _ = configured
    response = client.post(
        "/api/webhooks", json={"name": "", "url": {}, "secret": "secret-canary"}
    )
    assert response.status_code == 422
    assert "secret-canary" not in response.text


def test_retry_restart_signature_and_safe_errors(configured):
    client, svc = configured
    ep = endpoint(client)
    block(client, task(client)["id"])
    sent = []

    def offline(request):
        sent.append(request)
        raise httpx.ConnectError("secret-canary private failure", request=request)

    svc.transport = httpx.MockTransport(offline)
    run(client, svc.tick)
    row = deliveries(client, ep)[0]
    assert row["state"] == "pending" and row["attempts"] == 1
    assert "secret-canary" not in row["last_error"]
    assert (
        client.post(
            f"/api/webhooks/{ep['id']}/deliveries/{row['id']}/retry"
        ).status_code
        == 200
    )

    def success(request):
        sent.append(request)
        timestamp = request.headers["X-Journal-Timestamp"]
        expected = hmac.new(
            b"secret-canary",
            timestamp.encode() + b"." + request.content,
            hashlib.sha256,
        ).hexdigest()
        assert request.headers["X-Journal-Signature"] == "sha256=" + expected
        return httpx.Response(204)

    restarted = Service(db.get_sessionmaker(), svc.store, httpx.MockTransport(success))
    run(client, restarted.tick)
    assert sent[0].content == sent[1].content
    assert (
        sent[0].headers["X-Journal-Event-Id"] == sent[1].headers["X-Journal-Event-Id"]
    )
    assert deliveries(client, ep)[0]["state"] == "delivered"


@pytest.mark.parametrize(
    "changes",
    [
        {"enabled": False},
        {"url": "http://localhost/new"},
        {"scope": {"kind": "lists", "list_ids": []}},
        {"include_titles": False},
        {"secret": "replacement"},
    ],
)
def test_configuration_cancels_old_private_payload(configured, changes):
    client, svc = configured
    ep = endpoint(client, include_titles=True)
    block(client, task(client)["id"])
    row = deliveries(client, ep)[0]
    response = client.patch("/api/webhooks/" + ep["id"], json=changes)
    assert response.status_code == 200, response.text
    assert deliveries(client, ep)[0]["state"] == "cancelled"
    assert (
        client.post(
            f"/api/webhooks/{ep['id']}/deliveries/{row['id']}/retry"
        ).status_code
        == 409
    )

    async def check():
        async with db.get_sessionmaker()() as session:
            assert (await session.get(WebhookDelivery, row["id"])).payload == "{}"

    run(client, check)


def test_test_delivery_removal_and_disabled(configured):
    client, svc = configured
    ep = endpoint(client)
    response = client.post("/api/webhooks/" + ep["id"] + "/test")
    assert response.status_code == 200
    assert response.json()["event_type"] == "webhook.test"
    assert client.delete("/api/webhooks/" + ep["id"]).status_code == 204
    assert svc.store.values == {}
    assert client.get("/api/webhooks").json() == []
    ep = endpoint(client, enabled=False)
    assert client.post("/api/webhooks/" + ep["id"] + "/test").status_code == 409


def test_transaction_rollback_and_all_day(configured):
    client, svc = configured
    ep = endpoint(client)
    t = task(client)

    async def rollback():
        async with db.get_sessionmaker()() as session:
            session.add(
                TimeBlock(
                    task_id=t["id"],
                    kind="all_day",
                    timezone=None,
                    start_date=date(2026, 11, 1),
                    end_date=date(2026, 11, 2),
                )
            )
            await session.flush()
            await session.rollback()
        async with db.get_sessionmaker()() as session:
            assert (await session.scalars(select(WebhookDelivery))).all() == []
            assert (await session.scalars(select(WebhookVersion))).all() == []

    run(client, rollback)
    r = client.post(
        "/api/time-blocks",
        json={
            "task_id": t["id"],
            "kind": "all_day",
            "start_date": "2026-11-01",
            "end_date": "2026-11-02",
        },
    )
    assert r.status_code == 201, r.text
    assert len(deliveries(client, ep)) == 1


def test_delivered_cannot_replay_old_private_payload(configured):
    client, svc = configured
    ep = endpoint(client, include_titles=True)
    block(client, task(client)["id"])
    sent = []

    def success(request):
        sent.append(request)
        return httpx.Response(200)

    svc.transport = httpx.MockTransport(success)
    run(client, svc.tick)
    row = deliveries(client, ep)[0]
    retry_url = f"/api/webhooks/{ep['id']}/deliveries/{row['id']}/retry"
    assert client.post(retry_url).status_code == 409
    assert (
        client.patch(
            "/api/webhooks/" + ep["id"],
            json={"include_titles": False, "url": "http://localhost/new"},
        ).status_code
        == 200
    )
    assert client.post(retry_url).status_code == 409
    run(client, svc.tick)
    assert len(sent) == 1


@pytest.mark.parametrize(
    "status,expected",
    [(302, "failed"), (400, "failed"), (429, "pending"), (503, "pending")],
)
def test_http_classification_and_no_response_echo(configured, status, expected):
    client, svc = configured
    ep = endpoint(client)
    client.post("/api/webhooks/" + ep["id"] + "/test")
    svc.transport = httpx.MockTransport(
        lambda request: httpx.Response(status, text="secret-canary")
    )
    run(client, svc.tick)
    row = deliveries(client, ep)[0]
    assert row["state"] == expected
    assert row["last_error"] == f"Endpoint returned HTTP {status}"


def test_creation_completed_recompletion_versions(configured):
    client, svc = configured
    ep = endpoint(client, events=["task.completed"])
    t = task(
        client, status="completed", deadline={"kind": "date", "date": "2026-11-03"}
    )
    assert (
        client.patch("/api/tasks/" + t["id"], json={"status": "completed"}).status_code
        == 200
    )
    assert (
        client.patch("/api/tasks/" + t["id"], json={"status": "todo"}).status_code
        == 200
    )
    assert (
        client.patch("/api/tasks/" + t["id"], json={"status": "completed"}).status_code
        == 200
    )
    assert sorted(d["entity_version"] for d in deliveries(client, ep)) == [1, 2]

    async def check():
        async with db.get_sessionmaker()() as session:
            for d in await session.scalars(select(WebhookDelivery)):
                assert json.loads(d.payload)["data"]["deadline"] == {
                    "kind": "date",
                    "date": "2026-11-03",
                }

    run(client, check)


def test_scoped_title_payload_and_all_day_metadata(configured):
    client, svc = configured
    listing = client.post("/api/lists", json={"name": "Selected"}).json()
    ep = endpoint(
        client,
        scope={"kind": "lists", "list_ids": [listing["id"]]},
        include_titles=True,
    )
    t = task(client, list_id=listing["id"])
    r = client.post(
        "/api/time-blocks",
        json={
            "task_id": t["id"],
            "kind": "all_day",
            "start_date": "2026-11-01",
            "end_date": "2026-11-02",
        },
    )
    assert r.status_code == 201
    assert len(deliveries(client, ep)) == 1

    async def check():
        async with db.get_sessionmaker()() as session:
            data = json.loads(
                (await session.scalars(select(WebhookDelivery))).one().payload
            )["data"]
            assert data["title"] == "private-title"
            assert data["kind"] == "all_day" and data["timezone"] is None
            assert (
                data["start_date"] == "2026-11-01" and data["end_date"] == "2026-11-02"
            )
            assert data["start_at"] is None and data["end_at"] is None

    run(client, check)


def test_automatic_retry_waits_until_due(configured, monkeypatch):
    from app.webhooks import service as service_module
    from datetime import datetime, timedelta

    client, svc = configured
    clock = datetime(2026, 11, 3, 10, 0, 0)
    monkeypatch.setattr(service_module, "utc_now", lambda: clock)
    ep = endpoint(client)
    client.post("/api/webhooks/" + ep["id"] + "/test")
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(503 if len(sent) == 1 else 204)

    svc.transport = httpx.MockTransport(handler)

    # Stored scheduling is source clock; place it at controlled delivery time
    async def ready():
        async with db.get_sessionmaker()() as session:
            row = (await session.scalars(select(WebhookDelivery))).one()
            row.next_attempt_at = clock
            await session.commit()

    run(client, ready)
    run(client, svc.tick)
    assert len(sent) == 1
    run(client, svc.tick)
    assert len(sent) == 1
    clock += timedelta(seconds=2)
    run(client, svc.tick)
    assert len(sent) == 2
    assert sent[0].content == sent[1].content
    assert deliveries(client, ep)[0]["state"] == "delivered"


def test_interruption_after_receiver_applied_replays_stable_identity(configured):
    import asyncio

    client, svc = configured
    ep = endpoint(client)
    client.post("/api/webhooks/" + ep["id"] + "/test")
    sent = []

    async def interrupt():
        applied = asyncio.Event()
        wait_forever = asyncio.Event()

        async def receiver(request):
            sent.append(request)
            applied.set()
            await wait_forever.wait()
            return httpx.Response(204)

        svc.transport = httpx.MockTransport(receiver)
        running = asyncio.create_task(svc.tick())
        await applied.wait()
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running

        async with db.get_sessionmaker()() as session:
            pending = (await session.scalars(select(WebhookDelivery))).one()
            assert pending.state == "pending"
            assert pending.attempts == 1
            assert pending.payload.encode() == sent[0].content

        def acknowledge(request):
            sent.append(request)
            return httpx.Response(204)

        restarted = Service(
            db.get_sessionmaker(), svc.store, httpx.MockTransport(acknowledge)
        )
        await restarted.tick()

    run(client, interrupt)
    assert len(sent) == 2
    assert sent[0].content == sent[1].content
    assert (
        sent[0].headers["X-Journal-Event-Id"] == sent[1].headers["X-Journal-Event-Id"]
    )
    row = deliveries(client, ep)[0]
    assert row["state"] == "delivered" and row["attempts"] == 2
