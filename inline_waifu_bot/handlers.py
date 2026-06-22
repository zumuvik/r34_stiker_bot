"""
Обработчики событий aiogram.
"""

import logging
import secrets
import time

from aiogram import F
from aiogram.filters import CommandStart
from aiogram.types import (
    ChosenInlineResult,
    InlineQuery,
    InlineQueryResultPhoto,
    CallbackQuery,
    InputMediaPhoto,
    Message,
)

from .core import bot, dp
from .config import (
    VALID_TAGS,
    BUTTON_COOLDOWN,
    PLACEHOLDER_IMAGE_URL,
    validate_tag,
)
from .api import fetch_nsfw_image
from .keyboard import build_markup

logger = logging.getLogger(__name__)

# Хранилище времени последнего нажатия кнопки для каждого пользователя.
_cooldowns: dict[int, float] = {}


# ─────────────────── Inline Query Handler ───────────────────


@dp.inline_query()
async def handle_inline_query(query: InlineQuery) -> None:
    """
    Обрабатывает инлайн-запрос: ``@bot_username [тег]``.

    Возвращает ``InlineQueryResultPhoto`` с картинкой-плейсхолдером
    (без спойлера — Telegram API не поддерживает спойлер в этом типе).
    Сразу после отправки срабатывает ``handle_chosen_inline_result``,
    который заменяет плейсхолдер на реальное NSFW-изображение под спойлером.
    """
    tag = validate_tag(query.query)
    owner_id = query.from_user.id
    logger.info("Inline-запрос от %s: тег='%s'", owner_id, tag)

    tag_display = tag or "random"

    result = InlineQueryResultPhoto(
        id=secrets.token_hex(8),
        photo_url=PLACEHOLDER_IMAGE_URL,
        thumbnail_url=PLACEHOLDER_IMAGE_URL,
        caption=(
            f"<b>NSFW Anime</b>\n"
            f"Тег: {tag_display}"
        ),
        reply_markup=build_markup(tag, owner_id),
    )

    await query.answer(
        results=[result],
        cache_time=0,
        is_personal=True,
        switch_pm_text="📋 Список тегов",
        switch_pm_parameter="tags",
    )


# ─────────────────── Chosen Inline Result — замена плейсхолдера ───────────────────


@dp.chosen_inline_result()
async def handle_chosen_inline_result(chosen: ChosenInlineResult) -> None:
    """
    Обрабатывает выбор инлайн-результата пользователем.

    Заменяет картинку-плейсхолдер на реальное изображение с Waifu.im
    под спойлером (``InputMediaPhoto(has_spoiler=True)``).
    """
    if not chosen.inline_message_id:
        return

    tag = validate_tag(chosen.query)
    owner_id = chosen.from_user.id
    logger.info(
        "ChosenInlineResult от %s: тег='%s', msg=%s",
        owner_id, tag, chosen.inline_message_id,
    )

    image_url = await fetch_nsfw_image(tag)

    media = InputMediaPhoto(
        media=image_url,
        caption=(
            f"<b>NSFW Anime</b>\n"
            f"Тег: {tag or 'random'}"
        ),
        has_spoiler=True,
    )

    try:
        await bot.edit_message_media(
            inline_message_id=chosen.inline_message_id,
            media=media,
            reply_markup=build_markup(tag, owner_id),
        )
    except Exception as exc:
        logger.error("Не удалось заменить плейсхолдер: %s", exc)


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
    payload = callback.data.removeprefix("more_")
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
            f"⏳ Подожди {remaining} с перед следующим нажатием.",
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
        has_spoiler=True,
    )

    try:
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
        await callback.answer()
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
