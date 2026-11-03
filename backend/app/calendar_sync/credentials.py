"""OS-backed CalDAV credentials; no plaintext fallback."""
from __future__ import annotations

import asyncio
import importlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeVar


class CredentialStoreError(Exception):
    """Credential storage is unavailable or its data is invalid."""


@dataclass(frozen=True)
class Credentials:
    username: str = field(repr=False)
    password: str = field(repr=False)
    auth_type: Literal["basic", "digest"]

    def __post_init__(self) -> None:
        if (not isinstance(self.username, str) or not isinstance(self.password, str)
                or self.auth_type not in ("basic", "digest")):
            raise CredentialStoreError("Invalid credentials")


class CredentialStore(Protocol):
    async def get(self, connection_id: str) -> Credentials | None: ...
    async def put(self, connection_id: str, credentials: Credentials) -> None: ...
    async def delete(self, connection_id: str) -> None: ...


class KeyringBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


# Select one platform vault; never invoke plugin/chainer selection or fall back
_OS_BACKENDS = {
    "linux": ("keyring.backends.SecretService", "Keyring"),
    "darwin": ("keyring.backends.macOS", "Keyring"),
    "win32": ("keyring.backends.Windows", "WinVaultKeyring"),
}


def _select_backend() -> KeyringBackend:
    try:
        module, name = _OS_BACKENDS[sys.platform]
        cls = getattr(importlib.import_module(module), name)
        if cls.priority > 0:
            return cls()
    except Exception:
        pass
    raise CredentialStoreError("OS credential store unavailable") from None


T = TypeVar("T")


async def _run(operation: Callable[[], T]) -> T:
    worker = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # Threads cannot be cancelled; drain before lifecycle cleanup proceeds
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not worker.cancelled():
            worker.exception()
        raise
    except Exception:
        raise CredentialStoreError("OS credential operation failed") from None


class OSCredentialStore:
    def __init__(
        self, database_namespace: str, *,
        backend_factory: Callable[[], KeyringBackend] = _select_backend,
    ) -> None:
        if not isinstance(database_namespace, str) or not database_namespace.strip():
            raise CredentialStoreError("Database namespace required")
        self._service = f"Journal/CalDAV/{database_namespace}"
        self._backend_factory = backend_factory

    async def get(self, connection_id: str) -> Credentials | None:
        def read() -> Credentials | None:
            blob = self._backend_factory().get_password(self._service, connection_id)
            if blob is None:
                return None
            data = json.loads(blob)
            if (not isinstance(data, dict)
                    or set(data) != {"version", "username", "password", "auth_type"}
                    or type(data["version"]) is not int or data["version"] != 1):
                raise CredentialStoreError("Invalid stored credentials")
            return Credentials(data["username"], data["password"], data["auth_type"])
        return await _run(read)

    async def put(self, connection_id: str, credentials: Credentials) -> None:
        def write() -> None:
            blob = json.dumps({"version": 1, "username": credentials.username,
                               "password": credentials.password, "auth_type": credentials.auth_type})
            self._backend_factory().set_password(self._service, connection_id, blob)
        await _run(write)

    async def delete(self, connection_id: str) -> None:
        def remove() -> None:
            backend = self._backend_factory()
            if backend.get_password(self._service, connection_id) is None:
                return
            # PasswordDeleteError also represents denied/locked deletion; do not swallow it
            backend.delete_password(self._service, connection_id)
        await _run(remove)
