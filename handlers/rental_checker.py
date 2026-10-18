import asyncio
import logging
from datetime import datetime
from sqlalchemy import select
from database.models import Account
from database.session import async_session


async def rental_checker_loop():
    while True:
        try:
            async with async_session() as session:
                now = datetime.utcnow()
                result = await session.execute(
                    select(Account).where(
                        Account.status == "rented",
                        Account.rented_until <= now,
                    )
                )
                expired = result.scalars().all()
                for acc in expired:
                    acc.status = "free"
                    acc.buyer_id = None
                    acc.rented_until = None
                    acc.rental_hours = None
                if expired:
                    await session.commit()
                    logging.info(f"Освобождено {len(expired)} аккаунтов после аренды")
        except Exception as e:
            logging.error(f"rental_checker error: {e}")
        await asyncio.sleep(60)