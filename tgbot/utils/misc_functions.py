# shop/tgbot/utils/misc_functions.py

import asyncio
import json
import os
import uuid
import shutil
import sqlite3
import aiohttp 
import html
from io import BytesIO
from PIL import Image
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Union
from aiohttp import ClientSession
from aiogram import Bot
from aiogram.types import CallbackQuery, FSInputFile, Message, Document, PhotoSize
from aiogram.utils.keyboard import InlineKeyboardBuilder


from tgbot.data.config import (
    BACKUP_DIR,
    PATH_DATABASE,
    HTX_access_key,
    HTX_secret_key,
    get_admins, get_operators,
    BASE_DIR,
)
from tgbot.database import (
    AggregatorTrafficx,
    CategoryModel,
    Categoryx,
    Disputex,
    DisputeModel,
    Invoice,
    ItemModel,
    Itemx,
    PositionModel,
    Positionx,
    Purchasesx,
    PurchasesModel,
    Settingsx,
    Subcategoryx,
    UserModel,
    Userx,
)
from tgbot.database.db_helper import dict_factory
from tgbot.services.i18n import i18n, Translator
from tgbot.services.api_htx import get_htx_deposits, get_htx_ltc_to_usd_rate
from tgbot.services.api_rate_coingecko import get_ltc_to_usd_rate
from tgbot.services.api_tatum import get_ltc_transactions
from tgbot.services.api_tronscan import get_usdt_trc20_transactions
from tgbot.utils.const_functions import (
    convert_date,
    ded,
    get_date,
    get_unix,
    send_admins,
)
from tgbot.utils.misc.bot_logging import bot_logger
from tgbot.utils.misc.bot_models import ARS, FSM
from tgbot.utils.text_functions import get_statistics
from urllib.parse import urlencode

# API-ключ и секрет
API_KEY = HTX_access_key
API_SECRET = HTX_secret_key
BASE_URL = "https://api.htx.com"






# Безопасное деление текста
def split_message_safely(text: str, chunk_size: int = 4096) -> list[str]:
    """
    #! Splits long text into chunks without breaking HTML tags.
    #! Splitting occurs at the last newline character before the chunk_size limit.
    """
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    while text:
        if len(text) <= chunk_size:
            chunks.append(text)
            break
        # Ищем последний перенос строки перед лимитом
        split_pos = text.rfind("\n", 0, chunk_size)
        # Если переноса строки не найдено, режем по лимиту (крайний случай)
        if split_pos == -1:
            split_pos = chunk_size
        chunks.append(text[:split_pos])
        text = text[
            split_pos:
        ].lstrip()  # Удаляем лишние пробелы/переносы в начале следующего куска
    return chunks


#! напоминание о спорах
async def check_dispute_queue(bot: Bot):
    """#! Checks the dispute queue and sends a reminder to administrators."""
    now = get_unix()
    h12, h24 = 12 * 3600, 24 * 3600
    open_disputes = Disputex.gets(status="open")
    if not open_disputes:
        return

    overdue_24h = sum(1 for d in open_disputes if now - d.created_at > h24)
    important_12h = sum(1 for d in open_disputes if h12 < now - d.created_at <= h24)
    regular_disputes = sum(1 for d in open_disputes if now - d.created_at <= h12)

    locale = "en"
    text = i18n.get_text("misc_functions.dispute_reminder_title", locale)
    if overdue_24h > 0:
        text += i18n.get_text(
            "misc_functions.dispute_reminder_overdue", locale, count=overdue_24h
        )
    if important_12h > 0:
        text += i18n.get_text(
            "misc_functions.dispute_reminder_important", locale, count=important_12h
        )
    if regular_disputes > 0:
        text += i18n.get_text(
            "misc_functions.dispute_reminder_new", locale, count=regular_disputes
        )

    builder = InlineKeyboardBuilder()
    builder.button(
        text=i18n.get_text("misc_functions.dispute_reminder_button", locale),
        callback_data="admin:view_disputes",
    )
    await send_admins(bot, text, keyboard=builder.as_markup(), not_me=0)


#! Функция проверки ключа агрегатора 
async def initialize_agg_key(bot: Bot):
    """ #! Checks if the aggregator key is set. """
    get_settings = Settingsx.get()
    if get_settings.send_to_aggregator != "True":
        return
    if get_settings.agg_key is None or get_settings.agg_key == "None":
        bot_logger.warning("Aggregator key is not set. Data sending to the aggregator is disabled until the key is configured in the settings.")






#! функция для отправки данных по частям
async def _send_chunked_data(
    session: ClientSession,
    url: str,
    headers: dict,
    data: list,
    entity_name: str,
    #shop_port: int,
    chunk_size: int = 1000,
    is_full_sync: bool = True,
    is_first_call_in_session: bool = False,
):
    """#! Sends a large list of data in chunks."""
    if not data:
        return


    for i, chunk_start in enumerate(range(0, len(data), chunk_size)):
        chunk = data[chunk_start : chunk_start + chunk_size]

        params = {}
        # Устанавливаем append=false только для самого первого чанка всей сессии
        if i == 0 and is_first_call_in_session:
            params['append'] = 'false'
        else:
            params['append'] = 'true'

        # Флаг полной синхронизации также отправляем только с первым чанком
        if is_full_sync and i == 0 and is_first_call_in_session:
            params['full_sync'] = 'true'

        query_string = urlencode(params)
        request_url = f"{url}?{query_string}"


        # request_url = url
        # if i > 0:
        #     request_url += "?append=true"

        # Проверяем и русскую, и английскую версию названия сущности. Код устойчив к изменениям в файлах локализации.
        if entity_name in ("Товары", "Items", "Позиции", "Positions"):
            payload = {"items": chunk}
        else:
            payload = chunk

        try:
            async with session.post(request_url, json=payload, headers=headers, timeout=45, ssl=False) as response:
                if response.status == 200:
                    bot_logger.debug(i18n.get_text("log_messages.aggregator_chunk_sent","en",chunk_num=i + 1,entity_name=entity_name,count=len(chunk),))
                else:
                    response_text = await response.text()
                    bot_logger.error(i18n.get_text("log_messages.aggregator_chunk_error","en",chunk_num=i + 1,entity_name=entity_name,status=response.status,response=response_text[:50],))
                    break
        except Exception as e:
            bot_logger.error(i18n.get_text("log_messages.aggregator_connection_error","en",chunk_num=i + 1,entity_name=entity_name,error=e,))
            break


#############################################################
# Функция для отправки данных в агрегатор
async def send_data_to_aggregator(bot: Bot, arSession: ARS, force_full_sync: bool = True):
    get_settings = Settingsx.get()
    if get_settings.send_to_aggregator != "True":
        return
    if get_settings.agg_url is None or get_settings.agg_url == "None":
        bot_logger.warning(i18n.get_text("log_messages.aggregator_url_not_set", "en"))
        return
    if get_settings.agg_key is None or get_settings.agg_key == "None":
        bot_logger.error(i18n.get_text("log_messages.aggregator_key_not_set_log", "en"))
        return

    bot_logger.debug(i18n.get_text("log_messages.aggregator_sending_start", "en"))
    shop_id = bot.id
    api_key = get_settings.agg_key
    headers = {"X-Shop-ID": str(shop_id), "X-Api-Key": api_key}
    session = await arSession.get_session()
    base_url = f"http://{get_settings.agg_url}/api/v1"

    # last_sync_time = get_settings.agg_last_sync_unix or 0
    # if force_full_sync:
    #     bot_logger.info("Forcing a full data sync with the aggregator.")
    #     last_sync_time = 0 # Игнорируем время последней синхронизации для полной выгрузки
        
    # current_sync_time = get_unix()
    
    con = sqlite3.connect(PATH_DATABASE)
    con.row_factory = dict_factory
    cursor = con.cursor()

    try:
        
        first_call = True # Флаг для отслеживания первого вызова _send_chunked_data
        # 1. Получение и отправка ПОЗИЦИЙ
        cursor.execute("SELECT * FROM storage_position")
        positions_to_process = cursor.fetchall()
        
        if positions_to_process:
            category_map = {cat.category_id: cat.category_name for cat in Categoryx.get_all()}
            subcategory_map = {sub.subcategory_id: sub.subcategory_name for sub in Subcategoryx.get_all()}
            items_to_send = []
            for pos_data in positions_to_process:
                pos = PositionModel(**pos_data)
                cursor.execute("SELECT COUNT(increment) as count FROM storage_item WHERE position_id = ?", (pos.position_id,))
                item_count = cursor.fetchone()['count']
                items_to_send.append({
                    "position_id": pos.position_id,
                    "category": category_map.get(pos.category_id, "Без категории"),
                    "subcategory": subcategory_map.get(pos.subcategory_id, "Без подкатегории"),
                    "position_name": pos.position_name,
                    "position_price": pos.position_price,
                    "item_count": item_count,
                })
            bot_logger.info(f"Sending {len(items_to_send)} positions records to aggregator.")
            await _send_chunked_data(session, f"{base_url}/update_positions", headers, items_to_send, "Позиции", is_full_sync=True, is_first_call_in_session=first_call)
            first_call = False # Сбрасываем флаг после первого вызова


        # 2. Отправка ПОЛЬЗОВАТЕЛЕЙ
        cursor.execute("SELECT * FROM storage_users")
        users_data = [UserModel(**row).model_dump() for row in cursor.fetchall()]
        bot_logger.info(f"Sending {len(users_data)} users records to aggregator.")
        await _send_chunked_data(session, f"{base_url}/update_users", headers, users_data, "Пользователи", is_full_sync=True, is_first_call_in_session=first_call)
        if users_data:
            first_call = False

        # 3. Отправка ПОКУПОК
        cursor.execute("SELECT * FROM storage_purchases")
        purchases_data = [PurchasesModel(**p).model_dump() for p in cursor.fetchall()]
        bot_logger.info(f"Sending {len(purchases_data)} purchases records to aggregator.")
        await _send_chunked_data(session, f"{base_url}/update_purchases", headers, purchases_data, "Покупки", is_full_sync=True, is_first_call_in_session=first_call)
        if purchases_data: 
            first_call = False

        # 4. Отправка СЧЕТОВ
        cursor.execute("SELECT * FROM storage_invoice")
        invoices_data = [Invoice(**row).model_dump() for row in cursor.fetchall()]
        bot_logger.info(f"Sending {len(invoices_data)} invoices records to aggregator.")
        await _send_chunked_data(session, f"{base_url}/update_invoices", headers, invoices_data, "Счета", is_full_sync=True, is_first_call_in_session=first_call)
        if invoices_data: 
            first_call = False
        
        # 5. Отправка СПОРОВ
        cursor.execute("SELECT * FROM storage_disputes")
        disputes_raw = [DisputeModel(**row) for row in cursor.fetchall()]
        disputes_data = [d.model_dump(exclude={"media_message_ids", "media_chat_id"}) for d in disputes_raw]
        bot_logger.info(f"Sending {len(disputes_data)} disputes records to aggregator.")
        await _send_chunked_data(session, f"{base_url}/update_disputes", headers, disputes_data, "Споры", is_full_sync=True, is_first_call_in_session=first_call)
        
        bot_logger.info("Full sync completed.")

    finally:
        con.close()



#! функция для отправки отчета о переходе в агрегатор
async def report_transition_to_aggregator(bot: Bot, arSession: ARS, user_id: int):
    """#! Asynchronously notifies the aggregator about a user transition."""
    get_settings = Settingsx.get()
    if (
        get_settings.send_to_aggregator != "True"
        or not get_settings.agg_url
        or get_settings.agg_url == "None"
    ):
        return
    if not get_settings.agg_key or get_settings.agg_key == "None":
        bot_logger.warning(i18n.get_text("log_messages.aggregator_report_key_missing", "en"))
        await send_admins(bot, i18n.get_text("log_messages.aggregator_report_key_missing_admin", "en"))
        return

    shop_id = bot.id
    api_key = get_settings.agg_key
    headers = {"X-Shop-ID": str(shop_id), "X-Api-Key": api_key}
    payload = {"user_id": user_id}
    agg_url = f"http://{get_settings.agg_url}/api/v1/track_transition"
    try:
        session = await arSession.get_session()
        async with session.post(
            agg_url, json=payload, headers=headers, timeout=10, ssl=False
        ) as response:
            if response.status == 200:
                bot_logger.info(
                    i18n.get_text(
                        "log_messages.aggregator_report_success", "en", user_id=user_id
                    )
                )
            else:
                response_text = await response.text()
                bot_logger.error(
                    i18n.get_text(
                        "log_messages.aggregator_report_error",
                        "en",
                        status=response.status,
                        response=response_text[:50],
                    )
                )
    except Exception as e:
        bot_logger.error(
            i18n.get_text(
                "log_messages.aggregator_report_connection_error", "en", error=e
            )
        )


#! Автоматическое проставление оценки "Успех"
async def check_unrated_purchases():
    """#! Sets a "Success" rating for unrated purchases older than 12 hours"""
    twelve_hours_ago = get_unix() - (12 * 3600)

    unrated_purchases = Purchasesx.gets(rating=0)
    bot_logger.debug(
        i18n.get_text(
            "misc_functions.auto_rate_unrated_count", "en", count=len(unrated_purchases)
        )
    )
    if not unrated_purchases:
        return

    purchases_to_update = [
        p for p in unrated_purchases if p.purchase_unix < twelve_hours_ago
    ]
    bot_logger.debug(
        i18n.get_text(
            "misc_functions.auto_rate_to_update_count",
            "en",
            count=len(purchases_to_update),
        )
    )
    if not purchases_to_update:
        bot_logger.debug(i18n.get_text("misc_functions.auto_rate_none_to_update", "en"))
        return

    updated_count = 0
    for purchase in purchases_to_update:
        try:
            Purchasesx.update(purchase_receipt=purchase.purchase_receipt, rating=1)
            bot_logger.debug(
                i18n.get_text(
                    "misc_functions.auto_rate_success",
                    "en",
                    receipt=purchase.purchase_receipt,
                )
            )
            updated_count += 1
        except Exception as e:
            bot_logger.error(
                i18n.get_text(
                    "misc_functions.auto_rate_error",
                    "en",
                    receipt=purchase.purchase_receipt,
                    error=e,
                )
            )

    if updated_count > 0:
        bot_logger.debug(
            i18n.get_text("misc_functions.auto_rate_summary", "en", count=updated_count)
        )


async def send_notification(bot: Bot, user_id: int, message: str):
    try:
        await bot.send_message(chat_id=user_id, text=message)
    except Exception as e:
        bot_logger.error(
            i18n.get_text(
                "misc_functions.send_notification_error",
                "en",
                user_id=user_id,
                message=message,
                error=e,
            )
        )


async def _send_success_notifications(
    bot: Bot, admin_ids: list, user: UserModel, data: dict, i18n: Translator
):
    """
    #! Sends notifications of successful refill to the user and administrators.
    #! Errors are logged but do not interrupt execution.
    """
    user_locale = user.language_code or "en"
    date_to_sent = convert_date(data["created_at"])
    payment_time = convert_date(get_unix())

    user_message = (
        f"{i18n.get_text('misc_functions.refill_success_user_title', user_locale)}\n"
        f"{i18n.get_text('misc_functions.refill_success_user_body', user_locale, amount_usd=data['amount_usd'], amount_ltc=data['amount_ltc'], invoice_id=data['invoice_id'], date_created=date_to_sent, date_paid=payment_time)}"
    )

    AggregatorTrafficx.log_refill(user.user_id, data["amount_usd"])

    try:
        await bot.send_message(user.user_id, user_message, parse_mode="HTML")
        bot_logger.debug(
            i18n.get_text(
                "misc_functions.log_refill_notify_user_success",
                "en",
                login=user.user_login,
            )
        )
    except Exception as e:
        bot_logger.error(
            i18n.get_text(
                "misc_functions.log_refill_notify_user_error",
                "en",
                user_id=user.user_id,
                login=user.user_login,
                error=e,
            )
        )

    users_list = set(admin_ids) | set(get_operators())
    for user_id in users_list:
        try:
            recipient_user = Userx.get(user_id=user_id)
            recipient_locale = recipient_user.language_code if recipient_user else "en"
            admin_message = (
                f"{i18n.get_text('misc_functions.refill_success_admin_title', recipient_locale, invoice_id=data['invoice_id'])}\n"
                f"{i18n.get_text('misc_functions.refill_success_admin_body', recipient_locale, login=user.user_login, user_id=user.user_id, amount_usd=data['amount_usd'], amount_ltc=data['amount_ltc'], date_created=date_to_sent, date_paid=payment_time, txid=data['txid'])}"
            )
            await bot.send_message(
                chat_id=user_id, text=admin_message, parse_mode="HTML"
            )
        except Exception as e:
            bot_logger.warning(
                i18n.get_text(
                    "misc_functions.log_refill_notify_admin_error",
                    "en",
                    admin_id=user_id,
                    error=e,
                )
            )


async def _send_db_error_to_admins(
    bot: Bot,
    admin_ids: list,
    user_id: int,
    user_login: str,
    invoice_id: int,
    error: Exception,
    i18n: Translator,
):
    """#! Sends a notification to administrators about a failure to update the database."""
    error_message = i18n.get_text(
        "misc_functions.db_update_error_admin_alert",
        "en",
        invoice_id=invoice_id,
        login=user_login,
        user_id=user_id,
        error=error,
    )

    bot_logger.error(
        i18n.get_text(
            "misc_functions.log_db_update_critical_error",
            "en",
            invoice_id=invoice_id,
            user_id=user_id,
            error=error,
        )
    )

    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, error_message, parse_mode="HTML")
        except Exception as e:
            bot_logger.error(
                i18n.get_text(
                    "misc_functions.log_send_admin_notify_error",
                    "en",
                    admin_id=admin_id,
                    error=e,
                )
            )


async def update_balance(PATH_DATABASE: str, bot: Bot, arSession: ARS):
    """Проверяет наличие успешно выставленных счетов и зачисляет средства на баланс пользователя.
    Эта функция выполняет заключительный этап процесса пополнения счета.
    Он находит все счета-фактуры со статусом -succsess-, обновляет соответствующий
    баланс пользователя и общую сумму пополнения, а затем изменяет счет-фактуру
    присвоен статус -finished- для предотвращения двойного зачисления. Каждый счет-фактура обрабатывается 
    в отдельной транзакции базы данных для обеспечения отказоустойчивости.
    Аргументы:
        PATH_DATABASE (str): Путь к файлу базы данных SQLite.
        бот (Bot): Экземпляр бота aiogram для отправки уведомлений.
    """

    bot_logger.debug(i18n.get_text("misc_functions.log_update_balance_start", "en"))
    conn = None
    try:
        conn = sqlite3.connect(PATH_DATABASE, timeout=15.0)
        cursor = conn.cursor()
        cursor.execute("""SELECT id, user_id, amount_usd, amount_ltc, created_at, txid FROM storage_invoice WHERE status = 'succsess' AND txid IS NOT NULL""")
        invoices_to_process = cursor.fetchall()

        if not invoices_to_process:
            bot_logger.debug(i18n.get_text("misc_functions.log_update_balance_none_found", "en"))
            return

        bot_logger.info(
            i18n.get_text(
                "misc_functions.log_update_balance_found_count",
                "en",
                count=len(invoices_to_process),
            )
        )
        admin_ids = get_admins()

        for invoice in invoices_to_process:
            invoice_id, user_id, amount_usd, amount_ltc, created_at, txid = invoice
            user = Userx.get(user_id=user_id)
            if not user:
                bot_logger.warning(i18n.get_text("misc_functions.log_update_balance_user_not_found","en", invoice_id=invoice_id, user_id=user_id,))
                continue

            try:
                cursor.execute( "SELECT 1 FROM storage_invoice WHERE txid = ? AND status = 'finished'", (txid,), )
                if cursor.fetchone():
                    bot_logger.warning(i18n.get_text("misc_functions.log_update_balance_txid_used","en", txid=txid, invoice_id=invoice_id,))
                    continue

                cursor.execute("UPDATE storage_users SET user_balance = user_balance + ?, user_refill = user_refill + ? WHERE user_id = ?",(amount_usd, amount_usd, user_id),)
                cursor.execute("UPDATE storage_invoice SET status = 'finished' WHERE id = ?",(invoice_id,),) 
                conn.commit()
                bot_logger.info( i18n.get_text( "misc_functions.log_update_balance_success", "en", invoice_id=invoice_id, user_id=user_id, ) )

                #! Уведомляем агрегатор об изменении баланса
                from tgbot.utils.misc_functions import notify_aggregator_of_balance_update #arSession=ARS(), Создаем новую сессию, если нужно
                asyncio.create_task(notify_aggregator_of_balance_update(bot=bot, arSession=arSession, user_id=user.user_id, new_balance=user.user_balance + amount_usd))

                await _send_success_notifications(bot, admin_ids, user, { "invoice_id": invoice_id, "amount_usd": amount_usd, "amount_ltc": amount_ltc, "created_at": created_at, "txid": txid, }, i18n)
            

            except Exception as db_error:
                if conn:
                    conn.rollback()
                await _send_db_error_to_admins(
                    bot,
                    admin_ids,
                    user.user_id,
                    user.user_login,
                    invoice_id,
                    db_error,
                    i18n,
                )
                continue

    except Exception as e:
        bot_logger.error(
            i18n.get_text(
                "misc_functions.log_update_balance_global_error", "en", error=e
            )
        )
    finally:
        if conn:
            conn.close()
    bot_logger.debug(i18n.get_text("misc_functions.log_update_balance_end", "en"))


#! Функция для обновления статуса записей в таблице storage_invoice pending меняем на reject
async def update_pending_status(PATH_DATABASE, bot: Bot):
    bot_logger.debug(i18n.get_text("log_messages.update_pending_status_start", "en"))
    from tgbot.data.config import pause_to_reject_status

    conn = sqlite3.connect(PATH_DATABASE, timeout=15)
    cursor = conn.cursor()
    try:
        current_time = get_unix()
        time_ago = current_time - pause_to_reject_status
        bot_logger.debug(
            i18n.get_text(
                "log_messages.update_pending_status_times",
                "en",
                current_time=convert_date(current_time),
                reject_time=convert_date(time_ago),
            )
        )

        cursor.execute(
            "SELECT id, user_id, created_at FROM storage_invoice WHERE status = 'pending'"
        )
        invoices = cursor.fetchall()
        bot_logger.debug(
            i18n.get_text(
                "log_messages.update_pending_status_found", "en", count=len(invoices)
            )
        )

        count_rejected = 0
        for invoice_id, user_id, created_at in invoices:
            if created_at <= time_ago:
                bot_logger.debug(
                    i18n.get_text(
                        "log_messages.update_pending_status_rejecting",
                        "en",
                        invoice_id=invoice_id,
                        duration=pause_to_reject_status,
                    )
                )
                cursor.execute(
                    "UPDATE storage_invoice SET status = 'reject' WHERE id = ?",
                    (invoice_id,),
                )
                count_rejected += 1

                user = Userx.get(user_id=user_id)
                locale = user.language_code if user else "en"

                message_to_user = (
                    f"{i18n.get_text('misc_functions.invoice_expired_title', locale)}\n"
                    f"{i18n.get_text('misc_functions.invoice_expired_body', locale, invoice_id=invoice_id, created_date=convert_date(created_at), expired_date=convert_date(created_at + pause_to_reject_status))}"
                )

                try:
                    await bot.send_message(chat_id=user_id, text=ded(message_to_user))
                except Exception as e:
                    bot_logger.error(
                        i18n.get_text(
                            "log_messages.update_pending_status_notify_error",
                            "en",
                            user_id=user_id,
                            error=e,
                        )
                    )

        conn.commit()
        if count_rejected > 0:
            bot_logger.debug(
                i18n.get_text(
                    "log_messages.update_pending_status_summary",
                    "en",
                    count=count_rejected,
                )
            )
    except Exception as e:
        bot_logger.error(
            i18n.get_text("log_messages.update_pending_status_error", "en", error=e)
        )
        conn.rollback()
    finally:
        conn.close()


#! Автоматическая очистка и отправка ежедневной статистики в 00:00:30
async def update_profit_day(bot: Bot):
    """ #! Отправляет каждому администратору ежедневный отчет по статистике на его языке. """
    try:
        # Отправляем статистику каждому админу на его языке
        for admin_id in get_admins():
            try:
                admin_user = Userx.get(user_id=admin_id)
                # Определяем язык админа, по умолчанию 'en'
                admin_locale = admin_user.language_code if admin_user.language_code else "en"
                # Генерируем статистику для конкретного языка
                statistics_text_parts = get_statistics(i18n, admin_locale)
                # FIX: Отправляем каждую часть статистики ОТДЕЛЬНЫМ сообщением
                for text_part in statistics_text_parts:
                    if text_part: # Убедимся, что часть не пустая
                        await bot.send_message(admin_id, text_part)
                        await asyncio.sleep(0.3) # Небольшая задержка, чтобы избежать спама

            except Exception as e:
                error_msg = f"Error sending statistics to admin {admin_id}: {e}"
                bot_logger.error(error_msg)
                print(error_msg)

        try:
            Settingsx.update(misc_profit_day=get_unix())
        except Exception as e:
            error_msg = f"Error in update_profit_day: {e}"
            bot_logger.error(error_msg)
            await send_admins(bot, error_msg)  # Уведомляем админов об ошибке обновления
    except Exception as e:
        error_msg = f"Error to get process statistics: {e}"
        bot_logger.error(error_msg)
        await send_admins(bot, error_msg) # Уведомляем админов об ошибке получения статистики


#! Автоматическая очистка еженедельной статистики в понедельник 00:00:10
async def update_profit_week():
    try:
        Settingsx.update(misc_profit_week=get_unix())
    except Exception as e:
        bot_logger.error(f"Error in update_profit_week: {e}")


#! Автоматическое обновление счётчика каждый месяц первого числа в 00:00:05
async def update_profit_month():
    try:
        Settingsx.update(misc_profit_month=get_unix())
    except Exception as e:
        bot_logger.error(f"Error in update_profit_month: {e}")


#! Автонастройка UNIX времени в БД
async def autosettings_unix():
    now = datetime.now()
    unix_day = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    unix_week = unix_day - (now.weekday() * 86400)
    unix_month = int(
        now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    )
    Settingsx.update(
        misc_profit_day=unix_day,
        misc_profit_week=unix_week,
        misc_profit_month=unix_month,
    )


#! Проверка на перенесение БД из старого бота в нового или указание токена нового бота
async def check_bot_username(bot: Bot):
    get_login = Settingsx.get()
    get_bot = await bot.get_me()
    if get_bot.username != get_login.misc_bot:
        Settingsx.update(misc_bot=get_bot.username)


#! Уведомление и проверка обновления при запуске бота
async def startup_notify(bot: Bot, arSession: ARS):
    if len(get_admins()) >= 1:
        # Уведомление админам отправляется на языке по умолчанию (en)
        await send_admins(
            bot, ded(i18n.get_text("misc_functions.startup_notify_admin", "en"))
        )


# #! Автобэкапы БД для админов
async def autobackup_admin(bot: Bot):
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)

    backup_filename = f"database_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    try:
        shutil.copy2(PATH_DATABASE, backup_path)
    except Exception as e:
        print(i18n.get_text("log_messages.db_backup_copy_error", "en", error=e))

    try:
        now = datetime.now()
        for filename in os.listdir(BACKUP_DIR):
            file_path = os.path.join(BACKUP_DIR, filename)
            if os.path.isfile(file_path) and filename.startswith("database_"):
                file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                if now - file_mtime > timedelta(hours=24):
                    os.remove(file_path)
    except Exception as e:
        print(i18n.get_text("log_messages.db_backup_delete_old_error", "en", error=e))

    for admin_id in get_admins():
        try:
            admin_user = Userx.get(user_id=admin_id)
            admin_locale = admin_user.language_code if admin_user else "en"

            await bot.send_document(
                admin_id,
                FSInputFile(PATH_DATABASE),
                caption=i18n.get_text(
                    "misc_functions.db_backup_caption",
                    admin_locale,
                    date=get_date(full=False),
                ),
                disable_notification=True,
            )
        except Exception as e:
            admin_login = admin_user.user_login if admin_user else "unknown"
            print(
                i18n.get_text(
                    "log_messages.db_backup_send_error",
                    "en",
                    login=admin_login,
                    error=e,
                )
            )


#! Проверка наличия обновлений бота
async def check_update(bot: Bot):
    """#! Sends a notification to administrators that update checks are not being performed."""
    try:
        await send_admins(
            bot, i18n.get_text("misc_functions.update_check_disabled", "en")
        )
        bot_logger.debug(
            i18n.get_text("log_messages.update_check_admin_notification_sent", "en")
        )
    except Exception as ex:
        bot_logger.error(
            i18n.get_text("log_messages.update_check_send_error", "en", error=ex)
        )


#! Рассылка админам о критических ошибках и обновлениях
async def check_mail(bot: Bot):
    """#! Sends a notification to administrators that critical update checks are not being performed."""
    try:
        await send_admins(
            bot, i18n.get_text("misc_functions.mail_check_disabled", "en")
        )
        bot_logger.debug(
            i18n.get_text("log_messages.mail_check_admin_notification_sent", "en")
        )
    except Exception as ex:
        bot_logger.error(
            i18n.get_text("log_messages.mail_check_send_error", "en", error=ex)
        )


#! Вставка кастомных тэгов юзера в текст
def insert_tags(user_id: Union[int, str], text: str) -> str:
    get_user = Userx.get(user_id=user_id)
    if get_user:
        if "{user_id}" in text:
            text = text.replace("{user_id}", f"<b>{get_user.user_id}</b>")
        if "{username}" in text:
            text = text.replace("{username}", f"<b>{get_user.user_login}</b>")
        if "{firstname}" in text:
            text = text.replace("{firstname}", f"<b>{get_user.user_name}</b>")
    return text


#! Загрузка текста на текстовый хостинг
async def upload_text(arSession: ARS, text: str) -> str:
    session = await arSession.get_session()
    spare_pass = False
    await asyncio.sleep(0.5)
    try:
        response = await session.post(
            "http://pastie.org/pastes/create",
            data={"language": "plaintext", "content": text},
        )
        get_link = response.url
        if "create" in str(get_link):
            spare_pass = True
    except Exception:
        spare_pass = True

    if spare_pass:
        response = await session.post(
            "https://www.friendpaste.com",
            json={"language": "text", "title": "", "snippet": text},
        )
        get_link = json.loads((await response.read()).decode())["url"]
    return get_link


#! Наличие товаров администраторы
def get_items_available_admin(i18n: Translator, locale: str) -> list[str]:
    # (Эта функция была переведена ранее, но теперь добавлена зависимость от i18n)
    categories = Categoryx.get_all()
    messages, current_message, current_length = [], [], 0

    for category in categories:
        category_content_parts = []
        all_positions = Positionx.gets(category_id=category.category_id)
        subcategories = Subcategoryx.gets(category_id=category.category_id)

        for subcategory in subcategories:
            positions_in_sub = [
                pos
                for pos in all_positions
                if pos.subcategory_id == subcategory.subcategory_id
            ]
            positions_with_items_sub = [
                (pos, len(Itemx.gets(position_id=pos.position_id)))
                for pos in positions_in_sub
                if Itemx.gets(position_id=pos.position_id)
            ]

            if positions_with_items_sub:
                category_content_parts.append(
                    f"📍 <b>{subcategory.subcategory_name}</b>\n"
                )
                for position, total_items in positions_with_items_sub:
                    status = (
                        i18n.get_text(
                            "misc_functions.availability_low_stock_admin", locale
                        )
                        if total_items <= 5
                        else ""
                    )
                    position_text = f"    {position.position_name} | {int(position.position_price)} | {total_items} шт. {status}\n"
                    category_content_parts.append(position_text)
                category_content_parts.append("\n")

        if category_content_parts:
            category_header = f"╔═══════════════╗\n🏘 <b>{category.category_name}</b>\n╚═══════════════╝\n"
            full_category_text = category_header + "".join(category_content_parts)
            if current_length + len(full_category_text) > 4000:
                messages.append("".join(current_message))
                current_message, current_length = [], 0
            current_message.append(full_category_text)
            current_length += len(full_category_text)

    if current_message:
        messages.append("".join(current_message))
    return messages


#! Рассылка админам о наличии товаров
async def status_items_available_admin(bot: Bot):
    categories = Categoryx.get_all()
    # Уведомления админам отправляются на языке по умолчанию (русском)
    locale = "en"

    for admin_id in get_admins():
        admin_user = Userx.get(user_id=admin_id)
        if admin_user and admin_user.language_code:
            locale = admin_user.language_code

        message_lines = []
        for category in categories:
            message_lines.append(f"<b>➖{category.category_name}</b>")
            positions = Positionx.gets(category_id=category.category_id)
            for position in positions:
                total_items = len(Itemx.gets(position_id=position.position_id))
                status = ""
                if total_items == 0:
                    status = i18n.get_text(
                        "misc_functions.availability_no_stock_admin", locale
                    )
                elif 1 < total_items <= 5:
                    status = i18n.get_text(
                        "misc_functions.availability_low_stock_admin", locale
                    )
                elif total_items > 5:
                    status = i18n.get_text(
                        "misc_functions.availability_in_stock_admin", locale
                    )

                message_lines.append(
                    f"{position.position_name} | {int(position.position_price)}  | {total_items} шт. | {status}"
                )
            message_lines.append("")

        message_to_sent = "\n".join(message_lines)

        try:
            await bot.send_message(
                chat_id=admin_id, text=message_to_sent, parse_mode="HTML"
            )
            bot_logger.debug(
                i18n.get_text(
                    "log_messages.status_items_admin_notification_sent",
                    "en",
                    login=admin_user.user_login,
                )
            )
        except Exception as e:
            bot_logger.error(
                i18n.get_text(
                    "log_messages.status_items_admin_notification_error",
                    "en",
                    login=admin_user.user_login,
                    error=e,
                )
            )


#! Наличие товаров пользователи
def get_items_available(i18n: Translator, locale: str) -> list[str]:
    categories = get_categories_items()
    messages = []
    current_message = []
    current_length = 0
    get_settings = Settingsx.get()

    if get_settings.zagolovok_info != "None":
        zagolovok_text = f"<b>{get_settings.zagolovok_info}</b>\n\n"
        current_message.append(zagolovok_text)
        current_length += len(zagolovok_text)

    for category in categories:
        category_content_parts = []
        all_positions = Positionx.gets(category_id=category.category_id)
        subcategories = Subcategoryx.gets(category_id=category.category_id)

        for subcategory in subcategories:
            positions_in_sub = [
                pos
                for pos in all_positions
                if pos.subcategory_id == subcategory.subcategory_id
            ]
            positions_with_items_sub = []
            for pos in positions_in_sub:
                items = Itemx.gets(position_id=pos.position_id)
                if items:
                    positions_with_items_sub.append((pos, len(items)))

            if positions_with_items_sub:
                category_content_parts.append(
                    f"📍 <b>{subcategory.subcategory_name}</b>\n"
                )
                for position, total_items in positions_with_items_sub:
                    if total_items <= 5:
                        position_text = f"    {position.position_name} | {int(position.position_price)} | {i18n.get_text('misc_functions.availability_low_stock_user', locale)}\n"
                    else:
                        position_text = f"    {position.position_name} | {int(position.position_price)}\n"
                    category_content_parts.append(position_text)
                category_content_parts.append("\n")

        if category_content_parts:
            category_header = f"╔═══════════════╗\n🏘 <b>{category.category_name}</b>\n╚═══════════════╝\n"
            full_category_text = category_header + "".join(category_content_parts)

            if current_length + len(full_category_text) > 4000:
                messages.append("".join(current_message))
                current_message = (
                    [zagolovok_text] if get_settings.zagolovok_info != "None" else []
                )
                current_length = (
                    len(zagolovok_text) if get_settings.zagolovok_info != "None" else 0
                )

            current_message.append(full_category_text)
            current_length += len(full_category_text)

    if current_message:
        if get_settings.misc_info_check != "None":
            final_text_chunk = (
                "".join(current_message) + f"\n{get_settings.misc_info_check}"
            )
            if len(final_text_chunk) > 4000:
                messages.append("".join(current_message))
                messages.append(f"\n{get_settings.misc_info_check}")
            else:
                messages.append(final_text_chunk)
        else:
            messages.append("".join(current_message))
    return messages


#! Получение категорий с товарами
def get_categories_items() -> list[CategoryModel]:
    get_settings = Settingsx.get()
    get_categories = Categoryx.get_all()
    save_categories = []

    if get_settings.misc_hide_category == "True":
        for category in get_categories:
            has_items = False
            positions = Positionx.gets(
                category_id=category.category_id, subcategory_id=None
            )
            for position in positions:
                if len(Itemx.gets(position_id=position.position_id)) >= 1:
                    has_items = True
                    break
            if not has_items:
                subcategories = Subcategoryx.gets(category_id=category.category_id)
                for subcategory in subcategories:
                    positions = Positionx.gets(
                        category_id=category.category_id,
                        subcategory_id=subcategory.subcategory_id,
                    )
                    for position in positions:
                        if len(Itemx.gets(position_id=position.position_id)) >= 1:
                            has_items = True
                            break
                    if has_items:
                        break
            if has_items:
                save_categories.append(category)
    else:
        save_categories = get_categories
    return save_categories


#! Получение позиций с товарами
def get_positions_items(
    category_id: Union[str, int], subcategory_id: Union[str, int]
) -> list[PositionModel]:
    get_settings = Settingsx.get()
    positions = Positionx.gets(category_id=category_id, subcategory_id=subcategory_id)
    save_positions = []
    if get_settings.misc_hide_position == "True":
        for position in positions:
            if len(Itemx.gets(position_id=position.position_id)) >= 1:
                save_positions.append(position)
    else:
        save_positions = positions
    return save_positions


#! Отправка рассылки
async def functions_mail_make(bot: Bot, message: Message, call: CallbackQuery, i18n: Translator, locale: str):
    users_receive, users_block, users_count = 0, 0, 0
    get_users = [user for user in Userx.get_all() if not user.bot_blocked_by_user]
    total_users = len(get_users)
    get_time = get_unix()
    for user in get_users:
        try:
            await bot.copy_message(chat_id=user.user_id,from_chat_id=message.from_user.id,message_id=message.message_id,)
            users_receive += 1
        except Exception:
            users_block += 1
            await asyncio.to_thread(Userx.update, user.user_id, bot_blocked_by_user=1)

        users_count += 1
        if users_count % 10 == 0:
            try:
                await call.message.edit_text( i18n.get_text( "misc_functions.mailing_started", locale, count=users_count, total=total_users,))
            except Exception:
                pass
        await asyncio.sleep(0.07)

    try:
        await call.message.edit_text( ded( i18n.get_text( "misc_functions.mailing_finished", locale, seconds=get_unix() - get_time, total=total_users, received=users_receive, blocked=users_block, ) ) )
    except Exception:
        pass


#! Создание записи о покупке
def create_purchase_record(
    user_id: int,
    position_id: int,
    items: list[ItemModel],
    user_balance_before: float,
    user_balance_after: float,
    total_price: float,
) -> None:
    position = Positionx.get(position_id=position_id)
    category = Categoryx.get(category_id=position.category_id)
    subcategory = Subcategoryx.get(
        category_id=position.category_id, subcategory_id=position.subcategory_id
    )

    #! Формируем данные о покупке
    items_data = [item.item_data for item in items]
    receipt = "\n".join([f"{item.item_name}: {item.item_data}" for item in items])

    Purchasesx.add(
        user_id=user_id,
        user_balance_before=user_balance_before,
        user_balance_after=user_balance_after,
        purchase_receipt=receipt,
        purchase_data=items_data,
        purchase_count=len(items),
        purchase_price=total_price,
        purchase_price_one=position.position_price,
        purchase_position_id=position.position_id,
        purchase_position_name=position.position_name,
        purchase_category_id=category.category_id,
        purchase_category_name=category.category_name,
        purchase_subcategory_id=subcategory.subcategory_id,
        purchase_subcategory_name=subcategory.subcategory_name,
        purchase_unix=get_unix(),
        from_site=False,
    )


########################
async def api_retry_wrapper_background(
    bot: Bot, api_name: str, api_functions: list, i18n: Translator, locale: str, *args
):
    #! """Обёртка для фоновых задач с 2 кругами резервирования."""
    for i in range(2):
        for provider in api_functions:
            try:
                result = await provider(*args)
                if (
                    result is not None
                ):  #! Успех, если не None (пустой список [] - тоже успех)
                    bot_logger.debug(
                        f"api_retry_wrapper_background: Данные для {api_name} получены от {provider.__name__}"
                    )
                    return result
            except Exception as e:
                bot_logger.warning(
                    f"api_retry_wrapper_background: Провайдер {provider.__name__} для {api_name} не ответил: {e}"
                )
        bot_logger.warning(
            f"api_retry_wrapper_background: Все провайдеры для {api_name} не ответили. Круг {i + 1}."
        )

    bot_logger.critical(
        f"api_retry_wrapper_background: Все API для {api_name} не отвечают после попыток!"
    )

    error_text = i18n.get_text("errors.api_critical_failure", locale, api_name=api_name)

    await send_admins(
        bot,
        error_text,
    )
    return []  #! Возвращаем пустой список в случае полного провала


#! --- Источники данных для USDT TRC20 ---
async def get_usdt_from_tronscan(address: str) -> list | None:
    #! """Источник 1: TronScan. Ищет подтвержденные транзакции не старше 2 часов."""
    url = "https://apilist.tronscan.org/api/token_trc20/transfers"
    params = {
        "limit": 50,
        "start": 0,
        "sort": "-timestamp",
        "toAddress": address,
        "contract_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
    }
    try:
        async with ClientSession() as s:
            async with s.get(url, params=params, timeout=15) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                transactions = []
                cutoff_time = datetime.now(timezone.utc) - timedelta(hours=2)
                for tx in data.get("token_transfers", []):
                    if (
                        tx.get("confirmed")
                        and tx.get("to_address", "").lower() == address.lower()
                    ):
                        tx_time = datetime.fromtimestamp(
                            tx["block_ts"] / 1000, tz=timezone.utc
                        )
                        if tx_time >= cutoff_time:
                            transactions.append(
                                {
                                    "txid": tx["transaction_id"],
                                    "amount": round(int(tx["quant"]) / 10**6, 6),
                                    "date": tx_time.isoformat(),
                                    "confirmations": "confirmed",
                                }
                            )
                return transactions
    except Exception:
        return None


#! Резервные источники для USDT
async def get_usdt_from_tronscan_fallback(address: str) -> list | None:
    #! Используем тот же TronScan, но это защищает от временных сбоев сети
    await asyncio.sleep(2)  #! Небольшая задержка перед повторной попыткой
    return await get_usdt_from_tronscan(address)


#! Обновление статуса на succsess для storage_invoice
async def update_invoice_status(PATH_DATABASE, bot: Bot):
    """Обновляет статусы счетов-фактур, проверяя внешние платежные API.
    Эта функция является важной частью автоматизированной системы пополнения счета.
    Она извлекает последние транзакции от активного поставщика платежей (HTX или альтернативного), 
    сравнивает их с -pending- счетами в базе данных, основываясь на точной сумму и валюту платежа, 
    а также обновляет статус сопоставленных счетов-фактур до -succsess-.

    Аргументы:
        PATH_DATABASE (str): Путь к файлу базы данных SQLite.
        бот (Bot): Экземпляр бота aiogram, используемый базовыми модулями API для уведомлений.
    """
    bot_logger.debug(i18n.get_text("log_messages.update_invoice_status_start", "en"))
    settings = Settingsx.get()

    if settings.payment_system == "htx":
        bot_logger.debug(i18n.get_text("log_messages.update_invoice_status_active_ps_htx", "en"))
        currencies_to_check = {
            "LTC": {
                "fetch_function": lambda: get_htx_deposits("ltc"),
                "amount_field": "amount_ltc",
                "precision": 6,
            },
            "USDT": {
                "fetch_function": lambda: get_htx_deposits("usdt"),
                "amount_field": "amount_usdt",
                "precision": 6,
            },
        }
    else:
        bot_logger.debug(i18n.get_text("log_messages.update_invoice_status_active_ps_alt", "en"))
        currencies_to_check = {
            "LTC": {
                "address": settings.alter_ltc_address,
                "fetch_function": get_ltc_transactions,
                "amount_field": "amount_ltc",
                "precision": 6,
            },
            "USDT": {
                "address": settings.alter_usdt_trc20_address,
                "fetch_function": get_usdt_trc20_transactions,
                "amount_field": "amount_usdt",
                "precision": 6,
            },
        }

    for currency_code, params in currencies_to_check.items():
        try:
            bot_logger.info(i18n.get_text("log_messages.update_invoice_status_checking_for","en",currency=currency_code,))

            if settings.payment_system == "alternative":
                address = params.get("address")
                if (not address or i18n.get_text("admin_settings.not_specified", "en") in address):
                    bot_logger.info(i18n.get_text("log_messages.update_invoice_status_no_address","en",currency=currency_code,))
                    continue
                recent_transactions = await params["fetch_function"](bot, address)
            else:
                recent_transactions = await params["fetch_function"]()

            if recent_transactions is None:
                bot_logger.warning(
                    i18n.get_text(
                        "log_messages.update_invoice_status_provider_error",
                        "en",
                        currency=currency_code,
                    )
                )
                continue
            if not recent_transactions:
                bot_logger.info(
                    i18n.get_text(
                        "log_messages.update_invoice_status_no_new_tx",
                        "en",
                        currency=currency_code,
                    )
                )
                continue

            bot_logger.info(
                i18n.get_text(
                    "log_messages.update_invoice_status_tx_received",
                    "en",
                    currency=currency_code,
                    count=len(recent_transactions),
                )
            )

            conn = sqlite3.connect(PATH_DATABASE, timeout=15)
            cursor = conn.cursor()
            cursor.execute("SELECT txid FROM storage_invoice WHERE txid IS NOT NULL")
            used_txids = {row[0] for row in cursor.fetchall()}
            cursor.execute(
                f"SELECT id, {params['amount_field']} FROM storage_invoice WHERE status = 'pending' AND currency = ?",
                (currency_code,),
            )
            pending_invoices = cursor.fetchall()

            if not pending_invoices:
                bot_logger.debug(
                    i18n.get_text(
                        "log_messages.update_invoice_status_no_pending_invoices",
                        "en",
                        currency=currency_code,
                    )
                )
                conn.close()
                continue

            bot_logger.info(
                i18n.get_text(
                    "log_messages.update_invoice_status_pending_invoices_found",
                    "en",
                    currency=currency_code,
                    count=len(pending_invoices),
                )
            )

            invoice_map = {
                f"{amount:.{params['precision']}f}": []
                for inv_id, amount in pending_invoices
                if amount is not None
            }
            for inv_id, amount in pending_invoices:
                if amount is not None:
                    invoice_map[f"{amount:.{params['precision']}f}"].append(inv_id)

            bot_logger.info(
                i18n.get_text(
                    "log_messages.update_invoice_status_map_created",
                    "en",
                    currency=currency_code,
                    count=len(invoice_map),
                )
            )

            for tx in recent_transactions:
                tx_id, tx_timestamp = tx["txid"], tx["timestamp"]
                tx_amount_str = f"{tx['amount']:.{params['precision']}f}"
                bot_logger.debug(
                    i18n.get_text(
                        "log_messages.update_invoice_status_checking_tx",
                        "en",
                        currency=currency_code,
                        txid=tx_id,
                        amount=tx_amount_str,
                        date=convert_date(tx_timestamp),
                    )
                )

                if tx_id in used_txids:
                    bot_logger.debug(
                        i18n.get_text(
                            "log_messages.update_invoice_status_tx_used",
                            "en",
                            currency=currency_code,
                            txid=tx_id,
                        )
                    )
                    continue

                if tx_amount_str in invoice_map and invoice_map[tx_amount_str]:
                    invoice_id_to_update = invoice_map[tx_amount_str].pop(0)
                    bot_logger.info(
                        i18n.get_text(
                            "log_messages.update_invoice_status_match_found",
                            "en",
                            currency=currency_code,
                            invoice_id=invoice_id_to_update,
                            txid=tx_id,
                            date=convert_date(tx_timestamp),
                        )
                    )
                    cursor.execute(
                        "UPDATE storage_invoice SET status = 'succsess', txid = ?, payed_at = ? WHERE id = ?",
                        (tx_id, get_unix(), invoice_id_to_update),
                    )
                    used_txids.add(tx_id)
                else:
                    bot_logger.info(
                        i18n.get_text(
                            "log_messages.update_invoice_status_no_match",
                            "en",
                            currency=currency_code,
                            txid=tx_id,
                            amount=tx_amount_str,
                        )
                    )

            conn.commit()
            conn.close()
        except Exception as e:
            bot_logger.error(
                i18n.get_text(
                    "log_messages.update_invoice_status_critical_error",
                    "en",
                    currency=currency_code,
                    error=e,
                ),
                exc_info=True,
            )

    bot_logger.debug(i18n.get_text("log_messages.update_invoice_status_finished", "en"))


async def get_actual_ltc_rate(bot: Bot) -> float | None:
    """#! Gets the LTC rate depending on the selected payment system."""
    settings = Settingsx.get()
    if settings.payment_system == "htx":
        return await get_htx_ltc_to_usd_rate()
    else:
        return await get_ltc_to_usd_rate(bot)


#! Updates the LTC rate in the DB depending on the system
async def update_actual_ltc_rate_in_db(bot: Bot):
    """#! Background task to update the LTC rate in the database, considering the active payment system."""
    bot_logger.debug(i18n.get_text("log_messages.ltc_rate_update_start", "en"))
    rate = await get_actual_ltc_rate(bot)
    if rate:
        Settingsx.update(ltc_to_usd_rate=rate)
        bot_logger.debug(
            i18n.get_text("log_messages.ltc_rate_update_success", "en", rate=rate)
        )
    else:
        bot_logger.error(i18n.get_text("log_messages.ltc_rate_update_fail", "en"))


async def send_traffic_data_to_aggregator(bot: Bot, arSession: ARS):
    """#! Background task to send accumulated traffic statistics to the aggregator."""

    get_settings = Settingsx.get()
    if get_settings.send_to_aggregator != "True":
        return

    if not get_settings.agg_url or get_settings.agg_url == "None":
        bot_logger.debug(i18n.get_text("log_messages.traffic_send_stopped", "en"))
        return

    if not get_settings.agg_key or get_settings.agg_key == "None":
        bot_logger.warning(i18n.get_text("log_messages.traffic_send_no_key", "en"))
        return

    unsynced_data = AggregatorTrafficx.get_unsynced()
    if not unsynced_data:
        bot_logger.debug(i18n.get_text("log_messages.traffic_send_no_data", "en"))
        return

    bot_logger.debug(
        i18n.get_text(
            "log_messages.traffic_send_found_data", "en", count=len(unsynced_data)
        )
    )

    shop_id = bot.id
    api_key = get_settings.agg_key
    headers = {"X-Shop-ID": str(shop_id), "X-Api-Key": api_key}
    payload = {"traffic_data": unsynced_data}
    agg_url = f"http://{get_settings.agg_url}/api/v1/sync_traffic_data"

    bot_logger.debug(
        i18n.get_text(
            "log_messages.traffic_send_sending_data",
            "en",
            count=len(unsynced_data),
            url=agg_url,
        )
    )

    try:
        session = await arSession.get_session()
        async with session.post(
            agg_url, json=payload, headers=headers, timeout=30, ssl=False
        ) as response:
            if response.status == 200:
                record_ids = [record["id"] for record in unsynced_data]
                AggregatorTrafficx.mark_as_synced(record_ids)
                bot_logger.info(
                    i18n.get_text(
                        "log_messages.traffic_send_success", "en", count=len(record_ids)
                    )
                )
            else:
                response_text = await response.text()
                bot_logger.error(
                    i18n.get_text(
                        "log_messages.traffic_send_sync_error",
                        "en",
                        status=response.status,
                        response=response_text[:50],
                    )
                )
    except Exception as e:
        bot_logger.error(
            i18n.get_text("log_messages.traffic_send_connection_error", "en", error=e)
        )



async def update_connection_details_on_aggregator(bot: Bot, arSession: ARS):
    """Получает публичный IP и внешний порт, а затем отправляет их агрегатору."""
    bot_logger.info("Attempting to send connection details to aggregator...")
    get_settings = Settingsx.get()
    if get_settings.send_to_aggregator != "True":
        bot_logger.info("Sending connection details skipped: aggregator integration is disabled.")
        return

    agg_url = get_settings.agg_url
    api_key = get_settings.agg_key
    if not agg_url or agg_url == "None" or not api_key or api_key == "None":
        bot_logger.error("Aggregator URL or API key is not configured. Cannot send connection details.")
        return

    # 1. Получение порта из переменных окружения Docker
    shop_port = os.environ.get('EXTERNAL_PORT')
    if not shop_port:
        bot_logger.error("EXTERNAL_PORT environment variable not set. Cannot send port to aggregator.")
        return

    # 2. Получение публичного IP-адреса
    shop_ip = None
    try:
        session = await arSession.get_session()
        async with session.get("https://api.ipify.org", timeout=10) as response:
            if response.status == 200:
                shop_ip = await response.text()
                bot_logger.info(f"Successfully retrieved public IP: {shop_ip}")
            else:
                bot_logger.error(f"Failed to retrieve public IP. Status: {response.status}")
                return
    except Exception as e:
        bot_logger.error(f"Error while getting public IP: {e}")
        return

    # 3. Отправка данных агрегатору
    shop_id = bot.id
    headers = {"X-Shop-ID": str(shop_id), "X-Api-Key": api_key}
    payload = {"shop_ip": shop_ip, "shop_port": int(shop_port)}
    request_url = f"http://{agg_url}/api/v1/update_connection_details"
    
    try:
        session = await arSession.get_session()
        async with session.post(request_url, json=payload, headers=headers, timeout=20, ssl=False) as response:
            response_text = await response.text()
            log_message = f"Aggregator connection details response | Status: {response.status} | Body: {response_text}"
            
            if response.ok:
                bot_logger.info(log_message)
            else:
                bot_logger.error(log_message)

            # Отправляем полный ответ администраторам для диагностики
            #admin_notification = (f"Ответ от агрегатора при отправке IP/порта:</b>\n\n<b>Статус:</b> <code>{response.status}</code>\n<b>Тело ответа:</b>\n<pre>{html.escape(response_text)}</pre>")
            #admin_notification = (f"Aggregator response when register IP/port: Status: {response.status} body: {html.escape(response_text)}")
            #bot_logger.error(admin_notification)
            #await send_admins(bot, admin_notification)

    except Exception as e:
        bot_logger.error(f"Connection error when sending details to aggregator: {e}")
        await send_admins(bot, f"❌ Ошибка подключения к агрегатору при отправке IP/порта:\n\n<pre>{html.escape(str(e))}</pre>")


# 1. Добавьте эту новую "сердцевинную" функцию
def process_and_save_image_data(image_bytes: bytes) -> str | None:
    """Обрабатывает байты изображения, сжимает и сохраняет их в /media/items/. Возвращает относительный путь только в случае успешного сохранения файла."""
    try:
        # Открываем изображение из байтов
        image = Image.open(BytesIO(image_bytes))
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
        # Формируем путь для сохранения в БД
        save_dir = "items"  # Путь жестко задан для товаров
        filename = f"{uuid.uuid4()}.webp"  # Формируем уникальное имя файла
        relative_path = Path("media") / save_dir / filename
        full_path = (
            BASE_DIR / relative_path
        )  # Формируем АБСОЛЮТНЫЙ путь для физического сохранения файла
        full_path.parent.mkdir(
            parents=True, exist_ok=True
        )  # Убедимся, что директория существует
        image.save(full_path, "WEBP", quality=85)  # Сохраняем файл

        if full_path.exists():  # Проверяем, что файл действительно был создан
            return str(
                relative_path.as_posix()
            )  # Возвращаем относительный путь в виде строки, совместимой с разными ОС
        else:
            bot_logger.error(f"The file was not created using the {full_path} path")
            return None
    except Exception as e:
        bot_logger.error(f"Error when processing and saving the image: {e}")
        return None


async def save_and_compress_photo(message: Message, bot: Bot) -> str | None:
    """ Скачивает фото из Telegram и передает его на обработку. Возвращает относительный путь или None. Изображения сохраняются как товары."""
    photo_to_process: PhotoSize | Document | None = None
    if message.photo:
        photo_to_process = message.photo[-1]
    elif message.document and "image" in message.document.mime_type:
        photo_to_process = message.document
    else:
        return None
    file_in_memory = BytesIO()
    await bot.download(file=photo_to_process.file_id, destination=file_in_memory)
    # Передаем байты в функцию process_and_save_image_data
    return process_and_save_image_data(file_in_memory.getvalue())


#!MARK: Удаления (архивации) файлов
async def archive_old_purchase_files(bot: Bot):
    """#!    Проверяет покупки старше определенного времени в зависимости от свободного места на диске, удаляет связанные файлы изображений и помечает их как архивированные. """
    bot_logger.info("Starting scheduled task: ArchiveOldPurchaseFiles...")

    # Проверяем свободное место на диске
    disk_usage = shutil.disk_usage(BASE_DIR)
    free_space_percent = (disk_usage.free / disk_usage.total) * 100
    bot_logger.info(f"Disk free space: {free_space_percent:.2f}%")

    # Определяем порог времени в зависимости от свободного места
    if free_space_percent < 20:
        threshold_unix = get_unix() - (7 * 24 * 60 * 60)  # 7 
        await send_admins(bot, f"Low disk space detected. Free space: {free_space_percent}. Archiving files older than 7 days.")
        bot_logger.info("Low disk space detected. Archiving files older than 7 days.")
    else:
        threshold_unix = get_unix() - (30 * 24 * 60 * 60)  # 30 дней (месяц)
        bot_logger.info("Sufficient disk space. Archiving files older than 30 days.")

    #! 1. Находим все покупки, которые старше порога и еще не были заархивированы
    purchases_to_archive = Purchasesx.gets(purchase_data_is_archived=0)
    old_purchases = [p for p in purchases_to_archive if p.purchase_unix < threshold_unix]
    if not old_purchases:
        bot_logger.info("ArchiveOldPurchaseFiles: No old purchases to archive.")
        return
    archived_files_count = 0
    processed_purchases_count = 0
    for purchase in old_purchases:
        path_str = purchase.purchase_data
        #! 2. Удаляем файл, если путь начинается с "media/items"
        if path_str and path_str.startswith('media/items'):
            full_path = BASE_DIR / path_str
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
                    bot_logger.debug(f"Deleted archived file: {full_path}")
                    archived_files_count += 1
            except OSError as e:
                bot_logger.error(f"Error deleting image file {full_path}: {e}")
                await send_admins(bot, f"Error deleting image file - {full_path}: {e}")
        #! 3. Обновляем статус в базе данных
        try:
            Purchasesx.update(purchase_receipt=purchase.purchase_receipt, purchase_data_is_archived=1)
            processed_purchases_count += 1
        except Exception as e:
            bot_logger.error(f"Failed to update archive status for receipt {purchase.purchase_receipt}: {e}")
    bot_logger.info(f"ArchiveOldPurchaseFiles finished. Deleted {archived_files_count} image files for {processed_purchases_count} purchases.")


async def notify_aggregator_of_balance_update(bot: Bot, arSession: ARS, user_id: int, new_balance: float):
    """Отправляет PUSH-уведомление в агрегатор об изменении баланса пользователя."""
    get_settings = Settingsx.get()
    if get_settings.send_to_aggregator != "True":
        return

    agg_url = get_settings.agg_url
    api_key = get_settings.agg_key

    if not agg_url or agg_url == "None" or not api_key or api_key == "None":
        bot_logger.warning("notify_aggregator_of_balance_update: Aggregator URL or API key is not set. Skipping.")
        return

    shop_id = bot.id
    headers = {"X-Shop-ID": str(shop_id), "X-Api-Key": api_key}
    payload = {"user_id": user_id, "new_balance": new_balance}
    request_url = f"http://{agg_url}/api/v1/update_user_balance"

    try:
        session = await arSession.get_session()
        async with session.post(request_url, json=payload, headers=headers, timeout=15, ssl=False) as response:
            if response.ok:
                bot_logger.info(f"Successfully notified aggregator of balance update for user {user_id}. New balance: {new_balance}")
            else:
                response_text = await response.text()
                bot_logger.error(f"Failed to notify aggregator of balance update for user {user_id}. Status: {response.status}, Response: {response_text[:100]}")
    except Exception as e:
        bot_logger.error(f"Connection error while notifying aggregator of balance update for user {user_id}: {e}")

