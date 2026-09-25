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
    last_activity_at INTEGER NOT NULL DEFAULT 0,
    hardness_mode TEXT NOT NULL DEFAULT 'auto',
    fixed_hardness INTEGER NOT NULL DEFAULT 3,
    response_delay_seconds INTEGER NOT NULL DEFAULT 20
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
    reply_to_message_id INTEGER,
    reply_to_user_id INTEGER,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_time ON messages(chat_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_chat_seen ON users(chat_id, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS learned_words (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL DEFAULT 0,
    token TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    last_seen_at INTEGER NOT NULL,
    PRIMARY KEY(chat_id, user_id, token)
);

CREATE INDEX IF NOT EXISTS idx_learned_words_chat_count
ON learned_words(chat_id, user_id, count DESC);

CREATE TABLE IF NOT EXISTS avoided_addresses (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    token TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY(chat_id, user_id, token)
);

CREATE TABLE IF NOT EXISTS humor_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    style TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_humor_history_chat_user
ON humor_history(chat_id, user_id, id DESC);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(chats)").fetchall()}
            if "hardness_mode" not in columns:
                conn.execute("ALTER TABLE chats ADD COLUMN hardness_mode TEXT NOT NULL DEFAULT 'auto'")
            if "fixed_hardness" not in columns:
                conn.execute("ALTER TABLE chats ADD COLUMN fixed_hardness INTEGER NOT NULL DEFAULT 3")
            if "response_delay_seconds" not in columns:
                conn.execute("ALTER TABLE chats ADD COLUMN response_delay_seconds INTEGER NOT NULL DEFAULT 20")

            message_columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
            if "reply_to_message_id" not in message_columns:
                conn.execute("ALTER TABLE messages ADD COLUMN reply_to_message_id INTEGER")
            if "reply_to_user_id" not in message_columns:
                conn.execute("ALTER TABLE messages ADD COLUMN reply_to_user_id INTEGER")

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
        allowed = {"enabled", "roast_level", "min_interval_minutes", "silence_minutes", "last_bot_message_at", "last_activity_at", "hardness_mode", "fixed_hardness", "response_delay_seconds"}
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

    def avoid_address(self, chat_id: int, user_id: int, token: str):
        token = (token or "").strip().lower()
        if not token:
            return
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO avoided_addresses(chat_id,user_id,token,created_at)
                VALUES(?,?,?,?)
                """,
                (chat_id, user_id, token[:32], int(time.time())),
            )

    def avoided_addresses(self, chat_id: int, user_id: int) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT token FROM avoided_addresses WHERE chat_id=? AND user_id=? ORDER BY created_at ASC",
                (chat_id, user_id),
            ).fetchall()
            return [r["token"] for r in rows]

    def add_message(
        self,
        chat_id: int,
        message_id: int,
        user_id: int | None,
        username: str,
        display_name: str,
        kind: str,
        content: str,
        reply_to_message_id: int | None = None,
        reply_to_user_id: int | None = None,
    ):
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO messages(
                    chat_id,telegram_message_id,user_id,username,display_name,kind,content,
                    reply_to_message_id,reply_to_user_id,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    chat_id, message_id, user_id, username, display_name, kind, content[:2000],
                    reply_to_message_id, reply_to_user_id, now,
                ),
            )
            conn.execute("UPDATE chats SET last_activity_at=? WHERE chat_id=?", (now, chat_id))

    def add_bot_message(
        self,
        chat_id: int,
        message_id: int,
        content: str,
        reply_to_message_id: int | None = None,
        reply_to_user_id: int | None = None,
    ):
        """Сохраняет ответ Аксакала и его связь с сообщением, на которое он ответил."""
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO messages(
                    chat_id,telegram_message_id,user_id,username,display_name,kind,content,
                    reply_to_message_id,reply_to_user_id,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    chat_id, message_id, None, "", "Аксакал", "bot", content[:2000],
                    reply_to_message_id, reply_to_user_id, now,
                ),
            )

    def message_thread(self, chat_id: int, message_id: int | None, max_depth: int = 8) -> list[dict[str, Any]]:
        """Восстанавливает цепочку Telegram Reply назад от конкретного сообщения."""
        if not message_id:
            return []
        current_id = int(message_id)
        seen: set[int] = set()
        chain: list[dict[str, Any]] = []
        with self.connect() as conn:
            while current_id and current_id not in seen and len(chain) < max_depth:
                seen.add(current_id)
                row = conn.execute(
                    """
                    SELECT * FROM messages
                    WHERE chat_id=? AND telegram_message_id=?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (chat_id, current_id),
                ).fetchone()
                if not row:
                    break
                item = dict(row)
                chain.append(item)
                current_id = int(item.get("reply_to_message_id") or 0)
        chain.reverse()
        return chain

    def user_profile_summary(self, chat_id: int, user_id: int) -> dict[str, Any]:
        """Безопасный поведенческий профиль из фактов самой переписки, без догадок о личности."""
        with self.connect() as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
            if not user:
                return {}

            tokens = conn.execute(
                """
                SELECT token,count FROM learned_words
                WHERE chat_id=? AND user_id=? AND count>=2
                ORDER BY count DESC,last_seen_at DESC LIMIT 12
                """,
                (chat_id, user_id),
            ).fetchall()

            recent = conn.execute(
                """
                SELECT content,kind,created_at FROM messages
                WHERE chat_id=? AND user_id=? AND kind IN ('message','sticker')
                ORDER BY id DESC LIMIT 6
                """,
                (chat_id, user_id),
            ).fetchall()

            partners = conn.execute(
                """
                SELECT m.reply_to_user_id AS target_id,
                       COALESCE(u.display_name, '') AS display_name,
                       COUNT(*) AS cnt
                FROM messages m
                LEFT JOIN users u
                  ON u.chat_id=m.chat_id AND u.user_id=m.reply_to_user_id
                WHERE m.chat_id=? AND m.user_id=? AND m.reply_to_user_id IS NOT NULL
                  AND m.reply_to_user_id!=?
                GROUP BY m.reply_to_user_id,u.display_name
                ORDER BY cnt DESC LIMIT 3
                """,
                (chat_id, user_id, user_id),
            ).fetchall()

        info = dict(user)
        return {
            "message_count": int(info.get("message_count") or 0),
            "sticker_count": int(info.get("sticker_count") or 0),
            "reaction_count": int(info.get("reaction_count") or 0),
            "style_profile": info.get("style_profile") or "neutral",
            "frequent_phrases": [dict(x) for x in tokens],
            "recent_messages": [dict(x) for x in recent],
            "frequent_reply_targets": [dict(x) for x in partners],
        }

    def recent_humor_styles(self, chat_id: int, user_id: int, limit: int = 5) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT style FROM humor_history
                WHERE chat_id=? AND user_id=?
                ORDER BY id DESC LIMIT ?
                """,
                (chat_id, user_id, limit),
            ).fetchall()
        return [str(r["style"]) for r in rows]

    def record_humor_style(self, chat_id: int, user_id: int, style: str):
        if not style or style == "none":
            return
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO humor_history(chat_id,user_id,style,created_at) VALUES(?,?,?,?)",
                (chat_id, user_id, style[:32], int(time.time())),
            )

    def recent_bot_replies(self, chat_id: int, limit: int = 20) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT content FROM messages
                WHERE chat_id=? AND kind='bot'
                ORDER BY id DESC LIMIT ?
                """,
                (chat_id, limit),
            ).fetchall()
        return [r["content"] for r in rows if r["content"]]

    def relevant_messages(self, chat_id: int, query: str, limit: int = 8, scan: int = 600) -> list[dict[str, Any]]:
        """Дешёвая долговременная память: ищет старые сообщения по пересечению значимых слов."""
        import re
        stop = {
            "это","как","что","чтобы","когда","тогда","тут","там","где","кто","она","они","оно",
            "его","ее","её","для","про","под","над","или","если","уже","еще","ещё","вот","был","была",
            "были","будет","есть","нет","да","не","ни","ну","же","бы","ли","то","из","на","по","за","от",
            "до","во","со","мы","вы","ты","мне","тебе","ему","нам","вам","их","так","просто","очень",
        }
        endings = (
            "иями","ями","ами","ого","ему","ыми","ими","иях",
            "ах","ях","ов","ев","ей","ой","ий","ый","ая","яя","ое","ее",
            "ам","ям","ом","ем","ую","юю","у","ю","а","я","ы","и","е","о",
        )

        def term_key(word: str) -> str:
            word = word.lower().replace("ё", "е")
            if len(word) < 5:
                return word
            for ending in endings:
                if word.endswith(ending) and len(word) - len(ending) >= 4:
                    return word[:-len(ending)]
            return word

        query_norm = " ".join((query or "").lower().replace("ё", "е").split())
        qwords = {
            term_key(w)
            for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9_+-]{3,}", query_norm)
            if w not in stop
        }
        if not qwords:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE chat_id=? AND kind IN ('message','bot')
                ORDER BY id DESC LIMIT ?
                """,
                (chat_id, scan),
            ).fetchall()
        scored = []
        for row in rows:
            item = dict(row)
            content_norm = " ".join((item.get("content") or "").lower().replace("ё", "е").split())
            # Текущее сообщение уже отдельно передаётся генератору; не выдаём его за старую память.
            if item.get("kind") == "message" and content_norm == query_norm:
                continue
            words = {
                term_key(w)
                for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9_+-]{3,}", content_norm)
            }
            overlap = len(qwords & words)
            if overlap:
                scored.append((overlap, item.get("created_at", 0), item))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [item for _, _, item in scored[:limit]]

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

    def learn_tokens(self, chat_id: int, user_id: int, tokens: list[str]):
        now = int(time.time())
        cleaned = [t.strip().lower()[:64] for t in tokens if t and 2 <= len(t.strip()) <= 64]
        if not cleaned:
            return
        with self.connect() as conn:
            for token in cleaned:
                for owner_id in (0, user_id):
                    conn.execute(
                        """
                        INSERT INTO learned_words(chat_id,user_id,token,count,last_seen_at)
                        VALUES(?,?,?,?,?)
                        ON CONFLICT(chat_id,user_id,token) DO UPDATE SET
                            count=count+1,
                            last_seen_at=excluded.last_seen_at
                        """,
                        (chat_id, owner_id, token, 1, now),
                    )

    def top_learned_words(self, chat_id: int, user_id: int | None = None, limit: int = 20) -> list[dict[str, Any]]:
        owner_id = 0 if user_id is None else int(user_id)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT token,count,last_seen_at
                FROM learned_words
                WHERE chat_id=? AND user_id=?
                ORDER BY count DESC, last_seen_at DESC
                LIMIT ?
                """,
                (chat_id, owner_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_roasted(self, chat_id: int, user_id: int):
        now = int(time.time())
        with self.connect() as conn:
            conn.execute("UPDATE users SET last_roasted_at=? WHERE chat_id=? AND user_id=?", (now, chat_id, user_id))
