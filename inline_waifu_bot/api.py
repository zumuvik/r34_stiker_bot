"""
Работа с Waifu.im API: запрос NSFW-изображений.
"""

import asyncio
import logging

import aiohttp

from . import config

logger = logging.getLogger(__name__)


async def fetch_nsfw_image(tag: str | None = None) -> str:
    """
    Запрашивает NSFW-изображение у Waifu.im API.

    1. Формирует query-параметры: ``is_nsfw=true`` и, если передан тег,
       ``included_tags={tag}``.
    2. Совершает GET-запрос с таймаутом 5 секунд.
    3. Парсит ответ, извлекает URL первого изображения.
    4. При любой ошибке (сеть, таймаут, кривой JSON, пустой ответ)
       возвращает URL заглушки.

    Args:
        tag: Опциональный тег для фильтрации (например ``"maid"``, ``"ero"``).

    Returns:
        Прямой URL изображения (строка) или ``config.FALLBACK_IMAGE_URL``.
    """
    # Внимание: API чувствителен к регистру — параметры PascalCase!
    params: dict[str, str] = {"IsNsfw": "True"}
    if tag:
        params["IncludedTags"] = tag

    timeout = aiohttp.ClientTimeout(total=config.API_TIMEOUT_SECONDS)

    try:
        async with aiohttp.ClientSession(
            timeout=timeout,
            headers={"Accept-Version": "v7"},
        ) as session:
            async with session.get(config.WAIFU_API_URL, params=params) as response:
                if response.status != 200:
                    body = await response.text()
                    logger.error(
                        "Waifu API вернул %s: %s", response.status, body
                    )
                    return config.FALLBACK_IMAGE_URL

                data = await response.json()
                items = data.get("items") or data.get("images", [])

                if not items:
                    logger.error("Waifu API вернул пустой список изображений")
                    return config.FALLBACK_IMAGE_URL

                return items[0]["url"]

    except asyncio.TimeoutError:
        logger.error(
            "Таймаут запроса к Waifu.im API (%s сек)", config.API_TIMEOUT_SECONDS
        )
        return config.FALLBACK_IMAGE_URL
    except aiohttp.ClientError as exc:
        logger.error("HTTP-ошибка при запросе к Waifu.im API: %s", exc)
        return config.FALLBACK_IMAGE_URL
    except (KeyError, IndexError, ValueError) as exc:
        logger.error("Ошибка парсинга ответа Waifu API: %s", exc)
        return config.FALLBACK_IMAGE_URL
    except Exception as exc:
        logger.exception("Неожиданная ошибка при запросе к Waifu.im API: %s", exc)
        return config.FALLBACK_IMAGE_URL
