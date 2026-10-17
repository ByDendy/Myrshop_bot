from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select, distinct
from database.models import Account
from keyboards.inline import ranks_keyboard, accounts_keyboard, main_menu
from services.funpay_service import FunPayService

router = Router()

@router.callback_query(F.data == "main_menu")
async def back_to_menu(callback: CallbackQuery):
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu())

@router.callback_query(F.data == "buy_account")
async def show_ranks(callback: CallbackQuery, session):
    result = await session.execute(select(distinct(Account.rank)))
    ranks = [row[0] for row in result.all()]

    if not ranks:
        await callback.message.edit_text(
            "😔 Пока нет доступных аккаунтов.\nЗагляни позже!",
            reply_markup=main_menu()
        )
        return

    await callback.message.edit_text(
        "Выбери ранг аккаунта:",
        reply_markup=ranks_keyboard(ranks)
    )

@router.callback_query(F.data.startswith("rank_"))
async def show_accounts(callback: CallbackQuery, session):
    rank = callback.data.replace("rank_", "")
    result = await session.execute(
        select(Account).where(Account.rank == rank)
    )
    accounts = result.scalars().all()

    text = f"📋 Аккаунты ранга {rank}:\n\n"
    free_count = 0
    for acc in accounts:
        status = "🟢 Свободен" if acc.status == "free" else "🔴 Занят"
        if acc.status == "free":
            free_count += 1
        text += f"#{acc.id} — {status}\n"

    if free_count == 0:
        text += "\n😔 Все аккаунты этого ранга заняты."

    await callback.message.edit_text(text, reply_markup=accounts_keyboard(accounts))

@router.callback_query(F.data.startswith("buy_"))
async def buy_account(callback: CallbackQuery, session, funpay: FunPayService):
    acc_id = int(callback.data.replace("buy_", ""))
    account = await session.get(Account, acc_id)

    if not account or account.status != "free":
        await callback.answer("Этот аккаунт уже занят!", show_alert=True)
        return

    account.status = "reserved"
    account.buyer_id = callback.from_user.id
    await session.commit()

    lot_url = await funpay.create_lot(account)
    account.lot_id = lot_url.split("id=")[-1]
    await session.commit()

    await callback.message.edit_text(
        f"✅ Аккаунт зарезервирован!\n\n"
        f"💰 Сумма к оплате: {account.price} ₽\n"
        f"🔗 Ссылка на оплату: {lot_url}\n\n"
        f"После оплаты бот автоматически выдаст данные."
    )