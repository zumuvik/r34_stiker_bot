"""
Построители инлайн-клавиатур.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def build_markup(tag: str | None, owner_id: int) -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру с кнопкой «🔥 Давай ещё!».

    В ``callback_data`` кодируется ID владельца и тег, чтобы при
    нажатии можно было проверить, что кнопку жмёт тот же пользователь.

    Формат callback_data: ``more:{owner_id}:{tag}``.

    Args:
        tag: Текущий тег или ``None``.
        owner_id: Telegram ID пользователя, отправившего сообщение.

    Returns:
        Готовая ``InlineKeyboardMarkup`` с одной кнопкой.
    """
    tag_part = tag if tag else "random"
    data = f"more:{owner_id}:{tag_part}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔥 Давай ещё!",
                    callback_data=data,
                )
            ]
        ]
    )
