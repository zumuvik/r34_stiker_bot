"""
SQLite database for user stats and leaderboard.

Хранит статистику спермы пользователей в WAL-режиме.
Все функции синхронные — вызывайте через ``asyncio.to_thread()`` из async-кода.
"""

import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# Файл БД — рядом с пакетом inline_waifu_bot (в корне проекта).
DB_PATH = Path(__file__).resolve().parent.parent / "bot_stats.db"

_conn: sqlite3.Connection | None = None
_write_lock = threading.Lock()


def get_connection() -> sqlite3.Connection:
    """Возвращает (создавая при первом вызове) подключение к SQLite."""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL;").fetchone()
    return _conn


def init_db() -> None:
    """Создаёт таблицы, если их нет. Безопасно вызывать многократно."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id   INTEGER PRIMARY KEY,
            username  TEXT    NOT NULL DEFAULT '',
            total_sperm INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_tag_stats (
            user_id INTEGER NOT NULL,
            tag     TEXT    NOT NULL,
            count   INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, tag)
        )
    """)
    conn.commit()
    logger.info("Database initialised at %s", DB_PATH)


def update_user_sperm(user_id: int, username: str, delta: int) -> int:
    """
    Добавляет (или вычитает) ``delta`` к ``total_sperm`` пользователя.

    Пол в нуле НЕТ — баланс свободно уходит в минус.

    Returns:
        ``delta`` (всегда равен запрошенному, пол не срезает).
    """
    with _write_lock:
        conn = get_connection()

        # UPSERT без пола
        conn.execute(
            """
            INSERT INTO user_stats (user_id, username, total_sperm)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username     = excluded.username,
                total_sperm  = total_sperm + ?
            """,
            (user_id, username, delta, delta),
        )
        conn.commit()
        return delta


def get_leaderboard(limit: int = 10) -> list[dict]:
    """
    Возвращает топ-``limit`` пользователей по убыванию ``total_sperm``.

    Каждый элемент: ``{"user_id": int, "username": str, "total_sperm": int}``.
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT user_id, username, total_sperm
        FROM user_stats
        ORDER BY total_sperm DESC, user_id ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def increment_tag_count(user_id: int, tag: str) -> None:
    """
    Увеличивает счётчик просмотров тега ``tag`` для пользователя ``user_id``.

    При первом просмотре создаёт запись с ``count=1``,
    при повторных — ``count = count + 1``.
    """
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO user_tag_stats (user_id, tag, count)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, tag) DO UPDATE SET
            count = count + 1
        """,
        (user_id, tag),
    )
    conn.commit()


def get_user_favorite_tags(user_id: int, limit: int = 3) -> list[dict]:
    """
    Возвращает топ-``limit`` самых просматриваемых тегов пользователя.

    Каждый элемент: ``{"tag": str, "count": int}``.
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT tag, count
        FROM user_tag_stats
        WHERE user_id = ?
        ORDER BY count DESC, tag ASC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]
