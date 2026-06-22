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
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultPhoto,
    InputMediaPhoto,
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
        markup = bot.build_markup("maid")
        assert isinstance(markup, InlineKeyboardMarkup)
        btn = markup.inline_keyboard[0][0]
        assert btn.text == "🔥 Давай ещё!"
        assert btn.callback_data == "more_maid"

    def test_without_tag(self):
        markup = bot.build_markup(None)
        btn = markup.inline_keyboard[0][0]
        assert btn.callback_data == "more_random"

    def test_several_tags(self):
        for tag in ("ero", "hentai", "waifu"):
            btn = bot.build_markup(tag).inline_keyboard[0][0]
            assert btn.callback_data == f"more_{tag}"

    def test_returns_new_markup_each_call(self):
        m1 = bot.build_markup("maid")
        m2 = bot.build_markup("maid")
        assert m1 is not m2


# ─────────────────────────────────────────────────
#  fetch_nsfw_image
# ─────────────────────────────────────────────────


class TestFetchNsfwImage:
    """Все сценарии работы с Waifu.im API."""

    FALLBACK = bot.FALLBACK_IMAGE_URL
    SUCCESS_URL = "https://cdn.waifu.im/test_123.jpg"
    SUCCESS_JSON = {"items": [{"url": SUCCESS_URL}]}
    EMPTY_JSON = {"items": []}

    # -- Успех -------------------------------------------------

    @pytest.mark.asyncio
    async def test_success_no_tag(self):
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON) as (resp, session):
            url = await bot.fetch_nsfw_image()

        assert url == self.SUCCESS_URL

    @pytest.mark.asyncio
    async def test_success_with_tag(self):
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON) as (resp, session):
            url = await bot.fetch_nsfw_image("maid")

        assert url == self.SUCCESS_URL
        # Проверяем, что тег ушёл в запрос
        session.get.assert_called_once_with(
            bot.WAIFU_API_URL,
            params={"is_nsfw": "true", "included_tags": "maid"},
        )

    # -- HTTP-ошибки -------------------------------------------

    @pytest.mark.asyncio
    async def test_non_200_status(self):
        with _mock_aiohttp_get(status=500, text_data="Internal Server Error"):
            url = await bot.fetch_nsfw_image()

        assert url == self.FALLBACK

    @pytest.mark.asyncio
    async def test_404_status(self):
        with _mock_aiohttp_get(status=404, text_data="Not Found"):
            url = await bot.fetch_nsfw_image()

        assert url == self.FALLBACK

    # -- Пустой ответ -----------------------------------------

    @pytest.mark.asyncio
    async def test_empty_images_list(self):
        with _mock_aiohttp_get(json_data=self.EMPTY_JSON):
            url = await bot.fetch_nsfw_image()

        assert url == self.FALLBACK

    @pytest.mark.asyncio
    async def test_missing_images_key(self):
        with _mock_aiohttp_get(json_data={"error": "no images"}):
            url = await bot.fetch_nsfw_image()

        assert url == self.FALLBACK

    # -- Сетевые ошибки ----------------------------------------

    @pytest.mark.asyncio
    async def test_timeout(self):
        """Таймаут → fallback."""
        with _mock_aiohttp_get() as (resp, session):
            resp.json.side_effect = asyncio.TimeoutError

            url = await bot.fetch_nsfw_image()

        assert url == self.FALLBACK

    @pytest.mark.asyncio
    async def test_client_error(self):
        with _mock_aiohttp_get() as (resp, session):
            resp.json.side_effect = aiohttp.ClientError("connection reset")

            url = await bot.fetch_nsfw_image()

        assert url == self.FALLBACK

    # -- Кривые данные ----------------------------------------

    @pytest.mark.asyncio
    async def test_malformed_json_not_a_dict(self):
        with _mock_aiohttp_get(json_data=["not", "a", "dict"]):
            url = await bot.fetch_nsfw_image()

        assert url == self.FALLBACK

    @pytest.mark.asyncio
    async def test_image_missing_url_key(self):
        with _mock_aiohttp_get(json_data={"items": [{"id": 1}]}):
            url = await bot.fetch_nsfw_image()

        assert url == self.FALLBACK

    # -- Параметры запроса ------------------------------------

    @pytest.mark.asyncio
    async def test_no_tag_passes_only_is_nsfw(self):
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON) as (resp, session):
            await bot.fetch_nsfw_image()

        session.get.assert_called_once_with(
            bot.WAIFU_API_URL,
            params={"is_nsfw": "true"},
        )

    @pytest.mark.asyncio
    async def test_empty_tag_passes_only_is_nsfw(self):
        """Если тег пустая строка — он не None, но валидатор отсечёт.
        Функция fetch_nsfw_image получает None из handle_inline_query."""
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON) as (resp, session):
            await bot.fetch_nsfw_image(None)

        session.get.assert_called_once_with(
            bot.WAIFU_API_URL,
            params={"is_nsfw": "true"},
        )


# ─────────────────────────────────────────────────
#  handle_inline_query
# ─────────────────────────────────────────────────


class TestHandleInlineQuery:
    """Проверяем логику формирования ответа на инлайн-запрос."""

    SUCCESS_URL = "https://cdn.waifu.im/inline_test.jpg"
    SUCCESS_JSON = {"items": [{"url": SUCCESS_URL}]}

    def _make_query(self, text: str) -> AsyncMock:
        query = AsyncMock(spec=InlineQuery)
        query.query = text
        query.from_user = MagicMock()
        query.from_user.id = 12345
        query.answer = AsyncMock(return_value=None)
        return query

    @pytest.mark.asyncio
    async def test_valid_tag_in_caption(self):
        query = self._make_query("maid")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        query.answer.assert_awaited_once()
        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert "maid" in result.caption
        assert isinstance(result, InlineQueryResultPhoto)

    @pytest.mark.asyncio
    async def test_invalid_tag_uses_random_in_caption(self):
        query = self._make_query("unknown_tag")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert "random" in result.caption

    @pytest.mark.asyncio
    async def test_empty_query_uses_random(self):
        query = self._make_query("")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert "random" in result.caption
        assert isinstance(result, InlineQueryResultPhoto)

    @pytest.mark.asyncio
    async def test_whitespace_query_uses_random(self):
        query = self._make_query("   ")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert "random" in result.caption

    @pytest.mark.asyncio
    async def test_cache_time_is_zero(self):
        query = self._make_query("ero")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        assert kwargs["cache_time"] == 0

    @pytest.mark.asyncio
    async def test_result_has_reply_markup(self):
        query = self._make_query("hentai")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        markup = result.reply_markup
        assert markup is not None
        btn = markup.inline_keyboard[0][0]
        assert btn.callback_data == "more_hentai"

    @pytest.mark.asyncio
    async def test_result_has_reply_markup_random(self):
        query = self._make_query("")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        btn = result.reply_markup.inline_keyboard[0][0]
        assert btn.callback_data == "more_random"

    @pytest.mark.asyncio
    async def test_single_result_returned(self):
        query = self._make_query("maid")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        assert len(kwargs["results"]) == 1

    @pytest.mark.asyncio
    async def test_fallback_on_api_error(self):
        """При ошибке API в ответе всё равно валидный InlineQueryResultPhoto."""
        query = self._make_query("maid")

        with _mock_aiohttp_get(status=503):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert result.photo_url == bot.FALLBACK_IMAGE_URL
        assert result.thumbnail_url == bot.FALLBACK_IMAGE_URL


# ─────────────────────────────────────────────────
#  handle_more_callback
# ─────────────────────────────────────────────────


class TestHandleMoreCallback:
    """Проверяем логику кнопки «Давай ещё!»."""

    SUCCESS_URL = "https://cdn.waifu.im/callback_new.jpg"
    SUCCESS_JSON = {"items": [{"url": SUCCESS_URL}]}

    def _make_callback(self, data: str) -> AsyncMock:
        callback = AsyncMock(spec=CallbackQuery)
        callback.data = data
        callback.from_user = MagicMock()
        callback.from_user.id = 12345
        # message — отдельный мок с edit_media
        callback.message = MagicMock(spec=Message)
        callback.message.edit_media = AsyncMock(return_value=None)
        # Явно задаём AsyncMock, иначе AsyncMock возвращает
        # обычный MagicMock, который нельзя await.
        callback.answer = AsyncMock(return_value=None)
        return callback

    # -- Разбор callback_data ----------------------------------

    @pytest.mark.asyncio
    async def test_extracts_tag_from_callback_data(self):
        callback = self._make_callback("more_maid")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON) as (resp, session):
            await bot.handle_more_callback(callback)

        session.get.assert_called_once_with(
            bot.WAIFU_API_URL,
            params={"is_nsfw": "true", "included_tags": "maid"},
        )

    @pytest.mark.asyncio
    async def test_random_callback_passes_no_tag(self):
        callback = self._make_callback("more_random")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON) as (resp, session):
            await bot.handle_more_callback(callback)

        session.get.assert_called_once_with(
            bot.WAIFU_API_URL,
            params={"is_nsfw": "true"},
        )

    # -- edit_media -------------------------------------------

    @pytest.mark.asyncio
    async def test_edit_media_called_once(self):
        callback = self._make_callback("more_ero")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        callback.message.edit_media.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_edit_media_contains_InputMediaPhoto(self):
        callback = self._make_callback("more_ero")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        _args, kwargs = callback.message.edit_media.call_args
        media = kwargs.get("media")
        assert isinstance(media, InputMediaPhoto)
        assert media.media == self.SUCCESS_URL

    @pytest.mark.asyncio
    async def test_edit_media_has_reply_markup(self):
        callback = self._make_callback("more_ero")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        _args, kwargs = callback.message.edit_media.call_args
        rm = kwargs.get("reply_markup")
        assert rm is not None
        assert rm.inline_keyboard[0][0].callback_data == "more_ero"

    @pytest.mark.asyncio
    async def test_random_edit_has_random_markup(self):
        callback = self._make_callback("more_random")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        _args, kwargs = callback.message.edit_media.call_args
        rm = kwargs.get("reply_markup")
        assert rm.inline_keyboard[0][0].callback_data == "more_random"

    # -- callback.answer --------------------------------------

    @pytest.mark.asyncio
    async def test_answer_called_on_success(self):
        callback = self._make_callback("more_waifu")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        callback.answer.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_answer_with_alert_on_edit_failure(self):
        callback = self._make_callback("more_waifu")
        callback.message.edit_media.side_effect = Exception("edit failed")
        callback.answer = AsyncMock(return_value=None)

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        callback.answer.assert_awaited_once_with(
            "Не удалось обновить картинку. Попробуйте ещё раз.",
            show_alert=True,
        )

    # -- Тег в caption ----------------------------------------

    @pytest.mark.asyncio
    async def test_caption_contains_tag_in_edit(self):
        callback = self._make_callback("more_maid")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        _args, kwargs = callback.message.edit_media.call_args
        caption = kwargs["media"].caption
        assert "maid" in caption

    @pytest.mark.asyncio
    async def test_caption_contains_random_in_edit(self):
        callback = self._make_callback("more_random")

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        _args, kwargs = callback.message.edit_media.call_args
        caption = kwargs["media"].caption
        assert "random" in caption


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
