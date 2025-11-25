# tgbot/routers/user/user_transactions.py
from datetime import datetime
from typing import Union

import aiohttp
from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from tgbot.utils.misc.bot_models import FSM
from tgbot.data.config import get_admins, get_operators
from tgbot.database import InvoiceStatus, Invoicex, Exchangersx, Settingsx, Userx
from tgbot.services.i18n import i18n, Translator
from tgbot.utils.misc.i18n_filters import I18nText
from tgbot.utils.const_functions import (
    bot_logger,
    convert_date,
    ded,
    get_unix,
    is_number,
)
from tgbot.utils.misc_functions import get_actual_ltc_rate
from tgbot.utils.misc.bot_filters import IsSubscribed


#! Определение состояний
class RefillStates(StatesGroup):
    choose_currency = State()
    here_refill_amount = State()


min_refill_usd = 1  # Минимальная сумма пополнения в 
max_refill_usd = 999  # Максимальная сумма пополнения в 
router = Router(name=__name__)


#! Клавиатура для выбора валюты
def choose_currency_keyboard(i18n: Translator, locale: str) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="LTC", callback_data="refill_currency:LTC")],
            [
                InlineKeyboardButton(
                    text="USDT (TRC20)", callback_data="refill_currency:USDT"
                )
            ],
        ]
    )
    return keyboard


#!###############################################################################
#! для deep link ( дип линк )


#! ВНУТРЕННЯЯ ФУНКЦИЯ ДЛЯ СОЗДАНИЯ СЧЕТА
async def _create_and_send_invoice(
    message: Message,
    bot: Bot,
    pay_amount_usd: float,
    currency: str,
    i18n: Translator,
    locale: str,
):
    """
    #! Универсальная функция для создания и отправки счёта на пополнение.
    """
    get_settings = Settingsx.get()
    payment_address = None

    if currency == "LTC":
        payment_address = (
            get_settings.htx_ltc_address
            if get_settings.payment_system == "htx"
            else get_settings.alter_ltc_address
        )
    elif currency == "USDT":
        payment_address = (
            get_settings.htx_usdt_trc20_address
            if get_settings.payment_system == "htx"
            else get_settings.alter_usdt_trc20_address
        )

    if not payment_address:
        await message.answer(
            i18n.get_text(
                "user_transactions.address_not_set_for_currency",
                locale,
                currency=currency,
            )
        )
        return

    invoice_params = {
        "user_id": message.from_user.id,
        "amount_usd": float(pay_amount_usd),
        "currency": currency,
        "status": InvoiceStatus.PENDING,
    }
    crypto_amount = 0.0

    if currency == "LTC":
        ltc_rate = get_settings.ltc_to_usd_rate or await get_actual_ltc_rate(bot)
        if not ltc_rate:
            await message.answer(
                i18n.get_text("user_transactions.failed_to_get_ltc_rate", locale)
            )
            return
        crypto_amount = round(pay_amount_usd / ltc_rate, 6)
        invoice_params.update(
            {"amount_ltc": crypto_amount, "ltc_address": payment_address}
        )
    elif currency == "USDT":
        crypto_amount = float(pay_amount_usd)
        invoice_params.update(
            {"amount_usdt": crypto_amount, "usdt_address": payment_address}
        )

    # Проверка уникальности суммы
    while True:
        pending_invoices = Invoicex.gets(
            status=InvoiceStatus.PENDING, currency=currency
        )
        pending_amounts = (
            [inv.amount_ltc for inv in pending_invoices if inv.amount_ltc is not None]
            if currency == "LTC"
            else [
                inv.amount_usdt
                for inv in pending_invoices
                if inv.amount_usdt is not None
            ]
        )
        if not any(
            abs(p_amount - crypto_amount) < 1e-9 for p_amount in pending_amounts
        ):
            break
        crypto_amount = round(
            crypto_amount + (0.000001 if currency == "LTC" else 0.01),
            6 if currency == "LTC" else 2,
        )

    if currency == "LTC":
        invoice_params["amount_ltc"] = crypto_amount
    elif currency == "USDT":
        invoice_params["amount_usdt"] = crypto_amount

    invoice_id = Invoicex.add(**invoice_params)
    invoice_datetime = get_unix()
    exchangers_text_done = ""

    exchanger_filter = (
        {"exchanger_enabled": True, "is_ltc": True}
        if currency == "LTC"
        else {"exchanger_enabled": True, "is_usdt_trc20": True}
    )
    exchangers = Exchangersx.gets(**exchanger_filter)

    if exchangers:
        exchangers_sorted = sorted(
            exchangers, key=lambda x: (x.exchanger_order, x.exchanger_id)
        )
        ex_url_list = []
        for ex in exchangers_sorted:
            param_text = f"?text=/{currency.lower()}/{currency.upper()}/{crypto_amount}/{payment_address}"
            ex_url_full = (
                ex.exchanger_custom_url.replace(
                    "{{crypto_amount}}", str(crypto_amount)
                ).replace("{{payment_address}}", str(payment_address))
                if ex.exchanger_custom_url
                and not ex.exchanger_custom_url.startswith("+")
                else f"https://t.me/{ex.exchanger_name}{param_text}"
            )
            ex_url_list.append(f"<a href='{ex_url_full}'>{ex.exchanger_data}</a>")

        omben_title = i18n.get_text(
            "user_transactions.exchangers_recommendation", locale
        )
        exchangers_text_done = f"{omben_title}\n" + "\n".join(ex_url_list)

    await message.answer(
        ded(f"""{i18n.get_text("user_transactions.invoice_title", locale, currency=currency, invoice_id=invoice_id)}
{i18n.get_text("user_transactions.invoice_issued_to", locale, username=message.from_user.username)}
{i18n.get_text("user_transactions.invoice_user_id", locale, user_id=message.from_user.id)}
{i18n.get_text("user_transactions.invoice_created_at", locale, date=convert_date(invoice_datetime))}

{i18n.get_text("user_transactions.invoice_copy_instruction", locale, amount=crypto_amount, currency=currency, address=payment_address)}

{i18n.get_text("user_transactions.invoice_warning", locale)}

{exchangers_text_done}"""),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    bot_logger.debug(
        f"Счет {currency} # ID: {invoice_id} Сумма: {pay_amount_usd} {currency}: {crypto_amount} Дата выставления: {convert_date(invoice_datetime)} Логин: @{message.from_user.username} ID:{message.from_user.id}"
    )

    users_list = set(get_admins()) | set(get_operators())
    for user_id in users_list:
        try:
            recipient_user = Userx.get(user_id=user_id)
            recipient_locale = recipient_user.language_code if recipient_user else "en"
            message_invoice_admin = (
                f"{i18n.get_text('user_transactions.admin_notification_invoice_title', recipient_locale, currency=currency, invoice_id=invoice_id)}\n"
                f"{i18n.get_text('user_transactions.admin_notification_invoice_body', recipient_locale, amount_usd=pay_amount_usd, currency=currency, crypto_amount=crypto_amount, address=payment_address, username=message.from_user.username, user_id=message.from_user.id, date=convert_date(invoice_datetime))}"
            )
            await bot.send_message(chat_id=user_id, text=message_invoice_admin)
        except Exception as e:
            bot_logger.error(f"Error while sending invoice notification to {user_id}: {e}")


#! ДЛЯ ОБРАБОТКИ DEEP LINK
async def process_invoice_deeplink(
    message: Message,
    bot: Bot,
    pay_amount_usd: float,
    currency: str,
    i18n: Translator,
    locale: str,
):
    """
    #! Обрабатывает запрос на создание счёта из deep link.
    """
    if currency not in ["LTC", "USDT"]:
        await message.answer(
            i18n.get_text("user_transactions.unsupported_currency_deeplink", locale)
        )
        return
    if not (min_refill_usd <= pay_amount_usd <= max_refill_usd):
        await message.answer(
            i18n.get_text(
                "user_transactions.invalid_amount_deeplink",
                locale,
                min_amount=min_refill_usd,
                max_amount=max_refill_usd,
            )
        )
        return

    await _create_and_send_invoice(message, bot, pay_amount_usd, currency, i18n, locale)


#!###############################################################################
#! Кнопка пополнить Из главного меню
@router.message(IsSubscribed(), I18nText("buttons.refill")) 
async def refill_from_message(message: Message, state: FSM, i18n: Translator, locale: str):
    get_settings = Settingsx.get()
    if get_settings.status_refill == "True":
        await message.answer(i18n.get_text("user_transactions.choose_currency", locale),reply_markup=choose_currency_keyboard(i18n, locale),)
        await state.set_state(RefillStates.choose_currency)
    else:
        await message.answer(i18n.get_text("user_transactions.refills_disabled", locale))


#! Кнопка пополнить Из профиля
@router.callback_query(F.data == "user_refill")
async def refill_method(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
    get_settings = Settingsx.get()
    if get_settings.status_refill == "True":
        await call.message.edit_text(
            i18n.get_text("user_transactions.choose_currency", locale),
            reply_markup=choose_currency_keyboard(i18n, locale),
        )
        await state.set_state(RefillStates.choose_currency)
    else:
        await call.answer(
            i18n.get_text("user_transactions.refills_disabled", locale), show_alert=True
        )


#! Обработка выбора валюты
@router.callback_query(
    F.data.startswith("refill_currency:"), StateFilter(RefillStates.choose_currency)
)
async def currency_chosen(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    currency = call.data.split(":")[1]
    await state.update_data(chosen_currency=currency)
    await call.message.edit_text(
        i18n.get_text("user_transactions.currency_selected", locale, currency=currency)
    )
    await state.set_state(RefillStates.here_refill_amount)


#!###############################################################################
#!################################### ВВОД СУММЫ #################################
#! Принятие суммы для формирования счета
@router.message(F.text, StateFilter(RefillStates.here_refill_amount))
async def refill_amount_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    if not is_number(message.text) or not message.text.isdigit():
        bot_logger.info(
            f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} username: {message.from_user.username} id: {message.from_user.id} Введена неправильная сумма для пополнения"
        )
        return await message.answer(
            ded(i18n.get_text("user_transactions.error_invalid_amount_format", locale))
        )

    pay_amount_usd = int(message.text)
    if pay_amount_usd < min_refill_usd or pay_amount_usd > max_refill_usd:
        bot_logger.info(
            f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} username: {message.from_user.username} id: {message.from_user.id} Введена сумма пополнения больше разрешенной"
        )
        return await message.answer(
            ded(
                i18n.get_text("user_transactions.error_amount_out_of_range", locale, min_amount=min_refill_usd, max_amount=max_refill_usd,)
            )
        )

    user_data = await state.get_data()
    currency = user_data.get("chosen_currency")
    await state.clear()

    # Вызываем универсальную функцию создания и отправки счета
    await _create_and_send_invoice(message, bot, float(pay_amount_usd), currency, i18n, locale)


async def htx_api_get_ltc_rate() -> Union[float, None]:
    """Получает курс USDT к LTC с HTX API. Возвращает: float: Курс USDT к LTC. None: В случае ошибки."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.huobi.pro/market/detail/merged?symbol=ltcusdt"
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    #! Проверяем, содержит ли ответ данные о курсе
                    if "tick" in data and "close" in data["tick"]:
                        return float(data["tick"]["close"])
                    else:
                        bot_logger.error(
                            i18n.get_text(
                                "log_messages.htx_invalid_response_format", "en"
                            )
                        )
                        return None
                else:
                    bot_logger.error(
                        i18n.get_text(
                            "log_messages.htx_api_error", "en", status=response.status
                        )
                    )
                    return None
    except Exception as e:
        bot_logger.error(
            i18n.get_text("log_messages.htx_get_ltc_rate_error", "en", error=e)
        )
        return None
