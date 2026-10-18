"""Private SQLite metadata history. File contents and encryption keys are never stored."""

import asyncio
import re
import sqlite3
import time
import uuid
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import TypeVar
from urllib.parse import urlsplit

from uploadbot.models import StoredUpload, UploadOptions, UploadResult

T = TypeVar("T")


class HistoryStore:
    def __init__(self, path: Path) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Use await HistoryStore.open inside an event loop")
        self.path = path
        self._lock = asyncio.Lock()
        self._last_cleanup = 0.0
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)
        self._run(self._initialize)

    @classmethod
    async def open(cls, path: Path) -> "HistoryStore":
        return await asyncio.to_thread(cls, path)

    @staticmethod
    def _initialize(db: sqlite3.Connection) -> None:
        if db.execute("PRAGMA user_version").fetchone()[0] > 1:
            raise ValueError("History database was created by a newer version")
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS uploads (
                id TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                url TEXT NOT NULL, filename TEXT NOT NULL, size INTEGER NOT NULL,
                provider TEXT NOT NULL, delete_url TEXT, expires_at REAL,
                encrypted INTEGER NOT NULL, created_at REAL NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS uploads_owner ON uploads(user_id, created_at);
            CREATE INDEX IF NOT EXISTS uploads_created ON uploads(created_at);
            CREATE TABLE IF NOT EXISTS preferences (
                user_id INTEGER PRIMARY KEY, provider TEXT NOT NULL,
                retention_days INTEGER NOT NULL, encrypted INTEGER NOT NULL
            );
            PRAGMA user_version=1;
        """)

    def _run(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            db.create_function(
                "casefold", 1, lambda value: str(value).casefold(), deterministic=True
            )
            with db:
                return operation(db)

    async def _call(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        async with self._lock:
            task = asyncio.create_task(asyncio.to_thread(self._run, operation))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not task.cancelled():
                    task.exception()
                raise

    @staticmethod
    def _record(row: sqlite3.Row) -> StoredUpload:
        return StoredUpload(
            id=row["id"],
            user_id=row["user_id"],
            created_at=row["created_at"],
            deleted=bool(row["deleted"]),
            result=UploadResult(
                url=row["url"],
                filename=row["filename"],
                size=row["size"],
                provider=row["provider"],
                delete_url=row["delete_url"],
                expires_at=row["expires_at"],
                encrypted=bool(row["encrypted"]),
            ),
        )

    async def add(self, user_id: int, result: UploadResult) -> StoredUpload:
        if result.encrypted and urlsplit(result.url).fragment:
            raise ValueError("Encrypted upload links must not contain a key fragment")

        def insert(db: sqlite3.Connection) -> StoredUpload:
            db.execute("BEGIN IMMEDIATE")
            record = StoredUpload(uuid.uuid4().hex, user_id, result, time.time())
            db.execute(
                "INSERT INTO uploads "
                "(id, user_id, url, filename, size, provider, delete_url, expires_at, "
                "encrypted, created_at, deleted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    record.id,
                    user_id,
                    result.url,
                    result.filename,
                    result.size,
                    result.provider,
                    result.delete_url,
                    result.expires_at,
                    int(result.encrypted),
                    record.created_at,
                ),
            )

            if time.monotonic() - self._last_cleanup >= 3600:
                db.execute("DELETE FROM uploads WHERE created_at < ?", (time.time() - 30 * 86400,))
                self._last_cleanup = time.monotonic()
            db.execute(
                "DELETE FROM uploads WHERE user_id = ? AND id NOT IN "
                "(SELECT id FROM uploads WHERE user_id = ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1000)",
                (user_id, user_id),
            )
            return record

        return await self._call(insert)

    async def files(
        self, user_id: int, query: str = "", limit: int = 10, *, include_expired: bool = False
    ) -> list[StoredUpload]:
        if not 1 <= limit <= 50:
            raise ValueError("History limit must be between 1 and 50")

        def select(db: sqlite3.Connection) -> list[StoredUpload]:
            rows = db.execute(
                "SELECT * FROM uploads WHERE user_id = ? AND deleted = 0 "
                "AND instr(casefold(filename), casefold(?)) > 0 "
                "AND (? OR expires_at IS NULL OR expires_at > ?) "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, query[:200], include_expired, time.time(), limit),
            ).fetchall()
            return [self._record(row) for row in rows]

        return await self._call(select)

    async def get(self, user_id: int, identifier: str) -> StoredUpload | None:
        if not re.fullmatch(r"[0-9a-f]{8,32}", identifier):
            return None

        def select(db: sqlite3.Connection) -> StoredUpload | None:
            rows = db.execute(
                "SELECT * FROM uploads WHERE user_id = ? AND id LIKE ? AND deleted = 0 "
                "AND (expires_at IS NULL OR expires_at > ?) LIMIT 2",
                (user_id, identifier + "%", time.time()),
            ).fetchall()
            return self._record(rows[0]) if len(rows) == 1 else None

        return await self._call(select)

    async def mark_deleted(self, user_id: int, identifier: str) -> bool:
        if not re.fullmatch(r"[0-9a-f]{8,32}", identifier):
            return False

        def update(db: sqlite3.Connection) -> bool:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT id FROM uploads WHERE user_id = ? AND id LIKE ? AND deleted = 0 LIMIT 2",
                (user_id, identifier + "%"),
            ).fetchall()
            if len(rows) != 1:
                return False
            return (
                db.execute(
                    "UPDATE uploads SET deleted = 1, delete_url = NULL, url = '' "
                    "WHERE user_id = ? AND id = ? AND deleted = 0",
                    (user_id, rows[0]["id"]),
                ).rowcount
                == 1
            )

        return await self._call(update)

    async def preferences(self, user_id: int, default_provider: str) -> tuple[str, UploadOptions]:
        def select(db: sqlite3.Connection) -> tuple[str, UploadOptions]:
            row = db.execute("SELECT * FROM preferences WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                return default_provider, UploadOptions()
            return row["provider"], UploadOptions(row["retention_days"], bool(row["encrypted"]))

        return await self._call(select)

    async def set_preferences(self, user_id: int, provider: str, options: UploadOptions) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", provider):
            raise ValueError("Invalid provider name")

        def update(db: sqlite3.Connection) -> None:
            db.execute(
                "INSERT INTO preferences (user_id, provider, retention_days, encrypted) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET "
                "provider=excluded.provider, retention_days=excluded.retention_days, "
                "encrypted=excluded.encrypted",
                (user_id, provider, options.retention_days, int(options.encrypted)),
            )

        await self._call(update)
