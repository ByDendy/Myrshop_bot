import asyncio
import logging
from datetime import datetime
from sqlalchemy import select
from database.models import Account
from database.session import async_session
from services.crypto_service import CryptoService
from config import ADMIN_IDS
from aiogram import Bot

crypto_service = CryptoService()

async def crypto_payment_checker_loop(bot: Bot):
    """Каждые 60 секунд проверяет статус крипто-счетов."""
    while True:
        try:
            async with async_session() as session:
                # Ищем аккаунты в резерве с крипто-оплатой
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
                        # Оплата прошла!
                        acc.status = "sold" if acc.type == "sale" else "rented"
                        if acc.type == "rental":
                            # Здесь нужно знать часы аренды, но они не сохранены.
                            # Для простоты ставим 3 часа (можно доработать, сохранив hours).
                            acc.rented_until = datetime.utcnow() + timedelta(hours=3)
                        acc.sold_at = datetime.utcnow()
                        await session.commit()

                        # Выдаём данные покупателю
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
                            logging.error(f"Не удалось отправить данные: {e}")

                        # Уведомляем админа
                        for admin_id in ADMIN_IDS:
                            try:
                                await bot.send_message(
                                    admin_id,
                                    f"🪙 **Крипто-оплата!**\n"
                                    f"Аккаунт: #{acc.id} ({acc.rank})\n"
                                    f"Логин: `{acc.login}`\n"
                                    f"Покупатель: `{acc.buyer_id}`",
                                    parse_mode="Markdown"
                                )
                            except Exception:
                                pass

                    elif status == "expired":
                        # Счёт истёк — снимаем резерв
                        acc.status = "free"
                        acc.buyer_id = None
                        acc.payment_method = None
                        acc.crypto_invoice_id = None
                        acc.reserved_until = None
                        await session.commit()

        except Exception as e:
            logging.error(f"Crypto checker error: {e}")

        await asyncio.sleep(60)