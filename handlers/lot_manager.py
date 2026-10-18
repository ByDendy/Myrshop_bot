import asyncio
import logging
from sqlalchemy import select, func
from database.models import Account, Lot
from database.session import async_session
from services.funpay_service import FunPayService


CHECK_INTERVAL = 60  # раз в минуту


async def lot_manager_loop(funpay: FunPayService):
    while True:
        try:
            async with async_session() as session:
                # Все комбинации (rank, hours), для которых есть аккаунты
                combos = await session.execute(
                    select(Account.rank).distinct()
                )
                ranks = [row[0] for row in combos.all()]

                for rank in ranks:
                    for hours in (3, 6, 12):
                        # Свободные аккаунты этого ранга
                        free_result = await session.execute(
                            select(func.count(Account.id)).where(
                                Account.rank == rank,
                                Account.status == "free",
                            )
                        )
                        free_count = free_result.scalar() or 0

                        # Существующий лот
                        lot_result = await session.execute(
                            select(Lot).where(
                                Lot.rank == rank,
                                Lot.hours == hours,
                            )
                        )
                        lot = lot_result.scalar_one_or_none()

                        if free_count > 0:
                            # Нужен активный лот
                            if not lot or not lot.active:
                                # Берём цену из первого свободного аккаунта
                                acc_result = await session.execute(
                                    select(Account).where(
                                        Account.rank == rank,
                                        Account.status == "free",
                                    ).limit(1)
                                )
                                sample = acc_result.scalar_one_or_none()
                                if not sample:
                                    continue
                                price = {
                                    3: sample.price_3h,
                                    6: sample.price_6h,
                                    12: sample.price_12h,
                                }[hours]

                                try:
                                    url = await funpay.create_lot(rank, hours, price)
                                    lot_id = url.split("id=")[-1]

                                    if lot:
                                        lot.funpay_lot_id = lot_id
                                        lot.price = price
                                        lot.active = True
                                    else:
                                        lot = Lot(
                                            rank=rank,
                                            hours=hours,
                                            price=price,
                                            funpay_lot_id=lot_id,
                                            active=True,
                                        )
                                        session.add(lot)
                                    await session.commit()
                                    logging.info(f"📤 Лот создан: {rank} / {hours}ч")
                                except Exception as e:
                                    logging.error(f"❌ Ошибка создания лота {rank}/{hours}ч: {e}")
                        else:
                            # Свободных нет — лот не нужен
                            if lot and lot.active and lot.funpay_lot_id:
                                try:
                                    await funpay.delete_lot(lot.funpay_lot_id)
                                    lot.active = False
                                    await session.commit()
                                    logging.info(f"🗑 Лот закрыт: {rank} / {hours}ч")
                                except Exception as e:
                                    logging.error(f"❌ Ошибка удаления лота {rank}/{hours}ч: {e}")

        except Exception as e:
            logging.error(f"lot_manager error: {e}")

        await asyncio.sleep(CHECK_INTERVAL)