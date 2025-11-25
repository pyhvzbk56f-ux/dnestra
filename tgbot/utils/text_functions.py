# tgbot/utils/text_functions.py

import os
import re
import pytz
import asyncio
import aiohttp
import html
import sqlite3
import traceback
from io import BytesIO
from datetime import datetime
from typing import Union
from aiogram import Bot
from aiogram.types import LinkPreviewOptions, FSInputFile, InlineKeyboardMarkup
from aiogram.utils.markdown import hide_link 
from tgbot.data.config import BOT_TIMEZONE, get_admins, get_operators, BASE_DIR, PATH_DATABASE
from tgbot.services.i18n import Translator
from tgbot.utils.misc.bot_logging import bot_logger

from aiogram.utils.keyboard import InlineKeyboardBuilder


from tgbot.database import (
    Categoryx,
    Invoice,
    Invoicex,
    Itemx,
    Positionx,
    PurchasesModel,
    Purchasesx,
    RefillModel,
    Settingsx,
    UserModel,
    Userx,
    Subcategoryx,
    InvoiceStatus,
)
from tgbot.database.db_helper import dict_factory
from tgbot.keyboards.inline_admin import profile_edit_finl, purchase_manage_finl
from tgbot.keyboards.inline_admin_products import (
    category_edit_open_finl,
    item_delete_finl,
    position_edit_open_finl,
    subcategory_edit_open_finl,
)
from tgbot.keyboards.inline_user import user_profile_finl
from tgbot.keyboards.inline_user_products import products_open_finl
from tgbot.utils.const_functions import (
    convert_date,
    convert_day,
    get_unix,
    PurchaseSource,
)
from tgbot.utils.misc.bot_models import ARS





def _get_top_users_stat(
    cursor: sqlite3.Cursor,
    i18n: Translator,
    locale: str,
    title_key: str,
    query: str,
    value_format: str = "{value}",
) -> str:
    """Выполняет SQL-запрос для получения топа пользователей и форматирует результат."""
    title = i18n.get_text(title_key, locale)
    lines = [f"<b>{title}</b>"]
    try:
        cursor.execute(query)
        results = cursor.fetchall()
        if not results:
            lines.append(f"  - {i18n.get_text('statistics.no_data', locale)}")
        else:
            for i, row in enumerate(results, 1):
                # row - это словарь, так как мы используем dict_factory
                login = html.escape(row.get("user_login", ""))
                user_id = row.get("user_id")
                value = row.get("value") 

                formatted_value = value_format.format(value=value)
                lines.append(
                    f"  <code>{i:02d}.</code> @{login} | ID:<code>{user_id}</code> - <b>{formatted_value}</b>"
                )
    except Exception as e:
        lines.append(f"  - Ошибка: {e}")
    return "\n".join(lines)


async def send_purchase_details(bot: Bot, chat_id: int, purchase: PurchasesModel,i18n: Translator, locale: str,
    caption_template_key: str, source: PurchaseSource,reply_markup: InlineKeyboardMarkup = None, ):
    """ 
    #! Отправка деталей покупки.
    #! Если путь к локальному файлу, отправляет фото и текстовый чек.
    #! Иначе - отправляет только текстовый чек с сырыми данными из бд в конце чека.
    """
    bot_logger.info(f"Starting send_purchase_details for receipt {purchase.purchase_receipt} to chat {chat_id}. Source: {source.value}")
    user = Userx.get(user_id=purchase.user_id)
    get_settings = Settingsx.get()
    misc_info = get_settings.misc_info_check if get_settings.misc_info_check != "None" else ""

    #!  1. Формируем основной текст чека без misc_info (отправим отдельно)
    full_receipt_text = i18n.get_text(
        key=caption_template_key,
        locale=locale,
        source=source.value,
        receipt_id=purchase.purchase_receipt,
        user_id=user.user_id,
        user_name=user.user_name,
        login=f"@{user.user_login}" if user.user_login else "N/A",
        category_name=purchase.purchase_category_name,
        subcategory_name=purchase.purchase_subcategory_name,
        position_name=purchase.purchase_position_name,
        price=purchase.purchase_price,
        balance_before=purchase.user_balance_before,
        balance_after=purchase.user_balance_after,
        purchase_date=convert_date(purchase.purchase_unix),
        rating_status=i18n.get_text(f"purchase_rating.{'success' if purchase.rating == 1 else 'failure' if purchase.rating == -1 else 'pending'}",locale),
        misc_info_check="")
    full_receipt_text = "\n".join(line for line in full_receipt_text.splitlines() if line.strip())

    #!  1.1. Формируем отдельное сообщение с misc_info (только для покупателя)
    misc_info_message = ""
    if misc_info and chat_id == purchase.user_id:  # Отправляем misc_info только покупателю
        misc_info_message = misc_info

    #! 2. Проверяем, был ли файл товара архивирован (удален) 
    if purchase.purchase_data_is_archived == 1:
        bot_logger.info(f"Purchase {purchase.purchase_receipt} is archived. Sending text-only receipt.")
        full_receipt_text += i18n.get_text ("user_products.img_archived", locale) #! Добавляем пометку об архивации
        bot_logger.info(f"Sending text-only receipt for archived purchase {purchase.purchase_receipt}")
        try:
            await bot.send_message(chat_id=chat_id,text=full_receipt_text,reply_markup=reply_markup,link_preview_options=LinkPreviewOptions(is_disabled=True),)
        except Exception as e:
            bot_logger.error(f"Failed to send text-only receipt for archived purchase: User ID: {user.user_id}\n Receipt: {purchase.purchase_receipt}: Error: {e}")
            error_message_for_admins = f"Error: Failed to send text-only receipt for archived purchase.\n\nUser ID: {user.user_id}\n Receipt <code>#{purchase.purchase_receipt}</code>\nError: {html.escape(str(e))}"
            for admin_id in get_admins():
                try:
                    await bot.send_message(admin_id, error_message_for_admins)
                except Exception as admin_send_error:
                    bot_logger.error(f"Failed to send error notification to admin {admin_id}: {admin_send_error}")
        return

    # ! 3. Основная логика отправки на основе содержимого 
    try:
        raw_purchase_data = purchase.purchase_data.strip() if purchase.purchase_data else ""
        bot_logger.info(f"Processing purchase data for receipt {purchase.purchase_receipt}: '{raw_purchase_data[:100]}...'")

        #! Сценарий 1: Если начинается media/items/ - это путь к локальному файлу изображения.
        if raw_purchase_data.startswith("media/items/"):
            bot_logger.info(f"Purchase {purchase.purchase_receipt} identified as local file.")
            full_path = BASE_DIR / raw_purchase_data

            #* Проверяем, существует ли файл на диске
            if os.path.exists(full_path):
                bot_logger.error(f"File found at {full_path}. Attempting to send photo.")
                #* Отправляем фото с полным чеком как подписью
                await bot.send_photo(chat_id=chat_id, photo=FSInputFile(full_path), caption=full_receipt_text, reply_markup=reply_markup)
                bot_logger.info(f"Successfully sent photo for receipt {purchase.purchase_receipt} to {chat_id}.")
            
            else:
                #* Если файл по пути не найден, логируем и отправляем текстовый чек с данными
                bot_logger.error(f"File not found for receipt {purchase.purchase_receipt}. Path: '{full_path}'. Sending text with raw data.")
                error_message_for_admins = f"Error: Failed to send receipt. IMG file not found.\n\nUser ID: {user.user_id}\n Receipt <code>#{purchase.purchase_receipt}</code>\nError:\n<code>{html.escape(raw_purchase_data)}</code>"
                for admin_id in get_admins():
                    try:
                        await bot.send_message(admin_id, error_message_for_admins)
                    except Exception as admin_send_error:
                        bot_logger.error(f"Failed to send error notification to admin {admin_id}: {admin_send_error}")

                content_header = i18n.get_text("user_products.purchase_content", locale)
                full_receipt_text += f"\n\n<b>{content_header} (img not found):</b>\n<code>{html.escape(raw_purchase_data)}</code>"
                await bot.send_message( chat_id=chat_id, text=full_receipt_text, reply_markup=reply_markup, link_preview_options=LinkPreviewOptions(is_disabled=True), )

            #* Отправляем misc_info отдельным сообщением
            if misc_info_message:
                bot_logger.info(f"Sending misc_info message to {chat_id}.")
                await bot.send_message(chat_id=chat_id, text=misc_info_message)
        
        #! Сценарий 2: Не локальный файл (текст, URL, координаты и т.д.).
        else:
            bot_logger.info(f"Purchase {purchase.purchase_receipt} identified as text/URL.")
            if raw_purchase_data:
                #* Если данные есть, добавляем их в конец текстового чека
                content_header = i18n.get_text("user_products.purchase_content", locale)
                #* Используем html.escape для безопасного отображения любых символов
                full_receipt_text += f"\n\n<b>{content_header}</b>\n<code>{html.escape(raw_purchase_data)}</code>"
            bot_logger.info(f"Attempting to send text receipt to {chat_id}.")
            await bot.send_message(chat_id=chat_id,text=full_receipt_text,reply_markup=reply_markup,link_preview_options=LinkPreviewOptions(is_disabled=True),)
            bot_logger.info(f"Successfully sent text receipt for {purchase.purchase_receipt} to {chat_id}.")


            #* Отправляем misc_info отдельным сообщением
            if misc_info_message:
                bot_logger.info(f"Sending misc_info message to {chat_id}.")
                await bot.send_message(chat_id=chat_id, text=misc_info_message)
            
    except Exception as e:
        #* Общий обработчик ошибок на случай непредвиденных проблем
        
        bot_logger.critical(f"CRITICAL: Failed to send purchase details for receipt {purchase.purchase_receipt} to {chat_id}. Error: {e}", exc_info=True)
        #* Отправляем уведомление админам с деталями ошибки
        #error_message_for_admins = f"Error: Failed to send purchase details:\n\nUser ID: {user.user_id}\n Receipt <code>#{purchase.purchase_receipt}</code>\nError: {e}"
        #for admin_id in get_admins():
        #    try:
        #        await bot.send_message(admin_id, error_message_for_admins)
        #    except Exception as admin_send_error:
        #        bot_logger.error(f"Failed to send error notification to admin {admin_id}: {admin_send_error}")

        #* В случае любой ошибки, отправляем пользователю хотя бы текстовый чек
        try:
            bot_logger.critical(f"Attempting to send fallback text receipt to {chat_id} after error.")
            await bot.send_message(chat_id, full_receipt_text, reply_markup=reply_markup)
        except Exception as fallback_e:
            bot_logger.critical(f"Failed to send even the fallback message to {chat_id} for receipt {purchase.purchase_receipt}: {fallback_e}")
        




################################################################################
################################# ПОЛЬЗОВАТЕЛЬ #################################
#! Открытие профиля пользователем
async def open_profile_user(
    bot: Bot, user_id: Union[int, str], i18n: Translator, locale: str
):
    get_purchases = Purchasesx.gets(user_id=user_id)
    get_user = Userx.get(user_id=user_id)
    how_days = int(get_unix() - get_user.user_unix) // 60 // 60 // 24
    #! Расчёты статистики по покупкам
    count_items = sum([purchase.purchase_count for purchase in get_purchases])
    successful_count = sum(1 for p in get_purchases if p.rating == 1)
    failed_count = sum(1 for p in get_purchases if p.rating == -1)
    total_rated_count = successful_count + failed_count
    if total_rated_count > 0:
        successful_percentage = round((successful_count / count_items) * 100)
        failed_percentage = round((failed_count / count_items) * 100)
    else:
        successful_percentage = 0
        failed_percentage = 0

    send_text = i18n.get_text(
        "user_profile.text",
        locale,
        user_id=get_user.user_id,
        balance=get_user.user_balance,
        count_items=count_items,
        successful_count=successful_count,
        successful_percentage=successful_percentage,
        failed_count=failed_count,
        failed_percentage=failed_percentage,
        registration_date=convert_date(get_user.user_unix, False, False),
        days_since_reg=convert_day(how_days, i18n, locale),
        pieces=i18n.get_text("words.pieces_abbr", locale),
    )
    await bot.send_message(
        chat_id=user_id,
        text=send_text,
        reply_markup=user_profile_finl(i18n, locale),
    )


#! Открытие позиции пользователем
async def position_open_user(
    bot: Bot,
    user_id: int,
    position_id: Union[str, int],
    remover: Union[str, int],
    i18n: Translator,
    locale: str,
):
    get_position = Positionx.get(position_id=position_id)
    get_category = Categoryx.get(category_id=get_position.category_id)
    get_subcategory = Subcategoryx.get(subcategory_id=get_position.subcategory_id)

    if get_position.position_desc != "None":
        description_block = i18n.get_text(
            "product_purchase.description_line",
            locale,
            description=get_position.position_desc,
        )
    else:
        description_block = ""

    send_text = i18n.get_text(
        "product_purchase.text",
        locale,
        hidden_link=hide_link(get_position.position_photo),
        position_name=get_position.position_name,
        category_name=get_category.category_name,
        price=get_position.position_price,
        description_block=description_block,
    )

    await bot.send_message(
        chat_id=user_id,
        text=send_text,
        link_preview_options=LinkPreviewOptions(
            show_above_text=True,
        ),
        reply_markup=products_open_finl(
            get_position.position_id,
            # get_position.category_id,
            # get_position.subcategory_id,
            remover,
            i18n,
            locale,
        ),
    )


################################################################################
#################################### АДМИН #####################################
#! Открытие профиля админом
async def open_profile_admin(
    bot: Bot, user_id: int, get_user: UserModel, i18n: Translator, locale: str
):
    get_purchases = Purchasesx.gets(user_id=get_user.user_id)
    get_all_invoices = Invoicex.gets(user_id=get_user.user_id)
    get_paid_invoices = Invoicex.gets(user_id=get_user.user_id, status="finished")

    invoices_issued_count = len(get_all_invoices)
    invoices_paid_count = len(get_paid_invoices)

    how_days = int(get_unix() - get_user.user_unix) // 60 // 60 // 24
    count_items = sum([purchase.purchase_count for purchase in get_purchases])
    user_status_key = (
        "user_status.active" if get_user.user_blocked == 0 else "user_status.blocked"
    )
    user_status = i18n.get_text(user_status_key, locale)

    #! Расчёты статистики по покупкам
    count_items = sum(purchase.purchase_count for purchase in get_purchases)
    successful_count = sum(1 for p in get_purchases if p.rating == 1)
    failed_count = sum(1 for p in get_purchases if p.rating == -1)
    total_rated_count = successful_count + failed_count
    total_unrated_count = count_items - total_rated_count

    if total_unrated_count > 0:
        unrated_percentage = round((total_unrated_count / count_items) * 100)
    else:
        unrated_percentage = 0

    if total_rated_count > 0:
        successful_percentage = round((successful_count / count_items) * 100)
        failed_percentage = round((failed_count / count_items) * 100)
    else:
        successful_percentage = 0
        failed_percentage = 0

    send_text = i18n.get_text(
        "admin_user_profile.text",
        locale,
        user_id=get_user.user_id,
        user_name=get_user.user_name,
        user_status=user_status,
        user_login=get_user.user_login,
        registration_date=convert_date(get_user.user_unix, False, False),
        days_since_reg=convert_day(how_days, i18n, locale),
        balance=get_user.user_balance,
        total_given=get_user.user_give,
        total_refilled=get_user.user_refill,
        invoices_issued=invoices_issued_count,
        invoices_paid=invoices_paid_count,
        items_bought=count_items,
        successful_count=successful_count,
        successful_percentage=successful_percentage,
        failed_count=failed_count,
        failed_percentage=failed_percentage,
        unrated_count=total_unrated_count,
        unrated_percentage=unrated_percentage,
        pieces=i18n.get_text("words.pieces_abbr", locale),
    )

    await bot.send_message(
        chat_id=user_id,
        text=send_text,
        reply_markup=profile_edit_finl(get_user.user_id, i18n, locale),
    )


#! Открытие пополнения админом
async def refill_open_admin(
    bot: Bot, user_id: int, get_refill: RefillModel, i18n: Translator, locale: str
):
    get_user = Userx.get(user_id=get_refill.user_id)

    if get_refill.refill_method in ["Form", "Nickname", "Number", "QIWI"]:
        pay_method = i18n.get_text("payment_methods.qiwi", locale)
    elif get_refill.refill_method == "Yoomoney":
        pay_method = i18n.get_text("payment_methods.yoomoney", locale)
    elif get_refill.refill_method == "Cryptobot":
        pay_method = i18n.get_text("payment_methods.cryptobot", locale)
    else:
        pay_method = f"{get_refill.refill_method}"

    send_text = i18n.get_text(
        "admin_refill_receipt.text",
        locale,
        receipt_id=get_refill.refill_receipt,
        user_id=get_user.user_id,
        user_name=get_user.user_name,
        amount=get_refill.refill_amount,
        payment_method=pay_method,
        comment=get_refill.refill_comment,
        refill_date=convert_date(get_refill.refill_unix),
    )

    await bot.send_message(
        chat_id=user_id,
        text=send_text,
    )


#!######################################################################
#! Клавиатура для управления счетом админом
def invoice_admin_keyboard(invoice: Invoice, i18n: Translator, locale: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if invoice.status in [InvoiceStatus.PENDING, InvoiceStatus.REJECT]:
        builder.button(
            text=i18n.get_text("buttons.manual_confirm", locale),
            callback_data=f"admin_confirm_invoice:{invoice.id}",
        )
    return builder.as_markup()

#! Открытие счета админом
async def invoice_open_admin(
    bot: Bot, user_id: int, get_invoice: Invoice, i18n: Translator, locale: str
):

    get_user = Userx.get(user_id=get_invoice.user_id)

    #! Формируем блок с информацией о валюте
    currency_details = ""
    if get_invoice.currency == "LTC":
        currency_details = i18n.get_text(
            "admin_invoice.ltc_details",
            locale,
            amount_ltc=get_invoice.amount_ltc,
            ltc_address=get_invoice.ltc_address,
        )
    elif get_invoice.currency == "USDT":
        currency_details = i18n.get_text(
            "admin_invoice.usdt_details",
            locale,
            amount_usdt=get_invoice.amount_usdt,
            usdt_address=get_invoice.usdt_address,
        )

    #! Формируем информацию о дате пополнения
    if get_invoice.payed_at:
        payed_at_text = i18n.get_text(
            "admin_invoice.payment_date_line",
            locale,
            payment_date=convert_date(get_invoice.payed_at),
        )
    else:
        payed_at_text = i18n.get_text("admin_invoice.payment_date_unpaid", locale)

    send_text = i18n.get_text(
        "admin_invoice.text",
        locale,
        invoice_id=get_invoice.id,
        status=get_invoice.status.value,
        amount_usd=get_invoice.amount_usd,
        currency_details=currency_details,
        creation_date=convert_date(get_invoice.created_at),
        payment_date_text=payed_at_text,
        user_id=get_user.user_id,
        user_login=get_user.user_login,
        user_name=get_user.user_name,
    )

    await bot.send_message(
        chat_id=user_id,
        text=send_text,
        reply_markup=invoice_admin_keyboard(get_invoice, i18n, locale),
    )


#! Открытие покупки админом


async def purchase_open_admin(
    bot: Bot,
    arSession: ARS,
    user_id: int,
    get_purchase: PurchasesModel,
    i18n: Translator,
    locale: str,
):
    # функция вызывает универсальную функцию для отправки деталей покупки
    await send_purchase_details(bot=bot,
        chat_id=user_id,
        purchase=get_purchase,
        i18n=i18n,locale=locale,
        caption_template_key="admin_purchase.receipt_full",  # Используем шаблон для админа
        source=PurchaseSource.BOT,
        reply_markup=purchase_manage_finl(str(get_purchase.purchase_receipt), i18n, locale),
    )



#! Открытие категории админом
async def category_open_admin(
    bot: Bot,
    user_id: int,
    category_id: Union[str, int],
    remover: int,
    i18n: Translator,
    locale: str,
):
    profit_amount_all, profit_amount_day, profit_amount_week, profit_amount_month = (
        0,
        0,
        0,
        0,
    )
    profit_count_all, profit_count_day, profit_count_week, profit_count_month = (
        0,
        0,
        0,
        0,
    )

    get_items = Itemx.gets(category_id=category_id)
    get_category = Categoryx.get(category_id=category_id)
    get_positions = Positionx.gets(category_id=category_id)
    get_subcategories = Subcategoryx.gets(category_id=category_id)
    get_purchases = Purchasesx.gets(purchase_category_id=category_id)
    get_settings = Settingsx.get()

    for purchase in get_purchases:
        profit_amount_all += purchase.purchase_price
        profit_count_all += purchase.purchase_count

        if purchase.purchase_unix - get_settings.misc_profit_day >= 0:
            profit_amount_day += purchase.purchase_price
            profit_count_day += purchase.purchase_count
        if purchase.purchase_unix - get_settings.misc_profit_week >= 0:
            profit_amount_week += purchase.purchase_price
            profit_count_week += purchase.purchase_count
        if purchase.purchase_unix - get_settings.misc_profit_month >= 0:
            profit_amount_month += purchase.purchase_price
            profit_count_month += purchase.purchase_count

    send_text = i18n.get_text(
        "admin_category.text",
        locale,
        category_name=get_category.category_name,
        subcategories_count=len(get_subcategories),
        positions_count=len(get_positions),
        items_count=len(get_items),
        creation_date=convert_date(get_category.category_unix),
        pieces=i18n.get_text("words.pieces_abbr", locale),
    )

    await bot.send_message(
        chat_id=user_id,
        text=send_text,
        reply_markup=await category_edit_open_finl(
            bot, int(category_id), remover, i18n, locale
        ),
    )


async def subcategory_open_admin(
    bot: Bot,
    user_id: int,
    category_id: int,
    subcategory_id: int,
    remover: int,
    i18n: Translator,
    locale: str,
):
    get_subcategory = Subcategoryx.get(
        category_id=category_id, subcategory_id=subcategory_id
    )
    get_category = Categoryx.get(category_id=category_id)
    send_text = i18n.get_text(
        "admin_subcategory.text",
        locale,
        category_name=get_category.category_name,
        subcategory_name=get_subcategory.subcategory_name,
        creation_date=datetime.fromtimestamp(get_subcategory.subcategory_time).strftime(
            "%d.%m.%Y %H:%M:%S"
        ),
    )
    await bot.send_message(
        user_id,
        text=send_text,
        reply_markup=await subcategory_edit_open_finl(
            bot, category_id, subcategory_id, remover, i18n, locale
        ),
    )


#! Открытие позиции админом
async def position_open_admin(
    bot: Bot, user_id: int, position_id: Union[str, int], i18n: Translator, locale: str
):
    get_position = Positionx.get(position_id=position_id)
    get_items = Itemx.gets(position_id=position_id)

    get_category = Categoryx.get(category_id=get_position.category_id)
    get_subcategory = Subcategoryx.get(subcategory_id=get_position.subcategory_id)

    position_desc = (
        get_position.position_desc
        if get_position.position_desc != "None"
        else i18n.get_text("common.absent", locale)
    )

    get_pieces = i18n.get_text("words.pieces_abbr", locale)

    send_text = i18n.get_text(
        "admin_position.text",
        locale,
        category_name=get_category.category_name,
        subcategory_name=get_subcategory.subcategory_name,
        position_name=get_position.position_name,
        price=get_position.position_price,
        items_count=len(get_items),
        creation_date=convert_date(get_position.position_unix),
        description=position_desc,
        pieces=get_pieces,
    )

    await bot.send_message(
        chat_id=user_id,
        text=send_text,
        reply_markup=await position_edit_open_finl(
            bot, get_position.position_id, get_position.category_id, 0, i18n, locale
        ),
    )  # link_preview_options=LinkPreviewOptions(show_above_text=True,),


#! Открытие товара админом
async def item_open_admin(
    bot: Bot,
    user_id: int,
    item_id: Union[str, int],
    remover: int,
    i18n: Translator,
    locale: str,
):
    get_item = Itemx.get(item_id=item_id)

    get_position = Positionx.get(position_id=get_item.position_id)
    get_category = Categoryx.get(category_id=get_item.category_id)
    get_subcategory = Subcategoryx.get(subcategory_id=get_item.subcategory_id)

    send_text = i18n.get_text(
        "admin_item.text",
        locale,
        category_name=get_category.category_name,
        subcategory_name=get_subcategory.subcategory_name,
        position_name=get_position.position_name,
        creation_date=convert_date(get_item.item_unix),
        item_data=get_item.item_data,
    )

    await bot.send_message(
        chat_id=user_id,
        text=send_text,
        reply_markup=item_delete_finl(
            get_item.item_id, get_item.position_id, get_item.category_id, i18n, locale
        ),
    )


################################################################################
#! Статистика бота
def get_statistics(i18n: Translator, locale: str) -> tuple[str, str, str, str, str, str, str, str, str, str, str, str, str]:
    """#! Собирает и возвращает статистику по боту в текстовом формате."""
    # Суммы дохода
    profit_amount_all, profit_amount_day, profit_amount_week, profit_amount_month = (0,0,0,0,)

    # Количество продаж
    profit_count_all, profit_count_day, profit_count_week, profit_count_month = (0,0,0,0,)

    # Метрики пользователей
    (
        users_all,
        users_all_blocked,
        users_day,
        users_week,
        users_month,
        users_money_have,
        users_money_give,
    ) = 0, 0, 0, 0, 0, 0, 0

    # Счетчики покупателей
    buyers_all, buyers_day, buyers_week, buyers_month = 0, 0, 0, 0

    # Средства в системе без админ балансов
    users_money_have_clear = 0

    # Счётчики для пополнений общий
    total_refill_count_all, total_refill_amount_all = 0, 0
    total_refill_count_day, total_refill_amount_day = 0, 0
    total_refill_count_week, total_refill_amount_week = 0, 0
    total_refill_count_month, total_refill_amount_month = 0, 0

    # Счётчики для пополнений по LTC
    ltc_refill_count_all, ltc_refill_amount_all = 0, 0
    ltc_refill_count_day, ltc_refill_amount_day = 0, 0
    ltc_refill_count_week, ltc_refill_amount_week = 0, 0
    ltc_refill_count_month, ltc_refill_amount_month = 0, 0

    # Счётчики для пополнений по USDT
    usdt_refill_count_all, usdt_refill_amount_all = 0, 0
    usdt_refill_count_day, usdt_refill_amount_day = 0, 0
    usdt_refill_count_week, usdt_refill_amount_week = 0, 0
    usdt_refill_count_month, usdt_refill_amount_month = 0, 0

    # Множества для хранения уникальных покупателей по периодам
    unique_buyers_all, unique_buyers_day, unique_buyers_week, unique_buyers_month = (
        set(),
        set(),
        set(),
        set(),
    )

    # Получение всех данных из базы
    get_categories = Categoryx.get_all()  # Все категории
    get_subcategories = Subcategoryx.get_all()  # Все подкатегории
    get_positions = Positionx.get_all()  # Все позиции
    get_purchases = Purchasesx.get_all()  # Все покупки
    get_items = Itemx.get_all()  # Все товары
    get_users = Userx.get_all()  # Все пользователи
    get_settings = Settingsx.get()  # Настройки системы
    get_invoices = Invoicex.get_all()  # Все счета

    # Счётчики для оценок покупок
    success_all, success_day, success_week, success_month = 0, 0, 0, 0  # Успешные
    failure_all, failure_day, failure_week, failure_month = 0, 0, 0, 0  # Провальные
    unrated_all, unrated_day, unrated_week, unrated_month = 0, 0, 0, 0  # Без оценки

    # Общее кол-во покупок
    total_purchases_day, total_purchases_week, total_purchases_month = 0, 0, 0
    total_purchases_all = len(get_purchases)

    # Обработка покупок
    for purchase in get_purchases:
        profit_amount_all += purchase.purchase_price  # Суммируем общий доход
        profit_count_all += purchase.purchase_count  # Считаем общее количество продаж

        # Добавляем покупателя в множество за все время
        unique_buyers_all.add(purchase.user_id)
        buyers_all = len(unique_buyers_all)

        # Статистика по оценкам
        if purchase.rating == 1:
            success_all += 1
        elif purchase.rating == -1:
            failure_all += 1
        else:
            unrated_all += 1

        # Проверяем временные периоды для статистики
        if purchase.purchase_unix - get_settings.misc_profit_day >= 0:
            profit_amount_day += purchase.purchase_price
            profit_count_day += purchase.purchase_count
            unique_buyers_day.add(purchase.user_id)
            buyers_day = len(unique_buyers_day)
            total_purchases_day += 1
            if purchase.rating == 1:
                success_day += 1
            elif purchase.rating == -1:
                failure_day += 1
            else:
                unrated_day += 1

        if purchase.purchase_unix - get_settings.misc_profit_week >= 0:
            profit_amount_week += purchase.purchase_price
            profit_count_week += purchase.purchase_count
            unique_buyers_week.add(purchase.user_id)
            buyers_week = len(unique_buyers_week)
            total_purchases_week += 1
            if purchase.rating == 1:
                success_week += 1
            elif purchase.rating == -1:
                failure_week += 1
            else:
                unrated_week += 1

        if purchase.purchase_unix - get_settings.misc_profit_month >= 0:
            profit_amount_month += purchase.purchase_price
            profit_count_month += purchase.purchase_count
            unique_buyers_month.add(purchase.user_id)
            buyers_month = len(unique_buyers_month)
            total_purchases_month += 1
            if purchase.rating == 1:
                success_month += 1
            elif purchase.rating == -1:
                failure_month += 1
            else:
                unrated_month += 1

    # Обработка счетов (пополнений)
    for invoice in get_invoices:
        if invoice.status == "finished":
            # Общая статистика пополнений
            total_refill_amount_all += invoice.amount_usd
            total_refill_count_all += 1

            if invoice.created_at >= get_settings.misc_profit_day:
                total_refill_amount_day += invoice.amount_usd
                total_refill_count_day += 1
            if invoice.created_at >= get_settings.misc_profit_week:
                total_refill_amount_week += invoice.amount_usd
                total_refill_count_week += 1
            if invoice.created_at >= get_settings.misc_profit_month:
                total_refill_amount_month += invoice.amount_usd
                total_refill_count_month += 1

            # Статистика по LTC
            if invoice.currency == "LTC":
                ltc_refill_amount_all += invoice.amount_usd
                ltc_refill_count_all += 1
                if invoice.created_at >= get_settings.misc_profit_day:
                    ltc_refill_amount_day += invoice.amount_usd
                    ltc_refill_count_day += 1
                if invoice.created_at >= get_settings.misc_profit_week:
                    ltc_refill_amount_week += invoice.amount_usd
                    ltc_refill_count_week += 1
                if invoice.created_at >= get_settings.misc_profit_month:
                    ltc_refill_amount_month += invoice.amount_usd
                    ltc_refill_count_month += 1

            # Статистика по USDT
            elif invoice.currency == "USDT":
                usdt_refill_amount_all += invoice.amount_usd
                usdt_refill_count_all += 1
                if invoice.created_at >= get_settings.misc_profit_day:
                    usdt_refill_amount_day += invoice.amount_usd
                    usdt_refill_count_day += 1
                if invoice.created_at >= get_settings.misc_profit_week:
                    usdt_refill_amount_week += invoice.amount_usd
                    usdt_refill_count_week += 1
                if invoice.created_at >= get_settings.misc_profit_month:
                    usdt_refill_amount_month += invoice.amount_usd
                    usdt_refill_count_month += 1

    #! Обработка пользователей
    for user in get_users:
        if user.user_balance > 50:
            bot_logger.info(
                f"Balance > 50 : Name: {user.user_name}, ID: {user.user_id}, Balance: {user.user_balance}"
            )
        if not user.user_blocked:  # Проверяем что пользователь не забанен
            if user.user_balance > 0:
                users_money_have += user.user_balance  # Суммируем средства на балансах только незабаненных пользователей и у кого нет минуса
            users_money_give += user.user_give  # Суммируем выданные средства
            users_all += 1  # Считаем общее количество пользователей не в блоке
            # Проверяем временные периоды для статистики пользователей
            if user.user_unix - get_settings.misc_profit_day >= 0:
                users_day += 1
            if user.user_unix - get_settings.misc_profit_week >= 0:
                users_week += 1
            if user.user_unix - get_settings.misc_profit_month >= 0:
                users_month += 1
        else:
            users_all_blocked += 1

    # Считаем балансы администраторов и вычитаем их из общего баланса
    for admin in get_admins():
        admin_info = Userx.get(user_id=admin)
        bot_logger.info(
            f"Admin balance : Name: {admin_info.user_name}, ID: {admin_info.user_id}, Balance: {admin_info.user_balance}"
        )
        users_money_have_clear -= admin_info.user_balance

    #! Подготовка данных для отображения дат
    all_days = [
        i18n.get_text("weekdays.monday", locale),
        i18n.get_text("weekdays.tuesday", locale),
        i18n.get_text("weekdays.wednesday", locale),
        i18n.get_text("weekdays.thursday", locale),
        i18n.get_text("weekdays.friday", locale),
        i18n.get_text("weekdays.saturday", locale),
        i18n.get_text("weekdays.sunday", locale),
    ]
    all_months = [
        i18n.get_text("months.january", locale),
        i18n.get_text("months.february", locale),
        i18n.get_text("months.march", locale),
        i18n.get_text("months.april", locale),
        i18n.get_text("months.may", locale),
        i18n.get_text("months.june", locale),
        i18n.get_text("months.july", locale),
        i18n.get_text("months.august", locale),
        i18n.get_text("months.september", locale),
        i18n.get_text("months.october", locale),
        i18n.get_text("months.november", locale),
        i18n.get_text("months.december", locale),
    ]

    # Получение текущих дат
    now_day = datetime.now().day
    now_week = datetime.now().weekday()
    now_month = datetime.now().month
    now_year = datetime.now().year

    # Расчет временных меток для статистики
    unix_day = int(
        datetime.strptime(
            f"{now_day}.{now_month}.{now_year} 0:0:0", "%d.%m.%Y %H:%M:%S"
        ).timestamp()
    )
    unix_week = unix_day - (now_week * 86400)

    # Получение дат для недельной статистики
    week_day = int(
        datetime.fromtimestamp(unix_week, pytz.timezone(BOT_TIMEZONE)).strftime("%d")
    )
    week_month = int(
        datetime.fromtimestamp(unix_week, pytz.timezone(BOT_TIMEZONE)).strftime("%m")
    )
    week_week = int(
        datetime.fromtimestamp(unix_week, pytz.timezone(BOT_TIMEZONE)).weekday()
    )

    # Расчет сумм для категорий, подкатегорий и позиций
    # Словари для хранения сумм
    category_sums = {}  # Суммы по категориям
    subcategory_sums = {}  # Суммы по подкатегориям
    position_sums = {}  # Суммы по позициям

    # Словари для хранения количества товаров
    category_items_count = {}  # Количество товаров по категориям
    subcategory_items_count = {}  # Количество товаров по подкатегориям
    position_items_count = {}  # Количество товаров по позициям

    # Общая сумма всех товаров и общее количество товаров
    total_items_sum = 0
    total_items_count = len(get_items)

    # Создаем словари для быстрого доступа к названиям категорий и подкатегорий
    category_names = {cat.category_id: cat.category_name for cat in get_categories}
    subcategory_names = {
        sub.subcategory_id: sub.subcategory_name for sub in get_subcategories
    }

    # Вычисляем суммы для каждой позиции
    for position in get_positions:
        # Получаем все товары для текущей позиции
        position_items = Itemx.gets(position_id=position.position_id)
        pos_items_count = len(position_items)

        # Пропускаем позиции без товаров
        if pos_items_count == 0:
            continue

        # Рассчитываем сумму позиции (количество товаров * цена позиции)
        position_sum = pos_items_count * position.position_price
        # Сохраняем сумму и количество для позиции
        position_sums[position.position_id] = position_sum
        position_items_count[position.position_id] = pos_items_count

        # Добавляем сумму и количество позиции к сумме и количеству категории
        if position.category_id not in category_sums:
            category_sums[position.category_id] = 0
            category_items_count[position.category_id] = 0
        category_sums[position.category_id] += position_sum
        category_items_count[position.category_id] += pos_items_count

        # Добавляем сумму и количество позиции к сумме и количеству подкатегории, если она есть
        if position.subcategory_id:
            if position.subcategory_id not in subcategory_sums:
                subcategory_sums[position.subcategory_id] = 0
                subcategory_items_count[position.subcategory_id] = 0
            subcategory_sums[position.subcategory_id] += position_sum
            subcategory_items_count[position.subcategory_id] += (
                pos_items_count  # Используем переименованную переменную
            )

        # Суммируем общую стоимость всех товаров
        total_items_sum += position_sum

    # Получаем только непустые категории (с товарами)
    non_empty_categories = [
        cat for cat in get_categories if cat.category_id in category_items_count
    ]
    # Получаем только непустые подкатегории (с товарами)
    non_empty_subcategories = [
        subcat
        for subcat in get_subcategories
        if subcat.subcategory_id in subcategory_items_count
    ]
    # Получаем только непустые позиции (с товарами)
    non_empty_positions = [
        pos for pos in get_positions if pos.position_id in position_items_count
    ]

    #! Формируем блоки текста для каждого типа товаров
    #! Категории
    categories_text = (
        i18n.get_text(
            "statistics.products_table_header",
            locale,
            type=i18n.get_text("statistics.products_categories", locale),
            count=len(non_empty_categories),
            sum_text=i18n.get_text("statistics.products_sum", locale),
            total_sum=total_items_sum,
            units_text=i18n.get_text("statistics.products_units", locale),
            total_units=total_items_count,
        )
        + "\n"
    )
    for category in non_empty_categories:
        category_sum = category_sums.get(category.category_id, 0)
        category_count = category_items_count.get(category.category_id, 0)
        categories_text += (
            f"| {category.category_name} | {category_sum} | {category_count} шт. |\n"
        )

    #! Подкатегории
    subcategories_text = (
        "\n"
        + i18n.get_text(
            "statistics.products_table_header",
            locale,
            type=i18n.get_text("statistics.products_subcategories", locale),
            count=len(non_empty_subcategories),
            sum_text=i18n.get_text("statistics.products_sum", locale),
            total_sum=total_items_sum,
            units_text=i18n.get_text("statistics.products_units", locale),
            total_units=total_items_count,
        )
        + "\n"
    )
    for subcategory in non_empty_subcategories:
        subcategory_sum = subcategory_sums.get(subcategory.subcategory_id, 0)
        subcategory_count = subcategory_items_count.get(subcategory.subcategory_id, 0)
        parent_category = category_names.get(
            subcategory.category_id, i18n.get_text("common.unknown_category", locale)
        )
        subcategories_text += f"| {subcategory.subcategory_name} | {parent_category} | {subcategory_sum}  | {subcategory_count} шт. |\n"

    #! Позиции
    positions_text = (
        "\n"
        + i18n.get_text(
            "statistics.products_table_header",
            locale,
            type=i18n.get_text("statistics.products_positions", locale),
            count=len(non_empty_positions),
            sum_text=i18n.get_text("statistics.products_sum", locale),
            total_sum=total_items_sum,
            units_text=i18n.get_text("statistics.products_units", locale),
            total_units=total_items_count,
        )
        + "\n"
    )
    for position in non_empty_positions:
        position_sum = position_sums.get(position.position_id, 0)
        position_count = position_items_count.get(position.position_id, 0)
        parent_category = category_names.get(
            position.category_id, i18n.get_text("common.unknown_category", locale)
        )
        parent_subcategory = (
            subcategory_names.get(
                position.subcategory_id, i18n.get_text("common.no_subcategory", locale)
            )
            if position.subcategory_id
            else i18n.get_text("common.no_subcategory", locale)
        )
        positions_text += f"| {position.position_name} | {parent_subcategory} | {parent_category} | {position_sum} | {position_count} шт. |\n"

    #! Оборачиваем каждый блок в свернутую цитату
    stat_categories = f"<blockquote expandable><b>{i18n.get_text('reply_admin.items', locale)}</b>\n{categories_text}</blockquote>"
    stat_subcategories = f"<blockquote expandable>{subcategories_text}</blockquote>"
    stat_positions = f"<blockquote expandable>{positions_text}</blockquote>"
    stat_items = f"<blockquote expandable>{i18n.get_text('statistics.products_items', locale)}: {total_items_count} шт. | {i18n.get_text('statistics.products_sum', locale)} - {total_items_sum} </blockquote>"

    users_stat_body = "\n".join(
        [
            f"<blockquote expandable><b>{i18n.get_text('statistics.users_header', locale)}</b>",
            i18n.get_text("statistics.by_day", locale, value=users_day),
            i18n.get_text("statistics.by_week", locale, value=users_week),
            i18n.get_text("statistics.by_month", locale, value=users_month),
            i18n.get_text("statistics.by_all_time", locale, value=users_all),
            i18n.get_text("statistics.blocked", locale, count=users_all_blocked),
            "",
            f"<b>{i18n.get_text('statistics.buyers_header', locale)}</b>",
            i18n.get_text("statistics.by_day", locale, value=buyers_day),
            i18n.get_text("statistics.by_week", locale, value=buyers_week),
            i18n.get_text("statistics.by_month", locale, value=buyers_month),
            i18n.get_text("statistics.by_all_time", locale, value=buyers_all),
            "</blockquote>",
        ]
    )
    users_stat = f"<b>{i18n.get_text('statistics.main_header', locale)}</b>\n➖➖➖➖\n{users_stat_body}"

    money_stat_body = "\n".join(
        [
            f"<blockquote expandable><b>{i18n.get_text('statistics.funds_header', locale)}</b>",
            i18n.get_text("statistics.sales_header", locale),
            f"  {i18n.get_text('statistics.by_day', locale, value=i18n.get_text('statistics.sales_line', locale, count=profit_count_day, amount=profit_amount_day))}",
            f"  {i18n.get_text('statistics.by_week', locale, value=i18n.get_text('statistics.sales_line', locale, count=profit_count_week, amount=profit_amount_week))}",
            f"  {i18n.get_text('statistics.by_month', locale, value=i18n.get_text('statistics.sales_line', locale, count=profit_count_month, amount=profit_amount_month))}",
            f"  {i18n.get_text('statistics.by_all_time', locale, value=i18n.get_text('statistics.sales_line', locale, count=profit_count_all, amount=profit_amount_all))}",
            "",
            i18n.get_text("statistics.refills_total_header", locale),
            f"  {i18n.get_text('statistics.by_all_time', locale, value=i18n.get_text('statistics.refills_line', locale, count=total_refill_count_all, amount=total_refill_amount_all))}",
            f"  {i18n.get_text('statistics.by_day', locale, value=i18n.get_text('statistics.refills_line', locale, count=total_refill_count_day, amount=total_refill_amount_day))}",
            f"  {i18n.get_text('statistics.by_week', locale, value=i18n.get_text('statistics.refills_line', locale, count=total_refill_count_week, amount=total_refill_amount_week))}",
            f"  {i18n.get_text('statistics.by_month', locale, value=i18n.get_text('statistics.refills_line', locale, count=total_refill_count_month, amount=total_refill_amount_month))}",
            "",
            i18n.get_text("statistics.refills_ltc_header", locale),
            f"  {i18n.get_text('statistics.by_all_time', locale, value=i18n.get_text('statistics.refills_line', locale, count=ltc_refill_count_all, amount=ltc_refill_amount_all))}",
            f"  {i18n.get_text('statistics.by_day', locale, value=i18n.get_text('statistics.refills_line', locale, count=ltc_refill_count_day, amount=ltc_refill_amount_day))}",
            f"  {i18n.get_text('statistics.by_week', locale, value=i18n.get_text('statistics.refills_line', locale, count=ltc_refill_count_week, amount=ltc_refill_amount_week))}",
            f"  {i18n.get_text('statistics.by_month', locale, value=i18n.get_text('statistics.refills_line', locale, count=ltc_refill_count_month, amount=ltc_refill_amount_month))}",
            "",
            i18n.get_text("statistics.refills_usdt_header", locale),
            f"  {i18n.get_text('statistics.by_all_time', locale, value=i18n.get_text('statistics.refills_line', locale, count=usdt_refill_count_all, amount=usdt_refill_amount_all))}",
            f"  {i18n.get_text('statistics.by_day', locale, value=i18n.get_text('statistics.refills_line', locale, count=usdt_refill_count_day, amount=usdt_refill_amount_day))}",
            f"  {i18n.get_text('statistics.by_week', locale, value=i18n.get_text('statistics.refills_line', locale, count=usdt_refill_count_week, amount=usdt_refill_amount_week))}",
            f"  {i18n.get_text('statistics.by_month', locale, value=i18n.get_text('statistics.refills_line', locale, count=usdt_refill_count_month, amount=usdt_refill_amount_month))}",
            "",
            i18n.get_text("statistics.other_funds_header", locale),
            "  ",
            f"  {i18n.get_text('statistics.funds_given', locale, amount=users_money_give)}",
            f"  {i18n.get_text('statistics.funds_in_system', locale, amount=users_money_have)}",
            f"  {i18n.get_text('statistics.funds_clear', locale, amount=users_money_have_clear)}",
            "</blockquote>",
        ]
    )
    money_stat = money_stat_body

    #! Блок Покупки (с оценками)
    def get_percent(count, total):
        return round((count / total) * 100) if total > 0 else 0

    purchases_stat_body = "\n".join(
        [
            f"<blockquote expandable><b>{i18n.get_text('statistics.success_rate_header', locale)}</b>",
            i18n.get_text("statistics.success_header", locale),
            f"  {i18n.get_text('statistics.by_all_time', locale, value=i18n.get_text('statistics.rating_line', locale, count=success_all, percent=get_percent(success_all, total_purchases_all)))}",
            f"  {i18n.get_text('statistics.by_day', locale, value=i18n.get_text('statistics.rating_line', locale, count=success_day, percent=get_percent(success_day, total_purchases_day)))}",
            f"  {i18n.get_text('statistics.by_week', locale, value=i18n.get_text('statistics.rating_line', locale, count=success_week, percent=get_percent(success_week, total_purchases_week)))}",
            f"  {i18n.get_text('statistics.by_month', locale, value=i18n.get_text('statistics.rating_line', locale, count=success_month, percent=get_percent(success_month, total_purchases_month)))}",
            "",
            i18n.get_text("statistics.failure_header", locale),
            f"  {i18n.get_text('statistics.by_all_time', locale, value=i18n.get_text('statistics.rating_line', locale, count=failure_all, percent=get_percent(failure_all, total_purchases_all)))}",
            f"  {i18n.get_text('statistics.by_day', locale, value=i18n.get_text('statistics.rating_line', locale, count=failure_day, percent=get_percent(failure_day, total_purchases_day)))}",
            f"  {i18n.get_text('statistics.by_week', locale, value=i18n.get_text('statistics.rating_line', locale, count=failure_week, percent=get_percent(failure_week, total_purchases_week)))}",
            f"  {i18n.get_text('statistics.by_month', locale, value=i18n.get_text('statistics.rating_line', locale, count=failure_month, percent=get_percent(failure_month, total_purchases_month)))}",
            "",
            i18n.get_text("statistics.unrated_header", locale),
            f"  {i18n.get_text('statistics.by_all_time', locale, value=i18n.get_text('statistics.rating_line', locale, count=unrated_all, percent=get_percent(unrated_all, total_purchases_all)))}",
            f"  {i18n.get_text('statistics.by_day', locale, value=i18n.get_text('statistics.rating_line', locale, count=unrated_day, percent=get_percent(unrated_day, total_purchases_day)))}",
            f"  {i18n.get_text('statistics.by_week', locale, value=i18n.get_text('statistics.rating_line', locale, count=unrated_week, percent=get_percent(unrated_week, total_purchases_week)))}",
            f"  {i18n.get_text('statistics.by_month', locale, value=i18n.get_text('statistics.rating_line', locale, count=unrated_month, percent=get_percent(unrated_month, total_purchases_month)))}",
            "</blockquote>",
        ]
    )
    purchases_stat = purchases_stat_body

    stats_date_body = "\n".join(
        [
            f"<b>{i18n.get_text('statistics.dates_header', locale)}</b>",
            f"  {i18n.get_text('statistics.date_daily', locale, day=now_day, month=all_months[now_month - 1].title())}",
            f"  {i18n.get_text('statistics.date_weekly', locale, day=week_day, month=all_months[week_month - 1].title(), weekday=all_days[week_week])}",
            f"  {i18n.get_text('statistics.date_monthly', locale, month=all_months[now_month - 1].title(), year=now_year)}",
        ]
    )
    stats_date = stats_date_body


    #* =================================================================================
    #* ТОП-15 СТАТИСТИКА
    #* =================================================================================
    conn_top = sqlite3.connect(PATH_DATABASE)
    conn_top.row_factory = dict_factory
    cursor_top = conn_top.cursor()

    tops_blocks = [i18n.get_text("statistics.tops_header", locale)]

    #* 1. Топ по балансу
    top_balance_content = _get_top_users_stat(
        cursor_top, i18n, locale,
        "statistics.top_balance",
        "SELECT user_id, user_login, user_balance as value FROM storage_users ORDER BY user_balance DESC LIMIT 15",
        "{value:.2f}"
    )

    #* 2. Топ по пополнениям
    top_refills_content = _get_top_users_stat(
        cursor_top, i18n, locale,
        "statistics.top_refills",
        "SELECT user_id, user_login, user_refill as value FROM storage_users ORDER BY user_refill DESC LIMIT 15",
        "{value:.2f}"
    )

    #* 3. Топ по покупкам
    top_purchases_content = _get_top_users_stat(
        cursor_top, i18n, locale,
        "statistics.top_purchases",
        """
        SELECT u.user_id, u.user_login, COUNT(p.increment) as value
        FROM storage_purchases p
        JOIN storage_users u ON p.user_id = u.user_id
        GROUP BY p.user_id
        ORDER BY value DESC
        LIMIT 15
        """,
        "{value} шт."
    )

    #* 4. Топ любимчиков
    top_favorites_content = _get_top_users_stat(
        cursor_top, i18n, locale,
        "statistics.top_favorites",
        "SELECT user_id, user_login, user_give as value FROM storage_users ORDER BY user_give DESC LIMIT 15",
        "{value:.2f}"
    )

    #* 5. Топ неудачников
    top_unlucky_content = _get_top_users_stat(
        cursor_top, i18n, locale,
        "statistics.top_unlucky",
        """
        SELECT u.user_id, u.user_login, COUNT(p.increment) as value
        FROM storage_purchases p
        JOIN storage_users u ON p.user_id = u.user_id
        WHERE p.rating = -1
        GROUP BY p.user_id
        ORDER BY value DESC
        LIMIT 15
        """,
        "{value} шт."
    )

    conn_top.close()

    #* =================================================================================
    #* =================================================================================



    return (
        users_stat,
        money_stat,
        purchases_stat,
        stat_categories,
        stat_subcategories,
        stat_positions,
        stat_items,
        stats_date,
        f"<blockquote expandable>{top_balance_content}</blockquote>",
        f"<blockquote expandable>{top_refills_content}</blockquote>",
        f"<blockquote expandable>{top_purchases_content}</blockquote>",
        f"<blockquote expandable>{top_favorites_content}</blockquote>",
        f"<blockquote expandable>{top_unlucky_content}</blockquote>",
    )


async def is_valid_url(custom_url: str) -> bool:
    """
    Проверяет, является ли строка допустимым URL-адресом.
    :param custom_url: URL-адрес для проверки.
    :return: True, если URL-адрес допустим, иначе False.
    """

    # Pattern for http(s) URLs
    http_regex = re.compile(
        r"^https?://"
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
        r"(?::\d+)?"
        r"(?:/?|[/?]\S+)?$",
        re.IGNORECASE,
    )
    # Pattern for Telegram links
    tg_regex = re.compile(r"^tg://resolve\?domain=[\w\d_]+$", re.IGNORECASE)
    if custom_url is not None and (
        http_regex.match(custom_url) or tg_regex.match(custom_url)
    ):
        return True
    return False
