import asyncio

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from tgbot.data.config import get_admins, get_operators

from tgbot.database import Invoicex, Purchasesx, Userx, InvoiceStatus
from tgbot.keyboards.inline_admin import mail_confirm_finl, profile_edit_return_finl, purchase_manage_finl
from tgbot.services.i18n import Translator
from tgbot.utils.const_functions import (
    clear_html,
    convert_date,
    ded,
    del_message,
    ikb,
    is_number,
    to_number,
    PurchaseSource,
    get_unix,
)
from tgbot.utils.misc.bot_logging import bot_logger
from tgbot.utils.misc.bot_models import ARS, FSM
from tgbot.utils.misc_functions import functions_mail_make, send_admins
from tgbot.utils.text_functions import (
    invoice_open_admin,
    open_profile_admin,
    purchase_open_admin,
    send_purchase_details,
)

from tgbot.utils.misc.i18n_filters import I18nText


router = Router(name=__name__)


# Поиск чеков и профилей
@router.message(F.text.in_(("🔍 Поиск", "/search", "🔍 Search")))
async def functions_find(message: Message, state: FSM, i18n: Translator, locale: str):
    await state.clear()
    await state.set_state("here_find")
    await message.answer(i18n.get_text("admin_functions.search_prompt", locale))


# Обработка смены статуса покупки админом
@router.callback_query(F.data.startswith("admin_rate_purchase:"))
async def admin_purchase_rate_handler(
    call: CallbackQuery, bot: Bot, arSession: ARS, i18n: Translator, locale: str
):
    try:
        receipt, rating_str = call.data.split(":")[1:]
        rating = int(rating_str)
    except (ValueError, IndexError):
        return await call.answer(
            i18n.get_text("admin_functions.data_error", locale), show_alert=True
        )

    Purchasesx.update(purchase_receipt=receipt, rating=rating)

    if rating == 1:
        status_text = i18n.get_text("buttons.success", locale)
    elif rating == -1:
        status_text = i18n.get_text("buttons.fail", locale)
    else:
        status_text = i18n.get_text("buttons.open", locale)

    await call.answer(
        i18n.get_text(
            "admin_functions.purchase_status_changed",
            locale,
            receipt=receipt,
            status_text=status_text,
        )
    )

    get_purchase = Purchasesx.get(purchase_receipt=receipt)
    if get_purchase:
        await call.message.delete()
        # Передаем i18n и locale в text_function
        await purchase_open_admin(
            bot, arSession, call.from_user.id, get_purchase, i18n, locale
        )


# Рассылка
@router.message(I18nText("reply_admin.mailing"))
#@router.message(F.text == "📢 Рассылка")
async def functions_mail(message: Message, state: FSM, i18n: Translator, locale: str):
    await state.clear()
    await state.set_state("here_mail_message")
    await message.answer(i18n.get_text("admin_functions.mail_prompt", locale))


################################################################################
################################### РАССЫЛКА ###################################
# Принятие текста для рассылки
@router.message(StateFilter("here_mail_message"))
async def functions_mail_get(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    await state.update_data(here_mail_message=message)
    await state.set_state("here_mail_confirm")

    get_users = Userx.get_all()
    active_users = [user for user in get_users if not user.bot_blocked_by_user]

    await message.reply(
        i18n.get_text(
            "admin_functions.mail_confirm_prompt",
            locale,
            active_users_count=len(active_users),
            total_users_count=len(get_users),
        ),
        reply_markup=mail_confirm_finl(i18n, locale),
    )


# Подтверждение отправки рассылки
@router.callback_query(
    F.data.startswith("mail_confirm:"), StateFilter("here_mail_confirm")
)
async def functions_mail_confirm(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    get_status = call.data.split(":")[1]
    send_message = (await state.get_data())["here_mail_message"]
    await state.clear()

    if get_status == "Yes":
        get_users = Userx.get_all()
        await call.message.edit_text(
            i18n.get_text(
                "admin_functions.mail_started", locale, user_count=len(get_users)
            )
        )
        await asyncio.create_task(
            functions_mail_make(bot, send_message, call, i18n, locale)
        )
    else:
        await call.message.edit_text(
            i18n.get_text("admin_functions.mail_cancelled", locale)
        )


################################################################################
##################################### ПОИСК ####################################
# Принятие айди/логина пользователя или чека для поиска
@router.message(F.text, StateFilter("here_find"))
@router.message(F.text.lower().startswith((".find", "find")))
async def functions_find_get(
    message: Message,
    bot: Bot,
    state: FSM,
    arSession: ARS,
    i18n: Translator,
    locale: str,
):
    find_data = message.text.lower()

    if ".find" in find_data or "find" in find_data:
        if len(find_data.split(" ")) >= 2:
            find_data = message.text.split(" ")[1]
        else:
            return await message.answer(
                i18n.get_text("admin_functions.search_no_query", locale)
            )

    if find_data.startswith(("@", "#")):
        find_data = find_data[1:]

    get_user = (
        Userx.get(user_id=find_data)
        if find_data.isdigit()
        else Userx.get(user_login=find_data.lower())
    )
    get_invoice = Invoicex.get(id=find_data)
    get_purchase = Purchasesx.get(purchase_receipt=find_data)

    if get_user is None and get_invoice is None and get_purchase is None:
        return await message.answer(
            i18n.get_text("admin_functions.search_not_found", locale)
        )

    await state.clear()

    # Передаем i18n и locale в text_functions
    if get_user is not None:
        return await open_profile_admin(
            bot, message.from_user.id, get_user, i18n, locale
        )
    if get_invoice is not None:
        return await invoice_open_admin(
            bot, message.from_user.id, get_invoice, i18n, locale
        )
    if get_purchase is not None:
        return await purchase_open_admin(
            bot, arSession, message.from_user.id, get_purchase, i18n, locale
        )


################################################################################
############################## УПРАВЛЕНИЕ ПРОФИЛЕМ #############################
# Обновление профиля пользователя
@router.callback_query(F.data.startswith("admin_user_refresh:"))
async def functions_user_refresh(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    user_id = int(call.data.split(":")[1])
    get_user = Userx.get(user_id=user_id)
    await state.clear()
    await del_message(call.message)
    await open_profile_admin(bot, call.from_user.id, get_user, i18n, locale)


# Покупки пользователя
@router.callback_query(F.data.startswith("admin_user_purchases:"))
async def functions_user_purchases( call: CallbackQuery, bot: Bot, state: FSM, arSession: ARS, i18n: Translator, locale: str,):
    user_id = int(call.data.split(":")[1])
    get_user = Userx.get(user_id=user_id)
    get_purchases = Purchasesx.gets(user_id=user_id)[-5:]

    if not get_purchases:
        return await call.answer(i18n.get_text("admin_functions.user_no_purchases", locale), True)

    await call.answer(i18n.get_text("admin_functions.user_last_5_purchases", locale))
    await del_message(call.message)

    for purchase in get_purchases:
        await send_purchase_details(bot=bot,
            chat_id=call.from_user.id,
            purchase=purchase,
            i18n=i18n,locale=locale,
            caption_template_key="admin_purchase.receipt_full",
            source=PurchaseSource.BOT,
            reply_markup=purchase_manage_finl(purchase.purchase_receipt, i18n, locale)
        )
        await asyncio.sleep(0.3)
        
    await open_profile_admin(bot, call.from_user.id, get_user, i18n, locale)

# Пополнения пользователя
@router.callback_query(F.data.startswith("admin_user_refills:"))
async def functions_user_refills(call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str):
    user_id = int(call.data.split(":")[1])
    get_user = Userx.get(user_id=user_id)
    get_refills = Invoicex.gets(user_id=user_id, status="finished")

    if not get_refills:
        return await call.answer(i18n.get_text("admin_functions.user_no_refills", locale), True)

    await call.message.answer(i18n.get_text("admin_functions.user_total_refills", locale, count=len(get_refills)))
    await del_message(call.message)

    for refill in get_refills[-10:]:
        created_date = i18n.get_text("admin_functions.refill_created_date",locale,date=convert_date(refill.created_at),)
        if refill.payed_at:
            payed_at_text = f"{created_date}\n{i18n.get_text('admin_functions.refill_paid_date', locale, date=convert_date(refill.payed_at))}"
        else:
            payed_at_text = f"{created_date}\n{i18n.get_text('admin_functions.refill_not_paid', locale)}"

        currency_text = (
            f"LTC: <code>{refill.amount_ltc}</code>"
            if refill.amount_ltc is not None
            else f"USDT: <code>{refill.amount_usdt}</code>"
        )
        
        txid_line = f"\nTXID: <code>{refill.txid}</code>" if refill.txid else ""

        await call.message.answer(
            ded(f"""
                {i18n.get_text("admin_functions.refill_invoice_id", locale, id=refill.id)}
                {i18n.get_text("admin_functions.refill_payment_method", locale, method=refill.currency)}
                {i18n.get_text("admin_functions.refill_amount", locale, amount=refill.amount_usd)}
                {currency_text}
                {payed_at_text}{txid_line}
                """)
        )
        await asyncio.sleep(0.2)
    await open_profile_admin(bot, call.from_user.id, get_user, i18n, locale)



# Выдача баланса пользователю
@router.callback_query(F.data.startswith("admin_user_balance_add:"))
async def functions_user_balance_add(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    user_id = int(call.data.split(":")[1])
    await state.update_data(here_user=user_id)
    await state.set_state("here_user_add")
    await call.message.edit_text(i18n.get_text("admin_functions.balance_give_prompt", locale),reply_markup=profile_edit_return_finl(user_id, i18n, locale),)


# Принятие суммы для выдачи баланса пользователю
@router.message(StateFilter("here_user_add"))
async def functions_user_balance_add_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str, arSession: ARS
):
    user_id = (await state.get_data())["here_user"]
    action_text = i18n.get_text("admin_functions.action_give_balance", locale)
    if not is_number(message.text):
        return await message.answer(i18n.get_text("admin_functions.balance_invalid_data", locale, action=action_text),reply_markup=profile_edit_return_finl(user_id, i18n, locale),)
    get_amount = to_number(message.text)
    if get_amount <= 0 or get_amount > 1_000:
        return await message.answer(i18n.get_text("admin_functions.balance_give_limit_error", locale),reply_markup=profile_edit_return_finl(user_id, i18n, locale),)

    await state.clear()
    get_user = Userx.get(user_id=user_id)
    new_balance = round(get_user.user_balance + get_amount, 2)
    Userx.update(user_id,user_balance=new_balance,user_give=round(get_user.user_give + get_amount, 2),)

    # Уведомляем агрегатор об изменении баланса
    from tgbot.utils.misc_functions import notify_aggregator_of_balance_update
    asyncio.create_task(notify_aggregator_of_balance_update( bot=bot, arSession=arSession, user_id=user_id, new_balance=new_balance ))

    try:
        await bot.send_message( user_id, i18n.get_text( "admin_functions.balance_give_notification", locale, amount=message.text ), )

        message_text = i18n.get_text("admin_functions.balance_give_admin_log", locale, admin_id=message.from_user.id, admin_username=message.from_user.username, user_id=get_user.user_id, user_name=get_user.user_name, before=get_user.user_balance, amount=message.text, after=new_balance, )
        for admin in get_admins():
            try:
                await bot.send_message(chat_id=admin, text=message_text, parse_mode=ParseMode.HTML)
            except Exception as e:
                bot_logger.error(f"Error when sending notification to administrator about balance issue {admin}: {e}")
        

    except Exception as e:
        bot_logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")

    



    await message.answer(
        i18n.get_text(
            "admin_functions.balance_give_success_reply",
            locale,
            user_id=get_user.user_id,
            user_name=get_user.user_name,
            amount=message.text,
            before=get_user.user_balance,
            after=new_balance,
        )
    )
    get_user = Userx.get(user_id=user_id)
    await open_profile_admin(bot, message.from_user.id, get_user, i18n, locale)

# Ручное подтверждение платежа
@router.callback_query(F.data.startswith("admin_confirm_invoice:"))
async def manual_invoice_confirm(call: CallbackQuery, bot: Bot, i18n: Translator, locale: str):
    invoice_id = int(call.data.split(":")[1])
    admin_user = call.from_user

    invoice = Invoicex.get(id=invoice_id)

    if not invoice or invoice.status not in [InvoiceStatus.PENDING, InvoiceStatus.REJECT]:
        await call.answer(i18n.get_text("admin_functions.invoice_already_processed", locale), show_alert=True)
        return

    # Формируем уникальный txid для отслеживания
    new_txid = f"{admin_user.id}invoice{invoice_id}"

    # Обновляем счет
    Invoicex.update(
        invoice_id=invoice_id,
        status=InvoiceStatus.SUCCSESS,
        txid=new_txid,
        payed_at=get_unix(),
    )

    # Получаем данные пользователя для логов и уведомлений
    invoice_user = Userx.get(user_id=invoice.user_id)

    # Логирование действия
    bot_logger.info(
        i18n.get_text(
            "log_messages.manual_confirm_log",
            "en", # Логи всегда на английском
            admin_id=admin_user.id,
            admin_username=admin_user.username or "N/A",
            invoice_id=invoice_id,
            user_id=invoice_user.user_id,
            user_login=invoice_user.user_login or "N/A",
            new_txid=new_txid
        )
    )

    # Уведомление другим администраторам и операторам
    admin_mention = f"<a href='tg://user?id={admin_user.id}'>{admin_user.full_name}</a>"
    user_mention = f"<a href='tg://user?id={invoice_user.user_id}'>{invoice_user.user_name}</a>"
    
    recipients = set(get_admins()) | set(get_operators())
    for recipient_id in recipients:
        if recipient_id != admin_user.id:
            try:
                recipient_user = Userx.get(user_id=recipient_id)
                recipient_locale = recipient_user.language_code if recipient_user and recipient_user.language_code else 'ru'
                
                notification_text = i18n.get_text(
                    "admin_functions.log_manual_invoice_confirm",
                    recipient_locale,
                    admin_mention=admin_mention,
                    invoice_id=invoice_id,
                    user_mention=user_mention
                )
                await bot.send_message(recipient_id, notification_text)
            except Exception as e:
                bot_logger.error(f"Failed to send manual confirmation notification to {recipient_id}: {e}")

    await call.answer(
        i18n.get_text(
            "admin_functions.invoice_confirmed_manually",
            locale,
            invoice_id=invoice_id,
        ),
        show_alert=True,
    )

    # Обновляем сообщение с информацией о счете
    updated_invoice = Invoicex.get(id=invoice_id)
    await call.message.delete()
    await invoice_open_admin(bot, call.from_user.id, updated_invoice, i18n, locale)

# Изменение баланса пользователю
@router.callback_query(F.data.startswith("admin_user_balance_set:"))
async def functions_user_balance_set(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    user_id = int(call.data.split(":")[1])
    await state.update_data(here_user=user_id)
    await state.set_state("here_user_set")
    await call.message.edit_text(
        i18n.get_text("admin_functions.balance_edit_prompt", locale),
        reply_markup=profile_edit_return_finl(user_id, i18n, locale),
    )


# Принятие суммы для изменения баланса пользователя
@router.message(StateFilter("here_user_set"))
async def functions_user_balance_set_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str, arSession: ARS
):
    user_id = (await state.get_data())["here_user"]
    action_text = i18n.get_text("admin_functions.action_edit_balance", locale)
    if not is_number(message.text):
        return await message.answer(
            i18n.get_text(
                "admin_functions.balance_invalid_data", locale, action=action_text
            ),
            reply_markup=profile_edit_return_finl(user_id, i18n, locale),
        )
    get_amount = to_number(message.text)
    if get_amount < -1_000 or get_amount > 1_000:
        return await message.answer(
            i18n.get_text("admin_functions.balance_edit_limit_error", locale),
            reply_markup=profile_edit_return_finl(user_id, i18n, locale),
        )

    await state.clear()
    get_user = Userx.get(user_id=user_id)
    user_give = (
        get_amount - get_user.user_give if get_amount > get_user.user_balance else 0
    )
    Userx.update(
        user_id,
        user_balance=get_amount,
        user_give=round(get_user.user_give + user_give, 2),
    )

    # Уведомляем агрегатор об изменении баланса
    from tgbot.utils.misc_functions import notify_aggregator_of_balance_update
    asyncio.create_task(notify_aggregator_of_balance_update(
        bot=bot,
        arSession=arSession,
        user_id=user_id,
        new_balance=get_amount
    ))

    await message.answer(
        i18n.get_text(
            "admin_functions.balance_edit_success_reply",
            locale,
            user_id=get_user.user_id,
            user_name=get_user.user_name,
            amount=message.text,
            before=get_user.user_balance,
            after=get_amount,
        )
    )
    message_text = i18n.get_text(
        "admin_functions.balance_edit_admin_log",
        locale,
        admin_id=message.from_user.id,
        admin_username=message.from_user.username,
        user_id=get_user.user_id,
        user_name=get_user.user_name,
        before=get_user.user_balance,
        amount=message.text,
        after=get_amount,
    )
    for admin in get_admins():
        try:
            await bot.send_message(
                chat_id=admin, text=message_text, parse_mode=ParseMode.HTML
            )
        except Exception as e:
            bot_logger.error(
                f"Ошибка при отправке уведомления администратору о изменении баланса {admin}: {e}"
            )

    get_user = Userx.get(user_id=user_id)
    await open_profile_admin(bot, message.from_user.id, get_user, i18n, locale)


# Отправка сообщения пользователю
@router.callback_query(F.data.startswith("admin_user_message:"))
async def functions_user_user_message(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    user_id = int(call.data.split(":")[1])
    await state.update_data(here_user_id=user_id)
    await state.set_state("here_user_message")
    await call.message.edit_text(
        i18n.get_text("admin_functions.send_message_prompt", locale),
        reply_markup=profile_edit_return_finl(user_id, i18n, locale),
    )


# Принятие сообщения для отправки пользователю
@router.message(StateFilter("here_user_message"))
async def functions_user_user_message_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    user_id = (await state.get_data())["here_user_id"]
    await state.clear()
    get_message = (
        i18n.get_text("admin_functions.admin_message_prefix", locale)
        + f"<code>{clear_html(message.text)}</code>"
    )
    get_user = Userx.get(user_id=user_id)

    try:
        await bot.send_message(user_id, get_message)
    except TelegramForbiddenError:
        try:
            await asyncio.to_thread(Userx.update, user_id, bot_blocked_by_user=1)
        except Exception as e:
            await message.reply(f"Error while updating user data in DB: {e}")
        else:
            await message.reply(
                i18n.get_text("admin_functions.user_blocked_bot", locale)
            )
    except Exception as e:
        bot_logger.error(f"Ошибка при отправке сообщения: {e}")
        await message.reply(i18n.get_text("admin_functions.send_message_fail", locale))
    else:
        await message.reply(
            i18n.get_text("admin_functions.send_message_success", locale)
        )

    await open_profile_admin(bot, message.from_user.id, get_user, i18n, locale)


# Блокировка пользователя
@router.callback_query(F.data.startswith("admin_user_block:"))
async def admin_user_block(
    call: CallbackQuery, bot: Bot, i18n: Translator, locale: str
):
    user_id = int(call.data.split(":")[1])
    get_user = Userx.get(user_id=user_id)

    if get_user.user_blocked == 0:
        if user_id in get_admins():
            log_text = i18n.get_text(
                "admin_functions.log_admin_tried_block_admin",
                locale,
                admin_id=call.from_user.id,
                admin_username=call.from_user.username,
                admin_firstname=call.from_user.first_name,
                target_id=get_user.user_id,
                target_login=get_user.user_login,
                target_name=get_user.user_name,
            )
            bot_logger.warning(log_text)
            await send_admins(bot=bot, text=ded(log_text), not_me=call.from_user.id)
            return await call.answer(
                i18n.get_text("admin_functions.cannot_block_admin", locale), True
            )

        keyboard = InlineKeyboardBuilder()
        keyboard.row(
            ikb(
                i18n.get_text("admin_functions.block_button", locale),
                data=f"admin_user_block_confirm:{user_id}:1",
            )
        )
        await call.message.edit_text(
            i18n.get_text(
                "admin_functions.block_user_prompt",
                locale,
                user_name=get_user.user_name,
                user_login=get_user.user_login,
                user_id=get_user.user_id,
            ),
            reply_markup=keyboard.as_markup(),
        )
    else:
        keyboard = InlineKeyboardBuilder()
        keyboard.row(
            ikb(
                i18n.get_text("admin_functions.unblock_button", locale),
                data=f"admin_user_block_confirm:{user_id}:0",
            )
        )
        await call.message.edit_text(
            i18n.get_text(
                "admin_functions.unblock_user_prompt",
                locale,
                user_name=get_user.user_name,
                user_login=get_user.user_login,
                user_id=get_user.user_id,
            ),
            reply_markup=keyboard.as_markup(),
        )


# Подтверждение блокировки пользователя
@router.callback_query(F.data.startswith("admin_user_block_confirm:"))
async def admin_user_block_confirm(
    call: CallbackQuery, bot: Bot, i18n: Translator, locale: str
):
    user_id = int(call.data.split(":")[1])
    block_status = int(call.data.split(":")[2])
    get_user = Userx.get(user_id=user_id)
    Userx.update(user_id=user_id, user_blocked=block_status)

    if block_status == 1:
        log_text = i18n.get_text(
            "admin_functions.log_admin_blocked_user",
            locale,
            admin_username=call.from_user.username,
            target_id=get_user.user_id,
            target_login=get_user.user_login,
            target_name=get_user.user_name,
        )
    else:
        log_text = i18n.get_text(
            "admin_functions.log_admin_unblocked_user",
            locale,
            admin_username=call.from_user.username,
            target_id=get_user.user_id,
            target_login=get_user.user_login,
            target_name=get_user.user_name,
        )

    bot_logger.warning(log_text)
    await call.message.edit_text(log_text)
    await send_admins(bot=bot, text=ded(log_text), not_me=call.from_user.id)
