"""Frozen restore must succeed after shutdown and preserve linked source data."""
import re

import pytest

from test_smoke_sidecar import check_cleanup, fake_sidecar, module


def test_offline_restore_after_server_shutdown(fake_sidecar):
    binary, record = fake_sidecar('success')
    module.smoke(binary, startup_timeout=3)
    check_cleanup(record)


@pytest.mark.parametrize(('mode', 'message'), [
    ('restore-error', 'offline restore failed (exit 17)'),
    ('restore-empty', 'missing the linked source data'),
    ('restore-corrupt', 'file is not a database'),
    ('restore-orphan', 'failed foreign key check'),
])
def test_restore_failure_rejects_otherwise_healthy_binary(fake_sidecar, mode, message):
    binary, record = fake_sidecar(mode)
    with pytest.raises(module.SmokeError, match=re.escape(message)) as error:
        module.smoke(binary, startup_timeout=3)
    if mode == 'restore-error':
        assert 'vec0.so' in str(error.value)
    check_cleanup(record)
