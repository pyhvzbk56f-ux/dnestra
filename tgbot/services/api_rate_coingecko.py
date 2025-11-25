# shop/tgbot/services/api_rate_coingecko.py
import aiohttp
from aiogram import Bot

from tgbot.utils.const_functions import bot_logger, send_admins

async def get_ltc_to_usd_rate(bot: Bot) -> float | None:
    """
    Получает актуальный курс LTC к USD через публичный API CoinGecko.
    """
    url = "https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=usd"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if "litecoin" in data and "usd" in data["litecoin"]:
                        rate = float(data["litecoin"]["usd"])
                        bot_logger.debug(f"get_ltc_to_usd_rate: CoinGecko: Курс LTC/USD получен: {rate}")
                        return rate
                    else:
                        bot_logger.error("get_ltc_to_usd_rate: CoinGecko API: Некорректный формат ответа.")
                        return None
                else:
                    bot_logger.error(f"get_ltc_to_usd_rate: CoinGecko API: Ошибка статуса {response.status}")
                    return None
    except Exception as e:
        bot_logger.error(f"get_ltc_to_usd_rate: Критическая ошибка при запросе к CoinGecko API: {e}", exc_info=True)
        await send_admins(bot, "get_ltc_to_usd_rate: КРИТИЧЕСКАЯ ОШИБКА: API CoinGecko для получения курса LTC недоступно.")
        return None