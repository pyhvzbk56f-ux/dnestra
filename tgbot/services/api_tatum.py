# shop/tgbot/services/api_tatum.py
from datetime import datetime, timezone
import aiohttp
from aiogram import Bot
import time

from tgbot.database import Settingsx
from tgbot.utils.const_functions import send_admins, bot_logger

async def get_ltc_transactions(bot: Bot, address: str) -> list:
    """Получает последние 50 транзакций LTC через Tatum API."""
    bot_logger.debug(f"get_ltc_transactions: Tatum: request for LTC address: {address}")
    get_settings = Settingsx.get()
    api_key = get_settings.tatum_api_key

    if not api_key:
        bot_logger.error("get_ltc_transactions: Tatum API-key not installed!")
        await send_admins(bot, "get_ltc_transactions: Error: Tatum API-key not installed!")
        return []

    url = f"https://api.tatum.io/v3/litecoin/transaction/address/{address}"
    params = {"pageSize": 50, "offset": 0}
    headers = {"x-api-key": api_key}
    transactions = []

    # Временная метка для фильтрации (последние 4 часа)
    four_hours_ago = int(time.time()) - 4 * 3600

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=20) as response:
                if response.status == 200:
                    data = await response.json()
                    bot_logger.debug("get_ltc_transactions: Tatum: respoose 200.")
                    for tx in data:
                        tx_time = tx.get('time', 0)
                        # Фильтруем транзакции, которые были совершены за последние 4 часа
                        if tx_time >= four_hours_ago:
                            block_number = tx.get('blockNumber')
                            if block_number is not None and block_number > 0:
                                for vout in tx.get('outputs', []):
                                    if vout.get('address') == address:
                                        transactions.append({
                                            'txid': tx.get('hash'),
                                            'amount': round(float(vout.get('value', '0.0')), 6),
                                            'timestamp': tx_time,
                                            'confirmations': block_number
                                        })
                                        break
                else:
                    bot_logger.error(f"get_ltc_transactions: Tatum API error: Status {response.status}, Respponse: {await response.text()}")
                    return []
    except Exception as e:
        bot_logger.error(f"get_ltc_transactions: Error request Tatum API: {e}", exc_info=True)
        return []

    transactions.sort(key=lambda x: x.get('date', ''), reverse=True)
    bot_logger.debug(f"get_ltc_transactions: Tatum: Found {len(transactions)} confirmed transactions.")
    return transactions