from __future__ import annotations

import pytest


@pytest.mark.parametrize("field", ["name", "color", "is_favorite"])
def test_required_list_fields_reject_null_without_changes(client, field):
    original = client.post("/api/lists", json={"name": "Keep", "icon": "star"}).json()
    url = f"/api/lists/{original['id']}"
    response = client.patch(url, json={field: None, "icon": "Must not persist"})
    assert response.status_code == 422
    assert any(error["loc"] == ["body", field] for error in response.json()["detail"])
    assert client.get(url).json() == original
    assert client.get("/api/lists").json() == [original]


def test_list_patch_allows_icon_clearing_and_omission(client):
    original = client.post("/api/lists", json={
        "name": "Keep", "icon": "star", "is_favorite": True,
    }).json()
    url = f"/api/lists/{original['id']}"
    assert client.patch(url, json={}).json() == original
    assert client.patch(url, json={"icon": None}).json() == {**original, "icon": None}
    response = client.patch(url, json={"is_favorite": False})
    assert response.status_code == 200
    assert response.json()["is_favorite"] is False
    assert client.get(url).json()["is_favorite"] is False
