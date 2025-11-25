# shop/tgbot/routers/admin/admin_products.py

import math
import asyncio
import os
import html
from aiogram import Router, Bot, F
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message, User, FSInputFile, Union
from aiogram.utils.keyboard import InlineKeyboardBuilder
from tgbot.database import Categoryx, Itemx, Positionx, Subcategoryx, PositionModel, ItemModel, Userx
from tgbot.keyboards.inline_helper import build_advanced_pagination
from tgbot.keyboards.inline_admin_page import (
    position_edit_category_swipe_fp,
    category_edit_swipe_fp,
    subcategory_edit_swipe_fp,
    subcategory_add_swipe_fp,
    #position_add_swipe_fp,
    position_add_subcategory_swipe_fp,
    position_add_category_swipe_fp,
    position_edit_subcategory_swipe_fp,
    position_edit_swipe_fp,
    item_add_position_swipe_fp,
    item_add_category_swipe_fp,
    item_add_subcategory_swipe_fp,
    item_add_position_by_subcategory_swipe_fp,
)
from tgbot.keyboards.inline_admin_products import (
    category_edit_delete_finl,
    category_edit_cancel_finl,
    position_edit_clear_finl,
    position_edit_delete_finl,
    position_edit_cancel_finl,
    products_removes_finl,
    products_removes_categories_finl,
    products_removes_subcategories_finl,
    products_removes_positions_finl,
    products_removes_items_finl,
    item_add_finish_finl,
    subcategory_edit_delete_finl,
)
from tgbot.keyboards.reply_main import items_frep
from tgbot.services.i18n import Translator
from tgbot.utils.misc.i18n_filters import I18nText
from tgbot.utils.const_functions import (
    is_number,
    to_number,
    del_message,
    ded,
    get_unix,
    clear_html,
    send_admins,
    get_date,
)
from tgbot.utils.misc.bot_logging import bot_logger
from tgbot.utils.misc.bot_models import FSM, ARS
from tgbot.utils.misc_functions import save_and_compress_photo

from tgbot.utils.text_functions import (
    category_open_admin,
    position_open_admin,
    item_open_admin,
    subcategory_open_admin,
)
from tgbot.data.config import BASE_DIR, get_admins, get_operators
from tgbot.utils.misc.bot_filters import IsAdmin
from tgbot.database.db_executor import run_db_operation
from urllib.parse import urlencode


router = Router(name=__name__)

# Лимит символов Telegram (с запасом)
TELEGRAM_MSG_LIMIT = 4000



# функция для отправки уведомлений о массовом удалении ---
async def _send_mass_delete_notification(
    bot: Bot,
    admin_user: User,
    date: str,
    deletion_type: str,  # Например, "Все категории", "Все товары"
    totals: dict,  # Словарь с итогами {'Категорий': N, 'Товаров': M, ...}
    entities_details: list[str],  # Полный список строк с деталями сущностей
    not_me: int,
    i18n: Translator,
    locale: str,
):
    """Формирует и отправляет уведомление о массовом удалении, разбивая на части при необходимости."""
    admin_mention = (
        f"@{admin_user.username}" if admin_user.username else f"{admin_user.full_name}"
    )

    # Формируем строку с итогами
    totals_lines = [f"   - {key}: {value}" for key, value in totals.items()]
    totals_str = "\n".join(totals_lines)

    # Формируем базовую часть (заголовок)
    base_text = ded(
        i18n.get_text(
            "admin_products.mass_delete_notification.title",
            locale,
            deletion_type=deletion_type,
        )
        + "\n\n"
        + i18n.get_text(
            "admin_products.add_items_finish_notification_admin",
            locale,
            admin_mention=admin_mention,
            admin_id=admin_user.id,
        )
        + "\n"
        + i18n.get_text(
            "admin_products.add_items_finish_notification_date",
            locale,
            date = date,
        )
        + "\n\n"
        + i18n.get_text("admin_products.mass_delete_notification.total_deleted", locale)
        + "\n"
        + totals_str
        + "\n\n"
        + i18n.get_text(
            "admin_products.mass_delete_notification.deleted_entities", locale
        )
        + "\n"
    )

    current_message = base_text
    for entity_line in entities_details:
        line_to_add = entity_line + "\n"
        if len(current_message) + len(line_to_add) > TELEGRAM_MSG_LIMIT:
            await send_admins(bot, current_message, not_me=not_me)
            current_message = (
                i18n.get_text(
                    "admin_products.log_mass_delete_notification_continuation", locale
                )
                + line_to_add
            )
        else:
            current_message += line_to_add

    if current_message and (len(current_message) > len(base_text) or entities_details):
        await send_admins(bot, current_message, not_me=not_me)
    elif not entities_details:
        await send_admins(
            bot,
            base_text
            + i18n.get_text(
                "admin_products.mass_delete_notification.no_data_to_delete", locale
            ),
            not_me=not_me,
        )


# --- Конец новой общей функции ---


#! Создание новой категории
@router.message(I18nText("reply_admin.create_category"))
async def prod_category_add(message: Message, state: FSM, i18n: Translator, locale: str):
    await state.clear()
    await state.set_state("here_category_name")
    await message.answer(i18n.get_text("admin_products.create_category_prompt", locale))


#! Выбор категории для редактирования
@router.message(I18nText("reply_admin.edit_category"))
async def prod_category_edit(message: Message, state: FSM, i18n: Translator, locale: str):
    await state.clear()
    if len(Categoryx.get_all()) >= 1:
        await message.answer(i18n.get_text("admin_products.edit_category_prompt", locale),reply_markup=category_edit_swipe_fp(0, i18n, locale),)
    else:
        await message.answer(i18n.get_text("admin_products.no_categories_to_edit", locale))


#! Создание новой позиции
@router.message(I18nText("reply_admin.create_position"))
async def prod_position_add(message: Message, state: FSM, i18n: Translator, locale: str):
    await state.clear()

    # Проверяем, есть ли вообще категории с подкатегориями
    all_subcategories = Subcategoryx.get_all()
    if not all_subcategories:
        await message.answer(i18n.get_text("admin_products.no_subcategories_for_position", locale))
        return

    await message.answer(i18n.get_text("admin_products.create_position_select_category_prompt", locale),reply_markup=position_add_category_swipe_fp(0, i18n, locale),)

#! Обработчик кнопки "Назад" к выбору категории
@router.callback_query(F.data == "back_to_pos_add_cat_select")
async def back_to_category_selection_for_pos_add(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
    await call.message.edit_text(i18n.get_text("admin_products.create_position_select_category_prompt", locale),reply_markup=position_add_category_swipe_fp(0, i18n, locale),)
    
#! Пагинация для выбора категории
@router.callback_query(F.data.startswith("pos_add_swipe_cat:"))
async def prod_position_add_cat_swipe(call: CallbackQuery, i18n: Translator, locale: str):
    remover = int(call.data.split(":")[1])
    await call.message.edit_text(i18n.get_text("admin_products.create_position_select_category_prompt", locale),reply_markup=position_add_category_swipe_fp(remover, i18n, locale),)    

#! Шаг 2: Обработка выбора категории (показ подкатегорий)
@router.callback_query(F.data.startswith("pos_add_select_cat:"))
async def prod_position_select_category(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
    category_id, remover = map(int, call.data.split(":")[1:])
    await call.message.edit_text(i18n.get_text("admin_products.create_position_prompt", locale),reply_markup=position_add_subcategory_swipe_fp(remover, category_id, i18n, locale),)
    await call.answer()

#! Шаг 3: Выбор подкатегории и переход к вводу данных
@router.callback_query(F.data.startswith("position_add_open:"))
async def prod_position_add_open(call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str):
    data = call.data.split(":")
    subcategory_id = int(data[1])

    get_subcategory = Subcategoryx.get(subcategory_id=subcategory_id)
    if not get_subcategory:
        await call.answer(i18n.get_text("admin_products.subcategory_not_found", locale), True)
        return

    category_id = get_subcategory.category_id
    await state.update_data(here_category_id=category_id, here_subcategory_id=subcategory_id)
    await state.set_state("here_position_name")

    await call.message.edit_text(i18n.get_text("admin_products.enter_position_name", locale))

#! Выбор позиции для редактирования
@router.message(I18nText("reply_admin.edit_position"))
@router.callback_query(F.data == "prod_position_edit_start") # Также для кнопки "Назад"
async def prod_position_edit(message: Union[Message, CallbackQuery], state: FSM, i18n: Translator, locale: str):
    """#! ШАГ 1: Показывает список категорий для выбора."""
    await state.clear()
    #! Определяем, откуда пришел запрос - от сообщения или колбэка
    target_message = message if isinstance(message, Message) else message.message
    edit_mode = isinstance(message, CallbackQuery)
    #! Проверяем, есть ли вообще категории с позициями
    all_positions = Positionx.get_all()
    if not all_positions:
        text = i18n.get_text("admin_products.no_positions_to_edit", locale)
        if edit_mode:
            await message.answer(text, show_alert=True)
        else:
            await target_message.answer(text)
        return
    text = i18n.get_text("admin_products.create_position_select_category_prompt", locale)
    reply_markup = position_edit_category_swipe_fp(0, i18n, locale)
    if edit_mode:
        await target_message.edit_text(text, reply_markup=reply_markup)
    else:
        await target_message.answer(text, reply_markup=reply_markup)


    #! НОВЫЙ ХЕНДЛЕР
@router.callback_query(F.data.startswith("pos_edit_cat_swipe:"))
async def prod_position_edit_cat_swipe(call: CallbackQuery, i18n: Translator, locale: str):
    """#! Пагинация для выбора категории."""
    remover = int(call.data.split(":")[1])
    await call.message.edit_text(i18n.get_text("admin_products.create_position_select_category_prompt", locale), reply_markup=position_edit_category_swipe_fp(remover, i18n, locale),)

#! НОВЫЙ ХЕНДЛЕР
@router.callback_query(F.data.startswith("pos_edit_select_cat:"))
async def prod_position_select_category(call: CallbackQuery, i18n: Translator, locale: str):
    """#! ШАГ 2: Принимает категорию и показывает список подкатегорий."""
    _, category_id_str, remover_str = call.data.split(":")
    category_id = int(category_id_str)
    remover = int(remover_str)
    await call.message.edit_text(i18n.get_text("admin_products.create_position_prompt", locale), reply_markup=position_edit_subcategory_swipe_fp(remover, category_id, i18n, locale), )

#! НОВЫЙ ХЕНДЛЕР
@router.callback_query(F.data.startswith("pos_edit_select_subcat:"))
async def prod_position_select_subcategory(call: CallbackQuery, i18n: Translator, locale: str):
    """#! ШАГ 3: Принимает подкатегорию и показывает список позиций."""
    _, category_id_str, subcategory_id_str, remover_str = call.data.split(":")
    category_id = int(category_id_str)
    subcategory_id = int(subcategory_id_str)
    remover = int(remover_str)
    get_subcategory = Subcategoryx.get(subcategory_id=subcategory_id)
    await call.message.edit_text(i18n.get_text( "admin_products.select_position_from_subcategory", locale, subcategory_name=get_subcategory.subcategory_name, ), reply_markup=position_edit_swipe_fp(remover, i18n, locale, category_id, subcategory_id), )



# Страницы товаров для добавления
@router.message(I18nText("reply_admin.add_items"))
async def prod_item_add(message: Message, state: FSM, i18n: Translator, locale: str):
    await state.clear()
    get_categories = Categoryx.get_all()
    if len(get_categories) >= 1:
        await message.answer(
            i18n.get_text("admin_products.select_category_for_items", locale),
            reply_markup=item_add_category_swipe_fp(0, i18n, locale),
        )
    else:
        await message.answer(
            i18n.get_text("admin_products.no_categories_for_items", locale)
        )


# Удаление категорий, позиций или товаров
@router.message(I18nText("reply_admin.mass_delete"))
async def prod_removes(message: Message, state: FSM, i18n: Translator, locale: str):
    await state.clear()
    await message.answer(
        i18n.get_text("admin_products.mass_delete_return_prompt", locale),
        reply_markup=products_removes_finl(i18n, locale),
    )


# СОЗДАНИЕ КАТЕГОРИИ #
# Принятие названия категории для её создания
@router.message(F.text, StateFilter("here_category_name"))
async def prod_category_add_name_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    if len(message.text) > 50:
        return await message.answer(
            i18n.get_text("admin_products.error_name_too_long_50", locale)
            + i18n.get_text("admin_products.enter_new_category_name", locale),
        )
    await state.clear()
    category_id = get_unix()
    Categoryx.add(category_id=category_id, category_name=clear_html(message.text))
    # Передаем i18n и locale в следующую функцию
    await category_open_admin(bot, message.from_user.id, category_id, 0, i18n, locale)


# ИЗМЕНЕНИЕ КАТЕГОРИИ #
# Страница выбора категорий для редактирования
@router.callback_query(F.data.startswith("category_edit_swipe:"))
async def prod_category_edit_swipe(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    remover = int(call.data.split(":")[1])
    await call.message.edit_text(
        i18n.get_text("admin_products.edit_category_prompt", locale),
        # Передаем i18n и locale в функцию создания клавиатуры
        reply_markup=category_edit_swipe_fp(remover, i18n, locale),
    )


# Выбор текущей категории для редактирования
@router.callback_query(F.data.startswith("category_edit_open:"))
async def prod_category_edit_open(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id = int(call.data.split(":")[1])
    remover = int(call.data.split(":")[2])
    await state.clear()
    await del_message(call.message)
    # Передаем i18n и locale в следующую функцию
    await category_open_admin(
        bot, call.from_user.id, category_id, remover, i18n, locale
    )


# САМО ИЗМЕНЕНИЕ КАТЕГОРИИ #
# Изменение названия категории
@router.callback_query(F.data.startswith("category_edit_name:"))
async def prod_category_edit_name(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id = int(call.data.split(":")[1])
    remover = int(call.data.split(":")[2])
    await state.update_data(here_category_id=category_id)
    await state.update_data(here_remover=remover)
    await state.set_state("here_category_edit_name")
    await del_message(call.message)
    await call.message.answer(
        i18n.get_text("admin_products.enter_new_category_name", locale),
        # Передаем i18n и locale в функцию создания клавиатуры
        reply_markup=category_edit_cancel_finl(category_id, remover, i18n, locale),
    )


# Принятие нового названия для категории
@router.message(F.text, StateFilter("here_category_edit_name"))
async def prod_category_edit_name_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id = (await state.get_data())["here_category_id"]
    remover = (await state.get_data())["here_remover"]
    if len(message.text) > 50:
        return await message.answer(
            i18n.get_text("admin_products.error_name_too_long_50", locale)
            + i18n.get_text("admin_products.enter_new_category_name", locale),
            # Передаем i18n и locale в функцию создания клавиатуры
            reply_markup=category_edit_cancel_finl(category_id, remover, i18n, locale),
        )
    await state.clear()
    Categoryx.update(category_id=category_id, category_name=clear_html(message.text))
    # Передаем i18n и locale в следующую функцию
    await category_open_admin(
        bot, message.from_user.id, category_id, remover, i18n, locale
    )


# Окно с уточнением удалить категорию
@router.callback_query(F.data.startswith("category_edit_delete:"))
async def prod_category_edit_delete(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id = int(call.data.split(":")[1])
    remover = int(call.data.split(":")[2])

    # Получаем информацию о категории
    category = Categoryx.get(category_id=category_id)

    # Получаем все подкатегории
    subcategories = Subcategoryx.gets(category_id=category_id)
    subcategories_text = "\n".join(
        [f" - {sub.subcategory_name}" for sub in subcategories]
    )

    # Получаем все позиции
    positions = Positionx.gets(category_id=category_id)
    positions_text = "\n".join([f" - {pos.position_name}" for pos in positions])

    # Получаем количество товаров
    items_count = len(Itemx.gets(category_id=category_id))

    # Формируем сообщение из словаря i18n
    message_text = i18n.get_text(
        "admin_products.confirm_delete_category_prompt",
        locale,
        subcategories_count=len(subcategories),
        subcategories_text=subcategories_text,
        positions_count=len(positions),
        positions_text=positions_text,
        items_count=items_count,
    )

    await call.message.edit_text(
        ded(message_text),  # ded() остается для очистки отступов
        reply_markup=category_edit_delete_finl(category_id, remover, i18n, locale),
    )


# Подтверждение удаления категории
@router.callback_query(F.data.startswith("category_edit_delete_confirm:"))
async def prod_category_edit_delete_confirm(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id = int(call.data.split(":")[1])
    remover = int(call.data.split(":")[2])

    admin_user = call.from_user
    date = get_date()

    category_to_delete = Categoryx.get(category_id=category_id)
    if not category_to_delete:
        await call.answer(
            i18n.get_text("admin_products.category_already_deleted", locale),
            show_alert=True,
        )
        try:
            await call.message.delete()
        except:
            pass
        return

    category_name = category_to_delete.category_name
    deleted_entities_details = []
    total_items = 0
    total_positions = 0

    subcategories_to_delete = Subcategoryx.gets(category_id=category_id)
    total_subcategories = len(subcategories_to_delete)

    if not subcategories_to_delete:
        deleted_entities_details.append(
            f"  {i18n.get_text('admin_products.log_mass_delete_subcategory_part', locale)}"
        )
    else:
        for subcategory in subcategories_to_delete:
            sub_str = f"  📁 {subcategory.subcategory_name}"
            deleted_entities_details.append(sub_str)
            positions_in_sub = Positionx.gets(subcategory_id=subcategory.subcategory_id)
            total_positions += len(positions_in_sub)

            if not positions_in_sub:
                deleted_entities_details.append(
                    f"    {i18n.get_text('admin_products.log_mass_delete_position_part', locale)}"
                )
            else:
                for position in positions_in_sub:
                    items_in_pos = Itemx.gets(position_id=position.position_id)
                    items_count = len(items_in_pos)
                    total_items += items_count
                    pos_str = (
                        f"    📦 {position.position_name} (Товаров: {items_count})"
                    )
                    deleted_entities_details.append(pos_str)

                    if items_in_pos:
                        for item in items_in_pos:
                            deleted_entities_details.append(f"      - {item.item_data}")
                    elif items_count == 0:
                        deleted_entities_details.append(
                            f"      {i18n.get_text('admin_products.export_items_no_items', locale)}"
                        )

    # Отправляем уведомление другим администраторам
    await _send_mass_delete_notification(
        bot=bot,
        admin_user=admin_user,
        date = date,
        deletion_type=i18n.get_text("admin_products.log_mass_delete_category", locale),
        totals={
            "Category": 1,
            "Subcategory": total_subcategories,
            "Positions": total_positions,
            "Items": total_items,
        },
        entities_details=deleted_entities_details,
        not_me=admin_user.id,
        i18n=i18n,
        locale=locale,
    )

    # Непосредственное удаление данных
    subcategories_final_check = Subcategoryx.gets(category_id=category_id)
    for subcategory in subcategories_final_check:
        positions_final_check = Positionx.gets(
            subcategory_id=subcategory.subcategory_id
        )
        for position in positions_final_check:
            Itemx.delete(position_id=position.position_id)
        Positionx.delete(subcategory_id=subcategory.subcategory_id)
    Subcategoryx.delete(category_id=category_id)
    Categoryx.delete(category_id=category_id)

    await call.answer(
        i18n.get_text(
            "admin_products.category_delete_success_answer",
            locale,
            category_name=category_name,
            subcategories_count=total_subcategories,
            total_positions=total_positions,
            total_items=total_items,
        ),
        show_alert=True,
    )

    # Возврат к списку категорий
    get_categories_after_delete = Categoryx.get_all()
    if len(get_categories_after_delete) >= 1:
        await call.message.edit_text(
            i18n.get_text("admin_products.edit_category_prompt", locale),
            reply_markup=category_edit_swipe_fp(remover, i18n, locale),
        )
    else:
        await call.message.edit_text(
            i18n.get_text("admin_products.no_more_categories", locale)
        )


################################################################################
############################### ДОБАВЛЕНИЕ ПОЗИЦИИ #############################
# Cтраницы выбора категорий для расположения позиции
@router.callback_query(F.data.startswith("position_add_swipe:"))
async def prod_position_add_swipe(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    remover = int(call.data.split(":")[1])

    await call.message.edit_text(
        i18n.get_text("admin_products.create_position_select_category_prompt", locale),
        reply_markup=position_add_category_swipe_fp(remover, i18n, locale),
    )


# Выбор подкатегории для создания позиции
@router.callback_query(F.data.startswith("position_add_open:"))
async def prod_position_add_open(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    data = call.data.split(":")
    subcategory_id = int(data[1])

    get_subcategory = Subcategoryx.get(subcategory_id=subcategory_id)
    if not get_subcategory:
        await call.answer(
            i18n.get_text("admin_products.subcategory_not_found", locale), True
        )
        return

    category_id = get_subcategory.category_id

    await state.update_data(
        here_category_id=category_id, here_subcategory_id=subcategory_id
    )
    await state.set_state("here_position_name")

    await call.message.edit_text(
        i18n.get_text("admin_products.enter_position_name", locale)
    )


# Принятие названия для создания позиции
@router.message(F.text, StateFilter("here_position_name"))
async def prod_position_add_name_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    if len(message.text) > 50:
        return await message.answer(
            i18n.get_text("admin_products.error_name_too_long_50", locale)
            + i18n.get_text("admin_products.enter_position_name", locale),
        )

    await state.update_data(here_position_name=clear_html(message.text))
    await state.set_state("here_position_price")

    await message.answer(i18n.get_text("admin_products.enter_position_price", locale))


# Принятие цены позиции для её создания
@router.message(F.text, StateFilter("here_position_price"))
async def prod_position_add_price_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    if not is_number(message.text):
        return await message.answer(
            i18n.get_text("admin_products.error_price_invalid", locale)
        )

    if to_number(message.text) > 10_000_000 or to_number(message.text) < 0:
        return await message.answer(
            i18n.get_text("admin_products.error_price_out_of_range", locale)
        )

    await state.update_data(here_position_price=to_number(message.text))
    await state.set_state("here_position_desc")
    await message.answer(
        i18n.get_text("admin_products.enter_position_description", locale)
    )


# Принятие описания позиции для её создания
@router.message(F.text, StateFilter("here_position_desc"))
async def prod_position_add_desc_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    if len(message.text) > 1200:
        return await message.answer(
            i18n.get_text("admin_products.error_description_too_long_1200", locale)
        )
    try:
        position_desc = message.text if message.text != "0" else "None"
        if position_desc != "None":
            # Проверяем синтаксис HTML, не сохраняя сообщение
            await bot.send_message(message.chat.id, position_desc, parse_mode="HTML")
            await bot.delete_message(message.chat.id, message.message_id + 1)
    except Exception:
        return await message.answer(
            ded(i18n.get_text("admin_products.error_html_syntax", locale))
        )

    # ---СРАЗУ СОЗДАЕМ ПОЗИЦИЮ ---
    state_data = await state.get_data()
    position_id = get_unix()

    Positionx.add(
        category_id=state_data["here_category_id"],
        subcategory_id=state_data["here_subcategory_id"],
        position_id=position_id,
        position_name=clear_html(state_data["here_position_name"]),
        position_price=to_number(state_data["here_position_price"]),
        position_desc=position_desc,
        position_photo="None",  # Фото всегда "None"
    )
    await state.clear()
    await position_open_admin(bot, message.from_user.id, position_id, i18n, locale)


################################################################################
############################### ИЗМЕНЕНИЕ ПОЗИЦИИ ##############################
# Перемещение по страницам категорий для редактирования позиции
@router.callback_query(F.data.startswith("position_edit_category_swipe:"))
async def prod_position_edit_category_swipe(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    remover = int(call.data.split(":")[1])
    await call.message.edit_text(
        i18n.get_text("admin_products.edit_position_prompt", locale),
        reply_markup=position_edit_subcategory_swipe_fp(remover, i18n, locale),
    )


# Выбор категории с нужной позицией
@router.callback_query(F.data.startswith("position_edit_category_open:"))
async def prod_position_edit_category_open(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id = int(call.data.split(":")[1])
    get_category = Categoryx.get(category_id=category_id)
    get_subcategory = Subcategoryx.get(category_id=category_id)
    get_positions = Positionx.gets(category_id=category_id)
    if len(get_positions) >= 1:
        await call.message.edit_text(
            i18n.get_text("admin_products.edit_position_prompt", locale),
            reply_markup=position_edit_swipe_fp(0, i18n, locale, category_id),
        )
    else:
        await call.answer(
            i18n.get_text(
                "admin_products.no_positions_in_category",
                locale,
                category_name=get_category.category_name,
            )
        )


# Перемещение по страницам позиций для редактирования позиции
@router.callback_query(F.data.startswith("position_edit_swipe:"))
async def prod_position_edit_swipe(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    remover = int(call.data.split(":")[1])
    await del_message(call.message)
    await call.message.answer(
        i18n.get_text("admin_products.edit_position_prompt", locale),
        reply_markup=position_edit_swipe_fp(remover, i18n, locale),
    )


# Выбор позиции для редактирования
@router.callback_query(F.data.startswith("position_edit_open:"))
async def prod_position_edit_open(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    position_id = int(call.data.split(":")[1])
    await state.clear()
    await del_message(call.message)
    await position_open_admin(bot, call.from_user.id, position_id, i18n, locale)


############################ САМО ИЗМЕНЕНИЕ ПОЗИЦИИ ############################
# Изменение названия позиции
@router.callback_query(F.data.startswith("position_edit_name:"))
async def prod_position_edit_name(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id, position_id, remover = map(int, call.data.split(":")[1:])
    await state.update_data(
        here_position_id=position_id, here_category_id=category_id, here_remover=remover
    )
    await state.set_state("here_position_edit_name")
    await del_message(call.message)
    await call.message.answer(
        i18n.get_text("admin_products.enter_new_position_name", locale),
        reply_markup=position_edit_cancel_finl(
            position_id, category_id, remover, i18n, locale
        ),
    )


# Принятие названия позиции для её изменения
@router.message(F.text, StateFilter("here_position_edit_name"))
async def prod_position_edit_name_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    state_data = await state.get_data()
    position_id, category_id, remover = (
        state_data["here_position_id"],
        state_data["here_category_id"],
        state_data["here_remover"],
    )

    if len(message.text) > 50:
        return await message.answer(
            i18n.get_text("admin_products.error_name_too_long_50", locale)
            + i18n.get_text("admin_products.enter_new_position_name", locale),
            reply_markup=position_edit_cancel_finl(
                position_id, category_id, remover, i18n, locale
            ),
        )

    await state.clear()
    Positionx.update(position_id=position_id, position_name=clear_html(message.text))
    await position_open_admin(bot, message.from_user.id, position_id, i18n, locale)


# Изменение цены позиции
@router.callback_query(F.data.startswith("position_edit_price:"))
async def prod_position_edit_price(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id, position_id, remover = map(int, call.data.split(":")[1:])
    await state.update_data(
        here_position_id=position_id, here_category_id=category_id, here_remover=remover
    )
    await state.set_state("here_position_edit_price")
    await del_message(call.message)
    await call.message.answer(
        i18n.get_text("admin_products.enter_new_position_price", locale),
        reply_markup=position_edit_cancel_finl(
            position_id, category_id, remover, i18n, locale
        ),
    )


# Принятие цены позиции для её изменения
@router.message(F.text, StateFilter("here_position_edit_price"))
async def prod_position_edit_price_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    state_data = await state.get_data()
    position_id, category_id, remover = (
        state_data["here_position_id"],
        state_data["here_category_id"],
        state_data["here_remover"],
    )

    if not is_number(message.text):
        return await message.answer(
            i18n.get_text("admin_products.error_price_invalid", locale),
            reply_markup=position_edit_cancel_finl(
                position_id, category_id, remover, i18n, locale
            ),
        )

    if to_number(message.text) > 10_000_000 or to_number(message.text) < 0:
        return await message.answer(
            i18n.get_text("admin_products.error_price_out_of_range", locale),
            reply_markup=position_edit_cancel_finl(
                position_id, category_id, remover, i18n, locale
            ),
        )

    await state.clear()
    Positionx.update(position_id=position_id, position_price=to_number(message.text))
    await position_open_admin(bot, message.from_user.id, position_id, i18n, locale)


# Изменение описания позиции
@router.callback_query(F.data.startswith("position_edit_desc:"))
async def prod_position_edit_desc(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id, position_id, remover = map(int, call.data.split(":")[1:])
    await state.update_data(
        here_position_id=position_id, here_category_id=category_id, here_remover=remover
    )
    await state.set_state("here_position_edit_desc")
    await del_message(call.message)
    await call.message.answer(
        ded(i18n.get_text("admin_products.enter_new_position_description", locale)),
        reply_markup=position_edit_cancel_finl(
            position_id, category_id, remover, i18n, locale
        ),
    )


# Принятие описания позиции для её изменения
@router.message(F.text, StateFilter("here_position_edit_desc"))
async def prod_position_edit_desc_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    state_data = await state.get_data()
    position_id, category_id, remover = (
        state_data["here_position_id"],
        state_data["here_category_id"],
        state_data["here_remover"],
    )

    if len(message.text) > 1200:
        return await message.answer(
            ded(
                i18n.get_text("admin_products.error_description_too_long_1200", locale)
            ),
            reply_markup=position_edit_cancel_finl(
                position_id, category_id, remover, i18n, locale
            ),
        )

    try:
        position_desc = message.text if message.text != "0" else "None"
        if position_desc != "None":
            await (await message.answer(position_desc)).delete()
    except:
        return await message.answer(
            ded(i18n.get_text("admin_products.error_html_syntax", locale)),
            reply_markup=position_edit_cancel_finl(
                position_id, category_id, remover, i18n, locale
            ),
        )

    await state.clear()
    Positionx.update(position_id=position_id, position_desc=position_desc)
    await position_open_admin(bot, message.from_user.id, position_id, i18n, locale)

#! Выгрузка товаров позиции
@router.callback_query(F.data.startswith("position_edit_items:"))
async def prod_position_edit_items(
    call: CallbackQuery, bot: Bot, state: FSM, arSession: ARS, i18n: Translator, locale: str
):
    # ! 1. Парсинг данных из колбэка
    data_parts = call.data.split(":")
    position_id = int(data_parts[1])
    current_page = int(data_parts[2]) if len(data_parts) > 2 else 1
    initiator_admin = call.from_user
    
    # ! 2. Получение данных и пагинация 
    all_items = Itemx.gets(position_id=position_id)
    if not all_items:
        return await call.answer(i18n.get_text("admin_products.no_items_in_position", locale), show_alert=True)
    
    await call.message.delete()
    items_per_page = 10
    start_index = (current_page - 1) * items_per_page
    items_to_show = all_items[start_index : start_index + items_per_page]

    # ! 3. Отправка товаров инициатору 
    for item in items_to_show:
        raw_data = item.item_data.strip()
        
        try:
            #! Сценарий 1: Если  это локальный файл
            if raw_data.startswith("media/items/"):
                full_path = BASE_DIR / raw_data
                caption = os.path.basename(raw_data)
                # Проверяем, существует ли файл, перед отправкой
                if os.path.exists(full_path):
                    await bot.send_photo(call.from_user.id, photo=FSInputFile(full_path), caption=caption)
                else:
                    # Если файл не найден, отправляем текстовое уведомление
                    bot_logger.warning(f"File not found for item {item.item_id}: {full_path}")
                    await bot.send_message(call.from_user.id, f"⚠️ Файл не найден: <code>{html.escape(raw_data)}</code>")

            #! Сценарий 2: Если - что-то другое (URL, текст и т.д.)
            else:
                # Отправляем сырые данные как текстовое сообщение в безопасном формате
                await bot.send_message(call.from_user.id, f"<code>{html.escape(raw_data)}</code>")
            
            await asyncio.sleep(0.1) # Задержка между отправками
            
        except Exception as e:
            # Общий обработчик ошибок на случай проблем с API Telegram
            await bot.send_message(call.from_user.id, f"⚠️ Не удалось отправить товар: <code>{html.escape(raw_data)}</code>\nОшибка: {e}")

    # ! 4. Уведомление другим администраторам 
    admin_mention = (
        f"@{initiator_admin.username} ID: {initiator_admin.id}"
        if initiator_admin.username else f"{initiator_admin.full_name}"
    )
    position = Positionx.get(position_id=position_id)
    notification_header = f"Администратор {admin_mention} выгрузил товары из позиции: <b>{position.position_name}</b>\nСтраница {current_page} из {math.ceil(len(all_items) / items_per_page)}"
    
    for admin_id in get_admins():
        if admin_id != initiator_admin.id:
            try:
                await bot.send_message(admin_id, notification_header)
                for item in items_to_show:
                    raw_data = item.item_data.strip()
                    if raw_data.startswith("media/items/"):
                        full_path = BASE_DIR / raw_data
                        caption = os.path.basename(raw_data)
                        if os.path.exists(full_path):
                            await bot.send_photo(admin_id, photo=FSInputFile(full_path), caption=caption)
                        else:
                            await bot.send_message(admin_id, f"⚠️ Файл не найден: <code>{html.escape(raw_data)}</code>")
                    else:
                        await bot.send_message(admin_id, f"<code>{html.escape(raw_data)}</code>")

                    await asyncio.sleep(0.1)
            except Exception as e:
                bot_logger.error(f"Couldn't send a review notification to the admin {admin_id}: {e}")

    # ! 5. Отправка клавиатуры пагинации 
    pagination_kb = build_advanced_pagination(i18n=i18n, locale=locale, total_items=len(all_items), current_page=current_page, items_per_page=items_per_page, callback_prefix=f"position_edit_items:{position_id}", back_callback=f"position_edit_open:{position_id}", )
    builder = InlineKeyboardBuilder()
    for row in pagination_kb:
        builder.row(*row)
    await call.message.answer( f"{current_page} / {math.ceil(len(all_items) / items_per_page)}", reply_markup=builder.as_markup(),)



async def _clear_position_and_notify_admins(
    bot: Bot,
    admin_user: User,
    position_id: int,
    notification_title: str, # Заголовок для уведомления (например, "Очистка Позиции")
    i18n: Translator,
    locale: str,
) -> tuple[int, str, str, str]:
    """ #! Универсальная функция для очистки товаров из позиции и уведомления администраторов.
    #! 1. Находит все товары в позиции.
    #! 2. Уведомляет других администраторов, отправляя фото или текст для каждого товара.
    #! 3. Удаляет все товары из таблицы `storage_item`.
    #! 4. Возвращает количество удаленных товаров и информацию о позиции.
    """
    date = get_date()
    items_to_delete = Itemx.gets(position_id=position_id)
    items_count = len(items_to_delete)
    
    position = Positionx.get(position_id=position_id)
    
    #! Собираем информацию для ответа и уведомлений
    category_name, subcategory_name = "Unknown Category", "Unknown Subcategory"
    position_name = position.position_name if position else "Unknown Position"
    
    if position:
        subcategory = Subcategoryx.get(subcategory_id=position.subcategory_id)
        if subcategory:
            subcategory_name = subcategory.subcategory_name
            category = Categoryx.get(category_id=subcategory.category_id)
            if category:
                category_name = category.category_name

    #! Уведомляем других администраторов, только если есть что удалять
    if items_count > 0:
        admin_mention = f"@{admin_user.username}" if admin_user.username else f"{admin_user.full_name}"

        for admin_id in get_admins():
            if admin_id != admin_user.id:
                try:
                    #! 1. Определяем язык администратора-получателя
                    recipient_admin = Userx.get(user_id=admin_id)
                    recipient_locale = "en" # Язык по умолчанию, если у админа не задан
                    if recipient_admin and recipient_admin.language_code:
                        recipient_locale = recipient_admin.language_code

                    act_title = i18n.get_text(notification_title, recipient_locale)
                    #! 2. Формируем заголовок на языке получателя
                    header_text = i18n.get_text(
                        "admin_products.admin_notification_position_action_header",
                        recipient_locale,
                        action_title=act_title,
                        admin_mention=admin_mention,
                        admin_id=admin_user.id,
                        date = date,
                        category_name=category_name,
                        subcategory_name=subcategory_name,
                        position_name=position_name,
                        items_count=items_count,
                    )

                    await bot.send_message(admin_id, header_text)

                    # 3. Отправляем товары, используя язык получателя для сообщений об ошибках
                    for item in items_to_delete:
                        raw_data = item.item_data.strip()
                        if raw_data.startswith("media/items/"):
                            full_path = BASE_DIR / raw_data
                            caption = os.path.basename(raw_data)
                            if os.path.exists(full_path):
                                await bot.send_photo(admin_id, photo=FSInputFile(full_path), caption=caption)
                            else:
                                error_text = i18n.get_text("admin_products.admin_notification_file_not_found", recipient_locale, file_path=html.escape(raw_data))
                                await bot.send_message(admin_id, error_text)
                        else:
                            await bot.send_message(admin_id, f"<code>{html.escape(raw_data)}</code>")
                        await asyncio.sleep(0.1)
                except Exception as e:
                    bot_logger.error(f"Couldn't send position action notification to admin {admin_id}: {e}")

    # Непосредственное удаление товаров из базы данных
    Itemx.delete(position_id=position_id)
    
    return items_count, position_name, category_name, subcategory_name




#! Удаление позиции
@router.callback_query(F.data.startswith("position_edit_delete:"))
async def prod_position_edit_delete(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id, position_id, remover = map(int, call.data.split(":")[1:])
    await del_message(call.message)
    await call.message.answer(
        i18n.get_text("admin_products.confirm_delete_position_prompt", locale),
        reply_markup=position_edit_delete_finl(
            position_id, category_id, remover, i18n, locale
        ),
    )


# Подтверждение удаления позиции
@router.callback_query(F.data.startswith("position_edit_delete_confirm:"))
async def prod_position_edit_delete_confirm(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id, position_id, remover = map(int, call.data.split(":")[1:])
    admin_user = call.from_user

    # ! 1. Вызываем универсальную функцию для очистки и уведомления 
    # Передаем заголовок "Удаление Позиции"
    #title_notify = i18n.get_text("admin_products.log_mass_delete_position", locale)
    items_count, position_name, category_name, subcategory_name = await _clear_position_and_notify_admins(
        bot, admin_user, position_id, "admin_products.log_mass_delete_position", i18n, locale
    )

    # ! 2. Выполняем уникальное действие - удаление самой позиции ---
    Positionx.delete(position_id=position_id)
    
    await call.answer(
        i18n.get_text(
            "admin_products.position_delete_success_answer",
            locale,
            position_name=position_name,
            items_count=items_count,
        ),
        show_alert=True,
    )

    # ! 3. Возврат к меню (логика не изменилась) ---
    position = Positionx.get(position_id=position_id) # Повторная проверка для навигации
    if len(Positionx.gets(category_id=category_id)) >= 1:
        target_subcategory_id = position.subcategory_id if position else None
        if target_subcategory_id and len(Positionx.gets(subcategory_id=target_subcategory_id)) >= 1:
            await call.message.edit_text(
                i18n.get_text("admin_products.select_position_from_subcategory", locale, subcategory_name=subcategory_name),
                reply_markup=item_add_position_by_subcategory_swipe_fp(0, category_id, target_subcategory_id, i18n, locale),
            )
            return
        if len(Subcategoryx.gets(category_id=category_id)) >= 1:
            get_category_obj = Categoryx.get(category_id=category_id)
            await call.message.edit_text(
                i18n.get_text("admin_products.select_subcategory_from_category", locale, category_name=get_category_obj.category_name),
                reply_markup=item_add_subcategory_swipe_fp(0, category_id, i18n, locale),
            )
            return
    
    await del_message(call.message)


#! Очистка позиции
@router.callback_query(F.data.startswith("position_edit_clear:"))
async def prod_position_edit_clear(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id, position_id, remover = map(int, call.data.split(":")[1:])
    await del_message(call.message)
    await call.message.answer(i18n.get_text("admin_products.confirm_clear_position_prompt", locale),reply_markup=position_edit_clear_finl(position_id, category_id, remover, i18n, locale),)


# Согласие очистки позиции
@router.callback_query(F.data.startswith("position_edit_clear_confirm:"))
async def prod_position_edit_clear_confirm(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id, position_id, remover = map(int, call.data.split(":")[1:])
    admin_user = call.from_user

    #!   1. Вызываем универсальную функцию
    #title_notify = i18n.get_text("admin_products.log_mass_clear_position")
    items_count, _, _, _ = await _clear_position_and_notify_admins(
        bot, admin_user, position_id, "admin_products.log_mass_clear_position", i18n, locale
    )

    # ! 2. позиция не удаляется 
    
    await call.answer(
        i18n.get_text(
            "admin_products.position_clear_success_answer", locale, count=items_count
        ),
        show_alert=True
    )

    # ! 3. Возвращаемся в меню редактирования очищенной позиции
    await del_message(call.message)
    await position_open_admin(bot, call.from_user.id, position_id, i18n, locale)



################################################################################
############################### ДОБАВЛЕНИЕ ТОВАРОВ #############################
# Перемещение по страницам категорий для добавления товаров
@router.callback_query(F.data.startswith("item_add_category_swipe:"))
async def prod_item_add_category_swipe(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    remover = int(call.data.split(":")[1])

    await call.message.edit_text(
        i18n.get_text("admin_products.select_category_for_items", locale),
        reply_markup=item_add_category_swipe_fp(remover, i18n, locale),
    )


# Выбор категории для добавления товаров (показываем подкатегории)
@router.callback_query(F.data.startswith("item_add_category_open:"))
async def prod_item_add_category_open(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id = int(call.data.split(":")[1])
    remover = int(call.data.split(":")[2])

    get_category = Categoryx.get(category_id=category_id)
    get_subcategories = Subcategoryx.gets(category_id=category_id)

    bot_logger.info(
        f"item_add_category_open: Выбрана категория {get_category.category_name} (ID: {category_id}). Найдено {len(get_subcategories)} подкатегорий."
    )

    if len(get_subcategories) >= 1:
        await call.message.edit_text(
            i18n.get_text(
                "admin_products.select_subcategory_from_category",
                locale,
                category_name=get_category.category_name,
            ),
            reply_markup=item_add_subcategory_swipe_fp(0, category_id, i18n, locale),
        )
    else:
        await call.answer(
            i18n.get_text(
                "admin_products.no_subcategories_in_category",
                locale,
                category_name=get_category.category_name,
            )
        )


# Пагинация подкатегорий для добавления товаров
@router.callback_query(F.data.startswith("item_add_subcategory_swipe:"))
async def prod_item_add_subcategory_swipe(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    data = call.data.split(":")
    category_id = int(data[1])
    remover = int(data[2]) if len(data) > 2 else 0

    get_category = Categoryx.get(category_id=category_id)

    await call.message.edit_text(
        i18n.get_text(
            "admin_products.select_subcategory_from_category",
            locale,
            category_name=get_category.category_name,
        ),
        reply_markup=item_add_subcategory_swipe_fp(remover, category_id, i18n, locale),
    )


# Выбор подкатегории для добавления товаров (показываем позиции)
@router.callback_query(F.data.startswith("item_add_subcategory_open:"))
async def prod_item_add_subcategory_open(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    data = call.data.split(":")
    category_id = int(data[1])
    subcategory_id = int(data[2])
    remover = int(data[3]) if len(data) > 3 else 0

    get_category = Categoryx.get(category_id=category_id)
    get_subcategory = Subcategoryx.get(subcategory_id=subcategory_id)
    get_positions = Positionx.gets(
        category_id=category_id, subcategory_id=subcategory_id
    )

    bot_logger.info(
        f"item_add_subcategory_open: Выбрана подкатегория {get_subcategory.subcategory_name} (ID: {subcategory_id}) из категории {get_category.category_name}. Найдено {len(get_positions)} позиций."
    )

    if len(get_positions) >= 1:
        await call.message.edit_text(
            i18n.get_text(
                "admin_products.select_position_from_subcategory",
                locale,
                subcategory_name=get_subcategory.subcategory_name,
            ),
            reply_markup=item_add_position_by_subcategory_swipe_fp(
                0, category_id, subcategory_id, i18n, locale
            ),
        )
    else:
        await call.answer(
            i18n.get_text(
                "admin_products.no_positions_in_subcategory",
                locale,
                subcategory_name=get_subcategory.subcategory_name,
            ),
            show_alert=True,
        )


# Пагинация позиций конкретной подкатегории для добавления товаров
@router.callback_query(F.data.startswith("item_add_position_by_subcategory_swipe:"))
async def prod_item_add_position_by_subcategory_swipe(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    data = call.data.split(":")
    category_id = int(data[1])
    subcategory_id = int(data[2])
    remover = int(data[3]) if len(data) > 3 else 0

    get_subcategory = Subcategoryx.get(subcategory_id=subcategory_id)

    await call.message.edit_text(
        i18n.get_text(
            "admin_products.select_position_from_subcategory",
            locale,
            subcategory_name=get_subcategory.subcategory_name,
        ),
        reply_markup=item_add_position_by_subcategory_swipe_fp(
            remover, category_id, subcategory_id, i18n, locale
        ),
    )


# Перемещение по страницам позиций для добавления товаров (старая версия, оставлена для обратной совместимости)
@router.callback_query(F.data.startswith("item_add_position_swipe:"))
async def prod_item_add_position_swipe(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    remover = int(call.data.split(":")[1])

    await call.message.edit_text(
        i18n.get_text("admin_products.select_position_for_items", locale),
        reply_markup=item_add_position_swipe_fp(remover, i18n, locale),
    )


# Добавления товаров после выбора позиции
@router.callback_query(F.data.startswith("item_add_position_open:"))
async def prod_item_add_position_open(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    data = call.data.split(":")
    position_id = int(data[1])

    position = Positionx.get(position_id=position_id)
    if not position:
        await call.answer(
            i18n.get_text("admin_products.position_not_found", locale), True
        )
        return

    category_id = position.category_id
    subcategory_id = position.subcategory_id

    await state.update_data(
        here_add_item_position_id=position_id,
        here_add_item_category_id=category_id,
        here_add_item_subcategory_id=subcategory_id,
        here_add_item_count=0,
    )
    await state.set_state("here_add_items")

    await del_message(call.message)

    await call.message.answer(
        ded(i18n.get_text("admin_products.add_items_data_prompt", locale)),
        reply_markup=item_add_finish_finl(position_id, i18n, locale),
    )


# Завершение загрузки товаров
@router.callback_query(
    F.data.startswith("item_add_position_finish:"), flags={"rate": 0}
)
async def prod_item_add_finish(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    position_id = int(call.data.split(":")[1])

    try:
        count_items = (await state.get_data())["here_add_item_count"]
    except:
        count_items = 0

    await state.clear()
    await call.message.edit_reply_markup()

    if count_items > 0:
        position = Positionx.get(position_id=position_id)
        if position:
            subcategory = Subcategoryx.get(subcategory_id=position.subcategory_id)
            category = Categoryx.get(category_id=position.category_id)

            category_name = (
                category.category_name
                if category
                else i18n.get_text("admin_menu_main.no_category", locale)
            )
            subcategory_name = (
                subcategory.subcategory_name
                if subcategory
                else i18n.get_text("common.no_subcategory", locale)
            )
            position_name = position.position_name

            admin_user = call.from_user
            date = get_date()
            admin_mention = (
                f"@{admin_user.username}"
                if admin_user.username
                else f"{admin_user.full_name}"
            )

            notification_text = ded(
                f"{i18n.get_text('admin_products.add_items_finish_notification_title', locale)}\n\n"
                f"{i18n.get_text('admin_products.add_items_finish_notification_admin', locale, admin_mention=admin_mention, admin_id=admin_user.id)}\n"
                f"{i18n.get_text('admin_products.add_items_finish_notification_date', locale, date = date)}\n\n"
                f"{i18n.get_text('admin_products.add_items_finish_notification_category', locale, category_name=category_name)}\n"
                f"{i18n.get_text('admin_products.add_items_finish_notification_subcategory', locale, subcategory_name=subcategory_name)}\n"
                f"{i18n.get_text('admin_products.add_items_finish_notification_position', locale, position_name=position_name)}\n\n"
                f"{i18n.get_text('admin_products.add_items_finish_notification_amount', locale, count=count_items)}"
            )
            await send_admins(bot, notification_text, not_me=admin_user.id)

    await call.message.answer(
        i18n.get_text(
            "admin_products.add_items_success_message", locale, count=count_items
        )
    )
    await position_open_admin(bot, call.from_user.id, position_id, i18n, locale)


# Словарь для кеширования медиагрупп
media_group_cache = {}


# Принятие данных товара
@router.message(
    StateFilter("here_add_items"), F.photo | F.document | F.text, flags={"rate": 0}
)
async def prod_item_add_get(
    message: Message,
    bot: Bot,
    state: FSM,
    arSession: ARS,
    i18n: Translator,
    locale: str,
):
    user_id = message.from_user.id
    saved_items_data = []  # универсальный список для путей и ссылок

    cache_message = await message.reply(
        i18n.get_text("admin_products.items_adding_wait", locale)
    )

    # --- ЛОГИКА ДЛЯ ПРЯМОЙ ЗАГРУЗКИ ФОТО/АЛЬБОМОВ ---
    if message.photo or (message.document and "image" in message.document.mime_type):
        messages_to_process = []
        if message.media_group_id:
            if message.media_group_id not in media_group_cache:
                media_group_cache[message.media_group_id] = {
                    "messages": [],
                    "timer": asyncio.create_task(asyncio.sleep(1.5)),
                }
            media_group_cache[message.media_group_id]["messages"].append(message)
            try:
                await media_group_cache[message.media_group_id]["timer"]
            except asyncio.CancelledError:
                if message.media_group_id in media_group_cache:
                    media_group_cache[message.media_group_id]["timer"].cancel()
                    media_group_cache[message.media_group_id]["timer"] = (
                        asyncio.create_task(asyncio.sleep(1.5))
                    )
                return
            user_cache = media_group_cache.pop(message.media_group_id, None)
            if not user_cache:
                return
            messages_to_process = user_cache["messages"]
        else:
            messages_to_process = [message]

        for msg in messages_to_process:
            saved_path = await save_and_compress_photo(msg, bot)
            if saved_path:
                saved_items_data.append(saved_path)

    # --- ИЗМЕНЕННАЯ ЛОГИКА ДЛЯ ОБРАБОТКИ ССЫЛОК ---
    elif message.text:
        # Просто берем ссылки из текста, проверяя, что они начинаются с http
        urls = [
            url.strip()
            for url in message.text.split("\n")
            if url.strip().startswith("http")
        ]
        if urls:
            saved_items_data.extend(urls)

    # --- ОБЩАЯ ЛОГИКА ДЛЯ ЗАВЕРШЕНИЯ ---
    if not saved_items_data:
        await cache_message.edit_text("❌ Images/links could not be processed.")
        return

    state_data = await state.get_data()
    item_count = state_data.get("here_add_item_count", 0)
    position_id = state_data["here_add_item_position_id"]

    position = Positionx.get(position_id=position_id)
    category_id = position.category_id
    subcategory_id = position.subcategory_id

    await state.update_data(here_add_item_count=item_count + len(saved_items_data))

    await run_db_operation(Itemx.add,
        user_id=user_id,
        category_id=category_id,
        subcategory_id=subcategory_id,
        position_id=position_id,
        item_datas=saved_items_data,
    )

    # Удаляем сообщение "Ждите..." и отправляем новое с подтверждением
    await cache_message.delete()
    await message.answer(
        i18n.get_text(
            "admin_products.items_added_chunk_success",
            locale,
            count=len(saved_items_data),
        ),
        reply_markup=item_add_finish_finl(position_id, i18n, locale),
    )


################################################################################
############################### УДАЛЕНИЕ ТОВАРОВ ###############################
# Страницы удаления товаров

# Страницы товаров для удаления
@router.callback_query(F.data.startswith("item_delete_swipe:"))
async def prod_item_delete_swipe(
    call: CallbackQuery, bot: Bot, i18n: Translator, locale: str
):
    # ! 1. Парсинг данных и получение информации 
    data_parts = call.data.split(":")
    position_id = int(data_parts[1])
    current_page = int(data_parts[2]) if len(data_parts) > 2 else 1
    initiator_admin = call.from_user

    all_items = Itemx.gets(position_id=position_id)
    if not all_items:
        return await call.answer(i18n.get_text("admin_products.no_items_in_position_for_delete", locale, position_name=""),show_alert=True,)

    items_per_page = 10
    start_index = (current_page - 1) * items_per_page
    items_to_show = all_items[start_index : start_index + items_per_page]

    # ! 2. Уведомление другим администраторам о просмотре 
    position = Positionx.get(position_id=position_id)
    if position:
        admin_mention = f"@{initiator_admin.username}" if initiator_admin.username else f"{initiator_admin.full_name}"
        category = Categoryx.get(category_id=position.category_id)
        subcategory = Subcategoryx.get(subcategory_id=position.subcategory_id)
        category_name = category.category_name if category else "N/A"
        subcategory_name = subcategory.subcategory_name if subcategory else "N/A"
        for admin_id in get_admins():
            if admin_id != initiator_admin.id:
                try:
                    #! Определяем язык получателя
                    recipient_admin = Userx.get(user_id=admin_id)
                    recipient_locale = "ru"
                    if recipient_admin and recipient_admin.language_code:
                        recipient_locale = recipient_admin.language_code
                    #! Формируем заголовок на языке получателя
                    header_text = i18n.get_text(
                        "admin_products.admin_notification_view_for_deletion_header",
                        recipient_locale,
                        admin_mention=admin_mention,
                        admin_id=initiator_admin.id,
                        date=get_date(),
                        category_name=category_name,
                        subcategory_name=subcategory_name,
                        position_name=position.position_name,
                        current_page=current_page,
                        total_pages=math.ceil(len(all_items) / items_per_page),
                    )
                    await bot.send_message(admin_id, header_text)
                    #! Отправляем просматриваемые товары
                    for item in items_to_show:
                        raw_data = item.item_data.strip()
                        if raw_data.startswith("media/items/"):
                            full_path = BASE_DIR / raw_data
                            if os.path.exists(full_path):
                                await bot.send_photo(admin_id, photo=FSInputFile(full_path), caption=os.path.basename(raw_data))
                            else:
                                await bot.send_message(admin_id, f"{i18n.get_text('admin_products.admin_notification_file_not_found_short')} <code>{html.escape(raw_data)}</code>")
                        else:
                            await bot.send_message(admin_id, f"<code>{html.escape(raw_data)}</code>")
                        await asyncio.sleep(0.1)
                
                except Exception as e:
                    bot_logger.error(f"Couldn't send 'view for deletion' notification to admin {admin_id}: {e}")
    # ! 3. Отправка интерфейса для удаления инициатору 
    await call.message.delete()
    delete_button_text = i18n.get_text("buttons.delete_text", locale)
    for item in items_to_show:
        raw_data = item.item_data.strip()
        delete_button = InlineKeyboardBuilder().button(text=delete_button_text, callback_data=f"item_delete_confirm:{item.item_id}").as_markup()
        try:
            if raw_data.startswith("media/items/"):
                full_path = BASE_DIR / raw_data
                if os.path.exists(full_path):
                    await bot.send_photo(call.from_user.id, photo=FSInputFile(full_path), caption=os.path.basename(raw_data), reply_markup=delete_button)
                else:
                    await bot.send_message(call.from_user.id, f"{i18n.get_text('admin_products.admin_notification_file_not_found_short')} <code>{html.escape(raw_data)}</code>", reply_markup=delete_button)
            else:
                await bot.send_message(call.from_user.id, f"<code>{html.escape(raw_data)}</code>", reply_markup=delete_button)
            await asyncio.sleep(0.1)
        except Exception as e:
            await bot.send_message(call.from_user.id, f"{i18n.get_text('admin_products.admin_notification_items_not_send_short')} <code>{html.escape(raw_data)}</code>\nОшибка: {e}")

    # ! 4. Отправка пагинации инициатору 
    pagination_kb = build_advanced_pagination(
        i18n=i18n, locale=locale,
        total_items=len(all_items),
        current_page=current_page, items_per_page=items_per_page,
        callback_prefix=f"item_delete_swipe:{position_id}",
        back_callback=f"position_edit_open:{position_id}",
    )
    builder = InlineKeyboardBuilder()
    for row in pagination_kb:
        builder.row(*row)
    
    await call.message.answer(f"{current_page} / {math.ceil(len(all_items) / items_per_page)}",reply_markup=builder.as_markup(),)



# Удаление товара
@router.callback_query(F.data.startswith("item_delete_open:"))
async def prod_item_delete_open(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    item_id = call.data.split(":")[1]
    await del_message(call.message)
    await item_open_admin(bot, call.from_user.id, item_id, 0, i18n, locale)


#! Подтверждение удаления товара
@router.callback_query(F.data.startswith("item_delete_confirm:"))
async def prod_item_delete_confirm_open(
    call: CallbackQuery, bot: Bot, i18n: Translator, locale: str
):
    item_id = int(call.data.split(":")[1])
    get_item = Itemx.get(item_id=item_id)

    if not get_item:
        return await call.answer(
            i18n.get_text("admin_products.item_already_deleted", locale),
            show_alert=True,
        )

    #! УВЕДОМЛЕНИЕ С ФОТОГРАФИЕЙ
    admin_user = call.from_user
    admin_mention = (
        f"@{admin_user.username}" if admin_user.username else f"{admin_user.full_name}"
    )
    position = Positionx.get(position_id=get_item.position_id)
    category = Categoryx.get(category_id=position.category_id)
    subcategory = Subcategoryx.get(subcategory_id=position.subcategory_id)

    #! 1. Формируем заголовок уведомления
    notification_caption = ded(f"""
        Admin {admin_mention} remove item.
        {position.position_name} : {subcategory.subcategory_name} : {category.category_name}
        Файл: {os.path.basename(get_item.item_data)}
    """)

    #! 2. Отправляем фото и заголовок другим администраторам
    for admin_id in get_admins():
        if admin_id != admin_user.id:
            try:
                if get_item.item_data.startswith(("http://", "https://")):
                    await bot.send_photo(admin_id, photo=get_item.item_data, caption=notification_caption)
                else:
                    full_path = BASE_DIR / get_item.item_data
                    await bot.send_photo(
                        admin_id,
                        photo=FSInputFile(full_path),
                        caption=notification_caption,
                    )
            except Exception as e:
                bot_logger.error(f"Couldn't send the deletion notification to the admin {admin_id}: {e}")

    #! 3. Удаляем товар из БД и отвечаем инициатору
    Itemx.delete(item_id=item_id)

    await call.message.delete()
    await call.answer(i18n.get_text("admin_products.item_delete_success_message",locale,item_data=get_item.item_data,),show_alert=True,)



################################################################################
############################### УДАЛЕНИЕ РАЗДЕЛОВ ##############################
# Возвращение к меню удаления разделов
@router.callback_query(F.data == "prod_removes_return")
async def prod_removes_return(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    await state.clear()

    await call.message.edit_text(
        i18n.get_text("admin_products.mass_delete_return_prompt", locale),
        reply_markup=products_removes_finl(i18n, locale),
    )


# Удаление всех категорий
@router.callback_query(F.data == "prod_removes_categories")
async def prod_removes_categories(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    get_categories = len(Categoryx.get_all())
    get_subcategories = len(Subcategoryx.get_all())
    get_positions = len(Positionx.get_all())
    get_items = len(Itemx.get_all())

    await call.message.edit_text(
        ded(
            i18n.get_text(
                "admin_products.confirm_mass_delete_categories_prompt",
                locale,
                categories_count=get_categories,
                subcategories_count=get_subcategories,
                positions_count=get_positions,
                items_count=get_items,
            )
        ),
        reply_markup=products_removes_categories_finl(i18n, locale),
    )


# Подтверждение удаления всех категорий
@router.callback_query(F.data == "prod_removes_categories_confirm")
async def prod_removes_categories_confirm(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    admin_user = call.from_user
    date = get_date()

    # --- Сбор информации для уведомления ПЕРЕД удалением ---
    all_categories = Categoryx.get_all()
    deleted_entities_details = []
    total_items = 0
    total_positions = 0
    total_subcategories = 0
    total_categories = len(all_categories)

    for category in all_categories:
        cat_str = f"🗃 {category.category_name}"
        deleted_entities_details.append(cat_str)

        subcategories = Subcategoryx.gets(category_id=category.category_id)
        total_subcategories += len(subcategories)

        if not subcategories:
            deleted_entities_details.append(
                f"  {i18n.get_text('admin_products.log_mass_delete_subcategory_part', locale)}"
            )

        for subcategory in subcategories:
            sub_str = f"  📁 {subcategory.subcategory_name}"
            deleted_entities_details.append(sub_str)

            positions = Positionx.gets(subcategory_id=subcategory.subcategory_id)
            total_positions += len(positions)

            if not positions:
                deleted_entities_details.append(
                    f"    {i18n.get_text('admin_products.log_mass_delete_position_part', locale)}"
                )
            else:
                for position in positions:
                    items = Itemx.gets(position_id=position.position_id)
                    items_count = len(items)
                    total_items += items_count
                    pos_str = (
                        f"    📦 {position.position_name} (Товаров: {items_count})"
                    )
                    deleted_entities_details.append(pos_str)

                    if items:
                        for item in items:
                            deleted_entities_details.append(f"      - {item.item_data}")
                    elif items_count == 0:
                        deleted_entities_details.append(
                            f"      {i18n.get_text('admin_products.export_items_no_items', locale)}"
                        )

    # --- Отправка уведомления через новую функцию ---
    await _send_mass_delete_notification(
        bot=bot,
        admin_user=admin_user,
        date = date,
        deletion_type=i18n.get_text("admin_products.log_mass_delete_all_categories", locale),
        totals={
            i18n.get_text("statistics.products_categories", locale): total_categories,
            i18n.get_text("statistics.products_subcategories", locale): total_subcategories,
            i18n.get_text("admin_products.mass_delete_notification.totals_positions", locale): total_positions,
            i18n.get_text("statistics.products_items", locale): total_items,
        },
        entities_details=deleted_entities_details,
        not_me=admin_user.id,
        i18n=i18n,
        locale=locale,
    )
    # --- Конец сбора и отправки уведомления ---

    # Непосредственное удаление данных
    Categoryx.clear()
    Subcategoryx.clear()
    Positionx.clear()
    Itemx.clear()

    # Сообщение администратору, который выполнил действие
    await call.message.edit_text(
        ded(
            i18n.get_text(
                "admin_products.mass_delete_categories_success",
                locale,
                categories_count=total_categories,
                subcategories_count=total_subcategories,
                positions_count=total_positions,
                items_count=total_items,
            )
        ),
        reply_markup=products_removes_finl(i18n, locale),
    )


# Удаление всех позиций
@router.callback_query(F.data == "prod_removes_positions")
async def prod_removes_positions(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    get_positions = len(Positionx.get_all())
    get_items = len(Itemx.get_all())

    await call.message.edit_text(
        ded(
            i18n.get_text(
                "admin_products.confirm_mass_delete_positions_prompt",
                locale,
                positions_count=get_positions,
                items_count=get_items,
            )
        ),
        reply_markup=products_removes_positions_finl(i18n, locale),
    )


# Подтверждение удаления всех позиций (товаров включительно)
@router.callback_query(F.data == "prod_removes_positions_confirm")
async def prod_removes_positions_confirm(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    admin_user = call.from_user
    date = get_date()

    all_positions = Positionx.get_all()
    deleted_entities_details = []
    total_items = 0
    total_positions = len(all_positions)
    category_cache = {}
    subcategory_cache = {}

    for position in all_positions:
        subcategory = subcategory_cache.get(position.subcategory_id)
        if position.subcategory_id not in subcategory_cache:
            subcategory = Subcategoryx.get(subcategory_id=position.subcategory_id)
            subcategory_cache[position.subcategory_id] = (
                subcategory if subcategory else None
            )

        category = None
        if subcategory and subcategory.category_id in category_cache:
            category = category_cache[subcategory.category_id]
        elif subcategory:
            category = Categoryx.get(category_id=subcategory.category_id)
            category_cache[subcategory.category_id] = category if category else None

        subcategory_name = (
            subcategory.subcategory_name
            if subcategory
            else i18n.get_text("common.no_subcategory", locale)
        )
        category_name = (
            category.category_name
            if category
            else i18n.get_text("admin_menu_main.no_category", locale)
        )

        items = Itemx.gets(position_id=position.position_id)
        items_count = len(items)
        total_items += items_count

        pos_str = f"🗃 {category_name} / 📁 {subcategory_name} / 📦 {position.position_name} (Товаров: {items_count})"
        deleted_entities_details.append(pos_str)

        if items:
            for item in items:
                deleted_entities_details.append(f"    - {item.item_data}")
        elif items_count == 0:
            deleted_entities_details.append(
                f"    {i18n.get_text('admin_products.export_items_no_items', locale)}"
            )

    await _send_mass_delete_notification(
        bot=bot,
        admin_user=admin_user,
        date = date,
        deletion_type=i18n.get_text("admin_products.log_mass_delete_all_positions", locale),
        totals={i18n.get_text("admin_products.mass_delete_notification.totals_positions", locale): total_positions, i18n.get_text("statistics.products_items", locale): total_items,},
        entities_details=deleted_entities_details,
        not_me=admin_user.id,
        i18n=i18n,
        locale=locale,
    )

    Positionx.clear()
    Itemx.clear()

    await call.message.edit_text(
        ded(
            i18n.get_text(
                "admin_products.mass_delete_positions_success",
                locale,
                positions_count=total_positions,
                items_count=total_items,
            )
        ),
        reply_markup=products_removes_finl(i18n, locale),
    )


# Удаление всех товаров
@router.callback_query(F.data == "prod_removes_items")
async def prod_removes_items(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    get_items = len(Itemx.get_all())

    await call.message.edit_text(
        i18n.get_text(
            "admin_products.confirm_mass_delete_items_prompt",
            locale,
            items_count=get_items,
        ),
        reply_markup=products_removes_items_finl(i18n, locale),
    )


# Согласие на удаление всех товаров
@router.callback_query(F.data == "prod_removes_items_confirm")
async def prod_removes_items_confirm(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    admin_user = call.from_user
    date = get_date()

    all_positions = Positionx.get_all()
    total_items = 0
    deleted_entities_details = []
    category_cache = {}
    subcategory_cache = {}

    for position in all_positions:
        items_in_position = Itemx.gets(position_id=position.position_id)
        items_count = len(items_in_position)
        if items_count == 0:
            continue
        total_items += items_count

        subcategory = subcategory_cache.get(position.subcategory_id)
        if position.subcategory_id not in subcategory_cache:
            subcategory = Subcategoryx.get(subcategory_id=position.subcategory_id)
            subcategory_cache[position.subcategory_id] = (
                subcategory if subcategory else None
            )

        category = None
        if subcategory and subcategory.category_id in category_cache:
            category = category_cache[subcategory.category_id]
        elif subcategory:
            category = Categoryx.get(category_id=subcategory.category_id)
            category_cache[subcategory.category_id] = category if category else None

        subcategory_name = (
            subcategory.subcategory_name
            if subcategory
            else i18n.get_text("common.no_subcategory", locale)
        )
        category_name = (
            category.category_name
            if category
            else i18n.get_text("admin_menu_main.no_category", locale)
        )

        pos_str = (
            f"🗃 {category_name} / 📁 {subcategory_name} / 📦 {position.position_name} /"
        )
        deleted_entities_details.append(pos_str)

        for item in items_in_position:
            deleted_entities_details.append(f"  - {item.item_data}")

    await _send_mass_delete_notification(
        bot=bot,
        admin_user=admin_user,
        date = date,
        deletion_type=i18n.get_text("admin_products.log_mass_delete_all_items", locale),
        totals={i18n.get_text("statistics.products_items", locale): total_items},
        entities_details=deleted_entities_details,
        not_me=admin_user.id,
        i18n=i18n,
        locale=locale,
    )

    Itemx.clear()

    await call.message.edit_text(
        i18n.get_text(
            "admin_products.mass_delete_items_success", locale, items_count=total_items
        ),
        reply_markup=products_removes_finl(i18n, locale),
    )


################################################################################
############################### СОЗДАНИЕ ПОДКАТЕГОРИИ ###########################
# Создание новой подкатегории
@router.message(I18nText("reply_admin.create_subcategory"))
async def prod_subcategory_add(
    message: Message, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    get_categories = Categoryx.get_all()
    if len(get_categories) >= 1:
        await message.answer(
            i18n.get_text("admin_products.create_subcategory_prompt", locale),
            reply_markup=subcategory_add_swipe_fp(0, i18n, locale),
        )
    else:
        await message.answer(
            i18n.get_text("admin_products.no_categories_for_subcategory", locale)
        )


# Перемещение по страницам категорий для создания подкатегории
@router.callback_query(F.data.startswith("subcategory_add_swipe:"))
async def prod_subcategory_add_swipe(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    remover = int(call.data.split(":")[1])
    await call.message.edit_text(
        i18n.get_text("admin_products.create_subcategory_prompt", locale),
        reply_markup=subcategory_add_swipe_fp(remover, i18n, locale),
    )


# Выбор категории для создания подкатегории
@router.callback_query(F.data.startswith("subcategory_add_open:"))
async def prod_subcategory_add_category_open(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id = int(call.data.split(":")[1])
    await state.update_data(here_category_id=category_id)
    await state.set_state("here_subcategory_name")
    await call.message.edit_text(
        i18n.get_text("admin_products.enter_subcategory_name", locale)
    )


# Принятие названия подкатегории для её создания
@router.message(F.text, StateFilter("here_subcategory_name"))
async def prod_subcategory_add_name_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    if len(message.text) > 50:
        return await message.answer(
            i18n.get_text("admin_products.error_name_too_long_50", locale)
            + i18n.get_text("admin_products.enter_subcategory_name", locale),
        )

    state_data = await state.get_data()
    category_id = state_data["here_category_id"]
    await state.clear()

    Subcategoryx.add(category_id=category_id, subcategory_name=clear_html(message.text))

    get_subcategories = Subcategoryx.gets(category_id=category_id)
    new_subcategory = get_subcategories[-1]

    await subcategory_open_admin(
        bot,
        message.from_user.id,
        category_id,
        new_subcategory.subcategory_id,
        0,
        i18n,
        locale,
    )


# Выбор подкатегории для редактирования
@router.message(I18nText("reply_admin.edit_subcategory"))
async def prod_subcategory_edit(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    await state.clear()
    get_subcategories = Subcategoryx.get_all()
    if len(get_subcategories) >= 1:
        await message.answer(
            i18n.get_text("admin_products.edit_subcategory_prompt", locale),
            reply_markup=subcategory_edit_swipe_fp(0, i18n, locale),
        )
    else:
        await message.answer(
            i18n.get_text("admin_products.no_subcategories_to_edit", locale)
        )


# Перемещение по страницам подкатегорий для редактирования
@router.callback_query(F.data.startswith("subcategory_edit_swipe:"))
async def prod_subcategory_edit_swipe(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    remover = int(call.data.split(":")[1])
    await call.message.edit_text(
        i18n.get_text("admin_products.edit_subcategory_prompt", locale),
        reply_markup=subcategory_edit_swipe_fp(remover, i18n, locale),
    )


# Выбор подкатегории для редактирования
@router.callback_query(F.data.startswith("subcategory_edit_open:"))
async def prod_subcategory_edit_open(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id, subcategory_id, remover = map(int, call.data.split(":")[1:])

    await state.clear()
    await del_message(call.message)
    await subcategory_open_admin(
        bot, call.from_user.id, category_id, subcategory_id, remover, i18n, locale
    )


# Изменение названия подкатегории
@router.callback_query(F.data.startswith("subcategory_edit_name:"))
async def prod_subcategory_edit_name(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id, subcategory_id, remover = map(int, call.data.split(":")[1:])

    await state.update_data(
        here_category_id=category_id,
        here_subcategory_id=subcategory_id,
        here_remover=remover,
    )
    await state.set_state("here_subcategory_edit_name")

    await call.message.edit_text(
        i18n.get_text("admin_products.enter_new_subcategory_name", locale)
    )


# Принятие нового названия подкатегории
@router.message(F.text, StateFilter("here_subcategory_edit_name"))
async def prod_subcategory_edit_name_get(
    message: Message, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    if len(message.text) > 50:
        return await message.answer(
            i18n.get_text("admin_products.error_name_too_long_50", locale)
            + i18n.get_text("admin_products.enter_new_subcategory_name", locale),
        )

    state_data = await state.get_data()
    category_id = state_data["here_category_id"]
    subcategory_id = state_data["here_subcategory_id"]
    remover = state_data["here_remover"]
    await state.clear()

    Subcategoryx.update(
        category_id=category_id,
        subcategory_id=subcategory_id,
        subcategory_name=clear_html(message.text),
    )

    await subcategory_open_admin(
        bot, message.from_user.id, category_id, subcategory_id, remover, i18n, locale
    )


# Подтверждение удаления подкатегории
@router.callback_query(F.data.startswith("subcategory_edit_delete:"))
async def prod_subcategory_edit_delete(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id, subcategory_id, remover = map(int, call.data.split(":")[1:])

    subcategory = Subcategoryx.get(subcategory_id=subcategory_id)
    if not subcategory:
        await call.answer(
            i18n.get_text("admin_products.subcategory_not_found", locale),
            show_alert=True,
        )
        try:
            await call.message.delete()
        except:
            pass
        return

    positions = Positionx.gets(subcategory_id=subcategory_id)
    positions_text = "\n".join([f" - {pos.position_name}" for pos in positions])
    if not positions:
        positions_text = i18n.get_text(
            "admin_products.log_mass_delete_position_part", locale
        )

    total_items_count = sum(
        len(Itemx.gets(position_id=pos.position_id)) for pos in positions
    )

    message_text = ded(
        i18n.get_text(
            "admin_products.confirm_delete_subcategory_prompt",
            locale,
            subcategory_name=subcategory.subcategory_name,
            positions_count=len(positions),
            positions_text=positions_text,
            items_count=total_items_count,
        )
    )

    await call.message.edit_text(
        message_text,
        reply_markup=subcategory_edit_delete_finl(
            category_id, subcategory_id, remover, i18n, locale
        ),
    )


# Удаление подкатегории
@router.callback_query(F.data.startswith("subcategory_edit_delete_confirm:"))
async def prod_subcategory_edit_delete_confirm(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    category_id, subcategory_id, remover = map(int, call.data.split(":")[1:])

    admin_user = call.from_user
    date = get_date()
    admin_mention = (
        f"@{admin_user.username}" if admin_user.username else f"{admin_user.full_name}"
    )

    subcategory_to_delete = Subcategoryx.get(subcategory_id=subcategory_id)
    if not subcategory_to_delete:
        await call.answer(
            i18n.get_text("admin_products.subcategory_already_deleted", locale),
            show_alert=True,
        )
        try:
            await call.message.delete()
        except:
            pass
        return

    category = Categoryx.get(category_id=category_id)
    category_name = (
        category.category_name
        if category
        else i18n.get_text("admin_menu_main.no_category", locale)
    )
    subcategory_name = subcategory_to_delete.subcategory_name

    deleted_entities_details = []
    total_items = 0

    positions_to_delete = Positionx.gets(subcategory_id=subcategory_id)
    total_positions = len(positions_to_delete)

    base_notification_text = ded(
        f"{i18n.get_text('admin_products.log_mass_delete_subcategory', locale)}\n\n"
        f"{i18n.get_text('admin_products.add_items_finish_notification_admin', locale, admin_mention=admin_mention, admin_id=admin_user.id)}\n"
        f"{i18n.get_text('admin_products.add_items_finish_notification_date', locale, date = date)}\n\n"
        f"🗃 <b>Category:</b> {category_name}\n"
        f"📁 <b>Subcategory:</b> {subcategory_name}\n\n"
        f"{i18n.get_text('admin_products.will_be_deleted_positions', locale, count=total_positions)}\n\n"
        f"{i18n.get_text('admin_products.list_of_deleted_positions_and_items', locale)}\n"
    )
    current_message = base_notification_text

    if not positions_to_delete:
        deleted_entities_details.append(
            f"  {i18n.get_text('admin_products.log_mass_delete_position_part', locale)}"
        )
    else:
        for position in positions_to_delete:
            items_in_position = Itemx.gets(position_id=position.position_id)
            items_count = len(items_in_position)
            total_items += items_count
            pos_str = f"  📦 {position.position_name} (Items: {items_count})"
            deleted_entities_details.append(pos_str)
            if items_in_position:
                for item in items_in_position:
                    deleted_entities_details.append(f"    - {item.item_data}")
            elif items_count == 0:
                deleted_entities_details.append(
                    f"    {i18n.get_text('admin_products.export_items_no_items', locale)}"
                )

    if deleted_entities_details:
        for entity_line in deleted_entities_details:
            line_to_add = entity_line + "\n"
            if len(current_message) + len(line_to_add) > TELEGRAM_MSG_LIMIT:
                await send_admins(bot, current_message, not_me=admin_user.id)
                current_message = (
                    i18n.get_text(
                        "admin_products.log_mass_delete_notification_continuation",
                        locale,
                    )
                    + line_to_add
                )
            else:
                current_message += line_to_add
        if current_message and len(current_message) > len(base_notification_text):
            await send_admins(bot, current_message, not_me=admin_user.id)
    else:
        await send_admins(
            bot,
            base_notification_text
            + f"  {i18n.get_text('admin_products.log_mass_delete_position_part', locale)}",
            not_me=admin_user.id,
        )

    # Непосредственное удаление данных
    positions_final_check = Positionx.gets(subcategory_id=subcategory_id)
    for position in positions_final_check:
        Itemx.delete(position_id=position.position_id)
    Positionx.delete(subcategory_id=subcategory_id)
    Subcategoryx.delete(subcategory_id=subcategory_id)

    await call.answer(
        i18n.get_text(
            "admin_products.subcategory_delete_success_answer",
            locale,
            subcategory_name=subcategory_name,
            positions_count=total_positions,
            items_count=total_items,
        ),
        show_alert=True,
    )

    await call.message.edit_text(
        i18n.get_text(
            "admin_products.subcategory_delete_success_message",
            locale,
            subcategory_name=subcategory_name,
        )
    )
    await category_open_admin(
        bot, call.from_user.id, category_id, remover, i18n, locale
    )


# Удаление всех подкатегорий
@router.callback_query(F.data == "prod_removes_subcategories")
async def prod_removes_subcategories(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    get_subcategories = len(Subcategoryx.get_all())
    get_positions = len(Positionx.get_all())
    get_items = len(Itemx.get_all())

    await call.message.edit_text(
        ded(
            i18n.get_text(
                "admin_products.confirm_mass_delete_subcategories_prompt",
                locale,
                subcategories_count=get_subcategories,
                positions_count=get_positions,
                items_count=get_items,
            )
        ),
        reply_markup=products_removes_subcategories_finl(i18n, locale),
    )


# Подтверждение удаления всех подкатегорий
@router.callback_query(F.data == "prod_removes_subcategories_confirm")
async def prod_removes_subcategories_confirm(
    call: CallbackQuery, bot: Bot, state: FSM, i18n: Translator, locale: str
):
    admin_user = call.from_user
    date = get_date()

    # --- Сбор информации для уведомления ПЕРЕД удалением ---
    all_subcategories = Subcategoryx.get_all()
    deleted_entities_details = []
    total_items = 0
    total_positions = 0
    total_subcategories = len(all_subcategories)
    category_cache = {}

    for subcategory in all_subcategories:
        category = category_cache.get(subcategory.category_id)
        if not category:
            category = Categoryx.get(category_id=subcategory.category_id)
            category_cache[subcategory.category_id] = category if category else None

        category_name = (
            category.category_name
            if category
            else i18n.get_text("admin_menu_main.no_category", locale)
        )

        sub_str = f"🗃 {category_name} / 📁 {subcategory.subcategory_name}"
        deleted_entities_details.append(sub_str)

        positions = Positionx.gets(subcategory_id=subcategory.subcategory_id)
        total_positions += len(positions)

        if not positions:
            deleted_entities_details.append(
                f"  {i18n.get_text('admin_products.log_mass_delete_position_part', locale)}"
            )
        else:
            for position in positions:
                items = Itemx.gets(position_id=position.position_id)
                items_count = len(items)
                total_items += items_count
                pos_str = f"  📦 {position.position_name} (Items: {items_count})"
                deleted_entities_details.append(pos_str)
                if items:
                    for item in items:
                        deleted_entities_details.append(f"    - {item.item_data}")
                elif items_count == 0:
                    deleted_entities_details.append(
                        f"      {i18n.get_text('admin_products.export_items_no_items', locale)}"
                    )

    # --- Отправка уведомления через новую функцию ---
    await _send_mass_delete_notification(
        bot=bot,
        admin_user=admin_user,
        date = date,
        deletion_type=i18n.get_text(
            "admin_products.log_mass_delete_all_subcategories", locale
        ),
        totals={
            i18n.get_text(
                "statistics.products_subcategories", locale
            ): total_subcategories,
            i18n.get_text(
                "admin_products.mass_delete_notification.totals_positions", locale
            ): total_positions,
            i18n.get_text("statistics.products_items", locale): total_items,
        },
        entities_details=deleted_entities_details,
        not_me=admin_user.id,
        i18n=i18n,
        locale=locale,
    )
    # --- Конец отправки уведомления ---

    # Непосредственное удаление данных
    Subcategoryx.clear()
    Positionx.clear()
    Itemx.clear()

    # Сообщение администратору
    await call.message.edit_text(
        ded(
            i18n.get_text(
                "admin_products.mass_delete_subcategories_success",
                locale,
                subcategories_count=total_subcategories,
                positions_count=total_positions,
                items_count=total_items,
            )
        ),
        reply_markup=products_removes_finl(i18n, locale),
    )

# Управление товарами
@router.message(I18nText("reply_admin.items"))
async def admin_products(message: Message, state: FSM, i18n: Translator, locale: str):
    await state.clear()
    await message.answer( i18n.get_text("admin_menu_main.products_title", locale), reply_markup=items_frep(i18n, locale), )


@router.callback_query(F.data == "products_edit")
async def admin_products_callback(call: CallbackQuery, state: FSM, i18n: Translator, locale: str):
    await state.clear()
    await call.bot.send_message(
        chat_id=call.from_user.id,
        text=i18n.get_text("admin_menu_main.products_title", locale),
        reply_markup=items_frep(i18n, locale),
    )
    try:
        await call.message.delete()
    except:
        pass
    await call.answer()