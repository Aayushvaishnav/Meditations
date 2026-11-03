import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

from app.calendar_sync import credentials as module
from app.calendar_sync.credentials import Credentials, CredentialStoreError, OSCredentialStore


class FakeBackend:
    def __init__(self):
        self.values = {}
        self.threads = []

    def get_password(self, service, username):
        self.threads.append(threading.get_ident())
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        self.values[service, username] = password

    def delete_password(self, service, username):
        del self.values[service, username]


def test_roundtrip_isolation_and_delete():
    async def run():
        backend = FakeBackend()
        store = OSCredentialStore("db-one", backend_factory=lambda: backend)
        other = OSCredentialStore("db-two", backend_factory=lambda: backend)
        value = Credentials("private-user", "private-password", "digest")
        assert "private" not in repr(value)
        assert await store.get("a") is None
        await store.put("a", value)
        assert await store.get("a") == value
        assert await store.get("b") is None
        assert await other.get("a") is None
        assert json.loads(backend.values["Journal/CalDAV/db-one", "a"])["version"] == 1
        await store.put("a", Credentials("new", "new", "basic"))
        assert len(backend.values) == 1
        await store.delete("a")
        await store.delete("a")
        assert await store.get("a") is None
        assert all(t != threading.get_ident() for t in backend.threads)
    asyncio.run(run())


@pytest.mark.parametrize("blob", ["", "secret", "null", "[]", "{}", '{"version":2}',
    json.dumps(dict(version=True, username="u", password="p", auth_type="basic")),
    json.dumps(dict(version=1, username=1, password="p", auth_type="basic")),
    json.dumps(dict(version=1, username="u", password="p", auth_type="oauth"))])
def test_invalid_blob_fails_closed(blob):
    backend = FakeBackend()
    backend.values["Journal/CalDAV/db", "a"] = blob
    store = OSCredentialStore("db", backend_factory=lambda: backend)
    with pytest.raises(CredentialStoreError):
        asyncio.run(store.get("a"))


@pytest.mark.parametrize("operation", ["get", "put", "delete"])
def test_backend_errors_are_generic(operation):
    class Broken(FakeBackend):
        def get_password(self, *args):
            if operation == "delete":
                return "present"
            raise RuntimeError("private-password")

        def set_password(self, *args):
            raise RuntimeError("private-password")

        def delete_password(self, *args):
            raise RuntimeError("private-password")
    store = OSCredentialStore("db", backend_factory=Broken)
    args = ("a", Credentials("u", "p", "basic")) if operation == "put" else ("a",)
    with pytest.raises(CredentialStoreError) as error:
        asyncio.run(getattr(store, operation)(*args))
    assert "private" not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize("namespace", ["", "  ", None])
def test_namespace_required(namespace):
    with pytest.raises(CredentialStoreError):
        OSCredentialStore(namespace)


@pytest.mark.parametrize("operation", ["get", "put", "delete"])
@pytest.mark.parametrize("failure", ["priority", "import", "initialization"])
def test_secret_service_unavailable_never_probes_kwallet(monkeypatch, operation, failure):
    seen = []

    class Unavailable:
        priority = 0 if failure == "priority" else 1

        def __init__(self):
            raise RuntimeError("private-password")

    def load(name):
        seen.append(name)
        if name == "keyring.backends.SecretService":
            if failure == "import":
                raise ImportError("private-password")
            return SimpleNamespace(Keyring=Unavailable)
        return SimpleNamespace(DBusKeyring=FakeBackend)

    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.importlib, "import_module", load)
    store = OSCredentialStore("db")
    assert seen == []
    args = ("a", Credentials("u", "p", "basic")) if operation == "put" else ("a",)
    for _ in range(2):
        with pytest.raises(CredentialStoreError, match="^OS credential operation failed$"):
            asyncio.run(getattr(store, operation)(*args))
    assert seen == ["keyring.backends.SecretService"] * 2


@pytest.mark.parametrize("failure", [False, True])
def test_cancellation_drains_worker(failure):
    async def run():
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        class Blocking(FakeBackend):
            def set_password(self, *args):
                started.set()
                release.wait()
                finished.set()
                if failure:
                    raise RuntimeError("secret")
        store = OSCredentialStore("db", backend_factory=Blocking)
        task = asyncio.create_task(store.put("a", Credentials("u", "p", "basic")))
        await asyncio.to_thread(started.wait)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
    asyncio.run(run())


@pytest.mark.parametrize("platform, backend_module, backend_class", [
    ("linux", "keyring.backends.SecretService", "Keyring"),
    ("darwin", "keyring.backends.macOS", "Keyring"),
    ("win32", "keyring.backends.Windows", "WinVaultKeyring"),
])
def test_select_platform_backend_lazily_in_worker(
    monkeypatch, platform, backend_module, backend_class,
):
    seen = []
    backend = FakeBackend()

    class Secure:
        priority = 1

        def __new__(cls):
            return backend

    def load(name):
        seen.append((name, threading.get_ident()))
        return SimpleNamespace(**{backend_class: Secure})

    monkeypatch.setattr(module.sys, "platform", platform)
    monkeypatch.setattr(module.importlib, "import_module", load)
    store = OSCredentialStore("db")
    assert seen == []

    async def run():
        value = Credentials("u", "p", "basic")
        await store.put("a", value)
        assert await store.get("a") == value
        await store.delete("a")

    asyncio.run(run())
    assert [name for name, _ in seen] == [backend_module] * 3
    assert all(thread != threading.get_ident() for _, thread in seen)


def test_unsupported_platform_fails_without_imports(monkeypatch):
    seen = []
    monkeypatch.setattr(module.sys, "platform", "freebsd")
    monkeypatch.setattr(module.importlib, "import_module", lambda name: seen.append(name))
    with pytest.raises(CredentialStoreError, match="^OS credential operation failed$"):
        asyncio.run(OSCredentialStore("db").get("a"))
    assert seen == []
