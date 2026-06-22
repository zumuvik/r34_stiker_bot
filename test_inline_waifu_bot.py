"""
Тесты для inline_waifu_bot.py

Запуск:
    cd /home/zumuvik/project/r34_stiker_bot
    .venv/bin/pytest test_inline_waifu_bot.py -v
"""

import os

# Токен обязан быть установлен ДО импорта модуля, иначе sys.exit(1).
os.environ["BOT_TOKEN"] = "123456:test_fake_token_abc"

import asyncio
import sqlite3
import time
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputMediaPhoto,
    InputMediaVideo,
    InputTextMessageContent,
    Message,
)

import inline_waifu_bot as bot

# ─────────────────────────────────────────────────
#  Helper — мок aiohttp.ClientSession
# ─────────────────────────────────────────────────


@contextmanager
def _mock_aiohttp_get(status=200, json_data=None, text_data=""):
    """
    Контекстный менеджер, подменяющий aiohttp.ClientSession
    и возвращающий контролируемый ответ.

    Используется во всех тестах fetch_nsfw_image и хэндлеров.
    """
    mock_resp = AsyncMock(spec=aiohttp.ClientResponse)
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data or {})
    mock_resp.text = AsyncMock(return_value=text_data)

    # session.get(...) → async context manager → response
    get_cm = MagicMock()
    get_cm.__aenter__.return_value = mock_resp
    get_cm.__aexit__.return_value = None

    # ClientSession() → async context manager → session
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None
    mock_session.get.return_value = get_cm

    with patch("aiohttp.ClientSession", return_value=mock_session):
        yield mock_resp, mock_session


# ─────────────────────────────────────────────────
#  validate_tag
# ─────────────────────────────────────────────────


class TestValidateTag:
    def test_all_valid_tags(self):
        for tag in bot.VALID_TAGS:
            assert bot.validate_tag(tag) == tag, f"tag={tag!r}"

    def test_case_insensitive(self):
        assert bot.validate_tag("Maid") == "maid"
        assert bot.validate_tag("ERO") == "ero"
        assert bot.validate_tag("Hentai") == "hentai"

    def test_whitespace_stripped(self):
        assert bot.validate_tag("   maid   ") == "maid"

    def test_unknown_tag_returns_none(self):
        assert bot.validate_tag("nonexistent") is None

    def test_empty_string_returns_none(self):
        assert bot.validate_tag("") is None
        assert bot.validate_tag("   ") is None

    def test_not_strip_inside(self):
        """Внутренние пробелы не убираются (теги не содержат пробелов)."""
        assert bot.validate_tag("ma id") is None  # space inside → not a valid tag


# ─────────────────────────────────────────────────
#  build_markup
# ─────────────────────────────────────────────────


class TestBuildMarkup:
    def test_with_tag(self):
        markup = bot.build_markup("maid", owner_id=12345)
        assert isinstance(markup, InlineKeyboardMarkup)
        btn = markup.inline_keyboard[0][0]
        assert btn.text == "🔥 Давай ещё!"
        assert btn.callback_data == "more:12345:maid"

    def test_without_tag(self):
        markup = bot.build_markup(None, owner_id=999)
        btn = markup.inline_keyboard[0][0]
        assert btn.callback_data == "more:999:random"

    def test_several_tags(self):
        for tag in ("ero", "hentai", "waifu"):
            btn = bot.build_markup(tag, owner_id=42).inline_keyboard[0][0]
            assert btn.callback_data == f"more:42:{tag}"

    def test_returns_new_markup_each_call(self):
        m1 = bot.build_markup("maid", owner_id=1)
        m2 = bot.build_markup("maid", owner_id=1)
        assert m1 is not m2


# ─────────────────────────────────────────────────
#  fetch_nsfw_content
# ─────────────────────────────────────────────────

# Типовые ответы Purrbot для тестов
_PURRBOT_GIF_JSON = {
    "link": "https://cdn.purrbot.site/nsfw/neko/gif/neko_031.gif",
    "error": False,
    "response-code": 200,
}

_PURRBOT_ERROR_JSON = {
    "error": True,
    "response-code": 403,
    "message": "Not found",
}

_PURRBOT_NO_LINK_JSON = {
    "error": False,
    "response-code": 200,
}


class TestFetchNsfwContent:
    """Все сценарии работы fetch_nsfw_content: Waifu.im и Reddit."""

    FALLBACK = bot.FALLBACK_IMAGE_URL
    PHOTO_URL = "https://cdn.waifu.im/test_123.jpg"
    PHOTO_JSON = {
        "items": [{
            "url": PHOTO_URL,
            "tags": [{"slug": "waifu", "name": "Waifu"}],
        }],
    }
    EMPTY_JSON = {"items": []}

    # ── Photo: Waifu.im (успех) ──────────────────────────────

    @pytest.mark.asyncio
    async def test_photo_with_tag(self):
        with _mock_aiohttp_get(json_data=self.PHOTO_JSON) as (resp, session):
            url, mtype, _display = await bot.fetch_nsfw_content("maid")

        assert url == self.PHOTO_URL
        assert mtype == "photo"
        session.get.assert_called_once_with(
            bot.WAIFU_API_URL,
            params={"IsNsfw": "True", "IncludedTags": "maid"},
        )

    @pytest.mark.asyncio
    async def test_photo_no_tag_passes_only_is_nsfw(self):
        """При tag=None и выборе фото — только IsNsfw."""
        with patch("secrets.randbelow", return_value=0):
            with _mock_aiohttp_get(json_data=self.PHOTO_JSON) as (resp, session):
                url, mtype, _display = await bot.fetch_nsfw_content(None)

        assert url == self.PHOTO_URL
        assert mtype == "photo"
        session.get.assert_called_once_with(
            bot.WAIFU_API_URL,
            params={"IsNsfw": "True"},
        )

    # ── Video: Purrbot (успех) ─────────────────────────────

    @pytest.mark.asyncio
    async def test_video_with_gif_tag(self):
        """Тег neko_gif → Purrbot API."""
        with _mock_aiohttp_get(json_data=_PURRBOT_GIF_JSON) as (resp, session):
            url, mtype, _display = await bot.fetch_nsfw_content("neko_gif")

        assert url == "https://cdn.purrbot.site/nsfw/neko/gif/neko_031.gif"
        assert mtype == "video"

    @pytest.mark.asyncio
    async def test_video_random_picks_purrbot(self):
        """При tag=None и выборе GIF — идём в Purrbot."""
        with patch("secrets.randbelow", return_value=1):
            with patch(
                "secrets.choice", return_value="v2/img/nsfw/neko/gif"
            ):
                with _mock_aiohttp_get(
                    json_data=_PURRBOT_GIF_JSON
                ) as (resp, session):
                    url, mtype, _display = await bot.fetch_nsfw_content(None)

        assert mtype == "video"

    # ── HTTP-ошибки (фото) ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_photo_non_200(self):
        with _mock_aiohttp_get(status=500, text_data="Error"):
            url, mtype, _display = await bot.fetch_nsfw_content("waifu")

        assert url == self.FALLBACK
        assert mtype == "photo"

    @pytest.mark.asyncio
    async def test_photo_empty_list(self):
        with _mock_aiohttp_get(json_data=self.EMPTY_JSON):
            url, mtype, _display = await bot.fetch_nsfw_content("maid")

        assert url == self.FALLBACK
        assert mtype == "photo"

    # ── HTTP-ошибки (GIF) → фоллбэк на фото ─────────────────

    @pytest.mark.asyncio
    async def test_video_purrbot_500_falls_back_to_photo(self):
        with _mock_aiohttp_get(status=500, text_data="Server Error"):
            url, mtype, _display = await bot.fetch_nsfw_content("neko_gif")

        assert url == self.FALLBACK
        assert mtype == "photo"

    @pytest.mark.asyncio
    async def test_video_purrbot_error_falls_back_to_photo(self):
        with _mock_aiohttp_get(json_data=_PURRBOT_ERROR_JSON):
            url, mtype, _display = await bot.fetch_nsfw_content("neko_gif")

        assert url == self.FALLBACK
        assert mtype == "photo"

    @pytest.mark.asyncio
    async def test_video_purrbot_no_link_falls_back_to_photo(self):
        with _mock_aiohttp_get(json_data=_PURRBOT_NO_LINK_JSON):
            url, mtype, _display = await bot.fetch_nsfw_content("nsfw_gif")

        assert url == self.FALLBACK
        assert mtype == "photo"

    # ── Сетевые ошибки (фото) ────────────────────────────────

    @pytest.mark.asyncio
    async def test_photo_timeout(self):
        with _mock_aiohttp_get() as (resp, session):
            resp.json.side_effect = asyncio.TimeoutError
            url, mtype, _display = await bot.fetch_nsfw_content("maid")

        assert url == self.FALLBACK
        assert mtype == "photo"

    @pytest.mark.asyncio
    async def test_photo_client_error(self):
        with _mock_aiohttp_get() as (resp, session):
            resp.json.side_effect = aiohttp.ClientError("reset")
            url, mtype, _display = await bot.fetch_nsfw_content("maid")

        assert url == self.FALLBACK
        assert mtype == "photo"

    # ── Кривые данные ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_photo_malformed_json(self):
        with _mock_aiohttp_get(json_data=["not", "a", "dict"]):
            url, mtype, _display = await bot.fetch_nsfw_content("waifu")

        assert url == self.FALLBACK
        assert mtype == "photo"

    @pytest.mark.asyncio
    async def test_photo_missing_url_key(self):
        with _mock_aiohttp_get(json_data={"items": [{"id": 1}]}):
            url, mtype, _display = await bot.fetch_nsfw_content("waifu")

        assert url == self.FALLBACK
        assert mtype == "photo"


# ─────────────────────────────────────────────────
#  handle_inline_query
# ─────────────────────────────────────────────────


class TestHandleInlineQuery:
    """Проверяет Article + текст-заглушка + кнопка верификации в том же чате."""

    def _make_query(self, text: str) -> AsyncMock:
        query = AsyncMock(spec=InlineQuery)
        query.query = text
        query.from_user = MagicMock()
        query.from_user.id = 12345
        query.answer = AsyncMock(return_value=None)
        return query

    # ── Тип результата ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_returns_article(self):
        """Возвращается InlineQueryResultArticle — без NSFW-превью."""
        query = self._make_query("maid")
        await bot.handle_inline_query(query)

        query.answer.assert_awaited_once()
        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert isinstance(result, InlineQueryResultArticle)

    # ── Заголовок и описание ────────────────────────────────

    @pytest.mark.asyncio
    async def test_title_contains_tag(self):
        query = self._make_query("maid")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert "maid" in result.title
        assert "Подрочить" in result.title

    @pytest.mark.asyncio
    async def test_title_shows_leaderboard_when_no_query(self):
        """Пустой запрос → лидерборд (не verify-article)."""
        query = self._make_query("")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert "ТОП-10" in result.title
        assert "ШПЕРМАПРИЕМНИКОВ" in result.title

    @pytest.mark.asyncio
    async def test_title_shows_random_when_invalid_tag(self):
        query = self._make_query("unknown")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert "random" in result.title

    @pytest.mark.asyncio
    async def test_description(self):
        query = self._make_query("maid")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert "18+" in result.description

    # ── input_message_content ───────────────────────────────

    @pytest.mark.asyncio
    async def test_input_message_content_is_text(self):
        """Текст-заглушка, не команда."""
        query = self._make_query("maid")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert isinstance(result.input_message_content, InputTextMessageContent)
        assert "18+" in result.input_message_content.message_text
        assert "maid" in result.input_message_content.message_text

    @pytest.mark.asyncio
    async def test_input_message_content_leaderboard_when_no_query(self):
        """Пустой запрос → контент лидерборда (не verify-заглушка)."""
        query = self._make_query("")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        text = result.input_message_content.message_text
        assert "ТОП-10" in text
        assert "статистика" not in text  # статистика отдельно, не в топе

    # ── Reply markup (кнопка верификации) ───────────────────

    @pytest.mark.asyncio
    async def test_has_verify_button(self):
        """К статье прикреплена кнопка «Мне есть 18 лет ✅»."""
        query = self._make_query("maid")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert result.reply_markup is not None
        btn = result.reply_markup.inline_keyboard[0][0]
        assert "18" in btn.text
        assert "✅" in btn.text

    @pytest.mark.asyncio
    async def test_verify_callback_contains_creator_id(self):
        """В callback_data зашит ID создателя инлайн-запроса."""
        query = self._make_query("maid")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        btn = result.reply_markup.inline_keyboard[0][0]
        assert ":12345:" in btn.callback_data

    @pytest.mark.asyncio
    async def test_verify_callback_contains_tag(self):
        query = self._make_query("maid")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        btn = result.reply_markup.inline_keyboard[0][0]
        assert btn.callback_data == "verify_18:12345:maid"

    @pytest.mark.asyncio
    async def test_leaderboard_has_no_verify_button_when_no_query(self):
        """Пустой запрос → лидерборд без кнопки верификации."""
        query = self._make_query("")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert result.reply_markup is None

    @pytest.mark.asyncio
    async def test_verify_callback_random_when_invalid_tag(self):
        query = self._make_query("unknown")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        btn = result.reply_markup.inline_keyboard[0][0]
        assert btn.callback_data == "verify_18:12345:random"

    # ── Нет фото-полей ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_no_photo_preview_fields(self):
        query = self._make_query("maid")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert not hasattr(result, "photo_url")

    # ── Параметры query.answer ─────────────────────────────

    @pytest.mark.asyncio
    async def test_cache_time_is_zero(self):
        query = self._make_query("ero")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        assert kwargs["cache_time"] == 0

    @pytest.mark.asyncio
    async def test_is_personal(self):
        query = self._make_query("maid")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        assert kwargs["is_personal"] is True

    @pytest.mark.asyncio
    async def test_single_result(self):
        query = self._make_query("maid")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        assert len(kwargs["results"]) == 1

    @pytest.mark.asyncio
    async def test_no_switch_pm(self):
        """Кнопка «список тегов» удалена."""
        query = self._make_query("maid")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        assert "switch_pm_text" not in kwargs





# ─────────────────────────────────────────────────
#  handle_verify_callback
# ─────────────────────────────────────────────────


class TestHandleVerifyCallback:
    """Проверяет логику кнопки «Мне есть 18 лет ✅»."""

    SUCCESS_URL = "https://cdn.waifu.im/verify_test.jpg"
    SUCCESS_JSON = {"items": [{"url": SUCCESS_URL, "tags": [{"slug": "waifu"}]}]}
    CREATOR_ID = 12345
    STRANGER_ID = 99999

    @pytest.fixture(autouse=True)
    def _patch_db(self):
        """update_user_sperm возвращает int (не MagicMock)."""
        with (
            patch(
                "inline_waifu_bot.handlers.database.update_user_sperm",
                side_effect=lambda _uid, _uname, delta: delta,
            ),
            patch("inline_waifu_bot.handlers.database.increment_tag_count"),
        ):
            yield

    @pytest.fixture
    def mock_bot_edit(self):
        """Патч bot.edit_message_media для тестов инлайн-пути."""
        with patch.object(bot.bot, "edit_message_media", AsyncMock(return_value=None)) as m:
            yield m

    def _make_callback(
        self, tag: str | None, *, has_message: bool = False,
        clicker_id: int | None = None,
    ) -> AsyncMock:
        """Создаёт мок CallbackQuery с verify_18: callback_data."""
        tag_part = tag if tag else "random"
        callback_data = f"verify_18:{self.CREATOR_ID}:{tag_part}"

        callback = AsyncMock(spec=CallbackQuery)
        callback.data = callback_data
        clicker_id = clicker_id or self.CREATOR_ID
        callback.from_user = MagicMock()
        callback.from_user.id = clicker_id
        callback.inline_message_id = "AQAAABBBCCCDDD" if not has_message else None
        callback.message = None if not has_message else MagicMock(spec=Message)
        if has_message:
            callback.message.edit_media = AsyncMock(return_value=None)
        callback.answer = AsyncMock(return_value=None)
        return callback

    # ── Парсинг тега ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_parses_tag_from_callback_data(self, mock_bot_edit):
        """Тег из callback_data уходит в API."""
        callback = self._make_callback("maid")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON) as (resp, session):
            await bot.handle_verify_callback(callback)

        session.get.assert_called_once_with(
            bot.WAIFU_API_URL,
            params={"IsNsfw": "True", "IncludedTags": "maid"},
        )

    @pytest.mark.asyncio
    async def test_random_tag_passes_no_tag_to_api(self, mock_bot_edit):
        """random → запрос без тега (Waifu.im)."""
        callback = self._make_callback(None)

        with patch("inline_waifu_bot.api.secrets.randbelow", return_value=0):
            with _mock_aiohttp_get(json_data=self.SUCCESS_JSON) as (resp, session):
                await bot.handle_verify_callback(callback)

        session.get.assert_called_once_with(
            bot.WAIFU_API_URL,
            params={"IsNsfw": "True"},
        )

    @pytest.mark.asyncio
    async def test_invalid_callback_data_answered_with_alert(self, mock_bot_edit):
        """Мусор в callback_data — ответ с ошибкой."""
        callback = self._make_callback("maid")
        callback.data = "garbage_data"

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_verify_callback(callback)

        callback.answer.assert_awaited_once_with(
            "Ошибка данных", show_alert=True,
        )
        mock_bot_edit.assert_not_called()

    # ── Проверка создателя ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_stranger_cannot_verify(self, mock_bot_edit):
        """Чужой получает alert и отказ."""
        callback = self._make_callback("maid", clicker_id=self.STRANGER_ID)

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_verify_callback(callback)

        callback.answer.assert_awaited_once_with(
            "Это сообщение создал другой пользователь. "
            "Введи @username бота сам!",
            show_alert=True,
        )
        mock_bot_edit.assert_not_called()

    @pytest.mark.asyncio
    async def test_creator_can_verify(self, mock_bot_edit):
        """Создатель может подтвердить 18+ и получить фото."""
        callback = self._make_callback("ero")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_verify_callback(callback)

        mock_bot_edit.assert_awaited_once()

    # ── inline_message_id path ──────────────────────────────

    @pytest.mark.asyncio
    async def test_edit_via_bot_with_inline_message_id(self, mock_bot_edit):
        callback = self._make_callback("ero")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_verify_callback(callback)

        _args, kwargs = mock_bot_edit.call_args
        assert kwargs["inline_message_id"] == "AQAAABBBCCCDDD"
        assert isinstance(kwargs["media"], InputMediaPhoto)
        assert kwargs["media"].has_spoiler is True
        assert kwargs["reply_markup"].inline_keyboard[0][
            0].callback_data == f"more:{self.CREATOR_ID}:ero"

    # ── callback.message path ───────────────────────────────

    @pytest.mark.asyncio
    async def test_edit_via_message_when_no_inline_id(self):
        callback = self._make_callback("maid", has_message=True)

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_verify_callback(callback)

        callback.message.edit_media.assert_awaited_once()
        _args, kwargs = callback.message.edit_media.call_args
        assert isinstance(kwargs["media"], InputMediaPhoto)
        assert kwargs["media"].has_spoiler is True
        assert kwargs["reply_markup"].inline_keyboard[0][
            0].callback_data == f"more:{self.CREATOR_ID}:maid"

    # ── Video / GIF path ──────────────────────────────────

    def _make_video_callback(
        self, tag: str, *, has_message: bool = False,
        clicker_id: int | None = None,
    ) -> AsyncMock:
        """Создаёт мок с GIF-тегом."""
        tag_part = tag
        callback_data = f"verify_18:{self.CREATOR_ID}:{tag_part}"
        callback = AsyncMock(spec=CallbackQuery)
        callback.data = callback_data
        clicker_id = clicker_id or self.CREATOR_ID
        callback.from_user = MagicMock()
        callback.from_user.id = clicker_id
        callback.inline_message_id = "AQAAABBBCCCDDD" if not has_message else None
        callback.message = None if not has_message else MagicMock(spec=Message)
        if has_message:
            callback.message.edit_media = AsyncMock(return_value=None)
        callback.answer = AsyncMock(return_value=None)
        return callback

    @pytest.mark.asyncio
    async def test_video_uses_InputMediaVideo(self, mock_bot_edit):
        """GIF-тег → InputMediaVideo."""
        callback = self._make_video_callback("neko_gif")

        with _mock_aiohttp_get(json_data=_PURRBOT_GIF_JSON):
            await bot.handle_verify_callback(callback)

        _args, kwargs = mock_bot_edit.call_args
        assert isinstance(kwargs["media"], InputMediaVideo)
        assert kwargs["media"].has_spoiler is True

    @pytest.mark.asyncio
    async def test_video_edit_failure_falls_back_to_photo(self, mock_bot_edit):
        """TelegramBadRequest на GIF → фоллбэк на фото с котом."""
        callback = self._make_video_callback("neko_gif")
        mock_bot_edit.side_effect = [
            TelegramBadRequest(method="edit_message_media", message="wrong type"),
            None,  # second call (fallback) succeeds
        ]

        with _mock_aiohttp_get(json_data=_PURRBOT_GIF_JSON):
            await bot.handle_verify_callback(callback)

        # Было два вызова edit_message_media
        assert mock_bot_edit.call_count == 2
        first_call_args = mock_bot_edit.call_args_list[0]
        second_call_args = mock_bot_edit.call_args_list[1]
        # Первый был InputMediaVideo
        assert isinstance(first_call_args.kwargs["media"], InputMediaVideo)
        # Второй — InputMediaPhoto с fallback URL
        assert isinstance(second_call_args.kwargs["media"], InputMediaPhoto)
        assert "http.cat" in second_call_args.kwargs["media"].media


# ─────────────────────────────────────────────────
#  handle_more_callback
# ─────────────────────────────────────────────────


class TestHandleMoreCallback:
    """Проверяем логику кнопки «Давай ещё!»."""

    SUCCESS_URL = "https://cdn.waifu.im/callback_new.jpg"
    SUCCESS_JSON = {"items": [{"url": SUCCESS_URL, "tags": [{"slug": "waifu"}]}]}
    OWNER_ID = 12345
    STRANGER_ID = 99999

    @pytest.fixture(autouse=True)
    def clear_cooldowns(self):
        """Сбрасываем кд перед каждым тестом."""
        bot._cooldowns.clear()

    @pytest.fixture(autouse=True)
    def _patch_db(self):
        """update_user_sperm возвращает int (не MagicMock)."""
        with (
            patch(
                "inline_waifu_bot.handlers.database.update_user_sperm",
                side_effect=lambda _uid, _uname, delta: delta,
            ),
            patch("inline_waifu_bot.handlers.database.increment_tag_count"),
        ):
            yield

    @pytest.fixture
    def mock_bot_edit(self):
        """Патч bot.edit_message_media для тестов инлайн-пути."""
        with patch.object(bot.bot, "edit_message_media", AsyncMock(return_value=None)) as m:
            yield m

    def _make_callback(
        self, tag: str | None, *, has_message: bool = False,
        clicker_id: int | None = None,
    ) -> AsyncMock:
        """Создаёт мок CallbackQuery с корректным callback_data."""
        tag_part = tag if tag else "random"
        callback_data = f"more:{self.OWNER_ID}:{tag_part}"

        callback = AsyncMock(spec=CallbackQuery)
        callback.data = callback_data
        clicker_id = clicker_id or self.OWNER_ID
        callback.from_user = MagicMock()
        callback.from_user.id = clicker_id
        # Сообщения из инлайн-режима идут через inline_message_id,
        # а callback.message приходит None.
        callback.inline_message_id = "AQAAABBBCCCDDD" if not has_message else None
        callback.message = None if not has_message else MagicMock(spec=Message)
        if has_message:
            callback.message.edit_media = AsyncMock(return_value=None)
        callback.answer = AsyncMock(return_value=None)
        return callback

    # -- Разбор callback_data ----------------------------------

    @pytest.mark.asyncio
    async def test_extracts_tag_from_callback_data(self, mock_bot_edit):
        callback = self._make_callback("maid")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON) as (resp, session):
            await bot.handle_more_callback(callback)

        session.get.assert_called_once_with(
            bot.WAIFU_API_URL,
            params={"IsNsfw": "True", "IncludedTags": "maid"},
        )

    @pytest.mark.asyncio
    async def test_random_callback_passes_no_tag(self, mock_bot_edit):
        callback = self._make_callback(None)

        with patch("inline_waifu_bot.api.secrets.randbelow", return_value=0):
            with _mock_aiohttp_get(json_data=self.SUCCESS_JSON) as (resp, session):
                await bot.handle_more_callback(callback)

        session.get.assert_called_once_with(
            bot.WAIFU_API_URL,
            params={"IsNsfw": "True"},
        )

    @pytest.mark.asyncio
    async def test_invalid_callback_data_answered_with_alert(self, mock_bot_edit):
        """Мусор в callback_data — ответ с ошибкой."""
        callback = self._make_callback("maid")
        callback.data = "garbage_data"

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        callback.answer.assert_awaited_once_with(
            "Ошибка данных", show_alert=True,
        )

    # -- Проверка владельца ------------------------------------

    @pytest.mark.asyncio
    async def test_stranger_cannot_use_button(self, mock_bot_edit):
        """Чужой пользователь получает alert и отказ."""
        callback = self._make_callback("maid", clicker_id=self.STRANGER_ID)

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        callback.answer.assert_awaited_once_with(
            "Это сообщение создал другой пользователь. "
            "Введи @username бота сам!",
            show_alert=True,
        )
        mock_bot_edit.assert_not_called()

    @pytest.mark.asyncio
    async def test_owner_can_use_button(self, mock_bot_edit):
        """Владелец может нажать кнопку."""
        callback = self._make_callback("ero")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        mock_bot_edit.assert_awaited_once()

    # -- Кд ----------------------------------------------------

    @pytest.mark.asyncio
    async def test_cooldown_rejects_rapid_clicks(self, mock_bot_edit):
        """Повторное нажатие раньше 3 секунд отклоняется."""
        callback = self._make_callback("maid")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)
        mock_bot_edit.reset_mock()
        callback.answer.reset_mock()

        # Второе нажатие сразу — должно быть отклонено
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        alert_kwargs = [c for c in callback.answer.call_args_list
                        if c.kwargs.get("show_alert")][0]
        assert "Подожди" in alert_kwargs.kwargs.get("text", alert_kwargs.args[0] if alert_kwargs.args else "")
        mock_bot_edit.assert_not_called()

    @pytest.mark.asyncio
    async def test_cooldown_expired_allows_click(self, mock_bot_edit):
        """После истечения кд нажатие снова проходит."""
        callback = self._make_callback("maid")
        # Ставим метку давно
        bot._cooldowns[self.OWNER_ID] = time.time() - 10

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        mock_bot_edit.assert_awaited_once()

    # -- inline_message_id path (бот вызван через инлайн) ------

    @pytest.mark.asyncio
    async def test_edit_via_bot_with_inline_message_id(self, mock_bot_edit):
        callback = self._make_callback("ero")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        mock_bot_edit.assert_awaited_once()
        _args, kwargs = mock_bot_edit.call_args
        assert kwargs["inline_message_id"] == "AQAAABBBCCCDDD"
        assert isinstance(kwargs["media"], InputMediaPhoto)
        assert kwargs["media"].media == self.SUCCESS_URL
        assert kwargs["reply_markup"].inline_keyboard[0][
            0].callback_data == f"more:{self.OWNER_ID}:ero"

    @pytest.mark.asyncio
    async def test_inline_edit_media_contains_InputMediaPhoto(self, mock_bot_edit):
        callback = self._make_callback("ero")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        _args, kwargs = mock_bot_edit.call_args
        assert isinstance(kwargs["media"], InputMediaPhoto)
        assert kwargs["media"].media == self.SUCCESS_URL

    @pytest.mark.asyncio
    async def test_inline_edit_has_reply_markup(self, mock_bot_edit):
        callback = self._make_callback("ero")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        _args, kwargs = mock_bot_edit.call_args
        rm = kwargs["reply_markup"]
        assert rm.inline_keyboard[0][0].callback_data == f"more:{self.OWNER_ID}:ero"

    @pytest.mark.asyncio
    async def test_inline_random_edit_has_random_markup(self, mock_bot_edit):
        callback = self._make_callback(None)

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        _args, kwargs = mock_bot_edit.call_args
        rm = kwargs["reply_markup"]
        assert rm.inline_keyboard[0][0].callback_data == f"more:{self.OWNER_ID}:random"

    @pytest.mark.asyncio
    async def test_inline_caption_contains_tag(self, mock_bot_edit):
        callback = self._make_callback("maid")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        _args, kwargs = mock_bot_edit.call_args
        assert "maid" in kwargs["media"].caption

    @pytest.mark.asyncio
    async def test_inline_caption_contains_real_tag_when_random(self, mock_bot_edit):
        """При random в подписи реальный тег из ответа API, не 'random'."""
        callback = self._make_callback(None)

        with patch("inline_waifu_bot.api.secrets.randbelow", return_value=0):
            with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
                await bot.handle_more_callback(callback)

        _args, kwargs = mock_bot_edit.call_args
        assert "waifu" in kwargs["media"].caption
        assert "random" not in kwargs["media"].caption

    # -- callback.message path (обычное сообщение без inline) ---

    @pytest.mark.asyncio
    async def test_edit_via_message_when_no_inline_id(self):
        callback = self._make_callback("ero", has_message=True)

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        callback.message.edit_media.assert_awaited_once()
        _args, kwargs = callback.message.edit_media.call_args
        assert isinstance(kwargs["media"], InputMediaPhoto)
        assert kwargs["media"].media == self.SUCCESS_URL
        assert kwargs["reply_markup"].inline_keyboard[0][
            0].callback_data == f"more:{self.OWNER_ID}:ero"

    @pytest.mark.asyncio
    async def test_message_edit_caption_contains_tag(self):
        callback = self._make_callback("maid", has_message=True)

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        _args, kwargs = callback.message.edit_media.call_args
        assert "maid" in kwargs["media"].caption

    # -- callback.answer ----------------------------------------

    @pytest.mark.asyncio
    async def test_answer_called_on_success(self, mock_bot_edit):
        callback = self._make_callback("waifu")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        callback.answer.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_answer_with_alert_on_edit_failure(self, mock_bot_edit):
        callback = self._make_callback("waifu")
        mock_bot_edit.side_effect = Exception("edit failed")
        callback.answer = AsyncMock(return_value=None)

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        callback.answer.assert_awaited_once_with(
            "Не удалось обновить картинку. Попробуйте ещё раз.",
            show_alert=True,
        )

    # ── Video / GIF path ──────────────────────────────────

    def _make_more_video_callback(
        self, tag: str, *, has_message: bool = False,
        clicker_id: int | None = None,
    ) -> AsyncMock:
        """Создаёт мок CallbackQuery с GIF-тегом."""
        callback_data = f"more:{self.OWNER_ID}:{tag}"
        callback = AsyncMock(spec=CallbackQuery)
        callback.data = callback_data
        clicker_id = clicker_id or self.OWNER_ID
        callback.from_user = MagicMock()
        callback.from_user.id = clicker_id
        callback.inline_message_id = "AQAAABBBCCCDDD" if not has_message else None
        callback.message = None if not has_message else MagicMock(spec=Message)
        if has_message:
            callback.message.edit_media = AsyncMock(return_value=None)
        callback.answer = AsyncMock(return_value=None)
        return callback

    @pytest.mark.asyncio
    async def test_more_video_uses_InputMediaVideo(self, mock_bot_edit):
        """GIF-тег → InputMediaVideo."""
        callback = self._make_more_video_callback("neko_gif")

        with _mock_aiohttp_get(json_data=_PURRBOT_GIF_JSON):
            await bot.handle_more_callback(callback)

        _args, kwargs = mock_bot_edit.call_args
        assert isinstance(kwargs["media"], InputMediaVideo)
        assert kwargs["media"].has_spoiler is True

    @pytest.mark.asyncio
    async def test_more_video_edit_failure_falls_back_to_photo(self, mock_bot_edit):
        """TelegramBadRequest на GIF → фоллбэк на фото с котом."""
        callback = self._make_more_video_callback("neko_gif")
        mock_bot_edit.side_effect = [
            TelegramBadRequest(method="edit_message_media", message="wrong type"),
            None,
        ]

        with _mock_aiohttp_get(json_data=_PURRBOT_GIF_JSON):
            await bot.handle_more_callback(callback)

        assert mock_bot_edit.call_count == 2
        first_call = mock_bot_edit.call_args_list[0]
        second_call = mock_bot_edit.call_args_list[1]
        assert isinstance(first_call.kwargs["media"], InputMediaVideo)
        assert isinstance(second_call.kwargs["media"], InputMediaPhoto)
        assert "http.cat" in second_call.kwargs["media"].media


# ─────────────────────────────────────────────────
#  Конфигурация модуля
# ─────────────────────────────────────────────────


class TestModuleConfig:
    """Проверяем, что константы инициализированы корректно."""

    def test_bot_token_loaded(self):
        assert bot.BOT_TOKEN == "123456:test_fake_token_abc"

    def test_valid_tags_non_empty(self):
        assert len(bot.VALID_TAGS) > 0
        assert "maid" in bot.VALID_TAGS
        assert "ero" in bot.VALID_TAGS

    def test_fallback_url_is_plain_url(self):
        """Проверяем, что баг со склейкой с docstring исправлен."""
        url = bot.FALLBACK_IMAGE_URL
        assert url.startswith("https://")
        assert "\n" not in url, "FALLBACK_IMAGE_URL содержит перевод строки (баг склейки!)"

    def test_api_timeout_is_int(self):
        assert isinstance(bot.API_TIMEOUT_SECONDS, int)
        assert bot.API_TIMEOUT_SECONDS == 5

    def test_waifu_api_url(self):
        assert bot.WAIFU_API_URL == "https://api.waifu.im/images"

    # ── Новые конфиги (фото/видео теги) ─────────────────────

    def test_photo_tags_are_subset_of_valid(self):
        assert bot.PHOTO_TAGS.issubset(bot.VALID_TAGS)

    def test_video_tags_are_subset_of_valid(self):
        assert bot.VIDEO_TAGS.issubset(bot.VALID_TAGS)

    def test_photo_and_video_tags_are_disjoint(self):
        assert bot.PHOTO_TAGS.isdisjoint(bot.VIDEO_TAGS)

    def test_is_video_tag_returns_true_for_video_tags(self):
        assert bot.is_video_tag("neko_gif") is True
        assert bot.is_video_tag("nsfw_gif") is True

    def test_is_video_tag_returns_false_for_photo_tags(self):
        assert bot.is_video_tag("waifu") is False

    def test_is_video_tag_returns_false_for_none(self):
        assert bot.is_video_tag(None) is False

    def test_is_photo_tag_returns_true_for_photo_tags(self):
        assert bot.is_photo_tag("maid") is True
        assert bot.is_photo_tag("ero") is True

    def test_is_photo_tag_returns_false_for_video_tags(self):
        assert bot.is_photo_tag("neko_gif") is False

    def test_is_photo_tag_returns_false_for_none(self):
        assert bot.is_photo_tag(None) is False

    def test_get_video_endpoint_known_tag(self):
        expected = bot.VIDEO_ENDPOINTS["neko_gif"]
        assert bot.get_video_endpoint("neko_gif") == expected

    def test_get_video_endpoint_unknown_tag_returns_tag_itself(self):
        assert bot.get_video_endpoint("unknown") == "unknown"

    # ── femboy / furry ─────────────────────────────────────

    def test_femboy_tag_is_valid(self):
        assert "femboy" in bot.VALID_TAGS

    def test_furry_tag_is_valid(self):
        assert "furry" in bot.VALID_TAGS

    def test_femboy_not_in_photo_tags(self):
        """femboy не в PHOTO_TAGS → не попадает в random."""
        assert "femboy" not in bot.PHOTO_TAGS

    def test_furry_not_in_photo_tags(self):
        """furry не в PHOTO_TAGS → не попадает в random."""
        assert "furry" not in bot.PHOTO_TAGS

    def test_femboy_not_in_video_tags(self):
        assert "femboy" not in bot.VIDEO_TAGS

    def test_furry_not_in_video_tags(self):
        assert "furry" not in bot.VIDEO_TAGS

    def test_is_femboy_tag(self):
        assert bot.is_femboy_tag("femboy") is True
        assert bot.is_femboy_tag("maid") is False
        assert bot.is_femboy_tag(None) is False

    def test_is_furry_tag(self):
        assert bot.is_furry_tag("furry") is True
        assert bot.is_furry_tag("neko_gif") is False
        assert bot.is_furry_tag(None) is False


# ─────────────────────────────────────────────────
#  Database: init_db, update_user_sperm, get_leaderboard
# ─────────────────────────────────────────────────


class TestDatabase:
    """Проверяет SQLite-слой: инициализацию, обновление/чтение статистики.

    Использует in-memory SQLite (не затрагивает bot_stats.db на диске).
    """

    @pytest.fixture(autouse=True)
    def _in_memory_db(self):
        """Подменяем database.get_connection на in-memory БД для каждого теста."""
        import inline_waifu_bot.database as db_mod

        orig_db_conn = db_mod.get_connection   # database.get_connection
        orig_bot_conn = bot.get_connection      # inline_waifu_bot.get_connection (экспорт)
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        db_mod.get_connection = lambda: conn
        bot.get_connection = lambda: conn       # тоже патчим, т.к. это копия ссылки
        db_mod.init_db()                        # создаёт таблицы в :memory:
        yield
        db_mod.get_connection = orig_db_conn
        bot.get_connection = orig_bot_conn
        conn.close()

    def test_init_db_creates_table(self):
        """После init_db таблица существует."""
        conn = bot.get_connection()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'",
        ).fetchall()
        assert any(r["name"] == "user_stats" for r in tables)

    def test_update_new_user_inserts_row(self):
        """Первый вызов update_user_sperm создаёт запись."""
        bot.update_user_sperm(123, "test_user", 10)
        conn = bot.get_connection()
        row = conn.execute(
            "SELECT * FROM user_stats WHERE user_id=?", (123,),
        ).fetchone()
        assert row is not None
        assert row["username"] == "test_user"
        assert row["total_sperm"] == 10

    def test_update_existing_user_accumulates(self):
        """Последующие вызовы накапливают total_sperm."""
        bot.update_user_sperm(123, "test_user", 10)
        bot.update_user_sperm(123, "test_user", -3)
        conn = bot.get_connection()
        row = conn.execute(
            "SELECT total_sperm FROM user_stats WHERE user_id=?", (123,),
        ).fetchone()
        assert row["total_sperm"] == 7

    def test_update_refreshes_username(self):
        """username обновляется при повторном вызове."""
        bot.update_user_sperm(123, "old_name", 10)
        bot.update_user_sperm(123, "new_name", 5)
        conn = bot.get_connection()
        row = conn.execute(
            "SELECT username FROM user_stats WHERE user_id=?", (123,),
        ).fetchone()
        assert row["username"] == "new_name"

    def test_get_leaderboard_empty(self):
        """Когда нет записей — пустой список."""
        assert bot.get_leaderboard() == []

    def test_get_leaderboard_ordering(self):
        """Топ сортируется по total_sperm DESC."""
        bot.update_user_sperm(1, "alpha", 10)
        bot.update_user_sperm(2, "beta", 30)
        bot.update_user_sperm(3, "gamma", 20)
        top = bot.get_leaderboard(10)
        assert len(top) == 3
        assert top[0]["user_id"] == 2  # beta: 30
        assert top[1]["user_id"] == 3  # gamma: 20
        assert top[2]["user_id"] == 1  # alpha: 10
        assert [u["total_sperm"] for u in top] == [30, 20, 10]

    def test_get_leaderboard_limited(self):
        """Параметр limit работает."""
        for uid in range(1, 6):
            bot.update_user_sperm(uid, f"u{uid}", uid * 10)
        top3 = bot.get_leaderboard(3)
        assert len(top3) == 3
        assert top3[0]["total_sperm"] == 50
        assert top3[-1]["total_sperm"] == 30

    def test_negative_capped_at_zero(self):
        """total_sperm не уходит в минус — пол в нуле."""
        # Сначала +10
        bot.update_user_sperm(1, "unlucky", 10)
        # Потом -25, но в минус уйти нельзя — срезается до 0
        actual = bot.update_user_sperm(1, "unlucky", -25)
        conn = bot.get_connection()
        row = conn.execute(
            "SELECT total_sperm FROM user_stats WHERE user_id=?", (1,),
        ).fetchone()
        assert row["total_sperm"] == 0
        assert actual == -10, f"expected -10, got {actual}"  # 10 → 0, фактически -10


# ─────────────────────────────────────────────────
#  Tag tracking: increment_tag_count, get_user_favorite_tags
# ─────────────────────────────────────────────────


class TestTagTracking:
    """Проверяет таблицу user_tag_stats."""

    @pytest.fixture(autouse=True)
    def _in_memory_db(self):
        """Та же in-memory фикстура, что и в TestDatabase."""
        import inline_waifu_bot.database as db_mod

        orig_db_conn = db_mod.get_connection
        orig_bot_conn = bot.get_connection
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        db_mod.get_connection = lambda: conn
        bot.get_connection = lambda: conn
        db_mod.init_db()
        yield
        db_mod.get_connection = orig_db_conn
        bot.get_connection = orig_bot_conn
        conn.close()

    def test_increment_new_tag(self):
        """Первый вызов создаёт запись с count=1."""
        bot.increment_tag_count(1, "waifu")
        conn = bot.get_connection()
        row = conn.execute(
            "SELECT count FROM user_tag_stats WHERE user_id=? AND tag=?",
            (1, "waifu"),
        ).fetchone()
        assert row["count"] == 1

    def test_increment_existing_tag(self):
        """Повторный вызов увеличивает count."""
        bot.increment_tag_count(1, "maid")
        bot.increment_tag_count(1, "maid")
        conn = bot.get_connection()
        row = conn.execute(
            "SELECT count FROM user_tag_stats WHERE user_id=? AND tag=?",
            (1, "maid"),
        ).fetchone()
        assert row["count"] == 2

    def test_composite_key_different_users(self):
        """Один и тот же тег для разных юзеров — разные строки."""
        bot.increment_tag_count(1, "ero")
        bot.increment_tag_count(2, "ero")
        conn = bot.get_connection()
        rows = conn.execute(
            "SELECT user_id, count FROM user_tag_stats WHERE tag=? ORDER BY user_id",
            ("ero",),
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["count"] == 1
        assert rows[1]["count"] == 1

    def test_composite_key_different_tags(self):
        """Один юзер с разными тегами — разные строки."""
        bot.increment_tag_count(1, "waifu")
        bot.increment_tag_count(1, "maid")
        conn = bot.get_connection()
        rows = conn.execute(
            "SELECT tag, count FROM user_tag_stats WHERE user_id=? ORDER BY tag",
            (1,),
        ).fetchall()
        assert len(rows) == 2

    def test_get_favorite_tags_empty(self):
        """Если тегов нет — пустой список."""
        assert bot.get_user_favorite_tags(999) == []

    def test_get_favorite_tags_ordering(self):
        """Топ сортируется по count DESC."""
        bot.increment_tag_count(1, "a")
        bot.increment_tag_count(1, "b")
        bot.increment_tag_count(1, "b")
        bot.increment_tag_count(1, "c")
        bot.increment_tag_count(1, "c")
        bot.increment_tag_count(1, "c")
        top = bot.get_user_favorite_tags(1)
        assert len(top) == 3
        assert top[0]["tag"] == "c"  # 3 раза
        assert top[1]["tag"] == "b"  # 2 раза
        assert top[2]["tag"] == "a"  # 1 раз

    def test_get_favorite_tags_limit(self):
        """Параметр limit работает."""
        for t in ("a", "b", "c", "d"):
            bot.increment_tag_count(1, t)
        top2 = bot.get_user_favorite_tags(1, limit=2)
        assert len(top2) == 2


# ─────────────────────────────────────────────────
#  Stats line в verify_callback
# ─────────────────────────────────────────────────


class TestStatsInVerifyCallback:
    """Статистика дописывается в caption при верификации."""

    SUCCESS_URL = "https://cdn.waifu.im/verify_stats.jpg"
    SUCCESS_JSON = {
        "items": [{"url": SUCCESS_URL, "tags": [{"slug": "waifu"}]}],
    }
    CREATOR_ID = 12345

    @pytest.fixture
    def mock_bot_edit(self):
        with patch.object(bot.bot, "edit_message_media", AsyncMock()) as m:
            yield m

    def _make_callback(self, tag="maid", *, clicker_id=None):
        tag_part = tag or "random"
        cb = AsyncMock(spec=CallbackQuery)
        cb.data = f"verify_18:{self.CREATOR_ID}:{tag_part}"
        cb.from_user = MagicMock()
        cb.from_user.id = clicker_id or self.CREATOR_ID
        cb.from_user.username = "test_user"
        cb.inline_message_id = "AQAAABBBCCCDDD"
        cb.message = None
        cb.answer = AsyncMock()
        return cb

    @pytest.mark.asyncio
    async def test_caption_includes_stats_line(self, mock_bot_edit):
        """После верификации caption заканчивается строкой статистики."""
        cb = self._make_callback("waifu")
        with (
            patch("inline_waifu_bot.handlers.database.update_user_sperm", return_value=25),
            patch("inline_waifu_bot.handlers.database.increment_tag_count"),
            patch("random.choices", return_value=[25]),
            patch("secrets.choice", return_value="Вы подододрочель"),
        ):
            with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
                await bot.handle_verify_callback(cb)

        _args, kwargs = mock_bot_edit.call_args
        caption = kwargs["media"].caption
        assert "Вы подододрочель" in caption
        assert "✅" in caption
        assert "+25 мл спермы" in caption

    @pytest.mark.asyncio
    async def test_negative_stats_format(self, mock_bot_edit):
        """Отрицательная сперма: ❌ и -N."""
        cb = self._make_callback("ero")
        with (
            patch("inline_waifu_bot.handlers.database.update_user_sperm", return_value=-10),
            patch("inline_waifu_bot.handlers.database.increment_tag_count"),
            patch("random.choices", return_value=[-10]),
            patch("secrets.choice", return_value="У тебя сегодня отсох хуец."),
        ):
            with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
                await bot.handle_verify_callback(cb)

        _args, kwargs = mock_bot_edit.call_args
        caption = kwargs["media"].caption
        assert "У тебя сегодня отсох хуец." in caption
        assert "❌" in caption
        assert "-10 мл спермы" in caption

    @pytest.mark.asyncio
    async def test_delta_calls_db(self, mock_bot_edit):
        """update_user_sperm вызывается с корректными аргументами."""
        cb = self._make_callback("maid")
        with patch("inline_waifu_bot.handlers.database.update_user_sperm", return_value=10) as mock_upd:
            with (
                patch("inline_waifu_bot.handlers.database.increment_tag_count"),
                patch("random.choices", return_value=[10]),
                patch("secrets.choice", return_value="Вы подододрочель"),
            ):
                with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
                    await bot.handle_verify_callback(cb)

        # sync-функция, вызвана через asyncio.to_thread
        mock_upd.assert_called_once_with(12345, "test_user", 10)

    @pytest.mark.asyncio
    async def test_fallback_also_has_stats(self, mock_bot_edit):
        """При фолбэке статистика тоже есть в caption."""
        cb = self._make_callback("neko_gif")
        mock_bot_edit.side_effect = [
            TelegramBadRequest(method="edit_message_media", message="wrong type"),
            None,
        ]
        with (
            patch("inline_waifu_bot.handlers.database.update_user_sperm", return_value=25),
            patch("inline_waifu_bot.handlers.database.increment_tag_count"),
            patch("random.choices", return_value=[25]),
            patch("secrets.choice", return_value="Вы подододрочель"),
        ):
            with _mock_aiohttp_get(json_data=_PURRBOT_GIF_JSON):
                await bot.handle_verify_callback(cb)

        second_call = mock_bot_edit.call_args_list[1]
        caption = second_call.kwargs["media"].caption
        assert "Вы подододрочель" in caption
        assert "✅" in caption
        assert "+25 мл спермы" in caption


# ─────────────────────────────────────────────────
#  Stats line в more_callback
# ─────────────────────────────────────────────────


class TestStatsInMoreCallback:
    """Статистика дописывается в caption при «Давай ещё!»."""

    SUCCESS_URL = "https://cdn.waifu.im/more_stats.jpg"
    SUCCESS_JSON = {
        "items": [{"url": SUCCESS_URL, "tags": [{"slug": "waifu"}]}],
    }
    OWNER_ID = 12345

    @pytest.fixture(autouse=True)
    def clear_cooldowns(self):
        bot._cooldowns.clear()

    @pytest.fixture
    def mock_bot_edit(self):
        with patch.object(bot.bot, "edit_message_media", AsyncMock()) as m:
            yield m

    def _make_callback(self, tag="maid", *, clicker_id=None):
        tag_part = tag or "random"
        cb = AsyncMock(spec=CallbackQuery)
        cb.data = f"more:{self.OWNER_ID}:{tag_part}"
        cb.from_user = MagicMock()
        cb.from_user.id = clicker_id or self.OWNER_ID
        cb.from_user.username = "test_user"
        cb.inline_message_id = "AQAAABBBCCCDDD"
        cb.message = None
        cb.answer = AsyncMock()
        return cb

    @pytest.mark.asyncio
    async def test_caption_includes_stats_line(self, mock_bot_edit):
        cb = self._make_callback("maid")
        with (
            patch("inline_waifu_bot.handlers.database.update_user_sperm", return_value=50),
            patch("inline_waifu_bot.handlers.database.increment_tag_count"),
            patch("random.choices", return_value=[50]),
            patch("secrets.choice", return_value="Вы выдрочили яца"),
        ):
            with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
                await bot.handle_more_callback(cb)

        _args, kwargs = mock_bot_edit.call_args
        caption = kwargs["media"].caption
        assert "Вы выдрочили яца" in caption
        assert "✅" in caption
        assert "+50 мл спермы" in caption

    @pytest.mark.asyncio
    async def test_more_fallback_has_stats(self, mock_bot_edit):
        cb = self._make_callback("neko_gif")
        mock_bot_edit.side_effect = [
            TelegramBadRequest(method="edit_message_media", message="wrong type"),
            None,
        ]
        with (
            patch("inline_waifu_bot.handlers.database.update_user_sperm", return_value=-10),
            patch("inline_waifu_bot.handlers.database.increment_tag_count"),
            patch("random.choices", return_value=[-10]),
            patch("secrets.choice", return_value="У вас отвалился хуй"),
        ):
            with _mock_aiohttp_get(json_data=_PURRBOT_GIF_JSON):
                await bot.handle_more_callback(cb)

        second_call = mock_bot_edit.call_args_list[1]
        caption = second_call.kwargs["media"].caption
        assert "У вас отвалился хуй" in caption
        assert "❌" in caption
        assert "-10 мл спермы" in caption


# ─────────────────────────────────────────────────
#  Leaderboard inline query (top / stats)
# ─────────────────────────────────────────────────


class TestLeaderboardInlineQuery:
    """Проверяем, что 'top'/'stats' возвращает лидерборд, а не NSFW."""

    @pytest.fixture(autouse=True)
    def mock_fav_tags(self):
        """Подменяем get_user_favorite_tags — по дефолту возвращаем пустой список."""
        with patch(
            "inline_waifu_bot.handlers.database.get_user_favorite_tags",
            return_value=[],
        ) as m:
            yield m

    @pytest.fixture
    def mock_leaderboard(self):
        """Подменяем database.get_leaderboard на контролируемые данные."""
        data = [
            {"user_id": 1, "username": "alpha", "total_sperm": 100},
            {"user_id": 2, "username": "beta", "total_sperm": 50},
            {"user_id": 3, "username": "", "total_sperm": 10},
        ]
        with patch(
            "inline_waifu_bot.handlers.database.get_leaderboard",
            return_value=data,
        ) as m:
            yield m

    def _make_query(self, text: str) -> AsyncMock:
        query = AsyncMock(spec=InlineQuery)
        query.query = text
        query.from_user = MagicMock()
        query.from_user.id = 999
        query.answer = AsyncMock()
        return query

    @pytest.mark.asyncio
    async def test_returns_article_for_top(self, mock_leaderboard, mock_fav_tags):
        query = self._make_query("top")
        await bot.handle_inline_query(query)
        query.answer.assert_awaited_once()
        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert isinstance(result, InlineQueryResultArticle)

    @pytest.mark.asyncio
    async def test_returns_article_for_stats(self, mock_leaderboard, mock_fav_tags):
        query = self._make_query("stats")
        await bot.handle_inline_query(query)
        query.answer.assert_awaited_once()
        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert isinstance(result, InlineQueryResultArticle)

    @pytest.mark.asyncio
    async def test_leaderboard_content(self, mock_leaderboard, mock_fav_tags):
        query = self._make_query("top")
        await bot.handle_inline_query(query)
        _args, kwargs = query.answer.call_args
        text = kwargs["results"][0].input_message_content.message_text
        assert "🏆" in text
        assert "ТОП-10 САМЫХ ШПЕРМАПРИЕМНИКОВ ЧАТА" in text
        assert "🥇 alpha" in text or "alpha" in text
        assert "🥈 beta" in text or "beta" in text
        assert "User #3" in text  # пустой username → User #ID
        assert "100 мл спермы" in text
        assert "50 мл спермы" in text
        # Личной статистики в топе нет
        assert "Ты ещё не дрочил" not in text

    @pytest.mark.asyncio
    async def test_leaderboard_empty(self):
        query = self._make_query("top")
        with patch(
            "inline_waifu_bot.handlers.database.get_leaderboard",
            return_value=[],
        ):
            with patch(
                "inline_waifu_bot.handlers.database.get_user_favorite_tags",
                return_value=[],
            ):
                await bot.handle_inline_query(query)
        _args, kwargs = query.answer.call_args
        text = kwargs["results"][0].input_message_content.message_text
        assert "Пока никого нет" in text

    @pytest.mark.asyncio
    async def test_top_case_insensitive(self, mock_leaderboard, mock_fav_tags):
        query = self._make_query("TOP")
        await bot.handle_inline_query(query)
        query.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stats_with_whitespace(self, mock_leaderboard, mock_fav_tags):
        query = self._make_query("  stats  ")
        await bot.handle_inline_query(query)
        query.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_normal_tag_unaffected_by_leaderboard(self):
        """Обычный тег не задевает логику лидерборда."""
        query = self._make_query("maid")
        await bot.handle_inline_query(query)
        query.answer.assert_awaited_once()
        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert "verify_18" in result.reply_markup.inline_keyboard[0][0].callback_data
        assert result.title == "🔞 Подрочить на maid"

    @pytest.mark.asyncio
    async def test_cache_time_zero_for_leaderboard(self, mock_leaderboard, mock_fav_tags):
        query = self._make_query("top")
        await bot.handle_inline_query(query)
        _args, kwargs = query.answer.call_args
        assert kwargs["cache_time"] == 0
        assert kwargs["is_personal"] is True

    @pytest.mark.asyncio
    async def test_personal_stats_shown_with_tags(self):
        """Статистика с тегами по запросу 'stats'."""
        query = self._make_query("stats")
        with patch(
            "inline_waifu_bot.handlers.database.get_user_favorite_tags",
            return_value=[
                {"tag": "waifu", "count": 5},
                {"tag": "maid", "count": 3},
            ],
        ):
            await bot.handle_inline_query(query)
        _args, kwargs = query.answer.call_args
        text = kwargs["results"][0].input_message_content.message_text
        assert "waifu (5 раз)" in text
        assert "maid (3 раз)" in text
        assert "Излюбленные теги:" in text
        # Топа в статистике нет
        assert "ТОП-10" not in text

    @pytest.mark.asyncio
    async def test_personal_stats_empty_when_no_history(self):
        """Статистика пуста, если истории нет."""
        query = self._make_query("stats")
        with patch(
            "inline_waifu_bot.handlers.database.get_user_favorite_tags",
            return_value=[],
        ):
            await bot.handle_inline_query(query)
        _args, kwargs = query.answer.call_args
        text = kwargs["results"][0].input_message_content.message_text
        assert "Ты ещё не дрочил, твоя история пуста" in text
        assert "ТОП-10" not in text
