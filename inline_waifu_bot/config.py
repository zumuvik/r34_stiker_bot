"""
Конфигурация бота: .env, константы, валидация тегов.
"""

import os
import sys


# ─────────────────── Загрузка .env ───────────────────


def _load_dotenv(path: str = ".env") -> None:
    """
    Загружает переменные из ``.env``-файла в ``os.environ``.

    Не требует внешних зависимостей. Формат строк: ``KEY=VALUE``.
    Пропускает пустые строки и комментарии (``#``).
    Не перезаписывает уже установленные переменные окружения.
    """
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("\"'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        pass  # .env опционален


_load_dotenv()


# ─────────────────── Конфигурация ───────────────────

BOT_TOKEN: str | None = os.getenv("BOT_TOKEN")
"""Токен бота из переменной окружения ``BOT_TOKEN`` (либо из ``.env``)."""

if not BOT_TOKEN:
    print("FATAL: Укажите BOT_TOKEN в переменных окружения.", file=sys.stderr)
    sys.exit(1)

WAIFU_API_URL: str = "https://api.waifu.im/images"
"""Базовый эндпоинт Waifu.im API."""

FALLBACK_IMAGE_URL: str = "https://placehold.co/512x512/1a1a2e/ffffff?text=NSFW+Error"
"""Заглушка на случай недоступности Waifu.im API или ошибочного ответа."""

PLACEHOLDER_IMAGE_URL: str = "https://placehold.co/512x512/1a1a2e/ffffff?text=.&font=playfair-display"
"""Плейсхолдер для первого показа в инлайн-режиме (без спойлера).
   Сразу после отправки заменяется реальным фото под спойлером."""

API_TIMEOUT_SECONDS: int = 5
"""Таймаут HTTP-запроса к Waifu.im API (в секундах)."""

BUTTON_COOLDOWN: int = 3
"""КД между нажатиями кнопки «Давай ещё!» для одного пользователя (в секундах)."""

# Допустимые теги, которые принимает бот.
# Актуальный список: https://waifu.im/docs
VALID_TAGS: frozenset[str] = frozenset({
    "waifu", "maid", "ero", "hentai", "ass", "oppai",
    "milf", "oral", "paizuri", "ecchi", "selfies",
    "uniform", "marin-kitagawa", "mori-calliope",
    "raiden-shogun",
})


# ─────────────────── Валидация тегов ───────────────────


def validate_tag(raw: str) -> str | None:
    """
    Валидирует пользовательский ввод как тег Waifu.im.

    Приводит к нижнему регистру, удаляет лишние пробелы,
    сверяет с множеством ``VALID_TAGS``.

    Args:
        raw: Строка, введённая пользователем после юзернейма бота.

    Returns:
        Нормализованный тег или ``None`` (если тег не поддерживается).
    """
    tag = raw.strip().lower()
    return tag if tag in VALID_TAGS else None
