"""
Построители инлайн-клавиатур.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def build_markup(tag: str | None, owner_id: int) -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру с кнопкой «🔥 Давай ещё!».

    В ``callback_data`` кодируется тег и ID владельца сообщения,
    чтобы при нажатии можно было проверить, что кнопку жмёт тот же
    пользователь.

    Формат callback_data:
        - ``more_random_{owner_id}`` — если тег не указан
        - ``more_{tag}_{owner_id}`` — если тег указан

    Args:
        tag: Текущий тег или ``None``.
        owner_id: Telegram ID пользователя, отправившего сообщение.

    Returns:
        Готовая ``InlineKeyboardMarkup`` с одной кнопкой.
    """
    tag_part = f"more_{tag}" if tag else "more_random"
    data = f"{tag_part}_{owner_id}"
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
