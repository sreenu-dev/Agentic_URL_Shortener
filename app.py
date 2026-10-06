from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, HttpUrl
import sqlite3
import string
import random
import logging
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('URLShortenerAPI')

app = FastAPI(title='Agentic URL Shortener', version='1.0')
DB_FILE = Path(__file__).with_name('urls.db')


class URLCreate(BaseModel):
    url: HttpUrl = Field(..., description='The long URL to shorten.')


class URLInfo(BaseModel):
    id: str
    original_url: str
    clicks: int = 0
    created_at: str


def init_db() -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS urls (
                id TEXT PRIMARY KEY,
                original_url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                clicks INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


init_db()


def generate_short_id(length: int = 6) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(random.choice(alphabet) for _ in range(length))


@app.post('/shorten', response_model=URLInfo)
def create_short_url(payload: URLCreate):
    short_id = generate_short_id()
    created_at = datetime.now(timezone.utc).isoformat()
    original_url = str(payload.url)

    while True:
        with sqlite3.connect(DB_FILE) as conn:
            try:
                conn.execute(
                    'INSERT INTO urls (id, original_url, created_at, clicks) VALUES (?, ?, ?, ?)',
                    (short_id, original_url, created_at, 0),
                )
                conn.commit()
                logger.info('Created short code %s for %s', short_id, original_url)
                return {
                    'id': short_id,
                    'original_url': original_url,
                    'clicks': 0,
                    'created_at': created_at,
                }
            except sqlite3.IntegrityError:
                short_id = generate_short_id()
                continue
            except Exception as exc:
                logger.exception('Failed to save shortened URL: %s', exc)
                raise HTTPException(status_code=500, detail='Internal server error')


@app.get('/{short_id}')
def redirect_to_url(short_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute('SELECT original_url FROM urls WHERE id = ?', (short_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Short URL not found')

        target_url = row[0]
        conn.execute('UPDATE urls SET clicks = clicks + 1 WHERE id = ?', (short_id,))
        conn.commit()

    logger.info('Redirecting %s to %s', short_id, target_url)
    return RedirectResponse(url=target_url, status_code=307)


@app.get('/analytics/{short_id}', response_model=URLInfo)
def get_url_analytics(short_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute(
            'SELECT id, original_url, clicks, created_at FROM urls WHERE id = ?',
            (short_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail='Short URL not found')

    return {
        'id': row[0],
        'original_url': row[1],
        'clicks': row[2],
        'created_at': row[3],
    }


@app.get('/healthz')
def healthz():
    return {'status': 'ok'}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app:app', host='0.0.0.0', port=8000, reload=True)
