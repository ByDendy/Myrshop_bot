import asyncio
import logging
from datetime import datetime
from sqlalchemy import select
from database.models import Account
from database.session import async_session
from config import ADMIN_IDS


async def rental_checker_loop(bot):
    """
    Каждую минуту проверяет аккаунты с истёкшей арендой.
    - Переводит статус в 'awaiting_password_change'
    - Уведомляет админа о необходимости сменить пароль
    """
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
                    await session.commit()

                    logging.info(
                        f"Аренда #{acc.id} окончена, ожидает смены пароля"
                    )

                    text = (
                        f"⏰ Аренда окончена!\n\n"
                        f"Аккаунт: #{acc.id} ({acc.rank})\n"
                        f"Логин: {acc.login}\n"
                        f"Пароль: {acc.password}\n"
                        f"Срок аренды: {acc.rental_hours or '?'} ч\n\n"
                        f"⚠️ Смените пароль и верните аккаунт в свободные "
                        f"через /admin → «🔑 Ожидают смены пароля»."
                    )
                    for admin_id in ADMIN_IDS:
                        try:
                            await bot.send_message(admin_id, text)
                        except Exception as e:
                            logging.warning(
                                f"Не смог уведомить админа {admin_id}: {e}"
                            )
        except Exception as e:
            logging.error(f"rental_checker error: {e}")
        await asyncio.sleep(60)
