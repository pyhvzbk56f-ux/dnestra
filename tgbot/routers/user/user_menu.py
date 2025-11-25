# shop/tgbot/routers/user/user_menu.py

import asyncio
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime
from tgbot.data.config import get_desc, get_admins, get_operators
from tgbot.database import (
    Purchasesx,
    Buttonx,
    Settingsx,
    Subcategoryx,
    Positionx,
    Itemx,
    Disputex,
)

from tgbot.keyboards.reply_main import menu_frep
from tgbot.keyboards.inline_user import user_support_finl, channel_subscribe_finl
from tgbot.keyboards.inline_user_page import *
from tgbot.keyboards.inline_user_products import purchase_rating_finl # Импорт клавиатуры для оценки покупки
from tgbot.services.i18n import Translator
from tgbot.utils.misc.i18n_filters import I18nText

from tgbot.utils.const_functions import ded, del_message, convert_date, clear_html, PurchaseSource 
from tgbot.utils.misc.bot_models import FSM
from tgbot.utils.misc_functions import (
    insert_tags,
    get_items_available,
    get_categories_items,
    split_message_safely,
    bot_logger,
)  # upload_text
from tgbot.utils.text_functions import open_profile_user, send_purchase_details
from tgbot.utils.misc.bot_filters import IsSubscribed, IsCustomButton, IsAdmin
from tgbot.routers.user.user_disputes import DisputeSubmission, UpdateDispute
from tgbot.keyboards.inline_user import language_selection_keyboard

router = Router(name=__name__)




#! ОБЩАЯ ФУНКЦИЯ-ПРОВЕРКА ПОДПИСКИ ДЛЯ ХЕНДЛЕРОВ
async def check_subscription_and_proceed(message: Message, bot: Bot, i18n: Translator, locale: str, callback_func, **kwargs):
    """ #! Проверяет подписку. Если юзер подписан, выполняет основную функцию, иначе - просит подписаться."""
    subscription_result = await IsSubscribed().__call__(message, bot)
    
    if subscription_result is True:
        #! Передаем все аргументы в целевую функцию
        await callback_func(message=message, bot=bot, i18n=i18n, locale=locale, **kwargs)
    else:
        # Если вернулся список каналов, на которые нужно подписаться
        unsubscribed_channels = subscription_result
        text = i18n.get_text("user_menu.subscribe_prompt", locale)
        await message.answer(text, reply_markup=channel_subscribe_finl(unsubscribed_channels, i18n, locale))



@router.callback_query(F.data == "change_language")
async def change_language_handler(call: CallbackQuery, i18n: Translator, locale: str):
    await call.message.edit_text(
        i18n.get_text("language_selection.choose", locale),
        reply_markup=language_selection_keyboard(),
    )

#! ОСНОВНЫЕ ХЕНДЛЕРЫ МЕНЮ

@router.message(I18nText("buttons.buy"))
async def user_shop_router(message: Message, state: FSM, i18n: Translator, locale: str, bot: Bot):
    await check_subscription_and_proceed(message, bot, i18n, locale, user_shop_logic, state=state)

async def user_shop_logic(message: Message, state: FSM, bot: Bot, i18n: Translator, locale: str):
    await state.clear()
    get_categories = get_categories_items()
    if len(get_categories) >= 1:
        await message.answer(
            i18n.get_text("user_products.select_category", locale),
            reply_markup=prod_item_category_swipe_fp(0, i18n, locale),
        )
    else:
        await message.answer(i18n.get_text("user_menu.no_products_available", locale))

@router.message(I18nText("buttons.profile"))
async def user_profile_router(message: Message, state: FSM, i18n: Translator, locale: str, bot: Bot):
    await check_subscription_and_proceed(message, bot, i18n, locale, user_profile_logic, state=state)

async def user_profile_logic(message: Message, state: FSM, bot: Bot, i18n: Translator, locale: str):
    await state.clear()
    await open_profile_user(bot, message.from_user.id, i18n, locale)


@router.message(I18nText("buttons.availability"))
async def user_available_router(message: Message, state: FSM, i18n: Translator, locale: str, bot: Bot):
    await check_subscription_and_proceed(message, bot, i18n, locale, user_available_logic, state=state)

async def user_available_logic(message: Message, state: FSM, bot: Bot, i18n: Translator, locale: str):
    await state.clear()
    categories = get_categories_items()
    if not categories:
        await message.answer(i18n.get_text("user_menu.no_products_available", locale))
        return
    bot_info = await bot.get_me()
    bot_username = bot_info.username
    all_positions_raw = Positionx.get_all()
    all_positions = {
        pos.position_id: pos
        for pos in all_positions_raw
        if len(Itemx.gets(position_id=pos.position_id)) > 0
    }
    if not all_positions:
        return await message.answer(
            i18n.get_text("user_menu.no_products_available", locale)
        )
    get_settings = Settingsx.get()
    full_text = (
        f"<b>{get_settings.zagolovok_info}</b>\n\n"
        if get_settings.zagolovok_info != "None"
        else ""
    )
    full_text += i18n.get_text("user_menu.availability_low_stock_warning", locale)
    for category in categories:
        subcategories = Subcategoryx.gets(category_id=category.category_id)
        category_content = ""
        for subcategory in subcategories:
            positions_in_sub = [
                p
                for p in all_positions.values()
                if p.subcategory_id == subcategory.subcategory_id
            ]
            if positions_in_sub:
                category_content += f"📍 <b>{subcategory.subcategory_name}</b>\n"
                for position in positions_in_sub:
                    total_items = len(Itemx.gets(position_id=position.position_id))
                    availability = " ⚠️ |" if total_items <= 5 else ""
                    deeplink = (
                        f"https://t.me/{bot_username}?start=buy_{position.position_id}"
                    )
                    buy_button_text = i18n.get_text(
                        "user_menu.availability_buy_button", locale
                    )
                    category_content += f"    {position.position_name} | {int(position.position_price)} |{availability} <a href='{deeplink}'>{buy_button_text}</a>\n"
        if category_content:
            full_text += f"╔═══════════════╗\n🏘 <b>{category.category_name}</b>\n╚═══════════════╝\n"
            full_text += category_content + "\n"
    if get_settings.misc_info_check != "None":
        full_text += f"\n{get_settings.misc_info_check}"
    if full_text.strip() == "" or (
        get_settings.zagolovok_info != "None"
        and full_text.strip() == f"<b>{get_settings.zagolovok_info}</b>"
    ):
        return await message.answer(
            i18n.get_text("user_menu.no_products_available", locale)
        )
    message_chunks = split_message_safely(full_text)
    for chunk in message_chunks:
        if chunk.strip():
            await message.answer(chunk, disable_web_page_preview=True)
            await asyncio.sleep(0.3)


# --- ОСТАЛЬНЫЕ ХЕНДЛЕРЫ, КОТОРЫЕ ТАКЖЕ ДОЛЖНЫ ПРОВЕРЯТЬ ПОДПИСКУ ---

@router.message(F.text.in_(("❔ FAQ", "/faq")))
async def user_faq_router(message: Message, state: FSM, i18n: Translator, locale: str, bot: Bot):
    await check_subscription_and_proceed(message, bot, i18n, locale, user_faq_logic, state=state)

async def user_faq_logic(message: Message, state: FSM, bot: Bot, i18n: Translator, locale: str):
    await state.clear()
    get_settings = Settingsx.get()
    faq_text = get_settings.misc_faq
    if faq_text == "None":
        faq_text = ded(i18n.get_text("user_menu.faq_not_set", locale, bot_description=get_desc()))
    await message.answer(insert_tags(message.from_user.id, faq_text), disable_web_page_preview=True)


@router.message(F.text.in_(("☎️ Support", "/support", "☎️ Поддержка")))
async def user_support_router(message: Message, state: FSM, i18n: Translator, locale: str, bot: Bot):
    await check_subscription_and_proceed(message, bot, i18n, locale, user_support_logic, state=state)

async def user_support_logic(message: Message, state: FSM, bot: Bot, i18n: Translator, locale: str):
    await state.clear()
    get_settings = Settingsx.get()
    support_contact = get_settings.misc_support
    if support_contact == "None":
        await message.answer(ded(i18n.get_text("user_menu.support_not_set", locale, bot_description=get_desc())), disable_web_page_preview=True)
    else:
        await message.answer(i18n.get_text("user_menu.support_prompt", locale), reply_markup=user_support_finl(support_contact, i18n, locale))


# --- СЛУЖЕБНЫЕ И ВТОРОСТЕПЕННЫЕ ХЕНДЛЕРЫ ---

@router.callback_query(F.data == "user_profile")
async def user_profile_return(call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str):
    await state.clear()
    await del_message(call.message)
    await open_profile_user(bot, call.from_user.id, i18n, locale)


@router.callback_query(F.data == "user_purchases")
async def user_purchases(call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str):
    all_purchases = Purchasesx.gets(user_id=call.from_user.id)
    last_purchases = all_purchases[-5:]

    if not last_purchases:
        return await call.answer(i18n.get_text("user_menu.no_purchases", locale), show_alert=True)
        
    await call.answer(i18n.get_text("user_menu.your_purchases", locale))
    await del_message(call.message)

    for purchase in last_purchases:
        rating_markup = None
        if purchase.rating == 0:
            rating_markup = purchase_rating_finl(purchase.purchase_receipt, i18n, locale)
        await send_purchase_details(bot=bot,
            chat_id=call.from_user.id,
            purchase=purchase,
            i18n=i18n,locale=locale,
            caption_template_key="user_menu.purchase_history_item_full",
            source=PurchaseSource.BOT,
            reply_markup=rating_markup
        )
        await asyncio.sleep(0.2)
    await open_profile_user(bot, call.from_user.id, i18n, locale)


@router.callback_query(F.data.startswith("rate_purchase:"))
async def rate_purchase_handler(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    try:
        purchase_receipt, rating_str = call.data.split(":")[1:]
        rating = int(rating_str)
    except (ValueError, IndexError):
        await call.answer(i18n.get_text("user_menu.error_data_retry", locale), show_alert=True)
        return
    purchase = Purchasesx.get(purchase_receipt=purchase_receipt)
    if not purchase or purchase.user_id != call.from_user.id:
        await call.answer(i18n.get_text("user_menu.error_purchase_not_found", locale), show_alert=True)
        return
    if purchase.rating != 0:
        await call.answer(i18n.get_text("user_menu.already_rated", locale), show_alert=True)
        return
    if rating == 1:
        Purchasesx.update(purchase_receipt=purchase_receipt, rating=1)
        text_to_show = i18n.get_text("user_menu.rating_thanks", locale)
        if call.message.photo:
            # Если есть фото, редактируем подпись и убираем кнопки
            await call.message.edit_caption(caption=text_to_show, reply_markup=None)
        else:
            # Если это текстовое сообщение, редактируем текст
            await call.message.edit_text(text_to_show, reply_markup=None)
    elif rating == -1:
        await state.set_state(DisputeSubmission.waiting_for_media)
        await state.update_data(purchase_receipt=purchase_receipt)
        text_to_show = i18n.get_text("user_menu.dispute_prompt_video", locale)
        if call.message.photo:
            # Редактируем подпись, чтобы показать инструкцию к жалобе
            await call.message.edit_caption(caption=text_to_show, reply_markup=None)
        else:
            await call.message.edit_text(text_to_show, reply_markup=None)

@router.callback_query(F.data == "check_subscription")
async def check_subscription_handler(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    subscription_result = await IsSubscribed().__call__(call, bot)

    if subscription_result is True:
        await call.message.delete()
        await call.message.answer(
            i18n.get_text("user_menu.subscribe_thank_you", locale),
            reply_markup=menu_frep(call.from_user.id, i18n, locale),
        )
    else:
        # Обновляем сообщение с актуальным списком каналов для подписки
        unsubscribed_channels = subscription_result
        await call.message.edit_reply_markup(
            reply_markup=channel_subscribe_finl(unsubscribed_channels, i18n, locale)
        )
        await call.answer(i18n.get_text("user_menu.subscribe_not_yet", locale), show_alert=True)
        

@router.message(IsCustomButton())
async def handle_custom_buttons(message: Message, i18n: Translator, locale: str, bot: Bot):
    await check_subscription_and_proceed(message, bot, i18n, locale, handle_custom_buttons_logic)

async def handle_custom_buttons_logic(message: Message, i18n: Translator, locale: str, **kwargs):
    button = Buttonx.get_by_name(button_name=message.text)
    if button:
        try:
            await message.answer(button.button_data, parse_mode="HTML")
        except Exception as e:
            await message.answer(i18n.get_text("user_menu.custom_button_error", locale))
            bot_logger.error(f"Ошибка парсинга HTML для кнопки '{button.button_name}': {e}")


@router.callback_query(F.data == "user_disputes")
async def user_disputes_list(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    await call.message.delete()
    all_user_disputes = Disputex.gets(user_id=call.from_user.id)
    sorted_disputes = sorted(all_user_disputes, key=lambda d: d.created_at)
    last_five_disputes = sorted_disputes[-10:]
    if not last_five_disputes:
        await call.message.answer(i18n.get_text("user_disputes_view.no_disputes", locale))
        return
    open_disputes_for_keyboard = []
    last_message_id = None
    for dispute in last_five_disputes:
        purchase = Purchasesx.get(purchase_receipt=dispute.purchase_receipt)
        if not purchase:
            continue
        status_map = {
            "resolved_accepted": i18n.get_text("user_disputes_view.status_accepted", locale),
            "resolved_rejected": i18n.get_text("user_disputes_view.status_rejected", locale),
            "open": i18n.get_text("buttons.open", locale),}
        status_text = status_map.get(
            dispute.status, i18n.get_text("user_disputes_view.status_unknown", locale)
        )
        message_text = i18n.get_text(
            "user_disputes_view.list_item_template",
            locale,
            dispute_id=dispute.dispute_id,
            created_at=convert_date(dispute.created_at),
            item_name=purchase.purchase_position_name,
            receipt=purchase.purchase_receipt,
            status=status_text,
        )
        if dispute.status != "open" and dispute.resolution_comment:
            message_text += i18n.get_text(
                "user_disputes_view.resolution_line",
                locale,
                comment=dispute.resolution_comment,
            )
        sent_message = await call.message.answer(message_text)
        last_message_id = sent_message.message_id
        if dispute.status == "open":
            open_disputes_for_keyboard.append(dispute)
    if open_disputes_for_keyboard and last_message_id:
        builder = InlineKeyboardBuilder()
        for dispute in open_disputes_for_keyboard:
            purchase = Purchasesx.get(purchase_receipt=dispute.purchase_receipt)
            btn_text = f"#{dispute.dispute_id} | {purchase.purchase_position_name[:20]}"
            builder.button(
                text=btn_text, callback_data=f"view_open_dispute:{dispute.dispute_id}"
            )
        builder.adjust(1)
        await bot.edit_message_reply_markup(
            chat_id=call.from_user.id,
            message_id=last_message_id,
            reply_markup=builder.as_markup(),
        )
@router.callback_query(F.data.startswith("view_open_dispute:"))
async def view_open_dispute_handler(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    dispute_id = int(call.data.split(":")[1])
    dispute = Disputex.get(dispute_id=dispute_id)
    purchase = Purchasesx.get(purchase_receipt=dispute.purchase_receipt)
    media_count = (
        len(dispute.media_message_ids.split(",")) if dispute.media_message_ids else 0
    )
    media_text = (
        i18n.get_text("user_disputes_view.media_count", locale, count=media_count)
        if media_count > 0
        else i18n.get_text("user_disputes_view.media_absent", locale)
    )
    status_text = i18n.get_text("buttons.open", locale)
    message_text = i18n.get_text(
        "user_disputes_view.view_item_template",
        locale,
        dispute_id=dispute.dispute_id,
        created_at=convert_date(dispute.created_at),
        item_name=purchase.purchase_position_name,
        receipt=purchase.purchase_receipt,
        media_text=media_text,
        status=status_text,
    )
    builder = InlineKeyboardBuilder()
    builder.button(
        text=i18n.get_text("user_disputes_view.add_media_button", locale),
        callback_data=f"add_media_to_dispute:{dispute_id}",
    )
    await call.message.edit_text(message_text, reply_markup=builder.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("add_media_to_dispute:"))
async def add_media_to_dispute_start(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    dispute_id = int(call.data.split(":")[1])
    await state.set_state(UpdateDispute.waiting_for_media)
    await state.update_data(dispute_id_to_update=dispute_id)
    await call.message.edit_text(
        i18n.get_text("user_disputes_view.add_media_prompt", locale)
    )
    await call.answer()