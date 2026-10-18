import aiohttp
from config import CRYPTOBOT_TOKEN


API_URL = "https://pay.crypt.bot/api"


class CryptoBotService:
    def __init__(self):
        self.headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN or ""}

    async def create_invoice(self, amount_rub: float, description: str) -> dict:
        """
        Создаёт счёт в рублях (fiat=RUB).
        CryptoBot сам сконвертирует сумму в крипту по курсу.
        Возвращает ответ API: {'ok': True, 'result': {...}} или {'ok': False, ...}.
        """
        payload = {
            "currency_type": "fiat",
            "fiat": "RUB",
            "amount": f"{amount_rub:.2f}",
            "description": description[:1024],
            "expires_in": 3600,
            "allow_comments": False,
            "allow_anonymous": True,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{API_URL}/createInvoice",
                headers=self.headers,
                json=payload,
            ) as resp:
                return await resp.json()

    async def get_invoice_status(self, invoice_id: int):
        """
        Возвращает 'paid' | 'active' | 'expired' или None при ошибке.
        """
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{API_URL}/getInvoices",
                headers=self.headers,
                json={"invoice_ids": str(invoice_id)},
            ) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    return None
                items = data.get("result", {}).get("items", [])
                if not items:
                    return None
                return items[0].get("status")
