# shop/tgbot/routers/admin/admin_disputes.py
import asyncio
import os
import re
from aiogram import Router, Bot, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from tgbot.data.config import BASE_DIR
from tgbot.database import Disputex, Purchasesx, Userx, Invoicex
from tgbot.services.i18n import Translator
from tgbot.utils.misc.i18n_filters import I18nText
from tgbot.utils.const_functions import convert_date, ded, get_unix, bot_logger, convert_day
from tgbot.keyboards.inline_helper import build_pagination_finl
from tgbot.utils.text_functions import open_profile_admin, purchase_open_admin
from tgbot.utils.misc.bot_models import ARS, FSM


router = Router(name=__name__)


class DisputeResolution(StatesGroup):
    waiting_for_reject_reason = State()
    waiting_for_accept_reason = State()


async def format_dispute_list(disputes: list, i18n: Translator, locale: str) -> str:
    if not disputes:
        return i18n.get_text("admin_disputes.queue_empty", locale)

    text = i18n.get_text("admin_disputes.queue_title", locale)
    for dispute in disputes:
        purchase = Purchasesx.get(purchase_receipt=dispute.purchase_receipt)
        user = Userx.get(user_id=dispute.user_id)
        if purchase and user:
            text += i18n.get_text(
                "admin_disputes.queue_item",
                locale,
                dispute_id=dispute.dispute_id,
                date=convert_date(dispute.created_at, second=False),
                login=user.user_login,
                position_name=purchase.purchase_position_name,
                receipt=purchase.purchase_receipt,
            )
    return text


async def dispute_list_menu(
    bot: Bot, message: Message, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    disputes = Disputex.gets(status="open")
    text = await format_dispute_list(disputes[:10], i18n, locale)
    builder = InlineKeyboardBuilder()

    builder.button(
        text=i18n.get_text("admin_disputes.resolved_button", locale),
        callback_data="resolved_disputes:page:0",
    )

    for dispute in disputes[:10]:
        purchase = Purchasesx.get(purchase_receipt=dispute.purchase_receipt)
        user = Userx.get(user_id=dispute.user_id)
        if not purchase or not user:
            continue
        btn_text = (
            f"#{dispute.dispute_id} | {purchase.purchase_position_name[:15]}... | "
            f"@{user.user_login[:10]} | {convert_date(dispute.created_at, full=False)}"
        )
        builder.button(
            text=btn_text, callback_data=f"dispute:view:{dispute.dispute_id}:0"
        )

    pagination_btns = build_pagination_finl(disputes, "dispute:page", 0, i18n, locale)
    builder.row(*pagination_btns)
    builder.adjust(1)
    await message.answer(text, reply_markup=builder.as_markup())


# Архивные жалобы
async def format_resolved_dispute_list(
    disputes: list, i18n: Translator, locale: str
) -> str:
    if not disputes:
        return i18n.get_text("admin_disputes.archive_empty", locale)

    text = i18n.get_text("admin_disputes.archive_title", locale)
    for dispute in disputes:
        purchase = Purchasesx.get(purchase_receipt=dispute.purchase_receipt)
        user = Userx.get(user_id=dispute.user_id)
        status_text = (
            i18n.get_text("admin_disputes.status_accepted", locale)
            if dispute.status == "resolved_accepted"
            else i18n.get_text("admin_disputes.reject_button", locale)
        )
        if purchase and user:
            text += i18n.get_text(
                "admin_disputes.archive_item",
                locale,
                dispute_id=dispute.dispute_id,
                receipt=purchase.purchase_receipt,
                status=status_text,
                created_at=convert_date(dispute.created_at, second=False),
                resolved_at=convert_date(dispute.resolved_at, second=False),
                login=user.user_login,
                user_id=user.user_id,
                user_name=user.user_name,
                category=purchase.purchase_category_name,
                subcategory=purchase.purchase_subcategory_name,
                position_name=purchase.purchase_position_name,
                resolution=dispute.resolution_comment or dispute.complaint_text,
            )
    return text


@router.callback_query(F.data.startswith("resolved_disputes:page:"))
async def admin_resolved_disputes_list(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    remover = int(call.data.split(":")[2])
    resolved_disputes = Disputex.gets_resolved()
    text = await format_resolved_dispute_list(
        resolved_disputes[remover : remover + 10], i18n, locale
    )

    builder = InlineKeyboardBuilder()
    builder.button(
        text=i18n.get_text("admin_disputes.back_to_active", locale),
        callback_data="admin:view_disputes",
    )
    pagination_btns = build_pagination_finl(
        resolved_disputes, "resolved_disputes:page", remover, i18n, locale
    )
    builder.row(*pagination_btns)
    builder.adjust(1)
    await call.message.edit_text(text, reply_markup=builder.as_markup())


# Кнопка в главном меню
@router.message(I18nText("buttons.disputes"))
async def admin_disputes_start(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    await dispute_list_menu(bot, message, state, i18n, locale)


# Callback от напоминания
@router.callback_query(F.data == "admin:view_disputes")
async def admin_disputes_start_callback(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    await call.message.delete()
    await dispute_list_menu(bot, call.message, state, i18n, locale)


# Пагинация
@router.callback_query(F.data.startswith("dispute:page:"))
async def admin_disputes_page(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    remover = int(call.data.split(":")[2])
    disputes = Disputex.gets(status="open")
    text = await format_dispute_list(disputes[remover : remover + 10], i18n, locale)

    builder = InlineKeyboardBuilder()
    for dispute in disputes[remover : remover + 10]:
        purchase = Purchasesx.get(purchase_receipt=dispute.purchase_receipt)
        user = Userx.get(user_id=dispute.user_id)
        if not purchase or not user:
            continue
        btn_text = (
            f"#{dispute.dispute_id} | {purchase.purchase_position_name[:15]}... | "
            f"@{user.user_login[:10]} | {convert_date(dispute.created_at, full=False)}"
        )
        builder.button(
            text=btn_text, callback_data=f"dispute:view:{dispute.dispute_id}:{remover}"
        )

    pagination_btns = build_pagination_finl(
        disputes, "dispute:page", remover, i18n, locale
    )
    builder.row(*pagination_btns)
    builder.adjust(1)
    await call.message.edit_text(text, reply_markup=builder.as_markup())


# Просмотр одной жалобы
@router.callback_query(F.data.startswith("dispute:view:"))
async def admin_dispute_view(call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str):
    await call.message.delete()
    dispute_id = int(call.data.split(":")[2])
    remover = int(call.data.split(":")[3])
    
    dispute = Disputex.get(dispute_id=dispute_id)
    if not dispute or dispute.status != "open":
        return await call.answer(i18n.get_text("admin_disputes.already_processed", locale), show_alert=True)

    purchase = Purchasesx.get(purchase_receipt=dispute.purchase_receipt)
    user = Userx.get(user_id=dispute.user_id)
    chat_id = call.from_user.id

    # 1. Формируем подробный текстовый чек ЗАРАНЕЕ, на случай если фото не найдется
    source_text = "SITE" if purchase.from_site else "SHOP"
    full_receipt_text = i18n.get_text("admin_purchase.receipt_full", locale, 
        receipt_id=purchase.purchase_receipt,
        source=source_text,
        user_id=user.user_id,
        user_name=user.user_name,
        category_name=purchase.purchase_category_name,
        subcategory_name=purchase.purchase_subcategory_name,
        position_name=purchase.purchase_position_name,
        price=purchase.purchase_price,
        balance_before=purchase.user_balance_before,
        balance_after=purchase.user_balance_after,
        purchase_date=convert_date(purchase.purchase_unix),
        rating_status=i18n.get_text("buttons.open", locale)
    )

    # 2. Интегрируем вашу логику для отправки изображения
    try:
        raw_purchase_data = purchase.purchase_data
        
        if raw_purchase_data and raw_purchase_data.strip() and not purchase.purchase_data_is_archived:
            image_url_to_send = None
            bbcode_match = re.search(r'\[img\](https?://[^\s\[\]]+)\[/img\]', raw_purchase_data, re.IGNORECASE)
            
            if bbcode_match:
                image_url_to_send = bbcode_match.group(1)
            else:
                url_match = re.search(r'https?://[^\s]+', raw_purchase_data)
                if url_match:
                    image_url_to_send = url_match.group(0)

            if image_url_to_send:
                await bot.send_photo(chat_id=chat_id, photo=image_url_to_send)
            else:
                first_line = raw_purchase_data.split('\n')[0].strip()
                if first_line:
                    full_path = BASE_DIR / first_line
                    if os.path.exists(full_path):
                        await bot.send_photo(chat_id=chat_id, photo=FSInputFile(full_path))
                    else:
                        bot_logger.warning(f"File not found for receipt {purchase.purchase_receipt}. Data: '{raw_purchase_data}'. No image will be sent.")
                else:
                    raise ValueError("Purchase data is empty or contains only whitespace.")
    except Exception as e:
        bot_logger.error(f"Could not send purchase image for dispute {dispute_id}: {e}")

    # 3. Собираем подробную информацию о пользователе
    user_purchases = Purchasesx.gets(user_id=user.user_id)
    all_invoices = Invoicex.gets(user_id=user.user_id)
    paid_invoices = Invoicex.gets(user_id=user.user_id, status="finished")
    days_since_reg = (get_unix() - user.user_unix) // 86400
    
    total_purchases = len(user_purchases)
    successful_purchases = sum(1 for p in user_purchases if p.rating == 1)
    failed_purchases = sum(1 for p in user_purchases if p.rating == -1)
    
    success_rate = round((successful_purchases / total_purchases) * 100) if total_purchases > 0 else 0
    fail_rate = round((failed_purchases / total_purchases) * 100) if total_purchases > 0 else 0
    
    # 4. Форматируем комментарии пользователя
    comments_text = i18n.get_text("admin_disputes.comment_not_provided", locale)
    if dispute.complaint_text:
        cleaned_comments = re.sub(r'<b>Комментарий от .*?<\/b>\n', '', dispute.complaint_text, flags=re.IGNORECASE)
        comments_text = f'"{cleaned_comments.strip()}"'
        
    # 5. Собираем основной текст, используя ключ из ru.json
    main_text = i18n.get_text("admin_disputes.view_details_full", locale,
        dispute_id=dispute.dispute_id,
        receipt=purchase.purchase_receipt,
        source=source_text,
        purchase_date=convert_date(purchase.purchase_unix),
        price=purchase.purchase_price,
        position_name=purchase.purchase_position_name,
        category_name=purchase.purchase_category_name,
        subcategory_name=purchase.purchase_subcategory_name,
        balance_before=purchase.user_balance_before,
        balance_after=purchase.user_balance_after,
        user_name=user.user_name,
        login=user.user_login,
        user_id=user.user_id,
        registration_date=convert_date(user.user_unix, full=False, second=False),
        days_since_reg=convert_day(days_since_reg, i18n, locale),
        balance=user.user_balance,
        total_given=user.user_give,
        total_refilled=user.user_refill,
        invoices_issued=len(all_invoices),
        invoices_paid=len(paid_invoices),
        items_bought=total_purchases,
        successful_count=successful_purchases,
        successful_percentage=success_rate,
        failed_count=failed_purchases,
        failed_percentage=fail_rate,
        comments_text=comments_text
    )

    # 6. Создаем новую клавиатуру
    builder = InlineKeyboardBuilder()
    builder.button(text=i18n.get_text("buttons.success", locale), callback_data=f"dispute:reject:{dispute.dispute_id}:{remover}")
    builder.button(text=i18n.get_text("buttons.fail", locale), callback_data=f"dispute:accept:{dispute.dispute_id}:{remover}")
    
    # 7. Отправляем основное сообщение
    await call.message.answer(main_text, reply_markup=builder.as_markup())

    # 8. Отправляем медиафайлы, если они есть
    if dispute.media_chat_id and dispute.media_message_ids:
        message_ids = [int(mid) for mid in dispute.media_message_ids.split(",")]
        await call.message.answer(i18n.get_text("admin_disputes.user_media", locale))
        for msg_id in message_ids:
            try:
                await bot.forward_message(
                    chat_id=call.from_user.id,
                    from_chat_id=dispute.media_chat_id,
                    message_id=msg_id,
                )
                await asyncio.sleep(0.3)
            except Exception as e:
                await call.message.answer(i18n.get_text("admin_disputes.media_load_error", locale, msg_id=msg_id, error=e))
    
    await call.answer()


# Обработка решений
@router.callback_query(F.data.startswith("dispute:reject:"))
async def dispute_reject_start(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
    dispute_id, remover = int(call.data.split(":")[2]), int(call.data.split(":")[3])
    await state.set_state(DisputeResolution.waiting_for_reject_reason)
    await state.update_data(dispute_id=dispute_id, remover=remover)
    await call.message.edit_text(i18n.get_text("admin_disputes.enter_comment_prompt", locale))


@router.callback_query(F.data.startswith("dispute:accept:"))
async def dispute_accept_start(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    dispute_id, remover = int(call.data.split(":")[2]), int(call.data.split(":")[3])
    await state.set_state(DisputeResolution.waiting_for_accept_reason)
    await state.update_data(dispute_id=dispute_id, remover=remover)
    await call.message.edit_text(
        i18n.get_text("admin_disputes.enter_comment_prompt", locale)
    )


# FSM обработчики
@router.message(DisputeResolution.waiting_for_reject_reason)
async def process_reject_reason(
    message: Message, state: FSM, bot: Bot, i18n: Translator, locale: str
):
    data = await state.get_data()
    dispute = Disputex.get(dispute_id=data["dispute_id"])
    Disputex.update(
        dispute_id=dispute.dispute_id,
        status="resolved_rejected",
        resolution_comment=message.text,
        resolved_by_admin_id=message.from_user.id,
        resolved_at=get_unix(),
    )
    Purchasesx.update(purchase_receipt=dispute.purchase_receipt, rating=1)

    user_locale = Userx.get(user_id=dispute.user_id).language_code or "en"
    user_text = ded(
        i18n.get_text(
            "admin_disputes.user_notification_rejected_title",
            user_locale,
            dispute_id=dispute.dispute_id,
        )
        + "\n"
        + i18n.get_text(
            "admin_disputes.user_notification_resolution_comment",
            user_locale,
            comment=message.text,
        )
    )
    try:
        await bot.send_message(dispute.user_id, user_text)
    except Exception as e:
        await message.answer(
            i18n.get_text("admin_disputes.user_notification_failed", locale, error=e)
        )

    await message.answer(
        i18n.get_text(
            "admin_disputes.admin_notification_rejected",
            locale,
            dispute_id=dispute.dispute_id,
            receipt=dispute.purchase_receipt,
        )
    )
    await dispute_list_menu(bot, message, state, i18n, locale)


@router.message(DisputeResolution.waiting_for_accept_reason)
async def process_accept_reason(
    message: Message, state: FSM, bot: Bot, i18n: Translator, locale: str
):
    data = await state.get_data()
    dispute = Disputex.get(dispute_id=data["dispute_id"])
    Disputex.update(
        dispute_id=dispute.dispute_id,
        status="resolved_accepted",
        resolution_comment=message.text,
        resolved_by_admin_id=message.from_user.id,
        resolved_at=get_unix(),
    )
    Purchasesx.update(purchase_receipt=dispute.purchase_receipt, rating=-1)

    user_locale = Userx.get(user_id=dispute.user_id).language_code or "en"
    user_text = ded(
        i18n.get_text(
            "admin_disputes.user_notification_accepted_title",
            user_locale,
            dispute_id=dispute.dispute_id,
        )
        + "\n"
        + i18n.get_text(
            "admin_disputes.user_notification_resolution_comment",
            user_locale,
            comment=message.text,
        )
    )
    try:
        await bot.send_message(dispute.user_id, user_text)
    except Exception as e:
        await message.answer(
            i18n.get_text("admin_disputes.user_notification_failed", locale, error=e)
        )

    await message.answer(
        i18n.get_text(
            "admin_disputes.admin_notification_accepted",
            locale,
            dispute_id=dispute.dispute_id,
            receipt=dispute.purchase_receipt,
        )
    )
    await dispute_list_menu(bot, message, state, i18n, locale)


# ОБРАБОТЧИКИ ДЛЯ КНОПОК "ОТКРЫТЬ ..."
@router.callback_query(F.data.startswith("dispute:open_purchase:"))
async def admin_dispute_open_purchase(
    call: CallbackQuery, bot: Bot, arSession: ARS, i18n: Translator, locale: str
):
    purchase_receipt = call.data.split(":")[2]
    purchase = Purchasesx.get(purchase_receipt=purchase_receipt)
    if not purchase:
        return await call.answer(
            i18n.get_text("admin_disputes.purchase_not_found", locale), show_alert=True
        )
    await purchase_open_admin(bot, arSession, call.from_user.id, purchase, i18n, locale)
    await call.answer()


@router.callback_query(F.data.startswith("dispute:open_profile:"))
async def admin_dispute_open_profile(
    call: CallbackQuery, bot: Bot, i18n: Translator, locale: str
):
    user_id = int(call.data.split(":")[2])
    user = Userx.get(user_id=user_id)
    if not user:
        return await call.answer(
            i18n.get_text("admin_disputes.user_not_found", locale), show_alert=True
        )
    await open_profile_admin(bot, call.from_user.id, user, i18n, locale)
    await call.answer()
