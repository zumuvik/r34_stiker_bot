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
    PHOTO_JSON = {"items": [{"url": PHOTO_URL}]}
    EMPTY_JSON = {"items": []}

    # ── Photo: Waifu.im (успех) ──────────────────────────────

    @pytest.mark.asyncio
    async def test_photo_with_tag(self):
        with _mock_aiohttp_get(json_data=self.PHOTO_JSON) as (resp, session):
            url, mtype = await bot.fetch_nsfw_content("maid")

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
                url, mtype = await bot.fetch_nsfw_content(None)

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
            url, mtype = await bot.fetch_nsfw_content("neko_gif")

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
                    url, mtype = await bot.fetch_nsfw_content(None)

        assert mtype == "video"

    # ── HTTP-ошибки (фото) ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_photo_non_200(self):
        with _mock_aiohttp_get(status=500, text_data="Error"):
            url, mtype = await bot.fetch_nsfw_content("waifu")

        assert url == self.FALLBACK
        assert mtype == "photo"

    @pytest.mark.asyncio
    async def test_photo_empty_list(self):
        with _mock_aiohttp_get(json_data=self.EMPTY_JSON):
            url, mtype = await bot.fetch_nsfw_content("maid")

        assert url == self.FALLBACK
        assert mtype == "photo"

    # ── HTTP-ошибки (GIF) → фоллбэк на фото ─────────────────

    @pytest.mark.asyncio
    async def test_video_purrbot_500_falls_back_to_photo(self):
        with _mock_aiohttp_get(status=500, text_data="Server Error"):
            url, mtype = await bot.fetch_nsfw_content("neko_gif")

        assert url == self.FALLBACK
        assert mtype == "photo"

    @pytest.mark.asyncio
    async def test_video_purrbot_error_falls_back_to_photo(self):
        with _mock_aiohttp_get(json_data=_PURRBOT_ERROR_JSON):
            url, mtype = await bot.fetch_nsfw_content("neko_gif")

        assert url == self.FALLBACK
        assert mtype == "photo"

    @pytest.mark.asyncio
    async def test_video_purrbot_no_link_falls_back_to_photo(self):
        with _mock_aiohttp_get(json_data=_PURRBOT_NO_LINK_JSON):
            url, mtype = await bot.fetch_nsfw_content("nsfw_gif")

        assert url == self.FALLBACK
        assert mtype == "photo"

    # ── Сетевые ошибки (фото) ────────────────────────────────

    @pytest.mark.asyncio
    async def test_photo_timeout(self):
        with _mock_aiohttp_get() as (resp, session):
            resp.json.side_effect = asyncio.TimeoutError
            url, mtype = await bot.fetch_nsfw_content("maid")

        assert url == self.FALLBACK
        assert mtype == "photo"

    @pytest.mark.asyncio
    async def test_photo_client_error(self):
        with _mock_aiohttp_get() as (resp, session):
            resp.json.side_effect = aiohttp.ClientError("reset")
            url, mtype = await bot.fetch_nsfw_content("maid")

        assert url == self.FALLBACK
        assert mtype == "photo"

    # ── Кривые данные ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_photo_malformed_json(self):
        with _mock_aiohttp_get(json_data=["not", "a", "dict"]):
            url, mtype = await bot.fetch_nsfw_content("waifu")

        assert url == self.FALLBACK
        assert mtype == "photo"

    @pytest.mark.asyncio
    async def test_photo_missing_url_key(self):
        with _mock_aiohttp_get(json_data={"items": [{"id": 1}]}):
            url, mtype = await bot.fetch_nsfw_content("waifu")

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
    async def test_title_shows_random_when_no_tag(self):
        query = self._make_query("")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert "random" in result.title

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
    async def test_input_message_content_random_when_no_tag(self):
        query = self._make_query("")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert "random" in result.input_message_content.message_text

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
    async def test_verify_callback_random_when_no_tag(self):
        query = self._make_query("")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        btn = result.reply_markup.inline_keyboard[0][0]
        assert btn.callback_data == "verify_18:12345:random"

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
    async def test_switch_pm_text_and_parameter(self):
        query = self._make_query("maid")
        await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        assert kwargs.get("switch_pm_text") == "📋 Список тегов"
        assert kwargs.get("switch_pm_parameter") == "tags"





# ─────────────────────────────────────────────────
#  handle_verify_callback
# ─────────────────────────────────────────────────


class TestHandleVerifyCallback:
    """Проверяет логику кнопки «Мне есть 18 лет ✅»."""

    SUCCESS_URL = "https://cdn.waifu.im/verify_test.jpg"
    SUCCESS_JSON = {"items": [{"url": SUCCESS_URL}]}
    CREATOR_ID = 12345
    STRANGER_ID = 99999

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
    SUCCESS_JSON = {"items": [{"url": SUCCESS_URL}]}
    OWNER_ID = 12345
    STRANGER_ID = 99999

    @pytest.fixture(autouse=True)
    def clear_cooldowns(self):
        """Сбрасываем кд перед каждым тестом."""
        bot._cooldowns.clear()

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
    async def test_inline_caption_contains_random(self, mock_bot_edit):
        callback = self._make_callback(None)

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        _args, kwargs = mock_bot_edit.call_args
        assert "random" in kwargs["media"].caption

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
