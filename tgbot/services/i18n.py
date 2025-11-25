# shop/tgbot/services/i18n.py

import json
import os
from typing import Dict
from tgbot.utils.misc.bot_logging import bot_logger

class Translator:
    def __init__(self, locales_dir: str = "tgbot/locales"):
        self.locales_dir = locales_dir
        self.locales = {}

        if not os.path.exists(self.locales_dir):
            bot_logger.critical(f"Директория с переводами не найдена: '{self.locales_dir}'")
            # прервать выполнение:
            raise FileNotFoundError(f"Директория локализации '{self.locales_dir}' не существует. Создайте ее.")

        for lang in os.listdir(self.locales_dir):
            if lang.endswith(".json"):
                lang_code = lang.split(".")[0]
                path = os.path.join(self.locales_dir, lang)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        self.locales[lang_code] = json.load(f)
                except json.JSONDecodeError as e:
                    bot_logger.error(f"Ошибка чтения JSON файла '{path}': {e}")
                except Exception as e:
                    bot_logger.error(f"Не удалось загрузить локаль '{path}': {e}")
    
    def get_text(self, key: str, locale: str = "en", **kwargs) -> str:
        """ Получает текст по ключу для указанной локали. Поддерживает вложенные ключи через точку.        """
        try:
            keys = key.split('.')
            text_template = self.locales[locale]
            for k in keys:
                text_template = text_template[k]
            
            return text_template.format(**kwargs)
        except (KeyError, TypeError):
            # Если ключ не найден в текущей локали, пробуем найти в локали по умолчанию ('en')
            try:
                keys = key.split('.')
                text_template = self.locales["en"]
                for k in keys:
                    text_template = text_template[k]
                return text_template.format(**kwargs)
            except (KeyError, TypeError):
                bot_logger.warning(f"Key to translate '{key}' не найден ни в локали '{locale}', ни в 'en'")
                return key # Возвращаем ключ, чтобы было видно ошибку


# Создаем один экземпляр, который будет использоваться во всем приложении
i18n = Translator()