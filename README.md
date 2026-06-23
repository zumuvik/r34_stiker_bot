# Waifu Bot — Inline NSFW Telegram Bot (18+)

Telegram-бот, работающий исключительно в **инлайн-режиме**. Пользователь вводит
`@bot_username <тег>` в любом чате и получает NSFW-контент под спойлером.

Поддерживает **фото** (Waifu.im), **анимации/GIF** (Purrbot) и
**специализированные теги** через **Rule34.xxx** (femboy, furry, feet, umamusume
и другие). Встроена **система статистики спермы** с лидербордом и
люто-беспощадными фразами.

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
├── api.py          # Провайдеры контента (Waifu.im, Rule34, Purrbot)
├── database.py     # SQLite: статистика, лидерборд
├── handlers.py     # aiogram-хэндлеры (inline, callback, /start)
└── keyboard.py     # Inline-клавиатуры
```

### Поток данных

```
handlers.py           api.py                   Провайдеры
    │                    │                        │
    ├─ verify_18 ───────►│                        │
    │                    ├─ fetch_nsfw_content()  │
    │                    │  ├─ is_femboy_tag? ───►│ Rule34.xxx
    │                    │  ├─ is_furry_tag?  ───►│ Rule34.xxx
    │                    │  ├─ is_feet_tag?   ───►│ Rule34.xxx
    │                    │  ├─ is_video_tag?  ───►│ Purrbot
    │                    │  ├─ is_photo_tag?  ───►│ Waifu.im
    │                    │  └─ tag=None ─────────►│ 50/50 Waifu/Purrbot
    │                    │                        │
    │◄── (url, type, tag)┤                        │
    │                    │                        │
    ├─ _build_media()    │                        │
    │  └─ URL .gif? ────►│ InputMediaVideo        │
    │     иначе ────────►│ InputMediaPhoto        │
    │                    │   has_spoiler=True      │
    │                    │                        │
    └─ edit_message_media()                       │
```

---

## Теги и провайдеры

| Теги | Провайдер | Тип контента | Пример URL |
|---|---|---|---|
| `waifu`, `maid`, `ero`, `hentai`, `ass`, `oppai`, `milf`, `oral`, `paizuri`, `ecchi`, `selfies`, `uniform`, `marin-kitagawa`, `mori-calliope`, `raiden-shogun` | **Waifu.im** | Фото (JPG/PNG) | `https://cdn.waifu.im/...` |
| `neko_gif`, `nsfw_gif` | **Purrbot API** | GIF | `https://cdn.purrbot.site/...` |
| `femboy` | **Rule34.xxx** | Фото + GIF | `https://img.rule34.xxx/...` |
| `furry` | **Rule34.xxx** | Фото + GIF | `https://img.rule34.xxx/...` |
| `anthro` | **Rule34.xxx** | Фото + GIF | `https://img.rule34.xxx/...` |
| `furfem` | **Rule34.xxx** | Фото + GIF | `https://img.rule34.xxx/...` |
| `feet` | **Rule34.xxx** | Фото + GIF | `https://img.rule34.xxx/...` |
| `heels` | **Rule34.xxx** | Фото + GIF | `https://img.rule34.xxx/...` |
| `umamusume` | **Rule34.xxx** | Фото + GIF | `https://img.rule34.xxx/...` |
| `random` | 50/50 Waifu.im / Purrbot | Фото или GIF | — |

### Детали провайдеров

#### Waifu.im
- API v7, эндпоинт: `https://api.waifu.im/images`
- Параметры: `IsNsfw=True`, `IncludedTags=<тег>`
- Ответ: `{ items: [{ url, tags }] }`
- До 2 попыток при дубликате URL

#### Rule34.xxx
- API: `https://api.rule34.xxx/index.php?page=dapi&s=post&q=index`
- Требует `api_key` + `user_id` (с 2025 года)
- Параметры: `json=1`, `tags=...`, `limit=100`, `pid=<random 1-50>`
- Ответ: `[{ file_url, tags, rating, id }]`
- GIF определяется по расширению `.gif` — возвращается `media_type="video"`
- До 15 попыток вытащить неповторяющийся URL из 100 кандидатов

#### Purrbot API
- API: `https://api.purrbot.site/v2/img/nsfw/neko/gif`
- Ответ: `{ link, error, response-code }`
- До 2 попыток при дубликате

### Защита от повторов

В `api.py` глобальный кэш `_RECENT_URLS` хранит последние 30 URL для каждого
тега. Функции выбора случайного кандидата проверяют кэш и пропускают уже
показанные URL. При исчерпании пула возвращается последний кандидат (повтор
допустим только в крайнем случае).

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
|---|---|---|---|
| Обычный плюс | +10 мл | 30 | 30% |
| Хороший плюс | +25 мл | 30 | 30% |
| Большой плюс | +50 мл | 15 | 15% |
| **Джекпот** | **+500 мл** | **5** | **5%** |
| Мелкий минус | -10 мл | 12 | 12% |
| Большой минус | -25 мл | 8 | 8% |

- Пол в нуле — уйти в минус нельзя.
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

1. В `config.py`: добавить в соответствующее `frozenset` и в `VALID_TAGS`
2. В `config.py`: добавить запись в `RULE34_API_TAGS` (если тег идёт через rule34)
3. В `fetch_nsfw_content` (`api.py`): если тег попадает под существующую
   категорию — он уже обрабатывается. Если категория новая — добавить `is_*_tag()`
   и ветку с провайдером.

---

## Файловая структура

```
r34_stiker_bot/
├── .env                        # Токен бота, API-ключи (в gitignore)
├── .gitignore
├── README.md
├── bot.log                     # Лог-файл (в gitignore)
├── bot_stats.db                # SQLite (в gitignore)
├── test_inline_waifu_bot.py    # Pytest-тесты (1247 строк)
├── inline_waifu_bot/
│   ├── __init__.py             # Экспорт, инициализация
│   ├── __main__.py             # python -m entry point
│   ├── app.py                  # Запуск поллинга
│   ├── core.py                 # Bot + Dispatcher
│   ├── config.py               # .env, теги, маппинги (248 строк)
│   ├── api.py                  # Провайдеры: Waifu.im, Rule34, Purrbot (546 строк)
│   ├── database.py             # SQLite: stats, leaderboard (151 строка)
│   ├── handlers.py             # aiogram handlers: inline, verify, more, start (519 строк)
│   └── keyboard.py             # Inline-кнопки (35 строк)
└── venv/ / .venv/              # Виртуальное окружение
```

---

## Поведение при ошибках

| Сценарий | Поведение |
|---|---|
| API вернул 500 | Лог + fallback на `http.cat/500` |
| API вернул пустой массив | Лог + fallback на `http.cat/500` |
| Таймаут (>5с) | 2 попытки, после — fallback |
| Сетевой разрыв | 2 попытки, после — fallback |
| GIF не прошёл как `InputMediaVideo` | Fallback на `InputMediaPhoto(http.cat/500)` |
| Дубликат URL (не влез в кэш) | Повтор допустим при исчерпании 15 попыток |
| Мусор в callback_data | Alert «Ошибка данных», отказ |
| Чужой нажал кнопку | Alert «Это сообщение создал другой пользователь» |
| Кд не прошёл | Alert «Подожди N с» |
