import asyncio
import logging
from datetime import datetime
from sqlalchemy import select
from database.models import Account, RentalHistory
from database.session import async_session
from services.partner_service import on_rental_ended
from services.referral_service import process_referral_rewards
from web import notifications
from config import ADMIN_IDS


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
                    hist = (await session.execute(
                        select(RentalHistory).where(
                            RentalHistory.account_id == acc.id,
                            RentalHistory.ended_at.is_(None),
                        ).order_by(RentalHistory.started_at.desc())
                    )).scalar_one_or_none()

                    if hist:
                        hist.ended_at = now
                        hist.ended_reason = "expired"

                    await on_rental_ended(session, acc)
                    await process_referral_rewards(session, acc)

                    if acc.partner_id:
                        acc.status = "awaiting_review"
                    else:
                        acc.status = "awaiting_password_change"

                    acc.last_rental_ended_at = now
                    await session.commit()

                    notifications.push(
                        "Аренда окончена",
                        f"#{acc.id} · {acc.rank}",
                        level="warning",
                        category="partner" if acc.partner_id else "general",
                    )

                    if acc.partner_id:
                        from database.models import Partner
                        partner = await session.get(Partner, acc.partner_id)
                        if partner and partner.telegram_id:
                            try:
                                await bot.send_message(
                                    partner.telegram_id,
                                    f"⏰ *Аренда окончена*\n\n"
                                    f"Аккаунт #{acc.id} · {acc.rank}\n\n"
                                    f"Смени пароль от Riot Games и отправь его через "
                                    f"«🤝 Партнёрам» → «📁 Мои аккаунты» → «Сменить пароль».",
                                    parse_mode="Markdown",
                                )
                            except Exception as e:
                                logging.warning(f"Не смог уведомить партнёра {partner.telegram_id}: {e}")
                    else:
                        for admin_id in ADMIN_IDS:
                            try:
                                await bot.send_message(
                                    admin_id,
                                    f"⏰ Аренда окончена: #{acc.id} ({acc.rank}).\n"
                                    f"Смени пароль через веб-панель.",
                                )
                            except Exception:
                                pass

        except Exception as e:
            logging.error(f"rental_checker error: {e}")
        await asyncio.sleep(60)
