"""Disposable Radicale HTTP server; no user configuration, accounts, or vault."""
from threading import Thread
from types import SimpleNamespace
from wsgiref.simple_server import WSGIRequestHandler, make_server

import httpx
import pytest
from radicale import Application, config

USERNAME = 'journal'
PASSWORD = 'journal-test-password'


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass


class LocalServer:
    def __init__(self, application):
        self.application = application
        self.server = make_server('127.0.0.1', 0, application, handler_class=QuietHandler)
        self.port = self.server.server_port
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def restart(self):
        self.server = make_server('127.0.0.1', self.port, self.application, handler_class=QuietHandler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def radicale_server(tmp_path):
    users = tmp_path / 'users'
    users.write_text(f'{USERNAME}:{PASSWORD}\n')
    users.chmod(0o600)
    configuration = config.load([])
    configuration.update({
        'auth': {'type': 'htpasswd', 'htpasswd_filename': str(users),
                 'htpasswd_encryption': 'plain', 'delay': '0'},
        'storage': {'filesystem_folder': str(tmp_path / 'collections')},
        'rights': {'type': 'owner_only'},
        'logging': {'level': 'error'},
    }, 'isolated integration fixture')
    # Bind port zero once; retain the socket except during explicit outage tests
    server = LocalServer(Application(configuration))
    url = f'http://127.0.0.1:{server.port}/'
    calendar_url = url + USERNAME + '/meditations/'
    try:
        with httpx.Client(auth=(USERNAME, PASSWORD), trust_env=False) as client:
            response = client.request('MKCALENDAR', calendar_url, content='''
<C:mkcalendar xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
<D:set><D:prop><D:displayname>Meditations integration</D:displayname>
<C:supported-calendar-component-set><C:comp name="VEVENT"/></C:supported-calendar-component-set>
</D:prop></D:set></C:mkcalendar>''', headers={'Content-Type': 'application/xml'})
            assert response.status_code == 201, response.text
        yield SimpleNamespace(url=url, calendar_url=calendar_url, process=server)
    finally:
        server.stop()
