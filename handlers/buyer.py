from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select, distinct
from datetime import datetime
from database.models import Account, PaymentMethod
from keyboards.inline import (
    ranks_keyboard, accounts_keyboard, rental_keyboard, payment_methods_keyboard,
)
from services.funpay_service import FunPayService
from services.cryptobot_service import CryptoBotService
from services.settings_service import get_setting
from config import SUPPORT_USERNAME

router = Router()


async def _get_enabled_methods(session):
    result = await session.execute(
        select(PaymentMethod)
        .where(PaymentMethod.enabled.is_(True))
        .order_by(PaymentMethod.order)
    )
    return result.scalars().all()


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

    # Глобальный шаблон описания с подстановкой ранга
    template = await get_setting(session, "description_template")
    if template:
        desc = template.replace("{rank}", account.rank)
    else:
        desc = account.description or f"Аккаунт #{account.id}, ранг {account.rank}"

    text = (
        f"{desc}\n\n"
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

    methods = await _get_enabled_methods(session)
    if not methods:
        await callback.answer(
            "😔 Способы оплаты временно недоступны. Свяжитесь с поддержкой.",
            show_alert=True,
        )
        return

    await callback.message.delete()
    await callback.message.answer(
        f"Аккаунт #{account.id} ({account.rank})\n"
        f"Аренда на {hours} ч — {price:.0f} ₽\n\n"
        f"Выберите способ оплаты:",
        reply_markup=payment_methods_keyboard(methods, acc_id, hours),
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

    # Проверяем, что способ включён
    method = (await session.execute(
        select(PaymentMethod).where(
            PaymentMethod.code == method_code,
            PaymentMethod.enabled.is_(True),
        )
    )).scalar_one_or_none()

    if not method:
        await callback.answer("Этот способ оплаты недоступен", show_alert=True)
        return

    price = {3: account.price_3h, 6: account.price_6h, 12: account.price_12h}[hours]

    account.status = "reserved"
    account.buyer_id = callback.from_user.id
    account.rental_hours = hours
    account.reserved_at = datetime.utcnow()
    await session.commit()

    if method_code == "funpay":
        text = (
            f"✅ Аккаунт #{account.id} зарезервирован на {hours} ч!\n\n"
            f"💰 Сумма: {price:.0f} ₽\n"
            f"🔗 Перейдите на FunPay и оплатите лот:\n"
            f"«{account.rank} — аренда {hours}ч»\n\n"
            f"После оплаты бот автоматически выдаст данные в чат FunPay."
        )
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
