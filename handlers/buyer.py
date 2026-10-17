from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select, distinct
from database.models import Account
from keyboards.inline import (
    shop_menu, ranks_keyboard, accounts_keyboard,
    account_details_keyboard, payment_method_keyboard
)
from services.funpay_service import FunPayService
from services.crypto_service import CryptoService
from services.settings_service import get_rental_description
from config import RESERVE_MINUTES

router = Router()


@router.callback_query(F.data == "shop")
async def show_shop(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "🛒 Магазин\n\nВыберите нужную категорию:",
        reply_markup=shop_menu()
    )


@router.callback_query(F.data.in_({"shop_sale", "shop_rental"}))
async def show_ranks(callback: CallbackQuery, session):
    acc_type = "sale" if callback.data == "shop_sale" else "rental"
    result = await session.execute(
        select(distinct(Account.rank)).where(
            Account.type == acc_type, Account.status == "free"
        )
    )
    ranks = [row[0] for row in result.all()]
    if not ranks:
        await callback.answer("😔 В этой категории пока нет аккаунтов", show_alert=True)
        return
    title = "💰 Покупка аккаунта" if acc_type == "sale" else "⏱ Аренда аккаунта"
    await callback.message.delete()
    await callback.message.answer(
        f"{title}\n\nВыберите ранг:", reply_markup=ranks_keyboard(ranks, acc_type)
    )


@router.callback_query(F.data.startswith("rank|"))
async def show_accounts(callback: CallbackQuery, session):
    _, acc_type, rank = callback.data.split("|", 2)
    result = await session.execute(
        select(Account).where(
            Account.rank == rank, Account.type == acc_type, Account.status == "free"
        )
    )
    accounts = result.scalars().all()
    if not accounts:
        await callback.answer("Все аккаунты этого ранга заняты", show_alert=True)
        return
    category = "покупка" if acc_type == "sale" else "аренда"
    text = f"📋 Аккаунты ранга {rank} ({category}):\n\n"
    for acc in accounts:
        text += f"#{acc.id} — 🟢 Свободен\n"
    await callback.message.delete()
    await callback.message.answer(text, reply_markup=accounts_keyboard(accounts, acc_type, rank))


@router.callback_query(F.data.startswith("view|"))
async def view_account(callback: CallbackQuery, session):
    acc_id = int(callback.data.split("|")[1])
    account = await session.get(Account, acc_id)
    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return
    if account.status != "free":
        await callback.answer("Этот аккаунт уже занят", show_alert=True)
        return

    if account.type == "rental":
        template = await get_rental_description(session)
        body = template.replace("{rank}", account.rank)
        text = f"🎮 Аккаунт #{account.id}\n\n{body}\n\n"
        text += (
            f"💰 Аренда:\n"
            f"   • 3 часа — {account.price_3h:.0f} ₽\n"
            f"   • 6 часов — {account.price_6h:.0f} ₽\n"
            f"   • 12 часов — {account.price_12h:.0f} ₽"
        )
    else:
        text = (
            f"🎮 Аккаунт #{account.id}\n"
            f"Ранг: {account.rank}\n"
            f"Тип: Продажа\n\n"
            f"📝 {account.description or 'Без описания'}\n\n"
            f"💰 Цена: {account.price:.0f} ₽"
        )

    kb = account_details_keyboard(account, account.type)
    await callback.message.delete()
    if account.photo_id:
        await callback.message.answer_photo(photo=account.photo_id, caption=text, reply_markup=kb)
    else:
        await callback.message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("buy|"))
async def choose_payment_for_sale(callback: CallbackQuery):
    acc_id = int(callback.data.split("|")[1])
    await callback.message.delete()
    await callback.message.answer(
        "Выберите способ оплаты:",
        reply_markup=payment_method_keyboard(acc_id, action="sale")
    )


@router.callback_query(F.data.startswith("rent|"))
async def choose_payment_for_rental(callback: CallbackQuery):
    _, acc_id_str, hours_str = callback.data.split("|")
    await callback.message.delete()
    await callback.message.answer(
        f"Выберите способ оплаты для аренды на {hours_str} ч:",
        reply_markup=payment_method_keyboard(
            int(acc_id_str), action="rent", hours=int(hours_str)
        )
    )


@router.callback_query(F.data.startswith("pay_funpay|"))
async def pay_via_funpay(callback: CallbackQuery, session, funpay: FunPayService):
    _, action, acc_id_str, hours_str = callback.data.split("|")
    acc_id, hours = int(acc_id_str), int(hours_str)
    account = await session.get(Account, acc_id)
    if not account or account.status != "free":
        await callback.answer("Этот аккаунт уже занят!", show_alert=True)
        return

    price = account.price if action == "sale" else {
        3: account.price_3h, 6: account.price_6h, 12: account.price_12h
    }[hours]

    account.status = "reserved"
    account.buyer_id = callback.from_user.id
    account.payment_method = "funpay"
    account.reserved_until = datetime.utcnow() + timedelta(minutes=RESERVE_MINUTES)
    await session.commit()

    lot_url = await funpay.create_lot(
        account, hours=hours if action == "rent" else None, price=price
    )
    account.lot_id = lot_url.split("id=")[-1]
    await session.commit()

    await callback.message.delete()
    await callback.message.answer(
        f"✅ Аккаунт #{account.id} зарезервирован на {RESERVE_MINUTES} мин.\n\n"
        f"💰 Сумма: {price:.0f} ₽\n"
        f"🔗 Ссылка на оплату FunPay: {lot_url}\n\n"
        f"⏳ Если не оплатите в течение {RESERVE_MINUTES} минут — бронь снимется.\n\n"
        f"После оплаты бот автоматически выдаст данные."
    )


@router.callback_query(F.data.startswith("pay_crypto|"))
async def pay_via_crypto(callback: CallbackQuery, session, crypto: CryptoService):
    _, action, acc_id_str, hours_str = callback.data.split("|")
    acc_id, hours = int(acc_id_str), int(hours_str)
    account = await session.get(Account, acc_id)
    if not account or account.status != "free":
        await callback.answer("Этот аккаунт уже занят!", show_alert=True)
        return

    price = account.price if action == "sale" else {
        3: account.price_3h, 6: account.price_6h, 12: account.price_12h
    }[hours]

    invoice = await crypto.create_invoice(
        price, description=f"Аккаунт #{account.id} ({account.rank})"
    )
    if not invoice:
        await callback.answer("❌ Крипто-оплата временно недоступна. Попробуйте FunPay.", show_alert=True)
        return

    account.status = "reserved"
    account.buyer_id = callback.from_user.id
    account.payment_method = "crypto"
    account.crypto_invoice_id = invoice["invoice_id"]
    account.reserved_until = datetime.utcnow() + timedelta(minutes=RESERVE_MINUTES)
    await session.commit()

    await callback.message.delete()
    await callback.message.answer(
        f"✅ Аккаунт #{account.id} зарезервирован на {RESERVE_MINUTES} мин.\n\n"
        f"💰 Сумма: {price:.0f} ₽\n"
        f"🔗 Ссылка на оплату: {invoice['pay_url']}\n\n"
        f"⏳ Если не оплатите в течение {RESERVE_MINUTES} минут — бронь снимется.\n\n"
        f"После оплаты бот автоматически выдаст данные."
    )
