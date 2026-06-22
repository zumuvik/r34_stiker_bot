"""
Работа с провайдерами контента: Waifu.im (фото) и Reddit (видео).

Каждая функция-загрузчик возвращает ``(media_url, media_type)``,
где ``media_type`` — ``"photo"`` или ``"video"``.
"""

import asyncio
import logging
import secrets

import aiohttp

from . import config

logger = logging.getLogger(__name__)

# ─────────────────── Основная точка входа ───────────────────


async def fetch_nsfw_content(tag: str | None = None) -> tuple[str, str]:
    """
    Запрашивает контент (фото или видео) в зависимости от тега.

    * Если тег — видео-тег (``VIDEO_TAGS``) → запрос к Reddit.
    * Если тег — фото-тег (``PHOTO_TAGS``) → запрос к Waifu.im.
    * Если тег ``None`` (random) — случайный выбор 50/50 между фото и видео.

    Returns:
        Кортеж ``(media_url, media_type)``.
        При ошибке загрузки возвращает ``(FALLBACK_IMAGE_URL, "photo")``.
    """
    if tag is not None and config.is_video_tag(tag):
        subreddit = config.get_subreddit(tag)
        try:
            url = await _fetch_reddit_video(subreddit)
            return (url, "video")
        except Exception:
            logger.exception("Reddit fetch failed, falling back to photo")
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
            sub_list = list(config.VIDEO_SUBREDDITS.values())
            subreddit = secrets.choice(sub_list)
            try:
                url = await _fetch_reddit_video(subreddit)
                return (url, "video")
            except Exception:
                logger.warning(
                    "Reddit random failed, falling back to Waifu.im photo"
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


# ─────────────────── Reddit (видео) ───────────────────


async def _fetch_reddit_video(subreddit: str) -> str:
    """
    Запрашивает случайное видео из заданного сабреддита Reddit.

    Ищет:
    1. Посты с ``is_video=True`` и ``media.reddit_video.fallback_url``.
    2. Посты, где ``url`` заканчивается на ``.mp4``.

    Args:
        subreddit: Название сабреддита (например ``"nsfw_videos"``).

    Returns:
        Прямой URL видео (строка).

    Raises:
        ValueError: Если не удалось получить видео (пустой ответ, нет
                    подходящих постов, ошибка HTTP).
    """
    url = f"https://www.reddit.com/r/{subreddit}/random.json"
    headers = {"User-Agent": "WaifuBot/1.0 (+https://t.me/Waifulinuxbot)"}
    timeout = aiohttp.ClientTimeout(total=config.API_TIMEOUT_SECONDS)

    async with aiohttp.ClientSession(
        timeout=timeout, headers=headers
    ) as session:
        async with session.get(url) as response:
            if response.status != 200:
                body = await response.text()
                logger.error(
                    "Reddit API вернул %s: %s", response.status, body
                )
                raise ValueError(f"Reddit returned status {response.status}")

            data = await response.json()

            # Reddit /random.json иногда оборачивает ответ в массив
            if isinstance(data, list):
                if not data:
                    raise ValueError("Reddit returned empty array")
                data = data[0]

            posts = data.get("data", {}).get("children", [])

            for post in posts:
                post_data = post.get("data", {})

                # 1) reddit_video
                if post_data.get("is_video") and post_data.get("media"):
                    media = post_data["media"]
                    if "reddit_video" in media:
                        fallback = media["reddit_video"].get("fallback_url")
                        if fallback:
                            # Отрезаем query-параметры (?source=fallback)
                            clean = fallback.split("?")[0]
                            return clean

                # 2) прямая .mp4 ссылка
                post_url = post_data.get("url", "")
                if post_url.endswith(".mp4"):
                    return post_url

            raise ValueError("No suitable video post found")


async def _fetch_reddit_direct_mp4(subreddit: str) -> str:
    """
    Альтернативный метод: запрашивает hot-посты и ищет прямую mp4-ссылку
    в поле ``url``.

    Используется, если ``_fetch_reddit_video`` с ``/random.json``
    не находит видео (дополнительная попытка).
    """
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=30"
    headers = {"User-Agent": "WaifuBot/1.0 (+https://t.me/Waifulinuxbot)"}
    timeout = aiohttp.ClientTimeout(total=config.API_TIMEOUT_SECONDS)

    async with aiohttp.ClientSession(
        timeout=timeout, headers=headers
    ) as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise ValueError(
                    f"Reddit hot.json returned {response.status}"
                )

            data = await response.json()
            posts = data.get("data", {}).get("children", [])

            for post in posts:
                post_data = post.get("data", {})
                post_url = post_data.get("url", "")

                # Прямая mp4
                if post_url.endswith(".mp4"):
                    return post_url

                # reddit_video
                if post_data.get("is_video") and post_data.get("media"):
                    media = post_data["media"]
                    if "reddit_video" in media:
                        fallback = media["reddit_video"].get("fallback_url")
                        if fallback:
                            clean = fallback.split("?")[0]
                            return clean

            raise ValueError("No video found in hot.json")
