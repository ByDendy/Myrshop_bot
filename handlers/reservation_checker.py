import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from database.models import Account
from database.session import async_session
from services.cryptobot_service import CryptoBotService


RESERVE_TIMEOUT_MIN = 15


async def reservation_checker_loop(cryptobot: CryptoBotService):
    """
    Каждую минуту освобождает аккаунты, которые провисели в брони
    больше 15 минут и не были оплачены.
    Для CryptoBot-броней — сначала проверяет статус счёта,
    чтобы не освободить аккаунт, если пользователь уже оплатил,
    но payment_checker ещё не успел обработать.
    """
    while True:
        try:
            async with async_session() as session:
                cutoff = datetime.utcnow() - timedelta(minutes=RESERVE_TIMEOUT_MIN)
                result = await session.execute(
                    select(Account).where(
                        Account.status == "reserved",
                        Account.reserved_at <= cutoff,
                    )
                )
                expired = result.scalars().all()

                for acc in expired:
                    # Если есть активный CryptoBot-счёт — проверим, не оплачен ли он
                    if acc.payment_invoice_id:
                        status = await cryptobot.get_invoice_status(
                            int(acc.payment_invoice_id)
                        )
                        if status == "paid":
                            # Пусть payment_checker выдаст аккаунт
                            logging.info(
                                f"Резерв #{acc.id}: счёт оплачен, пропускаю, "
                                f"выдаст payment_checker"
                            )
                            continue

                    acc.status = "free"
                    acc.buyer_id = None
                    acc.rental_hours = None
                    acc.payment_invoice_id = None
                    acc.reserved_at = None
                    acc.lot_id = None
                    logging.info(
                        f"Резерв #{acc.id} истёк ({RESERVE_TIMEOUT_MIN} мин), "
                        f"аккаунт освобождён"
                    )
                if expired:
                    await session.commit()
        except Exception as e:
            logging.error(f"reservation_checker error: {e}")
        await asyncio.sleep(60)
