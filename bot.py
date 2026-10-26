import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web
from config import BOT_TOKEN, FUNPAY_AUTO_LOTS_ENABLED, WEB_PORT, WEB_ADMIN_PASSWORD
from database.session import init_db, async_session
from services.funpay_service import FunPayService
from services.cryptobot_service import CryptoBotService
from handlers import start, buyer, admin, partner, profile
from handlers.rental_checker import rental_checker_loop
from handlers.payment_checker import payment_checker_loop
from handlers.reservation_checker import reservation_checker_loop
from handlers.funpay_watcher import funpay_watcher_loop
from handlers.lot_manager import lot_manager_loop
from handlers.avatar_updater import avatar_updater_loop
from web.server import create_web_app

logging.basicConfig(level=logging.INFO)

_tasks = []

async def main():
    if not BOT_TOKEN:
        logging.error("❌ BOT_TOKEN не задан!")
        sys.exit(1)
    if not WEB_ADMIN_PASSWORD:
        logging.warning("⚠️ WEB_ADMIN_PASSWORD не задан — веб-панель отключена")
        web_enabled = False
    else:
        web_enabled = True

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
    dp.include_router(partner.router)
    dp.include_router(profile.router) # <--- ИСПРАВЛЕНИЕ ПУНКТА 5

    await init_db()

    _tasks.append(asyncio.create_task(rental_checker_loop(bot)))
    _tasks.append(asyncio.create_task(payment_checker_loop(bot)))
    _tasks.append(asyncio.create_task(reservation_checker_loop(cryptobot)))
    _tasks.append(asyncio.create_task(avatar_updater_loop(bot)))
    
    # Отключаем funpay_watcher и lot_manager, если в Railway стоит FUNPAY_AUTO_LOTS_ENABLED=false
    if FUNPAY_AUTO_LOTS_ENABLED:
        _tasks.append(asyncio.create_task(funpay_watcher_loop(bot, funpay))) # Включаем только вместе с лотами
        _tasks.append(asyncio.create_task(lot_manager_loop(funpay)))
        logging.info("✅ Автосоздание лотов FunPay: ВКЛЮЧЕНО")
    else:
        logging.warning("⚠️ Автосоздание лотов FunPay: ВЫКЛЮЧЕНО (и watcher отключён)")

    if web_enabled:
        try:
            app = create_web_app(bot)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", WEB_PORT)
            await site.start()
            logging.info(f"✅ Веб-панель: http://0.0.0.0:{WEB_PORT}")
        except Exception as e:
            logging.error(f"❌ Веб-панель не запустилась: {e}")

    logging.info("✅ VARendy запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())