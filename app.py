import ipaddress
import secrets
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import aiosqlite
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_file: str = "url_shortener.db"
    short_code_length: int = 8
    base_url: str = "http://localhost:8000/"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()


def is_safe_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname
        if not host:
            return False

        is_ip = False
        try:
            ipaddress.ip_address(host)
            is_ip = True
        except ValueError:
            pass

        if not is_ip:
            if "." not in host:
                return False
            if host.lower() in ("localhost", "localhost.localdomain"):
                return False

        if is_ip:
            ip = ipaddress.ip_address(host)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_unspecified
                or ip.is_multicast
                or ip.is_reserved
            ):
                return False
        return True
    except Exception:
        return False


BASE62_ALPHABET = (
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
)


def generate_base62_code(length: int) -> str:
    return "".join(secrets.choice(BASE62_ALPHABET) for _ in range(length))


class ShortenRequest(BaseModel):
    url: str = Field(..., max_length=2048)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not is_safe_url(v):
            raise ValueError(
                "The provided URL is invalid or insecure (SSRF protection)."
            )
        return v


class ShortenResponse(BaseModel):
    id: str
    short_url: str
    long_url: str
    created_at: str


class AnalyticsResponse(BaseModel):
    id: str
    long_url: str
    clicks: int
    created_at: str
    is_active: bool


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with aiosqlite.connect(settings.database_file) as db:
        await db.execute(f"""
            CREATE TABLE IF NOT EXISTS urls (
                id TEXT PRIMARY KEY CHECK(length(id) = {settings.short_code_length}),
                long_url TEXT NOT NULL,
                clicks INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1))
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_urls_long_url ON urls(long_url)"
        )
        await db.commit()
    yield


@asynccontextmanager
async def get_db():
    async with aiosqlite.connect(settings.database_file) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA synchronous = NORMAL")
        await db.execute("PRAGMA busy_timeout = 5000")
        await db.execute("PRAGMA foreign_keys = ON")
        yield db


app = FastAPI(title="URL Shortener API", lifespan=lifespan)


@app.get("/health", status_code=200)
async def health():
    return {"status": "healthy"}


@app.post("/shorten", response_model=ShortenResponse, status_code=201)
async def shorten(payload: ShortenRequest):
    async with get_db() as db:
        for _ in range(5):
            code = generate_base62_code(settings.short_code_length)
            try:
                await db.execute(
                    "INSERT INTO urls (id, long_url) VALUES (?, ?)",
                    (code, payload.url),
                )
                await db.commit()

                async with db.execute(
                    "SELECT created_at FROM urls WHERE id = ?", (code,)
                ) as cursor:
                    row = await cursor.fetchone()
                    created_at = row["created_at"] if row else ""

                return ShortenResponse(
                    id=code,
                    short_url=f"{settings.base_url.rstrip('/')}/{code}",
                    long_url=payload.url,
                    created_at=str(created_at),
                )
            except aiosqlite.IntegrityError:
                continue
        raise HTTPException(
            status_code=500,
            detail="Could not generate a unique short URL code. Please try again.",
        )


@app.get("/analytics/{short_id}", response_model=AnalyticsResponse)
async def analytics(short_id: str):
    if len(short_id) != settings.short_code_length:
        raise HTTPException(status_code=404, detail="Short URL not found")

    async with get_db() as db:
        async with db.execute(
            "SELECT id, long_url, clicks, created_at, is_active FROM urls WHERE id = ?",
            (short_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(
                    status_code=404, detail="Short URL not found"
                )
            return AnalyticsResponse(
                id=row["id"],
                long_url=row["long_url"],
                clicks=row["clicks"],
                created_at=str(row["created_at"]),
                is_active=bool(row["is_active"]),
            )


@app.get("/{short_id}")
async def redirect(short_id: str):
    if len(short_id) != settings.short_code_length:
        raise HTTPException(status_code=404, detail="Short URL not found")

    async with get_db() as db:
        async with db.execute(
            "SELECT long_url, is_active FROM urls WHERE id = ?", (short_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise HTTPException(
                    status_code=404, detail="Short URL not found"
                )

            if not row["is_active"]:
                raise HTTPException(
                    status_code=410, detail="The requested URL has been deactivated"
                )

        await db.execute(
            "UPDATE urls SET clicks = clicks + 1 WHERE id = ?", (short_id,)
        )
        await db.commit()

        return RedirectResponse(url=row["long_url"], status_code=307)