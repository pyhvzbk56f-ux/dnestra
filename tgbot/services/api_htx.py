# shop/tgbot/services/api_htx.py
import base64
import hashlib
import hmac
import time
from urllib.parse import urlencode
from typing import List, Dict, Any, Tuple
import aiohttp

from tgbot.database import Settingsx
from tgbot.services.i18n import i18n
from tgbot.utils.const_functions import bot_logger

BASE_URL = "https://api.htx.com"

def sign_request(method: str, endpoint: str, params: dict, secret_key: str) -> str:
    """#! Signs the request according to HTX API requirements."""
    sorted_params = sorted(params.items(), key=lambda d: d[0], reverse=False)
    query_string = urlencode(sorted_params)
    payload = f"{method}\napi.htx.com\n{endpoint}\n{query_string}"
    digest = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()

async def get_htx_ltc_to_usd_rate() -> float | None:
    """#! Gets the LTC to USDT rate from the HTX API."""
    bot_logger.info(i18n.get_text("log_messages.htx_requesting_rate", "en"))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{BASE_URL}/market/detail/merged?symbol=ltcusdt", timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "ok" and "tick" in data and "close" in data["tick"]:
                        rate = float(data["tick"]["close"])
                        bot_logger.info(i18n.get_text("log_messages.htx_rate_received", "en", rate=rate))
                        return rate
                bot_logger.error(i18n.get_text("log_messages.htx_rate_error_status", "en", status=response.status))
                return None
    except Exception as e:
        bot_logger.error(i18n.get_text("log_messages.htx_rate_critical_error", "en", error=e), exc_info=True)
        return None
    
async def get_htx_ltc_to_usd_rate() -> float | None:
    """#! Gets the LTC to USDT rate from the HTX API."""
    bot_logger.info(i18n.get_text("log_messages.htx_requesting_rate", "en"))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{BASE_URL}/market/detail/merged?symbol=ltcusdt", timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "ok" and "tick" in data and "close" in data["tick"]:
                        rate = float(data["tick"]["close"])
                        bot_logger.info(i18n.get_text("log_messages.htx_rate_received", "en", rate=rate))
                        return rate
                bot_logger.error(i18n.get_text("log_messages.htx_rate_error_status", "en", status=response.status))
                return None
    except Exception as e:
        bot_logger.error(i18n.get_text("log_messages.htx_rate_critical_error", "en", error=e), exc_info=True)
        return None

async def get_htx_deposits(currency_code: str) -> List[Dict[str, Any]] | None:
    """#! Fetches the last 100 deposits for the specified currency from HTX."""
    bot_logger.info(i18n.get_text("log_messages.htx_requesting_deposits", "en", currency=currency_code.upper()))
    settings = Settingsx.get()
    api_key = settings.htx_access_key
    secret_key = settings.htx_secret_key

    if not api_key or not secret_key:
        bot_logger.error(i18n.get_text("log_messages.htx_keys_not_configured", "en", currency=currency_code.upper()))
        return None

    endpoint = "/v1/query/deposit-withdraw"
    method = "GET"
    
    params = {
        "AccessKeyId": api_key,
        "SignatureMethod": "HmacSHA256",
        "SignatureVersion": "2",
        "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "type": "deposit",
        "currency": currency_code.lower(),
        "direct": "next",
        "size": 100,
    }

    try:
        params["Signature"] = sign_request(method, endpoint, params, secret_key)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{BASE_URL}{endpoint}", params=params, timeout=20) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "ok":
                        transactions = []

                        four_hours_ago_ms = int((time.time() - 4 * 3600) * 1000)

                        # Фильтруем транзакции со статусами confirming, confirmed, safe и по времени 
                        for tx in data.get('data', []):
                            if tx.get('created-at') >= four_hours_ago_ms and tx.get('state') in ['confirming', 'confirmed', 'safe']:
                                transactions.append({
                                    'txid': tx.get('tx-hash'),
                                    'amount': round(float(tx.get('amount')), 6),
                                    'timestamp': tx.get('created-at') // 1000,
                                })
                        bot_logger.info(i18n.get_text("log_messages.htx_deposits_found", "en", count=len(transactions), currency=currency_code.upper()))
                        return transactions
                
                error_text = await response.text()
                bot_logger.error(i18n.get_text("log_messages.htx_deposits_error_status", "en", status=response.status, response=error_text))
                return None
    except Exception as e:
        bot_logger.error(i18n.get_text("log_messages.htx_deposits_critical_error", "en", error=e), exc_info=True)
        return None