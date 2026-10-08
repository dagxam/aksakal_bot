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
    response_delay_seconds INTEGER NOT NULL DEFAULT 20,
    silence_nudge_count INTEGER NOT NULL DEFAULT 0,
    manual_quiet INTEGER NOT NULL DEFAULT 0,
    game_difficulty TEXT NOT NULL DEFAULT 'normal'
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

CREATE TABLE IF NOT EXISTS group_membership_cache (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(chat_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_group_membership_user
ON group_membership_cache(user_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS bot_ignored_users (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    added_by INTEGER NOT NULL DEFAULT 0,
    added_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(chat_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_bot_ignored_users_chat
ON bot_ignored_users(chat_id, added_at DESC);

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

CREATE TABLE IF NOT EXISTS bot_responses (
    chat_id INTEGER NOT NULL,
    telegram_message_id INTEGER NOT NULL,
    target_user_id INTEGER NOT NULL,
    humor_style TEXT NOT NULL,
    mode_level INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY(chat_id, telegram_message_id)
);

CREATE INDEX IF NOT EXISTS idx_bot_responses_target
ON bot_responses(chat_id, target_user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS response_feedback (
    chat_id INTEGER NOT NULL,
    bot_message_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(chat_id, bot_message_id, user_id, source)
);

CREATE INDEX IF NOT EXISTS idx_response_feedback_message
ON response_feedback(chat_id, bot_message_id);

CREATE TABLE IF NOT EXISTS crocodile_games (
    chat_id INTEGER PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 0,
    word TEXT NOT NULL DEFAULT '',
    clue_index INTEGER NOT NULL DEFAULT 0,
    round_number INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    started_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS crocodile_scores (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    score INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(chat_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_crocodile_scores_chat
ON crocodile_scores(chat_id, score DESC, updated_at ASC);

CREATE TABLE IF NOT EXISTS city_games (
    chat_id INTEGER PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 0,
    current_city TEXT NOT NULL DEFAULT '',
    required_letter TEXT NOT NULL DEFAULT '',
    used_cities TEXT NOT NULL DEFAULT '',
    round_number INTEGER NOT NULL DEFAULT 0,
    started_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS city_scores (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    score INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(chat_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_city_scores_chat
ON city_scores(chat_id, score DESC, updated_at ASC);

CREATE TABLE IF NOT EXISTS game_sessions (
    chat_id INTEGER NOT NULL,
    game TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0,
    target_score INTEGER NOT NULL DEFAULT 10,
    started_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(chat_id, game)
);

CREATE TABLE IF NOT EXISTS game_session_scores (
    chat_id INTEGER NOT NULL,
    game TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    score INTEGER NOT NULL DEFAULT 0,
    joined_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(chat_id, game, user_id)
);

CREATE INDEX IF NOT EXISTS idx_game_session_scores
ON game_session_scores(chat_id, game, score DESC, updated_at ASC);

CREATE TABLE IF NOT EXISTS game_stats (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    game TEXT NOT NULL,
    points INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    correct INTEGER NOT NULL DEFAULT 0,
    games_played INTEGER NOT NULL DEFAULT 0,
    streak INTEGER NOT NULL DEFAULT 0,
    best_streak INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(chat_id, user_id, game)
);

CREATE INDEX IF NOT EXISTS idx_game_stats_chat
ON game_stats(chat_id, points DESC, wins DESC);

CREATE TABLE IF NOT EXISTS game_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    game TEXT NOT NULL,
    event_type TEXT NOT NULL,
    points INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_game_events_week
ON game_events(chat_id, created_at DESC, game);

CREATE TABLE IF NOT EXISTS game_achievements (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    unlocked_at INTEGER NOT NULL,
    PRIMARY KEY(chat_id, user_id, code)
);

CREATE TABLE IF NOT EXISTS game_weekly_announcements (
    chat_id INTEGER NOT NULL,
    week_key TEXT NOT NULL,
    announced_at INTEGER NOT NULL,
    PRIMARY KEY(chat_id, week_key)
);

CREATE TABLE IF NOT EXISTS hangman_games (
    chat_id INTEGER PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 0,
    word TEXT NOT NULL DEFAULT '',
    hint TEXT NOT NULL DEFAULT '',
    guessed_letters TEXT NOT NULL DEFAULT '',
    misses INTEGER NOT NULL DEFAULT 0,
    round_number INTEGER NOT NULL DEFAULT 0,
    started_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quiz_games (
    chat_id INTEGER PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 0,
    question_id TEXT NOT NULL DEFAULT '',
    answer TEXT NOT NULL DEFAULT '',
    question TEXT NOT NULL DEFAULT '',
    options TEXT NOT NULL DEFAULT '',
    round_number INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    started_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS whoami_games (
    chat_id INTEGER PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 0,
    answer TEXT NOT NULL DEFAULT '',
    clue_index INTEGER NOT NULL DEFAULT 0,
    round_number INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    started_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS game_content (
    content_type TEXT NOT NULL,
    content_key TEXT NOT NULL,
    difficulty INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    answer TEXT NOT NULL DEFAULT '',
    options TEXT NOT NULL DEFAULT '',
    clue1 TEXT NOT NULL DEFAULT '',
    clue2 TEXT NOT NULL DEFAULT '',
    clue3 TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    fetched_at INTEGER NOT NULL DEFAULT 0,
    last_used_at INTEGER NOT NULL DEFAULT 0,
    use_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(content_type, content_key)
);

CREATE INDEX IF NOT EXISTS idx_game_content_pick
ON game_content(content_type, difficulty, use_count, last_used_at);

CREATE TABLE IF NOT EXISTS game_content_meta (
    meta_key TEXT PRIMARY KEY,
    meta_value TEXT NOT NULL DEFAULT ''
);
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
            if "silence_nudge_count" not in columns:
                conn.execute("ALTER TABLE chats ADD COLUMN silence_nudge_count INTEGER NOT NULL DEFAULT 0")
            if "manual_quiet" not in columns:
                conn.execute("ALTER TABLE chats ADD COLUMN manual_quiet INTEGER NOT NULL DEFAULT 0")
            if "game_difficulty" not in columns:
                conn.execute("ALTER TABLE chats ADD COLUMN game_difficulty TEXT NOT NULL DEFAULT 'normal'")

            crocodile_columns = {row["name"] for row in conn.execute("PRAGMA table_info(crocodile_games)").fetchall()}
            if "skip_used" not in crocodile_columns:
                conn.execute("ALTER TABLE crocodile_games ADD COLUMN skip_used INTEGER NOT NULL DEFAULT 0")
            if "difficulty" not in crocodile_columns:
                conn.execute("ALTER TABLE crocodile_games ADD COLUMN difficulty INTEGER NOT NULL DEFAULT 1")
            if "fast_rounds" not in crocodile_columns:
                conn.execute("ALTER TABLE crocodile_games ADD COLUMN fast_rounds INTEGER NOT NULL DEFAULT 0")
            if "round_started_at" not in crocodile_columns:
                conn.execute("ALTER TABLE crocodile_games ADD COLUMN round_started_at INTEGER NOT NULL DEFAULT 0")

            # Preserve scores earned before the unified game statistics system.
            conn.execute(
                """
                INSERT OR IGNORE INTO game_stats(
                    chat_id,user_id,display_name,game,points,wins,correct,games_played,streak,best_streak,updated_at
                )
                SELECT chat_id,user_id,display_name,'crocodile',score,0,score,0,0,0,updated_at
                FROM crocodile_scores WHERE score>0
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO game_stats(
                    chat_id,user_id,display_name,game,points,wins,correct,games_played,streak,best_streak,updated_at
                )
                SELECT chat_id,user_id,display_name,'cities',score,0,score,0,0,0,updated_at
                FROM city_scores WHERE score>0
                """
            )

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

    def cache_group_member_status(self, chat_id: int, user_id: int, status: str):
        if not chat_id or not user_id:
            return
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO group_membership_cache(chat_id,user_id,status,updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (chat_id, user_id, (status or "")[:32], int(time.time())),
            )

    def cached_group_member_status(self, chat_id: int, user_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT status,updated_at
                FROM group_membership_cache
                WHERE chat_id=? AND user_id=?
                """,
                (chat_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def known_chats_for_user(self, user_id: int) -> list[dict[str, Any]]:
        """
        Кандидаты для личной панели управления:
        - группы, где этот Telegram user уже писал боту;
        - группы, где ранее был подтверждён его статус участника/админа.
        Живые права всё равно перепроверяются через Telegram перед изменением настроек.
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT c.*
                FROM chats c
                LEFT JOIN users u
                  ON u.chat_id=c.chat_id AND u.user_id=?
                LEFT JOIN group_membership_cache g
                  ON g.chat_id=c.chat_id AND g.user_id=?
                WHERE u.user_id IS NOT NULL OR g.user_id IS NOT NULL
                ORDER BY c.title COLLATE NOCASE ASC, c.chat_id ASC
                """,
                (user_id, user_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def known_chats(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chats ORDER BY title COLLATE NOCASE ASC, chat_id ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_chat(self, chat_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM chats WHERE chat_id=?", (chat_id,)).fetchone()
            return dict(row) if row else None

    def update_chat(self, chat_id: int, **values):
        allowed = {"enabled", "roast_level", "min_interval_minutes", "silence_minutes", "last_bot_message_at", "last_activity_at", "hardness_mode", "fixed_hardness", "response_delay_seconds", "silence_nudge_count", "manual_quiet", "game_difficulty"}
        pairs = [(k, v) for k, v in values.items() if k in allowed]
        if not pairs:
            return
        sql = "UPDATE chats SET " + ", ".join(f"{k}=?" for k, _ in pairs) + " WHERE chat_id=?"
        with self.connect() as conn:
            conn.execute(sql, [v for _, v in pairs] + [chat_id])

    def upsert_game_content(self, items: list[dict[str, Any]]) -> int:
        if not items:
            return 0
        now = int(time.time())
        rows = []
        for item in items:
            content_type = str(item.get("content_type") or "").strip()
            content_key = str(item.get("content_key") or "").strip()
            if not content_type or not content_key:
                continue
            rows.append((
                content_type,
                content_key[:240],
                int(item.get("difficulty", 0) or 0),
                str(item.get("title") or "")[:1200],
                str(item.get("answer") or "")[:500],
                str(item.get("options") or "")[:4000],
                str(item.get("clue1") or "")[:1400],
                str(item.get("clue2") or "")[:1400],
                str(item.get("clue3") or "")[:1400],
                str(item.get("category") or "")[:200],
                str(item.get("source") or "")[:100],
                str(item.get("source_url") or "")[:1200],
                int(item.get("fetched_at", now) or now),
            ))
        if not rows:
            return 0
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO game_content(
                    content_type,content_key,difficulty,title,answer,options,
                    clue1,clue2,clue3,category,source,source_url,fetched_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(content_type,content_key) DO UPDATE SET
                    difficulty=excluded.difficulty,
                    title=excluded.title,
                    answer=excluded.answer,
                    options=excluded.options,
                    clue1=excluded.clue1,
                    clue2=excluded.clue2,
                    clue3=excluded.clue3,
                    category=excluded.category,
                    source=excluded.source,
                    source_url=excluded.source_url,
                    fetched_at=excluded.fetched_at
                """,
                rows,
            )
        return len(rows)

    def game_content_count(self, content_type: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM game_content WHERE content_type=?",
                (content_type,),
            ).fetchone()
        return int(row["n"] or 0) if row else 0

    def pick_game_content(
        self,
        content_type: str,
        difficulty: int = 0,
        exclude_key: str = "",
    ) -> dict[str, Any] | None:
        params: list[Any] = [content_type]
        where = ["content_type=?"]
        if difficulty:
            where.append("(difficulty=0 OR difficulty=?)")
            params.append(int(difficulty))
        if exclude_key:
            where.append("content_key<>?")
            params.append(exclude_key)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT *
                FROM game_content
                WHERE {' AND '.join(where)}
                ORDER BY use_count ASC, last_used_at ASC, RANDOM()
                LIMIT 1
                """,
                params,
            ).fetchone()
        return dict(row) if row else None

    def list_game_content(self, content_type: str, limit: int = 1000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM game_content
                WHERE content_type=?
                ORDER BY use_count ASC, last_used_at ASC
                LIMIT ?
                """,
                (content_type, max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_game_content_used(self, content_type: str, content_key: str):
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE game_content
                SET use_count=use_count+1,last_used_at=?
                WHERE content_type=? AND content_key=?
                """,
                (int(time.time()), content_type, content_key),
            )

    def set_game_content_meta(self, key: str, value: str):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO game_content_meta(meta_key,meta_value)
                VALUES(?,?)
                ON CONFLICT(meta_key) DO UPDATE SET meta_value=excluded.meta_value
                """,
                (key, value),
            )

    def get_game_content_meta(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT meta_value FROM game_content_meta WHERE meta_key=?",
                (key,),
            ).fetchone()
        return str(row["meta_value"]) if row else default

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

    def set_ignored_user(self, chat_id: int, user_id: int, ignored: bool, added_by: int = 0):
        with self.connect() as conn:
            if ignored:
                conn.execute(
                    """
                    INSERT INTO bot_ignored_users(chat_id,user_id,added_by,added_at)
                    VALUES(?,?,?,?)
                    ON CONFLICT(chat_id,user_id) DO UPDATE SET
                        added_by=excluded.added_by,
                        added_at=excluded.added_at
                    """,
                    (chat_id, user_id, added_by, int(time.time())),
                )
            else:
                conn.execute(
                    "DELETE FROM bot_ignored_users WHERE chat_id=? AND user_id=?",
                    (chat_id, user_id),
                )

    def is_ignored_user(self, chat_id: int, user_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM bot_ignored_users WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
        return bool(row)

    def ignored_users(self, chat_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT i.chat_id,i.user_id,i.added_by,i.added_at,
                       COALESCE(u.display_name,'') AS display_name,
                       COALESCE(u.username,'') AS username
                FROM bot_ignored_users i
                LEFT JOIN users u
                  ON u.chat_id=i.chat_id AND u.user_id=i.user_id
                WHERE i.chat_id=?
                ORDER BY i.added_at DESC, i.user_id ASC
                """,
                (chat_id,),
            ).fetchall()
        return [dict(row) for row in rows]

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
            existing = conn.execute(
                """
                SELECT id FROM messages
                WHERE chat_id=? AND telegram_message_id=? AND kind='bot'
                ORDER BY id DESC LIMIT 1
                """,
                (chat_id, message_id),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE messages
                    SET content=?,reply_to_message_id=COALESCE(?,reply_to_message_id),
                        reply_to_user_id=COALESCE(?,reply_to_user_id)
                    WHERE id=?
                    """,
                    (content[:2000], reply_to_message_id, reply_to_user_id, int(existing["id"])),
                )
                return
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

    def deletable_message_ids(
        self,
        chat_id: int,
        *,
        user_id: int | None = None,
        bot_only: bool = False,
        max_age_seconds: int = 48 * 3600,
    ) -> list[int]:
        cutoff = int(time.time()) - max(60, int(max_age_seconds))
        clauses = ["chat_id=?", "created_at>=?"]
        params: list[Any] = [chat_id, cutoff]
        if bot_only:
            clauses.append("kind='bot'")
        elif user_id is not None:
            clauses.append("user_id=?")
            params.append(int(user_id))
        else:
            return []

        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT telegram_message_id, MAX(created_at) AS newest
                FROM messages
                WHERE {' AND '.join(clauses)}
                GROUP BY telegram_message_id
                ORDER BY newest DESC
                """,
                params,
            ).fetchall()
        return [int(row["telegram_message_id"]) for row in rows if int(row["telegram_message_id"] or 0)]

    def forget_messages(self, chat_id: int, message_ids: list[int]):
        ids = sorted({int(x) for x in message_ids if int(x)})
        if not ids:
            return
        with self.connect() as conn:
            for start in range(0, len(ids), 400):
                batch = ids[start:start + 400]
                placeholders = ",".join("?" for _ in batch)
                args = [chat_id, *batch]
                conn.execute(
                    f"DELETE FROM messages WHERE chat_id=? AND telegram_message_id IN ({placeholders})",
                    args,
                )
                conn.execute(
                    f"DELETE FROM bot_responses WHERE chat_id=? AND telegram_message_id IN ({placeholders})",
                    args,
                )
                conn.execute(
                    f"DELETE FROM response_feedback WHERE chat_id=? AND bot_message_id IN ({placeholders})",
                    args,
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

    def register_bot_response(
        self,
        chat_id: int,
        telegram_message_id: int,
        target_user_id: int,
        humor_style: str,
        mode_level: int,
    ):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO bot_responses(
                    chat_id,telegram_message_id,target_user_id,humor_style,mode_level,created_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    chat_id,
                    telegram_message_id,
                    target_user_id,
                    humor_style or "none",
                    int(mode_level),
                    int(time.time()),
                ),
            )

    def get_bot_response(self, chat_id: int, telegram_message_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM bot_responses WHERE chat_id=? AND telegram_message_id=?",
                (chat_id, telegram_message_id),
            ).fetchone()
        return dict(row) if row else None

    def set_response_feedback(
        self,
        chat_id: int,
        bot_message_id: int,
        user_id: int,
        source: str,
        score: int,
        detail: str = "",
    ):
        if not self.get_bot_response(chat_id, bot_message_id):
            return
        score = max(-2, min(2, int(score)))
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO response_feedback(
                    chat_id,bot_message_id,user_id,source,score,detail,updated_at
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(chat_id,bot_message_id,user_id,source) DO UPDATE SET
                    score=excluded.score,
                    detail=excluded.detail,
                    updated_at=excluded.updated_at
                """,
                (
                    chat_id,
                    bot_message_id,
                    user_id,
                    source[:24],
                    score,
                    (detail or "")[:100],
                    int(time.time()),
                ),
            )

    def humor_style_preferences(self, chat_id: int, target_user_id: int) -> dict[str, float]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    br.humor_style AS style,
                    SUM(
                        CASE
                            WHEN br.target_user_id=? THEN rf.score * 2
                            ELSE rf.score
                        END
                    ) AS weighted_score,
                    COUNT(*) AS signals
                FROM bot_responses br
                JOIN response_feedback rf
                  ON rf.chat_id=br.chat_id
                 AND rf.bot_message_id=br.telegram_message_id
                WHERE br.chat_id=?
                  AND br.humor_style!='none'
                  AND rf.score!=0
                GROUP BY br.humor_style
                """,
                (target_user_id, chat_id),
            ).fetchall()

        result: dict[str, float] = {}
        for row in rows:
            signals = max(1, int(row["signals"] or 1))
            raw = float(row["weighted_score"] or 0)
            result[str(row["style"])] = raw / (1.0 + 0.20 * max(0, signals - 1))
        return result

    def manual_feedback_examples(
        self,
        chat_id: int,
        target_user_id: int,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Последние ответы, вручную оценённые администратором, для обучения стиля."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    m.content AS content,
                    rf.score AS score,
                    br.humor_style AS humor_style,
                    br.target_user_id AS target_user_id,
                    rf.updated_at AS updated_at
                FROM response_feedback rf
                JOIN bot_responses br
                  ON br.chat_id=rf.chat_id
                 AND br.telegram_message_id=rf.bot_message_id
                JOIN messages m
                  ON m.chat_id=br.chat_id
                 AND m.telegram_message_id=br.telegram_message_id
                 AND m.kind='bot'
                WHERE rf.chat_id=?
                  AND rf.source='admin'
                  AND rf.score!=0
                ORDER BY
                    CASE WHEN br.target_user_id=? THEN 0 ELSE 1 END,
                    rf.updated_at DESC
                LIMIT ?
                """,
                (chat_id, target_user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def feedback_stats(self, chat_id: int) -> dict[str, int]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS signals, COALESCE(SUM(score),0) AS score
                FROM response_feedback
                WHERE chat_id=? AND score!=0
                """,
                (chat_id,),
            ).fetchone()
        return {"signals": int(row["signals"] or 0), "score": int(row["score"] or 0)}

    def get_crocodile_game(self, chat_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM crocodile_games WHERE chat_id=?",
                (chat_id,),
            ).fetchone()
        return dict(row) if row else None

    def start_crocodile_game(self, chat_id: int):
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO crocodile_games(
                    chat_id,active,word,clue_index,round_number,attempts,started_at,updated_at,
                    skip_used,difficulty,fast_rounds,round_started_at
                ) VALUES(?,1,'',0,0,0,?,?,0,1,0,0)
                ON CONFLICT(chat_id) DO UPDATE SET
                    active=1,
                    word='',
                    clue_index=0,
                    attempts=0,
                    skip_used=0,
                    difficulty=1,
                    fast_rounds=0,
                    round_started_at=0,
                    started_at=excluded.started_at,
                    updated_at=excluded.updated_at
                """,
                (chat_id, now, now),
            )

    def set_crocodile_round(self, chat_id: int, word: str):
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE crocodile_games
                SET word=?, clue_index=0, attempts=0, skip_used=0,
                    round_number=round_number+1, round_started_at=?, updated_at=?
                WHERE chat_id=? AND active=1
                """,
                (word, now, now, chat_id),
            )

    def clear_crocodile_round(self, chat_id: int):
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE crocodile_games
                SET word='', clue_index=0, attempts=0, updated_at=?
                WHERE chat_id=? AND active=1
                """,
                (int(time.time()), chat_id),
            )

    def use_crocodile_skip(self, chat_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT skip_used FROM crocodile_games WHERE chat_id=? AND active=1",
                (chat_id,),
            ).fetchone()
            if not row or int(row["skip_used"] or 0):
                return False
            conn.execute(
                "UPDATE crocodile_games SET skip_used=1,updated_at=? WHERE chat_id=?",
                (int(time.time()), chat_id),
            )
            return True

    def update_crocodile_difficulty(self, chat_id: int, fast: bool) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT difficulty,fast_rounds FROM crocodile_games WHERE chat_id=?",
                (chat_id,),
            ).fetchone()
            if not row:
                return 1
            difficulty = max(1, min(3, int(row["difficulty"] or 1)))
            fast_rounds = int(row["fast_rounds"] or 0)
            if fast:
                fast_rounds += 1
                if fast_rounds >= 2 and difficulty < 3:
                    difficulty += 1
                    fast_rounds = 0
            else:
                if difficulty > 1:
                    difficulty -= 1
                fast_rounds = 0
            conn.execute(
                "UPDATE crocodile_games SET difficulty=?,fast_rounds=?,updated_at=? WHERE chat_id=?",
                (difficulty, fast_rounds, int(time.time()), chat_id),
            )
        return difficulty

    def stop_crocodile_game(self, chat_id: int):
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE crocodile_games
                SET active=0, word='', clue_index=0, attempts=0, updated_at=?
                WHERE chat_id=?
                """,
                (int(time.time()), chat_id),
            )

    def register_crocodile_attempt(self, chat_id: int) -> int:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE crocodile_games
                SET attempts=attempts+1, updated_at=?
                WHERE chat_id=? AND active=1
                """,
                (int(time.time()), chat_id),
            )
            row = conn.execute(
                "SELECT attempts FROM crocodile_games WHERE chat_id=?",
                (chat_id,),
            ).fetchone()
        return int(row["attempts"] or 0) if row else 0

    def advance_crocodile_clue(self, chat_id: int) -> int:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE crocodile_games
                SET clue_index=clue_index+1, updated_at=?
                WHERE chat_id=? AND active=1
                """,
                (int(time.time()), chat_id),
            )
            row = conn.execute(
                "SELECT clue_index FROM crocodile_games WHERE chat_id=?",
                (chat_id,),
            ).fetchone()
        return int(row["clue_index"] or 0) if row else 0

    def add_crocodile_score(self, chat_id: int, user_id: int, display_name: str, points: int = 1) -> int:
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO crocodile_scores(chat_id,user_id,display_name,score,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    score=crocodile_scores.score+excluded.score,
                    updated_at=excluded.updated_at
                """,
                (chat_id, user_id, display_name[:120], points, now),
            )
            row = conn.execute(
                "SELECT score FROM crocodile_scores WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
        return int(row["score"] or 0) if row else 0

    def crocodile_top(self, chat_id: int, limit: int = 5) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id,display_name,score
                FROM crocodile_scores
                WHERE chat_id=? AND score>0
                ORDER BY score DESC, updated_at ASC
                LIMIT ?
                """,
                (chat_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]


    def get_city_game(self, chat_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM city_games WHERE chat_id=?",
                (chat_id,),
            ).fetchone()
        return dict(row) if row else None

    def start_city_game(self, chat_id: int, city: str, required_letter: str):
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO city_games(
                    chat_id,active,current_city,required_letter,used_cities,round_number,started_at,updated_at
                ) VALUES(?,1,?,?,?,1,?,?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    active=1,
                    current_city=excluded.current_city,
                    required_letter=excluded.required_letter,
                    used_cities=excluded.used_cities,
                    round_number=1,
                    started_at=excluded.started_at,
                    updated_at=excluded.updated_at
                """,
                (chat_id, city, required_letter, city.lower(), now, now),
            )

    def update_city_game(self, chat_id: int, city: str, required_letter: str, used_cities: list[str]):
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE city_games
                SET current_city=?, required_letter=?, used_cities=?,
                    round_number=round_number+1, updated_at=?
                WHERE chat_id=? AND active=1
                """,
                (city, required_letter, "\n".join(used_cities), int(time.time()), chat_id),
            )

    def stop_city_game(self, chat_id: int):
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE city_games
                SET active=0, updated_at=?
                WHERE chat_id=?
                """,
                (int(time.time()), chat_id),
            )

    def add_city_score(self, chat_id: int, user_id: int, display_name: str, points: int = 1) -> int:
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO city_scores(chat_id,user_id,display_name,score,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    score=city_scores.score+excluded.score,
                    updated_at=excluded.updated_at
                """,
                (chat_id, user_id, display_name[:120], points, now),
            )
            row = conn.execute(
                "SELECT score FROM city_scores WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
        return int(row["score"] or 0) if row else 0

    def city_top(self, chat_id: int, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id,display_name,score
                FROM city_scores
                WHERE chat_id=? AND score>0
                ORDER BY score DESC, updated_at ASC
                LIMIT ?
                """,
                (chat_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]


    def start_game_session(self, chat_id: int, game: str, target_score: int = 10, reset: bool = True):
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO game_sessions(chat_id,game,active,target_score,started_at,updated_at)
                VALUES(?,?,1,?,?,?)
                ON CONFLICT(chat_id,game) DO UPDATE SET
                    active=1,
                    target_score=excluded.target_score,
                    started_at=CASE WHEN ? THEN excluded.started_at ELSE game_sessions.started_at END,
                    updated_at=excluded.updated_at
                """,
                (chat_id, game, target_score, now, now, 1 if reset else 0),
            )
            if reset:
                conn.execute(
                    "DELETE FROM game_session_scores WHERE chat_id=? AND game=?",
                    (chat_id, game),
                )

    def get_game_session(self, chat_id: int, game: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM game_sessions WHERE chat_id=? AND game=?",
                (chat_id, game),
            ).fetchone()
        return dict(row) if row else None

    def end_game_session(self, chat_id: int, game: str):
        with self.connect() as conn:
            conn.execute(
                "UPDATE game_sessions SET active=0,updated_at=? WHERE chat_id=? AND game=?",
                (int(time.time()), chat_id, game),
            )

    def touch_game_participant(self, chat_id: int, game: str, user_id: int, display_name: str):
        now = int(time.time())
        with self.connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM game_session_scores WHERE chat_id=? AND game=? AND user_id=?",
                (chat_id, game, user_id),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO game_session_scores(chat_id,game,user_id,display_name,score,joined_at,updated_at)
                VALUES(?,?,?,?,0,?,?)
                ON CONFLICT(chat_id,game,user_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    updated_at=excluded.updated_at
                """,
                (chat_id, game, user_id, display_name[:120], now, now),
            )
            if not exists:
                conn.execute(
                    """
                    INSERT INTO game_stats(
                        chat_id,user_id,display_name,game,points,wins,correct,games_played,streak,best_streak,updated_at
                    ) VALUES(?,?,?,?,0,0,0,1,0,0,?)
                    ON CONFLICT(chat_id,user_id,game) DO UPDATE SET
                        display_name=excluded.display_name,
                        games_played=game_stats.games_played+1,
                        updated_at=excluded.updated_at
                    """,
                    (chat_id, user_id, display_name[:120], game, now),
                )

    def award_game_point(
        self,
        chat_id: int,
        game: str,
        user_id: int,
        display_name: str,
        points: int = 1,
    ) -> dict[str, Any]:
        self.touch_game_participant(chat_id, game, user_id, display_name)
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                "UPDATE game_stats SET streak=0 WHERE chat_id=? AND game=? AND user_id!=?",
                (chat_id, game, user_id),
            )
            conn.execute(
                """
                UPDATE game_session_scores
                SET score=score+?, display_name=?, updated_at=?
                WHERE chat_id=? AND game=? AND user_id=?
                """,
                (points, display_name[:120], now, chat_id, game, user_id),
            )
            conn.execute(
                """
                UPDATE game_stats
                SET display_name=?,
                    points=points+?,
                    correct=correct+?,
                    streak=streak+1,
                    best_streak=MAX(best_streak, streak+1),
                    updated_at=?
                WHERE chat_id=? AND user_id=? AND game=?
                """,
                (display_name[:120], points, points, now, chat_id, user_id, game),
            )
            conn.execute(
                """
                INSERT INTO game_events(chat_id,user_id,display_name,game,event_type,points,created_at)
                VALUES(?,?,?,?,?,?,?)
                """,
                (chat_id, user_id, display_name[:120], game, "point", points, now),
            )
            score_row = conn.execute(
                "SELECT score FROM game_session_scores WHERE chat_id=? AND game=? AND user_id=?",
                (chat_id, game, user_id),
            ).fetchone()
            stat_row = conn.execute(
                """
                SELECT points,wins,correct,games_played,streak,best_streak
                FROM game_stats WHERE chat_id=? AND user_id=? AND game=?
                """,
                (chat_id, user_id, game),
            ).fetchone()
            session_row = conn.execute(
                "SELECT target_score FROM game_sessions WHERE chat_id=? AND game=?",
                (chat_id, game),
            ).fetchone()

        session_score = int(score_row["score"] or 0) if score_row else points
        target = int(session_row["target_score"] or 10) if session_row else 10
        result = dict(stat_row) if stat_row else {}
        result.update({"session_score": session_score, "target_score": target, "won": session_score >= target})
        return result

    def register_game_session_win(self, chat_id: int, game: str, user_id: int, display_name: str) -> dict[str, Any]:
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE game_stats
                SET wins=wins+1, display_name=?, updated_at=?
                WHERE chat_id=? AND user_id=? AND game=?
                """,
                (display_name[:120], now, chat_id, user_id, game),
            )
            conn.execute(
                """
                INSERT INTO game_events(chat_id,user_id,display_name,game,event_type,points,created_at)
                VALUES(?,?,?,?,?,0,?)
                """,
                (chat_id, user_id, display_name[:120], game, "session_win", now),
            )
            conn.execute(
                "UPDATE game_sessions SET active=0,updated_at=? WHERE chat_id=? AND game=?",
                (now, chat_id, game),
            )
            row = conn.execute(
                """
                SELECT points,wins,correct,games_played,streak,best_streak
                FROM game_stats WHERE chat_id=? AND user_id=? AND game=?
                """,
                (chat_id, user_id, game),
            ).fetchone()
        return dict(row) if row else {}

    def game_session_top(self, chat_id: int, game: str, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id,display_name,score
                FROM game_session_scores
                WHERE chat_id=? AND game=?
                ORDER BY score DESC, updated_at ASC
                LIMIT ?
                """,
                (chat_id, game, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def game_rating(self, chat_id: int, game: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if game:
                rows = conn.execute(
                    """
                    SELECT user_id,MAX(display_name) AS display_name,
                           SUM(points) AS points,SUM(wins) AS wins,SUM(correct) AS correct
                    FROM game_stats
                    WHERE chat_id=? AND game=?
                    GROUP BY user_id
                    HAVING SUM(points)>0 OR SUM(wins)>0
                    ORDER BY points DESC,wins DESC,correct DESC
                    LIMIT ?
                    """,
                    (chat_id, game, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT user_id,MAX(display_name) AS display_name,
                           SUM(points) AS points,SUM(wins) AS wins,SUM(correct) AS correct
                    FROM game_stats
                    WHERE chat_id=?
                    GROUP BY user_id
                    HAVING SUM(points)>0 OR SUM(wins)>0
                    ORDER BY points DESC,wins DESC,correct DESC
                    LIMIT ?
                    """,
                    (chat_id, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    def weekly_game_rating(
        self,
        chat_id: int,
        since_ts: int,
        until_ts: int | None = None,
        game: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [chat_id, since_ts]
        conditions = ["chat_id=?", "created_at>=?", "event_type='point'"]
        if until_ts is not None:
            conditions.append("created_at<?")
            params.append(until_ts)
        if game:
            conditions.append("game=?")
            params.append(game)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT user_id,MAX(display_name) AS display_name,SUM(points) AS points
                FROM game_events
                WHERE {' AND '.join(conditions)}
                GROUP BY user_id
                HAVING SUM(points)>0
                ORDER BY points DESC,MAX(created_at) ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def player_game_stats(self, chat_id: int, user_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT game,display_name,points,wins,correct,games_played,streak,best_streak
                FROM game_stats
                WHERE chat_id=? AND user_id=?
                ORDER BY points DESC, game ASC
                """,
                (chat_id, user_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def unlock_achievement(self, chat_id: int, user_id: int, code: str, title: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO game_achievements(chat_id,user_id,code,title,unlocked_at)
                VALUES(?,?,?,?,?)
                """,
                (chat_id, user_id, code, title, int(time.time())),
            )
            return cur.rowcount > 0

    def player_achievements(self, chat_id: int, user_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT code,title,unlocked_at
                FROM game_achievements
                WHERE chat_id=? AND user_id=?
                ORDER BY unlocked_at DESC
                """,
                (chat_id, user_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def weekly_announcement_done(self, chat_id: int, week_key: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM game_weekly_announcements WHERE chat_id=? AND week_key=?",
                (chat_id, week_key),
            ).fetchone()
        return bool(row)

    def mark_weekly_announcement(self, chat_id: int, week_key: str):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO game_weekly_announcements(chat_id,week_key,announced_at)
                VALUES(?,?,?)
                """,
                (chat_id, week_key, int(time.time())),
            )

    def get_hangman_game(self, chat_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM hangman_games WHERE chat_id=?", (chat_id,)).fetchone()
        return dict(row) if row else None

    def set_hangman_round(self, chat_id: int, word: str, hint: str, active: bool = True):
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO hangman_games(chat_id,active,word,hint,guessed_letters,misses,round_number,started_at,updated_at)
                VALUES(?,?,?,?, '',0,1,?,?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    active=excluded.active,word=excluded.word,hint=excluded.hint,
                    guessed_letters='',misses=0,round_number=hangman_games.round_number+1,
                    started_at=excluded.started_at,updated_at=excluded.updated_at
                """,
                (chat_id, 1 if active else 0, word, hint, now, now),
            )

    def update_hangman_game(self, chat_id: int, guessed_letters: str, misses: int):
        with self.connect() as conn:
            conn.execute(
                "UPDATE hangman_games SET guessed_letters=?,misses=?,updated_at=? WHERE chat_id=?",
                (guessed_letters, misses, int(time.time()), chat_id),
            )

    def clear_hangman_round(self, chat_id: int):
        with self.connect() as conn:
            conn.execute(
                "UPDATE hangman_games SET word='',hint='',guessed_letters='',misses=0,updated_at=? WHERE chat_id=? AND active=1",
                (int(time.time()), chat_id),
            )

    def stop_hangman_game(self, chat_id: int):
        with self.connect() as conn:
            conn.execute("UPDATE hangman_games SET active=0,updated_at=? WHERE chat_id=?", (int(time.time()), chat_id))

    def get_quiz_game(self, chat_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM quiz_games WHERE chat_id=?", (chat_id,)).fetchone()
        return dict(row) if row else None

    def set_quiz_round(self, chat_id: int, question_id: str, answer: str, question: str, options: str):
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO quiz_games(chat_id,active,question_id,answer,question,options,round_number,attempts,started_at,updated_at)
                VALUES(?,1,?,?,?,?,1,0,?,?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    active=1,question_id=excluded.question_id,answer=excluded.answer,
                    question=excluded.question,options=excluded.options,
                    round_number=quiz_games.round_number+1,attempts=0,
                    started_at=excluded.started_at,updated_at=excluded.updated_at
                """,
                (chat_id, question_id, answer, question, options, now, now),
            )

    def clear_quiz_round(self, chat_id: int):
        with self.connect() as conn:
            conn.execute(
                "UPDATE quiz_games SET question_id='',answer='',question='',options='',attempts=0,updated_at=? WHERE chat_id=? AND active=1",
                (int(time.time()), chat_id),
            )

    def add_quiz_attempt(self, chat_id: int) -> int:
        with self.connect() as conn:
            conn.execute("UPDATE quiz_games SET attempts=attempts+1,updated_at=? WHERE chat_id=?", (int(time.time()), chat_id))
            row = conn.execute("SELECT attempts FROM quiz_games WHERE chat_id=?", (chat_id,)).fetchone()
        return int(row["attempts"] or 0) if row else 0

    def stop_quiz_game(self, chat_id: int):
        with self.connect() as conn:
            conn.execute("UPDATE quiz_games SET active=0,updated_at=? WHERE chat_id=?", (int(time.time()), chat_id))

    def get_whoami_game(self, chat_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM whoami_games WHERE chat_id=?", (chat_id,)).fetchone()
        return dict(row) if row else None

    def set_whoami_round(self, chat_id: int, answer: str):
        now = int(time.time())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO whoami_games(chat_id,active,answer,clue_index,round_number,attempts,started_at,updated_at)
                VALUES(?,1,?,0,1,0,?,?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    active=1,answer=excluded.answer,clue_index=0,
                    round_number=whoami_games.round_number+1,attempts=0,
                    started_at=excluded.started_at,updated_at=excluded.updated_at
                """,
                (chat_id, answer, now, now),
            )

    def clear_whoami_round(self, chat_id: int):
        with self.connect() as conn:
            conn.execute(
                "UPDATE whoami_games SET answer='',clue_index=0,attempts=0,updated_at=? WHERE chat_id=? AND active=1",
                (int(time.time()), chat_id),
            )

    def advance_whoami_clue(self, chat_id: int) -> int:
        with self.connect() as conn:
            conn.execute("UPDATE whoami_games SET clue_index=clue_index+1,updated_at=? WHERE chat_id=?", (int(time.time()), chat_id))
            row = conn.execute("SELECT clue_index FROM whoami_games WHERE chat_id=?", (chat_id,)).fetchone()
        return int(row["clue_index"] or 0) if row else 0

    def add_whoami_attempt(self, chat_id: int) -> int:
        with self.connect() as conn:
            conn.execute("UPDATE whoami_games SET attempts=attempts+1,updated_at=? WHERE chat_id=?", (int(time.time()), chat_id))
            row = conn.execute("SELECT attempts FROM whoami_games WHERE chat_id=?", (chat_id,)).fetchone()
        return int(row["attempts"] or 0) if row else 0

    def stop_whoami_game(self, chat_id: int):
        with self.connect() as conn:
            conn.execute("UPDATE whoami_games SET active=0,updated_at=? WHERE chat_id=?", (int(time.time()), chat_id))


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
                SELECT m.*
                FROM messages m
                LEFT JOIN bot_ignored_users i
                  ON i.chat_id=m.chat_id AND i.user_id=m.user_id
                WHERE m.chat_id=? AND m.kind IN ('message','bot') AND i.user_id IS NULL
                ORDER BY m.id DESC LIMIT ?
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
                """
                SELECT m.*
                FROM messages m
                LEFT JOIN bot_ignored_users i
                  ON i.chat_id=m.chat_id AND i.user_id=m.user_id
                WHERE m.chat_id=? AND i.user_id IS NULL
                ORDER BY m.id DESC LIMIT ?
                """,
                (chat_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def active_users(self, chat_id: int, since_seconds: int = 7 * 86400) -> list[dict[str, Any]]:
        cutoff = int(time.time()) - since_seconds
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT u.*
                FROM users u
                LEFT JOIN bot_ignored_users i
                  ON i.chat_id=u.chat_id AND i.user_id=u.user_id
                WHERE u.chat_id=? AND u.last_seen_at>=? AND i.user_id IS NULL
                ORDER BY u.last_seen_at DESC
                """,
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
