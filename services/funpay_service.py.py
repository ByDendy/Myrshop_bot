from aioFunPayAPI import Account as FunPayAccount
from config import FUNPAY_GOLDEN_KEY, FUNPAY_USER_AGENT

class FunPayService:
    def __init__(self):
        self.account = None

    async def init(self):
        self.account = await FunPayAccount(
            golden_key=FUNPAY_GOLDEN_KEY,
            user_agent=FUNPAY_USER_AGENT
        ).get()

    async def create_lot(self, account) -> str:
        if not self.account:
            await self.init()

        lot = await self.account.create_lot(
            category_id=612,  # ID категории Valorant на FunPay
            title=f"Valorant аккаунт {account.rank}",
            description=f"Ранг: {account.rank}\nСервер: EU\nСмена почты: да",
            price=account.price,
            amount=1
        )
        return lot.url
