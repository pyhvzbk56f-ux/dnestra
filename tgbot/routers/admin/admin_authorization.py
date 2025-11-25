# shop/tgbot/routers/admin/admin_authorization.py
from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from tgbot.database import Userx
from tgbot.services.i18n import Translator
from tgbot.utils.const_functions import del_message
from tgbot.utils.misc.bot_logging import bot_logger
from tgbot.utils.misc.bot_models import FSM
from tgbot.utils.misc.i18n_filters import I18nText


router = Router(name=__name__)


class AuthStates(StatesGroup):
    waiting_for_user_to_authorize = State()
    waiting_for_user_to_block = State()


# Меню авторизации
@router.message(I18nText("reply_admin.authorization"))
async def authorization_menu(message: Message, i18n: Translator, locale: str):
    builder = InlineKeyboardBuilder()
    builder.button(
        text=i18n.get_text("admin_authorization.authorize_button", locale),
        callback_data="auth:authorize",
    )
    builder.button(
        text=i18n.get_text("admin_authorization.block_button", locale),
        callback_data="auth:block",
    )
    await message.answer(
        i18n.get_text("admin_authorization.menu_title", locale),
        reply_markup=builder.as_markup(),
    )


# Запрос пользователя для авторизации
@router.callback_query(F.data == "auth:authorize")
async def request_user_for_auth(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    await state.set_state(AuthStates.waiting_for_user_to_authorize)
    await call.message.edit_text(
        i18n.get_text("admin_authorization.prompt_user", locale)
    )
    await call.answer()


# Запрос пользователя для блокировки
@router.callback_query(F.data == "auth:block")
async def request_user_for_block(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    await state.set_state(AuthStates.waiting_for_user_to_block)
    await call.message.edit_text(
        i18n.get_text("admin_authorization.prompt_user", locale)
    )
    await call.answer()


# Обработка ввода для авторизации
@router.message(StateFilter(AuthStates.waiting_for_user_to_authorize))
async def process_user_for_auth(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    find_data = message.text.strip().replace("@", "")
    target_user = (
        Userx.get(user_id=find_data)
        if find_data.isdigit()
        else Userx.get(user_login=find_data.lower())
    )

    if not target_user:
        await message.answer(
            i18n.get_text("admin_authorization.user_not_found", locale)
        )
        return

    Userx.update(user_id=target_user.user_id, is_authorized=True)
    await state.clear()

    user_mention = f"<a href='tg://user?id={target_user.user_id}'>{target_user.user_name}</a>"
    await message.answer(
        i18n.get_text(
            "admin_authorization.user_authorized", locale, user_mention=user_mention
        )
    )

    bot_logger.warning(f"admin\operator ID {message.from_user.id} authorize user ID: {target_user.user_id} login: @{target_user.user_login}") 

    try:
        user_locale = target_user.language_code or "ru"
        await bot.send_message(
            target_user.user_id,
            i18n.get_text("user_notifications.authorized", user_locale),
        )
    except Exception as e:
        bot_logger.warning(
            f"Could not notify user {target_user.user_id} about authorization: {e}"
        )


# Обработка ввода для блокировки
@router.message(StateFilter(AuthStates.waiting_for_user_to_block))
async def process_user_for_block(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    find_data = message.text.strip().replace("@", "")
    target_user = (
        Userx.get(user_id=find_data)
        if find_data.isdigit()
        else Userx.get(user_login=find_data.lower())
    )

    if not target_user:
        await message.answer(
            i18n.get_text("admin_authorization.user_not_found", locale)
        )
        return

    Userx.update(user_id=target_user.user_id, user_blocked=1)
    await state.clear()

    user_mention = f"<a href='tg://user?id={target_user.user_id}'>{target_user.user_name}</a>"
    await message.answer(
        i18n.get_text(
            "admin_authorization.user_blocked", locale, user_mention=user_mention
        )
    )
    bot_logger.warning(f"admin\operator ID {message.from_user.id} blocked user ID: {target_user.user_id} login: @{target_user.user_login}") 


    try:
        user_locale = target_user.language_code or "ru"
        await bot.send_message(
            target_user.user_id,
            i18n.get_text("user_notifications.blocked", user_locale),
        )
    except Exception as e:
        bot_logger.warning(
            f"Could not notify user {target_user.user_id} about blocking: {e}"
        )