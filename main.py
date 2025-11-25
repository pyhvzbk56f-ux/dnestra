# shop/main.py

import asyncio
import hashlib
import os
import sys
from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from tgbot.data.config import (
    BOT_SCHEDULER,
    BOT_TOKEN,
    PATH_DATABASE,
    BOT_VERSION,
    get_admins, get_operators,
    update_balance_time,
    update_invoice_status_time,
    update_pending_status_time,
)
from tgbot.database import (
    Userx,
    Itemx,
    Positionx,
    Categoryx,
    Subcategoryx,
    Purchasesx,
    Invoicex,
    InvoiceStatus,
    AggregatorTrafficx,
    Settingsx,
)
from tgbot.database.db_helper import create_dbx
from tgbot.middlewares import register_all_middlwares
from tgbot.routers import register_all_routers
from tgbot.services.api_session import AsyncRequestSession
from tgbot.utils.const_functions import gen_id, get_unix
from tgbot.utils.misc.bot_commands import set_commands
from tgbot.utils.misc.bot_logging import bot_logger
from tgbot.utils.misc.bot_models import ARS
from tgbot.utils.misc_functions import (
    autobackup_admin,
    autosettings_unix,
    check_bot_username,
    check_mail,
    check_update,
    startup_notify,
    update_balance,
    update_invoice_status,
    update_pending_status,
    update_profit_day,
    update_profit_month,
    update_profit_week,
    check_unrated_purchases,
    update_actual_ltc_rate_in_db,
    send_data_to_aggregator,
    send_traffic_data_to_aggregator,
    initialize_agg_key,
    check_dispute_queue,
    archive_old_purchase_files,
    update_connection_details_on_aggregator,
)
from tgbot.api_server import setup_and_start_api_server


# Запуск шедулеров
async def scheduler_start(bot: Bot, arSession: ARS, shop_port: int):
    BOT_SCHEDULER.add_job(update_profit_month, trigger="cron", day=1, hour=0, minute=0, second=5)
    BOT_SCHEDULER.add_job(update_profit_week,trigger="cron",day_of_week="mon",hour=0,minute=0,second=10,)
    BOT_SCHEDULER.add_job(update_profit_day, trigger="cron", hour=0, minute=0, second=30, args=(bot,))
    BOT_SCHEDULER.add_job(autobackup_admin, trigger="interval", hours=1, args=(bot,))
    BOT_SCHEDULER.add_job(update_balance,trigger="interval",seconds=update_balance_time,args=[PATH_DATABASE, bot, arSession],) # Если статус succsess > обновление баланса > cтатус finished. # update_balance_time по умолчанию 30.
    BOT_SCHEDULER.add_job(update_pending_status,trigger="interval",seconds=update_pending_status_time,args=[PATH_DATABASE, bot],) # update_pending_status статус счетов pending на reject, {pause_to_reject_status}. update_pending_status_time  умолчанию 60.
    BOT_SCHEDULER.add_job(update_invoice_status, trigger="interval", minutes=3, args=[PATH_DATABASE, bot]) # update_invoice_status Обновление статуса счетов - pending на succsess если успешная транзакция.    # update_invoice_status_time - в секундах
    BOT_SCHEDULER.add_job(check_unrated_purchases,trigger="interval",minutes=60,id="check_unrated_purchases",)
    BOT_SCHEDULER.add_job(update_actual_ltc_rate_in_db, "interval", minutes=5, args=(bot,)) # для обновления курса LTC раз в 5 минут
    BOT_SCHEDULER.add_job(send_data_to_aggregator, trigger="interval", minutes=1, args=(bot, arSession)) # для отправки данных в агрегатор интервал 1 мин
    BOT_SCHEDULER.add_job(send_traffic_data_to_aggregator,trigger="interval",minutes=10,args=(bot, arSession),) # отправка статистики трафика в агрегатор каждые 10 минут
    BOT_SCHEDULER.add_job(check_dispute_queue, trigger="interval", hours=3, args=(bot,)) # напоминания о спорах каждые 3 часа
    BOT_SCHEDULER.add_job(archive_old_purchase_files, trigger="cron", hour=3, minute=30, args=(bot,)) #  ежедневная задача на архивацию старых файлов


# Запуск бота и базовых функций
async def main():
    BOT_SCHEDULER.start()  # Запуск Шедулера
    dp = Dispatcher()  # Образ Диспетчера
    arSession = AsyncRequestSession()  # Пул асинхронной сессии запросов
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode="HTML",
        ),
    )

    # СНАЧАЛА настраиваем и запускаем API сервер, получаем его порт
    api_runner, api_port = await setup_and_start_api_server(bot, arSession)
    if not api_runner:
        bot_logger.critical("Невозможно запустить API-сервер.")

    register_all_middlwares(dp)  # Регистрация всех мидлварей
    register_all_routers(dp)  # Регистрация всех роутеров

    try:
        await autosettings_unix()
        await set_commands(bot)  # Установка команд
        await check_bot_username(bot)  # Проверка юзернейма бота в БД
        await initialize_agg_key(bot)  # Проверка ключа агрегатора в БД
        await startup_notify(bot, arSession)  # Рассылка при запуске бота
        await update_connection_details_on_aggregator(bot, arSession) # Отправка IP и порта
        await send_data_to_aggregator(bot, arSession, force_full_sync=True)
        await scheduler_start(bot, arSession, api_port)
        

        bot_logger.critical(f"BOT WAS STARTED. VERSION: {BOT_VERSION} @{(await bot.get_me()).username}")


        if len(get_admins()) == 0:
            bot_logger.critical(" ENTER ADMIN ID IN settings.ini ")

        await bot.delete_webhook()  # Удаление вебхуков, если они имеются
        await bot.get_updates(offset=-1)  # Сброс пендинг апдейтов

        # Запуск бота (поллинга)
        await dp.start_polling(
            bot,
            arSession=arSession,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        if api_runner:
            await api_runner.cleanup()
        await arSession.close()
        await bot.session.close()


if __name__ == "__main__":
    create_dbx()  # Генерация Базы Данных и Таблиц
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        bot_logger.warning("Bot was stopped")
    finally:
        if sys.platform.startswith("win"):
            os.system("cls")
        else:
            os.system("clear")
