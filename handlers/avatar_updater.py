import asyncio
import logging
from sqlalchemy import select
from aiogram import Bot

from database.models import Customer, Partner
from database.session import async_session
from services.avatar_service import refresh_avatar


UPDATE_INTERVAL = 24 * 60 * 60  # 24 часа
BATCH_PAUSE = 1.0  # пауза между запросами (сек)


async def avatar_updater_loop(bot: Bot):
    await asyncio.sleep(300)  # первый запуск через 5 минут после старта

    while True:
        try:
            logging.info("🖼 Начинаю обновление аватарок…")
            updated_customers = 0
            updated_partners = 0

            async with async_session() as session:
                customers = (await session.execute(select(Customer))).scalars().all()
                for c in customers:
                    if await refresh_avatar(bot, c):
                        updated_customers += 1
                        await session.commit()
                    await asyncio.sleep(BATCH_PAUSE)

                partners = (await session.execute(select(Partner))).scalars().all()
                for p in partners:
                    if await refresh_avatar(bot, p):
                        updated_partners += 1
                        await session.commit()
                    await asyncio.sleep(BATCH_PAUSE)

            logging.info(
                f"✅ Аватарки: покупателей — {updated_customers}, "
                f"партнёров — {updated_partners}"
            )

        except Exception as e:
            logging.error(f"avatar_updater error: {e}")

        await asyncio.sleep(UPDATE_INTERVAL)