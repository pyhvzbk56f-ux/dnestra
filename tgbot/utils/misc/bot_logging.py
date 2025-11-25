# shop/tgbot/utils/misc/bot_logging.py
# # -*- coding: utf-8 -*-
import logging
from logging.handlers import RotatingFileHandler
import colorlog
from tgbot.data.config import PATH_LOGS
import sys
from datetime import datetime

# Принудительно устанавливаем кодировку для вывода в консоль
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# Настройки размеров и количество
log_size_settings = 9*1024*1024 # максимальный размер лог файл файла 9 МБ,
backup_count_settings = 4 # количество логов - 4)

bot_logger = logging.getLogger("bot_logger")  # Создаем именованный логгер

# Формат логирования в файл
log_formatter_file = logging.Formatter(
        "[%(levelname)s] %(asctime)s %(filename)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        )

# Формат логирования в консоль с цветами
log_formatter_console = colorlog.ColoredFormatter(
        "%(log_color)s[%(levelname)-8s]%(reset)s "
        "%(blue)s%(asctime)s%(reset)s "
        "%(green)s%(filename)s%(reset)s:%(lineno)d - "
        "%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
    )

# Обработчик для файла с ротацией (записывает всё, включая INFO)
file_handler = RotatingFileHandler(
    PATH_LOGS, mode="a", encoding="utf-8", maxBytes=log_size_settings, backupCount=backup_count_settings
)
file_handler.setFormatter(log_formatter_file)
file_handler.setLevel(logging.INFO)  # Файл пишет от INFO и выше

# Обработчик для консоли (выводит DEBUG и выше)
console_handler = colorlog.StreamHandler()
console_handler.setFormatter(log_formatter_console)
console_handler.setLevel(logging.DEBUG)  # В консоли DEBUG и выше

# Настройка логгера
bot_logger.setLevel(logging.INFO)  # Логгер принимает всё от INFO
bot_logger.addHandler(file_handler)
bot_logger.addHandler(console_handler)

def setup_logger(name: str, log_file: str):
    """Настраивает индивидуальный логгер для записи в файл и консоль."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Обработчик для файла с ротацией
    log_file_name = f"logs_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
    file_handler = RotatingFileHandler(
        log_file_name, mode="a", encoding="utf-8", maxBytes=log_size_settings, backupCount=backup_count_settings
    )

    file_handler.setFormatter(log_formatter_file)
    file_handler.setLevel(logging.INFO)  # Файл пишет INFO и выше

    # Обработчик для консоли
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter_console)
    console_handler.setLevel(logging.WARNING)  # Консоль только WARNING и выше

    # Добавляем обработчики к логгеру (если их еще нет)
    if not logger.hasHandlers():
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger
