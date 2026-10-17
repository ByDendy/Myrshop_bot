from aiogram import Bot
from config import ADMIN_IDS

async def notify_admin(bot: Bot, account, order):
    text = (
        f"🛒 **Новая покупка!**\n\n"
        f"Аккаунт: #{account.id} ({account.rank})\n"
        f"Логин: `{account.login}`\n"
        f"Покупатель: `{account.buyer_id}`\n"
        f"Сумма: {account.price} ₽"
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="Markdown")
        except Exception:
            pass