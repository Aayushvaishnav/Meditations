"""Packaged local calendar import smoke protocol."""
from unittest.mock import Mock

import pytest

from test_smoke_sidecar import module


def run(request):
    def require(condition, message):
        if not condition:
            raise module.SmokeError(message)
    module._smoke_calendar_import(request, require)


def test_import_inventory_snapshot_and_cleanup():
    request = Mock()

    def respond(method, path, status, payload=None):
        if method == 'POST':
            return {'source_id': 'source', 'created': 1, 'updated': 0, 'unchanged': 0}
        if path.endswith('/events'):
            return [{'start_kind': 'local', 'time_zone': 'America/New_York', 'representation': 'opaque'}]
        if path.endswith('/snapshots'):
            return [{'content': request.call_args_list[0].args[3]['content']}]

    request.side_effect = respond
    run(request)
    assert request.call_args.args == ('DELETE', '/api/calendar/imports/source', 204)
    payload = request.call_args_list[0].args[3]
    assert payload['content'].startswith('\ufeff')
    assert payload['target']['kind'] == 'new'


def test_inventory_failure_deletes_source():
    request = Mock(side_effect=[{'source_id': 'source', 'created': 1}, [], None])
    with pytest.raises(module.SmokeError, match='inventory mismatch'):
        run(request)
    assert request.call_args.args == ('DELETE', '/api/calendar/imports/source', 204)
