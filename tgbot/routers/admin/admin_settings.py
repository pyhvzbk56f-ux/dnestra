# shop/tgbot/routers/admin/admin_settings.py
from aiogram import Router, Bot, F
from aiogram.filters import StateFilter, Command


from aiogram.fsm.state import State, StatesGroup  #
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.enums import ChatMemberStatus

from tgbot.database import Settingsx, Userx, Buttonx, Channelx
from tgbot.keyboards.inline_admin import (
    settings_status_finl,
    settings_finl,
    select_default_language_keyboard,
    confirm_set_default_language_keyboard,
    wallet_addresses_finl,
    channel_admin_permissions_finl,
)

from tgbot.keyboards.reply_main import buttons_management_frep, settings_frep, channel_management_frep
from tgbot.routers.admin.admin_menu import admin_settings  #
from tgbot.services.i18n import Translator
from tgbot.utils.misc.i18n_filters import I18nText

from tgbot.utils.const_functions import ded, get_unix
from tgbot.utils.misc.bot_models import FSM, ARS
from tgbot.utils.misc_functions import send_admins, insert_tags, bot_logger, update_connection_details_on_aggregator
from tgbot.data.config import get_admins, get_operators, BOT_CONFIG
from tgbot.utils.misc.bot_filters import IsAdmin


router = Router()


#! Определяем состояния для FSM
class AdminSettingsStates(StatesGroup):
    here_settings_faq = State()  # изменение FAQ
    here_settings_info_check = State()  # инфо к чек товара
    here_settings_support = State()  # изменение поддержки
    here_settings_zagolovok = State()  # заголовок наличия товаров
    #here_settings_channel_id = State()  # для канала подписки

    here_settings_agg_url = State()  # для адреса агрегатора - не используется
    here_settings_agg_key = State()  # для ключа агрегатора

    here_wallet_address = State()  #  состояние для адреса кошелька
    here_htx_access_key = State()  # состояние для HTX API ключа
    here_htx_secret_key = State()  # состояние для HTX API ключа
    here_htx_usdt_trc20_address = State()  # состояние для адреса кошелька USDT TRC20 HTX
    here_htx_ltc_address = State()  # состояние для адреса кошелька LTC HTX

    here_alter_ltc_address = State()  # состояние для адреса кошелька LTC ALTERNATIVE
    here_alter_usdt_trc20_address = State()  # состояние для адреса кошелька USDT ALTERNATIVE
    here_tatum_key = State()  #  состояние для АПИ ключа tatum
    here_tronscan_key = State()  #  состояние для АПИ ключа tronscan

    here_settings_dispute_channel = State()  #  состояние для служебного канала для медиа жалоб

    selecting_default_language = State() # выбор языка для установки по умолчанию
    confirming_default_language = State() # подтверждение установки языка

    # Состояния для назначения админа в канале
    waiting_for_channel_to_promote_in = State()
    waiting_for_user_to_promote = State()
    selecting_admin_permissions = State()
    
    # Состояния для управления каналами подписки
    waiting_for_channel_id_to_add = State()
    waiting_for_channel_id_to_delete = State()

    # Состояние для лимита авто-авторизации
    waiting_for_auto_auth_limit = State()

################################################################################
# ! Определяем состояния для FSM для кастомных кнопок
class ButtonStates(StatesGroup):
    add_button_name = State()
    add_button_data = State()
    delete_button_id = State()
    edit_select_id = State()
    edit_new_name = State()
    edit_new_data = State()


################################################################################
#! ИЗМЕНЕНИЕ КАНАЛА ДЛЯ СПОРОВ
@router.callback_query(F.data == "settings_edit_dispute_channel")
async def settings_dispute_channel_edit(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    await state.set_state(AdminSettingsStates.here_settings_dispute_channel)
    await call.message.edit_text(
        i18n.get_text("admin_settings_main.dispute_channel_prompt", locale)
    )


@router.message(F.text, StateFilter(AdminSettingsStates.here_settings_dispute_channel))
async def settings_dispute_channel_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    raw_id = message.text.strip()
    if raw_id == "0":
        Settingsx.update(dispute_channel_id="None")
        await message.answer(
            i18n.get_text("admin_settings_main.dispute_channel_disabled", locale)
        )
        await state.clear()
        await message.answer(
            i18n.get_text("admin_settings_main.edit_bot_data", locale),
            reply_markup=settings_finl(message.from_user.id, i18n, locale),
        )
        return

    try:
        numeric_id = int(raw_id)
    except ValueError:
        return await message.answer(
            i18n.get_text("admin_settings_main.error_channel_id_must_be_int", locale)
        )

    channel_id = int(f"-100{numeric_id}") if numeric_id > 0 else numeric_id
    try:
        bot_member = await bot.get_chat_member(chat_id=channel_id, user_id=bot.id)
        if bot_member.status != ChatMemberStatus.ADMINISTRATOR:
            return await message.answer(
                i18n.get_text("admin_settings_main.error_bot_not_admin", locale)
            )
    except Exception as e:
        return await message.answer(
            i18n.get_text(
                "admin_settings_main.error_failed_to_check_channel",
                locale,
                channel_id=channel_id,
                error=e,
            )
        )

    Settingsx.update(dispute_channel_id=str(channel_id))
    await state.clear()
    await message.answer(
        i18n.get_text(
            "admin_settings_main.dispute_channel_set_success",
            locale,
            channel_id=channel_id,
        )
    )
    await message.answer(
        i18n.get_text("admin_settings_main.edit_bot_data", locale),
        reply_markup=settings_finl(message.from_user.id, i18n, locale),
    )


#!###############################################################################
#! УПРАВЛЕНИЕ ПЛАТЕЖНОЙ СИСТЕМОЙ


def payment_system_finl(i18n: Translator, locale: str) -> InlineKeyboardMarkup:
    """Генерирует клавиатуру для управления платежной системой."""
    settings = Settingsx.get()
    builder = InlineKeyboardBuilder()

    # Переключатель системы
    system_name = "HTX" if settings.payment_system == "htx" else "Альтернатива"
    switch_to = "alternative" if settings.payment_system == "htx" else "htx"
    builder.button(
        text=i18n.get_text(
            "admin_settings_main.switch_payment_system_button",
            locale,
            system_name=system_name,
        ),
        callback_data=f"switch_payment_system:{switch_to}",
    )
    builder.row()

    # Кнопки настроек в зависимости от выбранной системы
    if settings.payment_system == "htx":
        builder.button(
            text=i18n.get_text("admin_settings_main.htx_access_key_button", locale),
            callback_data="edit_payment_field:htx_access_key",
        )
        builder.button(
            text=i18n.get_text("admin_settings_main.htx_secret_key_button", locale),
            callback_data="edit_payment_field:htx_secret_key",
        )
        builder.button(
            text=i18n.get_text("admin_settings_main.htx_ltc_address_button", locale),
            callback_data="edit_payment_field:htx_ltc_address",
        )
        builder.button(
            text=i18n.get_text("admin_settings_main.htx_usdt_address_button", locale),
            callback_data="edit_payment_field:htx_usdt_trc20_address",
        )
    else:  # alternative
        builder.button(
            text=i18n.get_text("admin_settings_main.tatum_key_button", locale),
            callback_data="edit_payment_field:tatum_api_key",
        )
        builder.button(
            text=i18n.get_text("admin_settings_main.tronscan_key_button", locale),
            callback_data="edit_payment_field:tronscan_api_key",
        )
        builder.button(
            text=i18n.get_text("admin_settings_main.alt_ltc_address_button", locale),
            callback_data="edit_payment_field:alter_ltc_address",
        )
        builder.button(
            text=i18n.get_text("admin_settings_main.alt_usdt_address_button", locale),
            callback_data="edit_payment_field:alter_usdt_trc20_address",
        )

    builder.adjust(1, 2, 2)
    return builder.as_markup()


def get_current_payment_settings_text(i18n: Translator, locale: str) -> str:
    """Возвращает текстовое описание текущих настроек платежной системы."""
    settings = Settingsx.get()
    text = i18n.get_text(
        "admin_settings_main.payment_system_active",
        locale,
        system_name=settings.payment_system.upper(),
    )

    def key_status(key):
        return (
            i18n.get_text(
                "admin_settings_main.key_status_set", locale, key_last_chars=key[-4:]
            )
            if key
            else i18n.get_text("admin_settings_main.key_status_not_set", locale)
        )

    if settings.payment_system == "htx":
        text += f"{i18n.get_text('admin_settings_main.payment_system_htx_access_key', locale)}: {key_status(settings.htx_access_key)}\n"
        text += f"{i18n.get_text('admin_settings_main.payment_system_htx_secret_key', locale)}: {key_status(settings.htx_secret_key)}\n"
        text += f"{i18n.get_text('admin_settings_main.payment_system_htx_ltc_address', locale)}: <code>{settings.htx_ltc_address or i18n.get_text('admin_settings.not_specified', locale)}</code>\n"
        text += f"{i18n.get_text('admin_settings_main.payment_system_htx_usdt_address', locale)}: <code>{settings.htx_usdt_trc20_address or i18n.get_text('admin_settings.not_specified', locale)}</code>\n\n"
    else:
        text += f"{i18n.get_text('admin_settings_main.payment_system_alt_tatum_key', locale)}: {key_status(settings.tatum_api_key)}\n"
        text += f"{i18n.get_text('admin_settings_main.payment_system_alt_tronscan_key', locale)}: {key_status(settings.tronscan_api_key)}\n"
        text += f"{i18n.get_text('admin_settings_main.payment_system_alt_ltc_address', locale)}: <code>{settings.alter_ltc_address or i18n.get_text('admin_settings.not_specified', locale)}</code>\n"
        text += f"{i18n.get_text('admin_settings_main.payment_system_alt_usdt_address', locale)}: <code>{settings.alter_usdt_trc20_address or i18n.get_text('admin_settings.not_specified', locale)}</code>\n\n"

    text += i18n.get_text("admin_settings_main.payment_system_instructions", locale)
    return text


@router.message(I18nText("reply_admin.payment_system"), IsAdmin())
async def payment_system_menu(message: Message, i18n: Translator, locale: str):
    await message.answer(
        i18n.get_text("admin_settings_main.payment_system_title", locale)
        + "\n\n"
        + get_current_payment_settings_text(i18n, locale),
        reply_markup=payment_system_finl(i18n, locale),
    )


@router.callback_query(F.data.startswith("switch_payment_system:"))
async def switch_payment_system(call: CallbackQuery, i18n: Translator, locale: str):
    new_system = call.data.split(":")[1]
    Settingsx.update(payment_system=new_system)
    await call.message.edit_text(
        i18n.get_text("admin_settings_main.payment_system_title", locale)
        + "\n\n"
        + get_current_payment_settings_text(i18n, locale),
        reply_markup=payment_system_finl(i18n, locale),
    )
    await call.answer(
        i18n.get_text(
            "admin_settings_main.payment_system_switched",
            locale,
            system_name=new_system.upper(),
        )
    )


@router.callback_query(F.data.startswith("edit_payment_field:"))
async def edit_payment_field_start(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    field = call.data.split(":")[1]

    prompts_keys = {
        "htx_access_key": (
            "enter_htx_access_key",
            AdminSettingsStates.here_htx_access_key,
        ),
        "htx_secret_key": (
            "enter_htx_secret_key",
            AdminSettingsStates.here_htx_secret_key,
        ),
        "htx_ltc_address": (
            "enter_htx_ltc_address",
            AdminSettingsStates.here_htx_ltc_address,
        ),
        "htx_usdt_trc20_address": (
            "enter_htx_usdt_address",
            AdminSettingsStates.here_htx_usdt_trc20_address,
        ),
        "alter_ltc_address": (
            "enter_alt_ltc_address",
            AdminSettingsStates.here_alter_ltc_address,
        ),
        "alter_usdt_trc20_address": (
            "enter_alt_usdt_address",
            AdminSettingsStates.here_alter_usdt_trc20_address,
        ),
        "tatum_api_key": ("enter_tatum_key", AdminSettingsStates.here_tatum_key),
        "tronscan_api_key": (
            "enter_tronscan_key",
            AdminSettingsStates.here_tronscan_key,
        ),
    }

    if field not in prompts_keys:
        await call.answer(
            i18n.get_text("admin_settings_main.unknown_action", locale), show_alert=True
        )
        return

    prompt_key, new_state = prompts_keys.get(field)

    if not prompt_key:
        return

    await state.update_data(field_to_edit=field)
    await state.set_state(new_state)
    prompt_text = i18n.get_text(
        f"admin_settings_main.{prompt_key}", locale
    ) + i18n.get_text("admin_settings_main.prompt_cancel_instruction", locale)
    await call.message.edit_text(prompt_text)
    await call.answer()


async def process_payment_field_input(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    """Общий обработчик для всех состояний ввода данных платежной системы."""
    user_input = message.text.strip()

    if user_input == "0":
        await message.answer(
            i18n.get_text("admin_settings_main.edit_cancelled", locale)
        )
        await state.clear()
        await payment_system_menu(message, i18n, locale)
        return

    data = await state.get_data()
    field_to_edit = data.get("field_to_edit")

    if not field_to_edit:
        await message.answer(
            i18n.get_text("admin_settings_main.state_error_start_again", locale)
        )
        await state.clear()
        return

    try:
        Settingsx.update(**{field_to_edit: user_input})
        await state.clear()
        await message.answer(
            i18n.get_text(
                "admin_settings_main.data_updated_success",
                locale,
                field_name=field_to_edit,
            )
        )
        await payment_system_menu(message, i18n, locale)
    except Exception as e:
        await message.answer(
            i18n.get_text("admin_settings_main.data_save_error", locale, error=e)
        )
        await state.clear()


#! Регистрируем общий обработчик для всех состояний
#! Важно: нужно обернуть в lambda, чтобы передать i18n и locale в хендлер
for st in [
    AdminSettingsStates.here_htx_access_key,
    AdminSettingsStates.here_htx_secret_key,
    AdminSettingsStates.here_htx_ltc_address,
    AdminSettingsStates.here_htx_usdt_trc20_address,
    AdminSettingsStates.here_alter_ltc_address,
    AdminSettingsStates.here_alter_usdt_trc20_address,
    AdminSettingsStates.here_tatum_key,
    AdminSettingsStates.here_tronscan_key,
]:
    router.message.register(process_payment_field_input, st)


#!###############################################################################
#! блок для управления ключом агрегатора
@router.callback_query(F.data == "settings_edit_agg_key", IsAdmin())
async def settings_agg_key_edit(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
    await state.clear()
    await state.set_state(AdminSettingsStates.here_settings_agg_key)
    await call.message.edit_text(i18n.get_text("admin_settings_main.enter_aggregator_key", locale))


@router.message(F.text, StateFilter(AdminSettingsStates.here_settings_agg_key))
async def settings_agg_key_get(message: Message, bot: Bot, state: FSM, arSession: ARS, i18n: Translator, locale: str):
    agg_key = message.text.strip()

    if agg_key == "0":
        await message.answer(i18n.get_text("admin_settings_main.edit_cancelled", locale))
    else:
        Settingsx.update(agg_key=agg_key, send_to_aggregator="True")
        await message.answer(i18n.get_text("admin_settings_main.aggregator_key_updated", locale))
        # Сразу отправляем данные о подключении на агрегатор
        await update_connection_details_on_aggregator(bot, arSession)

    await state.clear()
    await message.answer(i18n.get_text("admin_settings_main.edit_bot_data", locale),reply_markup=settings_finl(message.from_user.id, i18n, locale),)


#!###############################################################################
#! УПРАВЛЕНИЕ API КЛЮЧАМИ


#! Меню управления API ключами
@router.message(I18nText("reply_admin.api_keys"))  # Предполагаемый ключ для кнопки
async def settings_api_keys_menu(message: Message, i18n: Translator, locale: str):
    get_settings = Settingsx.get()

    tatum_key = get_settings.tatum_api_key
    if tatum_key:
        tatum_status = i18n.get_text(
            "admin_settings_main.key_status_set", locale, key_last_chars=tatum_key[-4:]
        )
    else:
        tatum_status = i18n.get_text(
            "admin_settings_main.key_not_set", locale, key_name="Tatum"
        )
    tatum_status_text = i18n.get_text(
        "admin_settings_main.api_keys_tatum_status", locale, status=tatum_status
    )

    tronscan_key = get_settings.tronscan_api_key
    if tronscan_key:
        tronscan_status = i18n.get_text(
            "admin_settings_main.key_status_set",
            locale,
            key_last_chars=tronscan_key[-4:],
        )
    else:
        tronscan_status = i18n.get_text(
            "admin_settings_main.key_not_set", locale, key_name="TronScan"
        )
    tronscan_status_text = i18n.get_text(
        "admin_settings_main.api_keys_tronscan_status", locale, status=tronscan_status
    )

    keyboard = InlineKeyboardBuilder()
    keyboard.button(
        text=i18n.get_text("admin_settings_main.tatum_change_key_button", locale),
        callback_data="edit_tatum_key",
    )
    keyboard.button(
        text=i18n.get_text("admin_settings_main.tronscan_change_key_button", locale),
        callback_data="edit_tronscan_key",
    )
    keyboard.adjust(1)

    await message.answer(
        f"{i18n.get_text('admin_settings_main.api_keys_title', locale)}\n\n{tatum_status_text}\n{tronscan_status_text}",
        reply_markup=keyboard.as_markup(),
    )


#! Начало изменения ключа Tatum
@router.callback_query(F.data == "edit_tatum_key")
async def edit_tatum_key_start(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    await state.set_state(AdminSettingsStates.here_tatum_key)
    await call.message.edit_text(
        i18n.get_text("admin_settings_main.enter_tatum_token", locale)
    )
    await call.answer()


#! Получение и сохранение ключа
@router.message(StateFilter(AdminSettingsStates.here_tatum_key))
async def process_tatum_key(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    new_key = message.text.strip()

    if new_key == "0":
        await message.answer(
            i18n.get_text("admin_settings_main.edit_cancelled", locale)
        )
        await state.clear()
        return

    Settingsx.update(tatum_api_key=new_key)
    await state.clear()

    await message.answer(
        i18n.get_text(
            "admin_settings_main.tatum_key_updated", locale, key_last_chars=new_key[-4:]
        )
    )


#! Начало изменения ключа TronScan
@router.callback_query(F.data == "edit_tronscan_key")
async def edit_tronscan_key_start(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    await state.set_state(AdminSettingsStates.here_tronscan_key)
    await call.message.edit_text(
        i18n.get_text("admin_settings_main.enter_tronscan_token", locale)
    )
    await call.answer()


#! Получение и сохранение ключа TronScan
@router.message(StateFilter(AdminSettingsStates.here_tronscan_key))
async def process_tronscan_key(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    new_key = message.text.strip()

    if new_key == "0":
        await message.answer(
            i18n.get_text("admin_settings_main.edit_cancelled", locale)
        )
        await state.clear()
        return

    Settingsx.update(tronscan_api_key=new_key)
    await state.clear()

    await message.answer(
        i18n.get_text(
            "admin_settings_main.tronscan_key_updated",
            locale,
            key_last_chars=new_key[-4:],
        )
    )


#!###############################################################################
#! Управление адресами кошельков
@router.message(I18nText("reply_admin.wallet_addresses"))
async def settings_wallets_edit(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    await message.answer(
        i18n.get_text("admin_settings_main.wallets_title", locale),
        reply_markup=wallet_addresses_finl(i18n, locale),
    )


#! Начало изменения адреса кошелька
@router.callback_query(F.data.startswith("edit_wallet:"))
async def edit_wallet_address_start(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    currency = call.data.split(":")[1]
    await state.update_data(currency_to_edit=currency)
    await state.set_state(AdminSettingsStates.here_wallet_address)

    currency_name = "LTC" if currency == "ltc" else "USDT TRC20"
    await call.message.edit_text(
        i18n.get_text(
            "admin_settings_main.enter_new_address", locale, currency_name=currency_name
        )
    )
    await call.answer()


#! Получение нового адреса и сохранение
@router.message(StateFilter(AdminSettingsStates.here_wallet_address))
async def process_new_wallet_address(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    new_address = message.text.strip()
    user_data = await state.get_data()
    currency = user_data.get("currency_to_edit")

    if not new_address:
        await message.answer(
            i18n.get_text("admin_settings_main.error_address_empty", locale)
        )
        return

    if currency == "ltc":
        Settingsx.update(htx_ltc_address=new_address)
    elif currency == "usdt":
        Settingsx.update(htx_usdt_trc20_address=new_address)

    await state.clear()
    await message.answer(
        i18n.get_text(
            "admin_settings_main.address_updated_success",
            locale,
            currency_name=currency.upper(),
        ),
        reply_markup=wallet_addresses_finl(i18n, locale),
    )


#!###############################################################################
#!################################## ИНТЕРВАЛЫ #################################
#! Обработчик для команды 🕘 Настройки интервалов
@router.message(I18nText("reply_admin.intervals"), IsAdmin())
async def settings_interval_edit(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    await message.answer(
        i18n.get_text("admin_settings_main.intervals_title", locale),
        reply_markup=settings_update_interval(i18n, locale),
    )


#! Список возможных значений для config_key
VALID_CONFIG_KEYS = {
    "time_pause_to_reject_status",
    "update_balance_time_seconds",
    "update_pending_status_time_seconds",
    "update_invoice_status_time_seconds",
}


#! Функция для генерации клавиатуры с инструкциями
def settings_update_interval(i18n: Translator, locale: str) -> InlineKeyboardMarkup:
    button = InlineKeyboardButton(
        text=i18n.get_text("admin_settings_main.intervals_instruction_button", locale),
        callback_data="show_interval_info",
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[button]])
    return keyboard


#! Обработчик для показа инструкции по обновлению интервалов
@router.callback_query(F.data == "show_interval_info")
async def show_interval_info(callback: CallbackQuery, i18n: Translator, locale: str):
    info_text = i18n.get_text("admin_settings_main.intervals_instruction_text", locale)
    await callback.message.edit_text(info_text)


#! Обработчик команды /insert_interval_time
@router.message(Command("insert_interval_time"))
async def func_insert_interval_time(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    admin_ids = get_admins()
    if message.from_user.id in admin_ids:
        # Получаем текст после команды
        command_text = message.text.strip()
        # Разделяем строку по пробелу на два параметра
        params = command_text.split()
        # Извлекаем параметры
        config_key = params[1]
        update_time_str = params[2]
        # Проверяем, что первое значение является валидным ключом
        if config_key not in VALID_CONFIG_KEYS:
            keys_str = ", ".join(f"<code>{key}</code>" for key in VALID_CONFIG_KEYS)
            await message.answer(
                i18n.get_text(
                    "admin_settings_main.intervals_error_invalid_key",
                    locale,
                    keys=keys_str,
                )
            )
            return

        # Проверяем, что второе значение — это положительное целое число
        try:
            update_time = int(update_time_str)
            if update_time <= 0:
                raise ValueError(
                    i18n.get_text(
                        "admin_settings_main.intervals_error_not_positive_int", locale
                    )
                )
        except ValueError:
            await message.answer(
                i18n.get_text("admin_settings_main.intervals_error_invalid_int", locale)
            )
            return

        # Записываем значение в settings.ini
        try:
            BOT_CONFIG["settings"][config_key] = str(update_time)
            with open("settings.ini", "w") as configfile:
                BOT_CONFIG.write(configfile)

            # Ответ пользователю
            await message.answer(
                i18n.get_text(
                    "admin_settings_main.intervals_update_success",
                    locale,
                    key=config_key,
                    value=update_time,
                )
            )
        except Exception as ex:
            bot_logger.error(f"Error when writing in settings.ini: {ex}")


################################################################################


#! Изменение данных
@router.message(I18nText("reply_admin.edit_data"))
async def settings_data_edit(message: Message, state: FSM, i18n: Translator, locale: str):
    await state.clear()
    await message.answer(
        i18n.get_text("admin_settings_main.edit_bot_data", locale),
        reply_markup=settings_finl(message.from_user.id, i18n, locale),
    )


#! Выключатели бота
@router.message(I18nText("reply_admin.switches"))
async def settings_status_edit(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    await message.answer(
        i18n.get_text("admin_settings_main.switches_title", locale),
        reply_markup=settings_status_finl(message.from_user.id, i18n, locale),
    )


#!###############################################################################
#!################################## ВЫКЛЮЧАТЕЛИ #################################
#! Включение/выключение тех работ
@router.callback_query(F.data.startswith("settings_status_work:"))
async def settings_status_work(
    call: CallbackQuery, bot: Bot, i18n: Translator, locale: str
):
    get_status = call.data.split(":")[1]
    get_user = Userx.get(user_id=call.from_user.id)
    Settingsx.update(status_work=get_status)

    action_text_key = (
        "switches_log_tech_on" if get_status == "True" else "switches_log_tech_off"
    )
    send_text = i18n.get_text(f"admin_settings_main.{action_text_key}", locale)

    log_text = i18n.get_text(
        "admin_settings_main.switches_log_admin_action",
        locale,
        user_id=get_user.user_id,
        user_name=get_user.user_name,
        action_text=send_text,
    )

    await send_admins(bot=bot, text=ded(log_text), not_me=get_user.user_id)
    await call.message.edit_reply_markup(
        reply_markup=settings_status_finl(call.from_user.id, i18n, locale),
    )


#! Включение/выключение покупок
@router.callback_query(F.data.startswith("settings_status_buy:"), IsAdmin())
async def settings_status_buy(
    call: CallbackQuery, bot: Bot, i18n: Translator, locale: str
):
    get_status = call.data.split(":")[1]
    get_user = Userx.get(user_id=call.from_user.id)
    Settingsx.update(status_buy=get_status)

    action_text_key = (
        "switches_log_purchases_on"
        if get_status == "True"
        else "switches_log_purchases_off"
    )
    send_text = i18n.get_text(f"admin_settings_main.{action_text_key}", locale)

    log_text = i18n.get_text(
        "admin_settings_main.switches_log_admin_action",
        locale,
        user_id=get_user.user_id,
        user_name=get_user.user_name,
        action_text=send_text,
    )

    await send_admins(bot=bot, text=ded(log_text), not_me=get_user.user_id)
    await call.message.edit_reply_markup(
        reply_markup=settings_status_finl(call.from_user.id, i18n, locale),
    )


#! Включение/выключение пополнений
@router.callback_query(F.data.startswith("settings_status_pay:"), IsAdmin())
async def settings_status_pay(
    call: CallbackQuery, bot: Bot, i18n: Translator, locale: str
):
    get_status = call.data.split(":")[1]
    get_user = Userx.get(user_id=call.from_user.id)
    Settingsx.update(status_refill=get_status)

    action_text_key = (
        "switches_log_refills_on"
        if get_status == "True"
        else "switches_log_refills_off"
    )
    send_text = i18n.get_text(f"admin_settings_main.{action_text_key}", locale)

    log_text = i18n.get_text(
        "admin_settings_main.switches_log_admin_action",
        locale,
        user_id=get_user.user_id,
        user_name=get_user.user_name,
        action_text=send_text,
    )

    await send_admins(bot, log_text, not_me=get_user.user_id)
    await call.message.edit_reply_markup(
        reply_markup=settings_status_finl(call.from_user.id, i18n, locale),
    )

# Включение/выключение обязательной авторизации
@router.callback_query(F.data.startswith("settings_status_auth:"), IsAdmin())
async def settings_status_auth_toggle(
    call: CallbackQuery, bot: Bot, i18n: Translator, locale: str
):
    get_status = call.data.split(":")[1]
    get_user = Userx.get(user_id=call.from_user.id)
    Settingsx.update(authorization_required=get_status)

    action_text = (
        "включил" if get_status == "True" else "выключил"
    )
    send_text = f"🔑 Авторизация пользователей: {action_text}"

    log_text = i18n.get_text(
        "admin_settings_main.switches_log_admin_action",
        locale,
        user_id=get_user.user_id,
        user_name=get_user.user_name,
        action_text=send_text,
    )

    await send_admins(bot, log_text, not_me=get_user.user_id)
    await call.message.edit_reply_markup(
        reply_markup=settings_status_finl(call.from_user.id, i18n, locale),
    )



#!############################### ИЗМЕНЕНИЕ ДАННЫХ ###############################
#! Изменение FAQ
@router.callback_query(F.data == "settings_edit_faq")
async def settings_faq_edit(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    await state.set_state(AdminSettingsStates.here_settings_faq)
    await call.message.edit_text(
        ded(i18n.get_text("admin_settings_main.edit_faq_prompt", locale))
    )


#! Изменение инфо к чеку
@router.callback_query(F.data == "settings_edit_info_check")
async def settings_info_check_edit(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    await state.set_state("here_settings_info_check")
    await call.message.edit_text(
        ded(i18n.get_text("admin_settings_main.edit_info_check_prompt", locale))
    )


#! Изменение поддержки
@router.callback_query(F.data == "settings_edit_support")
async def settings_support_edit(
    call: CallbackQuery, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    await state.set_state("here_settings_support")
    await call.message.edit_text(
        i18n.get_text("admin_settings_main.edit_support_prompt", locale)
    )


#! Изменение отображения/скрытия категорий без товаров
@router.callback_query(F.data.startswith("settings_edit_hide_category:"))
async def settings_edit_hide_category(
    call: CallbackQuery, i18n: Translator, locale: str
):
    status = call.data.split(":")[1]
    Settingsx.update(misc_hide_category=status)
    await call.message.edit_text(
        i18n.get_text("admin_settings_main.edit_bot_data", locale),
        reply_markup=settings_finl(call.from_user.id, i18n, locale),
    )


#! Изменение отображения/скрытия подкатегорий без товаров
@router.callback_query(F.data.startswith("settings_edit_hide_subcategory:"))
async def settings_edit_hide_subcategory(
    call: CallbackQuery, i18n: Translator, locale: str
):
    status = call.data.split(":")[1]
    Settingsx.update(misc_hide_subcategory=status)
    await call.message.edit_text(
        i18n.get_text("admin_settings_main.edit_bot_data", locale),
        reply_markup=settings_finl(call.from_user.id, i18n, locale),
    )


#! Изменение отображения/скрытия позиций без товаров
@router.callback_query(F.data.startswith("settings_edit_hide_position:"))
async def settings_edit_hide_position(
    call: CallbackQuery, i18n: Translator, locale: str
):
    status = call.data.split(":")[1]
    Settingsx.update(misc_hide_position=status)
    await call.message.edit_text(
        i18n.get_text("admin_settings_main.edit_bot_data", locale),
        reply_markup=settings_finl(call.from_user.id, i18n, locale),
    )


# ?###############################################################################
# ? Изменение адреса агрегатора - Не используется.
# @router.callback_query(F.data == "settings_edit_agg_url")
# async def settings_agg_url_edit(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
#    await state.clear()
#    await state.set_state(AdminSettingsStates.here_settings_agg_url)
#    await call.message.edit_text(
#        ded(i18n.get_text("admin_settings_main.edit_aggregator_url_prompt", locale))
#    )


################################################################################
################################ ПРИНЯТИЕ ДАННЫХ ###############################
#! Принятие FAQ
@router.message(F.text, StateFilter(AdminSettingsStates.here_settings_faq))
async def settings_faq_get(message: Message, state: FSM, i18n: Translator, locale: str):
    get_message = insert_tags(message.from_user.id, message.text)
    try:
        await (await message.answer(get_message)).delete()
    except Exception as e:
        bot_logger.error(f"Error when edit FAQ: {e}")
        return await message.answer(i18n.get_text("admin_settings_main.error_html_syntax_faq", locale))

    await state.clear()
    Settingsx.update(misc_faq=message.text)
    await message.answer(i18n.get_text("admin_settings_main.edit_bot_data", locale),reply_markup=settings_finl(message.from_user.id, i18n, locale),)


@router.message(F.text, StateFilter("here_settings_info_check"))
async def settings_info_check_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    get_message = insert_tags(message.from_user.id, message.text)

    try:
        await (await message.answer(get_message)).delete()
    except Exception as e:
        bot_logger.error(f"Error when edit misc_info_check: {e}")
        return await message.answer(i18n.get_text("admin_settings_main.error_html_syntax_info_check", locale))

    await state.clear()
    Settingsx.update(misc_info_check=message.text)
    await message.answer(
        i18n.get_text("admin_settings_main.edit_bot_data", locale),
        reply_markup=settings_finl(message.from_user.id, i18n, locale),
    )


#! Принятие поддержки
@router.message(F.text, StateFilter("here_settings_support"))
async def settings_support_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    get_support = message.text
    if get_support.startswith("@"):
        get_support = get_support[1:]

    Settingsx.update(misc_support=get_support)
    await state.clear()
    await message.answer(
        i18n.get_text("admin_settings_main.edit_bot_data", locale),
        reply_markup=settings_finl(message.from_user.id, i18n, locale),
        )


#! Изменение заголовка наличия товаров
@router.callback_query(F.data == "settings_edit_zagolovok")
async def settings_edit_zagolovok(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
    await state.set_state("here_settings_zagolovok")
    await call.message.edit_text(i18n.get_text("admin_settings_main.edit_availability_header_prompt", locale))


#! Принятие нового заголовка наличия товаров
@router.message(F.text, StateFilter("here_settings_zagolovok"))
async def settings_zagolovok_get(message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str):
    get_message = insert_tags(message.from_user.id, message.text)
    try:
        await (await message.answer(get_message)).delete()
    except Exception as e:
        bot_logger.error(f"Error when edit zagolovok_get: {e}")
        return await message.answer(i18n.get_text("admin_settings_main.error_html_syntax_availability_header", locale))

    await state.clear()
    Settingsx.update(zagolovok_info=message.text)
    await message.answer(i18n.get_text("admin_settings_main.edit_bot_data", locale),reply_markup=settings_finl(message.from_user.id, i18n, locale),)

#!####################### УПРАВЛЕНИЕ КАНАЛАМИ ПОДПИСКИ ######################
@router.message(I18nText("reply_admin.channel_management"), IsAdmin())
async def manage_subscription_channels(message: Message, i18n: Translator, locale: str):
    await message.answer(
        i18n.get_text("admin_settings.channel_management_title", locale),
        reply_markup=channel_management_frep(i18n, locale)
    )

@router.message(I18nText("reply_admin.add_channel"), IsAdmin())
async def add_channel_start(message: Message, state: FSM, i18n: Translator, locale: str):
    if Channelx.count() >= 10:
        await message.answer(i18n.get_text("admin_settings.channel_add_limit_error", locale))
        return
    await state.set_state(AdminSettingsStates.waiting_for_channel_id_to_add)
    await message.answer(i18n.get_text("admin_settings_main.edit_channel_prompt", locale))

@router.message(StateFilter(AdminSettingsStates.waiting_for_channel_id_to_add))
async def add_channel_id_get(message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str):
    raw_id = message.text.strip()
    if not (raw_id.startswith("-") and raw_id[1:].isdigit() or raw_id.isdigit()):
        return await message.answer(i18n.get_text("admin_settings_main.error_id_must_be_int", locale))
    
    numeric_id = int(raw_id)
    api_chat_id = int(f"-100{str(numeric_id).lstrip('-')}") if numeric_id > -1000000000000 else numeric_id

    if Channelx.get(channel_id=api_chat_id):
        return await message.answer(i18n.get_text("admin_settings.channel_add_exists_error", locale))

    try:
        chat = await bot.get_chat(api_chat_id)
        bot_member = await bot.get_chat_member(chat_id=api_chat_id, user_id=bot.id)
        if bot_member.status != ChatMemberStatus.ADMINISTRATOR:
            return await message.answer(i18n.get_text("admin_settings_main.error_bot_not_admin_in_group", locale))
        if not bot_member.can_invite_users:
            return await message.answer(i18n.get_text("admin_settings_main.error_bot_no_invite_rights", locale))
        
        invite_link = await bot.create_chat_invite_link(chat_id=api_chat_id, name="Bot Invite")
        
        Channelx.add(channel_id=api_chat_id, channel_link=invite_link.invite_link, channel_name=chat.title)
        await state.clear()
        await message.answer(i18n.get_text("admin_settings.channel_add_success", locale, channel_name=chat.title, channel_id=api_chat_id))
        await manage_subscription_channels(message, i18n, locale)

    except Exception as e:
        await message.answer(i18n.get_text("admin_settings_main.error_failed_to_check_group", locale, chat_id=api_chat_id, error=e))

@router.message(I18nText("reply_admin.list_channels"), IsAdmin())
async def list_channels(message: Message, i18n: Translator, locale: str):
    channels = Channelx.get_all()
    if not channels:
        await message.answer(i18n.get_text("admin_settings.channel_list_empty", locale))
        return

    text = f"{i18n.get_text('admin_settings.channel_list_title', locale)} ({len(channels)}/10):\n\n"
    for i, channel in enumerate(channels, 1):
        text += f"{i}. <b>{channel.channel_name or 'Без названия'}</b>\n"
        text += f"   - ID: <code>{channel.channel_id}</code>\n"
        text += f"   - Link: {channel.channel_link}\n\n"
    
    await message.answer(text, disable_web_page_preview=True)

@router.message(I18nText("reply_admin.delete_channel"), IsAdmin())
async def delete_channel_start(message: Message, state: FSM, i18n: Translator, locale: str):
    channels = Channelx.get_all()
    if not channels:
        await message.answer(i18n.get_text("admin_settings.channel_list_empty", locale))
        return
    
    await state.set_state(AdminSettingsStates.waiting_for_channel_id_to_delete)
    text = f"{i18n.get_text('admin_settings.channel_delete_prompt', locale)}\n\n"
    for i, channel in enumerate(channels, 1):
        text += f"{i}. <b>{channel.channel_name or 'Без названия'}</b> (ID: <code>{channel.channel_id}</code>)\n"
    
    await message.answer(text)

@router.message(StateFilter(AdminSettingsStates.waiting_for_channel_id_to_delete))
async def delete_channel_id_get(message: Message, state: FSM, i18n: Translator, locale: str):
    try:
        channel_id = int(message.text)
        channel_to_delete = Channelx.get(channel_id=channel_id)
        if channel_to_delete:
            Channelx.delete(channel_id=channel_id)
            await state.clear()
            await message.answer(i18n.get_text("admin_settings.channel_delete_success", locale, channel_name=channel_to_delete.channel_name))
            await manage_subscription_channels(message, i18n, locale)
        else:
            await message.answer(i18n.get_text("admin_settings.channel_not_found_by_id", locale))
    except ValueError:
        await message.answer(i18n.get_text("admin_settings_main.error_id_must_be_int", locale))


#!####################### УПРАВЛЕНИЕ КНОПКАМИ ######################
#! Меню управления кнопками
@router.message(I18nText("reply_admin.buttons_manage"), IsAdmin())
async def manage_buttons_menu(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    await message.answer(
        i18n.get_text("admin_settings_main.buttons_manage_title", locale),
        reply_markup=buttons_management_frep(i18n, locale),
    )


#! Возврат в главное меню настроек
@router.message(I18nText("reply_admin.back"))  #! Используем новый фильтр
async def back_to_settings_menu(message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str):
    await admin_settings(message, bot, state, i18n, locale)


#! Просмотр списка кнопок
@router.message(I18nText("reply_admin.list_buttons"))
async def list_custom_buttons(message: Message, i18n: Translator, locale: str):
    buttons = Buttonx.get_all()
    if not buttons:
        return await message.answer(
            i18n.get_text("admin_settings_main.buttons_list_empty", locale)
        )

    response_text = i18n.get_text("admin_settings_main.buttons_list_title", locale)
    for btn in buttons:
        response_text += i18n.get_text(
            "admin_settings_main.buttons_list_item",
            locale,
            button_name=btn.button_name,
            button_id=btn.button_id,
            button_data=btn.button_data[:70],
        )

    if len(response_text) > 4096:
        for x in range(0, len(response_text), 4096):
            await message.answer(response_text[x : x + 4096])
    else:
        await message.answer(response_text)


#! Добавление кнопки
@router.message(I18nText("reply_admin.add_button"))
async def add_button_start(message: Message, state: FSM, i18n: Translator, locale: str):
    await state.set_state(ButtonStates.add_button_name)
    await message.answer(
        i18n.get_text("admin_settings_main.buttons_add_name_prompt", locale)
    )


#! Принятие названия кнопки
@router.message(StateFilter(ButtonStates.add_button_name))
async def add_button_name_get(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    await state.update_data(button_name=message.text)
    await state.set_state(ButtonStates.add_button_data)
    await message.answer(
        i18n.get_text("admin_settings_main.buttons_add_data_prompt", locale)
    )


#! Принятие данных кнопки и сохранение
@router.message(StateFilter(ButtonStates.add_button_data))
async def add_button_data_get(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    user_data = await state.get_data()
    button_name = user_data["button_name"]
    button_data = message.html_text

    Buttonx.add(
        user_id=message.from_user.id,
        button_name=button_name,
        button_data=button_data,
        button_enabled=True,
        button_unix=get_unix(),
        button_id=0,
    )

    await state.clear()
    await message.answer(
        i18n.get_text(
            "admin_settings_main.buttons_add_success", locale, button_name=button_name
        ),
        reply_markup=buttons_management_frep(i18n, locale),
    )


#! Удаление кнопки (показ списка и запрос ID)
@router.message(I18nText("reply_admin.delete_button"))
async def delete_button_start(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    buttons = Buttonx.get_all()
    if not buttons:
        await message.answer(
            i18n.get_text("admin_settings_main.buttons_list_empty", locale)
        )
        return

    response_text = i18n.get_text(
        "admin_settings_main.buttons_list_for_delete_long", locale
    )
    for btn in buttons:
        response_text += i18n.get_text(
            "admin_settings_main.buttons_list_for_delete_item",
            locale,
            button_name=btn.button_name,
            button_id=btn.button_id,
        )

    response_text += i18n.get_text("admin_settings_main.buttons_delete_prompt", locale)

    await state.set_state(ButtonStates.delete_button_id)

    if len(response_text) > 4096:
        list_text = i18n.get_text(
            "admin_settings_main.buttons_list_for_delete_long", locale
        )
        for btn in buttons:
            list_text += i18n.get_text(
                "admin_settings_main.buttons_list_for_delete_long_item",
                locale,
                button_name=btn.button_name,
                button_id=btn.button_id,
            )

        for x in range(0, len(list_text), 4096):
            await message.answer(list_text[x : x + 4096])
        await message.answer(
            i18n.get_text("admin_settings_main.buttons_delete_prompt_long", locale)
        )
    else:
        await message.answer(response_text)


#! Принятие ID и удаление
@router.message(StateFilter(ButtonStates.delete_button_id))
async def delete_button_id_get(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    try:
        button_id = int(message.text)
        button_to_delete = Buttonx.get(button_id=button_id)
        if button_to_delete:
            Buttonx.delete(button_id=button_id)
            await state.clear()
            await message.answer(
                i18n.get_text(
                    "admin_settings_main.buttons_delete_success",
                    locale,
                    button_name=button_to_delete.button_name,
                ),
                reply_markup=buttons_management_frep(i18n, locale),
            )
        else:
            await message.answer(
                i18n.get_text("admin_settings_main.buttons_not_found_by_id", locale)
            )
    except ValueError:
        await message.answer(
            i18n.get_text("admin_settings_main.buttons_id_must_be_int", locale)
        )


#! --- РЕДАКТИРОВАНИЕ КНОПКИ ---
@router.message(I18nText("reply_admin.edit_button"))
async def edit_button_start(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    buttons = Buttonx.get_all()
    if not buttons:
        await message.answer(
            i18n.get_text("admin_settings_main.buttons_edit_list_empty", locale)
        )
        return

    response_text = i18n.get_text("admin_settings_main.buttons_edit_list_title", locale)
    for btn in buttons:
        response_text += i18n.get_text(
            "admin_settings_main.buttons_edit_list_item",
            locale,
            button_name=btn.button_name,
            button_id=btn.button_id,
        )
    response_text += i18n.get_text("admin_settings_main.buttons_edit_prompt", locale)

    await state.set_state(ButtonStates.edit_select_id)
    await message.answer(response_text)


@router.message(StateFilter(ButtonStates.edit_select_id))
async def edit_button_id_get(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    try:
        button_id = int(message.text)
        if not Buttonx.get(button_id=button_id):
            await message.answer(
                i18n.get_text("admin_settings_main.buttons_not_found_by_id", locale)
            )
            return
        await state.update_data(edit_button_id=button_id)
        await state.set_state(ButtonStates.edit_new_name)
        await message.answer(
            i18n.get_text("admin_settings_main.buttons_edit_enter_new_name", locale)
        )
    except ValueError:
        await message.answer(
            i18n.get_text("admin_settings_main.buttons_id_must_be_int", locale)
        )


@router.message(StateFilter(ButtonStates.edit_new_name))
async def edit_button_name_get(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    await state.update_data(new_name=message.text)
    await state.set_state(ButtonStates.edit_new_data)
    await message.answer(
        i18n.get_text("admin_settings_main.buttons_edit_enter_new_data", locale)
    )


@router.message(StateFilter(ButtonStates.edit_new_data))
async def edit_button_data_get(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    user_data = await state.get_data()
    Buttonx.update(
        button_id=user_data["edit_button_id"],
        button_name=user_data["new_name"],
        button_data=message.html_text,
    )
    await state.clear()
    await message.answer(
        i18n.get_text(
            "admin_settings_main.buttons_edit_success",
            locale,
            button_id=user_data["edit_button_id"],
        ),
        reply_markup=buttons_management_frep(i18n, locale),
    )


#! Включение/выключение отправки в агрегатор
@router.callback_query(F.data.startswith("settings_status_aggregator:"), IsAdmin())
async def settings_status_aggregator(
    call: CallbackQuery, bot: Bot, i18n: Translator, locale: str
):
    get_status = call.data.split(":")[1]
    Settingsx.update(send_to_aggregator=get_status)

    get_user = Userx.get(user_id=call.from_user.id)
    action_key = (
        "switches_log_aggregator_on"
        if get_status == "True"
        else "switches_log_aggregator_off"
    )
    send_text = i18n.get_text(f"admin_settings_main.{action_key}", locale)

    log_text = i18n.get_text(
        "admin_settings_main.switches_log_admin_action",
        locale,
        user_id=get_user.user_id,
        user_name=get_user.user_name,
        action_text=send_text,
    )

    await send_admins(bot=bot, text=ded(log_text), not_me=get_user.user_id)
    await call.message.edit_reply_markup(
        reply_markup=settings_status_finl(call.from_user.id, i18n, locale),
    )


# Обработчик для переключения доступности языков
@router.callback_query(F.data.startswith("settings_lang_status:"), IsAdmin())
async def settings_lang_status_toggle(call: CallbackQuery, bot: Bot, i18n: Translator, locale: str):
    _, lang_code, new_status_str = call.data.split(":")
    field_to_update = f"lang_{lang_code}_enabled"
    Settingsx.update(**{field_to_update: new_status_str})

    get_user = Userx.get(user_id=call.from_user.id)
    status_text = "enables" if new_status_str == "True" else "disabled"

    lang_name_map = {
        "ru": "Русский",
        "en": "English",
        "ro": "Română",
        "ka": "ქართული",
    }
    lang_name = lang_name_map.get(lang_code, lang_code.upper())
    log_text = (
        f"👤 Administrator <a href='tg://user?id={get_user.user_id}'>{get_user.user_name}</a>\n"
        f"⚙️ {status_text} language availability: {lang_name}"
    )
    await send_admins(bot=bot, text=ded(log_text), not_me=get_user.user_id)
    await call.message.edit_reply_markup(
        reply_markup=settings_status_finl(call.from_user.id, i18n, locale),
    )
    await call.answer(f"language {lang_name} {status_text}")


#! Запрос выбора языка для установки по умолчанию
@router.callback_query(F.data == "set_default_language", IsAdmin())
async def set_default_language_start(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
    await state.set_state(AdminSettingsStates.selecting_default_language)
    keyboard = select_default_language_keyboard(i18n, locale)
    if not keyboard.inline_keyboard: # Проверяем, есть ли вообще включенные языки
        await call.answer(i18n.get_text("no_enabled_languages_error", locale), show_alert=True)
        await state.clear()
        return
    await call.message.edit_text(i18n.get_text("select_default_language_prompt", locale),reply_markup=keyboard,)
    await call.answer()

#! Получение выбранного языка и запрос подтверждения
@router.callback_query(F.data.startswith("select_default_lang:"), StateFilter(AdminSettingsStates.selecting_default_language))
async def process_language_selection(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
    lang_code = call.data.split(":")[1]
    lang_map = { "ru": "Русский", "en": "English", "ro": "Română", "ka": "ქართული" }
    lang_name = lang_map.get(lang_code, lang_code.upper())
    await state.update_data(chosen_lang=lang_code, lang_name=lang_name)
    await state.set_state(AdminSettingsStates.confirming_default_language)
    await call.message.edit_text( i18n.get_text("confirm_specific_default_lang_prompt", locale, lang_name=lang_name), reply_markup=confirm_set_default_language_keyboard(lang_code, i18n, locale), )
    await call.answer()

#! Финальное подтверждение и выполнение действия
@router.callback_query(F.data.startswith("confirm_set_default_lang:"), StateFilter(AdminSettingsStates.confirming_default_language))
async def confirm_and_set_default_language(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
    lang_code = call.data.split(":")[1]
    data = await state.get_data()
    lang_name = data.get("lang_name", lang_code)
    updated_count = Userx.set_default_language_if_null(lang_code)
    await call.message.edit_text(i18n.get_text("admin_settings_main.switches_title", locale),reply_markup=settings_status_finl(call.from_user.id, i18n, locale),)
    await call.answer(i18n.get_text("default_specific_lang_set_success", locale, lang_name=lang_name, count=updated_count),show_alert=True,)
    await state.clear()

#! Отмена на любом этапе
@router.callback_query(F.data == "back_to_switches", StateFilter("*"))
async def cancel_set_default_language(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
    await state.clear()
    await call.message.edit_text(i18n.get_text("admin_settings_main.switches_title", locale),reply_markup=settings_status_finl(call.from_user.id, i18n, locale),)
    await call.answer(i18n.get_text("default_lang_set_cancelled", locale))

    #!###############################################################################
#! УПРАВЛЕНИЕ ЛИМИТОМ АВТО-АВТОРИЗАЦИИ
@router.callback_query(F.data == "settings_edit_auto_auth_limit", IsAdmin())
async def edit_auto_auth_limit_start(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
    await state.set_state(AdminSettingsStates.waiting_for_auto_auth_limit)
    await call.message.edit_text(i18n.get_text("admin_settings.auto_auth_limit_prompt", locale))
    await call.answer()

@router.message(StateFilter(AdminSettingsStates.waiting_for_auto_auth_limit))
async def process_auto_auth_limit(message: Message, state: FSM, i18n: Translator, locale: str):
    try:
        new_limit = int(message.text.strip().replace(',', '.'))
        if new_limit < 0:
            raise ValueError("Limit cannot be negative")
    except ValueError:
        await message.answer(i18n.get_text("admin_settings.auto_auth_limit_error", locale))
        return

    Settingsx.update(auto_auth_refill_limit=new_limit)
    await state.clear()
    
    await message.answer(
        i18n.get_text("admin_settings.auto_auth_limit_updated", locale, limit=new_limit)
    )
    # Возвращаем в меню "Выключатели"
    await message.answer(
        i18n.get_text("admin_settings_main.switches_title", locale),
        reply_markup=settings_status_finl(message.from_user.id, i18n, locale),
    )

#!###############################################################################
#! УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ КАНАЛА
@router.message(I18nText("reply_admin.promote_admin_in_channel"), IsAdmin())
async def channel_promote_admin_start(message: Message, state: FSM, i18n: Translator, locale: str):
    channels = Channelx.get_all()
    if not channels:
        await message.answer(i18n.get_text("admin_settings.channel_list_empty", locale))
        return

    builder = InlineKeyboardBuilder()
    for channel in channels:
        builder.button(
            text=channel.channel_name or str(channel.channel_id),
            callback_data=f"select_channel_for_promote:{channel.channel_id}"
        )
    builder.adjust(1)
    
    await state.set_state(AdminSettingsStates.waiting_for_channel_to_promote_in)
    await message.answer(
        i18n.get_text("admin_settings.promote_select_channel", locale),
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("select_channel_for_promote:"), StateFilter(AdminSettingsStates.waiting_for_channel_to_promote_in))
async def select_channel_for_promotion(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
    channel_id = int(call.data.split(":")[1])
    await state.update_data(channel_id_to_promote_in=channel_id)
    await state.set_state(AdminSettingsStates.waiting_for_user_to_promote)
    await call.message.edit_text(i18n.get_text("admin_settings.promote_enter_user", locale))

@router.message(StateFilter(AdminSettingsStates.waiting_for_user_to_promote))
async def process_user_for_promotion(message: Message, state: FSM, bot: Bot, i18n: Translator, locale: str):
    user_id = 0
    if message.forward_from:
        user_id = message.forward_from.id
    elif message.text and message.text.isdigit():
        user_id = int(message.text)
    
    if not user_id:
        await message.answer(i18n.get_text("admin_settings.promote_invalid_input", locale))
        return

    data = await state.get_data()
    channel_id = data.get("channel_id_to_promote_in")

    try:
        chat_member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        if chat_member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
             await message.answer(i18n.get_text("admin_settings.promote_user_not_in_channel", locale, user_id=user_id))
             return
    except Exception:
        await message.answer(i18n.get_text("admin_settings.promote_user_not_found", locale, user_id=user_id))
        return

    permissions = {
        "can_manage_chat": False, "can_delete_messages": False, "can_manage_video_chats": False,
        "can_restrict_members": False, "can_promote_members": False, "can_change_info": False,
        "can_invite_users": False, "can_post_messages": False, "can_edit_messages": False,
        "can_pin_messages": False, "can_manage_topics": False,
    }

    await state.update_data(promote_user_id=user_id, permissions=permissions)
    await state.set_state(AdminSettingsStates.selecting_admin_permissions)
    
    await message.answer(
        i18n.get_text("admin_settings.promote_select_permissions", locale, user_id=user_id),
        reply_markup=channel_admin_permissions_finl(permissions, i18n, locale)
    )

@router.callback_query(F.data.startswith("toggle_perm:"), StateFilter(AdminSettingsStates.selecting_admin_permissions))
async def toggle_permission(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
    perm_key = call.data.split(":")[1]
    data = await state.get_data()
    permissions = data.get("permissions", {})
    
    permissions[perm_key] = not permissions.get(perm_key, False)
    
    await state.update_data(permissions=permissions)
    await call.message.edit_reply_markup(reply_markup=channel_admin_permissions_finl(permissions, i18n, locale))
    await call.answer()

@router.callback_query(F.data == "cancel_promotion", StateFilter(AdminSettingsStates.selecting_admin_permissions))
async def cancel_promotion(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
    await state.clear()
    await call.message.edit_text(i18n.get_text("admin_settings.promote_cancelled", locale))
    await manage_subscription_channels(call.message, i18n, locale)


@router.callback_query(F.data == "confirm_promotion", StateFilter(AdminSettingsStates.selecting_admin_permissions))
async def confirm_promotion(call: CallbackQuery, state: FSM, bot: Bot, i18n: Translator, locale: str):
    data = await state.get_data()
    user_id_to_promote = data.get("promote_user_id")
    permissions = data.get("permissions", {})
    channel_id = data.get("channel_id_to_promote_in")

    try:
        await bot.promote_chat_member(
            chat_id=channel_id,
            user_id=user_id_to_promote,
            **permissions
        )
        await call.message.edit_text(i18n.get_text("admin_settings.promote_success", locale, user_id=user_id_to_promote))
    except Exception as e:
        await call.message.edit_text(i18n.get_text("admin_settings.promote_error", locale, error=str(e)))
        bot_logger.error(f"Failed to promote user {user_id_to_promote} in chat {channel_id}: {e}")

    await state.clear()

