"""
Обработчики событий aiogram.

Всё взаимодействие происходит в том же чате, где вызван инлайн.
Никаких переходов в ЛС бота.
"""

import logging
import secrets
import time

from aiogram import F
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    InputMediaPhoto,
    Message,
)

from .core import bot, dp
from .config import VALID_TAGS, BUTTON_COOLDOWN, validate_tag
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

    Возвращает ``InlineQueryResultArticle`` — текст-заглушку с кнопкой
    верификации. Никакого NSFW-превью в панели выбора.
    Верификация и показ фото происходят в том же чате.
    """
    tag = validate_tag(query.query)
    logger.info("Inline-запрос от %s: тег='%s'", query.from_user.id, tag)

    tag_display = tag or "random"
    cb_verify = f"verify_18_{tag}" if tag else "verify_18_random"

    article = InlineQueryResultArticle(
        id=secrets.token_hex(8),
        title=f"🔞 Подрочить на {tag_display}",
        description="Требуется подтверждение 18+",
        input_message_content=InputTextMessageContent(
            message_text=(
                f"⚠️ <b>Контент 18+ скрыт</b>\n\n"
                f"Подтвердите, что вам есть 18 лет, чтобы открыть "
                f"изображение с тегом <code>{tag_display}</code>."
            ),
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Мне есть 18 лет ✅",
                        callback_data=cb_verify,
                    ),
                ]
            ]
        ),
    )

    await query.answer(
        results=[article],
        cache_time=0,
        is_personal=True,
        switch_pm_text="📋 Список тегов",
        switch_pm_parameter="tags",
    )


# ─────────────────── Callback: верификация 18+ → фото ───────────────────


@dp.callback_query(F.data.startswith("verify_18_"))
async def handle_verify_callback(callback: CallbackQuery) -> None:
    """
    Обрабатывает нажатие «Мне есть 18 лет ✅».

    Заменяет текст-заглушку в том же чате на NSFW-фото под спойлером
    (``InputMediaPhoto(has_spoiler=True)``) с кнопкой «🔥 Давай ещё!».
    """
    tag_raw = callback.data.removeprefix("verify_18_")
    tag: str | None = tag_raw if tag_raw != "random" else None
    owner_id = callback.from_user.id
    tag_display = tag or "random"

    logger.info(
        "Verify 18+ от %s: тег='%s', inline=%s",
        owner_id, tag, bool(callback.inline_message_id),
    )

    await callback.answer()

    image_url = await fetch_nsfw_image(tag)

    media = InputMediaPhoto(
        media=image_url,
        caption=(
            f"<b>NSFW Anime</b>\n"
            f"Тег: {tag_display}"
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
    except Exception as exc:
        logger.error("Не удалось показать фото после верификации: %s", exc)


# ─────────────────── Callback: Давай ещё! ───────────────────


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
        clicker_id, tag,
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
