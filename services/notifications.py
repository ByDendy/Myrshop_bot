from aiogram import Bot
from config import ADMIN_IDS


async def notify_admin(bot: Bot, account, order=None):
    text = (
        f"🛒 Новая аренда!\n\n"
        f"Аккаунт: #{account.id} ({account.rank})\n"
        f"Логин: {account.login}\n"
        f"Покупатель: {account.buyer_id}\n"
        f"Срок: {account.rental_hours} ч"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass