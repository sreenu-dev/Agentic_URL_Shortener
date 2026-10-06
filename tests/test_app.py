import pytest
from fastapi.testclient import TestClient

import app as app_module


@pytest.fixture
def client(monkeypatch, tmp_path):
    database_path = tmp_path / 'test_shortener.db'
    monkeypatch.setattr(app_module.settings, 'database_file', str(database_path))
    with TestClient(app_module.app) as test_client:
        yield test_client


def test_shorten_redirect_and_analytics_lifecycle(client):
    response = client.post(
        '/shorten',
        json={'url': 'https://example.com/target'},
    )

    assert response.status_code == 201
    result = response.json()
    assert result['long_url'] == 'https://example.com/target'
    assert result['id']
    assert result['short_url'].endswith(f"/{result['id']}")

    redirect = client.get(f"/{result['id']}", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers['location'] == result['long_url']

    analytics = client.get(f"/analytics/{result['id']}")
    assert analytics.status_code == 200
    assert analytics.json()['clicks'] == 1


def test_repeated_shortening_creates_distinct_short_codes(client):
    payload = {'url': 'https://example.com/'}

    first = client.post('/shorten', json=payload)
    second = client.post('/shorten', json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()['id'] != second.json()['id']

def test_list_urls_returns_short_and_destination_urls(client):
    first = client.post(
        '/shorten', json={'url': 'https://example.com/first'}
    ).json()
    second = client.post(
        '/shorten', json={'url': 'https://example.org/second'}
    ).json()

    response = client.get('/urls')

    assert response.status_code == 200
    listed_urls = response.json()
    assert len(listed_urls) == 2
    by_id = {entry['id']: entry for entry in listed_urls}
    assert by_id[first['id']] == {
        'id': first['id'],
        'short_url': first['short_url'],
        'long_url': first['long_url'],
    }
    assert by_id[second['id']] == {
        'id': second['id'],
        'short_url': second['short_url'],
        'long_url': second['long_url'],
    }


def test_list_urls_returns_empty_list_when_no_urls_exist(client):
    response = client.get('/urls')

    assert response.status_code == 200
    assert response.json() == []


def test_unknown_short_code_returns_not_found(client):
    redirect = client.get('/notfound', follow_redirects=False)

    assert redirect.status_code == 404


def test_invalid_url_and_ttl_are_rejected(client):
    invalid_url = client.post(
        '/shorten', json={'url': 'http://127.0.0.1/private'}
    )

    assert invalid_url.status_code == 422


def test_health_check_and_unknown_analytics(client):
    health = client.get('/health')
    missing = client.get('/analytics/not-found')

    assert health.status_code == 200
    assert health.json()['status'] == 'healthy'
    assert missing.status_code == 404
