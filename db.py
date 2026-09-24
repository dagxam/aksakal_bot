from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from typing import Any


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS chats (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    roast_level INTEGER NOT NULL DEFAULT 3,
    min_interval_minutes INTEGER NOT NULL DEFAULT 25,
    silence_minutes INTEGER NOT NULL DEFAULT 180,
    last_bot_message_at INTEGER NOT NULL DEFAULT 0,
    last_activity_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    display_name TEXT,
    style_profile TEXT NOT NULL DEFAULT 'neutral',
    first_seen_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    last_spoken_at INTEGER NOT NULL DEFAULT 0,
    last_reaction_at INTEGER NOT NULL DEFAULT 0,
    last_sticker_at INTEGER NOT NULL DEFAULT 0,
    last_roasted_at INTEGER NOT NULL DEFAULT 0,
    message_count INTEGER NOT NULL DEFAULT 0,
    reaction_count INTEGER NOT NULL DEFAULT 0,
    sticker_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    telegram_message_id INTEGER NOT NULL,
    user_id INTEGER,
    username TEXT,
    display_name TEXT,
    kind TEXT NOT NULL,
    content TEXT,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_time ON messages(chat_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_chat_seen ON users(chat_id, last_seen_at DESC);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def ensure_chat(self, chat_id: int, title: str | None, roast_level: int, min_interval: int, silence: int):
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chats(chat_id,title,roast_level,min_interval_minutes,silence_minutes,last_activity_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title
                """,
                (chat_id, title or "", roast_level, min_interval, silence, now),
            )

    def get_chat(self, chat_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM chats WHERE chat_id=?", (chat_id,)).fetchone()
            return dict(row) if row else None

    def update_chat(self, chat_id: int, **values):
        allowed = {"enabled", "roast_level", "min_interval_minutes", "silence_minutes", "last_bot_message_at", "last_activity_at"}
        pairs = [(k, v) for k, v in values.items() if k in allowed]
        if not pairs:
            return
        sql = "UPDATE chats SET " + ", ".join(f"{k}=?" for k, _ in pairs) + " WHERE chat_id=?"
        with self.connect() as conn:
            conn.execute(sql, [v for _, v in pairs] + [chat_id])

    def touch_user(self, chat_id: int, user: dict, kind: str):
        now = int(time.time())
        user_id = int(user["id"])
        username = user.get("username") or ""
        display_name = " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x).strip() or username or str(user_id)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users(chat_id,user_id,username,display_name,first_seen_at,last_seen_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET
                    username=excluded.username,
                    display_name=excluded.display_name,
                    last_seen_at=excluded.last_seen_at
                """,
                (chat_id, user_id, username, display_name, now, now),
            )
            if kind == "message":
                conn.execute("UPDATE users SET last_spoken_at=?, message_count=message_count+1 WHERE chat_id=? AND user_id=?", (now, chat_id, user_id))
            elif kind == "reaction":
                conn.execute("UPDATE users SET last_reaction_at=?, reaction_count=reaction_count+1 WHERE chat_id=? AND user_id=?", (now, chat_id, user_id))
            elif kind == "sticker":
                conn.execute("UPDATE users SET last_sticker_at=?, sticker_count=sticker_count+1 WHERE chat_id=? AND user_id=?", (now, chat_id, user_id))
        return user_id

    def set_profile(self, chat_id: int, user_id: int, profile: str):
        with self.connect() as conn:
            conn.execute("UPDATE users SET style_profile=? WHERE chat_id=? AND user_id=?", (profile, chat_id, user_id))

    def add_message(self, chat_id: int, message_id: int, user_id: int | None, username: str, display_name: str, kind: str, content: str):
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO messages(chat_id,telegram_message_id,user_id,username,display_name,kind,content,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (chat_id, message_id, user_id, username, display_name, kind, content[:2000], now),
            )
            conn.execute("UPDATE chats SET last_activity_at=? WHERE chat_id=?", (now, chat_id))

    def recent_context(self, chat_id: int, limit: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def active_users(self, chat_id: int, since_seconds: int = 7 * 86400) -> list[dict[str, Any]]:
        cutoff = int(time.time()) - since_seconds
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM users WHERE chat_id=? AND last_seen_at>=? ORDER BY last_seen_at DESC",
                (chat_id, cutoff),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_roasted(self, chat_id: int, user_id: int):
        now = int(time.time())
        with self.connect() as conn:
            conn.execute("UPDATE users SET last_roasted_at=? WHERE chat_id=? AND user_id=?", (now, chat_id, user_id))
