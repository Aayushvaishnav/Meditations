"""Durable at-least-once HTTP delivery; serializes configuration and sends."""

import asyncio
import hashlib
import hmac
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select

from app.calendar_sync.credentials import OSCredentialStore, CredentialStore
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from app.models import WebhookDelivery, WebhookEndpoint, utc_now


class Service:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        store: CredentialStore,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.sessions = sessions
        self.store = store
        self.transport = transport
        self.lock = asyncio.Lock()

    async def tick(self) -> None:
        async with self.sessions() as session:
            identifiers = (
                await session.scalars(
                    select(WebhookDelivery.id)
                    .where(
                        WebhookDelivery.state == "pending",
                        WebhookDelivery.next_attempt_at <= utc_now(),
                    )
                    .order_by(WebhookDelivery.created_at, WebhookDelivery.id)
                )
            ).all()
        for identifier in identifiers:
            await self.deliver(identifier)

    async def deliver(self, identifier: str) -> None:
        async with self.lock:
            async with self.sessions() as session:
                delivery = await session.get(WebhookDelivery, identifier)
                if (
                    delivery is None
                    or delivery.state != "pending"
                    or delivery.next_attempt_at > utc_now()
                ):
                    return
                endpoint = await session.get(WebhookEndpoint, delivery.endpoint_id)
                if not endpoint or not endpoint.enabled:
                    delivery.state = "cancelled"
                    await session.commit()
                    return
                # Persist attempts before sending; interruption keeps the same event pending
                delivery.attempts += 1
                await session.commit()
                try:
                    credentials = await self.store.get("webhook:" + endpoint.id)
                    if credentials is None:
                        raise ValueError("missing credential")
                    timestamp = str(int(time.time()))
                    body = delivery.payload.encode()
                    signature = hmac.new(
                        credentials.password.encode(),
                        timestamp.encode() + b"." + body,
                        hashlib.sha256,
                    ).hexdigest()
                    async with httpx.AsyncClient(
                        transport=self.transport, follow_redirects=False
                    ) as client:
                        response = await client.post(
                            endpoint.url,
                            content=body,
                            headers={
                                "Content-Type": "application/json",
                                "X-Journal-Timestamp": timestamp,
                                "X-Journal-Signature": "sha256=" + signature,
                                "X-Journal-Event-Id": delivery.event_id,
                            },
                        )
                    if 200 <= response.status_code < 300:
                        delivery.state = "delivered"
                        delivery.last_error = None
                    else:
                        delivery.last_error = "Endpoint returned HTTP " + str(
                            response.status_code
                        )
                        if response.status_code < 500 and response.status_code not in (
                            408,
                            425,
                            429,
                        ):
                            delivery.state = "failed"
                except Exception:
                    delivery.last_error = (
                        "Delivery unavailable; check endpoint and credential store"
                    )
                delivery.next_attempt_at = utc_now() + timedelta(
                    seconds=min(3600, 2 ** min(delivery.attempts, 12))
                )
                await session.commit()


def create_service(
    engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> Service:
    database = engine.url.database
    identity = (
        str(Path(database).resolve())
        if database not in (None, "", ":memory:")
        else str(uuid4())
    )
    namespace = "webhook:" + hashlib.sha256(identity.encode()).hexdigest()
    return Service(sessions, OSCredentialStore(namespace))


async def serve(service: Service) -> None:
    while True:
        await asyncio.sleep(1)
        try:
            await service.tick()
        except Exception:
            # Durable pending rows remain eligible after database availability returns
            continue
