from __future__ import annotations

import os
import subprocess
import sys

import pytest

from app.time_zones import zone_name


@pytest.mark.parametrize("name", ["posixrules", "posix/America/New_York", "right/America/New_York", "localtime"])
def test_reject_host_only_timezone_names(name):
    with pytest.raises(ValueError, match="IANA timezone"):
        zone_name(name)


@pytest.mark.parametrize("name", ["UTC", "US/Eastern", "Etc/GMT+5", "Asia/Kolkata"])
def test_portable_timezone_aliases(name):
    assert zone_name(name) == name


def test_timezone_fallback_without_host_zoneinfo():
    result = subprocess.run(
        [sys.executable, "-c", """
from datetime import datetime
from zoneinfo import TZPATH
from app.time_zones import resolve_local, zone_name
assert TZPATH == ()
for name in ('UTC', 'US/Eastern', 'Etc/GMT+5', 'Asia/Kolkata'):
    assert zone_name(name) == name
for name in ('posixrules', 'posix/America/New_York', 'right/America/New_York', 'localtime'):
    try:
        zone_name(name)
    except ValueError:
        pass
    else:
        raise AssertionError(name)
assert resolve_local(datetime(2026, 3, 1, 9), 'America/New_York') == datetime(2026, 3, 1, 14)
assert resolve_local(datetime(2026, 3, 8, 9), 'America/New_York') == datetime(2026, 3, 8, 13)
assert resolve_local(datetime.fromisoformat('2026-11-01T01:30:00-05:00'), 'America/New_York') == datetime(2026, 11, 1, 6, 30)
"""],
        env={**os.environ, "PYTHONTZPATH": ""},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
