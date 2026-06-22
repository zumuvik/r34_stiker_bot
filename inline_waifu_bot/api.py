"""
Работа с провайдерами контента:

* Waifu.im (фото) — основные теги
* Purrbot API (GIF) — анимации
* waifu.pics (фото) — femboy
* Nekos API v4 (фото) — furry

Каждая функция-загрузчик возвращает ``(media_url, media_type, display_tag)``,
где ``display_tag`` — реальный тег контента (полезно при random-выборе).
"""

import asyncio
import logging
import secrets

import aiohttp

from . import config

logger = logging.getLogger(__name__)

PURRBOT_API_BASE = "https://api.purrbot.site"


# ─────────────────── Основная точка входа ───────────────────


async def fetch_nsfw_content(
    tag: str | None = None,
) -> tuple[str, str, str]:
    """
    Запрашивает контент (фото или GIF) в зависимости от тега.

    * Если тег — видео-тег (``VIDEO_TAGS``) → Purrbot API (GIF).
    * Если тег — фото-тег (``PHOTO_TAGS``) → Waifu.im.
    * Если тег ``None`` (random) — 50/50.

    Returns:
        Кортеж ``(media_url, media_type, display_tag)``.
        ``display_tag`` — реальный тег полученного контента.
        При ошибке возвращает ``(FALLBACK_IMAGE_URL, "photo", "error")``.
    """
    # ── femboy (waifu.pics) ─────────────────────────────
    if tag is not None and config.is_femboy_tag(tag):
        try:
            return await _fetch_femboy_photo()
        except Exception:
            logger.exception("Femboy fetch failed")
            return (config.FALLBACK_IMAGE_URL, "photo", "error")

    # ── furry (Nekos API v4) ────────────────────────────
    if tag is not None and config.is_furry_tag(tag):
        try:
            return await _fetch_furry_photo()
        except Exception:
            logger.exception("Furry fetch failed")
            return (config.FALLBACK_IMAGE_URL, "photo", "error")

    # ── Конкретный видео-тег (Purrbot) ──────────────────
    if tag is not None and config.is_video_tag(tag):
        endpoint = config.get_video_endpoint(tag)
        try:
            url = await _fetch_purrbot(endpoint)
            return (url, "video", tag)
        except Exception:
            logger.exception("Purrbot fetch failed, falling back to photo")
            return (config.FALLBACK_IMAGE_URL, "photo", "error")

    # ── Конкретный фото-тег (Waifu.im) ──────────────────
    if tag is not None and config.is_photo_tag(tag):
        url, _ = await _fetch_waifu_photo(tag)
        return (url, "photo", tag)

    # ── Random (50/50) ─────────────────────────────────
    if tag is None:
        if secrets.randbelow(2) == 0:
            url, actual_tag = await _fetch_waifu_photo(None)
            display = actual_tag or "random"
            return (url, "photo", display)
        else:
            ep_list = list(config.VIDEO_ENDPOINTS.values())
            endpoint = secrets.choice(ep_list)
            try:
                url = await _fetch_purrbot(endpoint)
                return (url, "video", "random_gif")
            except Exception:
                logger.warning(
                    "Purrbot random failed, falling back to Waifu.im photo"
                )
                url, actual_tag = await _fetch_waifu_photo(None)
                display = actual_tag or "random"
                return (url, "photo", display)

    return (config.FALLBACK_IMAGE_URL, "photo", "error")


# ─────────────────── Waifu.im (фото) ───────────────────


async def _fetch_waifu_photo(
    tag: str | None = None,
) -> tuple[str, str | None]:
    """
    Запрашивает NSFW-изображение у Waifu.im API.

    Returns:
        Кортеж ``(url, actual_tag_slug_or_None)``.
        ``actual_tag_slug`` извлекается из ответа API (поле
        ``tags[0]["slug"]``), если доступен.
        При ошибке возвращает ``(FALLBACK_IMAGE_URL, None)``.
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
                    return (config.FALLBACK_IMAGE_URL, None)

                data = await response.json()
                items = data.get("items") or data.get("images", [])

                if not items:
                    logger.error(
                        "Waifu API вернул пустой список изображений"
                    )
                    return (config.FALLBACK_IMAGE_URL, None)

                # Извлекаем тег из ответа (первый тег первого изображения)
                img = items[0]
                actual_tag: str | None = None
                tags = img.get("tags")
                if tags and isinstance(tags, list) and len(tags) > 0:
                    actual_tag = tags[0].get("slug") or tags[0].get("name")

                return (img["url"], actual_tag)

    except asyncio.TimeoutError:
        logger.error(
            "Таймаут запроса к Waifu.im API (%s сек)",
            config.API_TIMEOUT_SECONDS,
        )
        return (config.FALLBACK_IMAGE_URL, None)
    except aiohttp.ClientError as exc:
        logger.error("HTTP-ошибка при запросе к Waifu.im API: %s", exc)
        return (config.FALLBACK_IMAGE_URL, None)
    except (KeyError, IndexError, ValueError) as exc:
        logger.error("Ошибка парсинга ответа Waifu API: %s", exc)
        return (config.FALLBACK_IMAGE_URL, None)
    except Exception as exc:
        logger.exception(
            "Неожиданная ошибка при запросе к Waifu.im API: %s", exc
        )
        return (config.FALLBACK_IMAGE_URL, None)


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


# ─────────────────── waifu.pics (femboy фото) ───────────────────


async def _fetch_femboy_photo() -> tuple[str, str, str]:
    """
    Запрашивает NSFW-фото femboy через waifu.pics API.

    Returns:
        ``(url, "photo", "femboy")``.

    Raises:
        Exception: При любых сетевых/парсинговых ошибках.
    """
    url = config.FEMBOY_API_URL
    timeout = aiohttp.ClientTimeout(total=config.API_TIMEOUT_SECONDS)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            if response.status != 200:
                body = await response.text()
                logger.error(
                    "waifu.pics вернул %s: %s", response.status, body
                )
                raise ValueError(f"waifu.pics status {response.status}")

            data = await response.json()
            image_url = data.get("url")
            if not image_url:
                raise ValueError("waifu.pics response missing 'url'")

            return (image_url, "photo", "femboy")


# ─────────────────── Nekos API v4 (furry фото) ───────────────────


async def _fetch_furry_photo() -> tuple[str, str, str]:
    """
    Запрашивает NSFW-фото furry через Nekos API v4.

    Returns:
        ``(url, "photo", "furry")``.

    Raises:
        Exception: При любых сетевых/парсинговых ошибках.
    """
    params = {"rating": "explicit", "limit": "1", "tags": "furry"}
    timeout = aiohttp.ClientTimeout(total=config.API_TIMEOUT_SECONDS)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(config.FURRY_API_URL, params=params) as response:
            if response.status != 200:
                body = await response.text()
                logger.error(
                    "Nekos API вернул %s: %s", response.status, body
                )
                raise ValueError(f"Nekos API status {response.status}")

            data = await response.json()
            items = data.get("items")
            if not items or not isinstance(items, list) or len(items) == 0:
                raise ValueError("Nekos API вернул пустой список")

            image_url = items[0].get("url")
            if not image_url:
                raise ValueError("Nekos API item missing 'url'")

            return (image_url, "photo", "furry")
