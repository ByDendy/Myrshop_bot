import asyncio
import logging
from datetime import datetime
from sqlalchemy import select
from database.models import Account
from database.session import async_session
from services.funpay_service import FunPayService

funpay = FunPayService()


async def reservation_checker_loop():
    """Каждые 60 секунд снимает резервы, у которых истёк reserved_until."""
    while True:
        try:
            async with async_session() as session:
                now = datetime.utcnow()
                result = await session.execute(
                    select(Account).where(
                        Account.status == "reserved",
                        Account.reserved_until != None,
                        Account.reserved_until <= now,
                    )
                )
                expired = result.scalars().all()

                for acc in expired:
                    if acc.lot_id:
                        try:
                            await funpay.close_lot(acc.lot_id)
                        except Exception as e:
                            logging.warning(
                                f"Не удалось закрыть лот {acc.lot_id}: {e}"
                            )

                    acc.status = "free"
                    acc.buyer_id = None
                    acc.reserved_until = None
                    acc.lot_id = None

                if expired:
                    await session.commit()
                    logging.info(f"Освобождено {len(expired)} просроченных резервов")
        except Exception as e:
            logging.error(f"Reservation checker error: {e}")

        await asyncio.sleep(60)