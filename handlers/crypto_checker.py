import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from database.models import Account
from database.session import async_session
from services.crypto_service import CryptoService
from services.lot_manager import sync_one
from config import ADMIN_IDS

crypto_service = CryptoService()


async def crypto_payment_checker_loop(bot):
    while True:
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(Account).where(
                        Account.status == "reserved",
                        Account.payment_method == "crypto",
                        Account.crypto_invoice_id != None,
                    )
                )
                accounts = result.scalars().all()

                for acc in accounts:
                    status = await crypto_service.get_invoice_status(acc.crypto_invoice_id)

                    if status == "paid":
                        acc.status = "sold" if acc.type == "sale" else "rented"
                        if acc.type == "rental":
                            acc.rented_until = datetime.utcnow() + timedelta(hours=3)
                        acc.sold_at = datetime.utcnow()
                        await session.commit()

                        try:
                            await bot.send_message(
                                acc.buyer_id,
                                f"🎉 Оплата получена!\n\n"
                                f"Логин: `{acc.login}`\n"
                                f"Пароль: `{acc.password}`\n\n"
                                f"Смените пароль после первого входа!",
                                parse_mode="Markdown"
                            )
                        except Exception as e:
                            logging.error(f"send creds error: {e}")

                        for admin_id in ADMIN_IDS:
                            try:
                                await bot.send_message(
                                    admin_id,
                                    f"🪙 Крипто-оплата\n"
                                    f"Аккаунт: #{acc.id} ({acc.rank})\n"
                                    f"Покупатель: `{acc.buyer_id}`",
                                    parse_mode="Markdown"
                                )
                            except Exception:
                                pass

                        if acc.type == "rental":
                            for h in (3, 6, 12):
                                await sync_one(session, "rental", acc.rank, h)
                        else:
                            await sync_one(session, "sale", acc.rank, None)

                    elif status == "expired":
                        acc.status = "free"
                        acc.buyer_id = None
                        acc.payment_method = None
                        acc.crypto_invoice_id = None
                        acc.reserved_until = None
                        await session.commit()

                        if acc.type == "rental":
                            for h in (3, 6, 12):
                                await sync_one(session, "rental", acc.rank, h)
                        else:
                            await sync_one(session, "sale", acc.rank, None)

        except Exception as e:
            logging.error(f"Crypto checker error: {e}")

        await asyncio.sleep(60)
