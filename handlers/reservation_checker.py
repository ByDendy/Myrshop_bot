import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from database.models import Account
from database.session import async_session


RESERVE_TIMEOUT = 15 * 60


async def reservation_checker_loop():
    while True:
        try:
            async with async_session() as session:
                cutoff = datetime.utcnow() - timedelta(seconds=RESERVE_TIMEOUT)
                result = await session.execute(
                    select(Account).where(
                        Account.status == "reserved",
                        Account.reserved_at <= cutoff,
                    )
                )
                expired = result.scalars().all()
                for acc in expired:
                    acc.status = "free"
                    acc.buyer_id = None
                    acc.rental_hours = None
                    acc.payment_invoice_id = None
                    acc.reserved_at = None
                    logging.info(f"Резерв #{acc.id} истёк, аккаунт освобождён")
                if expired:
                    await session.commit()
        except Exception as e:
            logging.error(f"reservation_checker error: {e}")
        await asyncio.sleep(60)