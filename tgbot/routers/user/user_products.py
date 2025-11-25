# shop/tgbot/routers/user/user_products.py

import datetime
import asyncio
import os

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, FSInputFile
from tgbot.data.config import get_admins, get_operators, BASE_DIR
from tgbot.database import (
    Categoryx,
    Positionx,
    PositionModel,
    Purchasesx,
    Settingsx,
    Userx,
    UserModel,
    Subcategoryx,
    Itemx,
    AggregatorTrafficx,
)
from tgbot.keyboards.inline_user import refill_method_buy_finl
from tgbot.keyboards.inline_user_page import *
from tgbot.keyboards.inline_user_products import (
    products_buy_confirm_finl,
    purchase_rating_finl,
)
from tgbot.keyboards.reply_main import menu_frep
from tgbot.services.i18n import Translator
from tgbot.utils.const_functions import (
    convert_date,
    ded,
    del_message,
    gen_id,
    get_unix,
    PurchaseSource,
)
from tgbot.utils.misc.bot_logging import bot_logger
from tgbot.utils.misc.bot_models import FSM, ARS
from tgbot.utils.misc_functions import get_positions_items, send_notification
from tgbot.utils.text_functions import send_purchase_details

router = Router(name=__name__)


#! Страницы выбора категории для покупки товара
@router.callback_query(F.data.startswith("buy_category_swipe:"))
async def user_buy_category_swipe(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    remover = int(call.data.split(":")[1])
    await call.message.edit_text(
        i18n.get_text("user_products.select_category", locale),
        reply_markup=prod_item_category_swipe_fp(remover, i18n, locale),
    )


#! Открытие подкатегории для покупки товара после выбора категории
@router.callback_query(F.data.startswith("buy_category_open:"))
async def user_buy_category_open(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id = int(call.data.split(":")[1])
    get_category = Categoryx.get(category_id=category_id)
    get_subcategories = Subcategoryx.gets(category_id=category_id)
    positions_subcategories_with_items = [
        subcategory
        for subcategory in get_subcategories
        if get_positions_items(category_id, subcategory.subcategory_id)
    ]

    await del_message(call.message)

    if len(positions_subcategories_with_items) > 1:
        await call.message.answer(
            i18n.get_text(
                "user_products.select_subcategory_in_category",
                locale,
                category_name=get_category.category_name,
            ),
            reply_markup=prod_item_subcategory_swipe_fp(0, category_id, i18n, locale),
        )
    elif len(positions_subcategories_with_items) == 1:
        subcategory = positions_subcategories_with_items[0]
        await call.message.answer(
            i18n.get_text(
                "user_products.position_in_category_and_subcategory",
                locale,
                category_name=get_category.category_name,
                subcategory_name=subcategory.subcategory_name,
            ),
            reply_markup=prod_item_position_swipe_fp(
                0, category_id, subcategory.subcategory_id, i18n, locale
            ),
        )
    else:
        bot_logger.warning(f"user_buy_category_open: Категория {category_id} пуста")
        await call.answer(
            i18n.get_text("user_products.no_items_in_category", locale),
            show_alert=True,
            cache_time=5,
        )


#! Страницы выбора подкатегории для покупки товара
@router.callback_query(F.data.startswith("buy_subcategory_swipe:"))
async def user_buy_subcategory_swipe(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id, remover = map(int, call.data.split(":")[1:])
    get_category = Categoryx.get(category_id=category_id)
    await del_message(call.message)
    await call.message.answer(
        i18n.get_text(
            "user_products.current_category",
            locale,
            category_name=get_category.category_name,
        ),
        reply_markup=prod_item_subcategory_swipe_fp(remover, category_id, i18n, locale),
    )


#! подкатегории с выбором позиции для покупки товара
@router.callback_query(F.data.startswith("buy_subcategory_open:"))
async def user_buy_subcategory_open(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id, subcategory_id, remover = map(int, call.data.split(":")[1:])
    get_category = Categoryx.get(category_id=category_id)
    get_subcategory = Subcategoryx.get(subcategory_id=subcategory_id)
    positions_with_items = [
        p
        for p in Positionx.gets(subcategory_id=subcategory_id)
        if len(Itemx.gets(position_id=p.position_id)) >= 1
    ]

    if len(positions_with_items) >= 1:
        await del_message(call.message)
        await call.message.answer(i18n.get_text("user_products.current_category_and_subcategory",locale,category_name=get_category.category_name,subcategory_name=get_subcategory.subcategory_name,),reply_markup=prod_item_position_swipe_fp( remover, category_id, subcategory_id, i18n, locale),)
    else:
        await call.answer(i18n.get_text( "user_products.no_positions_in_subcategory", locale, subcategory_name=get_subcategory.subcategory_name, ), True, cache_time=5, )


#!################################### ПОКУПКА ###################################
#! Покупка товара
@router.callback_query(F.data.startswith("buy_item_open:"))
async def user_buy_open(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    position_id, remover = map(int, call.data.split(":")[1:])
    get_position = Positionx.get(position_id=position_id)
    get_user = Userx.get(user_id=call.from_user.id)

    if int(get_user.user_balance) < int(get_position.position_price):
        await call.message.answer(i18n.get_text("user_products.insufficient_funds_for_purchase", locale),reply_markup=refill_method_buy_finl(i18n, locale),)
        return await call.answer(cache_time=5)

    if len(Itemx.gets(position_id=position_id)) < 1:
        return await call.answer(i18n.get_text("user_products.no_items_in_stock", locale), True)

    await state.clear()
    await del_message(call.message)
    await call.message.answer(
        ded(
            f"{i18n.get_text('user_products.purchase_confirmation_title', locale)}\n"
            f"{i18n.get_text('user_products.purchase_confirmation_body', locale, position_name=get_position.position_name, count=1, price=get_position.position_price)}"
        ),
        reply_markup=products_buy_confirm_finl( position_id, get_position.category_id, get_position.subcategory_id, 1, i18n, locale, ), )


#!##################################################################
#! ОБРАБОТЧИК для подтверждения покупки через диплинк
@router.callback_query(F.data.startswith("buy_item_confirm_deeplink:"))
async def user_buy_confirm_deeplink(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str, arSession: ARS
):
    position_id = int(call.data.split(":")[1])
    get_position = Positionx.get(position_id=position_id)
    get_user = Userx.get(user_id=call.from_user.id)
    #! Повторная проверка баланса и наличия товара на случай, если ситуация изменилась
    
    if get_user.user_balance < get_position.position_price:
        return await call.message.edit_text(i18n.get_text("user_products.deeplink_insufficient_funds", locale))
    
    if len(Itemx.gets(position_id=position_id)) < 1:
        return await call.message.edit_text(i18n.get_text("user_products.deeplink_out_of_stock", locale))
        
    await _process_successful_purchase(call, bot, get_user, get_position, count=1, i18n=i18n, locale=locale, arSession=arSession)



#! ОБРАБОТЧИК для отмены покупки через диплинк
@router.callback_query(F.data == "buy_item_cancel_deeplink")
async def user_buy_cancel_deeplink(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
    await call.message.edit_text(i18n.get_text("user_products.deeplink_purchase_cancelled", locale))


#!####################################################################
#! ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ОБРАБОТКИ УСПЕШНОЙ ПОКУПКИ
async def _process_successful_purchase(call: CallbackQuery,bot: Bot,user: UserModel,position: PositionModel,count: int,i18n: Translator,locale: str, arSession: ARS):
    """#! Выполняет всю логику покупки в соответствии с user_buy_confirm  списание, запись в БД, уведомления пользователю и администраторам, предложение оценки."""
    
    # Логирование подтверждения покупки
    bot_logger.info(
        i18n.get_text(
            "log_messages.log_purchase_confirmed",
            "en", # Логи всегда на английском
            user_id=user.user_id,
            user_login=user.user_login,
            count=count,
            position_name=position.position_name,
            position_id=position.position_id,
            price=position.position_price * count
        )
    )
    
    get_items = Itemx.gets(position_id=position.position_id)
    if len(get_items) < count:
        bot_logger.info(f"Username: {call.from_user.username} id: {call.from_user.id} product is finished")
        return await call.message.edit_text(i18n.get_text("user_products.deeplink_out_of_stock", locale))
    
    get_subcategory = Subcategoryx.get(subcategory_id=position.subcategory_id)
    get_category = Categoryx.get(category_id=position.category_id)
    purchase_price = round(position.position_price * count, 2)

    if user.user_balance < purchase_price:
        bot_logger.info(f"Username: {call.from_user.username} id: {call.from_user.id} insufficient_funds" )
        return await call.message.edit_text( i18n.get_text("user_products.deeplink_insufficient_funds", locale) )
    
    save_items, _ = Itemx.buy(get_items, count)
    user_balance_before = user.user_balance
    new_balance = round(user_balance_before - purchase_price, 2)
    Userx.update(user.user_id, user_balance=new_balance)

    # Уведомляем агрегатор об изменении баланса
    from tgbot.utils.misc_functions import notify_aggregator_of_balance_update
    asyncio.create_task(notify_aggregator_of_balance_update(
        bot=bot,
        arSession=arSession,
        user_id=user.user_id,
        new_balance=new_balance
    ))
    
    AggregatorTrafficx.log_purchase(user.user_id)
    
    purchase_receipt = gen_id()
    purchase_unix = get_unix()
    purchase_data_str = "\n".join(save_items)
    
    Purchasesx.add(
        user_id=user.user_id,
        user_balance_before=user_balance_before,
        user_balance_after=new_balance,
        purchase_receipt=purchase_receipt,
        purchase_data=purchase_data_str,
        purchase_count=count,
        purchase_price=purchase_price,
        purchase_price_one=position.position_price,
        purchase_position_id=position.position_id,
        purchase_position_name=position.position_name,
        purchase_category_id=get_category.category_id,
        purchase_category_name=get_category.category_name,
        purchase_subcategory_id=get_subcategory.subcategory_id,
        purchase_subcategory_name=get_subcategory.subcategory_name,
        from_site=False,
    )
    await del_message(call.message)

    purchase_object = Purchasesx.get(purchase_receipt=purchase_receipt)

    # 1. Уведомление пользователю 
    await send_purchase_details(bot=bot,
        chat_id=user.user_id,
        purchase=purchase_object,
        i18n=i18n,locale=locale,
        caption_template_key="user_products.purchase_receipt_full",
        source=PurchaseSource.BOT,
        reply_markup=None
    )

    # 2. Отдельное сообщение с кнопками оценки
    await bot.send_message(
        chat_id=user.user_id,
        text=i18n.get_text("user_products.purchase_rating_prompt", locale),
        reply_markup=purchase_rating_finl(str(purchase_receipt), i18n, locale),
    )

    # 3. Уведомление администраторам и операторам
    users_list = set(get_admins()) | set(get_operators())
    for user_id in users_list:
        try:
            recipient_user = Userx.get(user_id=user_id)
            recipient_locale = recipient_user.language_code if recipient_user else "en"
            await send_purchase_details(bot=bot,
                chat_id=user_id,
                purchase=purchase_object,
                i18n=i18n, locale=str(recipient_locale),
                source=PurchaseSource.BOT,
                caption_template_key="admin_purchase.receipt_full"
            )
        except Exception as e:
            bot_logger.error(i18n.get_text( "user_products.admin_notification_error", "en", admin_id=user_id, error=e, ) )



################################
# Подтверждение покупки товара
@router.callback_query(F.data.startswith("buy_item_confirm:"))
async def user_buy_confirm(call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str, arSession: ARS):
    """#! Обрабатывает подтверждение покупки из меню бота, вызывая общую логику."""
    position_id, _, _, count = map(int, call.data.split(":")[1:])
    get_position = Positionx.get(position_id=position_id)
    get_user = Userx.get(user_id=call.from_user.id)

    # Вызываем общую функцию для обработки покупки
    await _process_successful_purchase(call, bot, get_user, get_position, count, i18n, locale, arSession)


#! Страницы позиций для покупки товара
@router.callback_query(F.data.startswith("buy_position_swipe:"))
async def user_buy_position_swipe(call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str):
    category_id, subcategory_id, remover = map(int, call.data.split(":")[1:])
    get_category = Categoryx.get(category_id=category_id)
    get_subcategory = Subcategoryx.get(subcategory_id=subcategory_id)

    #! Обновляем сообщение с новой страницей позиций
    await call.message.edit_text(
        i18n.get_text(
            "user_products.current_category_and_subcategory",
            locale,
            category_name=get_category.category_name,
            subcategory_name=get_subcategory.subcategory_name,
        ),
        reply_markup=prod_item_position_swipe_fp(
            remover, category_id, subcategory_id, i18n, locale
        ),
    )
