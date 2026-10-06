from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_shorten_creates_record_and_returns_metadata(monkeypatch, tmp_path):
    import app

    monkeypatch.setattr(app, 'DB_FILE', tmp_path / 'urls.db')
    app.init_db()

    response = client.post('/shorten', json={'url': 'https://example.com'})

    assert response.status_code == 200
    payload = response.json()
    assert payload['original_url'] == 'https://example.com/'
    assert 'id' in payload
    assert payload['clicks'] == 0
    assert payload['created_at']


def test_redirect_increments_click_counter(monkeypatch, tmp_path):
    import app

    monkeypatch.setattr(app, 'DB_FILE', tmp_path / 'urls.db')
    app.init_db()

    short = client.post('/shorten', json={'url': 'https://example.com/landing'}).json()
    response = client.get(f"/{short['id']}", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers['location'] == 'https://example.com/landing'

    analytics = client.get(f"/analytics/{short['id']}")
    assert analytics.status_code == 200
    assert analytics.json()['clicks'] == 1


def test_analytics_returns_404_for_missing_id(monkeypatch, tmp_path):
    import app

    monkeypatch.setattr(app, 'DB_FILE', tmp_path / 'urls.db')
    app.init_db()

    response = client.get('/analytics/does-not-exist')

    assert response.status_code == 404
    assert response.json()['detail'] == 'Short URL not found'
