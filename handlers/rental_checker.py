import asyncio
import logging
from datetime import datetime
from sqlalchemy import select
from database.models import Account
from database.session import async_session
from services.lot_manager import sync_one


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

                ranks_to_sync = set()
                for acc in expired:
                    acc.status = "free"
                    acc.buyer_id = None
                    acc.rented_until = None
                    ranks_to_sync.add(acc.rank)

                if expired:
                    await session.commit()
                    logging.info(f"Освобождено после аренды: {len(expired)}")
                    for rank in ranks_to_sync:
                        for h in (3, 6, 12):
                            await sync_one(session, "rental", rank, h)
        except Exception as e:
            logging.error(f"Rental checker error: {e}")

        await asyncio.sleep(60)
