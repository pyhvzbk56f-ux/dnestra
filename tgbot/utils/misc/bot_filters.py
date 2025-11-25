from typing import Union

from aiogram import Bot
from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ChatMemberStatus

from tgbot.data.config import get_admins, get_operators
from tgbot.database import Settingsx, Buttonx, Channelx, ChannelModel
from tgbot.services.i18n import i18n
from tgbot.keyboards.inline_user import channel_subscribe_finl
from tgbot.utils.const_functions import send_admins, bot_logger


# Проверка на подписку на канал
class IsSubscribed(BaseFilter):
    async def __call__(self, update: Union[Message, CallbackQuery], bot: Bot) -> Union[bool, list[ChannelModel]]:
        user_id = update.from_user.id
        if user_id in get_admins() or user_id in get_operators():
            return True

        channels_to_check = Channelx.get_all()
        if not channels_to_check:
            return True

        unsubscribed_channels: list[ChannelModel] = []
        for channel in channels_to_check:
            try:
                member = await bot.get_chat_member(chat_id=channel.channel_id, user_id=user_id)
                if member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
                    unsubscribed_channels.append(channel)
            except Exception as e:
                # Если бот не может проверить (например, не админ), считаем, что пользователь должен подписаться
                bot_logger.warning(f"Could not check subscription for user {user_id} in channel {channel.channel_id}: {e}")
                unsubscribed_channels.append(channel)
        
        if unsubscribed_channels:
            return unsubscribed_channels # Возвращаем список каналов для подписки
        
        return True # Возвращаем True, если подписан на все



# Проверка на админа
class IsAdmin(BaseFilter):
    async def __call__(self, update: Union[Message, CallbackQuery], bot: Bot) -> bool:
        if update.from_user.id in get_admins():
            return True
        else:
            return False


class IsOperator(BaseFilter):
    """Проверяет оператор, но не администратор."""
    async def __call__(self, update: Union[Message, CallbackQuery], bot: Bot) -> bool:
        user_id = update.from_user.id
        return user_id in get_operators() and user_id not in get_admins()


class IsAdminOrOperator(BaseFilter):
    """Проверяет администратор или оператор."""
    async def __call__(self, update: Union[Message, CallbackQuery], bot: Bot) -> bool:
        user_id = update.from_user.id
        return user_id in get_admins() or user_id in get_operators()



# Проверка на технические работы
class IsWork(BaseFilter):
    async def __call__(self, update: Union[Message, CallbackQuery], bot: Bot) -> bool:
        get_settings = Settingsx.get()

        if get_settings.status_work == "False" or update.from_user.id in get_admins():
            return False
        else:
            return True


# Проверка на возможность пополнения
class IsRefill(BaseFilter):
    async def __call__(self, update: Union[Message, CallbackQuery], bot: Bot) -> bool:
        get_settings = Settingsx.get()

        if get_settings.status_refill == "True" or update.from_user.id in get_admins():
            return False
        else:
            return True


# Проверка на возможность покупки товара
class IsBuy(BaseFilter):
    async def __call__(self, update: Union[Message, CallbackQuery], bot: Bot) -> bool:
        get_settings = Settingsx.get()

        if get_settings.status_buy == "True" or update.from_user.id in get_admins():
            return False
        else:
            return True


class IsCustomButton(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        """ Фильтр проверяет в БД, существует ли кнопка с таким названием. Выполняется для каждого сообщения."""
        # Метод get_by_name вернет либо объект кнопки, либо None. преобразуем результат в bool, чтобы фильтр вернул True или False.
        return bool(Buttonx.get_by_name(button_name=message.text))
