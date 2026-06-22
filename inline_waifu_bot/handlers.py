"""
Обработчики событий aiogram.

Всё взаимодействие происходит в том же чате, где вызван инлайн.
Никаких переходов в ЛС бота.
Каждая кнопка проверяет, что нажал именно создатель инлайн-сообщения.
Поддерживаются фото (Waifu.im) и видео (Reddit).
"""

import logging
import secrets
import time

from aiogram import F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputMediaPhoto,
    InputMediaVideo,
    InputTextMessageContent,
    Message,
)

from .api import fetch_nsfw_content
from . import config
from .core import bot, dp
from .keyboard import build_markup

logger = logging.getLogger(__name__)

# Хранилище времени последнего нажатия кнопки для каждого пользователя.
_cooldowns: dict[int, float] = {}


# ─────────────────── Хелпер: создать InputMedia ───────────────────


def _build_media(
    media_url: str,
    media_type: str,
    caption: str,
) -> InputMediaPhoto | InputMediaVideo:
    """
    Создаёт ``InputMediaPhoto`` или ``InputMediaVideo`` с has_spoiler=True.
    """
    cls = InputMediaVideo if media_type == "video" else InputMediaPhoto
    return cls(media=media_url, caption=caption, has_spoiler=True)


# ─────────────────── Хелпер: отредактировать сообщение ───────────────────


async def _edit_message(
    callback: CallbackQuery,
    media: InputMediaPhoto | InputMediaVideo,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    """
    Редактирует сообщение: через ``bot.edit_message_media`` если
    ``inline_message_id`` есть, иначе через ``callback.message.edit_media``.
    """
    if callback.inline_message_id:
        await bot.edit_message_media(
            inline_message_id=callback.inline_message_id,
            media=media,
            reply_markup=reply_markup,
        )
    else:
        await callback.message.edit_media(
            media=media,
            reply_markup=reply_markup,
        )


# ─────────────────── Inline Query Handler ───────────────────


@dp.inline_query()
async def handle_inline_query(query: InlineQuery) -> None:
    """
    Обрабатывает инлайн-запрос: ``@bot_username [тег]``.

    Возвращает ``InlineQueryResultArticle`` — текст-заглушку с кнопкой
    верификации. В callback_data зашит ``creator_id``.
    """
    creator_id = query.from_user.id
    tag = config.validate_tag(query.query)
    logger.info("Inline-запрос от %s: тег='%s'", creator_id, tag)

    tag_display = tag or "random"
    cb_verify = f"verify_18:{creator_id}:{tag_display}"

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


# ─────────────────── Callback: верификация 18+ → контент ───────────────────


@dp.callback_query(F.data.startswith("verify_18:"))
async def handle_verify_callback(callback: CallbackQuery) -> None:
    """
    Обрабатывает нажатие «Мне есть 18 лет ✅».

    1. Проверяет создателя.
    2. Запрашивает контент (фото или видео).
    3. Заменяет текст-заглушку на контент под спойлером.
    4. При ошибке видео — фоллбэк на фото с котом.
    """
    payload = callback.data.removeprefix("verify_18:")
    try:
        creator_id_str, tag_str = payload.split(":", 1)
        creator_id = int(creator_id_str)
    except (ValueError, IndexError):
        logger.warning("Невалидный callback_data: %s", callback.data)
        await callback.answer("Ошибка данных", show_alert=True)
        return

    clicker_id = callback.from_user.id
    if clicker_id != creator_id:
        logger.info(
            "Чужой нажал verify: %s (создатель %s)", clicker_id, creator_id,
        )
        await callback.answer(
            "Это сообщение создал другой пользователь. "
            "Введи @username бота сам!",
            show_alert=True,
        )
        return

    tag: str | None = tag_str if tag_str != "random" else None
    tag_display = tag or "random"

    logger.info(
        "Verify 18+ от %s: тег='%s', inline=%s",
        creator_id, tag, bool(callback.inline_message_id),
    )

    await callback.answer()

    media_url, media_type = await fetch_nsfw_content(tag)
    caption = f"<b>NSFW Anime</b>\nТег: {tag_display}"
    media_obj = _build_media(media_url, media_type, caption)

    try:
        await _edit_message(callback, media_obj, build_markup(tag, creator_id))
    except TelegramBadRequest as exc:
        logger.warning(
            "Verify media (type=%s) failed edit: %s. Falling back to cat photo.",
            media_type, exc,
        )
        fallback = InputMediaPhoto(
            media=config.FALLBACK_IMAGE_URL,
            caption=(
                f"<b>NSFW Anime</b> (фолбэк)\n"
                f"Тег: {tag_display}"
            ),
        )
        await _edit_message(callback, fallback, build_markup(tag, creator_id))
    except Exception as exc:
        logger.error(
            "Не удалось показать контент после верификации: %s", exc
        )


# ─────────────────── Callback: Давай ещё! ───────────────────


@dp.callback_query(F.data.startswith("more:"))
async def handle_more_callback(callback: CallbackQuery) -> None:
    """
    Обрабатывает нажатие на кнопку «🔥 Давай ещё!».

    1. Проверяет создателя и кд.
    2. Запрашивает новый контент.
    3. Редактирует сообщение.
    4. При ошибке видео — фоллбэк на фото с котом.
    """
    payload = callback.data.removeprefix("more:")
    try:
        creator_id_str, tag_str = payload.split(":", 1)
        creator_id = int(creator_id_str)
    except (ValueError, IndexError):
        logger.warning("Невалидный callback_data: %s", callback.data)
        await callback.answer("Ошибка данных", show_alert=True)
        return

    tag: str | None = tag_str if tag_str != "random" else None

    # ── Проверка владельца ────────────────────────────────
    clicker_id = callback.from_user.id
    if clicker_id != creator_id:
        logger.info(
            "Чужой нажал more: %s (создатель %s)", clicker_id, creator_id,
        )
        await callback.answer(
            "Это сообщение создал другой пользователь. "
            "Введи @username бота сам!",
            show_alert=True,
        )
        return

    # ── Проверка кд ──────────────────────────────────────
    now = time.time()
    last = _cooldowns.get(clicker_id, 0.0)
    if now - last < config.BUTTON_COOLDOWN:
        remaining = int(config.BUTTON_COOLDOWN - (now - last))
        logger.info("Кд у %s: осталось %dс", clicker_id, remaining)
        await callback.answer(
            f"⏳ Подожди {remaining} с перед следующим нажатием.",
            show_alert=True,
        )
        return

    _cooldowns[clicker_id] = now

    logger.info(
        "More callback от %s: новый контент, тег='%s'",
        clicker_id, tag,
    )

    media_url, media_type = await fetch_nsfw_content(tag)
    caption = f"<b>NSFW Anime</b>\nТег: {tag or 'random'}"
    media_obj = _build_media(media_url, media_type, caption)

    try:
        await _edit_message(callback, media_obj, build_markup(tag, creator_id))
        await callback.answer()
    except TelegramBadRequest as exc:
        logger.warning(
            "More media (type=%s) failed edit: %s. Falling back to cat photo.",
            media_type, exc,
        )
        fallback = InputMediaPhoto(
            media=config.FALLBACK_IMAGE_URL,
            caption=(
                f"<b>NSFW Anime</b> (фолбэк)\n"
                f"Тег: {tag or 'random'}"
            ),
            has_spoiler=True,
        )
        await _edit_message(callback, fallback, build_markup(tag, creator_id))
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
        + "\n".join(f"• <code>{t}</code>" for t in sorted(config.VALID_TAGS))
        + "\n\n"
        "Просто напиши <code>@Waifulinuxbot &lt;тег&gt;</code> в любом чате."
    )
    await message.answer(tags_text)
