import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from database.models import Account, Order, RankLot
from database.session import async_session
from services.funpay_service import FunPayService
from config import ADMIN_IDS


async def order_watcher_loop(bot, funpay: FunPayService):
    try:
        from aioFunPayAPI import Runner
    except ImportError:
        logging.warning("Runner недоступен — автовыдача FunPay отключена")
        return

    for attempt in range(10):
        try:
            account = await funpay._ensure_init()
            break
        except Exception as e:
            logging.warning(f"FunPay init ({attempt + 1}/10): {e}")
            await asyncio.sleep(30)
    else:
        logging.error("FunPay init failed — order_watcher отключён")
        return

    try:
        runner = Runner(account, requests_delay=2.0)
        async for event in runner.run(ignore_init_events=True):
            try:
                if getattr(event, "type", None) == "NEW_ORDER":
                    await process_paid_order(event.order, bot, funpay)
            except Exception as e:
                logging.error(f"order event error: {e}")
    except Exception as e:
        logging.error(f"Runner crashed: {e}")


async def process_paid_order(order, bot, funpay):
    order_id = str(order.id)
    lot_id = str(order.lot_id)

    async with async_session() as session:
        q = select(Order).where(Order.funpay_order == order_id)
        if (await session.execute(q)).scalar():
            return

        q = select(RankLot).where(RankLot.lot_id == lot_id)
        rank_lot = (await session.execute(q)).scalar()
        if not rank_lot:
            logging.warning(f"Order {order_id}: unknown lot {lot_id}")
            return

        q = select(Account).where(
            Account.type == rank_lot.type,
            Account.rank == rank_lot.rank,
            Account.status == "free",
        ).limit(1)
        account = (await session.execute(q)).scalar()

        if not account:
            logging.error(f"Order {order_id}: no free accounts for {rank_lot.rank}")
            await funpay.send_order_message(
                order.chat_id,
                "К сожалению, товар закончился. Оформим возврат средств через FunPay."
            )
            return

        if rank_lot.type == "sale":
            account.status = "sold"
            account.sold_at = datetime.utcnow()
        else:
            account.status = "rented"
            account.rented_until = datetime.utcnow() + timedelta(hours=rank_lot.hours or 3)

        account.order_id = order_id
        account.payment_method = "funpay"

        session.add(Order(
            account_id=account.id,
            buyer_id=0,
            funpay_order=order_id,
            amount=float(order.price),
            status="completed",
        ))
        await session.commit()

        msg = (
            f"✅ Спасибо за покупку!\n\n"
            f"Логин: {account.login}\n"
            f"Пароль: {account.password}\n\n"
            f"Смените пароль после первого входа."
        )
        if rank_lot.type == "rental":
            msg += f"\n\nАренда на {rank_lot.hours} ч. По окончании доступ будет закрыт."

        await funpay.send_order_message(order.chat_id, msg)

        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"💳 FunPay-продажа\n"
                    f"Аккаунт #{account.id} ({account.rank})\n"
                    f"Логин: {account.login}\n"
                    f"Сумма: {order.price} ₽"
                )
            except Exception:
                pass

        from services.lot_manager import sync_one
        await sync_one(session, rank_lot.type, rank_lot.rank, rank_lot.hours)