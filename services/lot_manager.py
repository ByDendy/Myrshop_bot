import asyncio
import logging
from sqlalchemy import select, func, distinct
from database.models import Account, RankLot
from database.session import async_session
from services.funpay_service import FunPayService

funpay = FunPayService()
_sync_lock = asyncio.Lock()

PRICE_FIELDS = {
    ("sale", None): Account.price,
    ("rental", 3): Account.price_3h,
    ("rental", 6): Account.price_6h,
    ("rental", 12): Account.price_12h,
}


async def sync_one(session, type_, rank, hours):
    price_field = PRICE_FIELDS.get((type_, hours))
    if price_field is None:
        return

    q = select(func.count()).select_from(Account).where(
        Account.type == type_,
        Account.rank == rank,
        Account.status == "free",
    )
    count = (await session.execute(q)).scalar() or 0

    q = select(RankLot).where(
        RankLot.type == type_,
        RankLot.rank == rank,
        RankLot.hours == hours,
    )
    rank_lot = (await session.execute(q)).scalar()

    if count == 0:
        if rank_lot and rank_lot.lot_id and rank_lot.active:
            ok = await funpay.deactivate_lot(rank_lot.lot_id)
            if ok:
                rank_lot.active = False
                await session.commit()
                logging.info(f"Лот {rank_lot.lot_id} снят (пул {rank} пуст)")
        return

    q = select(func.min(price_field)).where(
        Account.type == type_,
        Account.rank == rank,
        Account.status == "free",
    )
    price = (await session.execute(q)).scalar() or 0
    if price <= 0:
        return

    if not rank_lot:
        rank_lot = RankLot(type=type_, rank=rank, hours=hours, active=False)
        session.add(rank_lot)
        await session.flush()

    if not rank_lot.lot_id:
        lot_id = await funpay.create_rank_lot(type_, rank, hours, price, count)
        if lot_id:
            rank_lot.lot_id = lot_id
            rank_lot.active = True
            rank_lot.last_error = None
        else:
            rank_lot.last_error = "create failed"
        await session.commit()
    elif rank_lot.active:
        await funpay.update_lot(rank_lot.lot_id, price, count)
    else:
        ok = await funpay.activate_lot(rank_lot.lot_id, price, count)
        if ok:
            rank_lot.active = True
            await session.commit()


async def sync_all(session):
    async with _sync_lock:
        q = select(distinct(Account.rank)).where(Account.type == "sale")
        sale_ranks = [r for (r,) in (await session.execute(q)).all()]

        q = select(distinct(Account.rank)).where(Account.type == "rental")
        rental_ranks = [r for (r,) in (await session.execute(q)).all()]

        q = select(RankLot)
        existing = (await session.execute(q)).scalars().all()

        done = set()

        for r in sale_ranks:
            key = ("sale", r, None)
            if key in done: continue
            done.add(key)
            try:
                await sync_one(session, "sale", r, None)
            except Exception as e:
                logging.error(f"sync sale {r}: {e}")
            await asyncio.sleep(1.5)

        for r in rental_ranks:
            for h in (3, 6, 12):
                key = ("rental", r, h)
                if key in done: continue
                done.add(key)
                try:
                    await sync_one(session, "rental", r, h)
                except Exception as e:
                    logging.error(f"sync rental {r} {h}: {e}")
                await asyncio.sleep(1.5)

        for rl in existing:
            key = (rl.type, rl.rank, rl.hours)
            if key in done: continue
            done.add(key)
            try:
                await sync_one(session, rl.type, rl.rank, rl.hours)
            except Exception as e:
                logging.error(f"sync existing {rl.rank}: {e}")
            await asyncio.sleep(1.5)


async def sync_for_account(session, account):
    """Вызывать сразу после добавления/удаления/смены статуса аккаунта."""
    try:
        if account.type == "rental":
            for h in (3, 6, 12):
                await sync_one(session, "rental", account.rank, h)
                await asyncio.sleep(1.5)
        else:
            await sync_one(session, "sale", account.rank, None)
    except Exception as e:
        logging.error(f"sync_for_account error: {e}")


async def lot_manager_loop():
    while True:
        try:
            async with async_session() as session:
                await sync_all(session)
        except Exception as e:
            logging.error(f"lot_manager error: {e}")
        await asyncio.sleep(60)