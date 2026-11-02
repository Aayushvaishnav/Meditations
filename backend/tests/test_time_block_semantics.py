"""SCHED03 behavioral contracts for calendar labels and wall-clock resolution."""
from datetime import datetime

import pytest

BASE = "/api/time-blocks"


def make_task(client, **fields):
    response = client.post("/api/tasks", json={"title": "Calendar semantics", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def timed(identifier, **fields):
    return {"task_id": identifier, "start_at": "2026-09-10T09:00:00", "end_at": "2026-09-10T10:00:00", **fields}


def local(identifier, start, end, zone="America/New_York"):
    return {"task_id": identifier, "kind": "local", "start_local": start, "end_local": end, "timezone": zone}


def all_day(identifier, **fields):
    return {"task_id": identifier, "kind": "all_day", "start_date": "2026-09-10", "end_date": "2026-09-12", **fields}


def create(client, body):
    response = client.post(BASE, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def listing(client, **params):
    response = client.get(BASE, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def canonical(block, kind):
    assert set(block) == {"id", "task_id", "kind", "timezone", "start_at", "end_at", "start_date", "end_date", "created_at", "updated_at"}
    assert block["kind"] == kind
    absent = ("timezone", "start_at", "end_at") if kind == "all_day" else ("start_date", "end_date")
    assert all(block[key] is None for key in absent)
    for key in ("created_at", "updated_at"):
        assert datetime.fromisoformat(block[key]).tzinfo is None


@pytest.mark.parametrize("explicit", [False, True])
def test_timed_defaults_and_metadata_do_not_reinterpret_instants(client, explicit):
    body = timed(make_task(client)["id"])
    if explicit:
        body.update(kind="timed", timezone="America/New_York", start_at="2026-09-10T11:00:00+02:00", end_at="2026-09-10T12:00:00+02:00")
    block = create(client, body)
    canonical(block, "timed")
    assert block["timezone"] == ("America/New_York" if explicit else "UTC")
    assert (block["start_at"], block["end_at"]) == ("2026-09-10T09:00:00", "2026-09-10T10:00:00")
    assert client.get(f"{BASE}/{block['id']}").json() == block


@pytest.mark.parametrize("zone,start,end,expected_start,expected_end", [
    ("America/New_York", "2026-03-08T01:30:00", "2026-03-08T03:30:00", "2026-03-08T06:30:00", "2026-03-08T07:30:00"),
    ("America/New_York", "2026-11-01T01:15:00-04:00", "2026-11-01T01:45:00-04:00", "2026-11-01T05:15:00", "2026-11-01T05:45:00"),
    ("America/New_York", "2026-11-01T01:15:00-05:00", "2026-11-01T01:45:00-05:00", "2026-11-01T06:15:00", "2026-11-01T06:45:00"),
    ("America/New_York", "2026-11-01T01:45:00-04:00", "2026-11-01T01:15:00-05:00", "2026-11-01T05:45:00", "2026-11-01T06:15:00"),
    ("Australia/Lord_Howe", "2026-04-05T01:35:00+11:00", "2026-04-05T01:45:00+11:00", "2026-04-04T14:35:00", "2026-04-04T14:45:00"),
    ("Australia/Lord_Howe", "2026-04-05T01:35:00+10:30", "2026-04-05T01:45:00+10:30", "2026-04-04T15:05:00", "2026-04-04T15:15:00"),
    ("Australia/Lord_Howe", "2026-10-04T01:45:00", "2026-10-04T02:45:00", "2026-10-03T15:15:00", "2026-10-03T15:45:00"),
])
def test_local_resolves_to_canonical_timed(client, zone, start, end, expected_start, expected_end):
    block = create(client, local(make_task(client)["id"], start, end, zone))
    canonical(block, "timed")
    assert (block["start_at"], block["end_at"], block["timezone"]) == (expected_start, expected_end, zone)
    assert client.get(f"{BASE}/{block['id']}").json() == block


INVALID_LOCAL = [
    ("America/New_York", "2026-03-08T02:15:00" , "2026-03-08T03:30:00"),
    *[("America/New_York", f"2026-03-08T02:15:00{offset}", "2026-03-08T03:30:00-04:00") for offset in ["-04:00", "-05:00"]],
    ("America/New_York", "2026-11-01T01:15:00", "2026-11-01T02:30:00"),
    ("America/New_York", "2026-11-01T00:30:00", "2026-11-01T01:45:00"),
    ("America/New_York", "2026-11-01T01:15:00-06:00", "2026-11-01T02:30:00-05:00"),
    ("America/New_York", "2026-07-01T09:00:00-05:00", "2026-07-01T10:00:00-04:00"),
    ("America/New_York", "2026-07-01T09:00:00-04:00", "2026-07-01T10:00:00-05:00"),
    ("America/New_York", "2026-11-01T01:15:00-05:00", "2026-11-01T01:45:00-04:00"),
    ("America/New_York", "2026-11-01T01:15:00-04:00", "2026-11-01T01:15:00-04:00"),
    ("Australia/Lord_Howe", "2026-04-05T01:35:00", "2026-04-05T02:30:00"),
    *[("Australia/Lord_Howe", f"2026-10-04T02:15:00{offset}", "2026-10-04T03:00:00+11:00") for offset in ["", "+10:30", "+11:00"]],
    *[("Pacific/Apia", f"2011-12-30T09:00:00{offset}", "2011-12-31T10:00:00+14:00") for offset in ["", "-10:00", "+14:00"]],
    ("Asia/Tokyo", "0001-01-01T00:00:00", "0001-01-01T10:00:00"),
    ("America/New_York", "9999-12-31T20:00:00", "9999-12-31T21:00:00"),
]


@pytest.mark.parametrize("zone,start,end", INVALID_LOCAL)
@pytest.mark.parametrize("method", ["post", "put"])
def test_invalid_local_is_422_and_atomic(client, zone, start, end, method):
    identifier = make_task(client)["id"]
    original = create(client, timed(identifier))
    url = BASE if method == "post" else f"{BASE}/{original['id']}"
    response = getattr(client, method)(url, json=local(identifier, start, end, zone))
    assert response.status_code == 422, response.text
    assert listing(client) == [original]


@pytest.mark.parametrize("dates,hours", [(["2026-03-01", "2026-03-08", "2026-03-15"], [14, 13, 13]), (["2026-10-25", "2026-11-01", "2026-11-08"], [13, 14, 14])])
def test_weekly_nine_am_inputs_cross_dst(client, dates, hours):
    identifier = make_task(client)["id"]
    for day, hour in zip(dates, hours):
        block = create(client, local(identifier, f"{day}T09:00:00", f"{day}T10:00:00"))
        assert block["start_at"] == f"{day}T{hour:02}:00:00"
        assert block["end_at"] == f"{day}T{hour + 1:02}:00:00"


def test_put_switches_kinds_and_clears_inapplicable_fields(client):
    identifier = make_task(client)["id"]
    original = create(client, timed(identifier, timezone="Asia/Tokyo"))
    for body, kind in [(all_day(identifier), "all_day"), (local(identifier, "2026-09-10T09:00:00", "2026-09-10T10:00:00"), "timed"), (all_day(identifier), "all_day"), (timed(identifier), "timed")]:
        response = client.put(f"{BASE}/{original['id']}", json=body)
        assert response.status_code == 200, response.text
        block = response.json()
        canonical(block, kind)
        assert (block["id"], block["created_at"]) == (original["id"], original["created_at"])
        assert client.get(f"{BASE}/{block['id']}").json() == block
        assert listing(client) == [block]


@pytest.mark.parametrize("shape", ["timed", "local", "all_day"])
@pytest.mark.parametrize("method", ["post", "put"])
def test_shapes_reject_missing_null_mixed_and_unknown_fields(client, shape, method):
    identifier = make_task(client)["id"]
    original = create(client, timed(identifier))
    body = {"timed": timed(identifier, kind="timed"), "local": local(identifier, "2026-09-10T09:00:00", "2026-09-10T10:00:00", "UTC"), "all_day": all_day(identifier)}[shape]
    required = {"timed": ["task_id", "start_at", "end_at"], "local": ["task_id", "start_local", "end_local", "timezone"], "all_day": ["task_id", "start_date", "end_date"]}[shape]
    invalid = []
    for field in required:
        invalid.extend([{key: value for key, value in body.items() if key != field}, {**body, field: None}])
    for field in {"start_at", "end_at", "start_local", "end_local", "start_date", "end_date", "timezone"} - set(body):
        if field == "timezone" and shape == "timed":
            continue
        invalid.extend([{**body, field: None}, {**body, field: "2026-09-10"}])
    invalid.extend({**body, "kind": value} for value in [None, "unknown", "", 1])
    invalid.append({**body, "unexpected": None})
    if shape != "all_day":
        invalid.extend({**body, "timezone": value} for value in [None, "", "Not/A_Zone", 123])
    url = BASE if method == "post" else f"{BASE}/{original['id']}"
    for candidate in invalid:
        response = getattr(client, method)(url, json=candidate)
        assert response.status_code == 422, (candidate, response.text)
        assert listing(client) == [original]


@pytest.mark.parametrize("field", ["start_date", "end_date"])
@pytest.mark.parametrize("value", ["2026-09-10T00:00:00", "2026-09-10T00:00:00Z", "2026-02-30", "2026-9-10", "0000-01-01", 20260910, 0, True])
@pytest.mark.parametrize("method", ["post", "put"])
def test_dates_are_strict_calendar_labels(client, field, value, method):
    identifier = make_task(client)["id"]
    original = create(client, timed(identifier))
    url = BASE if method == "post" else f"{BASE}/{original['id']}"
    response = getattr(client, method)(url, json=all_day(identifier, **{field: value}))
    assert response.status_code == 422, response.text
    assert listing(client) == [original]


@pytest.mark.parametrize("end", ["2026-09-10", "2026-09-09"])
def test_all_day_requires_positive_date_interval(client, end):
    assert client.post(BASE, json=all_day(make_task(client)["id"], end_date=end)).status_code == 422


def test_skipped_day_remains_a_calendar_label(client):
    block = create(client, all_day(make_task(client)["id"], start_date="2011-12-30", end_date="2011-12-31"))
    canonical(block, "all_day")
    assert (block["start_date"], block["end_date"]) == ("2011-12-30", "2011-12-31")
    assert listing(client, start_date="2011-12-30", end_date="2011-12-31") == [block]


def test_list_kind_task_order_and_half_open_ranges(client):
    identifier, other = make_task(client)["id"], make_task(client)["id"]
    bodies = [all_day(identifier, start_date="2026-09-12", end_date="2026-09-13"), timed(identifier), all_day(identifier, start_date="2026-09-09", end_date="2026-09-10"), all_day(identifier), all_day(other), timed(other)]
    blocks = [create(client, body) for body in bodies]
    def ordered(indices):
        return sorted((blocks[i] for i in indices), key=lambda b: (b["kind"], b["start_at"] or "", b["start_date"] or "", b["id"]))
    assert listing(client) == ordered(range(6))
    assert listing(client, task_id=identifier) == ordered(range(4))
    assert listing(client, kind="timed") == ordered([1, 5])
    assert listing(client, kind="all_day") == ordered([0, 2, 3, 4])
    assert listing(client, start="2026-09-10T09:00:00", end="2026-09-10T10:00:00") == ordered([1, 5])
    assert listing(client, start="2026-09-10T10:00:00") == []
    assert listing(client, end="2026-09-10T09:00:00") == []
    assert listing(client, start_date="2026-09-10", end_date="2026-09-12") == ordered([3, 4])
    assert listing(client, kind="all_day", task_id=identifier, start_date="2026-09-10", end_date="2026-09-12") == [blocks[3]]
    assert listing(client, start_date="2026-09-12") == [blocks[0]]
    assert listing(client, end_date="2026-09-10") == [blocks[2]]
    assert listing(client, task_id="missing") == []


@pytest.mark.parametrize("params", [
    {"kind": "local"}, {"kind": "unknown"},
    *[{instant: "2026-09-10T00:00:00", label: "2026-09-12"} for instant in ["start", "end"] for label in ["start_date", "end_date"]],
    *[{"kind": "timed", label: "2026-09-10"} for label in ["start_date", "end_date"]],
    *[{"kind": "all_day", instant: "2026-09-10T00:00:00"} for instant in ["start", "end"]],
    {"start_date": "2026-09-12", "end_date": "2026-09-12"}, {"start_date": "2026-09-13", "end_date": "2026-09-12"},
    {"start_date": "2026-09-10T00:00:00"}, {"end_date": "2026-02-30"},
    {"start": "0001-01-01T00:00:00+01:00"}, {"end": "9999-12-31T23:59:59-01:00"},
])
def test_invalid_filter_combinations(client, params):
    response = client.get(BASE, params=params)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("recurring", [False, True])
def test_all_day_deadline_focus_and_completion_independence(client, recurring):
    fields = {"recurrence_rule": "RRULE:FREQ=DAILY"} if recurring else {}
    original = make_task(client, due_date="2026-09-10T17:00:00", estimated_minutes=90, **fields)
    sessions = client.get("/api/focus/sessions").json()
    score = client.get("/api/scores/daily/2026-09-10").json()
    block = create(client, all_day(original["id"]))
    canonical(block, "all_day")
    assert client.get(f"/api/tasks/{original['id']}").json() == original
    assert client.get("/api/scores/daily/2026-09-10").json() == score
    response = client.patch(f"/api/tasks/{original['id']}", json={"status": "completed"})
    assert response.status_code == 200, response.text
    assert response.json()["due_date"] == original["due_date"]
    assert listing(client) == [block]
    assert client.get("/api/focus/sessions").json() == sessions
    successors = [item for item in client.get("/api/tasks").json() if item["id"] != original["id"]]
    assert len(successors) == int(recurring)
    for successor in successors:
        assert listing(client, task_id=successor["id"]) == []
