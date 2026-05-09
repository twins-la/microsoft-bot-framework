"""SQLite implementation of the Microsoft Bot Framework twin's TwinStorage.

Persistent across restarts; configurable via ``TWIN_DB_PATH``.

Every resource table carries a ``tenant_id`` column. Twin Plane operations
scope by ``tenant_id``; provider operations scope by app_id / bot_id /
conversation_id, and each row carries the ``tenant_id`` so isolation can
be enforced at the Twin Plane.
"""

import json
import sqlite3
import threading
from typing import Optional

from twins_microsoft_bot_framework.storage import TwinStorage


_VALID_FEEDBACK_COLUMNS = frozenset({"status", "date_updated"})


class SQLiteStorage(TwinStorage):
    """SQLite-backed storage for the Microsoft Bot Framework twin."""

    def __init__(self, db_path: str = "data/twin.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS bots (
                        app_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        app_password_hash TEXT NOT NULL,
                        messaging_endpoint TEXT NOT NULL,
                        friendly_name TEXT NOT NULL DEFAULT '',
                        date_created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_bots_tenant ON bots(tenant_id);

                    CREATE TABLE IF NOT EXISTS bot_instances (
                        bot_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        app_id TEXT NOT NULL,
                        trusted_openid_url TEXT NOT NULL,
                        friendly_name TEXT NOT NULL DEFAULT '',
                        date_created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_instances_tenant ON bot_instances(tenant_id);
                    CREATE INDEX IF NOT EXISTS idx_instances_app_id ON bot_instances(app_id);

                    CREATE TABLE IF NOT EXISTS conversations (
                        id TEXT PRIMARY KEY,
                        bot_app_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        channel_id TEXT NOT NULL,
                        service_url TEXT NOT NULL,
                        date_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_conv_bot ON conversations(bot_app_id);
                    CREATE INDEX IF NOT EXISTS idx_conv_tenant ON conversations(tenant_id);

                    CREATE TABLE IF NOT EXISTS activities (
                        id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        from_id TEXT NOT NULL DEFAULT '',
                        recipient_id TEXT NOT NULL DEFAULT '',
                        channel_id TEXT NOT NULL DEFAULT 'msteams',
                        service_url TEXT NOT NULL DEFAULT '',
                        text TEXT NOT NULL DEFAULT '',
                        reply_to_id TEXT NOT NULL DEFAULT '',
                        raw_json TEXT NOT NULL,
                        date_created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_activities_conv ON activities(conversation_id);
                    CREATE INDEX IF NOT EXISTS idx_activities_tenant ON activities(tenant_id);

                    CREATE TABLE IF NOT EXISTS inbox_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        bot_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        date_created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_inbox_bot ON inbox_messages(bot_id);

                    CREATE TABLE IF NOT EXISTS signing_keys (
                        kid TEXT PRIMARY KEY,
                        private_pem TEXT NOT NULL,
                        public_pem TEXT NOT NULL,
                        date_created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS feedback (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        body TEXT NOT NULL,
                        category TEXT NOT NULL DEFAULT '',
                        context_json TEXT NOT NULL DEFAULT '{}',
                        status TEXT NOT NULL DEFAULT 'pending',
                        date_created TEXT NOT NULL,
                        date_updated TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_feedback_tenant ON feedback(tenant_id);

                    CREATE TABLE IF NOT EXISTS logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tenant_id TEXT NOT NULL,
                        record_json TEXT NOT NULL,
                        timestamp TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_logs_tenant ON logs(tenant_id);
                    """
                )
                conn.commit()
            finally:
                conn.close()

    # -- bots --

    def create_bot(
        self,
        *,
        tenant_id: str,
        app_id: str,
        app_password_hash: str,
        messaging_endpoint: str,
        friendly_name: str,
    ) -> dict:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO bots (app_id, tenant_id, app_password_hash, messaging_endpoint, friendly_name) VALUES (?, ?, ?, ?, ?)",
                    (app_id, tenant_id, app_password_hash, messaging_endpoint, friendly_name),
                )
                conn.commit()
            finally:
                conn.close()
        return {
            "app_id": app_id,
            "tenant_id": tenant_id,
            "app_password_hash": app_password_hash,
            "messaging_endpoint": messaging_endpoint,
            "friendly_name": friendly_name,
        }

    def get_bot(self, app_id: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM bots WHERE app_id = ?", (app_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_bots(self, tenant_id: Optional[str] = None) -> list[dict]:
        conn = self._get_conn()
        try:
            if tenant_id is None:
                rows = conn.execute("SELECT * FROM bots ORDER BY app_id").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM bots WHERE tenant_id = ? ORDER BY app_id", (tenant_id,)
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # -- bot_instances --

    def create_bot_instance(
        self,
        *,
        tenant_id: str,
        bot_id: str,
        app_id: str,
        trusted_openid_url: str,
        friendly_name: str,
    ) -> dict:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO bot_instances (bot_id, tenant_id, app_id, trusted_openid_url, friendly_name) VALUES (?, ?, ?, ?, ?)",
                    (bot_id, tenant_id, app_id, trusted_openid_url, friendly_name),
                )
                conn.commit()
            finally:
                conn.close()
        return {
            "bot_id": bot_id,
            "tenant_id": tenant_id,
            "app_id": app_id,
            "trusted_openid_url": trusted_openid_url,
            "friendly_name": friendly_name,
        }

    def get_bot_instance(self, bot_id: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM bot_instances WHERE bot_id = ?", (bot_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_bot_instance_by_app_id(self, app_id: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM bot_instances WHERE app_id = ?", (app_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_bot_instances(self, tenant_id: Optional[str] = None) -> list[dict]:
        conn = self._get_conn()
        try:
            if tenant_id is None:
                rows = conn.execute(
                    "SELECT * FROM bot_instances ORDER BY bot_id"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM bot_instances WHERE tenant_id = ? ORDER BY bot_id",
                    (tenant_id,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # -- conversations + activities --

    def upsert_conversation(self, data: dict) -> dict:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """
                    INSERT INTO conversations (id, bot_app_id, tenant_id, channel_id, service_url)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        channel_id = excluded.channel_id,
                        service_url = excluded.service_url,
                        date_updated = CURRENT_TIMESTAMP
                    """,
                    (
                        data["id"],
                        data["bot_app_id"],
                        data["tenant_id"],
                        data["channel_id"],
                        data["service_url"],
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return self.get_conversation(data["id"]) or data

    def get_conversation(self, conversation_id: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def create_activity(self, data: dict) -> dict:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """
                    INSERT INTO activities
                        (id, conversation_id, tenant_id, direction, from_id, recipient_id,
                         channel_id, service_url, text, reply_to_id, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["id"],
                        data["conversation_id"],
                        data["tenant_id"],
                        data["direction"],
                        data.get("from_id", ""),
                        data.get("recipient_id", ""),
                        data.get("channel_id", "msteams"),
                        data.get("service_url", ""),
                        data.get("text", ""),
                        data.get("reply_to_id", ""),
                        json.dumps(data.get("raw_json", {})),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return data

    def list_activities(
        self,
        *,
        conversation_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> list[dict]:
        conn = self._get_conn()
        try:
            sql = "SELECT * FROM activities WHERE 1=1"
            params: list = []
            if conversation_id is not None:
                sql += " AND conversation_id = ?"
                params.append(conversation_id)
            if tenant_id is not None:
                sql += " AND tenant_id = ?"
                params.append(tenant_id)
            sql += " ORDER BY date_created"
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_activity(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def _row_to_activity(row) -> dict:
        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "tenant_id": row["tenant_id"],
            "direction": row["direction"],
            "from_id": row["from_id"],
            "recipient_id": row["recipient_id"],
            "channel_id": row["channel_id"],
            "service_url": row["service_url"],
            "text": row["text"],
            "reply_to_id": row["reply_to_id"],
            "raw_json": json.loads(row["raw_json"] or "{}"),
            "date_created": row["date_created"],
        }

    # -- inbox --

    def append_inbox(self, bot_id: str, activity: dict) -> dict:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO inbox_messages (bot_id, payload_json) VALUES (?, ?)",
                    (bot_id, json.dumps(activity)),
                )
                conn.commit()
            finally:
                conn.close()
        return activity

    def list_inbox(self, bot_id: str, *, limit: int = 100) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT id, payload_json, date_created FROM inbox_messages WHERE bot_id = ? ORDER BY id DESC LIMIT ?",
                (bot_id, limit),
            ).fetchall()
            out = []
            for r in rows:
                payload = json.loads(r["payload_json"])
                payload["_inbox_id"] = r["id"]
                payload["_received_at"] = r["date_created"]
                out.append(payload)
            return out
        finally:
            conn.close()

    # -- signing keys --

    def get_signing_key(self) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT kid, private_pem, public_pem FROM signing_keys ORDER BY date_created LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def put_signing_key(self, *, kid: str, private_pem: str, public_pem: str) -> dict:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO signing_keys (kid, private_pem, public_pem) VALUES (?, ?, ?)",
                    (kid, private_pem, public_pem),
                )
                conn.commit()
            finally:
                conn.close()
        return {"kid": kid, "private_pem": private_pem, "public_pem": public_pem}

    def get_or_create_signing_key(self, generator) -> dict:
        # `self._lock` is held across the entire SELECT-then-INSERT, so two
        # concurrent threads (or gunicorn workers via the connection-level lock)
        # cannot both observe "no key" and both generate. Postgres serialization
        # for the cloud path uses pg_advisory_xact_lock — see twins-la/cloud
        # twins_cloud/storage_postgres_microsoft_bot_framework.py.
        # See twins-la/microsoft-bot-framework#2 for the race that motivated this.
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT kid, private_pem, public_pem FROM signing_keys "
                    "ORDER BY date_created LIMIT 1"
                ).fetchone()
                if row:
                    return dict(row)
                kid, private_pem, public_pem = generator()
                conn.execute(
                    "INSERT INTO signing_keys (kid, private_pem, public_pem) VALUES (?, ?, ?)",
                    (kid, private_pem, public_pem),
                )
                conn.commit()
            finally:
                conn.close()
        return {"kid": kid, "private_pem": private_pem, "public_pem": public_pem}

    # -- feedback --

    def create_feedback(self, data: dict) -> dict:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """
                    INSERT INTO feedback
                        (id, tenant_id, body, category, context_json, status, date_created, date_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["id"],
                        data["tenant_id"],
                        data["body"],
                        data.get("category", ""),
                        json.dumps(data.get("context", {}) or {}),
                        data.get("status", "pending"),
                        data["date_created"],
                        data["date_updated"],
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return self.get_feedback(data["id"])

    def get_feedback(self, feedback_id: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM feedback WHERE id = ?", (feedback_id,)
            ).fetchone()
            return self._row_to_feedback(row) if row else None
        finally:
            conn.close()

    def list_feedback(
        self,
        *,
        status: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> list[dict]:
        conn = self._get_conn()
        try:
            sql = "SELECT * FROM feedback WHERE 1=1"
            params: list = []
            if status:
                sql += " AND status = ?"
                params.append(status)
            if tenant_id is not None:
                sql += " AND tenant_id = ?"
                params.append(tenant_id)
            sql += " ORDER BY date_created DESC"
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_feedback(r) for r in rows]
        finally:
            conn.close()

    def update_feedback(self, feedback_id: str, updates: dict) -> Optional[dict]:
        cols = [k for k in updates.keys() if k in _VALID_FEEDBACK_COLUMNS]
        if not cols:
            return self.get_feedback(feedback_id)
        sql = f"UPDATE feedback SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?"
        params = [updates[c] for c in cols] + [feedback_id]
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(sql, params)
                conn.commit()
            finally:
                conn.close()
        return self.get_feedback(feedback_id)

    @staticmethod
    def _row_to_feedback(row) -> dict:
        return {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "body": row["body"],
            "category": row["category"],
            "context": json.loads(row["context_json"] or "{}"),
            "status": row["status"],
            "date_created": row["date_created"],
            "date_updated": row["date_updated"],
        }

    # -- logs --

    def append_log(self, entry: dict) -> None:
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO logs (tenant_id, record_json, timestamp) VALUES (?, ?, ?)",
                    (
                        entry.get("tenant_id", ""),
                        json.dumps(entry),
                        entry.get("timestamp", ""),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def list_logs(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        tenant_id: Optional[str] = None,
    ) -> list[dict]:
        conn = self._get_conn()
        try:
            sql = "SELECT id, record_json FROM logs"
            params: list = []
            if tenant_id is not None:
                sql += " WHERE tenant_id = ?"
                params.append(tenant_id)
            sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(sql, params).fetchall()
            out = []
            for r in rows:
                rec = json.loads(r["record_json"])
                rec["id"] = r["id"]
                out.append(rec)
            return out
        finally:
            conn.close()
