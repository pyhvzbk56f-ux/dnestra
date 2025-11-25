#! shop/tgbot/utils/misc/i18n_filters.py

from aiogram.filters import BaseFilter
from aiogram.types import Message
from tgbot.services.i18n import Translator


class I18nText(BaseFilter):
    """#! Фильтр для сравнения текста сообщения с переведенной строкой."""

    def __init__(self, key: str):
        self.key = key

    async def __call__(self, message: Message, i18n: Translator, locale: str) -> bool:
        # aiogram автоматически передаст сюда i18n и locale из middleware
        translated_text = i18n.get_text(self.key, locale)
        return message.text == translated_text
