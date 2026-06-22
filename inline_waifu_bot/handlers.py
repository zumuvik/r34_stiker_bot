"""
Обработчики событий aiogram.

Всё взаимодействие происходит в том же чате, где вызван инлайн.
Никаких переходов в ЛС бота.
Каждая кнопка проверяет, что нажал именно создатель инлайн-сообщения.
Поддерживаются фото (Waifu.im) и видео (Reddit).
"""

import asyncio
import logging
import math
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
from . import database
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


# ─────────────────── Хелпер: генерация статистики ───────────────────


async def _generate_stats(user_id: int, username: str | None) -> str:
    """
    Генерирует случайное изменение спермы (+/- 1-50), обновляет БД
    и возвращает строку формата::

        {фраза} | {✅/❌} | {+/-X мл спермы}
    """
    delta = secrets.randbelow(50) + 1          # 1–50
    is_positive = secrets.randbelow(2) == 0     # 50/50

    if is_positive:
        phrase = secrets.choice(config.POSITIVE_PHRASES)
        sign = "✅"
        delta_str = f"+{delta}"
    else:
        phrase = secrets.choice(config.NEGATIVE_PHRASES)
        sign = "❌"
        delta_str = f"-{delta}"
        delta = -delta                          # физический дельта для БД

    # Обновляем БД в пуле потоков (SQLite — синхронный).
    await asyncio.to_thread(
        database.update_user_sperm, user_id, username or "", delta,
    )

    return f"{phrase} | {sign} | {delta_str} мл спермы"


# ─────────────────── Inline Query Handler ───────────────────


@dp.inline_query()
async def handle_inline_query(query: InlineQuery) -> None:
    """
    Обрабатывает инлайн-запрос: ``@bot_username [тег]``.

    - Пустой запрос → лидерборд + список тегов.
    - ``top`` → только лидерборд.
    - ``stats`` → только личная статистика.
    - ``<тег>`` → только верификация для тега.
    """
    user_query = query.query.strip().lower()
    creator_id = query.from_user.id

    # ── short-circuit: top → лидерборд, stats → личная статистика ──
    if user_query == "top":
        await _answer_leaderboard(query, creator_id)
        return
    if user_query == "stats":
        await _answer_stats(query, creator_id)
        return

    # ── Пустой запрос → лидерборд + все теги ───────────────────
    if not user_query:
        await _answer_leaderboard_with_tags(query, creator_id)
        return

    # ── Конкретный тег или произвольный запрос → верификация ────
    tag = config.validate_tag(query.query)
    logger.info("Inline-запрос от %s: тег='%s'", creator_id, tag)

    tag_display = tag or "random"
    article = _make_verify_article(creator_id, tag_display)

    await query.answer(
        results=[article],
        cache_time=0,
        is_personal=True,
    )


def _make_verify_article(creator_id: int, tag_display: str) -> InlineQueryResultArticle:
    """Собирает InlineQueryResultArticle с кнопкой верификации для tag_display."""
    return InlineQueryResultArticle(
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
                        callback_data=f"verify_18:{creator_id}:{tag_display}",
                    ),
                ]
            ]
        ),
    )


async def _build_leaderboard_text() -> str:
    """Формирует текст лидерборда (только топ, без личной статистики)."""
    top_users = await asyncio.to_thread(database.get_leaderboard, 10)
    if not top_users:
        return (
            "🏆 <b>ТОП-10 САМЫХ ШПЕРМАПРИЕМНИКОВ ЧАТА</b>\n\n"
            "Пока никого нет. Начни дрочить первым! 🔞"
        )

    lines = ["🏆 <b>ТОП-10 САМЫХ ШПЕРМАПРИЕМНИКОВ ЧАТА</b>\n\n"]
    for i, u in enumerate(top_users, 1):
        name = u["username"] or f"User #{u['user_id']}"
        sperm = u["total_sperm"]
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        lines.append(f"{medal} <b>{name}</b> — {sperm} мл спермы")
    return "\n".join(lines)


async def _build_stats_text(user_id: int) -> str:
    """Формирует текст личной статистики."""
    fav_tags = await asyncio.to_thread(database.get_user_favorite_tags, user_id)
    if fav_tags:
        tags_str = ", ".join(
            f"{t['tag']} ({t['count']} раз)" for t in fav_tags
        )
        return (
            "📊 <b>Твоя статистика</b>\n\n"
            f"Излюбленные теги: {tags_str}"
        )
    return (
        "📊 <b>Твоя статистика</b>\n\n"
        "Ты ещё не дрочил, твоя история пуста."
    )


async def _answer_leaderboard(query: InlineQuery, user_id: int) -> None:
    """Отвечает только лидербордом (один результат)."""
    text = await _build_leaderboard_text()
    article = InlineQueryResultArticle(
        id=secrets.token_hex(8),
        title="🏆 ТОП-10 САМЫХ ШПЕРМАПРИЕМНИКОВ ЧАТА",
        description="Посмотреть таблицу лидеров",
        input_message_content=InputTextMessageContent(
            message_text=text,
            parse_mode="HTML",
        ),
    )
    await query.answer(results=[article], cache_time=0, is_personal=True)


async def _answer_stats(query: InlineQuery, user_id: int) -> None:
    """Отвечает только личной статистикой (один результат)."""
    text = await _build_stats_text(user_id)
    article = InlineQueryResultArticle(
        id=secrets.token_hex(8),
        title="📊 Твоя статистика",
        description="Твои теги и активность",
        input_message_content=InputTextMessageContent(
            message_text=text,
            parse_mode="HTML",
        ),
    )
    await query.answer(results=[article], cache_time=0, is_personal=True)


async def _answer_leaderboard_with_tags(query: InlineQuery, user_id: int) -> None:
    """Отвечает лидербордом + списком всех тегов."""
    # Лидерборд
    text = await _build_leaderboard_text()
    results: list[InlineQueryResultArticle] = [
        InlineQueryResultArticle(
            id=secrets.token_hex(8),
            title="🏆 ТОП-10 САМЫХ ШПЕРМАПРИЕМНИКОВ ЧАТА",
            description="Посмотреть таблицу лидеров",
            input_message_content=InputTextMessageContent(
                message_text=text,
                parse_mode="HTML",
            ),
        ),
    ]

    # Random — сразу после лидерборда
    results.append(_make_verify_article(user_id, "random"))

    # Все доступные теги
    for tag in sorted(config.VALID_TAGS):
        results.append(_make_verify_article(user_id, tag))

    await query.answer(
        results=results,
        cache_time=0,
        is_personal=True,
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

    # Статистика генерируется ДО редактирования (один редактив с полным caption).
    stats_line = await _generate_stats(creator_id, callback.from_user.username)

    media_url, media_type, display_tag = await fetch_nsfw_content(tag)
    # Трекинг реального тега (не "random") в БД
    await asyncio.to_thread(database.increment_tag_count, creator_id, display_tag)
    caption = f"<b>NSFW Anime</b>\nТег: {display_tag}\n{stats_line}"
    media_obj = _build_media(media_url, media_type, caption)

    try:
        await _edit_message(callback, media_obj, build_markup(tag, creator_id))
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            logger.info("Verify — контент не изменился, пропускаем.")
            return
        logger.warning(
            "Verify media (type=%s) failed edit: %s. Falling back to cat photo.",
            media_type, exc,
        )
        fallback = InputMediaPhoto(
            media=config.FALLBACK_IMAGE_URL,
            caption=(
                f"<b>NSFW Anime</b> (фолбэк)\n"
                f"Тег: {display_tag}\n"
                f"{stats_line}"
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
        remaining = math.ceil(config.BUTTON_COOLDOWN - (now - last))
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

    stats_line = await _generate_stats(clicker_id, callback.from_user.username)

    media_url, media_type, display_tag = await fetch_nsfw_content(tag)
    # Трекинг реального тега (не "random") в БД
    await asyncio.to_thread(database.increment_tag_count, clicker_id, display_tag)
    caption = f"<b>NSFW Anime</b>\nТег: {display_tag}\n{stats_line}"
    media_obj = _build_media(media_url, media_type, caption)

    try:
        await _edit_message(callback, media_obj, build_markup(tag, creator_id))
        await callback.answer()
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            logger.info("More — контент не изменился, пропускаем.")
            await callback.answer()
            return
        logger.warning(
            "More media (type=%s) failed edit: %s. Falling back to cat photo.",
            media_type, exc,
        )
        fallback = InputMediaPhoto(
            media=config.FALLBACK_IMAGE_URL,
            caption=(
                f"<b>NSFW Anime</b> (фолбэк)\n"
                f"Тег: {display_tag}\n"
                f"{stats_line}"
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
