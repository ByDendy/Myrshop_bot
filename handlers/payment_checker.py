import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from database.models import Account
from database.session import async_session
from services.cryptobot_service import CryptoBotService
from services.notifications import notify_admin


CHECK_INTERVAL = 30
EXPIRE_TIMEOUT = 70 * 60


async def payment_checker_loop(bot):
    cryptobot = CryptoBotService()

    while True:
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(Account).where(
                        Account.status == "reserved",
                        Account.rental_hours.isnot(None),
                        Account.payment_invoice_id.isnot(None),
                    )
                )
                pending = result.scalars().all()

                for acc in pending:
                    status = await cryptobot.get_invoice_status(
                        int(acc.payment_invoice_id)
                    )

                    if status == "paid":
                        await _deliver_account(bot, session, acc)
                    elif status == "expired":
                        await _release_account(session, acc, "счёт истёк")
                    elif status is None:
                        age = datetime.utcnow() - acc.created_at
                        if age > timedelta(seconds=EXPIRE_TIMEOUT):
                            await _release_account(session, acc, "таймаут")

        except Exception as e:
            logging.error(f"payment_checker error: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


async def _release_account(session, acc: Account, reason: str):
    acc.status = "free"
    acc.buyer_id = None
    acc.rental_hours = None
    acc.payment_invoice_id = None
    acc.reserved_at = None
    await session.commit()
    logging.info(f"Аккаунт #{acc.id} освобождён ({reason})")


async def _deliver_account(bot, session, acc: Account):
    hours = acc.rental_hours or 3
    acc.status = "rented"
    acc.rented_until = datetime.utcnow() + timedelta(hours=hours)
    await session.commit()

    text = (
        f"🎉 Оплата получена! Аккаунт #{acc.id}\n\n"
        f"Логин: {acc.login}\n"
        f"Пароль: {acc.password}\n"
        f"Ранг: {acc.rank}\n\n"
        f"⏱ Аренда действует до: "
        f"{acc.rented_until.strftime('%d.%m.%Y %H:%M')} UTC\n\n"
        f"Смените пароль после первого входа!"
    )

    try:
        await bot.send_message(acc.buyer_id, text)
    except Exception as e:
        logging.warning(f"Не смог отправить покупателю {acc.buyer_id}: {e}")

    await notify_admin(bot, acc)