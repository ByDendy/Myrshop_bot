from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select, distinct
from datetime import datetime
from database.models import Account
from keyboards.inline import (
    ranks_keyboard, accounts_keyboard, rental_keyboard, payment_methods_keyboard,
)
from services.funpay_service import FunPayService
from services.cryptobot_service import CryptoBotService
from config import SUPPORT_USERNAME

router = Router()


@router.callback_query(F.data == "shop")
async def show_shop(callback: CallbackQuery, session):
    result = await session.execute(
        select(distinct(Account.rank)).where(Account.status == "free")
    )
    ranks = [row[0] for row in result.all()]

    if not ranks:
        await callback.answer("😔 Пока нет свободных аккаунтов", show_alert=True)
        return

    await callback.message.delete()
    await callback.message.answer(
        "🛒 Выберите ранг аккаунта:",
        reply_markup=ranks_keyboard(ranks),
    )


@router.callback_query(F.data.startswith("rank|"))
async def show_accounts(callback: CallbackQuery, session):
    rank = callback.data.split("|", 1)[1]

    result = await session.execute(
        select(Account).where(Account.rank == rank)
    )
    accounts = result.scalars().all()

    free = [a for a in accounts if a.status == "free"]
    if not free:
        await callback.answer("Все аккаунты этого ранга заняты", show_alert=True)
        return

    text = f"📋 Аккаунты ранга {rank}:\n\n"
    for acc in accounts:
        if acc.status == "free":
            text += f"#{acc.id} — 🟢 Свободен\n"
        else:
            text += f"#{acc.id} — 🔴 Занят\n"

    await callback.message.delete()
    await callback.message.answer(
        text, reply_markup=accounts_keyboard(accounts, rank),
    )


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

    text = (
        f"🎮 Аккаунт #{account.id}\n"
        f"Ранг: {account.rank}\n\n"
        f"📝 {account.description or 'Без описания'}\n\n"
        f"💰 Аренда:\n"
        f"   • 3 часа — {account.price_3h:.0f} ₽\n"
        f"   • 6 часов — {account.price_6h:.0f} ₽\n"
        f"   • 12 часов — {account.price_12h:.0f} ₽"
    )

    kb = rental_keyboard(account)
    await callback.message.delete()

    if account.photo_id:
        await callback.message.answer_photo(
            photo=account.photo_id, caption=text, reply_markup=kb,
        )
    else:
        await callback.message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("rent|"))
async def rent_account(callback: CallbackQuery, session):
    _, acc_id_str, hours_str = callback.data.split("|")
    acc_id = int(acc_id_str)
    hours = int(hours_str)
    account = await session.get(Account, acc_id)

    if not account or account.status != "free":
        await callback.answer("Этот аккаунт уже занят!", show_alert=True)
        return

    price = {3: account.price_3h, 6: account.price_6h, 12: account.price_12h}[hours]

    await callback.message.delete()
    await callback.message.answer(
        f"Аккаунт #{account.id} ({account.rank})\n"
        f"Аренда на {hours} ч — {price:.0f} ₽\n\n"
        f"Выберите способ оплаты:",
        reply_markup=payment_methods_keyboard(acc_id, hours),
    )


@router.callback_query(F.data.startswith("pay|"))
async def handle_payment(
    callback: CallbackQuery,
    session,
    funpay: FunPayService,
    cryptobot: CryptoBotService,
):
    _, acc_id_str, hours_str, method_code = callback.data.split("|")
    acc_id = int(acc_id_str)
    hours = int(hours_str)
    account = await session.get(Account, acc_id)

    if not account or account.status != "free":
        await callback.answer("Этот аккаунт уже занят!", show_alert=True)
        return

    price = {3: account.price_3h, 6: account.price_6h, 12: account.price_12h}[hours]

    # Резервируем
    account.status = "reserved"
    account.buyer_id = callback.from_user.id
    account.rental_hours = hours
    account.reserved_at = datetime.utcnow()
    await session.commit()

    # ---------- FunPay ----------
    if method_code == "funpay":
        # Для FunPay мы не создаём новый лот на каждый заказ.
        # Покупатель должен купить существующий лот нужного ранга и часов.
        # Здесь просто показываем инструкцию.
        text = (
            f"✅ Аккаунт #{account.id} зарезервирован на {hours} ч!\n\n"
            f"💰 Сумма: {price:.0f} ₽\n"
            f"🔗 Перейдите на FunPay и оплатите лот:\n"
            f"«{account.rank} — аренда {hours}ч»\n\n"
            f"После оплаты бот автоматически выдаст данные в чат FunPay."
        )
        # Снимаем резерв, если оплата не будет произведена (через 15 минут reservation_checker)
    # ---------- CryptoBot ----------
    elif method_code == "cryptobot":
        try:
            title = f"MyrShop #{account.id} ({account.rank}) — {hours}ч"
            data = await cryptobot.create_invoice(price, title)
            if not data.get("ok"):
                raise RuntimeError(data.get("error", "неизвестная ошибка"))

            invoice = data["result"]
            account.payment_invoice_id = str(invoice["invoice_id"])
            await session.commit()

            text = (
                f"✅ Аккаунт #{account.id} зарезервирован на {hours} ч!\n\n"
                f"💰 Сумма: {price:.0f} ₽\n"
                f"🪙 Оплата через CryptoBot\n\n"
                f"🔗 Ссылка на оплату: {invoice['bot_invoice_url']}\n\n"
                f"Счёт действует 1 час. После оплаты бот автоматически выдаст данные."
            )
        except Exception as e:
            account.status = "free"
            account.buyer_id = None
            account.rental_hours = None
            account.reserved_at = None
            await session.commit()
            await callback.message.delete()
            await callback.message.answer(
                f"❌ Не удалось создать счёт CryptoBot.\nОшибка: {e}\n\n"
                f"Свяжитесь с {SUPPORT_USERNAME}."
            )
            return
    else:
        await callback.answer("Неизвестный способ оплаты", show_alert=True)
        return

    await callback.message.delete()
    await callback.message.answer(text)