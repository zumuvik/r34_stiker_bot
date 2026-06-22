"""
Точка входа для ``python -m inline_waifu_bot``.
"""

import asyncio
import sys

from .app import main

try:
    asyncio.run(main())
except KeyboardInterrupt:
    sys.exit(0)
