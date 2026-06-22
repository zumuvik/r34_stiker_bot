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
import time
import logging
import asyncio
import secrets

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineQuery,
    InlineQueryResultPhoto,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    InputMediaPhoto,
    Message,
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

FALLBACK_IMAGE_URL: str = "https://placehold.co/512x512/1a1a2e/ffffff?text=NSFW+Error"
# Заглушка на случай недоступности Waifu.im API или ошибочного ответа.

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

# Хранилище времени последнего нажатия кнопки для каждого пользователя.
_cooldowns: dict[int, float] = {}

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
    # Внимание: API чувствителен к регистру — параметры PascalCase!
    params: dict[str, str] = {"IsNsfw": "True"}
    if tag:
        params["IncludedTags"] = tag

    timeout = aiohttp.ClientTimeout(total=API_TIMEOUT_SECONDS)

    try:
        async with aiohttp.ClientSession(
            timeout=timeout,
            headers={"Accept-Version": "v7"},
        ) as session:
            async with session.get(WAIFU_API_URL, params=params) as response:
                # Проверка HTTP-статуса
                if response.status != 200:
                    body = await response.text()
                    logger.error(
                        "Waifu API вернул %s: %s", response.status, body
                    )
                    return FALLBACK_IMAGE_URL

                data = await response.json()
                # API возвращает список в поле "items" (не "images")
                items = data.get("items") or data.get("images", [])

                if not items:
                    logger.error("Waifu API вернул пустой список изображений")
                    return FALLBACK_IMAGE_URL

                return items[0]["url"]

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


def build_markup(tag: str | None, owner_id: int) -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру с кнопкой «🔥 Давай ещё!».

    В ``callback_data`` кодируется тег и ID владельца сообщения,
    чтобы при нажатии можно было проверить, что кнопку жмёт тот же
    пользователь.

    Формат callback_data:
        - ``more_random_{owner_id}`` — если тег не указан
        - ``more_{tag}_{owner_id}`` — если тег указан

    Args:
        tag: Текущий тег или ``None``.
        owner_id: Telegram ID пользователя, отправившего сообщение.

    Returns:
        Готовая ``InlineKeyboardMarkup`` с одной кнопкой.
    """
    tag_part = f"more_{tag}" if tag else "more_random"
    data = f"{tag_part}_{owner_id}"
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
    owner_id = query.from_user.id
    logger.info("Inline-запрос от %s: тег='%s'", owner_id, tag)

    image_url = await fetch_nsfw_image(tag)

    result = InlineQueryResultPhoto(
        # Случайный ID — предотвращает склейку одинаковых результатов
        # на стороне клиента Telegram.
        id=secrets.token_hex(8),
        photo_url=image_url,
        thumbnail_url=image_url,
        reply_markup=build_markup(tag, owner_id),
        caption=(
            f"<b>NSFW Anime</b>\n"
            f"Тег: {tag or 'random'}"
        ),
    )

    await query.answer(
        results=[result],
        cache_time=0,
        switch_pm_text="📋 Список тегов",
        switch_pm_parameter="tags",
    )


# ─────────────────── Callback Query Handler ───────────────────


@dp.callback_query(F.data.startswith("more_"))
async def handle_more_callback(callback: CallbackQuery) -> None:
    """
    Обрабатывает нажатие на кнопку «🔥 Давай ещё!».

    1. Извлекает тег и ID владельца из ``callback.data``.
    2. Проверяет, что кнопку нажал владелец сообщения.
    3. Проверяет кд (3 секунды между нажатиями).
    4. Запрашивает новое изображение у Waifu.im API.
    5. Редактирует медиа-контент в том же сообщении.
    """
    # Разбор callback_data: more_{tag}_{owner_id}
    payload = callback.data.removeprefix("more_")
    # payload = "maid_123456" или "random_123456" или "marin-kitagawa_123456"
    try:
        *tag_parts, owner_id_str = payload.rsplit("_", 1)
        owner_id = int(owner_id_str)
        tag_str = "_".join(tag_parts)
    except (ValueError, IndexError):
        logger.warning("Невалидный callback_data: %s", callback.data)
        await callback.answer("Ошибка данных", show_alert=True)
        return

    tag: str | None = tag_str if tag_str != "random" else None

    # ── Проверка владельца ────────────────────────────────
    clicker_id = callback.from_user.id
    if clicker_id != owner_id:
        logger.info("Чужой нажал кнопку: %s (владелец %s)", clicker_id, owner_id)
        await callback.answer(
            "❌ Это могут нажимать только тот, кто отправил картинку.",
            show_alert=True,
        )
        return

    # ── Проверка кд ──────────────────────────────────────
    now = time.time()
    last = _cooldowns.get(clicker_id, 0.0)
    if now - last < BUTTON_COOLDOWN:
        remaining = int(BUTTON_COOLDOWN - (now - last))
        logger.info("Кд у %s: осталось %dс", clicker_id, remaining)
        await callback.answer(
            f"⏳ Подожди {remaining} с перед следующим нажатием.",
            show_alert=True,
        )
        return

    _cooldowns[clicker_id] = now

    logger.info(
        "Callback от %s: новый контент, тег='%s'",
        clicker_id,
        tag,
    )

    image_url = await fetch_nsfw_image(tag)

    media = InputMediaPhoto(
        media=image_url,
        caption=(
            f"<b>NSFW Anime</b>\n"
            f"Тег: {tag or 'random'}"
        ),
    )

    try:
        # Для сообщений, отправленных через инлайн-режим, callback.message
        # приходит None, а идентификатор хранится в inline_message_id.
        if callback.inline_message_id:
            await bot.edit_message_media(
                inline_message_id=callback.inline_message_id,
                media=media,
                reply_markup=build_markup(tag, owner_id),
            )
        else:
            await callback.message.edit_media(
                media=media,
                reply_markup=build_markup(tag, owner_id),
            )
        await callback.answer()  # Закрываем состояние загрузки на кнопке
    except Exception as exc:
        logger.error("Не удалось отредактировать сообщение: %s", exc)
        await callback.answer(
            "Не удалось обновить картинку. Попробуйте ещё раз.",
            show_alert=True,
        )


# ─────────────────── Command /start — список тегов ───────────────────


@dp.message(CommandStart())
async def handle_start(message: Message) -> None:
    """Отправляет список доступных тегов при /start."""
    tags_text = (
        "🏷 <b>Доступные теги</b>\n\n"
        + "\n".join(f"• <code>{t}</code>" for t in sorted(VALID_TAGS))
        + "\n\n"
        "Просто напиши <code>@Waifulinuxbot &lt;тег&gt;</code> в любом чате."
    )
    await message.answer(tags_text)


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
