# app.py
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, HttpUrl
import sqlite3
import string
import random
import logging
from datetime import datetime

# Setup basic observability
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("URLShortenerAPI")

app = FastAPI(title="Agentic URL Shortener", version="1.0")

# Database initialization
DB_FILE = "urls.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS urls (
            id TEXT PRIMARY KEY,
            original_url TEXT NOT NULL,
            created_at TEXT NOT NULL,
            clicks INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

init_db()

class URLCreate(BaseModel):
    url: HttpUrl

class URLInfo(BaseModel):
    id: str
    original_url: str
    clicks: int
    created_at: str

def generate_short_id(length=6):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

@app.post("/shorten", response_model=URLInfo)
def create_short_url(request: URLCreate):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    short_id = generate_short_id()
    created_at = datetime.utcnow().isoformat()
    
    # Safe parameterization to prevent SQL injection (Security Policy Guardrail)
    try:
        cursor.execute(
            "INSERT INTO urls (id, original_url, created_at, clicks) VALUES (?, ?, ?, ?)",
            (short_id, str(request.url), created_at, 0)
        )
        conn.commit()
        logger.info(f"URL shortened: {short_id} -> {request.url}")
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error during creation: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()

    return {"id": short_id, "original_url": str(request.url), "clicks": 0, "created_at": created_at}

@app.get("/{short_id}")
def redirect_to_url(short_id: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT original_url FROM urls WHERE id = ?", (short_id,))
    result = cursor.fetchone()
    
    if result:
        # Update analytics asynchronously in a production scenario; handled synchronously here for prototype
        cursor.execute("UPDATE urls SET clicks = clicks + 1 WHERE id = ?", (short_id,))
        conn.commit()
        conn.close()
        return RedirectResponse(url=result[0], status_code=307)
    
    conn.close()
    raise HTTPException(status_code=404, detail="Short URL not found")

@app.get("/analytics/{short_id}", response_model=URLInfo)
def get_url_analytics(short_id: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, original_url, clicks, created_at FROM urls WHERE id = ?", (short_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            "id": result[0],
            "original_url": result[1],
            "clicks": result[2],
            "created_at": result[3]
        }
        
    raise HTTPException(status_code=404, detail="Short URL not found")