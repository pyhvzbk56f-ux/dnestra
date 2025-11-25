# shop/tgbot/routers/user/user_disputes.py

import asyncio
from aiogram import Router, Bot, F

from tgbot.utils.misc.bot_models import FSM
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from tgbot.database import Purchasesx, Settingsx, Disputex
from tgbot.services.i18n import Translator
from tgbot.utils.const_functions import convert_date, get_unix, send_admins, bot_logger

router = Router(name=__name__)

# Используем словарь для временного хранения медиагрупп
media_group_cache = {}


# FSM ДЛЯ СОЗДАНИЯ ЖАЛОБ
class DisputeSubmission(StatesGroup):
    waiting_for_media = State()
    waiting_for_comment = State()


# FSM ДЛЯ ОБНОВЛЕНИЯ ЖАЛОБ
class UpdateDispute(StatesGroup):
    waiting_for_media = State()


# ФУНКЦИЯ ДЛЯ ЗАВЕРШЕНИЯ ОБНОВЛЕНИЯ
async def _finalize_dispute_update(
    state: FSM,
    bot: Bot,
    user_id: int,
    i18n: Translator,
    locale: str,
    complaint_text: str = None,
    new_media_ids: list = [],
):
    data = await state.get_data()
    await state.clear()
    dispute_id = data.get("dispute_id_to_update")
    if not dispute_id:
        return await bot.send_message(
            user_id, i18n.get_text("user_disputes.error_not_found", locale)
        )

    existing_dispute = Disputex.get(dispute_id=dispute_id)
    if not existing_dispute:
        return await bot.send_message(
            user_id, i18n.get_text("user_disputes.error_not_found", locale)
        )

    update_data = {}
    if new_media_ids:
        new_media_ids_str = ",".join(map(str, new_media_ids))
        if existing_dispute.media_message_ids:
            update_data["media_message_ids"] = (
                f"{existing_dispute.media_message_ids},{new_media_ids_str}"
            )
        else:
            update_data["media_message_ids"] = new_media_ids_str

    if complaint_text:
        new_comment_block = i18n.get_text(
            "user_disputes.comment_block",
            locale,
            date=convert_date(get_unix()),
            text=complaint_text,
        )
        if existing_dispute.complaint_text:
            update_data["complaint_text"] = (
                f"{existing_dispute.complaint_text}\n\n{new_comment_block}"
            )
        else:
            update_data["complaint_text"] = new_comment_block

    if not update_data:
        return await bot.send_message(
            user_id, i18n.get_text("user_disputes.update_nothing_added", locale)
        )

    Disputex.update(dispute_id=dispute_id, **update_data)
    await bot.send_message(
        user_id, i18n.get_text("user_disputes.update_data_added", locale)
    )


async def _finalize_dispute(
    state: FSM,
    bot: Bot,
    user_id: int,
    username: str,
    i18n: Translator,
    locale: str,
    complaint_text: str = None,
):
    """Функция создает новые жалобы."""
    data = await state.get_data()
    media_ids_str = ",".join(map(str, data.get("media_message_ids", [])))
    final_comment = None
    if complaint_text:
        final_comment = i18n.get_text(
            "user_disputes.comment_block",
            locale,
            date=convert_date(get_unix()),
            text=complaint_text,
        )

    Disputex.add(
        purchase_receipt=data["purchase_receipt"],
        user_id=user_id,
        complaint_text=final_comment,
        media_message_ids=media_ids_str,
        media_chat_id=data.get("media_chat_id"),
    )
    Purchasesx.update(
        purchase_receipt=data["purchase_receipt"], has_dispute=True, rating=-1
    )

    await state.clear()
    await bot.send_message(
        user_id, i18n.get_text("user_disputes.create_success", locale)
    )

    purchase = Purchasesx.get(purchase_receipt=data["purchase_receipt"])
    admin_text = (
        f"{i18n.get_text('user_disputes.admin_notification_title', 'ru')}\n"  # Уведомление админам всегда на русском
        f"{i18n.get_text('user_disputes.admin_notification_body', 'ru', receipt=purchase.purchase_receipt, username=username, user_id=user_id, item_name=purchase.purchase_position_name)}"
    )
    await send_admins(bot, admin_text, not_me=0)


# ОБРАБОТЧИК МЕДИА Ловим все фото и видео в состоянии waiting_for_media
@router.message(DisputeSubmission.waiting_for_media, F.photo | F.video)
@router.message(UpdateDispute.waiting_for_media, F.photo | F.video)
async def process_dispute_media(
    message: Message, state: FSM, bot: Bot, i18n: Translator, locale: str
):
    current_state = await state.get_state()
    settings = Settingsx.get()
    dispute_channel_id = settings.dispute_channel_id

    if not dispute_channel_id or dispute_channel_id == "None":
        await message.answer(i18n.get_text("user_disputes.error_no_channel", locale))
        await state.clear()
        return

    user_id = message.from_user.id
    if user_id not in media_group_cache:
        media_group_cache[user_id] = {"messages": [], "timer": None, "caption": None}

    media_group_cache[user_id]["messages"].append(message)
    if message.caption:
        media_group_cache[user_id]["caption"] = message.caption
    if media_group_cache[user_id]["timer"]:
        media_group_cache[user_id]["timer"].cancel()

    timer = asyncio.create_task(asyncio.sleep(2), name=f"media_group_timer_{user_id}")
    media_group_cache[user_id]["timer"] = timer

    try:
        await timer
        user_cache = media_group_cache.pop(user_id, None)
        if not user_cache:
            return

        messages_to_forward, caption, forwarded_ids = (
            user_cache["messages"],
            user_cache["caption"],
            [],
        )

        for msg in messages_to_forward:
            try:
                forwarded = await bot.forward_message(
                    chat_id=int(dispute_channel_id),
                    from_chat_id=msg.chat.id,
                    message_id=msg.message_id,
                )
                forwarded_ids.append(forwarded.message_id)
            except Exception as e:
                bot_logger.error(
                    i18n.get_text("user_disputes.error_media_forward", "en", error=e)
                )
                await message.answer(
                    i18n.get_text("user_disputes.error_media_save", locale)
                )
                return

        if current_state == UpdateDispute.waiting_for_media:
            await state.update_data(media_message_ids=forwarded_ids)
            await _finalize_dispute_update(
                state,
                bot,
                user_id,
                i18n,
                locale,
                complaint_text=caption,
                new_media_ids=forwarded_ids,
            )
        else:  # DisputeSubmission.waiting_for_media
            await state.update_data(
                media_message_ids=forwarded_ids, media_chat_id=int(dispute_channel_id)
            )
            if caption:
                await message.answer(
                    i18n.get_text("user_disputes.media_and_comment_added", locale)
                )
                await _finalize_dispute(
                    state,
                    bot,
                    user_id,
                    message.from_user.username,
                    i18n,
                    locale,
                    complaint_text=caption,
                )
            else:
                await state.set_state(DisputeSubmission.waiting_for_comment)
                await message.answer(
                    i18n.get_text("user_disputes.media_added_prompt_comment", locale)
                )
    except asyncio.CancelledError:
        pass


# Обработчик для текстового комментария в состоянии обновления
@router.message(UpdateDispute.waiting_for_media, F.text)
async def process_dispute_update_text(
    message: Message, state: FSM, bot: Bot, i18n: Translator, locale: str
):
    await _finalize_dispute_update(
        state, bot, message.from_user.id, i18n, locale, complaint_text=message.text
    )


# Обработчик для текстового комментария
@router.message(DisputeSubmission.waiting_for_comment, F.text)
async def process_dispute_comment(
    message: Message, state: FSM, bot: Bot, i18n: Translator, locale: str
):
    await message.answer(i18n.get_text("user_disputes.comment_accepted", locale))
    await _finalize_dispute(
        state,
        bot,
        message.from_user.id,
        message.from_user.username,
        i18n,
        locale,
        complaint_text=message.text,
    )
