import asyncio
import logging
from datetime import datetime
from sqlalchemy import select
from database.models import Account, RentalHistory
from database.session import async_session
from config import ADMIN_IDS
from web import notifications


async def rental_checker_loop(bot):
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
                    acc.status = "awaiting_password_change"

                    # Закрываем активную запись в истории
                    hist = (await session.execute(
                        select(RentalHistory).where(
                            RentalHistory.account_id == acc.id,
                            RentalHistory.ended_at.is_(None),
                        ).order_by(RentalHistory.started_at.desc())
                    )).scalar_one_or_none()
                    if hist:
                        hist.ended_at = now
                        hist.ended_reason = "expired"

                    await session.commit()

                    notifications.push(
                        "Аренда окончена",
                        f"#{acc.id} · {acc.rank} — смените пароль",
                        level="warning",
                    )

                    text = (
                        f"⏰ Аренда окончена!\n\n"
                        f"Аккаунт: #{acc.id} ({acc.rank})\n"
                        f"Смените пароль и отметьте в веб-панели."
                    )
                    for admin_id in ADMIN_IDS:
                        try:
                            await bot.send_message(admin_id, text)
                        except Exception:
                            pass
        except Exception as e:
            logging.error(f"rental_checker error: {e}")
        await asyncio.sleep(60)
