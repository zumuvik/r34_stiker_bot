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

FALLBACK_IMAGE_URL: str = "https://http.cat/500"
"""Заглушка на случай недоступности Waifu.im API или ошибочного ответа."""



API_TIMEOUT_SECONDS: int = 5
"""Таймаут HTTP-запроса к Waifu.im API (в секундах)."""

BUTTON_COOLDOWN: int = 3
"""КД между нажатиями кнопки «Давай ещё!» для одного пользователя (в секундах)."""

# ─────────────────── Теги ───────────────────

# Теги картинок (источник: Waifu.im API).
# Актуальный список: https://waifu.im/docs
PHOTO_TAGS: frozenset[str] = frozenset({
    "waifu", "maid", "ero", "hentai", "ass", "oppai",
    "milf", "oral", "paizuri", "ecchi", "selfies",
    "uniform", "marin-kitagawa", "mori-calliope",
    "raiden-shogun",
})

# Теги видео (источник: Reddit).
# Названия подобраны так, чтобы интуитивно сообщать пользователю
# о типе контента (hentai_video — хентай-видео, amv — аниме-клип).
VIDEO_TAGS: frozenset[str] = frozenset({
    "hentai_video", "nsfw_video", "amv",
})

# Маппинг видео-тегов в сабреддиты для запроса.
VIDEO_SUBREDDITS: dict[str, str] = {
    "hentai_video": "hentai_videos",
    "nsfw_video": "nsfw_videos",
    "amv": "amv",
}

# Объединённое множество (для валидации).
VALID_TAGS: frozenset[str] = frozenset(PHOTO_TAGS | VIDEO_TAGS)


# ─────────────────── Хелперы ───────────────────


def validate_tag(raw: str) -> str | None:
    """
    Валидирует пользовательский ввод.

    Приводит к нижнему регистру, удаляет лишние пробелы,
    сверяет с ``VALID_TAGS``.

    Returns:
        Нормализованный тег или ``None`` (если тег не поддерживается).
    """
    tag = raw.strip().lower()
    return tag if tag in VALID_TAGS else None


def is_video_tag(tag: str | None) -> bool:
    """Является ли тег видео-тегом (Reddit)."""
    if tag is None:
        return False
    return tag in VIDEO_TAGS


def is_photo_tag(tag: str | None) -> bool:
    """Является ли тег фото-тегом (Waifu.im)."""
    if tag is None:
        return False
    return tag in PHOTO_TAGS


def get_subreddit(tag: str) -> str:
    """Возвращает сабреддит для видео-тега. Если тег не найден — возвращает сам тег."""
    return VIDEO_SUBREDDITS.get(tag, tag)
