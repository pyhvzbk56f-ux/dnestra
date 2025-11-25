# shop/tgbot/services/api_tronscan.py
from datetime import datetime, timezone
import aiohttp
import time
from aiogram import Bot

from tgbot.database import Settingsx
from tgbot.utils.const_functions import send_admins, bot_logger

async def get_usdt_trc20_transactions(bot: Bot, address: str) -> list:
    """Получает последние 50 транзакций USDT TRC20 через TronScan API."""
    bot_logger.debug(f"get_usdt_trc20_transactions: TronScan: Request for a USDT address: {address}")
    get_settings = Settingsx.get()
    api_key = get_settings.tronscan_api_key

    if not api_key:
        bot_logger.error("get_usdt_trc20_transactions: TronScan API-key not installed!")
        await send_admins(bot, "get_usdt_trc20_transactions: TronScan API-key not installed!")
        return []

    # Устанавливаем временной фильтр на последние 4 часа (в миллисекундах)
    start_timestamp_ms = int((time.time() - 4 * 3600) * 1000)

    url = "https://apilist.tronscan.org/api/token_trc20/transfers"
    params = {
        'limit': 50, 'start': 0, 'sort': '-timestamp', 'toAddress': address,
        'contract_address': 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t',
        'start_timestamp': start_timestamp_ms
    }
    headers = {"TRON-PRO-API-KEY": api_key}
    transactions = []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    bot_logger.debug("get_usdt_trc20_transactions: TronScan: response 200.")
                    for tx in data.get('token_transfers', []):
                        if tx.get('confirmed'):
                            transactions.append({
                                'txid': tx['transaction_id'],
                                'amount': round(int(tx['quant']) / 10**6, 6),
                                'timestamp': tx['block_ts'] // 1000, # Возвращаем UNIX timestamp в секундах
                                'confirmations': 'confirmed'
                            })
                else:
                    bot_logger.error(f"get_usdt_trc20_transactions: TronScan API error: Статус {response.status}, Ответ: {await response.text()}")
                    return []
    except Exception as e:
        bot_logger.error(f"get_usdt_trc20_transactions: Error request TronScan API: {e}", exc_info=True)
        return []

    transactions.sort(key=lambda x: x.get('date', ''), reverse=True)
    bot_logger.debug(f"get_usdt_trc20_transactions: TronScan: Found {len(transactions)} confirmed transactions.")
    return transactions