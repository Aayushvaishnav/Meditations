"""Webhook configuration schemas, URL validation and public projections."""

import json
from typing import Any
from app.models import WebhookEndpoint, WebhookDelivery
from typing import Literal
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.webhooks.capture import scalar

EVENTS = {
    "time_block.created",
    "time_block.updated",
    "time_block.deleted",
    "task.completed",
}


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["all", "lists"] = "all"
    list_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scope(self):
        if self.kind == "all" and self.list_ids:
            raise ValueError("All scope must have no list IDs")
        return self


class Write(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    url: str
    enabled: bool = True
    events: list[str] = Field(default_factory=lambda: sorted(EVENTS))
    scope: Scope = Field(default_factory=Scope)
    include_titles: bool = False
    secret: str = Field(min_length=1, repr=False)


class Patch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = None
    enabled: bool | None = None
    events: list[str] | None = None
    scope: Scope | None = None
    include_titles: bool | None = None
    secret: str | None = Field(default=None, min_length=1, repr=False)

    @model_validator(mode="after")
    def nonnull(self):
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("Fields cannot be null")
        return self


def validate(values: dict[str, Any]) -> None:
    if "url" in values:
        try:
            url = urlsplit(values["url"])
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
                or any(c.isspace() or ord(c) < 32 for c in values["url"])
            ):
                raise ValueError()
            url.port
        except ValueError:
            raise HTTPException(
                422, "Use an HTTP(S) URL without credentials, query, or fragment"
            ) from None
    if "events" in values and not set(values["events"]) <= EVENTS:
        raise HTTPException(422, "Unsupported webhook event")


def endpoint_view(endpoint: WebhookEndpoint) -> dict[str, Any]:
    return dict(
        id=endpoint.id,
        name=endpoint.name,
        url=endpoint.url,
        enabled=endpoint.enabled,
        events=json.loads(endpoint.events),
        scope=json.loads(endpoint.scope),
        include_titles=endpoint.include_titles,
        has_secret=True,
    )


def delivery_view(delivery: WebhookDelivery) -> dict[str, Any]:
    return {
        key: scalar(getattr(delivery, key))
        for key in (
            "id",
            "event_id",
            "event_type",
            "entity_id",
            "entity_version",
            "state",
            "attempts",
            "last_error",
            "next_attempt_at",
            "created_at",
        )
    }
