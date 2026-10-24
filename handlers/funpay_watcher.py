import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select

from aioFunPayAPI import Runner


class EventTypes:
    NEW_ORDER = 6


class OrderStatuses:
    PAID = 0


from database.models import Account, RentalHistory
from database.session import async_session
from services.funpay_service import FunPayService
from services.notifications import notify_admin
from services.partner_service import on_rental_started
from web import notifications


async def funpay_watcher_loop(bot, funpay: FunPayService):
    while True:
        try:
            acc = await funpay.get_account()
            runner = Runner(acc)

            async for event in runner.listen(requests_delay=15.0):
                if event.type != EventTypes.NEW_ORDER:
                    continue

                clean_id = event.order.id.replace("#", "")

                if event.order.status != OrderStatuses.PAID:
                    logging.info(f"Заказ {clean_id} ещё не оплачен")
                    continue

                order_info = await acc.get_order(clean_id)
                desc = order_info.description or ""

                rank, hours = _parse_lot_description(desc)
                if not rank or not hours:
                    logging.warning(
                        f"Заказ {clean_id}: не удалось распарсить «{desc[:100]}»"
                    )
                    continue

                async with async_session() as session:
                    result = await session.execute(
                        select(Account).where(
                            Account.rank == rank,
                            Account.rental_hours == hours,
                            Account.status == "reserved",
                        ).limit(1)
                    )
                    account = result.scalar_one_or_none()

                    if not account:
                        result = await session.execute(
                            select(Account).where(
                                Account.rank == rank,
                                Account.status == "free",
                            ).limit(1)
                        )
                        account = result.scalar_one_or_none()

                    if not account:
                        logging.error(
                            f"Заказ {clean_id}: нет аккаунтов для {rank} / {hours}ч"
                        )
                        try:
                            await acc.send_message(
                                order_info.chat_id,
                                "⚠️ Свободных аккаунтов нет. "
                                "Напишите в поддержку для возврата.",
                            )
                        except Exception:
                            pass
                        continue

                    price = {
                        3: account.price_3h,
                        6: account.price_6h,
                        12: account.price_12h,
                    }.get(hours, account.price_3h)

                    account.status = "rented"
                    account.buyer_id = None
                    account.rental_hours = hours
                    account.rented_until = datetime.utcnow() + timedelta(hours=hours)
                    account.payment_invoice_id = None
                    account.reserved_at = None

                    rental = RentalHistory(
                        account_id=account.id,
                        buyer_id=None,
                        method="funpay",
                        amount=price,
                        hours=hours,
                        started_at=datetime.utcnow(),
                    )
                    session.add(rental)
                    await session.flush()  # получаем rental.id
                    await session.commit()

                    if account.partner_id:
                        await on_rental_started(session, account, rental.id, price)

                    notifications.push(
                        "Новая аренда (FunPay)",
                        f"#{account.id} · {account.rank} · {hours}ч · {price:.0f} ₽",
                        level="success",
                        category="partner" if account.partner_id else "general",
                    )

                    funpay_text = (
                        f"Привет, {order_info.buyer_username}!\n\n"
                        f"Данные твоего аккаунта:\n"
                        f"Логин: {account.login}\n"
                        f"Пароль: {account.password}\n"
                        f"Ранг: {account.rank}\n\n"
                        f"⏱ Аренда до: "
                        f"{account.rented_until.strftime('%d.%m.%Y %H:%M')} UTC"
                    )
                    try:
                        await acc.send_message(order_info.chat_id, funpay_text)
                    except Exception as e:
                        logging.error(f"Не смог отправить в FunPay: {e}")

                    await notify_admin(bot, account)
                    logging.info(
                        f"FunPay: аккаунт #{account.id} выдан по заказу {clean_id}"
                    )

        except Exception as e:
            err = str(e)
            if "Ошибка запроса" in err:
                logging.warning(
                    "funpay_watcher: FunPay не отвечает корректно, "
                    "переподключение через 60 сек"
                )
                await asyncio.sleep(60)
            else:
                logging.error(f"funpay_watcher error: {err[:300]}")
                await asyncio.sleep(30)


def _parse_lot_description(desc: str):
    try:
        if "ранга" in desc and " на " in desc and "час" in desc:
            rank = desc.split("ранга ")[1].split(" на ")[0].strip()
            hours = int(desc.split(" на ")[1].split(" час")[0].strip())
            return rank, hours
    except Exception:
        pass
    return None, None
