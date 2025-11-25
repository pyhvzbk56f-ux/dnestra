# shop/tgbot/routers/admin/admin_menu.py
import os
import aiohttp
import asyncio
import aiofiles
import re

from typing import Union
from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.utils.media_group import MediaGroupBuilder
from tgbot.data.config import PATH_DATABASE, PATH_LOGS

from tgbot.database import (
    Exchangersx,
    Settingsx,
    Categoryx,
    Subcategoryx,
    Positionx,
    Itemx,
)
from tgbot.keyboards.reply_main import (
    functions_frep,
    items_frep,
    # payments_frep,
    settings_frep,
)
from tgbot.services.i18n import Translator
from tgbot.utils.misc.i18n_filters import I18nText
from tgbot.utils.const_functions import get_date, get_unix, rkb
from tgbot.utils.misc.bot_models import ARS, FSM
from tgbot.utils.misc_functions import (
get_statistics,
get_items_available_admin,
archive_old_purchase_files,
update_invoice_status,
update_balance,
update_actual_ltc_rate_in_db,
update_profit_day,
)
from tgbot.utils.misc.bot_filters import IsAdmin, IsAdminOrOperator


router = Router(name=__name__)



#! Настройки бота
@router.message(I18nText("reply_admin.settings"))
@router.callback_query(F.data == "admin_settings")
async def admin_settings(message: Union[Message, CallbackQuery], bot: Bot, state: FSM, i18n: Translator, locale: str):
    await state.clear()

    # Определяем, Message это или CallbackQuery
    target_message = message if isinstance(message, Message) else message.message
    user_id = target_message.from_user.id


    await target_message.answer(
        i18n.get_text("admin_menu_main.settings_title", locale),
        reply_markup=settings_frep(user_id, i18n, locale),
    )

# Общие функции
# @router.message(F.text == "🔆 Общие функции")
# async def admin_functions(message: Message, bot: Bot, state: FSM, arSession: ARS):
    # await state.clear()
    # await message.answer("<b>🔆 Общие функции бота</b>",reply_markup=functions_frep(),)





# Витрина
@router.message(F.text.in_(("🛍️ Витрина", "/showcase", "🛍️ Showcase")), IsAdminOrOperator())
async def admin_showcase(
    message: Message,
    bot: Bot,
    state: FSM,
    arSession: ARS,
    i18n: Translator,
    locale: str,
):
    messages = get_items_available_admin(i18n, locale)
    for msg in messages:
        await message.answer(msg, parse_mode="HTML")
        await asyncio.sleep(0.5)


# Статистика бота #admin_menu
@router.message(I18nText("reply_admin.statistics"), IsAdmin())
async def admin_statistics(message: Message, i18n: Translator, locale: str):
    statistics_text = get_statistics(i18n, locale)
    for text_part in statistics_text:
        try:
            if len(text_part) > 4096:
                for x in range(0, len(text_part), 4096):
                    await message.answer(text_part[x : x + 4096])
            else:
                await message.answer(text_part)
        except Exception as e:
            await message.answer(i18n.get_text("admin_menu_main.statistics_error", locale, error=e))


# Получение БД
@router.message(Command(commands=["db", "database"]), IsAdmin())
async def admin_database(message: Message, i18n: Translator, locale: str):
    await message.answer_document(
        FSInputFile(PATH_DATABASE),
        caption=i18n.get_text("misc_functions.db_backup_caption", locale, date=get_date()),)


# Получение Логов
@router.message(Command(commands=["log", "logs"]), IsAdmin())
async def admin_log(message: Message, i18n: Translator, locale: str):
    media_group = MediaGroupBuilder(
        caption=i18n.get_text("admin_menu_main.logs_caption", locale, date=get_date())
    )
    log_files = [PATH_LOGS] + [f"{PATH_LOGS}.{i}" for i in range(1, 5)]
    for log_file in log_files:
        if os.path.exists(log_file):
            media_group.add_document(media=FSInputFile(log_file))
    if media_group:
        await message.answer_media_group(media=media_group.build())


# Очистка логов
@router.message(Command(commands=["clear_log", "clear_logs", "log_clear", "logs_clear"]), IsAdmin())
async def admin_log_clear(message: Message, i18n: Translator, locale: str):
    if os.path.isfile(PATH_LOGS):
        async with aiofiles.open(PATH_LOGS, "w") as file:
            await file.write(f"{get_date()} | LOGS WAS CLEAR")
    await message.answer(i18n.get_text("admin_menu_main.logs_cleared", locale))


##############################
# Управление обменниками


# Классы состояний для обменников
class ExchangerStates(StatesGroup):
    ADD_USERNAME = State()
    ADD_TITLE = State()
    ADD_PRIORITY = State()
    ADD_VISIBILITY = State()
    ADD_URL = State()
    DELETE_EXCHANGER = State()
    CONFIRM_DELETE = State()
    SELECT_EXCHANGER = State()
    SELECT_EDIT_ACTION = State()
    EDIT_FIELD = State()


# Кнопки управления обменниками
@router.message(I18nText("reply_admin.exchangers"), IsAdmin())
async def manage_exchangers(message: Message, i18n: Translator, locale: str):
    keyboard = ReplyKeyboardBuilder()
    keyboard.row(
        rkb(i18n.get_text("reply_admin.add_exchanger", locale)),
        rkb(i18n.get_text("reply_admin.edit_exchanger", locale)),
        rkb(i18n.get_text("reply_admin.delete_exchanger", locale)),
    ).row(
        rkb(i18n.get_text("reply_admin.list_exchangers", locale)),
        rkb(i18n.get_text("buttons.main_menu", locale)),
    )
    await message.answer(
        i18n.get_text("admin_exchangers.choose_action", locale),
        reply_markup=keyboard.as_markup(resize_keyboard=True),)


# Добавление обменника
@router.message(I18nText("reply_admin.add_exchanger"), IsAdmin())
async def add_exchanger_start(
    message: Message, state: FSMContext, i18n: Translator, locale: str
):
    await state.set_state(ExchangerStates.ADD_USERNAME)
    await message.answer(i18n.get_text("admin_exchangers.enter_username", locale))


############################
# Обработка добавления обменника
@router.message(ExchangerStates.ADD_USERNAME)
async def process_add_exchanger_username(
    message: Message, state: FSMContext, i18n: Translator, locale: str
):
    username = message.text.strip()

    if not username.startswith("@"):
        return await message.answer(
            i18n.get_text("admin_exchangers.error_username_at", locale)
        )
    if len(username) <= 5:
        return await message.answer(
            i18n.get_text("admin_exchangers.error_username_min_len", locale)
        )
    if len(username) >= 32:
        return await message.answer(
            i18n.get_text("admin_exchangers.error_username_max_len", locale)
        )
    if not re.match("^[a-zA-Z0-9_]+$", username[1:]):
        return await message.answer(
            i18n.get_text("admin_exchangers.error_username_chars", locale)
        )

    await state.update_data(username=username[1:])
    await state.set_state(ExchangerStates.ADD_TITLE)
    await message.answer(i18n.get_text("admin_exchangers.enter_title", locale))


@router.message(ExchangerStates.ADD_TITLE)
async def process_add_exchanger_title(
    message: Message, state: FSMContext, i18n: Translator, locale: str
):
    title = message.text.strip()
    state_data = await state.get_data()
    if not title or title == "0":
        title = f"@{state_data['username']}"
    if len(title) > 40:
        return await message.answer(
            i18n.get_text("admin_exchangers.error_title_max_len", locale)
        )

    await state.update_data(title=title)
    await state.set_state(ExchangerStates.ADD_PRIORITY)
    await message.answer(i18n.get_text("admin_exchangers.enter_priority", locale))


@router.message(ExchangerStates.ADD_PRIORITY)
async def process_add_exchanger_priority(
    message: Message, state: FSMContext, i18n: Translator, locale: str
):
    priority = message.text.strip()
    try:
        priority_num = int(priority)
        if not 1 <= priority_num <= 99:
            return await message.answer(
                i18n.get_text("admin_exchangers.error_priority_range", locale)
            )
    except ValueError:
        return await message.answer(
            i18n.get_text("admin_exchangers.error_invalid_number", locale)
        )

    await state.update_data(order=priority_num)
    await state.set_state(ExchangerStates.ADD_VISIBILITY)

    keyboard = InlineKeyboardBuilder()
    keyboard.button(
        text=i18n.get_text("buttons.yes", locale), callback_data="visibility_yes"
    )
    keyboard.button(
        text=i18n.get_text("buttons.no", locale), callback_data="visibility_no"
    )
    await message.answer(
        i18n.get_text("admin_exchangers.select_visibility", locale),
        reply_markup=keyboard.as_markup(),
    )


# Обработчик inline кнопок видимости
@router.callback_query(F.data.startswith("visibility_"))
async def process_add_exchanger_visibility(
    callback: CallbackQuery, state: FSMContext, i18n: Translator, locale: str
):
    status = callback.data.split("_")[1]
    await state.update_data(status=status)
    status_text = (
        i18n.get_text("admin_exchangers.status_on", locale)
        if status == "yes"
        else i18n.get_text("admin_exchangers.status_off", locale)
    )
    await callback.message.edit_text(
        i18n.get_text(
            "admin_exchangers.visibility_selected", locale, status=status_text
        )
    )

    keyboard = InlineKeyboardBuilder()
    keyboard.button(
        text=i18n.get_text("admin_exchangers.add_custom_link", locale),
        callback_data="url_choice_custom",
    )
    keyboard.button(
        text=i18n.get_text("admin_exchangers.use_default_link", locale),
        callback_data="url_choice_default",
    )
    await callback.message.answer(
        i18n.get_text("admin_exchangers.select_link_type", locale),
        reply_markup=keyboard.as_markup(),
    )
    await state.set_state(ExchangerStates.ADD_URL)


@router.callback_query(F.data.startswith("url_choice_"))
async def process_url_choice(
    callback: CallbackQuery, state: FSMContext, i18n: Translator, locale: str
):
    choice = callback.data.split("_")[2]
    if choice == "custom":
        await callback.message.edit_text(
            i18n.get_text("admin_exchangers.enter_custom_link", locale)
        )
    else:
        data = await state.get_data()
        default_url = f"+https://t.me/{data['username']}"
        try:
            Exchangersx.add(
                exchanger_id=get_unix(),
                user_id=callback.from_user.id,
                exchanger_name=data["username"],
                exchanger_data=data["title"],
                exchanger_order=data["order"],
                exchanger_enabled=(data["status"] == "yes"),
                exchanger_unix=get_unix(),
                exchanger_custom_url=default_url,
            )
            await callback.message.edit_text(
                i18n.get_text(
                    "admin_exchangers.add_success_default_link", locale, url=default_url
                )
            )
        except Exception as e:
            await callback.message.edit_text(
                i18n.get_text("admin_exchangers.add_error", locale, error=e)
            )
        await state.clear()


@router.message(ExchangerStates.ADD_URL)
async def process_add_exchanger_url(
    message: Message, state: FSMContext, i18n: Translator, locale: str
):
    custom_url = message.text.strip()
    if custom_url == "0":
        custom_url = None
    elif not custom_url.startswith(("http://", "https://", "tg://")):
        return await message.answer(
            i18n.get_text("admin_exchangers.error_link_format", locale)
        )

    data = await state.get_data()
    try:
        Exchangersx.add(
            exchanger_id=get_unix(),
            user_id=message.from_user.id,
            exchanger_name=data["username"],
            exchanger_data=data["title"],
            exchanger_order=data["order"],
            exchanger_enabled=(data["status"] == "yes"),
            exchanger_unix=get_unix(),
            exchanger_custom_url=custom_url,
        )
        success_message = i18n.get_text("admin_exchangers.add_success", locale)
        if custom_url:
            success_message += i18n.get_text(
                "admin_exchangers.add_success_custom_link", locale, url=custom_url
            )
        await message.answer(success_message)
    except Exception as e:
        await message.answer(
            i18n.get_text("admin_exchangers.add_error", locale, error=e)
        )
    await state.clear()


@router.message(I18nText("reply_admin.list_exchangers"))
async def list_exchangers(message: Message, i18n: Translator, locale: str):
    exchangers = Exchangersx.get_all()
    if not exchangers:
        return await message.answer(
            i18n.get_text("admin_exchangers.list_empty", locale)
        )

    sorted_exchangers = sorted(
        exchangers, key=lambda x: (x.exchanger_order, x.exchanger_id)
    )
    text = i18n.get_text("admin_exchangers.list_title", locale)
    for index, ex in enumerate(sorted_exchangers, 1):
        priority_note = ""
        same_priority = [
            x for x in sorted_exchangers if x.exchanger_order == ex.exchanger_order
        ]
        if len(same_priority) > 1:
            priority_note = i18n.get_text(
                "admin_exchangers.list_item_priority_note",
                locale,
                count=len(same_priority),
                priority=ex.exchanger_order,
            )

        text += (
            f"{index}. @{ex.exchanger_name} {priority_note}\n"
            f"{i18n.get_text('admin_exchangers.list_item_header_title', locale)}: {ex.exchanger_data}\n"
            f"{i18n.get_text('admin_exchangers.list_item_header_priority', locale)}: {ex.exchanger_order}\n"
            f"{i18n.get_text('admin_exchangers.list_item_header_status', locale)}: {i18n.get_text('admin_exchangers.status_on', locale) if ex.exchanger_enabled else i18n.get_text('admin_exchangers.status_off', locale)}\n"
            f"{i18n.get_text('admin_exchangers.list_item_header_currency_support', locale)}: LTC {'✅' if ex.is_ltc else '❌'} | USDT TRC20 {'✅' if ex.is_usdt_trc20 else '❌'}\n"
            f"{i18n.get_text('admin_exchangers.list_item_header_id', locale)}: <code>{ex.exchanger_id}</code>\n"
            f"{i18n.get_text('admin_exchangers.list_item_header_link', locale)}: {ex.exchanger_custom_url or i18n.get_text('admin_exchangers.not_specified', locale)}\n"
        )
    await message.answer(text, parse_mode="HTML")


############################
# Удаление обменника
@router.message(I18nText("reply_admin.delete_exchanger"), IsAdmin())
async def delete_exchanger_start(
    message: Message, state: FSMContext, i18n: Translator, locale: str
):
    exchangers = Exchangersx.get_all()
    if not exchangers:
        return await message.answer(i18n.get_text("admin_exchangers.list_empty", locale))

    keyboard = InlineKeyboardBuilder()
    for ex in exchangers:
        keyboard.button(
            text=f"@{ex.exchanger_name}", callback_data=f"del_ex_{ex.exchanger_id}"
        )
    keyboard.adjust(2)
    await message.answer(
        i18n.get_text("admin_exchangers.select_to_delete", locale),
        reply_markup=keyboard.as_markup(),
    )
    await state.set_state(ExchangerStates.DELETE_EXCHANGER)


############################
# Подтверждение удаления
@router.callback_query(
    F.data.startswith("del_ex_"), StateFilter(ExchangerStates.DELETE_EXCHANGER)
)
async def confirm_delete_exchanger(
    callback: CallbackQuery, state: FSMContext, i18n: Translator, locale: str
):
    exchanger_id = callback.data.split("_")[2]
    await state.update_data(exchanger_id=exchanger_id)
    keyboard = InlineKeyboardBuilder()
    keyboard.button(
        text=i18n.get_text("buttons.yes", locale), callback_data="confirm_del_ex"
    )
    keyboard.button(
        text=i18n.get_text("buttons.no", locale), callback_data="cancel_del_ex"
    )
    await callback.message.edit_text(
        i18n.get_text("admin_exchangers.confirm_delete_prompt", locale),
        reply_markup=keyboard.as_markup(),
    )
    await state.set_state(ExchangerStates.CONFIRM_DELETE)


############################
# Обработка подтверждения удаления
@router.callback_query(
    F.data.in_({"confirm_del_ex", "cancel_del_ex"}),
    StateFilter(ExchangerStates.CONFIRM_DELETE),
)
async def process_delete_exchanger(
    callback: CallbackQuery, state: FSMContext, i18n: Translator, locale: str
):
    if callback.data == "confirm_del_ex":
        data = await state.get_data()
        Exchangersx.delete(exchanger_id=data["exchanger_id"])
        await callback.message.edit_text(
            i18n.get_text("admin_exchangers.delete_success", locale)
        )
    else:
        await callback.message.edit_text(
            i18n.get_text("admin_exchangers.delete_cancelled", locale)
        )
    await state.clear()


####################################################################
# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ОТОБРАЖЕНИЯ МЕНЮ
async def _display_exchanger_edit_menu(
    message: Message,
    exchanger_id: int,
    state: FSMContext,
    i18n: Translator,
    locale: str,
):
    exchanger = Exchangersx.get(exchanger_id=exchanger_id)
    if not exchanger:
        return await message.edit_text(
            i18n.get_text("admin_exchangers.not_found", locale)
        )

    await state.update_data(exchanger_id=exchanger_id)
    keyboard = InlineKeyboardBuilder()
    keyboard.button(
        text=i18n.get_text("admin_exchangers.edit_change_name", locale),
        callback_data=f"edit_name_{exchanger_id}",
    )
    keyboard.button(
        text=i18n.get_text("admin_exchangers.edit_change_priority", locale),
        callback_data=f"edit_priority_{exchanger_id}",
    )
    keyboard.button(
        text=i18n.get_text("admin_exchangers.edit_change_link", locale),
        callback_data=f"edit_url_{exchanger_id}",
    )
    toggle_text = (
        i18n.get_text("admin_exchangers.edit_disable", locale)
        if exchanger.exchanger_enabled
        else i18n.get_text("admin_exchangers.edit_enable", locale)
    )
    keyboard.button(text=toggle_text, callback_data=f"toggle_ex_{exchanger_id}")
    keyboard.button(
        text=f"LTC: {'✅' if exchanger.is_ltc else '❌'}",
        callback_data=f"toggle_currency:ltc:{exchanger_id}",
    )
    keyboard.button(
        text=f"USDT: {'✅' if exchanger.is_usdt_trc20 else '❌'}",
        callback_data=f"toggle_currency:usdt:{exchanger_id}",
    )
    keyboard.button(
        text=i18n.get_text("reply_admin.back", locale), callback_data="back_to_ex_list"
    )
    keyboard.adjust(1, 1, 1, 1, 2, 1)

    text = (
        i18n.get_text("admin_exchangers.edit_menu_title", locale)
        + "\n"
        + i18n.get_text(
            "admin_exchangers.edit_menu_body",
            locale,
            username=exchanger.exchanger_name,
            title=exchanger.exchanger_data,
            priority=exchanger.exchanger_order,
            url=exchanger.exchanger_custom_url
            or i18n.get_text("admin_exchangers.not_specified", locale),
            status=i18n.get_text("admin_exchangers.status_on", locale)
            if exchanger.exchanger_enabled
            else i18n.get_text("admin_exchangers.status_off", locale),
            ltc_status="✅" if exchanger.is_ltc else "❌",
            usdt_status="✅" if exchanger.is_usdt_trc20 else "❌",
        )
    )
    try:
        await message.edit_text(text, reply_markup=keyboard.as_markup())
    except Exception:
        await message.answer(text, reply_markup=keyboard.as_markup())
    await state.set_state(ExchangerStates.SELECT_EDIT_ACTION)


###########################################################################


############################
# Редактирование обменника
@router.message(I18nText("reply_admin.edit_exchanger"))
async def edit_exchanger_start(
    message: Message, state: FSMContext, i18n: Translator, locale: str
):
    exchangers = Exchangersx.get_all()
    if not exchangers:
        return await message.answer(
            i18n.get_text("admin_exchangers.list_empty", locale)
        )

    keyboard = InlineKeyboardBuilder()
    for ex in exchangers:
        status = "✅" if ex.exchanger_enabled else "❌"
        keyboard.button(
            text=f"{status} @{ex.exchanger_name} | {ex.exchanger_data[:20]}...",
            callback_data=f"select_ex_{ex.exchanger_id}",
        )
    keyboard.adjust(1)
    await message.answer(
        i18n.get_text("admin_exchangers.select_to_edit", locale),
        reply_markup=keyboard.as_markup(),
    )
    await state.set_state(ExchangerStates.SELECT_EXCHANGER)


@router.callback_query(
    F.data.startswith("select_ex_"), StateFilter(ExchangerStates.SELECT_EXCHANGER)
)
async def show_edit_options(
    callback: CallbackQuery, state: FSMContext, i18n: Translator, locale: str
):
    exchanger_id = int(callback.data.split("_")[2])
    await _display_exchanger_edit_menu(
        callback.message, exchanger_id, state, i18n, locale
    )
    await callback.answer()


@router.callback_query(
    F.data.startswith("edit_"), StateFilter(ExchangerStates.SELECT_EDIT_ACTION)
)
async def edit_exchanger_field(
    callback: CallbackQuery, state: FSMContext, i18n: Translator, locale: str
):
    action, exchanger_id_str = callback.data.split("_")[1], callback.data.split("_")[2]
    exchanger_id = int(exchanger_id_str)
    await state.update_data(edit_action=action, exchanger_id=exchanger_id)

    prompts = {
        "name": "prompt_edit_name",
        "priority": "prompt_edit_priority",
        "url": "prompt_edit_url",
    }
    if action in prompts:
        await callback.message.edit_text(
            i18n.get_text(f"admin_exchangers.{prompts[action]}", locale)
        )
        await state.set_state(ExchangerStates.EDIT_FIELD)


# ОБРАБОТЧИК для переключения поддержки валют
@router.callback_query(
    F.data.startswith("toggle_currency:"),
    StateFilter(ExchangerStates.SELECT_EDIT_ACTION),
)
async def toggle_exchanger_currency_support(
    callback: CallbackQuery, state: FSMContext, i18n: Translator, locale: str
):
    _, currency, exchanger_id_str = callback.data.split(":")
    exchanger_id = int(exchanger_id_str)
    exchanger = Exchangersx.get(exchanger_id=exchanger_id)
    if not exchanger:
        return await callback.answer(
            i18n.get_text("admin_exchangers.not_found", locale), show_alert=True
        )
    try:
        if currency == "ltc":
            Exchangersx.update(exchanger_id=exchanger_id, is_ltc=not exchanger.is_ltc)
        elif currency == "usdt":
            Exchangersx.update(
                exchanger_id=exchanger_id, is_usdt_trc20=not exchanger.is_usdt_trc20
            )
        await _display_exchanger_edit_menu(
            callback.message, exchanger_id, state, i18n, locale
        )
        await callback.answer(
            i18n.get_text(
                "admin_exchangers.currency_support_updated",
                locale,
                currency=currency.upper(),
            )
        )
    except Exception:
        await callback.answer(i18n.get_text("admin_exchangers.error_generic", locale))


@router.callback_query(
    F.data.startswith("toggle_ex_"), StateFilter(ExchangerStates.SELECT_EDIT_ACTION)
)
async def toggle_exchanger_status(
    callback: CallbackQuery, state: FSMContext, i18n: Translator, locale: str
):
    exchanger_id = int(callback.data.split("_")[2])
    exchanger = Exchangersx.get(exchanger_id=exchanger_id)
    try:
        Exchangersx.update(
            exchanger_id=exchanger_id, exchanger_enabled=not exchanger.exchanger_enabled
        )
        await _display_exchanger_edit_menu(
            callback.message, exchanger_id, state, i18n, locale
        )
    except Exception as e:
        await callback.message.edit_text(
            i18n.get_text("admin_exchangers.error_value", locale, error=e)
        )


@router.message(StateFilter(ExchangerStates.EDIT_FIELD))
async def process_edit_field(
    message: Message, state: FSMContext, i18n: Translator, locale: str
):
    data = await state.get_data()
    action, exchanger_id = data["edit_action"], data["exchanger_id"]
    value = message.text.strip()
    try:
        if action == "name":
            if len(value) > 40:
                raise ValueError(
                    i18n.get_text("admin_exchangers.edit_name_error_len", locale)
                )
            Exchangersx.update(exchanger_id=exchanger_id, exchanger_data=value)
            await message.answer(
                i18n.get_text("admin_exchangers.edit_name_success", locale, value=value)
            )
        elif action == "priority":
            priority = int(value)
            if not 1 <= priority <= 99:
                raise ValueError(
                    i18n.get_text("admin_exchangers.edit_priority_error_range", locale)
                )
            Exchangersx.update(exchanger_id=exchanger_id, exchanger_order=priority)
            await message.answer(
                i18n.get_text(
                    "admin_exchangers.edit_priority_success", locale, priority=priority
                )
            )
        elif action == "url":
            if not value.startswith(("http://", "https://", "tg://")):
                raise ValueError(
                    i18n.get_text("admin_exchangers.edit_link_error_format", locale)
                )
            Exchangersx.update(exchanger_id=exchanger_id, exchanger_custom_url=value)
            await message.answer(
                i18n.get_text("admin_exchangers.edit_link_success", locale)
            )

        exchanger = Exchangersx.get(exchanger_id=exchanger_id)
        keyboard = InlineKeyboardBuilder()
        keyboard.button(
            text=i18n.get_text("admin_exchangers.edit_continue_editing", locale),
            callback_data=f"select_ex_{exchanger_id}",
        )
        keyboard.button(
            text=i18n.get_text(
                "admin_exchangers.edit_back_to_exchanger_list_button", locale
            ),
            callback_data="back_to_ex_list",
        )
        await message.answer(
            i18n.get_text(
                "admin_exchangers.edit_updated_message",
                locale,
                username=exchanger.exchanger_name,
                title=exchanger.exchanger_data,
                priority=exchanger.exchanger_order,
                url=exchanger.exchanger_custom_url
                or i18n.get_text("admin_exchangers.not_specified", locale),
                status=i18n.get_text("admin_exchangers.status_on", locale)
                if exchanger.exchanger_enabled
                else i18n.get_text("admin_exchangers.status_off", locale),
            ),
            reply_markup=keyboard.as_markup(),
        )
    except ValueError as e:
        await message.answer(
            i18n.get_text("admin_exchangers.error_value", locale, error=str(e))
        )
    except Exception as e:
        await message.answer(
            i18n.get_text("admin_exchangers.error_system", locale, error=str(e))
        )
        await message.answer(
            i18n.get_text("admin_exchangers.edit_retry_prompt", locale)
        )


@router.callback_query(F.data == "back_to_ex_list", StateFilter("*"))
async def back_to_exchangers_list(
    callback: CallbackQuery, state: FSMContext, i18n: Translator, locale: str
):
    await callback.message.delete()
    await edit_exchanger_start(callback.message, state, i18n, locale)



#! команда для ручного запуска удаления(архивации) старых файлов изображений покупок
@router.message(Command("delete_images"))
async def admin_force_delete_images(message: Message, bot: Bot):
    await message.answer("Running deletion of image files.\nThis may take some time.")
    try:
        await archive_old_purchase_files(bot)
        await message.answer("☑️ Complete")
    except Exception as e:
        await message.answer(f"❌ Error deletion of image files:\n<code>{e}</code>")
        

@router.message(Command("update_invoice"))
async def admin_force_update_invoice_status(message: Message, bot: Bot):
    await message.answer("Running update invoice status.")
    try:
        await update_invoice_status(PATH_DATABASE, bot)
        await message.answer("☑️ Complete")
    except Exception as e:
        await message.answer(f"❌ Error update invoice status:\n<code>{e}</code>")


@router.message(Command("update_balance"))
async def admin_force_update_balance(message: Message, bot: Bot):
    await message.answer("Running users balance updates.")
    try:
        await update_balance(PATH_DATABASE, bot)
        await message.answer("☑️ Complete")
    except Exception as e:
        await message.answer(f"❌ Error users balance updates:\n<code>{e}</code>")


@router.message(Command("update_rate"))
async def admin_force_update_rate(message: Message, bot: Bot):
    await message.answer("Running LTC rate update.")
    try:
        await update_actual_ltc_rate_in_db(bot)
        await message.answer("☑️ Complete")
    except Exception as e:
        await message.answer(f"❌ Error LTC rate update:\n<code>{e}</code>")


@router.message(Command("update_stats"))
async def admin_force_update_stats(message: Message, bot: Bot):
    await message.answer("Run sending daily stats.")
    try:
        await update_profit_day(bot)
        await message.answer("☑️ Complete")
    except Exception as e:
        await message.answer(f"❌ Error daily stats:\n<code>{e}</code>")