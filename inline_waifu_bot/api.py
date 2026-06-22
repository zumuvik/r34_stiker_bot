"""
Работа с провайдерами контента: Waifu.im (фото) и Purrbot API (GIF).

Каждая функция-загрузчик возвращает ``(media_url, media_type)``,
где ``media_type`` — ``"photo"`` или ``"video"`` (GIF отправляется
как InputMediaVideo).
"""

import asyncio
import logging
import secrets

import aiohttp

from . import config

logger = logging.getLogger(__name__)

PURRBOT_API_BASE = "https://api.purrbot.site"


# ─────────────────── Основная точка входа ───────────────────


async def fetch_nsfw_content(tag: str | None = None) -> tuple[str, str]:
    """
    Запрашивает контент (фото или GIF) в зависимости от тега.

    * Если тег — видео-тег (``VIDEO_TAGS``) → запрос к Purrbot API (GIF).
    * Если тег — фото-тег (``PHOTO_TAGS``) → запрос к Waifu.im.
    * Если тег ``None`` (random) — случайный выбор 50/50.

    Returns:
        Кортеж ``(media_url, media_type)``.
        При ошибке загрузки возвращает ``(FALLBACK_IMAGE_URL, "photo")``.
    """
    if tag is not None and config.is_video_tag(tag):
        endpoint = config.get_video_endpoint(tag)
        try:
            url = await _fetch_purrbot(endpoint)
            return (url, "video")
        except Exception:
            logger.exception("Purrbot fetch failed, falling back to photo")
            return (config.FALLBACK_IMAGE_URL, "photo")

    if tag is not None and config.is_photo_tag(tag):
        url = await _fetch_waifu_photo(tag)
        return (url, "photo")

    # tag is None — случайный выбор 50/50
    if tag is None:
        if secrets.randbelow(2) == 0:
            url = await _fetch_waifu_photo(None)
            return (url, "photo")
        else:
            ep_list = list(config.VIDEO_ENDPOINTS.values())
            endpoint = secrets.choice(ep_list)
            try:
                url = await _fetch_purrbot(endpoint)
                return (url, "video")
            except Exception:
                logger.warning(
                    "Purrbot random failed, falling back to Waifu.im photo"
                )
                url = await _fetch_waifu_photo(None)
                return (url, "photo")

    # Крайний случай (не должен возникать при корректной валидации)
    return (config.FALLBACK_IMAGE_URL, "photo")


# ─────────────────── Waifu.im (фото) ───────────────────


async def _fetch_waifu_photo(tag: str | None = None) -> str:
    """
    Запрашивает NSFW-изображение у Waifu.im API.

    Query-параметры: ``IsNsfw=True`` и, если передан тег,
    ``IncludedTags={tag}``.

    Returns:
        Прямой URL изображения или ``config.FALLBACK_IMAGE_URL`` при ошибке.
    """
    params: dict[str, str] = {"IsNsfw": "True"}
    if tag:
        params["IncludedTags"] = tag

    timeout = aiohttp.ClientTimeout(total=config.API_TIMEOUT_SECONDS)

    try:
        async with aiohttp.ClientSession(
            timeout=timeout,
            headers={"Accept-Version": "v7"},
        ) as session:
            async with session.get(
                config.WAIFU_API_URL, params=params
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    logger.error(
                        "Waifu API вернул %s: %s", response.status, body
                    )
                    return config.FALLBACK_IMAGE_URL

                data = await response.json()
                items = data.get("items") or data.get("images", [])

                if not items:
                    logger.error(
                        "Waifu API вернул пустой список изображений"
                    )
                    return config.FALLBACK_IMAGE_URL

                return items[0]["url"]

    except asyncio.TimeoutError:
        logger.error(
            "Таймаут запроса к Waifu.im API (%s сек)",
            config.API_TIMEOUT_SECONDS,
        )
        return config.FALLBACK_IMAGE_URL
    except aiohttp.ClientError as exc:
        logger.error("HTTP-ошибка при запросе к Waifu.im API: %s", exc)
        return config.FALLBACK_IMAGE_URL
    except (KeyError, IndexError, ValueError) as exc:
        logger.error("Ошибка парсинга ответа Waifu API: %s", exc)
        return config.FALLBACK_IMAGE_URL
    except Exception as exc:
        logger.exception(
            "Неожиданная ошибка при запросе к Waifu.im API: %s", exc
        )
        return config.FALLBACK_IMAGE_URL


# ─────────────────── Purrbot API (GIF) ───────────────────


async def _fetch_purrbot(endpoint: str) -> str:
    """
    Запрашивает GIF из Purrbot API.

    Args:
        endpoint: Путь эндпоинта (например ``"v2/img/nsfw/neko/gif"``).

    Returns:
        Прямой URL GIF-изображения.

    Raises:
        ValueError: При ошибке HTTP, пустом ответе или отсутствии ключа ``link``.
    """
    url = f"{PURRBOT_API_BASE}/{endpoint.lstrip('/')}"
    timeout = aiohttp.ClientTimeout(total=config.API_TIMEOUT_SECONDS)
    headers = {"User-Agent": "WaifuBot/1.0"}

    async with aiohttp.ClientSession(
        timeout=timeout, headers=headers
    ) as session:
        async with session.get(url) as response:
            if response.status != 200:
                body = await response.text()
                logger.error(
                    "Purrbot API вернул %s: %s", response.status, body
                )
                raise ValueError(
                    f"Purrbot returned status {response.status}"
                )

            data = await response.json()

            if data.get("error"):
                logger.error(
                    "Purrbot API вернул ошибку: %s", data.get("message", "")
                )
                raise ValueError("Purrbot API error")

            link = data.get("link")
            if not link:
                raise ValueError("Purrbot response missing 'link'")

            return link
