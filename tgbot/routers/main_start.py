# shop/tgbot/routers/main_start.py

import asyncio
from aiogram import Router, Bot, F
from aiogram.filters import StateFilter, CommandStart, CommandObject
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from tgbot.database import (
    Settingsx,
    Userx,
    Categoryx,
    Subcategoryx,
    Positionx,
    Itemx,
    AggregatorTrafficx,
)
from tgbot.keyboards.inline_user import user_support_finl
from tgbot.keyboards.reply_main import menu_frep
from tgbot.utils.const_functions import bot_logger
from tgbot.utils.misc.bot_filters import IsBuy, IsRefill, IsWork
from tgbot.utils.misc.bot_models import FSM, ARS
from tgbot.services.i18n import Translator
from tgbot.utils.misc.i18n_filters import I18nText 


# from tgbot.utils.misc_functions import report_transition_to_aggregator
from tgbot.routers.user.user_transactions import (
    process_invoice_deeplink,
    _create_and_send_invoice,
)

#! Импортируем хелпер для совершения покупки
from tgbot.keyboards.inline_user_products import products_buy_deeplink_confirm_finl
from tgbot.routers.user.user_menu import user_support_logic 
from tgbot.keyboards.inline_user import language_selection_keyboard

#! Игнор-колбэки покупок
prohibit_buy = [
    "buy_category_swipe",
    "buy_category_open",
    "buy_subcategory_open",
    "buy_subcategory_swipe",
    "buy_position_swipe",
    "buy_position_open",
    "buy_item_open",
    "buy_item_confirm",
]

#! Игнор-колбэки пополнений
prohibit_refill = [
    "user_refill",
    "user_refill_method",
    "Pay:Cryptobot",
    "Pay:Yoomoney",
    "Pay:",
]





router = Router(name=__name__)


#!########################## СТАТУС ТЕХНИЧЕСКИХ РАБОТ ###########################
#! Фильтр на технические работы - сообщение
@router.message(IsWork())
async def filter_work_message(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    get_settings = Settingsx.get()
    text = i18n.get_text("filters.tech_works", locale)

    if get_settings.misc_support != "None":
        reply_markup = user_support_finl(get_settings.misc_support, i18n, locale)
        return await message.answer(text, reply_markup=reply_markup)

    await message.answer(text)


#! Фильтр на технические работы - колбэк
@router.callback_query(IsWork())
async def filter_work_callback(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    await call.answer(i18n.get_text("filters.tech_works_alert", locale), True)


#!################################# СТАТУС ПОКУПОК ###############################
#! Фильтр на доступность покупок - сообщение
@router.message(IsBuy(),F.text.func(lambda msg, i18n, locale: msg.text == i18n.get_text("buttons.buy", locale)),)
@router.message(IsBuy(), StateFilter("here_item_count"))
async def filter_buy_message(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    await message.answer(i18n.get_text("filters.purchases_disabled", locale))


#! Фильтр на доступность покупок - колбэк
@router.callback_query(IsBuy(), F.data.startswith(tuple(prohibit_buy)))
async def filter_buy_callback(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    await call.answer(i18n.get_text("filters.purchases_disabled_alert", locale), True)


#!############################### СТАТУС ПОПОЛНЕНИЙ ##############################
#! Фильтр на доступность пополнения - сообщение
@router.message(IsRefill(), StateFilter("here_pay_amount"))
async def filter_refill_message(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    await message.answer(i18n.get_text("filters.refills_disabled", locale))


#! Фильтр на доступность пополнения - колбэк
@router.callback_query(IsRefill(), F.data.startswith(tuple(prohibit_refill)))
async def filter_refill_callback(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    await call.answer(i18n.get_text("filters.refills_disabled_alert", locale), True)


#!###############################################################################
#!################################### ПРОЧЕЕ ####################################
#! Открытие главного меню
async def show_main_menu(message: Message, state: FSM, i18n: Translator, locale: str):
    """#! Вспомогательная функция для отображения главного меню."""
    await state.clear()
    await message.answer(
        i18n.get_text("welcome", locale),
        reply_markup=menu_frep(message.from_user.id, i18n, locale),
    )


@router.message(I18nText("buttons.main_menu"))
async def main_menu_text_handler(message: Message, state: FSM, i18n: Translator, locale: str):
    """#! Обработчик для текстовой кнопки 'Главное меню'."""
    await show_main_menu(message, state, i18n, locale)


#! Открытие диплинков
@router.message(CommandStart())
async def main_start_handler(
    message: Message,
    bot: Bot,
    state: FSM,
    command: CommandObject,
    arSession: ARS,
    i18n: Translator,
    locale: str,
):
    """#! Универсальный обработчик /start. Обрабатывает deeplink-ссылки и предлагает выбор языка."""
    await state.clear()

    db_user = Userx.get(user_id=message.from_user.id)
    if not db_user:
        Userx.add(
            message.from_user.id,
            message.from_user.username or "",
            message.from_user.full_name,
        )
        db_user = Userx.get(user_id=message.from_user.id)

    #! Если язык не установлен, предлагаем выбор
    if not db_user.language_code:
        await message.answer(i18n.get_text("language_selection.choose", "en"), reply_markup=language_selection_keyboard(),)
        return

    deeplink_args = command.args

    # Обработка диплинка для поддержки
    if deeplink_args == "support":
        await user_support_logic(message, state, bot, i18n, locale)
        return


    if not deeplink_args:
        await show_main_menu(message, state, i18n, locale)
        return

    #!#####################################################################################################
    #! БЛОК ДЛЯ ОБРАБОТКИ ПОКУПКИ ЧЕРЕЗ ДИПЛИНК
    if deeplink_args.startswith("buy_"):
        AggregatorTrafficx.log_transition(message.from_user.id)
        bot_logger.info(
            f"Traffic: Logged transition for user {message.from_user.id} via deeplink."
        )
        try:
            position_id = int(deeplink_args.split("_")[1])
            position = Positionx.get(position_id=position_id)

            if not position or len(Itemx.gets(position_id=position.position_id)) < 1:
                return await message.answer(
                    i18n.get_text("errors.item_not_found", locale)
                )

            if db_user.user_balance >= position.position_price:
                category = Categoryx.get(category_id=position.category_id)
                subcategory = Subcategoryx.get(subcategory_id=position.subcategory_id)
                confirmation_text = i18n.get_text(
                    "user_products.purchase_confirmation_body",
                    locale,
                    position_name=position.position_name,
                    count=1,
                    price=position.position_price,
                )
                await message.answer(
                    f"{i18n.get_text('user_products.purchase_confirmation_title', locale)}\n{confirmation_text}",
                    reply_markup=products_buy_deeplink_confirm_finl(
                        position.position_id, i18n, locale
                    ),
                )
            else:
                await message.answer(
                    i18n.get_text(
                        "user_products.deeplink_insufficient_funds",
                        locale,
                        position_name=position.position_name,
                        price=position.position_price,
                    )
                )
                await _create_and_send_invoice(
                    message,
                    bot,
                    pay_amount_usd=position.position_price,
                    currency="LTC",
                    i18n=i18n,
                    locale=locale,
                )
        except (ValueError, IndexError):
            await message.answer(i18n.get_text("errors.invalid_link", locale))
            await show_main_menu(message, state, i18n, locale)

    elif deeplink_args.startswith("invoice_"):
        try:
            _, amount_str, currency = deeplink_args.split("_")
            amount = float(amount_str)
            await process_invoice_deeplink(message, bot, amount, currency, i18n, locale)
        except (ValueError, IndexError):
            await message.answer(i18n.get_text("errors.invalid_link", locale))
            await show_main_menu(message, state, i18n, locale)
    else:
        await show_main_menu(message, state, i18n, locale)


@router.callback_query(F.data.startswith("set_lang:"))
async def set_user_language(call: CallbackQuery, state: FSM, i18n: Translator):
    """Обрабатывает выбор языка, сохраняет его в БД и показывает главное меню."""
    lang_code = call.data.split(":")[1]
    Userx.update(user_id=call.from_user.id, language_code=lang_code)

    await call.message.edit_text(i18n.get_text("language_selection.changed", lang_code))

    await asyncio.sleep(0.5)
    await show_main_menu(call.message, state, i18n, lang_code)
