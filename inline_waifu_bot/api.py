"""
Работа с провайдерами контента:

* Waifu.im (фото) — основные теги
* Purrbot API (GIF) — анимации
* e621.net (фото) — femboy / furry
* Yande.re (фото) — feet / heels (девочки, не фури)

Каждая функция-загрузчик возвращает ``(media_url, media_type, display_tag)``.
Каждый провайдер сам отвечает за дедупликацию URL через общий кэш ``_RECENT_URLS``.

Логирование: все сообщения форматированы как ``[#RID] [тег] сообщение``,
где RID — сквозной ID запроса для трассировки.
"""

import asyncio
import logging
import secrets
import random as _random
import time
from collections import defaultdict, deque

import aiohttp

from . import config

logger = logging.getLogger(__name__)

PURRBOT_API_BASE = "https://api.purrbot.site"

# ── Deduplication cache ──────────────────────────────────────────
_RECENT_URLS: dict[str, deque] = defaultdict(lambda: deque(maxlen=30))

def _is_recent(tag_key: str, url: str) -> bool:
    return url in _RECENT_URLS[tag_key]

def _mark_seen(tag_key: str, url: str) -> None:
    _RECENT_URLS[tag_key].append(url)

# ── Validated URL cache (HEAD-проверенные ссылки, до 30шт на тег) ──
_VALIDATED_CACHE: dict[str, deque] = defaultdict(lambda: deque(maxlen=30))

def _cache_pop(tag: str) -> str | None:
    """Извлекает одну проверенную ссылку из кэша (FIFO)."""
    q = _VALIDATED_CACHE.get(tag)
    return q.popleft() if q and len(q) > 0 else None

def _cache_push(tag: str, url: str) -> None:
    """Добавляет проверенную ссылку в кэш."""
    _VALIDATED_CACHE[tag].append(url)

async def _validate_url(url: str) -> bool:
    """
    HEAD-запрос: проверяет, что URL доступен и возвращает image/*.
    Таймаут 3 секунды, следует редиректы.
    """
    try:
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.head(url, allow_redirects=True) as resp:
                ct = resp.headers.get("Content-Type", "")
                return resp.status == 200 and ct.startswith("image/")
    except Exception:
        return False


# ── Logging helpers ──────────────────────────────────────────────

_rid_counter: int = 0

def _next_rid() -> int:
    global _rid_counter
    _rid_counter += 1
    return _rid_counter

def _trunc(body: str, n: int = 200) -> str:
    """Обрезает тело ответа для логов, экранируя непечатные символы."""
    if len(body) > n:
        return body[:n] + "..."
    return body

async def _log_call(tag_key: str | None, provider: str, fetch_fn, *args, **kwargs):
    """Вызывает fetch_fn(*args, **kwargs) с логированием времени и результата.
    
    Формат:
        [#0001] [femboy] ← e621
        [#0001] [femboy] → e621 OK (0.58s)
        [#0001] [femboy] → e621 FAILED (2.30s): ValueError: e621 status 403
    
    Возвращает результат или пробрасывает исключение.
    """
    rid = _next_rid()
    tag_s = tag_key or "?"
    t0 = time.monotonic()
    logger.info("[#%04d] [%s] ← %s", rid, tag_s, provider)
    try:
        result = await fetch_fn(*args, **kwargs)
        elapsed = time.monotonic() - t0
        logger.info("[#%04d] [%s] → %s OK (%.2fs)", rid, tag_s, provider, elapsed)
        return result
    except Exception as exc:
        elapsed = time.monotonic() - t0
        logger.error(
            "[#%04d] [%s] → %s FAILED (%.2fs): %s: %s",
            rid, tag_s, provider, elapsed, type(exc).__name__, exc,
        )
        raise


# ─────────────────── Live fetch (без кэша) ────────────────────


async def _live_fetch(
    tag: str | None = None,
) -> tuple[str, str, str]:
    """Живой запрос к провайдеру, без проверки кэша.
    
    Используется внутри ``fetch_nsfw_content`` после cache-miss,
    а также фоновым прогревателем.
    """
    # ── rule34 ─
    if tag is not None and (
        config.is_femboy_tag(tag)
        or config.is_furry_tag(tag)
        or config.is_anthro_tag(tag)
        or config.is_furfem_tag(tag)
        or config.is_feet_tag(tag)
        or config.is_umamusume_tag(tag)
        or config.is_video_r34_tag(tag)
        or config.is_tentacles_tag(tag)
        or config.is_yuri_tag(tag)
        or config.is_femdom_tag(tag)
    ):
        try:
            return await _log_call(tag, "rule34", _fetch_rule34_photo, tag)
        except Exception:
            logger.error("[%s] rule34 FAILED", tag)
            return (config.FALLBACK_IMAGE_URL, "photo", "error")

    # ── Purrbot (GIF) ─────────────────────────────────
    if tag is not None and config.is_video_tag(tag):
        try:
            endpoint = config.get_video_endpoint(tag)
            url = await _log_call(tag, "purrbot", _fetch_purrbot, endpoint)
            return (url, "video", tag)
        except Exception:
            logger.error("[%s] purrbot FAILED, falling back to cat", tag)
            return (config.FALLBACK_IMAGE_URL, "photo", "error")

    # ── Waifu.im ──────────────────────────────────────
    if tag is not None and config.is_photo_tag(tag):
        try:
            url, actual_tag = await _log_call(tag, "waifu", _fetch_waifu_photo, tag)
            return (url, "photo", tag)
        except Exception:
            logger.error("[%s] waifu FAILED", tag)
            return (config.FALLBACK_IMAGE_URL, "photo", "error")

    # ── Random (50/50) ─────────────────────────────────
    if tag is None:
        if secrets.randbelow(2) == 0:
            url, actual_tag = await _log_call("random", "waifu", _fetch_waifu_photo, None)
            display = actual_tag or "random"
            return (url, "photo", display)
        else:
            ep_list = list(config.VIDEO_ENDPOINTS.values())
            endpoint = secrets.choice(ep_list)
            try:
                url = await _log_call("random", "purrbot", _fetch_purrbot, endpoint)
                return (url, "video", "random_gif")
            except Exception:
                logger.warning("[random] purrbot → waifu fallback")
                url, actual_tag = await _log_call("random", "waifu", _fetch_waifu_photo, None)
                display = actual_tag or "random"
                return (url, "photo", display)

    return (config.FALLBACK_IMAGE_URL, "photo", "error")


# ─────────────────── Основная точка входа ───────────────────


async def fetch_nsfw_content(
    tag: str | None = None,
) -> tuple[str, str, str]:
    """
    Запрашивает контент (фото или GIF).
    
    Сначала проверяет ``_VALIDATED_CACHE`` (HEAD-проверенные ссылки).
    Если кэш пуст — живой запрос к провайдеру, затем валидация URL.
    Если URL битый — повторяет запрос (до 3 попыток).
    При неудаче — fallback на ``FALLBACK_IMAGE_URL``.
    """
    cache_key = tag or "random"

    # ── 1. Кэш ────────────────────────────────────────────
    cached_url = _cache_pop(cache_key)
    if cached_url:
        logger.debug("[cache] HIT key=%s url=%s", cache_key, cached_url[:60])
        _mark_seen(cache_key, cached_url)
        media_type = "video" if cached_url.lower().endswith(".gif") else "photo"
        return (cached_url, media_type, cache_key)

    # ── 2. Живой запрос + валидация (до 3 попыток) ────────
    for attempt in range(1, 4):
        url, media_type, display_tag = await _live_fetch(tag)
        if url == config.FALLBACK_IMAGE_URL:
            # Провайдер сам отдал фолбэк — не валидируем, отдаём как есть
            return (url, media_type, display_tag)

        if await _validate_url(url):
            _cache_push(cache_key, url)
            _mark_seen(cache_key, url)
            return (url, media_type, display_tag)

        logger.warning(
            "[%s] URL не прошёл валидацию (попытка %d/3): %s",
            cache_key, attempt, url[:60],
        )

    # ── 3. Всё сломалось — фолбэк ─────────────────────────
    logger.error("[%s] все 3 попытки живого запроса дали битые URL", cache_key)
    return (config.FALLBACK_IMAGE_URL, "photo", "error")


# ─────────────────── Waifu.im (фото) ───────────────────


async def _fetch_waifu_photo(
    tag: str | None = None,
) -> tuple[str, str | None]:
    """
    Запрашивает NSFW-изображение у Waifu.im API.

    До 2 попыток при дубликате URL.
    Логи: ``[Waifu] <response.status> <items_count>``
    """
    params: dict[str, str] = {"IsNsfw": "True"}
    if tag:
        params["IncludedTags"] = tag

    timeout = aiohttp.ClientTimeout(total=config.API_TIMEOUT_SECONDS)
    cache_key = tag or "random"

    for attempt in range(1, 3):
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
                            "[waifu] HTTP %d (attempt %d/2): %s",
                            response.status, attempt, _trunc(body),
                        )
                        if attempt == 2:
                            return (config.FALLBACK_IMAGE_URL, None)
                        continue

                    data = await response.json()
                    items = data.get("items") or data.get("images", [])
                    logger.debug(
                        "[waifu] HTTP 200, %d items (attempt %d/2)",
                        len(items), attempt,
                    )

                    if not items:
                        logger.error("[waifu] empty response (attempt %d/2)", attempt)
                        if attempt == 2:
                            return (config.FALLBACK_IMAGE_URL, None)
                        continue

                    img = items[0]
                    actual_tag: str | None = None
                    tags = img.get("tags")
                    if tags and isinstance(tags, list) and len(tags) > 0:
                        actual_tag = tags[0].get("slug") or tags[0].get("name")

                    url = img["url"]
                    if _is_recent(cache_key, url):
                        logger.debug(
                            "[waifu] dedup: %s повтор (attempt %d/2)",
                            cache_key, attempt,
                        )
                        if attempt == 2:
                            _mark_seen(cache_key, url)
                            return (url, actual_tag)
                        await asyncio.sleep(0.1)
                        continue

                    _mark_seen(cache_key, url)
                    return (url, actual_tag)

        except asyncio.TimeoutError:
            logger.error("[waifu] timeout %ds (attempt %d/2)", config.API_TIMEOUT_SECONDS, attempt)
            if attempt == 2:
                return (config.FALLBACK_IMAGE_URL, None)
        except aiohttp.ClientError as exc:
            logger.error("[waifu] HTTP error (attempt %d/2): %s", attempt, exc)
            if attempt == 2:
                return (config.FALLBACK_IMAGE_URL, None)
        except (KeyError, IndexError, ValueError) as exc:
            logger.error("[waifu] parse error (attempt %d/2): %s", attempt, exc)
            if attempt == 2:
                return (config.FALLBACK_IMAGE_URL, None)
        except Exception as exc:
            logger.exception("[waifu] unexpected error (attempt %d/2): %s", attempt, exc)
            if attempt == 2:
                return (config.FALLBACK_IMAGE_URL, None)

    return (config.FALLBACK_IMAGE_URL, None)


# ─────────────────── Purrbot API (GIF) ───────────────────


async def _fetch_purrbot(endpoint: str) -> str:
    """
    Запрашивает GIF из Purrbot API.

    До 2 попыток при дубликате URL.
    Логи: ``[purrbot] HTTP <status>``
    """
    url = f"{PURRBOT_API_BASE}/{endpoint.lstrip('/')}"
    timeout = aiohttp.ClientTimeout(total=config.API_TIMEOUT_SECONDS)
    headers = {"User-Agent": "WaifuBot/1.0"}

    for attempt in range(1, 3):
        try:
            async with aiohttp.ClientSession(
                timeout=timeout, headers=headers
            ) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        body = await response.text()
                        logger.error(
                            "[purrbot] HTTP %d (attempt %d/2): %s",
                            response.status, attempt, _trunc(body),
                        )
                        if attempt == 2:
                            raise ValueError(f"Purrbot returned status {response.status}")
                        continue

                    data = await response.json()
                    logger.debug("[purrbot] HTTP 200 (attempt %d/2)", attempt)

                    if data.get("error"):
                        msg = data.get("message", "")
                        logger.error("[purrbot] API error: %s (attempt %d/2)", msg, attempt)
                        if attempt == 2:
                            raise ValueError(f"Purrbot API error: {msg}")
                        continue

                    link = data.get("link")
                    if not link:
                        logger.error("[purrbot] missing 'link' (attempt %d/2)", attempt)
                        if attempt == 2:
                            raise ValueError("Purrbot response missing 'link'")
                        continue

                    if _is_recent("purrbot", link):
                        logger.debug("[purrbot] dedup repeat (attempt %d/2)", attempt)
                        if attempt == 2:
                            _mark_seen("purrbot", link)
                            return link
                        await asyncio.sleep(0.1)
                        continue

                    _mark_seen("purrbot", link)
                    return link

        except ValueError:
            raise
        except Exception as exc:
            logger.error("[purrbot] fetch error (attempt %d/2): %s", attempt, exc)
            if attempt == 2:
                raise ValueError("Purrbot failed after retries") from exc

    raise ValueError("Purrbot failed after retries")


# ─────────────────── e621.net ───────────────────


MAX_E621_RETRIES: int = 3


async def _fetch_e621_photo(bot_tag: str) -> tuple[str, str, str]:
    """
    Запрашивает NSFW-фото через e621.net API (limit=5, random pick).

    Логи: ``[e621] [<bot_tag>] HTTP <status> <posts_count> <valid_count>``
    """
    e621_tags = f"{config.E621_API_TAGS[bot_tag]} order:random"
    params: dict[str, str] = {
        "tags": e621_tags,
        "limit": "5",
    }
    headers = {"User-Agent": config.E621_USER_AGENT}
    timeout = aiohttp.ClientTimeout(total=config.API_TIMEOUT_SECONDS)

    last_error: Exception | None = None

    for attempt in range(1, MAX_E621_RETRIES + 1):
        try:
            async with aiohttp.ClientSession(
                timeout=timeout, headers=headers
            ) as session:
                async with session.get(
                    config.E621_API_URL, params=params
                ) as response:
                    if response.status != 200:
                        body = await response.text()
                        logger.error(
                            "[e621] [%s] HTTP %d (attempt %d/%d): %s",
                            bot_tag, response.status, attempt, MAX_E621_RETRIES, _trunc(body),
                        )
                        raise ValueError(f"e621 status {response.status}")

                    data = await response.json()
                    posts = data.get("posts")
                    posts_count = len(posts) if posts else 0

                    if not posts or not isinstance(posts, list) or posts_count == 0:
                        logger.warning(
                            "[e621] [%s] empty posts (attempt %d/%d)",
                            bot_tag, attempt, MAX_E621_RETRIES,
                        )
                        raise ValueError("e621 вернул пустой список постов")

                    valid = [
                        p for p in posts
                        if p.get("file") and p["file"].get("url")
                    ]
                    valid_count = len(valid)
                    logger.debug(
                        "[e621] [%s] HTTP 200, %d posts, %d valid (attempt %d/%d)",
                        bot_tag, posts_count, valid_count, attempt, MAX_E621_RETRIES,
                    )

                    if not valid:
                        logger.warning(
                            "[e621] [%s] 0 valid posts out of %d (attempt %d/%d)",
                            bot_tag, posts_count, attempt, MAX_E621_RETRIES,
                        )
                        raise ValueError("e621: нет валидных постов")

                    # Пытаемся найти пост, которого ещё не было
                    for pick in range(min(5, len(valid))):
                        chosen = _random.choice(valid)
                        url = chosen["file"]["url"]
                        if not _is_recent(bot_tag, url):
                            _mark_seen(bot_tag, url)
                            return (url, "photo", bot_tag)
                        valid.remove(chosen)

                    # Все были в кэше — отдаём последний
                    url = chosen["file"]["url"]
                    _mark_seen(bot_tag, url)
                    logger.debug("[e621] [%s] all %d posts were recent, returning last", bot_tag, posts_count)
                    return (url, "photo", bot_tag)

        except ValueError as exc:
            last_error = exc
            await asyncio.sleep(0.3)

    logger.error(
        "[e621] [%s] exhausted after %d attempts, last error: %s",
        bot_tag, MAX_E621_RETRIES, last_error,
    )
    raise ValueError(
        f"e621 не вернул валидный пост после {MAX_E621_RETRIES} попыток"
    ) from last_error


async def _fetch_femboy_photo() -> tuple[str, str, str]:
    return await _fetch_e621_photo("femboy")

async def _fetch_furry_photo() -> tuple[str, str, str]:
    return await _fetch_e621_photo("furry")

async def _fetch_anthro_photo() -> tuple[str, str, str]:
    return await _fetch_e621_photo("anthro")

async def _fetch_furfem_photo() -> tuple[str, str, str]:
    return await _fetch_e621_photo("furfem")

async def _fetch_feet_photo(subtag: str) -> tuple[str, str, str]:
    return await _fetch_e621_photo(subtag)


# ─────────────────── Yande.re ───────────────────


async def _fetch_yandere_photo(bot_tag: str) -> tuple[str, str, str]:
    """
    Запрашивает фото через Yande.re API (limit=5, random pick, без ретраев).

    Логи: ``[yande] [<bot_tag>] HTTP <status> <candidates_count>``
    """
    yandere_tags = config.YANDE_RE_TAGS[bot_tag]
    params: dict[str, str] = {
        "tags": f"{yandere_tags} order:random",
        "limit": "5",
    }
    headers = {"User-Agent": "WaifuBot/1.0"}
    timeout = aiohttp.ClientTimeout(total=config.API_TIMEOUT_SECONDS)

    async with aiohttp.ClientSession(
        timeout=timeout, headers=headers
    ) as session:
        async with session.get(
            config.YANDE_RE_API_URL, params=params
        ) as response:
            if response.status != 200:
                body = await response.text()
                logger.error(
                    "[yande] [%s] HTTP %d: %s",
                    bot_tag, response.status, _trunc(body),
                )
                raise ValueError(f"Yande.re status {response.status}")

            data = await response.json()
            if not data or not isinstance(data, list) or len(data) == 0:
                logger.warning("[yande] [%s] empty list", bot_tag)
                raise ValueError("Yande.re вернул пустой список")

            candidates = [p.get("file_url") for p in data if p.get("file_url")]
            logger.debug(
                "[yande] [%s] HTTP 200, %d candidates",
                bot_tag, len(candidates),
            )

            if not candidates:
                logger.warning("[yande] [%s] 0 posts with file_url", bot_tag)
                raise ValueError("Yande.re вернул посты без file_url")

            # Выбираем случайный, проверяем по кэшу повторов (до 3 попыток)
            for pick in range(min(3, len(candidates))):
                url = _random.choice(candidates)
                if not _is_recent(bot_tag, url):
                    _mark_seen(bot_tag, url)
                    return (url, "photo", bot_tag)
                candidates.remove(url)

            # Все были в кэше — отдаём последний
            _mark_seen(bot_tag, url)
            logger.debug("[yande] [%s] all candidates were recent", bot_tag)
            return (url, "photo", bot_tag)


# ─────────────────── Rule34.xxx ───────────────────


async def _fetch_rule34_photo(bot_tag: str) -> tuple[str, str, str]:
    """
    Запрашивает фото/GIF через Rule34.xxx API.

    Стратегия:
    - ``limit=200`` — большой пул кандидатов.
    - Перебирает страницы 1..5 последовательно. Если страницы пустая или
      ошибка — переходит к следующей, а не падает сразу.
    - До 15 попыток выбрать URL, которого нет в кэше ``_RECENT_URLS``.
    - GIF определяется по ``.gif`` → ``media_type="video"`` для спойлера.

    Логи: ``[rule34] [<bot_tag>] pid=<N> HTTP <status> <candidates_count>``
    """
    rule34_tags = config.RULE34_API_TAGS[bot_tag]
    headers = {"User-Agent": "WaifuBot/1.0"}
    timeout = aiohttp.ClientTimeout(total=config.API_TIMEOUT_SECONDS)

    def _media_type(url: str) -> str:
        return "video" if url.lower().endswith(".gif") else "photo"

    last_error: Exception | None = None

    for pid in range(1, 6):
        params: dict[str, str] = {
            "page": "dapi",
            "s": "post",
            "q": "index",
            "json": "1",
            "tags": rule34_tags,
            "limit": "200",
            "pid": str(pid),
            "api_key": config.RULE34_API_KEY or "",
            "user_id": config.RULE34_USER_ID or "",
        }

        try:
            async with aiohttp.ClientSession(
                timeout=timeout, headers=headers
            ) as session:
                async with session.get(
                    config.RULE34_API_URL, params=params
                ) as response:
                    if response.status != 200:
                        body = await response.text()
                        logger.warning(
                            "[rule34] [%s] pid=%d HTTP %d → next page",
                            bot_tag, pid, response.status,
                        )
                        last_error = ValueError(f"Rule34 status {response.status}")
                        continue

                    data = await response.json()
                    if not data or not isinstance(data, list) or len(data) == 0:
                        logger.warning(
                            "[rule34] [%s] pid=%d empty → next page",
                            bot_tag, pid,
                        )
                        last_error = ValueError("Rule34 вернул пустой список")
                        continue

                    candidates = [p.get("file_url") for p in data if p.get("file_url")]
                    # Для тега "video" отбираем только .gif (остальное — статика)
                    if bot_tag == "video":
                        gif_candidates = [u for u in candidates if u.lower().endswith(".gif")]
                        if gif_candidates:
                            logger.debug(
                                "[rule34] [%s] pid=%d %d candidates, %d gif",
                                bot_tag, pid, len(candidates), len(gif_candidates),
                            )
                            candidates = gif_candidates
                        else:
                            logger.debug(
                                "[rule34] [%s] pid=%d %d candidates, 0 gif → next page",
                                bot_tag, pid, len(candidates),
                            )
                            last_error = ValueError("Rule34: нет GIF на странице")
                            continue
                    else:
                        logger.debug(
                            "[rule34] [%s] pid=%d HTTP 200, %d candidates",
                            bot_tag, pid, len(candidates),
                        )

                    if not candidates:
                        logger.warning(
                            "[rule34] [%s] pid=%d 0 file_url → next page",
                            bot_tag, pid,
                        )
                        last_error = ValueError("Rule34 вернул посты без file_url")
                        continue

                    # Выбираем случайный, проверяем по кэшу повторов (до 15)
                    for pick in range(min(15, len(candidates))):
                        url = _random.choice(candidates)
                        if not _is_recent(bot_tag, url):
                            _mark_seen(bot_tag, url)
                            return (url, _media_type(url), bot_tag)
                        candidates.remove(url)

                    # Все были в кэше — отдаём последний
                    _mark_seen(bot_tag, url)
                    logger.debug(
                        "[rule34] [%s] pid=%d all %d candidates recent",
                        bot_tag, pid, len(data),
                    )
                    return (url, _media_type(url), bot_tag)

        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            logger.warning(
                "[rule34] [%s] pid=%d network error: %s → next page",
                bot_tag, pid, exc,
            )
            last_error = exc
            continue

    logger.error("[rule34] [%s] exhausted pages 1-5, last error: %s", bot_tag, last_error)
    raise ValueError(
        f"Rule34 не вернул контент после 5 страниц"
    ) from last_error


# ─────────────────── Фоновый прогреватель кэша ───────────────────


async def _warm_single_tag(tag: str | None) -> None:
    """Одна итерация прогрева для одного тега."""
    cache_key = tag or "random"
    # Сколько ещё можем добавить (до 30)
    current = len(_VALIDATED_CACHE.get(cache_key, []))
    need = 30 - current
    if need <= 0:
        return

    for _ in range(need):
        try:
            url, _media_type, _display = await _live_fetch(tag)
            if url == config.FALLBACK_IMAGE_URL:
                continue
            if await _validate_url(url):
                # Не вызываем _mark_seen — прогреватель не должен
                # влиять на дедупликацию для пользователей
                _cache_push(cache_key, url)
        except Exception:
            pass
        # Небольшая задержка между запросами к одному тегу
        await asyncio.sleep(0.3)


async def _cache_warmer_loop() -> None:
    """
    Фоновый цикл: прогревает ``_VALIDATED_CACHE`` для всех тегов.
    
    Проходит по очереди тегов, заполняет до 30 проверенных URL на тег.
    Полный цикл занимает ~несколько минут (зависит от кол-ва тегов).
    Перезапускается каждые 10 минут.
    """
    logger.info("[warmer] прогреватель кэша запущен")
    while True:
        # Сначала прогреваем "горячие" теги (самые популярные)
        hot_tags = ["random", "maid", "ero", "waifu", "hentai", "ass", "oppai",
                     "milf", "neko_gif", "femboy", "furry", "feet"]
        for tag in hot_tags:
            try:
                await _warm_single_tag(tag)
            except Exception:
                logger.exception("[warmer] ошибка при прогреве %s", tag)
            await asyncio.sleep(1)  # пауза между тегами

        # Потом остальные
        others = sorted(t for t in config.VALID_TAGS if t not in hot_tags)
        for tag in others:
            try:
                await _warm_single_tag(tag)
            except Exception:
                logger.exception("[warmer] ошибка при прогреве %s", tag)
            await asyncio.sleep(1)

        logger.info(
            "[warmer] цикл завершён, всего URL в кэше: %d",
            sum(len(q) for q in _VALIDATED_CACHE.values()),
        )
        await asyncio.sleep(600)  # следующий цикл через 10 минут
