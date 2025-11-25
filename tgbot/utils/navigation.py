from aiogram import Bot
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

async def return_to_main_menu(call: CallbackQuery, bot: Bot, state: FSMContext):
    """ Утилитарная функция для возврата на главное меню. Очищает состояние FSM и перенаправляет пользователя на начальный экран.
    """
    # Очищаем все состояния FSM
    await state.clear()
    
    # Получаем меню для старта (предполагается, что есть функция main_start)
    from tgbot.routers.main_start import main_start_handler
    
    # Отправляем сообщение с главным меню
    await call.message.answer("Main menu:", reply_markup=main_start_handler())
    
    # Отвечаем на колбэк, чтобы убрать часы загрузки
    await call.answer()
    
    # Опционально: удаляем предыдущее сообщение с меню
    try:
        await call.message.delete()
    except Exception as e:
        # Логируем ошибку, но продолжаем выполнение
        print(f"Error delete message: {e}") 