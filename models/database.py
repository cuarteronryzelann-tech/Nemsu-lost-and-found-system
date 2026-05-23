"""
models/database.py - Database Connection Manager (Optimized)
=============================================================
Supports two modes:
  1. TURSO (cloud SQLite, free) — set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN
  2. Local SQLite (fallback)    — used when env vars are not set

Optimization changes:
  - Local SQLite now uses a persistent connection pool (threading.local)
    instead of opening/closing a new connection on every request.
  - WAL journal mode + optimized PRAGMAs applied once at pool init.
  - Connection pooling eliminates the per-request open/close overhead
    which was the #1 source of lag on the local/Render SQLite path.
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
        # Performance PRAGMAs — applied once per connection
        conn.execute("PRAGMA journal_mode=WAL")       # concurrent reads
        conn.execute("PRAGMA synchronous=NORMAL")     # safe + faster than FULL
        conn.execute("PRAGMA cache_size=-8000")       # 8 MB page cache
        conn.execute("PRAGMA temp_store=MEMORY")      # temp tables in RAM
        conn.execute("PRAGMA mmap_size=134217728")    # 128 MB memory-mapped I/O
        _local.conn = conn
    return conn


def get_connection(retries: int = 3, backoff: float = 0.5):
    if USE_TURSO:
        import libsql_experimental as libsql
        last_err = None
        for attempt in range(retries):
            try:
                conn = libsql.connect(
                    database=TURSO_DATABASE_URL,
                    auth_token=TURSO_AUTH_TOKEN,
                )
                return TursoConnection(conn)
            except Exception as e:
                last_err = e
                if attempt < retries - 1:
                    time.sleep(backoff * (2 ** attempt))  # 0.5s, 1s, 2s
        raise RuntimeError(f"Turso DB error after {retries} attempts: {last_err}") from last_err
    return _LocalConnection(_get_local_conn())


# ---------------------------------------------------------------------------
# Lightweight wrapper for the pooled local connection
# ---------------------------------------------------------------------------

class _LocalConnection:
    """
    Wraps a thread-local sqlite3.Connection so it looks like the Turso wrapper
    (context-manager support, .cursor(), .commit(), .close()).
    close() is a no-op — the connection stays open for the thread's lifetime.
    """
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
# Turso wrapper — sqlite3-compatible interface (unchanged)
# ---------------------------------------------------------------------------

class TursoConnection:
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
        try:
            if params is not None:
                self._cur.execute(sql, tuple(params))
            else:
                self._cur.execute(sql)
            self.lastrowid = getattr(self._cur, "lastrowid", None)
        except Exception as e:
            raise RuntimeError(f"Turso DB error: {e}") from e
        return self

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

    On Vercel (serverless), every cold start imports app.py and calls this.
    The module-level ``_db_initialized`` flag ensures the schema migration
    only runs *once* per Python process, preventing a burst of concurrent
    Turso connections that exhausts the free-tier connection limit.

    Set SKIP_INIT_DB=1 to skip entirely (e.g. if you run migrations
    separately in a one-off script).
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
        # New composite indexes for hot queries
        "CREATE INDEX IF NOT EXISTS idx_items_status_type  ON items(status, type)",
        "CREATE INDEX IF NOT EXISTS idx_notif_uid_read     ON notifications(user_id, is_read)",
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
