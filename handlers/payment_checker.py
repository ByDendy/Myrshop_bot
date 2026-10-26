import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select

from database.models import Account, RentalHistory
from database.session import async_session
from services.cryptobot_service import CryptoBotService
from services.notifications import notify_admin
from services.partner_service import on_rental_started
from services.promo_service import record_promo_use
from web import notifications


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
                        Account.payment_invoice_id.isnot(None),
                        Account.rental_hours.isnot(None),
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
    acc.promo_id = None
    acc.promo_discount = None
    await session.commit()
    logging.info(f"Аккаунт #{acc.id} освобождён ({reason})")


async def _deliver_account(bot, session, acc: Account):
    hours = acc.rental_hours or 3
    price = {
        3: acc.price_3h,
        6: acc.price_6h,
        12: acc.price_12h,
    }.get(hours, acc.price_3h)

    discount = acc.promo_discount or 0
    final_price = round(max(0, price - discount), 2)

    acc.status = "rented"
    acc.rented_until = datetime.utcnow() + timedelta(hours=hours)
    acc.payment_invoice_id = None
    acc.reserved_at = None

    rental = RentalHistory(
        account_id=acc.id,
        buyer_id=acc.buyer_id,
        method="cryptobot",
        amount=final_price,
        hours=hours,
        started_at=datetime.utcnow(),
    )
    session.add(rental)
    await session.flush()
    await session.commit()

    if acc.partner_id:
        await on_rental_started(session, acc, rental.id, final_price)

    if acc.promo_id:
        await record_promo_use(session, acc, "cryptobot")

    notifications.push(
        "Новая аренда (CryptoBot)",
        f"#{acc.id} · {acc.rank} · {hours}ч · {final_price:.0f} ₽",
        level="success",
        category="partner" if acc.partner_id else "general",
    )

    promo_line = f"\n🎟 Промокод: −{discount:.0f} ₽" if discount > 0 else ""
    text = (
        f"🎉 Оплата получена! Аккаунт #{acc.id}\n\n"
        f"Логин: {acc.login}\n"
        f"Пароль: {acc.password}\n"
        f"Ранг: {acc.rank}\n\n"
        f"💰 Оплачено: {final_price:.0f} ₽{promo_line}\n\n"
        f"⏱ Аренда действует до: "
        f"{acc.rented_until.strftime('%d.%m.%Y %H:%M')} UTC"
    )

    try:
        await bot.send_message(acc.buyer_id, text, parse_mode="Markdown")
    except Exception as e:
        logging.warning(f"Не смог отправить покупателю {acc.buyer_id}: {e}")

    await notify_admin(bot, acc)
    logging.info(f"CryptoBot: аккаунт #{acc.id} выдан (заказ оплачен)")
