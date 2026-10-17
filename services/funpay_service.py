from aioFunPayAPI import Account as FunPayAccount
from config import FUNPAY_GOLDEN_KEY, FUNPAY_USER_AGENT


class FunPayService:
    def __init__(self):
        self.account = None

    async def init(self):
        self.account = await FunPayAccount(
            golden_key=FUNPAY_GOLDEN_KEY,
            user_agent=FUNPAY_USER_AGENT,
        ).get()

    async def create_lot(self, account, hours: int = None, price: float = None) -> str:
        if not self.account:
            await self.init()

        if hours:
            title = f"Valorant аккаунт {account.rank} — аренда {hours}ч"
            final_price = price or {
                3: account.price_3h, 6: account.price_6h, 12: account.price_12h,
            }[hours]
        else:
            title = f"Valorant аккаунт {account.rank}"
            final_price = price or account.price

        lot = await self.account.create_lot(
            category_id=...,  # ← сюда вставь реальный ID раздела Valorant на FunPay
            title=title,
            description=account.description or f"Ранг: {account.rank}",
            price=final_price,
            amount=1,
        )
        return lot.url
