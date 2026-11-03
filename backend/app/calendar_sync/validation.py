"""Validation responses for credential-bearing connection requests."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse

_FIELDS = {"username", "password", "auth_type", "calendar_url", "server_url", "connection_id"}
_MESSAGES = {
    "missing": "Field is required",
    "extra_forbidden": "Unexpected field",
    "string_type": "A string value is required",
    "string_too_short": "A nonempty string is required",
    "literal_error": "Choose basic or digest authentication",
}


class CredentialRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request: Request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                # Error inputs, custom messages, and unknown field names can contain credentials
                detail = []
                for error in exc.errors():
                    location = [part if part in _FIELDS or part in {"body", "path", "query"}
                                else "unexpected_field" for part in error["loc"]]
                    detail.append({"loc": location, "type": error["type"],
                                   "msg": _MESSAGES.get(error["type"], "Invalid calendar connection value")})
                return JSONResponse(status_code=422, content={"detail": detail})

        return handle
