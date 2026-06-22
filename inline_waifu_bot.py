#!/usr/bin/env python3
"""
Inline NSFW Telegram Bot (18+)
================================

Работает исключительно в инлайн-режиме. Пользователь вызывает бота
через `@bot_username [тег]` в любом чате, получает NSFW-изображение
из Waifu.im API с возможностью динамической смены контента по кнопке.

Технологии: aiogram 3.x, aiohttp, Waifu.im API

Запуск:
    export BOT_TOKEN="your_token_here"
    python inline_waifu_bot.py

Зависимости:
    pip install aiogram aiohttp
"""

import os
import sys
import logging
import asyncio
import secrets

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    InlineQuery,
    InlineQueryResultPhoto,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    InputMediaPhoto,
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# ─────────────────── Конфигурация ───────────────────

BOT_TOKEN: str | None = os.getenv("BOT_TOKEN")
"""Токен бота из переменной окружения `BOT_TOKEN`."""

if not BOT_TOKEN:
    print("FATAL: Укажите BOT_TOKEN в переменных окружения.", file=sys.stderr)
    sys.exit(1)

WAIFU_API_URL: str = "https://api.waifu.im/images"
"""Базовый эндпоинт Waifu.im API."""

FALLBACK_IMAGE_URL: str = (
    "https://placehold.co/512x512/1a1a2e/ffffff?text=NSFW+Error"
    """
    Изображение-заглушка на случай, если Waifu.im API недоступен
    или вернул некорректный ответ.
    """
)

API_TIMEOUT_SECONDS: int = 5
"""Таймаут HTTP-запроса к Waifu.im API (в секундах)."""

# Допустимые теги, которые принимает бот.
# Актуальный список: https://waifu.im/docs
VALID_TAGS: frozenset[str] = frozenset({
    "waifu", "maid", "ero", "hentai", "ass", "oppai",
    "milf", "oral", "paizuri", "ecchi", "selfies",
    "uniform", "marin-kitagawa", "mori-calliope",
    "raiden-shogun",
})

# ─────────────────── Логирование ───────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─────────────────── Bot & Dispatcher ───────────────────

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# ─────────────────── Работа с Waifu.im API ───────────────────


async def fetch_nsfw_image(tag: str | None = None) -> str:
    """
    Запрашивает NSFW-изображение у Waifu.im API.

    1. Формирует query-параметры: ``is_nsfw=true`` и, если передан тег,
       ``included_tags={tag}``.
    2. Совершает GET-запрос с таймаутом 5 секунд.
    3. Парсит ответ, извлекает URL первого изображения.
    4. При любой ошибке (сеть, таймаут, кривой JSON, пустой ответ)
       возвращает URL заглушки.

    Args:
        tag: Опциональный тег для фильтрации (например ``"maid"``, ``"ero"``).

    Returns:
        Прямой URL изображения (строка) или ``FALLBACK_IMAGE_URL``.
    """
    params: dict[str, str] = {"is_nsfw": "true"}
    if tag:
        params["included_tags"] = tag

    timeout = aiohttp.ClientTimeout(total=API_TIMEOUT_SECONDS)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(WAIFU_API_URL, params=params) as response:
                # Проверка HTTP-статуса
                if response.status != 200:
                    body = await response.text()
                    logger.error(
                        "Waifu API вернул %s: %s", response.status, body
                    )
                    return FALLBACK_IMAGE_URL

                data = await response.json()
                images = data.get("images", [])

                if not images:
                    logger.error("Waifu API вернул пустой список изображений")
                    return FALLBACK_IMAGE_URL

                return images[0]["url"]

    except asyncio.TimeoutError:
        logger.error(
            "Таймаут запроса к Waifu.im API (%s сек)", API_TIMEOUT_SECONDS
        )
        return FALLBACK_IMAGE_URL
    except aiohttp.ClientError as exc:
        logger.error("HTTP-ошибка при запросе к Waifu.im API: %s", exc)
        return FALLBACK_IMAGE_URL
    except (KeyError, IndexError, ValueError) as exc:
        logger.error("Ошибка парсинга ответа Waifu API: %s", exc)
        return FALLBACK_IMAGE_URL
    except Exception as exc:
        logger.exception("Неожиданная ошибка при запросе к Waifu.im API: %s", exc)
        return FALLBACK_IMAGE_URL


# ─────────────────── Вспомогательные функции ───────────────────


def build_markup(tag: str | None) -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру с кнопкой «🔥 Давай ещё!».

    В ``callback_data`` кодируется текущий тег, чтобы при повторном
    нажатии запрашивать контент той же категории.

    Формат callback_data:
        - ``more_random`` — если тег не указан
        - ``more_{tag}`` — если тег указан (например ``more_maid``)

    Args:
        tag: Текущий тег или ``None``.

    Returns:
        Готовая ``InlineKeyboardMarkup`` с одной кнопкой.
    """
    data = f"more_{tag}" if tag else "more_random"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔥 Давай ещё!",
                    callback_data=data,
                )
            ]
        ]
    )


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


# ─────────────────── Inline Query Handler ───────────────────


@dp.inline_query()
async def handle_inline_query(query: InlineQuery) -> None:
    """
    Обрабатывает инлайн-запрос: ``@bot_username [тег]``.

    Валидирует тег → запрашивает изображение через Waifu.im API →
    возвращает один ``InlineQueryResultPhoto`` с кнопкой для смены контента.

    ``cache_time=0`` отключает серверное кэширование результата,
    чтобы каждый новый запрос выдавал свежую картинку.
    """
    tag = validate_tag(query.query)
    logger.info("Inline-запрос от %s: тег='%s'", query.from_user.id, tag)

    image_url = await fetch_nsfw_image(tag)

    result = InlineQueryResultPhoto(
        # Случайный ID — предотвращает склейку одинаковых результатов
        # на стороне клиента Telegram.
        id=secrets.token_hex(8),
        photo_url=image_url,
        thumbnail_url=image_url,
        reply_markup=build_markup(tag),
        caption=(
            f"<b>NSFW Anime</b>\n"
            f"Тег: {tag or 'random'}\n"
            f"<i>Нажми «Давай ещё!» для новой картинки</i>"
        ),
    )

    await query.answer(results=[result], cache_time=0)


# ─────────────────── Callback Query Handler ───────────────────


@dp.callback_query(F.data.startswith("more_"))
async def handle_more_callback(callback: CallbackQuery) -> None:
    """
    Обрабатывает нажатие на кнопку «🔥 Давай ещё!».

    1. Извлекает тег из ``callback.data`` (формат: ``more_{tag}``).
    2. Запрашивает новое изображение у Waifu.im API.
    3. Редактирует медиа-контент в том же сообщении через
       ``callback.message.edit_media()``.
    4. Сохраняет ту же клавиатуру (с актуальным тегом).
    """
    # Разбор callback_data
    tag_raw = callback.data.removeprefix("more_")
    tag: str | None = tag_raw if tag_raw != "random" else None

    logger.info(
        "Callback от %s: новый контент, тег='%s'",
        callback.from_user.id,
        tag,
    )

    image_url = await fetch_nsfw_image(tag)

    media = InputMediaPhoto(
        media=image_url,
        caption=(
            f"<b>NSFW Anime</b>\n"
            f"Тег: {tag or 'random'}\n"
            f"<i>Нажми «Давай ещё!» для новой картинки</i>"
        ),
    )

    try:
        # edit_media поддерживает как обычные сообщения, так и те,
        # что были отправлены через инлайн-режим.
        await callback.message.edit_media(
            media=media,
            reply_markup=build_markup(tag),
        )
        await callback.answer()  # Закрываем состояние загрузки на кнопке
    except Exception as exc:
        logger.error("Не удалось отредактировать сообщение: %s", exc)
        await callback.answer(
            "Не удалось обновить картинку. Попробуйте ещё раз.",
            show_alert=True,
        )


# ─────────────────── Точка входа ───────────────────


async def main() -> None:
    """Запускает поллинг бота."""
    logger.info("Бот запущен. Ожидание инлайн-запросов...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")
        sys.exit(0)
