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
from aiogram.types import (
    CallbackQuery,
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
        markup = bot.build_markup("maid", owner_id=12345)
        assert isinstance(markup, InlineKeyboardMarkup)
        btn = markup.inline_keyboard[0][0]
        assert btn.text == "🔥 Давай ещё!"
        assert btn.callback_data == "more_maid_12345"

    def test_without_tag(self):
        markup = bot.build_markup(None, owner_id=999)
        btn = markup.inline_keyboard[0][0]
        assert btn.callback_data == "more_random_999"

    def test_several_tags(self):
        for tag in ("ero", "hentai", "waifu"):
            btn = bot.build_markup(tag, owner_id=42).inline_keyboard[0][0]
            assert btn.callback_data == f"more_{tag}_42"

    def test_returns_new_markup_each_call(self):
        m1 = bot.build_markup("maid", owner_id=1)
        m2 = bot.build_markup("maid", owner_id=1)
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
            params={"IsNsfw": "True", "IncludedTags": "maid"},
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
            params={"IsNsfw": "True"},
        )

    @pytest.mark.asyncio
    async def test_empty_tag_passes_only_is_nsfw(self):
        """Если тег пустая строка — он не None, но валидатор отсечёт.
        Функция fetch_nsfw_image получает None из handle_inline_query."""
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON) as (resp, session):
            await bot.fetch_nsfw_image(None)

        session.get.assert_called_once_with(
            bot.WAIFU_API_URL,
            params={"IsNsfw": "True"},
        )


# ─────────────────────────────────────────────────
#  handle_inline_query
# ─────────────────────────────────────────────────


class TestHandleInlineQuery:
    """Проверяет, что инлайн возвращает InlineQueryResultPhoto с фото и кнопкой."""

    SUCCESS_URL = "https://cdn.waifu.im/inline_test.jpg"
    SUCCESS_JSON = {"items": [{"url": SUCCESS_URL}]}

    def _make_query(self, text: str) -> AsyncMock:
        query = AsyncMock(spec=InlineQuery)
        query.query = text
        query.from_user = MagicMock()
        query.from_user.id = 12345
        query.answer = AsyncMock(return_value=None)
        return query

    # ── Тип результата ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_returns_photo_not_article(self):
        """Возвращается InlineQueryResultPhoto — фото с превью."""
        query = self._make_query("maid")
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        query.answer.assert_awaited_once()
        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert isinstance(result, InlineQueryResultPhoto)

    # ── photo_url / thumbnail_url ───────────────────────────

    @pytest.mark.asyncio
    async def test_photo_url_from_api(self):
        """photo_url берётся из Waifu.im API (не плейсхолдер)."""
        query = self._make_query("maid")
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert result.photo_url == self.SUCCESS_URL
        assert result.thumbnail_url == self.SUCCESS_URL

    @pytest.mark.asyncio
    async def test_fallback_on_api_error(self):
        """При ошибке API используется FALLBACK_IMAGE_URL."""
        query = self._make_query("maid")
        with _mock_aiohttp_get(status=500, text_data="Server Error"):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert result.photo_url == bot.FALLBACK_IMAGE_URL

    # ── Caption ─────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_caption_contains_tag(self):
        query = self._make_query("maid")
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert result.caption is not None
        assert "maid" in result.caption

    @pytest.mark.asyncio
    async def test_caption_contains_random_when_no_tag(self):
        query = self._make_query("")
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert "random" in result.caption

    @pytest.mark.asyncio
    async def test_caption_contains_random_when_invalid_tag(self):
        query = self._make_query("unknown")
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert "random" in result.caption

    # ── Reply markup (кнопка) ───────────────────────────────

    @pytest.mark.asyncio
    async def test_has_reply_markup(self):
        query = self._make_query("maid")
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert result.reply_markup is not None
        assert result.reply_markup.inline_keyboard[0][0].text == "🔥 Давай ещё!"

    @pytest.mark.asyncio
    async def test_reply_markup_contains_owner_id(self):
        query = self._make_query("maid")
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        cd = result.reply_markup.inline_keyboard[0][0].callback_data
        assert "12345" in cd

    @pytest.mark.asyncio
    async def test_reply_markup_contains_tag(self):
        query = self._make_query("maid")
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        cd = result.reply_markup.inline_keyboard[0][0].callback_data
        assert "more_maid_" in cd

    @pytest.mark.asyncio
    async def test_reply_markup_random_when_no_tag(self):
        query = self._make_query("")
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        cd = result.reply_markup.inline_keyboard[0][0].callback_data
        assert "more_random_" in cd

    # ── Нет input_message_content ─────────────────────────

    @pytest.mark.asyncio
    async def test_no_input_message_content(self):
        """Нет текстового сообщения — фото отправляется напрямую."""
        query = self._make_query("maid")
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        result = kwargs["results"][0]
        assert result.input_message_content is None

    # ── Параметры query.answer ─────────────────────────────

    @pytest.mark.asyncio
    async def test_cache_time_is_zero(self):
        query = self._make_query("ero")
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        assert kwargs["cache_time"] == 0

    @pytest.mark.asyncio
    async def test_is_personal(self):
        query = self._make_query("maid")
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        assert kwargs["is_personal"] is True

    @pytest.mark.asyncio
    async def test_single_result(self):
        query = self._make_query("maid")
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        assert len(kwargs["results"]) == 1

    @pytest.mark.asyncio
    async def test_switch_pm_text_and_parameter(self):
        query = self._make_query("maid")
        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_inline_query(query)

        _args, kwargs = query.answer.call_args
        assert kwargs.get("switch_pm_text") == "📋 Список тегов"
        assert kwargs.get("switch_pm_parameter") == "tags"





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
        tag_part = f"more_{tag}" if tag else "more_random"
        callback_data = f"{tag_part}_{self.OWNER_ID}"

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
            "❌ Это могут нажимать только тот, кто отправил картинку.",
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
            0].callback_data == f"more_ero_{self.OWNER_ID}"

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
        assert rm.inline_keyboard[0][0].callback_data == f"more_ero_{self.OWNER_ID}"

    @pytest.mark.asyncio
    async def test_inline_random_edit_has_random_markup(self, mock_bot_edit):
        callback = self._make_callback(None)

        with _mock_aiohttp_get(json_data=self.SUCCESS_JSON):
            await bot.handle_more_callback(callback)

        _args, kwargs = mock_bot_edit.call_args
        rm = kwargs["reply_markup"]
        assert rm.inline_keyboard[0][0].callback_data == f"more_random_{self.OWNER_ID}"

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
            0].callback_data == f"more_ero_{self.OWNER_ID}"

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
