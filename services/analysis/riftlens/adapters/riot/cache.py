from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from gzip import GzipFile
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS riot_cache (
    url_hash TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    status INTEGER NOT NULL,
    ttl_expires_at INTEGER,
    size INTEGER NOT NULL,
    created_at INTEGER NOT NULL
)
"""


@dataclass(frozen=True)
class CacheLookup:
    status: int
    body: bytes


def _strip_key(url: str) -> str:
    parts = urlsplit(url)
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in {"api_key", "api-key", "x-riot-token"}
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


class RiotCache:
    def __init__(self, cache_dir: Path, index_path: Path | None = None) -> None:
        self._root = cache_dir / "riot"
        self._root.mkdir(parents=True, exist_ok=True)
        self._index_path = index_path or (cache_dir / "riot_cache.sqlite3")
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_CREATE_SQL)

    def key(self, url: str) -> str:
        """Return sha256 of the URL with API key query params removed. Assumes a full URL."""
        return hashlib.sha256(_strip_key(url).encode("utf-8")).hexdigest()

    def get(self, url: str) -> bytes | None:
        """Return a gzip-decompressed 2xx body, or None. Assumes negative entries are not bodies."""
        hit = self.lookup(url)
        if hit is None or hit.status >= 400:
            return None
        return hit.body

    def lookup(self, url: str) -> CacheLookup | None:
        """Return a live cache row. Assumes expired rows should be treated as missing."""
        digest = self.key(url)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status, ttl_expires_at FROM riot_cache WHERE url_hash = ?",
                (digest,),
            ).fetchone()
        if row is None:
            return None
        status, ttl_expires_at = int(row[0]), row[1]
        if ttl_expires_at is not None and int(ttl_expires_at) <= int(time.time()):
            return None
        path = self._blob_path(digest)
        if not path.exists():
            return None
        return CacheLookup(status=status, body=_gunzip(path.read_bytes()))

    def put(self, url: str, body: bytes, ttl_s: int | None) -> None:
        """Store a successful body forever when ttl_s is None. Assumes body is raw JSON bytes."""
        self._write(url, status=200, body=body, ttl_s=ttl_s)

    def put_negative(self, url: str, status: int, ttl_s: int) -> None:
        """Store a negative cache entry. Assumes status is an HTTP error code."""
        self._write(url, status=status, body=b"", ttl_s=ttl_s)

    def _write(self, url: str, status: int, body: bytes, ttl_s: int | None) -> None:
        digest = self.key(url)
        path = self._blob_path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_gzip(body))
        expires = None if ttl_s is None else int(time.time()) + int(ttl_s)
        clean = _strip_key(url)
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO riot_cache (url_hash, url, status, ttl_expires_at, size, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(url_hash) DO UPDATE SET
                    url = excluded.url,
                    status = excluded.status,
                    ttl_expires_at = excluded.ttl_expires_at,
                    size = excluded.size,
                    created_at = excluded.created_at
                """,
                (digest, clean, int(status), expires, len(body), now),
            )

    def _blob_path(self, digest: str) -> Path:
        return self._root / digest[:2] / f"{digest}.json.gz"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._index_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


def _gzip(body: bytes) -> bytes:
    buf = BytesIO()
    with GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(body)
    return buf.getvalue()


def _gunzip(blob: bytes) -> bytes:
    with GzipFile(fileobj=BytesIO(blob), mode="rb") as gz:
        return gz.read()
