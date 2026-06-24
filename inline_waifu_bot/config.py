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
"""Заглушка на случай недоступности API или ошибочного ответа."""



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

# Теги для новых провайдеров (НЕ входят в PHOTO_TAGS / VIDEO_TAGS,
# поэтому не попадают в random-выборку).
FEMBOY_TAGS: frozenset[str] = frozenset({"femboy"})
FURRY_TAGS: frozenset[str] = frozenset({"furry"})
ANTHRO_TAGS: frozenset[str] = frozenset({"anthro"})
FURFEM_TAGS: frozenset[str] = frozenset({"furfem"})
FEET_TAGS: frozenset[str] = frozenset({"feet", "heels"})
UMAMUSUME_TAGS: frozenset[str] = frozenset({"umamusume"})
VIDEO_R34_TAGS: frozenset[str] = frozenset({"video"})
"""Анимации/GIF через Rule34.xxx (тег ``animated``)."""
TENTACLES_TAGS: frozenset[str] = frozenset({"tentacles"})
"""Тентакли через Rule34.xxx."""
YURI_TAGS: frozenset[str] = frozenset({"yuri"})
"""Юри через Rule34.xxx."""
FEMDOM_TAGS: frozenset[str] = frozenset({"femdom"})
"""Фемдом через Rule34.xxx."""

# API-эндпоинты для новых провайдеров.
E621_API_URL: str = "https://e621.net/posts.json"
"""Базовый эндпоинт e621.net API."""

FEMBOY_API_URL: str = E621_API_URL
"""e621.net — femboy NSFW фото (тег: femboy)."""

FURRY_API_URL: str = E621_API_URL
"""e621.net — furry NSFW фото (тег: anthro)."""

E621_USER_AGENT: str = "WaifuBot/1.0 (by @zumuvik; discord)"
"""User-Agent для e621 API (обязателен по ToS e621)."""

E621_API_TAGS: dict[str, str] = {
    "femboy": "femboy rating:e",
    "furry":  "anthro rating:e",
    "anthro": "anthro rating:e -futanari -dickgirl",
    "furfem": "female anthro rating:e -futanari -dickgirl -intersex -fat -chubby -obese -overweight",
    "umamusume": "umamusume rating:e -futanari -dickgirl -fat -chubby -obese -overweight -thick -big_belly",
    # Fallback для feet/heels если yande.re лёг (с исключением фури).
    "feet":  "feet rating:explicit -loli -shota -male -anthro -furry",
    "heels": "high_heels rating:explicit -loli -shota -male -anthro -furry",
}
"""Маппинг тегов бота → строки поиска e621."""

# Yande.re — аниме-бора для ножек/пяток (человеческие девочки, не фури).
YANDE_RE_API_URL: str = "https://yande.re/post.json"
"""Базовый эндпоинт Yande.re API."""

YANDE_RE_TAGS: dict[str, str] = {
    "feet":   "feet rating:explicit -loli -shota -male",
    "heels":  "high_heels rating:explicit -loli -shota -male",
    "femboy": "femboy rating:explicit -loli -shota -male",
}
"""Маппинг тегов бота → строки поиска yande.re (для feet/heels)."""

# Добавим umamusume в маппинг Yande/e621
YANDE_RE_TAGS.update({
    "umamusume": "umamusume rating:explicit -loli -shota -male -trap -futanari -dickgirl -fat -chubby -obese -overweight -thick",
})

# Rule34.xxx — универсальный fallback для всех тегов (есть GIF).
RULE34_API_URL: str = "https://api.rule34.xxx/index.php?page=dapi&s=post&q=index"
"""Базовый эндпоинт Rule34.xxx API."""

RULE34_API_KEY: str | None = os.getenv("RULE34_API_KEY")
"""API ключ Rule34.xxx (из .env)."""

RULE34_USER_ID: str | None = os.getenv("RULE34_USER_ID")
"""User ID Rule34.xxx (из .env)."""

RULE34_API_TAGS: dict[str, str] = {
    "femboy": "femboy rating:explicit -loli -shota",
    "furry": "anthro rating:explicit",
    "anthro": "anthro rating:explicit -futanari -dickgirl",
    "furfem": "female anthro rating:explicit -futanari -dickgirl -intersex -fat -chubby -obese -overweight",
    "feet": "feet rating:explicit -loli -shota -male -anthro -furry",
    "heels": "high_heels rating:explicit -loli -shota -male -anthro -furry",
    "umamusume": "umamusume rating:explicit -loli -shota -male -trap -futanari -dickgirl -fat -chubby -obese -overweight -thick",
    "video": "animated rating:explicit -loli -shota",
    "tentacles": "tentacles rating:explicit -loli -shota",
    "yuri": "yuri rating:explicit -loli -shota",
    "femdom": "femdom rating:explicit -loli -shota",
}
"""Маппинг тегов бота → строки поиска rule34.xxx."""

# Объединённое множество (для валидации).
VALID_TAGS: frozenset[str] = frozenset(PHOTO_TAGS | VIDEO_TAGS | FEMBOY_TAGS | FURRY_TAGS | ANTHRO_TAGS | FURFEM_TAGS | FEET_TAGS | UMAMUSUME_TAGS | VIDEO_R34_TAGS | TENTACLES_TAGS | YURI_TAGS | FEMDOM_TAGS)

# Человекочитаемые названия тегов для меню.
TAG_LABELS: dict[str, str] = {
    "umamusume": "Umamusume Pretty Derby",
    "video": "Анимация / GIF",
    "tentacles": "Тентакли",
    "yuri": "Юри (девочки-девочки)",
    "femdom": "Фемдом (доминирование)",
}

# Маппинг тегов → смешные достижения для топа.
TAG_ACHIEVEMENTS: dict[str, str] = {
    "neko_gif":   "Гифкоман",
    "nsfw_gif":   "Гифоман-экстремал",
    "femboy":     "Фембой-ловушка",
    "furry":      "Пушной зверь",
    "anthro":     "Антропо-поцик",
    "furfem":     "Фурри-фем",
    "feet":       "Ножкоман",
    "heels":      "Каблучник",
    "umamusume":  "Умамуся",
    "tentacles":  "Тентакль-стайл",
    "yuri":       "Юрист",
    "femdom":     "Фемдом-госпожа",
    "video":      "Гифочник",
    "waifu":      "Вайфу-коллектор",
    "maid":       "Мейдоман",
    "ero":        "Эро-мастер",
    "hentai":     "Хентай-задрот",
    "ass":        "Жопошник",
    "oppai":      "Сиськоман",
    "milf":       "Милфолог",
    "oral":       "Рот на замке",
    "paizuri":    "Пазурщик",
    "ecchi":      "Эччи-извращ",
    "selfies":    "Селфи-фил",
    "uniform":    "Униформенный",
    "marin-kitagawa": "Марин-фаг",
    "mori-calliope":  "Мори-симпатяга",
    "raiden-shogun":  "Райден-шогун",
}
"""Маппинг тегов → смешные достижения для лидерборда."""

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


def get_tag_label(tag: str) -> str:
    """Возвращает человекочитаемое название тега для меню.

    Если для тега не задано отображаемое имя — возвращает сам тег.
    """
    return TAG_LABELS.get(tag, tag)


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


def is_femboy_tag(tag: str | None) -> bool:
    """Является ли тег femboy-тегом (e621)."""
    if tag is None:
        return False
    return tag in FEMBOY_TAGS


def is_furry_tag(tag: str | None) -> bool:
    """Является ли тег furry-тегом (e621)."""
    if tag is None:
        return False
    return tag in FURRY_TAGS


def is_furfem_tag(tag: str | None) -> bool:
    """Является ли тег furfem-тегом (e621, женские furry, нежирные, без футы)."""
    if tag is None:
        return False
    return tag in FURFEM_TAGS


def is_anthro_tag(tag: str | None) -> bool:
    """Является ли тег anthro-тегом (e621, без футанари)."""
    if tag is None:
        return False
    return tag in ANTHRO_TAGS


def is_feet_tag(tag: str | None) -> bool:
    """Является ли тег feet/heels-тегом (e621, ножки/пятки)."""
    if tag is None:
        return False
    return tag in FEET_TAGS


def is_umamusume_tag(tag: str | None) -> bool:
    """Является ли тег umamusume-тегом (yande/e621).

    Umamusume — фандом/персонажи, доступно на yande.re и e621.
    """
    if tag is None:
        return False
    return tag in UMAMUSUME_TAGS


def is_video_r34_tag(tag: str | None) -> bool:
    """Является ли тег видео-тегом (Rule34, ``animated``)."""
    if tag is None:
        return False
    return tag in VIDEO_R34_TAGS


def is_tentacles_tag(tag: str | None) -> bool:
    """Является ли тег тентаклей (Rule34)."""
    if tag is None:
        return False
    return tag in TENTACLES_TAGS


def is_yuri_tag(tag: str | None) -> bool:
    """Является ли тег юри (Rule34)."""
    if tag is None:
        return False
    return tag in YURI_TAGS


def is_femdom_tag(tag: str | None) -> bool:
    """Является ли тег фемдома (Rule34)."""
    if tag is None:
        return False
    return tag in FEMDOM_TAGS


def get_video_endpoint(tag: str) -> str:
    """Возвращает эндпоинт Purrbot для видео-тега. Если тег не найден — возвращает сам тег."""
    return VIDEO_ENDPOINTS.get(tag, tag)
