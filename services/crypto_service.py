from aiocryptopay import AioCryptoPay, Networks
from config import CRYPTOBOT_TOKEN, RESERVE_MINUTES
import logging


class CryptoService:
    def __init__(self):
        if not CRYPTOBOT_TOKEN:
            logging.warning("CRYPTOBOT_TOKEN не задан. Крипто-оплата недоступна.")
            self.crypto = None
        else:
            self.crypto = AioCryptoPay(token=CRYPTOBOT_TOKEN, network=Networks.MAIN_NET)

    async def create_invoice(self, amount_rub: float, description: str) -> dict | None:
        """Создаёт счёт в рублях. CryptoBot сам конвертирует в крипту по курсу."""
        if not self.crypto:
            return None
        try:
            invoice = await self.crypto.create_invoice(
                amount=amount_rub,
                currency_type="fiat",
                fiat="RUB",
                accepted_assets="USDT",  # можно убрать, если хочешь принимать любую крипту
                description=description,
                expires_in=RESERVE_MINUTES * 60,
            )
            return {
                "invoice_id": invoice.invoice_id,
                "pay_url": invoice.bot_invoice_url,
            }
        except Exception as e:
            logging.error(f"Crypto create_invoice error: {e}")
            return None

    async def get_invoice_status(self, invoice_id: int) -> str | None:
        """Возвращает статус счёта: 'active', 'paid', 'expired'."""
        if not self.crypto:
            return None
        try:
            invoices = await self.crypto.get_invoices(invoice_ids=invoice_id)
            if invoices and len(invoices) > 0:
                return invoices[0].status
            return None
        except Exception as e:
            logging.error(f"Crypto get_invoice error: {e}")
            return None
