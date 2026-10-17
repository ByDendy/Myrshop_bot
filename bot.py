import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN
from database.session import init_db, async_session
from services.funpay_service import FunPayService
from services.crypto_service import CryptoService
from services.settings_service import seed_defaults
from services.lot_manager import lot_manager_loop
from services.order_watcher import order_watcher_loop
from handlers import start, buyer, admin
from handlers.rental_checker import rental_checker_loop
from handlers.reservation_checker import reservation_checker_loop
from handlers.crypto_checker import crypto_payment_checker_loop

logging.basicConfig(level=logging.INFO)


async def main():
    if not BOT_TOKEN:
        logging.error("❌ BOT_TOKEN не задан")
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    funpay = FunPayService()
    crypto = CryptoService()

    async def session_middleware(handler, event, data):
        async with async_session() as session:
            data["session"] = session
            data["funpay"] = funpay
            data["crypto"] = crypto
            return await handler(event, data)

    dp.message.middleware(session_middleware)
    dp.callback_query.middleware(session_middleware)

    dp.include_router(start.router)
    dp.include_router(buyer.router)
    dp.include_router(admin.router)

    await init_db()
    async with async_session() as session:
        await seed_defaults(session)

    # Фоновые задачи
    asyncio.create_task(reservation_checker_loop())
    asyncio.create_task(rental_checker_loop())
    asyncio.create_task(crypto_payment_checker_loop(bot))
    asyncio.create_task(lot_manager_loop())
    asyncio.create_task(order_watcher_loop(bot, funpay))

    logging.info("✅ Бот запущен (лоты per-rank + FunPay + Крипта)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
