"""
Точка входа: запуск поллинга бота.
"""

import asyncio
import logging
import sys

from .core import bot, dp

# Импорт регистрирует хэндлеры на dp.
from . import handlers  # noqa: F401
from . import database

logger = logging.getLogger(__name__)


async def main() -> None:
    """Запускает поллинг бота."""
    database.init_db()
    logger.info("Бот запущен. Ожидание инлайн-запросов...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")
        sys.exit(0)
