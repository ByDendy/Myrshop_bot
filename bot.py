import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN
from database.session import init_db, async_session
from services.funpay_service import FunPayService
from services.cryptobot_service import CryptoBotService
from handlers import start, buyer, admin
from handlers.rental_checker import rental_checker_loop
from handlers.payment_checker import payment_checker_loop
from handlers.reservation_checker import reservation_checker_loop
from handlers.funpay_watcher import funpay_watcher_loop
from handlers.lot_manager import lot_manager_loop

logging.basicConfig(level=logging.INFO)


async def main():
    if not BOT_TOKEN:
        logging.error("❌ BOT_TOKEN не задан!")
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    funpay = FunPayService()
    cryptobot = CryptoBotService()

    async def session_middleware(handler, event, data):
        async with async_session() as session:
            data["session"] = session
            data["funpay"] = funpay
            data["cryptobot"] = cryptobot
            return await handler(event, data)

    dp.message.middleware(session_middleware)
    dp.callback_query.middleware(session_middleware)

    dp.include_router(start.router)
    dp.include_router(buyer.router)
    dp.include_router(admin.router)

    await init_db()

    asyncio.create_task(rental_checker_loop(bot))
    asyncio.create_task(payment_checker_loop(bot))
    asyncio.create_task(reservation_checker_loop(cryptobot))
    asyncio.create_task(funpay_watcher_loop(bot, funpay))
    asyncio.create_task(lot_manager_loop(funpay))

    logging.info("✅ MyrShop запущен: аренда + FunPay + CryptoBot + статусы")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
