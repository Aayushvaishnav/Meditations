import pytest


@pytest.mark.parametrize('endpoint,payload,canary', [
    ('', {'server_url': 'https://user:url-password-canary@calendar.example/',
          'calendar_url': 'https://calendar.example/events/'}, 'url-password-canary'),
    ('', {'server_url': 'https://calendar.example:port-secret-canary/',
          'calendar_url': 'https://calendar.example/events/'}, 'port-secret-canary'),
    ('/missing/connect', {'username': 'user', 'password': 123456789, 'auth_type': 'basic',
                          'calendar_url': 'https://calendar.example/events/'}, '123456789'),
    ('/missing/discover', {'username': 'user', 'password': {'private': 'password-object-canary'},
                           'auth_type': 'basic'}, 'password-object-canary'),
    ('/missing/connect', {'username': 'user', 'password': 'password-list-canary',
                          'auth_type': ['auth-list-canary'],
                          'calendar_url': 'https://calendar.example/events/'}, 'auth-list-canary'),
    ('/missing/discover', {'username': 'user', 'password': 'private', 'auth_type': 'basic',
                           'api_key': 'extra-value-canary'}, 'extra-value-canary'),
    ('/missing/discover', {'username': 'user', 'password': 'private', 'auth_type': 'basic',
                           'extra-name-canary': 'value'}, 'extra-name-canary'),
    ('/missing/connect', {'username': 'user', 'password': 'private', 'auth_type': 'basic',
                          'calendar_url': 'https://user:calendar-password-canary@calendar.example/events/'},
     'calendar-password-canary'),
])
def test_validation_never_echoes_credential_material(client, endpoint, payload, canary):
    response = client.post('/api/calendar/connections' + endpoint, json=payload)
    assert response.status_code == 422
    assert canary not in response.text
    for error in response.json()['detail']:
        assert 'input' not in error
        assert 'ctx' not in error


def test_invalid_json_body_is_not_echoed(client):
    response = client.post('/api/calendar/connections/missing/connect',
                           content='{"password": json-password-canary',
                           headers={'Content-Type': 'application/json'})
    assert response.status_code == 422
    assert 'json-password-canary' not in response.text


def test_other_resource_validation_is_unchanged(client):
    response = client.post('/api/tasks', json={})
    assert response.status_code == 422
    assert any(error['loc'] == ['body', 'title'] for error in response.json()['detail'])
