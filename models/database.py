"""
models/database.py - Database Connection Manager
=================================================
Supports two modes:
  1. TURSO (cloud SQLite, free) — set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN
  2. Local SQLite (fallback)    — used when env vars are not set

Key fix for "Database connections limit exceeded" on Turso free tier:
  - A single TursoConnection is cached per process (_turso_conn).
  - get_connection() reuses it instead of opening a new one each request.
  - The cached connection is validated before reuse; if stale, it reconnects.
  - init_db() is guarded so it only runs once per process AND sets
    SKIP_INIT_DB=1 pattern so cold-starts don't all race to create the schema.
  - All callers should use `with get_connection() as conn:` — the context
    manager commits on success and closes (no-op for pooled) on exit.
"""

import os
import sqlite3
import threading
import time
from config import Config

TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL", "").strip()
TURSO_AUTH_TOKEN   = os.environ.get("TURSO_AUTH_TOKEN",   "").strip()
USE_TURSO = bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)

SKIP_INIT_DB = os.environ.get("SKIP_INIT_DB", "").strip() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# Thread-local SQLite connection pool (local mode only)
# ---------------------------------------------------------------------------
_local = threading.local()


def _get_local_conn():
    """Return a cached per-thread SQLite connection, creating it if needed."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(Config.DATABASE_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-8000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=134217728")
        _local.conn = conn
    return conn


# ---------------------------------------------------------------------------
# Turso connection pool — ONE connection reused per process
# ---------------------------------------------------------------------------
_turso_conn = None
_turso_lock = threading.Lock()


def _get_turso_conn(retries: int = 5, backoff: float = 0.3):
    """
    Return the cached process-level Turso connection, creating it if needed.
    This is the KEY fix: Turso free tier allows very few concurrent connections.
    Reusing one connection per Vercel function instance keeps us well within
    the limit even when many requests hit the same warm instance.
    """
    global _turso_conn
    # Fast path — already have a good connection
    if _turso_conn is not None:
        try:
            # Cheap ping to verify the connection is still alive
            _turso_conn._conn.execute("SELECT 1")
            return _turso_conn
        except Exception:
            _turso_conn = None  # stale — fall through to reconnect

    with _turso_lock:
        # Re-check inside the lock
        if _turso_conn is not None:
            return _turso_conn

        import libsql_experimental as libsql
        last_err = None
        for attempt in range(retries):
            try:
                conn = libsql.connect(
                    database=TURSO_DATABASE_URL,
                    auth_token=TURSO_AUTH_TOKEN,
                )
                _turso_conn = _PooledTursoConnection(conn)
                return _turso_conn
            except Exception as e:
                last_err = e
                if attempt < retries - 1:
                    time.sleep(backoff * (2 ** attempt))  # 0.3s, 0.6s, 1.2s …
        raise RuntimeError(
            f"Turso DB error after {retries} attempts: {last_err}"
        ) from last_err


def get_connection(retries: int = 5, backoff: float = 0.3):
    if USE_TURSO:
        return _get_turso_conn(retries=retries, backoff=backoff)
    return _LocalConnection(_get_local_conn())


# ---------------------------------------------------------------------------
# Lightweight wrapper for the pooled local connection
# ---------------------------------------------------------------------------

class _LocalConnection:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        self._conn.commit()

    def close(self):
        pass  # keep alive — pooled

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self._conn.rollback()
        else:
            self._conn.commit()


# ---------------------------------------------------------------------------
# Pooled Turso wrapper
# close() is a no-op so callers' `finally: conn.close()` doesn't kill the pool.
# ---------------------------------------------------------------------------

class _PooledTursoConnection:
    """
    Wraps a single libsql connection that lives for the process lifetime.
    Exposes the same interface as TursoConnection but never closes the
    underlying connection — callers' close() calls are silently ignored.
    """
    def __init__(self, conn):
        self._conn = conn
        self._lock = threading.Lock()  # serialise concurrent request access

    def cursor(self):
        return TursoCursor(self._conn.cursor())

    def commit(self):
        try:
            self._conn.commit()
        except Exception:
            pass

    def close(self):
        pass  # intentional no-op — keep the connection alive

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if not exc_type:
                try:
                    self._conn.commit()
                except Exception:
                    pass
        finally:
            self._lock.release()


# ---------------------------------------------------------------------------
# Turso cursor / row wrappers (unchanged)
# ---------------------------------------------------------------------------

class TursoConnection:
    """Legacy non-pooled wrapper kept for compatibility; not used by get_connection()."""
    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return TursoCursor(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not exc_type:
            try:
                self._conn.commit()
            except Exception:
                pass
        self.close()


class TursoCursor:
    def __init__(self, cursor):
        self._cur = cursor
        self.lastrowid = None

    @property
    def description(self):
        return self._cur.description

    @property
    def rowcount(self):
        return getattr(self._cur, "rowcount", -1)

    def execute(self, sql, params=None):
        global _turso_conn
        _retries = 3
        _delay = 0.2
        for _attempt in range(_retries):
            try:
                if params is not None:
                    self._cur.execute(sql, tuple(params))
                else:
                    self._cur.execute(sql)
                self.lastrowid = getattr(self._cur, "lastrowid", None)
                return self
            except Exception as e:
                _msg = str(e)
                # On connection limit error: invalidate pool and retry
                if "connections limit" in _msg or "stream error" in _msg:
                    with _turso_lock:
                        _turso_conn = None  # force reconnect on next call
                    if _attempt < _retries - 1:
                        time.sleep(_delay * (2 ** _attempt))
                        # Re-acquire a fresh cursor from the new connection
                        try:
                            _new_conn = _get_turso_conn()
                            self._cur = _new_conn._conn.cursor()
                        except Exception:
                            pass
                        continue
                raise RuntimeError(f"Turso DB error: {e}") from e
        raise RuntimeError("Turso DB error: max retries exceeded")

    def executemany(self, sql, seq_of_params):
        try:
            self._cur.executemany(sql, [tuple(p) for p in seq_of_params])
        except Exception as e:
            raise RuntimeError(f"Turso DB error: {e}") from e

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        return TursoRow(row, self._cur.description)

    def fetchall(self):
        rows = self._cur.fetchall()
        desc = self._cur.description
        return [TursoRow(r, desc) for r in rows]

    def __iter__(self):
        desc = self._cur.description
        for row in self._cur:
            yield TursoRow(row, desc)


class TursoRow:
    def __init__(self, raw_row, description):
        self._values = list(raw_row)
        if description:
            self._keys = [col[0] for col in description]
            self._map  = dict(zip(self._keys, self._values))
        else:
            self._keys = []
            self._map  = {}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._map[key]

    def __iter__(self):
        return iter(self._values)

    def keys(self):
        return self._keys

    def get(self, key, default=None):
        return self._map.get(key, default)

    def __contains__(self, key):
        return key in self._map


# ---------------------------------------------------------------------------
# Schema init
# ---------------------------------------------------------------------------

_db_initialized = False
_db_init_lock = threading.Lock()


def init_db():
    """Initialize the database schema.

    On Vercel (serverless) every cold start imports app.py and calls this.
    The module-level ``_db_initialized`` flag ensures the schema migration
    only runs *once* per Python process.

    Set SKIP_INIT_DB=1 to skip entirely (e.g. if you run migrations
    separately in a one-off script).  This is strongly recommended for
    production Vercel deployments — run migrations once locally or in a
    release command, then set SKIP_INIT_DB=1 so cold starts don't open
    an extra connection just to run CREATE TABLE IF NOT EXISTS.
    """
    global _db_initialized
    if SKIP_INIT_DB:
        return
    if _db_initialized:
        return
    with _db_init_lock:
        if _db_initialized:
            return
        conn = get_connection()
        try:
            cursor = conn.cursor()
            _init_schema(cursor)
            conn.commit()
        finally:
            conn.close()
        _db_initialized = True


def _init_schema(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id         TEXT UNIQUE NOT NULL,
            full_name          TEXT NOT NULL,
            email              TEXT UNIQUE NOT NULL,
            role               TEXT NOT NULL DEFAULT 'user',
            phone              TEXT,
            course             TEXT,
            year_level         TEXT,
            profile_picture    TEXT,
            profile_pic_status TEXT DEFAULT 'none',
            is_registered      INTEGER NOT NULL DEFAULT 0,
            last_active        TEXT,
            created_at         TEXT,
            disable_until      TEXT,
            is_online          INTEGER DEFAULT 0
        )
    """)
    _migrate(cursor, "users", [
        ("phone",              "TEXT"),
        ("course",             "TEXT"),
        ("year_level",         "TEXT"),
        ("is_registered",      "INTEGER NOT NULL DEFAULT 0"),
        ("profile_picture",    "TEXT"),
        ("profile_pic_status", "TEXT DEFAULT 'none'"),
        ("last_active",        "TEXT"),
        ("created_at",         "TEXT"),
        ("disable_until",      "TEXT"),
        ("is_online",          "INTEGER DEFAULT 0"),
    ])

    import hashlib
    from datetime import datetime
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    admin_sid = hashlib.sha256(b"admin").hexdigest()
    cursor.execute("""
        INSERT INTO users (student_id, full_name, email, role, is_registered, last_active, created_at)
        VALUES (?, 'Administrator', 'admin@nemsu.edu.ph', 'admin', 1, ?, ?)
        ON CONFLICT(email) DO UPDATE SET role = 'admin', is_registered = 1
    """, (admin_sid, now, now))

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT NOT NULL,
            description    TEXT,
            category       TEXT,
            type           TEXT NOT NULL,
            status         TEXT DEFAULT 'pending',
            location       TEXT NOT NULL,
            pickup_lat     REAL,
            pickup_lng     REAL,
            pickup_address TEXT,
            date_reported  TEXT NOT NULL,
            time_found     TEXT,
            image_filename TEXT,
            reported_by    INTEGER,
            approved_by    INTEGER,
            created_at     TEXT,
            FOREIGN KEY (reported_by) REFERENCES users(id),
            FOREIGN KEY (approved_by) REFERENCES users(id)
        )
    """)
    _migrate(cursor, "items", [
        ("image_filename", "TEXT"),
        ("pickup_lat",     "REAL"),
        ("pickup_lng",     "REAL"),
        ("pickup_address", "TEXT"),
        ("found_at",       "TEXT"),   # timestamp when marked returned/found
        ("found_by",       "INTEGER"),  # user_id of the person who returned it
    ])

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id           INTEGER NOT NULL,
            claimant_id       INTEGER NOT NULL,
            student_id_text   TEXT NOT NULL,
            full_name_text    TEXT NOT NULL,
            last_location     TEXT NOT NULL,
            status            TEXT DEFAULT 'approved',
            pickup_location   TEXT,
            reviewed_by       INTEGER,
            confirmed_by_user INTEGER DEFAULT 0,
            created_at        TEXT,
            FOREIGN KEY (item_id)     REFERENCES items(id),
            FOREIGN KEY (claimant_id) REFERENCES users(id),
            FOREIGN KEY (reviewed_by) REFERENCES users(id)
        )
    """)
    _migrate(cursor, "claims", [
        ("confirmed_by_user",     "INTEGER DEFAULT 0"),
        ("pickup_location",       "TEXT"),
        ("finder_responded_at",   "TEXT"),
    ])

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            action     TEXT NOT NULL,
            details    TEXT,
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            message    TEXT NOT NULL,
            type       TEXT DEFAULT 'info',
            link       TEXT,
            is_read    INTEGER DEFAULT 0,
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    _migrate(cursor, "notifications", [
        ("link",    "TEXT"),
        ("is_read", "INTEGER DEFAULT 0"),
        ("type",    "TEXT DEFAULT 'info'"),
    ])

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user1_id   INTEGER NOT NULL,
            user2_id   INTEGER NOT NULL,
            item_id    INTEGER,
            created_at TEXT,
            FOREIGN KEY (user1_id) REFERENCES users(id),
            FOREIGN KEY (user2_id) REFERENCES users(id),
            FOREIGN KEY (item_id)  REFERENCES items(id),
            UNIQUE(user1_id, user2_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            sender_id       INTEGER NOT NULL,
            content         TEXT,
            image_filename  TEXT,
            is_read         INTEGER DEFAULT 0,
            created_at      TEXT,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (sender_id)       REFERENCES users(id)
        )
    """)
    _migrate(cursor, "messages", [
        ("image_filename", "TEXT"),
        ("is_deleted",     "INTEGER DEFAULT 0"),
        ("msg_type",       "TEXT DEFAULT 'text'"),   # 'text' | 'item_card'
        ("ref_item_id",    "INTEGER"),               # linked item for item_card messages
    ])

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id      INTEGER NOT NULL,
            reported_user_id INTEGER,
            reported_item_id INTEGER,
            reason           TEXT NOT NULL,
            details          TEXT,
            status           TEXT DEFAULT 'pending',
            reviewed_by      INTEGER,
            reviewed_at      TEXT,
            admin_note       TEXT,
            created_at       TEXT,
            FOREIGN KEY (reporter_id)      REFERENCES users(id),
            FOREIGN KEY (reported_user_id) REFERENCES users(id),
            FOREIGN KEY (reported_item_id) REFERENCES items(id),
            FOREIGN KEY (reviewed_by)      REFERENCES users(id)
        )
    """)

    _create_indexes(cursor)


def _create_indexes(cursor):
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_messages_conv_id   ON messages(conversation_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_sender_id ON messages(sender_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_is_read   ON messages(is_read)",
        "CREATE INDEX IF NOT EXISTS idx_messages_created   ON messages(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_conversations_u1   ON conversations(user1_id)",
        "CREATE INDEX IF NOT EXISTS idx_conversations_u2   ON conversations(user2_id)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_uid  ON notifications(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(is_read)",
        "CREATE INDEX IF NOT EXISTS idx_items_status       ON items(status)",
        "CREATE INDEX IF NOT EXISTS idx_items_type         ON items(type)",
        "CREATE INDEX IF NOT EXISTS idx_items_reported_by  ON items(reported_by)",
        "CREATE INDEX IF NOT EXISTS idx_claims_item_id     ON claims(item_id)",
        "CREATE INDEX IF NOT EXISTS idx_claims_claimant    ON claims(claimant_id)",
        "CREATE INDEX IF NOT EXISTS idx_users_email        ON users(email)",
        "CREATE INDEX IF NOT EXISTS idx_items_status_type  ON items(status, type)",
        "CREATE INDEX IF NOT EXISTS idx_notif_uid_read     ON notifications(user_id, is_read)",
        "CREATE INDEX IF NOT EXISTS idx_notif_uid_created   ON notifications(user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_msg_conv_read      ON messages(conversation_id, is_read)",
        "CREATE INDEX IF NOT EXISTS idx_items_created_desc ON items(created_at DESC)",
    ]
    for idx_sql in indexes:
        try:
            cursor.execute(idx_sql)
        except Exception:
            pass


def _migrate(cursor, table, columns):
    for col, definition in columns:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
        except Exception:
            pass