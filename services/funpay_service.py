import asyncio
import logging
from aioFunPayAPI import Account as FunPayAccount
from config import FUNPAY_GOLDEN_KEY, FUNPAY_USER_AGENT, FUNPAY_CATEGORY_ID


class FunPayService:
    def __init__(self):
        self.account = None
        self._lock = asyncio.Lock()

    async def _ensure_init(self):
        async with self._lock:
            if not self.account:
                self.account = await FunPayAccount(
                    golden_key=FUNPAY_GOLDEN_KEY,
                    user_agent=FUNPAY_USER_AGENT,
                ).get()
        return self.account

    def _build_title(self, type_, rank, hours):
        if type_ == "sale":
            return f"Valorant аккаунт {rank} | полный доступ"
        return f"Аренда Valorant {rank} на {hours}ч | полный доступ"

    def _build_description(self, type_, rank, hours):
        if type_ == "sale":
            return (
                f"Аккаунт Valorant — ранг {rank}\n"
                "Полный доступ — логин, пароль от Riot Games\n"
                "Регион: Россия\n\n"
                "Выдача моментальная после оплаты.\n"
                "Гарантия и поддержка 24/7."
            )
        return (
            f"Аренда аккаунта Valorant — ранг {rank} на {hours} часов\n"
            "Полный доступ — логин, пароль от Riot Games\n"
            "Регион: Россия\n\n"
            "Выдача моментальная после оплаты.\n"
            "Гарантия и поддержка 24/7."
        )

    async def create_rank_lot(self, type_, rank, hours, price, amount):
        if FUNPAY_CATEGORY_ID == 0:
            logging.warning("FUNPAY_CATEGORY_ID не задан — автосоздание лотов отключено")
            return None
        try:
            acc = await self._ensure_init()
            lot = await acc.create_lot(
                category_id=FUNPAY_CATEGORY_ID,
                title=self._build_title(type_, rank, hours),
                description=self._build_description(type_, rank, hours),
                price=float(price),
                amount=int(amount),
            )
            logging.info(f"Создан лот {lot.id}: {type_} {rank} {hours}ч x{amount}")
            return str(lot.id)
        except Exception as e:
            logging.error(f"create_rank_lot error: {e}")
            return None

    async def update_lot(self, lot_id, price, amount):
        try:
            acc = await self._ensure_init()
            await acc.save_lot(
                lot_id=int(lot_id),
                price=float(price),
                amount=int(amount),
            )
            return True
        except Exception as e:
            logging.error(f"update_lot error: {e}")
            return False

    async def deactivate_lot(self, lot_id):
        try:
            acc = await self._ensure_init()
            await acc.save_lot(lot_id=int(lot_id), active=False)
            return True
        except Exception as e:
            logging.error(f"deactivate_lot error: {e}")
            return False

    async def activate_lot(self, lot_id, price, amount):
        try:
            acc = await self._ensure_init()
            await acc.save_lot(
                lot_id=int(lot_id),
                price=float(price),
                amount=int(amount),
                active=True,
            )
            return True
        except Exception as e:
            logging.error(f"activate_lot error: {e}")
            return False

    async def send_order_message(self, chat_id, text):
        try:
            acc = await self._ensure_init()
            await acc.send_message(chat_id=chat_id, text=text)
            return True
        except Exception as e:
            logging.error(f"send_order_message error: {e}")
            return False

    def lot_url(self, lot_id):
        return f"https://funpay.com/lots/offer?id={lot_id}"
