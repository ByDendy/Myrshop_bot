from aiogram import Bot
from config import ADMIN_IDS


async def notify_admin(bot: Bot, account, order=None):
    """
    Уведомление админам о новой аренде (CryptoBot или FunPay).
    Вызывается из payment_checker и funpay_watcher после успешной выдачи.
    """
    text = (
        f"🛒 Новая аренда!\n\n"
        f"Аккаунт: #{account.id} ({account.rank})\n"
        f"Логин: {account.login}\n"
        f"Покупатель ID: {account.buyer_id or 'FunPay'}\n"
        f"Срок: {account.rental_hours} ч\n"
        f"Партнёрский: {'да' if account.partner_id else 'нет'}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass
