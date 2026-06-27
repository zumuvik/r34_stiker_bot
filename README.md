# Waifu Bot — Inline NSFW Telegram Bot (18+)

Telegram-бот, работающий исключительно в **инлайн-режиме**. Пользователь вводит
`@bot_username <тег>` в любом чате и получает NSFW-контент под спойлером.

Поддерживает **фото** (Waifu.im), **анимации/GIF** (Purrbot) и
**специализированные теги** через каскад провайдеров **e621.net → Yande.re →
Rule34.xxx** (femboy, furry, feet, umamusume и другие). Встроена **система
статистики спермы** с лидербордом и люто-беспощадными фразами.

Контент кэшируется в **SQLite-пуле** (10 проверенных URL на тег) для снижения
нагрузки на API и ускорения ответа. Фоновый warmer наполняет пул при старте и
каждые 10 минут.

---

## Содержание

- [Как это работает](#как-это-работает)
- [Архитектура](#архитектура)
- [Теги и провайдеры](#теги-и-провайдеры)
- [Установка и запуск](#установка-и-запуск)
- [Конфигурация](#конфигурация)
- [Система статистики](#система-статистики)
- [Разработка](#разработка)
- [Файловая структура](#файловая-структура)

---

## Как это работает

```
Пользователь                  Telegram                   Бот
    │                           │                        │
    ├─ @bot_username maid ─────►│                        │
    │                           ├── inline_query ───────►│
    │                           │                        ├─ возвращает Article
    │                           │                        │  с кнопкой 18+
    │◄──── Article + кнопка ────┤                        │
    │                           │                        │
    ├── нажимает «Мне есть 18»─►│                        │
    │                           ├── callback_query ─────►│
    │                           │                        ├─ fetch_nsfw_content()
    │                           │                        ├─ Waifu.im / Rule34 / Purrbot
    │                           │                        ├─ генер. статистику
    │◄── NSFW под спойлером ────┤                        │
    │                           │                        │
    ├── нажимает «Давай ещё!»──►│                        │
    │                           ├── callback_query ─────►│
    │                           │                        ├─ fetch_nsfw_content()
    │◄── новый NSFW ────────────┤                        │
```

**Безопасность:**
- NSFW-контент никогда не отправляется первым сообщением.
- Сначала показывается **текстовая заглушка** с кнопкой подтверждения 18+.
- После верификации контент приходит **под спойлером** (blur).
- Кнопку может нажать **только создатель** инлайн-сообщения.
- Кд между нажатиями — **3 секунды**.

---

## Архитектура

```
inline_waifu_bot/
├── __init__.py     # Экспорт, логирование, порядок импорта
├── __main__.py     # Точка входа: python -m inline_waifu_bot
├── app.py          # Запуск поллинга, инициализация БД
├── core.py         # Bot + Dispatcher (aiogram)
├── config.py       # .env, константы, теги, маппинги
├── api.py          # Провайдеры контента + SQLite-пул + fallback-каскад
├── database.py     # SQLite: статистика, лидерборд, content_pool
├── handlers.py     # aiogram-хэндлеры (inline, callback, /start)
└── keyboard.py     # Inline-клавиатуры
```

### Поток данных

```
handlers.py           api.py                         Провайдеры
    │                    │                              │
    ├─ verify_18 ───────►│                              │
    │                    ├─ fetch_nsfw_content()        │
    │                    │  ├─ 1. pop_pool_item()  ────►│ SQLite content_pool
    │                    │  │   hit → serve + replenish │
    │                    │  │   miss → live fetch       │
    │                    │  │                            │
    │                    │  ├─ 2. _live_fetch()         │
    │                    │  │                           │
    │                    │  │  e621-группа:             │
    │                    │  │   femboy/furry/feet/...   │
    │                    │  │   ├─ e621.net (primary)   │
    │                    │  │   ├─ Yande.re (intermed.) │
    │                    │  │   └─ Rule34.xxx (final)   │
    │                    │  │                           │
    │                    │  │  waifu.im (фото):         │
    │                    │  │   maid/ero/hentai/...     │
    │                    │  │                           │
    │                    │  │  purrbot (GIF):           │
    │                    │  │   neko_gif / nsfw_gif     │
    │                    │  │   (nsfw_gif — случайный   │
    │                    │  │    из 6 категорий)        │
    │                    │  │                           │
    │                    │  │  random (tag=None):       │
    │                    │  │   50% waifu.im / 50% GIF  │
    │                    │  │                           │
    │                    │  ├─ 3. HEAD-валидация URL    │
    │                    │  │   (User-Agent для e621)   │
    │                    │  │                           │
    │◄── (url, type, tag)┤  └─ fallback → http.cat/500 │
    │                    │                              │
    ├─ _build_media()    │                              │
    │  └─ URL .gif? ────►│ InputMediaAnimation         │
    │     .mp4 ─────────►│ InputMediaVideo             │
    │     иначе ────────►│ InputMediaPhoto             │
    │                    │   has_spoiler=True           │
    │                    │                              │
    └─ edit_message_media()                             │
```

---

## Теги и провайдеры

| Теги | Провайдер (каскад) | Тип контента |
|---|---|---|---|
| `waifu`, `maid`, `ero`, `hentai`, `ass`, `oppai`, `milf`, `oral`, `paizuri`, `ecchi`, `selfies`, `uniform`, `marin-kitagawa`, `mori-calliope`, `raiden-shogun` | **Waifu.im** | Фото (JPG/PNG) |
| `neko_gif` | **Purrbot API** `neko/gif` | GIF |
| `nsfw_gif` | **Purrbot API** (случайный из 6 категорий: anal, blowjob, cum, fuck, pussy, threesome) | GIF |
| `femboy`, `feet`, `heels`, `umamusume` | **e621.net → Yande.re → Rule34.xxx** | Фото + GIF |
| `furry`, `anthro`, `furfem`, `video`, `tentacles`, `yuri`, `femdom` | **e621.net → Rule34.xxx** | Фото + GIF |
| `random` | 50/50 Waifu.im / Purrbot | Фото или GIF |

### Детали провайдеров

#### Waifu.im
- API v7, эндпоинт: `https://api.waifu.im/images`
- Параметры: `IsNsfw=True`, `IncludedTags=<тег>`
- Ответ: `{ items: [{ url, tags }] }`
- До 2 попыток при дубликате URL

#### e621.net (primary)
- API: `https://e621.net/posts.json`
- `limit=5`, `order:random`, до 3 ретраев
- `.webm` исключается; для тега `video` отбираются только `.gif`
- Требует `User-Agent` (ToS e621)

#### Yande.re (intermediate fallback)
- API: `https://yande.re/post.json`
- `limit=5`, `order:random`, без ретраев
- Используется для `feet`, `heels`, `femboy`, `umamusume` при отказе e621

#### Rule34.xxx (final fallback)
- API: `https://api.rule34.xxx/index.php?page=dapi&s=post&q=index`
- Перебирает страницы 1–5, `limit=200`, до 15 попыток избежать дубликата
- GIF → `media_type="video"` для спойлера через InputMediaAnimation

#### Purrbot API (GIF)
- Базовый эндпоинт: `https://api.purrbot.site`
- `neko_gif` → `v2/img/nsfw/neko/gif`
- `nsfw_gif` → случайный из 6 категорий: `anal`, `blowjob`, `cum`, `fuck`, `pussy`, `threesome`
- До 2 попыток при дубликате

### SQLite-пул (content_pool)

Вместо in-memory кэша `_VALIDATED_CACHE` бот использует таблицу `content_pool`
в SQLite. Для каждого тега держится до `POOL_SIZE=10` проверенных URL.

**Жизненный цикл:**
1. **fetch_nsfw_content** сначала пытается `pop_pool_item()` из БД
2. **Cache hit** → сразу отдаём + фоновый `_replenish_pool_item`
3. **Cache miss** → `_live_fetch()` до 3 попыток с HEAD-валидацией
4. **Warmer** (`_cache_warmer_loop`) заполняет пул при старте и каждые 10 минут
5. Если все провайдеры отказали → `http.cat/500`

### Дедупликация URL

Два уровня защиты от повторов:
1. **In-memory `_RECENT_URLS`** — `deque(maxlen=30)` на тег, отсекает недавно
   показанные URL при выборе кандидата внутри провайдера.
2. **SQLite `content_pool`** — при cache-hit URL атомарно удаляется (FIFO),
   поэтому повтор в рамках одного цикла warmer'а невозможен.

Если все кандидаты уже были показаны — возвращается последний (повтор
допустим только в крайнем случае).

### Fallback-каскад

При отказе провайдера логгируется цепочка через `contextvars`:

```
FALLBACK CASCADE: e621: ValueError: e621 status 429 →
  yande.re: ValueError: Yande.re status 503 →
  rule34: ValueError: exhausted
```

Пользователь видит caption `⚠️ API Провайдеров недоступны (Включен Fallback)`
вместо обычного `NSFW Anime`. При HTTP-ошибках валидации CDN (403/429)
логируется WARNING с кодом ответа.

---

## Установка и запуск

```bash
# 1. Клонировать репозиторий
git clone <repo>
cd r34_stiker_bot

# 2. Создать виртуальное окружение
python -m venv .venv
source .venv/bin/activate  # Linux
# .venv\Scripts\activate   # Windows

# 3. Установить зависимости
pip install aiogram aiohttp

# 4. Создать .env с токеном бота
cat > .env << EOF
BOT_TOKEN=123456:ABCdef...
RULE34_API_KEY=...
RULE34_USER_ID=...
EOF

# 5. Запустить
python -m inline_waifu_bot
```

**Минимальные требования:** Python 3.10+ (используется `str | None` синтаксис).

---

## Конфигурация

### `.env`

| Переменная | Обязательно | Описание |
|---|---|---|
| `BOT_TOKEN` | ✅ | Токен Telegram-бота от @BotFather |
| `RULE34_API_KEY` | ❌* | API-ключ Rule34.xxx |
| `RULE34_USER_ID` | ❌* | User ID Rule34.xxx |

\* Обязательно, если используются теги femboy/furry/feet и т.д.
Для получения: зарегистрироваться на rule34.xxx → Account Options →
Generate New Key.

### Основные константы (`config.py`)

| Константа | По умолчанию | Описание |
|---|---|---|
| `API_TIMEOUT_SECONDS` | `5` | Таймаут HTTP-запроса ко всем API |
| `BUTTON_COOLDOWN` | `3` | Кд между нажатиями «Давай ещё!» (сек) |
| `FALLBACK_IMAGE_URL` | `https://http.cat/500` | Заглушка при ошибках всех провайдеров |

### Теги-фильтры для Rule34.xxx

В `config.RULE34_API_TAGS` определяются поисковые запросы для каждого тега.
Используются `-loli`, `-shota`, `-male`, `-anthro`, `-furry` и другие
исключающие теги для фильтрации нежелательного контента.

---

## Система статистики

### База данных (SQLite, WAL-режим)

Файл: `bot_stats.db` (в корне проекта, в `.gitignore`).

**Таблицы:**
- `user_stats` — `user_id`, `username`, `total_sperm`
- `user_tag_stats` — `user_id`, `tag`, `count`

### Механика спермы

При каждом показе контента (верификация или «Давай ещё!») генерируется
случайное изменение по **тирам с весами**:

| Исход | Дельта | Вес | Шанс |
|---|---|---|---|---|
| Обычный плюс | +10 мл | 30 | 30% |
| Хороший плюс | +25 мл | 28 | 28% |
| Большой плюс | +50 мл | 15 | 15% |
| Огромный плюс | +100 мл | 10 | 10% |
| **Джекпот** | **+500 мл** | **1** | **1%** |
| Мелкий минус | -10 мл | 8 | 8% |
| Средний минус | -25 мл | 6 | 6% |
| **Капут** | **-200 мл** | **2** | **2%** |

- Пол в нуле **УБРАН** — баланс может быть отрицательным.
- В сумме ~80% положительных, ~20% отрицательных исходов.

### Команды

| Инлайн-запрос | Результат |
|---|---|
| `@bot_username` | Лидерборд + список всех тегов |
| `@bot_username top` | Только лидерборд |
| `@bot_username stats` | Только личная статистика |

### Фразы

Положительные: «Вы подододрочель», «У вас ведро шпермы», «Вы выдрочили яца»,
«Вы отдрочили за весь чат», «Вы подорожник».

Отрицательные: «У тебя сегодня отсох хуец», «У вас отвалился хуй»,
«Ваш член попал в капкан», «Ваши яйца отрофировались».

---

## Разработка

### Запуск тестов

```bash
.venv/bin/pytest test_inline_waifu_bot.py -v
```

Тесты используют:
- In-memory SQLite (не трогают `bot_stats.db`)
- Mock `aiohttp.ClientSession` (не ходят в реальные API)
- Mock `bot.edit_message_media` (не шлют в Telegram)
- Патч `update_user_sperm` (не пишут в БД)

### Добавление нового тега

1. В `config.py`: добавить в соответствующее `frozenset`, в `VALID_TAGS`,
   `TAG_LABELS` и `TAG_ACHIEVEMENTS`.
2. В `config.py`: добавить маппинг в `RULE34_API_TAGS`, `E621_API_TAGS`
   и опционально в `YANDE_RE_TAGS`.
3. В `api.py`: если тег попадает под существующую группу (`is_*_tag()`) —
   он уже обрабатывается каскадом. Если группа новая — добавить `is_*_tag()`
   и ветку в `_live_fetch`.
4. В `config.py`: обновить хелпер `is_*_tag()` для новой группы.

---

## Файловая структура

```
r34_stiker_bot/
├── .env                        # Токен бота, API-ключи (в gitignore)
├── .gitignore
├── Makefile                    # deploy/restart/logs/status
├── README.md
├── bot.log                     # Лог-файл (в gitignore)
├── bot_stats.db                # SQLite (в gitignore)
├── test_inline_waifu_bot.py    # Pytest-тесты (~1780 строк)
├── inline_waifu_bot/
│   ├── __init__.py             # Экспорт, инициализация
│   ├── __main__.py             # python -m entry point
│   ├── app.py                  # Запуск поллинга, warmer
│   ├── core.py                 # Bot + Dispatcher
│   ├── config.py               # .env, теги, маппинги (350 строк)
│   ├── api.py                  # Провайдеры + SQLite-пул + каскад (870 строк)
│   ├── database.py             # SQLite: stats, leaderboard, content_pool (200 строк)
│   ├── handlers.py             # aiogram handlers (580 строк)
│   └── keyboard.py             # Inline-кнопки (35 строк)
└── venv/ / .venv/              # Виртуальное окружение
```

---

## Поведение при ошибках

| Сценарий | Поведение |
|---|---|
| API вернул 500 | Лог + переход к следующему провайдеру в каскаде |
| API вернул пустой массив | Лог + переход к следующему провайдеру |
| Таймаут (>5с) | 2-3 попытки внутри провайдера, затем след. провайдер |
| Все провайдеры отказали | `http.cat/500` + caption `⚠️ API Провайдеров недоступны` |
| CDN блокирует HEAD-запрос (403) | Лог WARNING с кодом, след. попытка live fetch |
| Telegram rejected media | Fallback на `InputMediaPhoto(http.cat/500)` |
| Дубликат URL | Повтор допустим при исчерпании всех кандидатов |
| Чужой нажал кнопку | Alert «Это сообщение создал другой пользователь» |
| Кд не прошёл | Alert «Подожди N с» |
