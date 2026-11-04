"""Small SQLite store for immutable results, resolved-input snapshots, saved scenarios and jobs (S02a).

Single-host durability only: one SQLite file, WAL mode, one process. This is not a distributed or replicated store.
`MOORING_DB` selects the file; unset means an in-process database that disappears on restart (tests, local demos).
Migrations are explicit and numbered; opening a database newer than this code is refused.
"""

import json
import os
import sqlite3
import threading
from collections.abc import Iterator, MutableMapping
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1: results, snapshots, documents
    """
    CREATE TABLE results (result_id TEXT PRIMARY KEY, model TEXT, inputs_hash TEXT, resolved_inputs_hash TEXT,
                          computed_at_utc TEXT, envelope TEXT NOT NULL);
    CREATE TABLE snapshots (resolved_inputs_hash TEXT PRIMARY KEY, snapshot TEXT NOT NULL);
    CREATE TABLE docs (namespace TEXT NOT NULL, key TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (namespace, key));
    """,
    # 2: jobs
    """
    CREATE TABLE jobs (job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL, created_at_utc TEXT NOT NULL,
                       finished_at_utc TEXT, error TEXT, result TEXT);
    """,
]


class ImmutableResultError(ValueError):
    """Raised when something tries to overwrite a stored result with different content."""


class Database:
    def __init__(self, path: str | None = None):
        self.path = path if path is not None else os.environ.get("MOORING_DB", ":memory:")
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL" if self.path != ":memory:" else "PRAGMA journal_mode=MEMORY")
        self._migrate()

    def _migrate(self) -> None:
        with self.lock:
            self.conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = self.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            current = row[0] or 0
            if current > len(MIGRATIONS):
                raise RuntimeError(f"database schema v{current} is newer than this code (v{len(MIGRATIONS)})")
            for n in range(current, len(MIGRATIONS)):
                self.conn.executescript("BEGIN;" + MIGRATIONS[n] + f"INSERT INTO schema_version VALUES ({n + 1}); COMMIT;")

    def schema_version(self) -> int:
        with self.lock:
            return self.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]

    def execute(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self.lock:
            self.conn.close()


_db: Database | None = None
_db_guard = threading.Lock()


def db() -> Database:
    global _db
    with _db_guard:
        if _db is None:
            _db = Database()
        return _db


def reset_db(path: str | None = None) -> Database:
    """Close and reopen the process database (tests, restart simulation)."""
    global _db
    with _db_guard:
        if _db is not None:
            _db.close()
        _db = Database(path)
        return _db


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


class ResultStore(MutableMapping):
    """result_id -> envelope dict. Write-once: re-writing identical content is a no-op, different content is an error."""

    def __setitem__(self, result_id: str, envelope: dict) -> None:
        body = canonical(envelope)
        d = db()
        with d.lock:
            old = d.execute("SELECT envelope FROM results WHERE result_id=?", (result_id,))
            if old:
                if old[0][0] != body:
                    raise ImmutableResultError(f"result '{result_id}' already stored with different content")
                return
            manifest = envelope.get("manifest") or {}
            d.execute("INSERT INTO results VALUES (?,?,?,?,?,?)",
                      (result_id, envelope.get("model"), envelope.get("inputs_hash"),
                       manifest.get("resolved_inputs_hash"), envelope.get("computed_at_utc"), body))

    def __getitem__(self, result_id: str) -> dict:
        rows = db().execute("SELECT envelope FROM results WHERE result_id=?", (result_id,))
        if not rows:
            raise KeyError(result_id)
        return json.loads(rows[0][0])

    def __delitem__(self, result_id: str) -> None:
        raise ImmutableResultError("stored results cannot be deleted")

    def __iter__(self) -> Iterator[str]:
        return iter([r[0] for r in db().execute("SELECT result_id FROM results")])

    def __len__(self) -> int:
        return db().execute("SELECT COUNT(*) FROM results")[0][0]

    def __contains__(self, result_id) -> bool:
        return bool(db().execute("SELECT 1 FROM results WHERE result_id=?", (result_id,)))


def save_snapshot(resolved_hash: str, snapshot: dict) -> None:
    """Store the resolved inputs (request plus the catalog records as they were) once per hash."""
    d = db()
    with d.lock:
        d.execute("INSERT OR IGNORE INTO snapshots VALUES (?,?)", (resolved_hash, canonical(snapshot)))


def load_snapshot(resolved_hash: str) -> dict | None:
    rows = db().execute("SELECT snapshot FROM snapshots WHERE resolved_inputs_hash=?", (resolved_hash,))
    return json.loads(rows[0][0]) if rows else None


class DocStore(MutableMapping):
    """namespace-scoped key -> pydantic model, persisted as JSON (saved scenarios and environment scenarios)."""

    def __init__(self, namespace: str, model):
        self.namespace, self.model = namespace, model

    def __setitem__(self, key: str, value) -> None:
        d = db()
        with d.lock:
            d.execute("INSERT OR REPLACE INTO docs VALUES (?,?,?)", (self.namespace, key, value.model_dump_json()))

    def __getitem__(self, key: str):
        rows = db().execute("SELECT body FROM docs WHERE namespace=? AND key=?", (self.namespace, key))
        if not rows:
            raise KeyError(key)
        return self.model.model_validate_json(rows[0][0])

    def __delitem__(self, key: str) -> None:
        d = db()
        with d.lock:
            d.execute("DELETE FROM docs WHERE namespace=? AND key=?", (self.namespace, key))

    def __iter__(self) -> Iterator[str]:
        return iter([r[0] for r in db().execute("SELECT key FROM docs WHERE namespace=? ORDER BY rowid", (self.namespace,))])

    def __len__(self) -> int:
        return db().execute("SELECT COUNT(*) FROM docs WHERE namespace=?", (self.namespace,))[0][0]

    def __contains__(self, key) -> bool:
        return bool(db().execute("SELECT 1 FROM docs WHERE namespace=? AND key=?", (self.namespace, key)))
