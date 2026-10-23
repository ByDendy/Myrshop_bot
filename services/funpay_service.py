import logging
from aioFunPayAPI import Account as FunPayAccount
from config import (
    FUNPAY_GOLDEN_KEY, FUNPAY_USER_AGENT, FUNPAY_CATEGORY_ID, FUNPAY_PROXY,
)


def _build_proxy(proxy_str):
    if not proxy_str:
        return None
    return {"http": proxy_str, "https": proxy_str}


class FunPayService:
    def __init__(self):
        self.account = None
        self._proxy = _build_proxy(FUNPAY_PROXY)

    async def init(self):
        kwargs = {
            "golden_key": FUNPAY_GOLDEN_KEY,
            "user_agent": FUNPAY_USER_AGENT,
        }
        if self._proxy:
            kwargs["proxy"] = self._proxy
        self.account = await FunPayAccount(**kwargs).get()

    async def get_account(self):
        if not self.account:
            await self.init()
        return self.account

    async def create_lot(self, rank: str, tier: str, hours: int, price: float) -> str:
        if not self.account:
            await self.init()

        tier_label = "💎 Premium" if tier == "premium" else "🟢 Standard"
        title = f"Valorant {tier_label} {rank} — аренда {hours}ч"
        description = (
            f"Аренда аккаунта Valorant ранга {rank} ({tier_label}) на {hours} часов.\n"
            f"После оплаты данные придут в чат автоматически."
        )

        lot = await self.account.create_lot(
            category_id=FUNPAY_CATEGORY_ID,
            title=title,
            description=description,
            price=price,
            amount=1,
        )
        return lot.url

    async def delete_lot(self, lot_id: str) -> bool:
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
