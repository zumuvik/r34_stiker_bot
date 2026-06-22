"""
SQLite database for user stats and leaderboard.

Хранит статистику спермы пользователей в WAL-режиме.
Все функции синхронные — вызывайте через ``asyncio.to_thread()`` из async-кода.
"""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# Файл БД — рядом с пакетом inline_waifu_bot (в корне проекта).
DB_PATH = Path(__file__).resolve().parent.parent / "bot_stats.db"

_conn: sqlite3.Connection | None = None


def get_connection() -> sqlite3.Connection:
    """Возвращает (создавая при первом вызове) подключение к SQLite."""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL;")
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
    conn.commit()
    logger.info("Database initialised at %s", DB_PATH)


def update_user_sperm(user_id: int, username: str, delta: int) -> None:
    """
    Добавляет (или вычитает) ``delta`` к ``total_sperm`` пользователя.

    При первом вызове создаёт запись; при повторных — обновляет
    username и накапливает total_sperm.
    """
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO user_stats (user_id, username, total_sperm)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username     = excluded.username,
            total_sperm  = total_sperm + excluded.total_sperm
        """,
        (user_id, username, delta),
    )
    conn.commit()


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
