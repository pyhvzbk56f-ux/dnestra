# shop/tgbot/utils/misc/bot_commands.py
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from tgbot.data.config import get_admins, get_operators

# Команды для юзеров
user_commands = [
    BotCommand(command="start", description="♻️ Restart"),
    BotCommand(command="support", description="☎️ Support"),
    BotCommand(command="faq", description="❔ FAQ"),
]

# Команды для админов
admin_commands = [
    BotCommand(command="start", description="♻️ Restart"),
    BotCommand(command="showcase", description="🛍️ Showcase"),
    BotCommand(command="search", description="🔍 Search"),
    BotCommand(command="db", description="📦 Get DB"),
    BotCommand(command="log", description="🖨 Get Logs"),
]


# Установка команд
async def set_commands(bot: Bot):
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())

    for admin in get_admins():
        try:
            await bot.set_my_commands(
                admin_commands, scope=BotCommandScopeChat(chat_id=admin)
            )
        except:
            ...
