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
    InputMediaAnimation,
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
) -> InputMediaAnimation | InputMediaPhoto | InputMediaVideo:
    """
    Создаёт ``InputMediaPhoto`` / ``InputMediaVideo`` / ``InputMediaAnimation``
    с ``has_spoiler=True``.

    Все типы анимаций/видео идут через ``InputMediaVideo`` — спойлер
    работает надёжнее, чем через ``InputMediaAnimation``.
    ``InputMediaAnimation`` используется только как fallback, если
    ``media_type="animation"``.
    """
    if media_url.lower().endswith(".gif") or media_type == "video":
        return InputMediaVideo(media=media_url, caption=caption, has_spoiler=True, supports_streaming=True)
    if media_type == "animation":
        return InputMediaAnimation(media=media_url, caption=caption, has_spoiler=True)
    return InputMediaPhoto(media=media_url, caption=caption, has_spoiler=True)


# ─────────────────── Хелпер: отредактировать сообщение ───────────────────


async def _edit_message(
    callback: CallbackQuery,
    media: InputMediaAnimation | InputMediaPhoto | InputMediaVideo,
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
    Генерирует изменение спермы по тирам с весами, обновляет БД
    и возвращает строку формата::

        {фраза} | {✅/❌} | {+/-X мл спермы}

    Новые шансы (сумма весов = 100):
    - +10  30 %,  +25  28 %,  +50  15 %,  +100  10 %
    - +500  1 %           (было 5 %)
    - -200  2 %           (новый крупный минус)
    - -10  8 %,  -25  6 %

    Пол в нуле УБРАН — баланс может быть отрицательным.
    """
    # Тиры: (дельта, вес) — сумма = 100
    TIERS: list[tuple[int, int]] = [
        (10,   30),   # +10   30 %
        (25,   28),   # +25   28 %
        (50,   15),   # +50   15 %
        (100,  10),   # +100  10 %
        (500,   1),   # +500   1 %
        (-10,   8),   # -10    8 %
        (-25,   6),   # -25    6 %
        (-200,  2),   # -200   2 %
    ]

    # Выбираем дельту по весам
    import random as _random
    raw_delta = _random.choices(
        [d for d, _ in TIERS],
        weights=[w for _, w in TIERS],
        k=1,
    )[0]

    # Определяем фразу и знак
    if raw_delta > 0:
        if raw_delta >= 500:
            phrase = "ДЖЕКПОТ! Сперма с тебя прёт фонтаном"
        else:
            phrase = secrets.choice(config.POSITIVE_PHRASES)
        sign = "✅"
        delta_str = f"+{raw_delta}"
    else:
        if raw_delta <= -200:
            phrase = "КАПУТ! Полный слив балона!"
        else:
            phrase = secrets.choice(config.NEGATIVE_PHRASES)
        sign = "❌"
        delta_str = f"{raw_delta}"

    # Обновляем БД (пола больше нет).
    await asyncio.to_thread(
        database.update_user_sperm, user_id, username or "", raw_delta,
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
    - ``<тег>`` → медиа со спойлером напрямую (без кнопки верификации).
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
    tag_display = tag or "random"
    logger.info("[u:%s] inline query: тег='%s'", creator_id, tag)
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
        title=f"🔞 Подрочить на {config.get_tag_label(tag_display)}",
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


async def _get_user_achievements(user_id: int) -> list[str]:
    """Возвращает список смешных достижений на основе топ-3 тегов пользователя."""
    fav_tags = await asyncio.to_thread(database.get_user_favorite_tags, user_id, 3)
    achievements = []
    for ft in fav_tags:
        title = config.TAG_ACHIEVEMENTS.get(ft["tag"])
        if title:
            achievements.append(title)
    return achievements


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
        display_name = f"@{u['username']}" if u["username"] else f"User #{u['user_id']}"
        sperm = u["total_sperm"]
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")

        # Достижения (топ-3 тега → смешные названия)
        achievements = await _get_user_achievements(u["user_id"])
        ach_part = " | " + " | ".join(achievements) if achievements else ""

        lines.append(
            f'{medal} <a href="tg://user?id={u["user_id"]}"><b>{display_name}</b></a> — {sperm} мл{ach_part}'
        )
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


# ─────────────────── Callback: верификация 18+ → контент под спойлером ─────────


@dp.callback_query(F.data.startswith("verify_18:"))
async def handle_verify_callback(callback: CallbackQuery) -> None:
    """
    Обрабатывает нажатие «Мне есть 18 лет ✅».

    Удаляет текст-заглушку и отправляет новое сообщение с медиа
    под спойлером. Новое сообщение создаётся сразу как медиа с
    ``has_spoiler=True`` — так спойлер работает надёжнее, чем
    при редактировании текста → медиа.
    """
    payload = callback.data.removeprefix("verify_18:")
    try:
        creator_id_str, tag_str = payload.split(":", 1)
        creator_id = int(creator_id_str)
    except (ValueError, IndexError):
        await callback.answer("Ошибка данных", show_alert=True)
        return

    clicker_id = callback.from_user.id
    if clicker_id != creator_id:
        await callback.answer(
            "Это сообщение создал другой пользователь. "
            "Введи @username бота сам!",
            show_alert=True,
        )
        return

    tag: str | None = tag_str if tag_str != "random" else None
    tag_display = tag or "random"

    await callback.answer()

    stats_line = await _generate_stats(creator_id, callback.from_user.username)
    media_url, media_type, display_tag = await fetch_nsfw_content(tag)
    await asyncio.to_thread(database.increment_tag_count, creator_id, display_tag)
    caption = f"<b>NSFW Anime</b>\nТег: {display_tag}\n{stats_line}"
    markup = build_markup(tag, creator_id)

    # ── Инлайн-путь: сообщение из инлайн-режима (callback.inline_message_id) ──
    # Нельзя отправить новое сообщение — нет chat_id. Редактируем через
    # edit_message_media с has_spoiler (иногда не применяется, но выбора нет).
    if callback.inline_message_id:
        try:
            if media_url.lower().endswith(".gif"):
                await bot.edit_message_media(
                    inline_message_id=callback.inline_message_id,
                    media=InputMediaVideo(
                        media=media_url,
                        caption=caption,
                        parse_mode="HTML",
                        has_spoiler=True,
                        supports_streaming=True,
                    ),
                    reply_markup=markup,
                )
            else:
                await bot.edit_message_media(
                    inline_message_id=callback.inline_message_id,
                    media=InputMediaPhoto(
                        media=media_url,
                        caption=caption,
                        parse_mode="HTML",
                        has_spoiler=True,
                    ),
                    reply_markup=markup,
                )
        except Exception as exc:
            logger.warning(
                "[u:%s] verify inline edit failed (type=%s): %s → cat fallback",
                creator_id, media_type, exc,
            )
            try:
                await bot.edit_message_media(
                    inline_message_id=callback.inline_message_id,
                    media=InputMediaPhoto(
                        media=config.FALLBACK_IMAGE_URL,
                        caption=(
                            f"<b>NSFW Anime</b> (фолбэк)\n"
                            f"Тег: {display_tag}\n"
                            f"{stats_line}"
                        ),
                        parse_mode="HTML",
                        has_spoiler=True,
                    ),
                    reply_markup=markup,
                )
            except Exception:
                logger.exception("[u:%s] verify: inline fallback also failed", creator_id)

    # ── Прямое сообщение: удаляем текст-заглушку и шлём новое медиа ──
    # (гарантирует has_spoiler от рождения).
    else:
        try:
            await callback.message.delete()
        except Exception:
            pass  # если не выйдет удалить — не страшно

        try:
            if media_url.lower().endswith(".gif"):
                await bot.send_animation(
                    chat_id=callback.message.chat.id,
                    animation=media_url,
                    caption=caption,
                    parse_mode="HTML",
                    has_spoiler=True,
                    reply_markup=markup,
                )
            else:
                await bot.send_photo(
                    chat_id=callback.message.chat.id,
                    photo=media_url,
                    caption=caption,
                    parse_mode="HTML",
                    has_spoiler=True,
                    reply_markup=markup,
                )
        except Exception as exc:
            logger.warning(
                "[u:%s] verify send failed (type=%s): %s → cat fallback",
                creator_id, media_type, exc,
            )
            try:
                await bot.send_photo(
                    chat_id=callback.message.chat.id,
                    photo=config.FALLBACK_IMAGE_URL,
                    caption=(
                        f"<b>NSFW Anime</b> (фолбэк)\n"
                        f"Тег: {display_tag}\n"
                        f"{stats_line}"
                    ),
                    parse_mode="HTML",
                    has_spoiler=True,
                    reply_markup=markup,
                )
            except Exception:
                logger.exception("[u:%s] verify: fallback also failed", creator_id)


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
        logger.warning("[u:%s] more: invalid callback_data: %s", callback.from_user.id, callback.data)
        await callback.answer("Ошибка данных", show_alert=True)
        return

    tag: str | None = tag_str if tag_str != "random" else None

    # ── Проверка владельца ────────────────────────────────
    clicker_id = callback.from_user.id
    if clicker_id != creator_id:
        logger.info(
            "[u:%s] more: чужой (owner=%s)", clicker_id, creator_id,
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
        logger.debug("[u:%s] more: cooldown %ds remaining", clicker_id, remaining)
        await callback.answer(
            f"⏳ Подожди {remaining} с перед следующим нажатием.",
            show_alert=True,
        )
        return

    _cooldowns[clicker_id] = now

    t0 = time.monotonic()
    logger.info(
        "[u:%s] more: тег='%s'",
        clicker_id, tag,
    )

    stats_line = await _generate_stats(clicker_id, callback.from_user.username)

    media_url, media_type, display_tag = await fetch_nsfw_content(tag)
    fetch_elapsed = time.monotonic() - t0
    logger.info(
        "[u:%s] more content: тег='%s' → type=%s fetch=%.2fs",
        clicker_id, tag, media_type, fetch_elapsed,
    )
    # Трекинг реального тега (не "random") в БД
    await asyncio.to_thread(database.increment_tag_count, clicker_id, display_tag)
    caption = f"<b>NSFW Anime</b>\nТег: {display_tag}\n{stats_line}"
    media_obj = _build_media(media_url, media_type, caption)

    try:
        await _edit_message(callback, media_obj, build_markup(tag, creator_id))
        await callback.answer()
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            logger.debug("[u:%s] more: content unchanged", clicker_id)
            await callback.answer()
            return
        logger.warning(
            "[u:%s] more edit failed (type=%s): %s → cat fallback",
            clicker_id, media_type, exc,
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
        logger.error(
            "[u:%s] more: unexpected error: %s: %s",
            clicker_id, type(exc).__name__, exc,
        )
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
        + "\n".join(
            f"• <code>{t}</code>{'  (' + config.TAG_LABELS[t] + ')' if t in config.TAG_LABELS else ''}"
            for t in sorted(config.VALID_TAGS)
        )
        + "\n\n"
        "Просто напиши <code>@Waifulinuxbot &lt;тег&gt;</code> в любом чате."
    )
    await message.answer(tags_text)
