from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func
from database.models import Customer, RentalHistory, Account
from keyboards.inline import main_menu
from config import WEB_BASE_URL

router = Router()


@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery, session):
    cust = await session.get(Customer, callback.from_user.id)
    if not cust:
        await callback.answer("Профиль не найден", show_alert=True)
        return

    stats = (await session.execute(
        select(
            func.count(RentalHistory.id),
            func.coalesce(func.sum(RentalHistory.amount), 0),
            func.coalesce(func.sum(RentalHistory.hours), 0)
        ).where(RentalHistory.buyer_id == callback.from_user.id)
    )).first()
    
    total_rentals = stats[0] or 0
    total_spent = round(stats[1] or 0, 2)
    total_hours = stats[2] or 0

    # Активные аренды
    active = (await session.execute(
        select(Account).where(
            Account.buyer_id == callback.from_user.id,
            Account.status == "rented"
        )
    )).scalars().all()
    
    active_text = ""
    if active:
        active_text = f"\n🟠 *Активных аренд:* {len(active)}\n"

    ref_link = f"https://t.me/{(await callback.bot.get_me()).username}?start=ref_{cust.telegram_id}"
    
    referrals_count = (await session.execute(
        select(func.count()).select_from(Customer).where(Customer.referred_by == cust.telegram_id)
    )).scalar() or 0

    text = (
        f"👤 *Твой профиль*\n\n"
        f"🆔 ID: `{cust.telegram_id}`\n"
        f"📅 С нами с: {cust.created_at.strftime('%d.%m.%Y')}\n\n"
        f"📊 *Статистика:*\n"
        f"• Всего аренд: {total_rentals}\n"
        f"• Потрачено: {total_spent:.0f} ₽\n"
        f"• Всего часов: {total_hours} ч\n"
        f"{active_text}\n"
        f"💰 *Бонусный баланс:* {cust.bonus_balance:.0f} ₽\n"
        f"_(можно тратить до 50% от суммы заказа)_\n\n"
        f"🎁 *Пригласи друга:*\n"
        f"Ты пригласил: {referrals_count} чел.\n"
        f"За каждого друга ты получаешь:\n"
        f"• 10% от его 1-го заказа\n"
        f"• +5 ₽ за каждый из следующих 10 заказов\n\n"
        f"🔗 Твоя ссылка:\n`{ref_link}`"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться ссылкой", url=f"https://t.me/share/url?url={ref_link}&text=Держи%20скидку%2010%25%20на%20аренду%20аккаунтов%20Valorant!")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")],
    ])

    await callback.message.delete()
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)