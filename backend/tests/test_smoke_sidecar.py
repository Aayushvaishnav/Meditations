"""Run the harness against real child processes, without app or AI imports."""
import importlib.util
import os
from pathlib import Path
import sys

import pytest


spec = importlib.util.spec_from_file_location(
    "smoke_sidecar", Path(__file__).parents[1] / "scripts" / "smoke_sidecar.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def fake_sidecar(tmp_path):
    def make(mode):
        script = tmp_path / "sidecar"
        record = tmp_path / "record"
        script.write_text(f"#!{sys.executable}\n" + f"MODE={mode!r}\nRECORD={str(record)!r}\n" + r'''
import json, os, signal, time, sqlite3, sys, shutil
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
root = Path.cwd()
if len(sys.argv) > 1:
    info = json.loads(Path(RECORD).read_text())
    try:
        os.kill(info['pid'], 0)
    except ProcessLookupError:
        pass
    else:
        raise SystemExit('server still running during restore')
    if MODE == 'restore-error':
        print('vec0.so: cannot open shared object file', flush=True)
        raise SystemExit(17)
    target = Path(sys.argv[4])
    assert sys.argv[1] == 'restore' and sys.argv[3] == '--database'
    assert target != Path(info['env']['JOURNAL_DB_PATH'])
    assert os.environ['JOURNAL_DB_PATH'] == str(target)
    shutil.copyfile(sys.argv[2], target)
    if MODE == 'restore-empty':
        with sqlite3.connect(target) as connection:
            connection.execute('DELETE FROM tasks')
    if MODE == 'restore-orphan':
        with sqlite3.connect(target) as connection:
            connection.execute('DELETE FROM lists')
    if MODE == 'restore-corrupt':
        target.write_bytes(b'not SQLite')
    raise SystemExit(0)
keys = ('HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
        'XDG_STATE_HOME', 'HF_HOME', 'JOURNAL_DB_PATH', 'MEDITATIONS_PORT',
        'MEDITATIONS_HOST', 'HF_HUB_OFFLINE', 'JOURNAL_SCHEDULED_REVIEWS')
Path(RECORD).write_text(json.dumps({'pid': os.getpid(), 'cwd': str(root),
                                  'env': {key: os.environ[key] for key in keys}}))
print('child diagnostic marker', flush=True)
if MODE == 'exit':
    raise SystemExit(23)
if MODE == 'timeout':
    time.sleep(60)
if MODE == 'kill':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(60)
Path(os.environ['JOURNAL_DB_PATH']).write_bytes(b'fake database')
objects = {}
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def handle_request(self):
        path = self.path
        method = self.command
        status = 200
        data = {}
        if path == '/api/backup' and method == 'POST':
            backup = root / 'download.db'
            with sqlite3.connect(backup) as connection:
                connection.execute('CREATE TABLE lists (id TEXT PRIMARY KEY, name TEXT)')
                connection.execute('CREATE TABLE tasks (id TEXT, title TEXT, list_id TEXT REFERENCES lists(id))')
                for key, obj in objects.items():
                    if key.startswith('/api/lists/'):
                        connection.execute('INSERT INTO lists VALUES (?, ?)', (obj['id'], obj['name']))
                    else:
                        connection.execute('INSERT INTO tasks VALUES (?, ?, ?)',
                                           (obj['id'], obj['title'], obj['list_id']))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(backup.read_bytes())
            return
        if path == '/api/health':
            data = {'status': 'bad' if MODE == 'health' else 'ok'}
        elif method == 'POST':
            if MODE == 'crud':
                status, data = 500, {'detail': 'broken create'}
            else:
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                data['id'] = 'list' if path == '/api/lists' else 'task'
                objects[path + '/' + data['id']] = data
                status = 201
        elif path not in objects:
            status, data = 404, {'detail': 'not found'}
        elif method == 'DELETE':
            del objects[path]
            status = 204
        elif method == 'PATCH':
            objects[path].update(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            data = objects[path]
        else:
            data = objects[path]
        self.send_response(status)
        self.end_headers()
        if status != 204:
            self.wfile.write(b'not json' if MODE == 'json' else json.dumps(data).encode())
    do_GET = do_POST = do_PATCH = do_DELETE = handle_request
server = HTTPServer(('127.0.0.1', 0), Handler)
print(f'Uvicorn running on http://127.0.0.1:{server.server_port} (Press CTRL+C to quit)', flush=True)
server.serve_forever()
''')
        script.chmod(0o755)
        return script, record
    return make


def check_cleanup(record):
    import json
    info = json.loads(record.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(info['pid'], 0)
    assert not Path(info['cwd']).exists()
    return info


def test_success_isolated_and_cleaned(fake_sidecar):
    binary, record = fake_sidecar('success')
    module.smoke(binary, startup_timeout=3)
    info = check_cleanup(record)
    env = info['env']
    assert env['MEDITATIONS_PORT'] == '0'
    assert env['MEDITATIONS_HOST'] == '127.0.0.1'
    assert env['HF_HUB_OFFLINE'] == '1'
    assert env['JOURNAL_SCHEDULED_REVIEWS'] == 'false'
    for key in ('HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
                'XDG_STATE_HOME', 'HF_HOME', 'JOURNAL_DB_PATH'):
        assert Path(env[key]).is_relative_to(info['cwd'])


@pytest.mark.parametrize(('mode', 'message'), [
    ('exit', 'exit 23'), ('timeout', 'deadline exceeded'),
    ('health', 'invalid health response'), ('json', 'invalid JSON'),
    ('crud', 'expected 201, got 500'), ('kill', 'deadline exceeded'),
])
def test_failures_report_logs_and_cleanup(fake_sidecar, mode, message):
    binary, record = fake_sidecar(mode)
    with pytest.raises(module.SmokeError) as error:
        module.smoke(binary, startup_timeout=0.5 if mode in ('timeout', 'kill') else 3)
    assert message in str(error.value)
    assert 'child diagnostic marker' in str(error.value)
    check_cleanup(record)
