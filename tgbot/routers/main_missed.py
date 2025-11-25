# shop/tgbot/routers/main_missed.py

from aiogram import Router, Bot, F
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message
from tgbot.services.i18n import Translator
from tgbot.utils.const_functions import del_message, ded
from tgbot.utils.misc.bot_models import FSM, ARS
from tgbot.data.config import get_admins, get_operators

router = Router(name=__name__)


#! Колбэк с удалением сообщения
@router.callback_query(F.data == "close_this")
async def main_missed_callback_close(call: CallbackQuery, bot: Bot, state: FSM, arSession: ARS):
    await del_message(call.message)


#! Колбэк с обработкой кнопки
@router.callback_query(F.data == "...")
async def main_missed_callback_answer(call: CallbackQuery, bot: Bot, state: FSM, arSession: ARS):
    await call.answer(cache_time=30)


#! Обработка всех колбэков которые потеряли стейты после перезапуска скрипта
@router.callback_query()
async def main_missed_callback(call: CallbackQuery, i18n: Translator, locale: str):
    await call.answer(i18n.get_text("main_missed.invalid_button", locale), True)


#! ОБРАБОТЧИК МЕДИА ФАЙЛОВ
@router.message(F.photo | F.video, StateFilter(None))
async def main_missed_media(message: Message, i18n: Translator, locale: str):
    """#! Срабатывает, если пользователь отправляет фото или видео, находясь в обычном состоянии."""
    await message.reply(ded(i18n.get_text("main_missed.unknown_media", locale)))


#! Обработка всех неизвестных команд
@router.message()
async def main_missed_message(message: Message, i18n: Translator, locale: str):
    admin_ids = get_admins()
    if message.from_user.id not in admin_ids:
        await message.answer(ded(i18n.get_text("main_missed.unknown_command", locale)))
