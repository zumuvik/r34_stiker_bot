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

# ── Порядок импорта важен: core → config/api/keyboard → handlers → app ──
from .core import bot, dp  # noqa: F401, E402
from .config import (  # noqa: F401, E402
    BOT_TOKEN,
    WAIFU_API_URL,
    FALLBACK_IMAGE_URL,
    API_TIMEOUT_SECONDS,
    BUTTON_COOLDOWN,
    VALID_TAGS,
    PHOTO_TAGS,
    VIDEO_TAGS,
    VIDEO_SUBREDDITS,
    validate_tag,
    is_video_tag,
    is_photo_tag,
    get_subreddit,
)
from .api import fetch_nsfw_content  # noqa: F401, E402
from .keyboard import build_markup  # noqa: F401, E402

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
