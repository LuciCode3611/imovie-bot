"""Persistent SQLite storage for users and content requests.

A single small SQLite file (path configurable, next to session.json by
default). sqlite3 is sync and the workload is trivial, so all calls are
serialised through a Lock — handlers may call these directly.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class UserRow:
    user_id: int
    full_name: str
    username: str | None
    searches: int
    blocked: bool
    created_at: str
    last_seen: str


@dataclass
class RequestRow:
    id: int
    user_id: int
    user_name: str
    title: str
    note: str
    status: str  # open | done | rejected
    created_at: str


class Database:
    """Thin synchronous SQLite repository; safe for the polling loop."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(f"cannot create database directory {self._path.parent}: {exc}") from exc
        self._lock = threading.RLock()
        try:
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        except sqlite3.OperationalError as exc:
            parent = self._path.parent
            raise RuntimeError(
                f"cannot open database at {self._path.absolute()} "
                f"(directory exists: {parent.exists()}, writable: {os.access(parent, os.W_OK)}) — "
                f"set DB_PATH to a writable location such as a mounted volume: {exc}"
            ) from exc
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id    INTEGER PRIMARY KEY,
                    full_name  TEXT NOT NULL DEFAULT '',
                    username   TEXT,
                    searches   INTEGER NOT NULL DEFAULT 0,
                    blocked    INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_seen  TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS requests (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL,
                    user_name  TEXT NOT NULL DEFAULT '',
                    title      TEXT NOT NULL,
                    note       TEXT NOT NULL DEFAULT '',
                    status     TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS subtitle_files (
                    url        TEXT PRIMARY KEY,
                    file_id    TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status);
                CREATE INDEX IF NOT EXISTS idx_users_seen ON users(last_seen);
                """
            )
            self._conn.commit()

    # ----- users ----------------------------------------------------------

    @staticmethod
    def _now() -> str:
        return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")

    def upsert_user(self, user_id: int, full_name: str, username: str | None) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO users (user_id, full_name, username, searches, blocked, created_at, last_seen)
                VALUES (?, ?, ?, 0, 0, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    full_name = excluded.full_name,
                    username  = excluded.username,
                    last_seen = excluded.last_seen
                """,
                (user_id, full_name, username, self._now(), self._now()),
            )
            self._conn.commit()

    def touch_user(self, user_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE users SET last_seen = ? WHERE user_id = ?",
                (self._now(), user_id),
            )
            self._conn.commit()

    def increment_searches(self, user_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE users SET searches = searches + 1, last_seen = ? WHERE user_id = ?",
                (self._now(), user_id),
            )
            self._conn.commit()

    def is_blocked(self, user_id: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT blocked FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return bool(row and row["blocked"])

    def set_blocked(self, user_id: int, blocked: bool) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE users SET blocked = ? WHERE user_id = ?",
                (1 if blocked else 0, user_id),
            )
            self._conn.commit()

    def get_user(self, user_id: int) -> UserRow | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return self._user(row) if row else None

    def list_users(self, limit: int = 10, offset: int = 0) -> list[UserRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM users ORDER BY last_seen DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._user(r) for r in rows]

    def count_users(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"])

    def count_active_since(self, days: int = 7) -> int:
        cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=days)).isoformat(timespec="seconds")
        with self._lock:
            return int(
                self._conn.execute(
                    "SELECT COUNT(*) AS n FROM users WHERE last_seen >= ?", (cutoff,)
                ).fetchone()["n"]
            )

    def count_blocked(self) -> int:
        with self._lock:
            return int(
                self._conn.execute("SELECT COUNT(*) AS n FROM users WHERE blocked = 1").fetchone()["n"]
            )

    def total_searches(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COALESCE(SUM(searches),0) AS n FROM users").fetchone()["n"])

    @staticmethod
    def _user(row: sqlite3.Row) -> UserRow:
        return UserRow(
            user_id=row["user_id"],
            full_name=row["full_name"],
            username=row["username"],
            searches=row["searches"],
            blocked=bool(row["blocked"]),
            created_at=row["created_at"],
            last_seen=row["last_seen"],
        )

    # ----- requests --------------------------------------------------------

    def add_request(self, user_id: int, user_name: str, title: str, note: str = "") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO requests (user_id, user_name, title, note, status, created_at) "
                "VALUES (?, ?, ?, ?, 'open', ?)",
                (user_id, user_name, title.strip()[:200], note[:500], self._now()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def set_request_status(self, request_id: int, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE requests SET status = ? WHERE id = ?", (status, request_id)
            )
            self._conn.commit()

    def get_request(self, request_id: int) -> RequestRow | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM requests WHERE id = ?", (request_id,)
            ).fetchone()
        return self._request(row) if row else None

    def list_requests(self, status: str = "open", limit: int = 8, offset: int = 0) -> list[RequestRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM requests WHERE status = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            ).fetchall()
        return [self._request(r) for r in rows]

    def count_requests(self, status: str | None = None) -> int:
        with self._lock:
            if status is None:
                row = self._conn.execute("SELECT COUNT(*) AS n FROM requests").fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM requests WHERE status = ?", (status,)
                ).fetchone()
        return int(row["n"])

    def count_open_requests(self) -> int:
        return self.count_requests("open")

    @staticmethod
    def _request(row: sqlite3.Row) -> RequestRow:
        return RequestRow(
            id=row["id"],
            user_id=row["user_id"],
            user_name=row["user_name"],
            title=row["title"],
            note=row["note"],
            status=row["status"],
            created_at=row["created_at"],
        )

    # ----- subtitle archive cache -----------------------------------------

    def subtitle_file_id(self, url: str) -> str | None:
        """Telegram file_id of a subtitle archive the bot already uploaded.

        Re-sending by file_id is free: no download from the subtitle source, no
        server bandwidth and no share of its anonymous per-IP daily limit."""
        with self._lock:
            row = self._conn.execute(
                "SELECT file_id FROM subtitle_files WHERE url = ?", (url,)
            ).fetchone()
        return row["file_id"] if row else None

    def store_subtitle_file_id(self, url: str, file_id: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO subtitle_files (url, file_id, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET file_id = excluded.file_id
                """,
                (url, file_id, self._now()),
            )
            self._conn.commit()

    def forget_subtitle_file_id(self, url: str) -> None:
        """Drop a cached file_id Telegram stopped accepting."""
        with self._lock:
            self._conn.execute("DELETE FROM subtitle_files WHERE url = ?", (url,))
            self._conn.commit()

    def count_subtitle_files(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) AS n FROM subtitle_files").fetchone()["n"])

    def stats(self) -> dict[str, Any]:
        return {
            "users": self.count_users(),
            "active_7d": self.count_active_since(7),
            "blocked": self.count_blocked(),
            "searches": self.total_searches(),
            "requests_open": self.count_open_requests(),
            "requests_total": self.count_requests(),
            "subtitle_files": self.count_subtitle_files(),
        }
