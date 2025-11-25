from aiogram import Dispatcher, F

from tgbot.routers import main_errors, main_start, main_missed
from tgbot.routers.admin import (
    admin_menu,
    admin_functions,
    admin_products,
    admin_settings,
    admin_disputes,
    admin_authorization,
)

from tgbot.routers.user import (
    user_menu,
    user_transactions,
    user_products,
    user_disputes,
)

from tgbot.utils.misc.bot_filters import IsAdmin, IsAdminOrOperator 


# Регистрация всех роутеров
def register_all_routers(dp: Dispatcher):
    """Регистрирует все роутеры в диспетчере."""
    # Подключение фильтров
    dp.message.filter(F.chat.type == "private")  # Работа бота только в личке - сообщения
    dp.callback_query.filter(F.message.chat.type == "private")  # Работа бота только в личке - колбэки
    dp.edited_message.filter(F.chat.type == "private")  # Работа бота только в личке - редактированные сообщения
    dp.channel_post.filter(F.chat.type == "private")  # Работа бота только в личке - посты в каналах
    

    # Роутеры, доступные и админам, и операторам
    admin_menu.router.message.filter(IsAdminOrOperator())
    admin_menu.router.callback_query.filter(IsAdminOrOperator())
    admin_functions.router.message.filter(IsAdminOrOperator())
    admin_functions.router.callback_query.filter(IsAdminOrOperator())
    admin_settings.router.message.filter(IsAdminOrOperator())
    admin_settings.router.callback_query.filter(IsAdminOrOperator())
    admin_disputes.router.message.filter(IsAdminOrOperator())
    admin_disputes.router.callback_query.filter(IsAdminOrOperator())
    admin_authorization.router.message.filter(IsAdminOrOperator())
    admin_authorization.router.callback_query.filter(IsAdminOrOperator())
    

    # Роутер, доступный только админам
    admin_products.router.message.filter(IsAdmin())
    admin_products.router.callback_query.filter(IsAdmin())

    # Добавление фильтров типа чата к админским роутерам
    admin_menu.router.message.filter(F.chat.type == "private")
    admin_menu.router.callback_query.filter(F.message.chat.type == "private")
    admin_functions.router.message.filter(F.chat.type == "private")
    admin_functions.router.callback_query.filter(F.message.chat.type == "private")
    admin_settings.router.message.filter(F.chat.type == "private")
    admin_settings.router.callback_query.filter(F.message.chat.type == "private")
    admin_disputes.router.message.filter(F.chat.type == "private")
    admin_disputes.router.callback_query.filter(F.message.chat.type == "private")
    admin_authorization.router.message.filter(F.chat.type == "private")
    admin_authorization.router.callback_query.filter(F.message.chat.type == "private")
    admin_products.router.message.filter(F.chat.type == "private")
    admin_products.router.callback_query.filter(F.message.chat.type == "private")


    # Добавление фильтров типа чата к основным роутерам
    main_errors.router.message.filter(F.chat.type == "private")
    main_errors.router.callback_query.filter(F.message.chat.type == "private")
    main_start.router.message.filter(F.chat.type == "private")
    main_start.router.callback_query.filter(F.message.chat.type == "private")
    main_missed.router.message.filter(F.chat.type == "private")
    main_missed.router.callback_query.filter(F.message.chat.type == "private")

    # Подключение обязательных роутеров
    dp.include_router(main_errors.router)  # Роутер ошибки
    dp.include_router(main_start.router)  # Роутер основных команд

    # Подключение роутеров для админов и операторов
    dp.include_router(admin_functions.router)  # Админ операторы 
    dp.include_router(admin_settings.router) # Админ операторы 
    dp.include_router(admin_products.router)  # Только для админов
    dp.include_router(admin_disputes.router) # Админ операторы
    dp.include_router(admin_authorization.router)  # Админ операторы 
    dp.include_router(admin_menu.router)  # Админ операторы 

    # Добавление фильтров типа чата к пользовательским роутерам
    user_menu.router.message.filter(F.chat.type == "private")
    user_menu.router.callback_query.filter(F.message.chat.type == "private")
    user_products.router.message.filter(F.chat.type == "private")
    user_products.router.callback_query.filter(F.message.chat.type == "private")
    user_disputes.router.message.filter(F.chat.type == "private")
    user_disputes.router.callback_query.filter(F.message.chat.type == "private")
    user_transactions.router.message.filter(F.chat.type == "private")
    user_transactions.router.callback_query.filter(F.message.chat.type == "private")

    dp.include_router(user_menu.router)  # Юзер роутер
    dp.include_router(user_transactions.router)  # Юзер роутер
    dp.include_router(user_products.router)  # Юзер роутер
    dp.include_router(user_disputes.router) # Юзер роутер

    # Подключение обязательных роутеров
    dp.include_router(main_missed.router)  # Роутер пропущенных апдейтов
