import logging
from aioFunPayAPI import Account as FunPayAccount
from config import FUNPAY_GOLDEN_KEY, FUNPAY_USER_AGENT, FUNPAY_CATEGORY_ID


class FunPayService:
    def __init__(self):
        self.account = None

    async def init(self):
        self.account = await FunPayAccount(
            golden_key=FUNPAY_GOLDEN_KEY,
            user_agent=FUNPAY_USER_AGENT,
        ).get()

    async def get_account(self):
        if not self.account:
            await self.init()
        return self.account

    async def create_lot(self, rank: str, hours: int, price: float) -> str:
        """Создаёт лот FunPay для комбинации (rank, hours). Возвращает URL лота."""
        if not self.account:
            await self.init()

        title = f"Valorant аккаунт {rank} — аренда {hours}ч"
        description = (
            f"Аренда аккаунта Valorant ранга {rank} на {hours} часов.\n"
            f"После оплаты данные придут в чат автоматически."
        )

        # save_lot с offer_id=0 создаёт новый лот.
        # В некоторых версиях aioFunPayAPI метод может называться иначе.
        lot = await self.account.save_lot(
            category_id=FUNPAY_CATEGORY_ID,
            offer_id=0,
            title=title,
            description=description,
            price=price,
            amount=1,
        )
        return lot.url

    async def delete_lot(self, lot_id: str) -> bool:
        """Удаляет (деактивирует) лот FunPay."""
        if not self.account:
            await self.init()

        try:
            await self.account.save_lot(
                category_id=FUNPAY_CATEGORY_ID,
                offer_id=lot_id,
                deleted=1,
            )
            return True
        except Exception as e:
            logging.error(f"Не удалось удалить лот {lot_id}: {e}")
            return False