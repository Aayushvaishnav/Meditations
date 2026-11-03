"""Opt-in webhook management; never returns stored payloads or secrets."""

import json
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy import select, text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.calendar_sync.credentials import Credentials
from app.models import WebhookEndpoint, WebhookDelivery, new_id, utc_now
from app.webhooks.capture import scalar
from app.webhooks.service import Service

from app.webhooks.schemas import Write, Patch, validate, endpoint_view, delivery_view


class PrivateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(422, "Invalid webhook configuration") from None

        return private_handler


router = APIRouter(prefix="/api/webhooks", tags=["webhooks"], route_class=PrivateRoute)


def service(request: Request) -> Service:
    return request.app.state.webhook_service


async def get_endpoint(session: AsyncSession, identifier: str) -> WebhookEndpoint:
    endpoint = await session.get(WebhookEndpoint, identifier)
    if endpoint is None:
        raise HTTPException(404, "Webhook endpoint not found")
    return endpoint


async def cancel(session: AsyncSession, identifier: str) -> None:
    deliveries = await session.scalars(
        select(WebhookDelivery).where(
            WebhookDelivery.endpoint_id == identifier,
            WebhookDelivery.state.in_(["pending", "failed"]),
        )
    )
    for delivery in deliveries:
        delivery.state = "cancelled"
        delivery.payload = "{}"


async def credential(operation: Awaitable[None]) -> None:
    try:
        await operation
    except Exception:
        raise HTTPException(503, "Credential store unavailable") from None


@router.get("")
async def listing(request: Request) -> list[dict[str, Any]]:
    async with service(request).sessions() as session:
        return [
            endpoint_view(e) for e in await session.scalars(select(WebhookEndpoint))
        ]


@router.post("", status_code=201)
async def create(body: Write, request: Request) -> dict[str, Any]:
    values = body.model_dump(exclude={"secret"})
    validate(values)
    values["events"] = json.dumps(values["events"])
    values["scope"] = json.dumps(values["scope"])
    endpoint = WebhookEndpoint(**values)
    svc = service(request)
    async with svc.lock:
        await credential(
            svc.store.put(
                "webhook:" + endpoint.id, Credentials("", body.secret, "basic")
            )
        )
        async with svc.sessions() as session:
            session.add(endpoint)
            try:
                await session.commit()
            except BaseException:
                await svc.store.delete("webhook:" + endpoint.id)
                raise
            return endpoint_view(endpoint)


@router.patch("/{identifier}")
async def update(identifier: str, body: Patch, request: Request) -> dict[str, Any]:
    values = body.model_dump(exclude_unset=True)
    validate(values)
    svc = service(request)
    async with svc.lock:
        async with svc.sessions() as session:
            await session.execute(
                text("UPDATE webhook_endpoints SET enabled=enabled WHERE 0")
            )
            endpoint = await get_endpoint(session, identifier)
            # Every change invalidates old payloads; manual retry cannot bypass cancellation
            await cancel(session, identifier)
            if "secret" in values:
                await credential(
                    svc.store.put(
                        "webhook:" + identifier,
                        Credentials("", values.pop("secret"), "basic"),
                    )
                )
            for key, value in values.items():
                setattr(
                    endpoint,
                    key,
                    json.dumps(value) if key in ("events", "scope") else value,
                )
            await session.commit()
            return endpoint_view(endpoint)


@router.delete("/{identifier}", status_code=204)
async def remove(identifier: str, request: Request) -> Response:
    svc = service(request)
    async with svc.lock:
        async with svc.sessions() as session:
            await session.execute(
                text("UPDATE webhook_endpoints SET enabled=enabled WHERE 0")
            )
            endpoint = await get_endpoint(session, identifier)
            # Commit disabling first; a locked vault must not leave delivery enabled
            endpoint.enabled = False
            await cancel(session, identifier)
            await session.commit()
            await credential(svc.store.delete("webhook:" + identifier))
            await session.delete(endpoint)
            await session.commit()
    return Response(status_code=204)


@router.get("/{identifier}/deliveries")
async def deliveries(identifier: str, request: Request) -> list[dict[str, Any]]:
    async with service(request).sessions() as session:
        await get_endpoint(session, identifier)
        return [
            delivery_view(d)
            for d in await session.scalars(
                select(WebhookDelivery)
                .where(WebhookDelivery.endpoint_id == identifier)
                .order_by(WebhookDelivery.created_at.desc())
            )
        ]


@router.post("/{identifier}/test")
async def test(identifier: str, request: Request) -> dict[str, Any]:
    svc = service(request)
    async with svc.lock:
        async with svc.sessions() as session:
            await session.execute(
                text("UPDATE webhook_endpoints SET enabled=enabled WHERE 0")
            )
            endpoint = await get_endpoint(session, identifier)
            if not endpoint.enabled:
                raise HTTPException(409, "Endpoint disabled")
            event_id = new_id()
            delivery = WebhookDelivery(
                endpoint_id=identifier,
                event_id=event_id,
                event_type="webhook.test",
                entity_id=identifier,
                entity_version=1,
                payload=json.dumps(
                    dict(
                        schema_version=1,
                        id=event_id,
                        type="webhook.test",
                        entity_id=identifier,
                        entity_version=1,
                        occurred_at=scalar(utc_now()),
                        data={},
                    )
                ),
            )
            session.add(delivery)
            await session.commit()
            return delivery_view(delivery)


@router.post("/{identifier}/deliveries/{delivery_id}/retry")
async def retry(identifier: str, delivery_id: str, request: Request) -> dict[str, Any]:
    svc = service(request)
    async with svc.lock:
        async with svc.sessions() as session:
            await session.execute(
                text("UPDATE webhook_endpoints SET enabled=enabled WHERE 0")
            )
            endpoint = await get_endpoint(session, identifier)
            delivery = await session.get(WebhookDelivery, delivery_id)
            if not delivery or delivery.endpoint_id != identifier:
                raise HTTPException(404, "Delivery not found")
            if not endpoint.enabled or delivery.state not in ("pending", "failed"):
                raise HTTPException(
                    409,
                    "Only pending or failed deliveries on an enabled endpoint can be retried",
                )
            delivery.state = "pending"
            delivery.next_attempt_at = utc_now()
            await session.commit()
            return delivery_view(delivery)
