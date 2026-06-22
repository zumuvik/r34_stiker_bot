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

# ─────────────────── Фразы для статистики ───────────────────

POSITIVE_PHRASES: list[str] = [
    "Вы подододрочель",
    "У вас ведро шпермы",
    "Вы выдрочили яца",
    "Вы отдрочили за весь чат",
    "Вы подорожник",
]
"""Фразы, когда сперма +."""

NEGATIVE_PHRASES: list[str] = [
    "У тебя сегодня отсох хуец.",
    "У вас отвалился хуй",
    "Ваш член попал в капкан",
    "Ваши яйца отрофировались",
]
"""Фразы, когда сперма -."""

# ─────────────────── Теги ───────────────────

# Теги картинок (источник: Waifu.im API).
# Актуальный список: https://waifu.im/docs
PHOTO_TAGS: frozenset[str] = frozenset({
    "waifu", "maid", "ero", "hentai", "ass", "oppai",
    "milf", "oral", "paizuri", "ecchi", "selfies",
    "uniform", "marin-kitagawa", "mori-calliope",
    "raiden-shogun",
})

# Теги анимаций/GIF (источник: Purrbot API).
# NOTE: Reddit заблокирован на стороне хостинга (403), поэтому видео
# заменены на NSFW GIF из Purrbot API.
VIDEO_TAGS: frozenset[str] = frozenset({
    "neko_gif", "nsfw_gif",
})

# Маппинг видео-тегов в эндпоинты Purrbot.
VIDEO_ENDPOINTS: dict[str, str] = {
    "neko_gif":   "v2/img/nsfw/neko/gif",
    "nsfw_gif":   "v2/img/nsfw/neko/gif",
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


def get_video_endpoint(tag: str) -> str:
    """Возвращает эндпоинт Purrbot для видео-тега. Если тег не найден — возвращает сам тег."""
    return VIDEO_ENDPOINTS.get(tag, tag)
