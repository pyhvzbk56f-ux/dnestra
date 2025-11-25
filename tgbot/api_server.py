# shop/tgbot/api_server.py
import logging
import asyncio
import hashlib
import os
import base64
import sys
import socket
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from tgbot.data.config import get_admins, get_operators
from tgbot.database import (Userx, Itemx, Positionx, Categoryx, Subcategoryx, Purchasesx, Invoicex, InvoiceStatus, AggregatorTrafficx, Settingsx, Disputex, Exchangersx, ExchangersModel,)
from tgbot.services.i18n import i18n
from tgbot.utils.const_functions import gen_id, get_unix, convert_date, send_admins, clear_html, PurchaseSource
from tgbot.services.api_session import AsyncRequestSession
from tgbot.utils.misc.bot_logging import bot_logger
from tgbot.utils.misc.bot_models import ARS
from tgbot.utils.misc_functions import update_actual_ltc_rate_in_db, send_notification
from tgbot.utils.text_functions import send_purchase_details
from tgbot.data.config import BASE_DIR

# # Глобальная переменная для хранения порта, на котором запустился API
# API_PORT = 0



# def find_available_port(start_port: int, max_ports: int = 10) -> int:
#     """# Checks ports sequentially starting from start_port and returns the first free one."""
#     for port in range(start_port, start_port + max_ports):
#         with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
#             try:
#                 s.bind(('0.0.0.0', port))
#                 bot_logger.info(i18n.get_text("api_server.port_is_free", "en", port=port))
#                 return port
#             except OSError:
#                 bot_logger.warning(i18n.get_text("api_server.port_is_busy", "en", port=port))
#     raise IOError(i18n.get_text("api_server.no_free_ports", "en", start_port=start_port, end_port=start_port + max_ports - 1))

#! Middleware для проверки авторизации
@web.middleware
async def auth_middleware(request: web.Request, handler):
    bot_id = str(request.app['bot'].id)
    internal_api_key = os.getenv("INTERNAL_API_KEY", hashlib.md5(f"dns{bot_id}".encode()).hexdigest())
    if request.headers.get("X-Internal-Api-Key") != internal_api_key:
        return web.json_response({'error': i18n.get_text("api_server.unauthorized", "en")}, status=401)
    return await handler(request)

#! уведомления администраторам
async def send_admin_notification_background(bot, details: dict):
    """#! Sends notifications to administrators in the background."""
    admin_message = details.get('admin_message', i18n.get_text("api_server.purchase_from_api_default", "en"))
    
    for admin in get_admins():
        try:
            await send_notification(bot, admin, admin_message)
        except Exception as e:
            bot_logger.error(i18n.get_text("api_server.admin_notification_error", "en", admin_id=admin, error=e))

    for operator in get_operators():
        try:
            await send_notification(bot, operator, admin_message)
        except Exception as e:
            bot_logger.error(i18n.get_text("api_server.admin_notification_error", "en", admin_id=operator, error=e))        


#! ОБРАБОТЧИКИ ДЛЯ ОЦЕНОК И ЖАЛОБ
#! ДЛЯ ОЦЕНОК 
async def rate_purchase_api(request: web.Request):
    bot = request.app['bot']
    try:
        data = await request.json()
        user_id, receipt, rating, comment = int(data['user_id']), data['purchase_receipt'], int(data['rating']), data.get('comment')
        
        if not Purchasesx.get(purchase_receipt=receipt, user_id=user_id):
            return web.json_response({'error': i18n.get_text("api_server.purchase_not_found", "en")}, status=404)

        if rating == -1:
            complaint = i18n.get_text("api_server.dispute_comment_from_site", "en", date=convert_date(get_unix()), comment=comment) if comment else i18n.get_text("api_server.dispute_created_from_site", "en")
            Disputex.add(purchase_receipt=receipt, user_id=user_id, complaint_text=complaint)
            Purchasesx.update(purchase_receipt=receipt, has_dispute=True, rating=-1)
            admin_text = i18n.get_text("api_server.new_dispute_admin_notification", "en", receipt=receipt, user_id=user_id)
            asyncio.create_task(send_admins(bot, admin_text, not_me=0, include_operators=True))
        else:
            Purchasesx.update(purchase_receipt=receipt, rating=1)
        
        return web.json_response({'status': 'success'}, status=200)
    except Exception as e:
        bot_logger.error(i18n.get_text("api_server.rate_purchase_api_error", "en", error=e), exc_info=True)
        return web.json_response({'error': i18n.get_text("api_server.internal_server_error", "en")}, status=500)

#! ДЛЯ ЖАЛОБ
async def update_dispute_api(request: web.Request):
    try:
        data = await request.json()
        user_id, dispute_id, comment = int(data['user_id']), int(data['dispute_id']), data['comment']
        
        dispute = Disputex.get(dispute_id=dispute_id, user_id=user_id)
        if not dispute:
            return web.json_response({'error': i18n.get_text("api_server.dispute_not_found", "en")}, status=404)

        new_comment_block = i18n.get_text("api_server.dispute_comment_from_site", "en", date=convert_date(get_unix()), comment=comment)
        final_comment = f"{dispute.complaint_text}\n\n{new_comment_block}" if dispute.complaint_text else new_comment_block
        
        Disputex.update(dispute_id=dispute_id, complaint_text=final_comment)
        return web.json_response({'status': 'success'}, status=200)
    except Exception as e:
        bot_logger.error(i18n.get_text("api_server.update_dispute_api_error", "en", error=e), exc_info=True)
        return web.json_response({'error': i18n.get_text("api_server.internal_server_error", "en")}, status=500)

#! Обработчики API. Списание средств и получение товара
async def debit_and_get_item(request: web.Request):
    bot = request.app['bot']
    try:
        data = await request.json()
        user_id, position_id = int(data['user_id']), int(data['position_id'])
        bot_logger.info(i18n.get_text("api_server.purchase_request_received", "en", user_id=user_id, position_id=position_id))
        user, position, items, get_settings = Userx.get(user_id=user_id), Positionx.get(position_id=position_id), Itemx.gets(position_id=position_id), Settingsx.get()
        if not user:
            bot_logger.warning(i18n.get_text("api_server.check_fail_user_not_found", "en", user_id=user_id))
            return web.json_response({'error': i18n.get_text("api_server.user_not_found_api_response", "en")}, status=404)
        if not position:
            bot_logger.warning(i18n.get_text("api_server.check_fail_position_not_found", "en", position_id=position_id))
            return web.json_response({'error': i18n.get_text("api_server.position_not_found_api_response", "en")}, status=404)
        bot_logger.debug(i18n.get_text("api_server.checks_log", "en", balance=user.user_balance, price=position.position_price, count=len(items)))
        if len(items) < 1:
            bot_logger.warning(i18n.get_text("api_server.purchase_denied_out_of_stock", "en", user_id=user_id))
            return web.json_response({'error': i18n.get_text("api_server.out_of_stock_api_response", "en")}, status=409)
        if user.user_balance < position.position_price:
            bot_logger.warning(i18n.get_text("api_server.purchase_denied_insufficient_funds", "en", user_id=user_id))
            return web.json_response({'error': i18n.get_text("api_server.insufficient_funds_api_response", "en")}, status=402)
        bot_logger.debug(i18n.get_text("api_server.all_checks_passed", "en", user_id=user_id))
        try:
            bought_item_data, _ = Itemx.buy(items, 1)
            
            #! Проверка на и кодирование 
            item_content = bought_item_data[0] # Это может быть путь или URL
            response_item_data = ""
            response_item_type = ""

            # Проверяем URL или локальный
            if item_content.startswith(('http://', 'https://')):
                response_item_data = item_content
                response_item_type = "url"
            else:
                # локальный - кодируем в Base64
                full_path = BASE_DIR / item_content
                if os.path.exists(full_path):
                    with open(full_path, "rb") as image_file:
                        image_bytes = image_file.read()
                    base64_string = base64.b64encode(image_bytes).decode('utf-8')
                    # Формируем Data URI
                    response_item_data = f"data:image/webp;base64,{base64_string}"
                    response_item_type = "base64"
                else:
                    bot_logger.error(f"API debit_and_get_item: Файл не найден по пути {full_path}")
                    response_item_data = "File not found on server."
                    response_item_type = "error"

            #! конец проверки 

            user_balance_before = user.user_balance
            new_balance = round(user_balance_before - position.position_price, 2)
            Userx.update(user_id, user_balance=new_balance)

            # Уведомляем агрегатор об изменении баланса
            from tgbot.utils.misc_functions import notify_aggregator_of_balance_update
            asyncio.create_task(notify_aggregator_of_balance_update(
                bot=bot,
                arSession=request.app['arSession'],
                user_id=user_id,
                new_balance=new_balance
            ))

            purchase_receipt, purchase_unix = gen_id(), get_unix()
            category, subcategory = Categoryx.get(category_id=position.category_id), Subcategoryx.get(subcategory_id=position.subcategory_id)
            
            Purchasesx.add(
                user_id=user_id, 
                user_balance_before=user_balance_before, 
                user_balance_after=new_balance,
                purchase_receipt=purchase_receipt, 
                purchase_data=item_content, 
                purchase_count=1,
                purchase_price=position.position_price, 
                purchase_price_one=position.position_price,
                purchase_position_id=position.position_id, 
                purchase_position_name=position.position_name,
                purchase_category_id=category.category_id, 
                purchase_category_name=category.category_name,
                purchase_subcategory_id=subcategory.subcategory_id, 
                purchase_subcategory_name=subcategory.subcategory_name,
                from_site=True
            )

            

            AggregatorTrafficx.log_purchase(user.user_id)

            purchase_object = Purchasesx.get(purchase_receipt=purchase_receipt)
            # Отправляем уведомления админам и операторам
            users_list = set(get_admins()) | set(get_operators())
            for user_id in users_list:
                try:
                    recipient_user = Userx.get(user_id=user_id)
                    recipient_locale = recipient_user.language_code if recipient_user else "en"
                    # Используем универсальную функцию для отправки деталей покупки
                    await send_purchase_details(bot=bot, 
                        chat_id=user_id, 
                        purchase=purchase_object, 
                        i18n=i18n, locale=str(recipient_locale),
                        caption_template_key="admin_purchase.receipt_full",
                        source=PurchaseSource.SITE
                        )
                except Exception as e:
                    bot_logger.error(f"Couldn't send API purchase notification to {user_id}: {e}")

            receipt_data = {
                "purchase_receipt": purchase_receipt, 
                "purchase_date": convert_date(purchase_unix),
                "position_name": position.position_name, 
                "purchase_price": position.position_price,
                "category_name": category.category_name, 
                "subcategory_name": subcategory.subcategory_name,
                "user": {
                    "id": user.user_id, 
                    "login": user.user_login, 
                    "name": user.user_name
                    },
                "item_data": response_item_data,
                "item_type": response_item_type,
                "misc_info_check": get_settings.misc_info_check if get_settings.misc_info_check != "None" else ""
            }
            bot_logger.warning(i18n.get_text("api_server.purchase_flow_success", "en", user_id=user_id, receipt=purchase_receipt))
            return web.json_response({'status': 'success', 'receipt_data': receipt_data}, status=200)
        except Exception as e:
            bot_logger.error(i18n.get_text("api_server.critical_error_in_debit_and_get_item", "en", error=e), exc_info=True)
            return web.json_response({'error': i18n.get_text("api_server.transaction_error_api_response", "en")}, status=500)
    except Exception as e:
        bot_logger.error(i18n.get_text("api_server.critical_error_in_debit_and_get_item", "en", error=e), exc_info=True)
        return web.json_response({'error': i18n.get_text("api_server.unexpected_error_api_response", "en")}, status=500)




#! ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ОБМЕННИКОВ
def _get_raw_exchangers(currency: str) -> list[ExchangersModel]:
    """#! Gets a "raw" list of exchanger models from the DB, filtered by currency, using the new fault-tolerant method."""
    return Exchangersx.get_for_currency(currency)

#! Отдает список активных обменников для указанной валюты
async def get_exchangers_api(request: web.Request):
    """#! Returns a "raw", unsorted list of active exchangers for the specified currency."""
    try:
        currency = request.match_info['currency'].upper()
        if currency not in ['LTC', 'USDT']:
            return web.json_response({'error': i18n.get_text("api_server.invalid_currency", "en")}, status=400)
    except KeyError:
        return web.json_response({'error': i18n.get_text("api_server.currency_not_specified", "en")}, status=400)
    exchangers_raw = _get_raw_exchangers(currency)
    exchangers_list = [ex.model_dump() for ex in exchangers_raw]
    return web.json_response(exchangers_list, status=200)

#! Создание счета на пополнение
async def create_invoice_api(request: web.Request):
    bot = request.app['bot']
    try:
        data = await request.json()
        user_id = int(data.get('user_id'))
        amount_usd = float(data.get('amount'))
        bot_logger.info(i18n.get_text("api_server.log_create_invoice_request", "en", user_id=user_id, amount=amount_usd))
        currency = data.get('currency', 'LTC')
    except (ValueError, TypeError, KeyError) as e:
        bot_logger.error(i18n.get_text("api_server.log_create_invoice_critical_error", "en", error=e), exc_info=True)
        return web.json_response({'error': i18n.get_text("api_server.invalid_data", "en")}, status=400)

    user = Userx.get(user_id=user_id)
    if not user:
        return web.json_response({'error': i18n.get_text("api_server.user_not_found_api_response", "en")}, status=404)

    settings = Settingsx.get()
    payment_system = settings.payment_system
    payment_address = None
    
    if currency == "LTC":
        payment_address = settings.htx_ltc_address if payment_system == 'htx' else settings.alter_ltc_address
    elif currency == "USDT":
        payment_address = settings.htx_usdt_trc20_address if payment_system == 'htx' else settings.alter_usdt_trc20_address

    if not payment_address or payment_address == "None":
        return web.json_response({'error': i18n.get_text("api_server.address_not_configured", "en", currency=currency)}, status=500)
    
    invoice_params = {"user_id": user_id, "amount_usd": amount_usd, "currency": currency, "from_site": True}
    crypto_amount = 0.0

    if currency == "LTC":
        ltc_rate = settings.ltc_to_usd_rate or await update_actual_ltc_rate_in_db(bot)
        if not ltc_rate:
            return web.json_response({'error': i18n.get_text("api_server.ltc_rate_fetch_error", "en")}, status=503)
        crypto_amount = round(amount_usd / ltc_rate, 6)
        invoice_params.update({"amount_ltc": crypto_amount, "ltc_address": payment_address})
    elif currency == "USDT":
        crypto_amount = amount_usd
        invoice_params.update({"amount_usdt": crypto_amount, "usdt_address": payment_address})
    
    while True:
        pending_invoices = Invoicex.gets(status=InvoiceStatus.PENDING, currency=currency)
        pending_amounts = [inv.amount_ltc for inv in pending_invoices if inv.amount_ltc is not None] if currency == "LTC" else [inv.amount_usdt for inv in pending_invoices if inv.amount_usdt is not None]
        if not any(abs(p_amount - crypto_amount) < 1e-9 for p_amount in pending_amounts):
            break
        crypto_amount += 0.000001 if currency == "LTC" else 0.01
        crypto_amount = round(crypto_amount, 6 if currency == "LTC" else 2)

    if currency == "LTC":
        invoice_params["amount_ltc"] = crypto_amount
    elif currency == "USDT":
        invoice_params["amount_usdt"] = crypto_amount
    
    invoice_id = Invoicex.add(**invoice_params)
    new_invoice = Invoicex.get(id=invoice_id)
    
    try:
        message_invoice_admin = f"<b>Invoice {currency} </b> #<code>{invoice_id}</code> (site)\nUSD: <code>{amount_usd}</code> | {currency}: <code>{crypto_amount}</code>\nAddres {currency}: {payment_address} \nLogin: @{user.user_login} | ID: <code>{user.user_id}</code>\nDate: {convert_date(get_unix())}"
        asyncio.create_task(send_admins(bot=bot, text=message_invoice_admin, not_me=0, include_operators=True))
    except Exception as e:
        bot_logger.error(i18n.get_text("api_server.admin_notification_task_error", "en", invoice_id=invoice_id, error=e), exc_info=True)

    exchangers_raw = _get_raw_exchangers(currency)
    exchangers_list = [ex.model_dump() for ex in exchangers_raw]

    return web.json_response({
        'status': 'success',
        'invoice_id': invoice_id,
        'shop_id': bot.id,
        'user_id': user.user_id,
        'user_login': user.user_login,
        'created_at': new_invoice.created_at,
        'amount': crypto_amount,
        'currency': currency,
        'address': payment_address,
        'exchangers': exchangers_list
    }, status=200)

#! Проверка статуса счета
async def check_invoice_api(request: web.Request):
    try:
        invoice_id = int(request.match_info['invoice_id'])
    except (ValueError, KeyError):
        return web.json_response({'error': i18n.get_text("api_server.invalid_invoice_id", "en")}, status=400)
    invoice = Invoicex.get(id=invoice_id)
    if not invoice:
        return web.json_response({'error': i18n.get_text("api_server.invoice_not_found", "en")}, status=404)
    return web.json_response({'status': invoice.status.value}, status=200)

#! ФУНКЦИЯ ЗАПУСКА API СЕРВЕРА
async def setup_and_start_api_server(bot: Bot, arSession: ARS) -> tuple[web.AppRunner | None, int]:
    """#! Configures and starts the API server, then returns its runner and port."""
    try:
        
        internal_port = 8181 # Внутренний порт всегда фиксированный
        external_port_str = os.environ.get('EXTERNAL_PORT') # Внешний порт берем из переменной окружения
        if not external_port_str:
            bot_logger.critical("Переменная окружения EXTERNAL_PORT не установлена!")
            return None, 0
        external_port = int(external_port_str)

    except IOError as e:
        bot_logger.critical(i18n.get_text("api_server.server_startup_failed", "en", error=e))
        return None, 0
    bot_id_str = str(bot.id)
    correct_api_key = hashlib.md5(f"dns{bot_id_str}".encode()).hexdigest()
    bot_logger.critical("="*60)
    bot_logger.critical(i18n.get_text("api_server.server_started_for_bot", "en", bot_id=bot_id_str))
    bot_logger.critical(i18n.get_text("api_server.server_internal_api_key", "en", api_key=correct_api_key))
    bot_logger.critical("="*60)
    
    app = web.Application(middlewares=[auth_middleware])
    app['bot'] = bot
    app['arSession'] = arSession
    
    app.router.add_post('/api/internal/debit_and_get_item', debit_and_get_item)
    app.router.add_post('/api/internal/create_invoice', create_invoice_api)
    app.router.add_get('/api/internal/check_invoice/{invoice_id}', check_invoice_api)
    app.router.add_post('/api/internal/rate_purchase', rate_purchase_api)
    app.router.add_post('/api/internal/update_dispute', update_dispute_api)
    app.router.add_get('/api/internal/get_exchangers/{currency}', get_exchangers_api)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', internal_port)
    await site.start()
    bot_logger.info(f"API internal_port: {internal_port}")
    bot_logger.info(f"API external_port: {external_port}")

    return runner, external_port