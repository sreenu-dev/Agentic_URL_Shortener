import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app as app_module


@pytest.fixture
def client(monkeypatch, tmp_path):
    database_path = tmp_path / 'test_shortener.db'
    monkeypatch.setattr(app_module.settings, 'SQLITE_DB_FILE', str(database_path))
    with TestClient(app_module.app) as test_client:
        yield test_client


def test_shorten_redirect_and_analytics_lifecycle(client):
    response = client.post(
        '/shorten',
        json={'url': 'https://example.com/target', 'ttl_seconds': 3600},
    )

    assert response.status_code == 201
    result = response.json()
    assert result['original_url'] == 'https://example.com/target'
    assert result['id']
    assert result['short_url'].endswith(f"/{result['id']}")

    redirect = client.get(f"/{result['id']}", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers['location'] == result['original_url']

    analytics = client.get(f"/analytics/{result['id']}")
    assert analytics.status_code == 200
    assert analytics.json()['metrics']['total_clicks'] == 1
    assert analytics.json()['metrics']['unique_visitors_approx'] == 1


def test_custom_id_collision_returns_conflict(client):
    payload = {'url': 'https://example.com/', 'custom_id': 'custom_1'}

    assert client.post('/shorten', json=payload).status_code == 201
    assert client.post('/shorten', json=payload).status_code == 409


def test_expired_url_returns_gone(client):
    response = client.post(
        '/shorten',
        json={'url': 'https://example.com/', 'ttl_seconds': 60},
    )
    url_id = response.json()['id']

    with sqlite3.connect(app_module.settings.SQLITE_DB_FILE) as connection:
        expired_at = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        connection.execute(
            'UPDATE urls SET expires_at = ? WHERE id = ?',
            (expired_at, url_id),
        )

    redirect = client.get(f'/{url_id}', follow_redirects=False)

    assert redirect.status_code == 410


def test_invalid_url_and_ttl_are_rejected(client):
    invalid_url = client.post('/shorten', json={'url': 'not-a-url'})
    too_short_ttl = client.post(
        '/shorten',
        json={'url': 'https://example.com/', 'ttl_seconds': 30},
    )

    assert invalid_url.status_code == 422
    assert too_short_ttl.status_code == 422


def test_health_check_and_unknown_analytics(client):
    health = client.get('/health')
    missing = client.get('/analytics/not-found')

    assert health.status_code == 200
    assert health.json()['status'] == 'healthy'
    assert missing.status_code == 404
