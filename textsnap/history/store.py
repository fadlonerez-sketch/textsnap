"""Optional local OCR history (SQLite).

The database file is created only when the user enables history; the app
never opens it otherwise. Images are never stored. Pinned entries and
snippets are exempt from the retention period and are cleared separately.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class HistoryError(Exception):
    pass


@dataclass
class HistoryEntry:
    id: int
    created_at: float
    text: str
    language: str
    source: str
    pinned: bool
    title: str

    @property
    def preview(self) -> str:
        first = next((line.strip() for line in self.text.splitlines() if line.strip()), "")
        return first[:120]


class HistoryStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    # -- connection ----------------------------------------------------
    def open(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=5)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA secure_delete=ON")  # deleted text is overwritten on disk
                self._migrate(conn)
                self._conn = conn
            except sqlite3.Error as exc:
                raise HistoryError(f"the history database could not be opened: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @property
    def is_open(self) -> bool:
        return self._conn is not None

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise sqlite3.DatabaseError(f"history database is from a newer TextSnap (schema {version})")
        if version < 1:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    text TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    pinned INTEGER NOT NULL DEFAULT 0,
                    title TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_entries_created ON entries(created_at);
                PRAGMA user_version = 1;
            """)
        conn.commit()

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise HistoryError("history is turned off")
        return self._conn

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            try:
                cur = self._db().execute(sql, args)
                self._db().commit()
                return cur
            except sqlite3.Error as exc:
                raise HistoryError(f"history database error: {exc}") from exc

    # -- operations ----------------------------------------------------
    def add(self, text: str, language: str = "", source: str = "", pinned: bool = False,
            title: str = "", when: float | None = None) -> int:
        if not text.strip():
            raise HistoryError("empty text is not stored")
        cur = self._exec("INSERT INTO entries(created_at, text, language, source, pinned, title) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         (when if when is not None else time.time(), text, language, source, int(pinned), title))
        return int(cur.lastrowid)

    def get(self, entry_id: int) -> HistoryEntry | None:
        rows = self._query("SELECT * FROM entries WHERE id = ?", (entry_id,))
        return rows[0] if rows else None

    def search(self, query: str = "", pinned_only: bool = False, limit: int = 500) -> list[HistoryEntry]:
        sql = "SELECT * FROM entries WHERE 1=1"
        args: list = []
        if query.strip():
            sql += " AND (text LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\')"
            q = "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            args += [q, q]
        if pinned_only:
            sql += " AND pinned = 1"
        sql += " ORDER BY pinned DESC, created_at DESC, id DESC LIMIT ?"
        args.append(int(limit))
        return self._query(sql, tuple(args))

    def update_text(self, entry_id: int, text: str) -> None:
        self._exec("UPDATE entries SET text = ? WHERE id = ?", (text, entry_id))

    def set_pinned(self, entry_id: int, pinned: bool, title: str | None = None) -> None:
        if title is None:
            self._exec("UPDATE entries SET pinned = ? WHERE id = ?", (int(pinned), entry_id))
        else:
            self._exec("UPDATE entries SET pinned = ?, title = ? WHERE id = ?", (int(pinned), title, entry_id))

    def delete(self, entry_id: int) -> None:
        self._exec("DELETE FROM entries WHERE id = ?", (entry_id,))

    def clear(self, include_pinned: bool = False) -> int:
        cur = self._exec("DELETE FROM entries" + ("" if include_pinned else " WHERE pinned = 0"))
        self._vacuum()
        return cur.rowcount

    def clear_pinned(self) -> int:
        cur = self._exec("DELETE FROM entries WHERE pinned = 1")
        self._vacuum()
        return cur.rowcount

    def purge_older_than(self, days: int, now: float | None = None) -> int:
        if days <= 0:
            return 0
        cutoff = (now if now is not None else time.time()) - days * 86400
        cur = self._exec("DELETE FROM entries WHERE pinned = 0 AND created_at < ?", (cutoff,))
        return cur.rowcount

    def count(self) -> int:
        with self._lock:
            return int(self._db().execute("SELECT COUNT(*) FROM entries").fetchone()[0])

    def export(self, entry_ids: list[int], path: Path) -> int:
        entries = [e for e in (self.get(i) for i in entry_ids) if e is not None]
        blocks = []
        for e in entries:
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(e.created_at))
            header = f"--- {e.title or 'TextSnap'} | {stamp} ---"
            blocks.append(f"{header}\n{e.text}")
        Path(path).write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
        return len(entries)

    def destroy(self) -> None:
        """Close and delete the database files entirely."""
        self.close()
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.path) + suffix)
            try:
                p.unlink(missing_ok=True)
            except OSError as exc:
                raise HistoryError(f"could not delete {p.name}: {exc}") from exc

    def _vacuum(self) -> None:
        with self._lock:
            try:
                self._db().execute("VACUUM")
            except sqlite3.Error:
                pass

    def _query(self, sql: str, args: tuple) -> list[HistoryEntry]:
        with self._lock:
            try:
                rows = self._db().execute(sql, args).fetchall()
            except sqlite3.Error as exc:
                raise HistoryError(f"history database error: {exc}") from exc
        return [HistoryEntry(r[0], r[1], r[2], r[3], r[4], bool(r[5]), r[6]) for r in rows]
