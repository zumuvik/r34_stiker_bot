"""
Inline NSFW Telegram Bot (18+)
===============================

Работает исключительно в инлайн-режиме. Пользователь вызывает бота
через ``@bot_username [тег]`` в любом чате, получает NSFW-изображение
из Waifu.im API с возможностью динамической смены контента по кнопке.

Технологии: aiogram 3.x, aiohttp, Waifu.im API

Запуск:
    # 1. Создать .env с BOT_TOKEN=...
    # 2. python -m inline_waifu_bot

Зависимости:
    pip install aiogram aiohttp
"""

import logging

# ── Логирование (должно быть настроено до всего остального) ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── Порядок импорта важен: core → config/api/database/keyboard → handlers → app ──
from .core import bot, dp  # noqa: F401, E402
from .config import (  # noqa: F401, E402
    BOT_TOKEN,
    WAIFU_API_URL,
    FALLBACK_IMAGE_URL,
    FEMBOY_API_URL,
    FURRY_API_URL,
    API_TIMEOUT_SECONDS,
    BUTTON_COOLDOWN,
    POSITIVE_PHRASES,
    NEGATIVE_PHRASES,
    VALID_TAGS,
    PHOTO_TAGS,
    VIDEO_TAGS,
    FEMBOY_TAGS,
    FURRY_TAGS,
    ANTHRO_TAGS,
    FURFEM_TAGS,
    FEET_TAGS,
    YANDE_RE_API_URL,
    YANDE_RE_TAGS,
    UMAMUSUME_TAGS,
    VIDEO_R34_TAGS,
    TENTACLES_TAGS,
    YURI_TAGS,
    FEMDOM_TAGS,
    TAG_LABELS,
    TAG_ACHIEVEMENTS,
    VIDEO_ENDPOINTS,
    validate_tag,
    get_tag_label,
    is_video_tag,
    is_photo_tag,
    is_femboy_tag,
    is_furry_tag,
    is_anthro_tag,
    is_furfem_tag,
    is_feet_tag,
    is_umamusume_tag,
    is_video_r34_tag,
    is_tentacles_tag,
    is_yuri_tag,
    is_femdom_tag,
    get_video_endpoint,
)
from .api import fetch_nsfw_content  # noqa: F401, E402
from .keyboard import build_markup  # noqa: F401, E402
from .database import (  # noqa: F401, E402
    init_db,
    update_user_sperm,
    get_leaderboard,
    get_connection,
    increment_tag_count,
    get_user_favorite_tags,
)

# Регистрация хэндлеров на dp (выполняется в момент импорта).
from . import handlers  # noqa: F401, E402

from .app import main  # noqa: F401, E402

# Явный реэкспорт для тестов (импортирующих модуль).
from .handlers import (  # noqa: F401, E402
    handle_inline_query,
    handle_verify_callback,
    handle_more_callback,
    handle_start,
    _cooldowns,
)
