from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select, distinct
from datetime import datetime, timedelta
from database.models import Account, PaymentMethod, RentalHistory, Customer
from keyboards.inline import (
    tiers_keyboard, ranks_keyboard, accounts_keyboard,
    rental_keyboard, payment_methods_keyboard,
)
from services.funpay_service import FunPayService
from services.cryptobot_service import CryptoBotService
from services.settings_service import get_setting
from services.notifications import notify_admin
from web import notifications
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
async def show_shop(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "🛒 Выберите категорию аккаунтов:",
        reply_markup=tiers_keyboard(),
    )


@router.callback_query(F.data.startswith("tier|"))
async def show_ranks(callback: CallbackQuery, session):
    tier = callback.data.split("|")[1]
    result = await session.execute(
        select(distinct(Account.rank)).where(
            Account.tier == tier,
            Account.status == "free",
        )
    )
    ranks = [row[0] for row in result.all()]
    if not ranks:
        await callback.answer(
            "😔 В этой категории пока нет свободных аккаунтов", show_alert=True,
        )
        return

    title = "💎 Premium" if tier == "premium" else "🟢 Standard"
    await callback.message.delete()
    await callback.message.answer(
        f"{title}\n\nВыберите ранг:",
        reply_markup=ranks_keyboard(ranks, tier),
    )


@router.callback_query(F.data.startswith("rank|"))
async def show_accounts(callback: CallbackQuery, session):
    _, tier, rank = callback.data.split("|", 2)
    result = await session.execute(
        select(Account).where(
            Account.rank == rank,
            Account.tier == tier,
        )
    )
    accounts = result.scalars().all()

    free = [a for a in accounts if a.status == "free"]
    if not free:
        await callback.answer("Все аккаунты этого ранга заняты", show_alert=True)
        return

    text = f"📋 Аккаунты {rank}:\n\n"
    for acc in accounts:
        label = {
            "free": "🟢 Свободен", "reserved": "🟡 Бронь",
            "rented": "🟠 Арендован", "awaiting_password_change": "🔑 Готовится",
        }.get(acc.status, "❓")
        text += f"#{acc.id} — {label}\n"

    await callback.message.delete()
    await callback.message.answer(text, reply_markup=accounts_keyboard(accounts, tier))


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

    template = await get_setting(session, "description_template")
    desc = template.replace("{rank}", account.rank) if template else f"Аккаунт #{account.id}, ранг {account.rank}"
    tier_text = "💎 Premium" if account.tier == "premium" else "🟢 Standard"

    text = (
        f"{tier_text}\n{desc}\n\n"
        f"💰 Аренда:\n"
        f"   • 3 часа — {account.price_3h:.0f} ₽\n"
        f"   • 6 часов — {account.price_6h:.0f} ₽\n"
        f"   • 12 часов — {account.price_12h:.0f} ₽"
    )
    kb = rental_keyboard(account)
    await callback.message.delete()
    if account.photo_id:
        await callback.message.answer_photo(photo=account.photo_id, caption=text, reply_markup=kb)
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
        await callback.answer("😔 Способы оплаты временно недоступны.", show_alert=True)
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

    # ─── Проверка бана ───
    cust = await session.get(Customer, callback.from_user.id)
    if cust and cust.is_banned:
        await callback.answer(
            f"🚫 Вы заблокированы.\nПричина: {cust.ban_reason or 'не указана'}\n\n"
            f"Напишите в поддержку {SUPPORT_USERNAME}",
            show_alert=True,
        )
        return

    # ─── Регистрация/обновление покупателя ───
    if not cust:
        cust = Customer(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )
        session.add(cust)
    else:
        if callback.from_user.username:
            cust.username = callback.from_user.username
        if callback.from_user.first_name:
            cust.first_name = callback.from_user.first_name
    await session.commit()

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

    test_mode = await get_setting(session, "test_mode", "0")
    if test_mode == "1":
        account.status = "rented"
        account.buyer_id = callback.from_user.id
        account.rental_hours = hours
        account.rented_until = datetime.utcnow() + timedelta(hours=hours)
        account.reserved_at = None
        account.payment_invoice_id = None

        session.add(RentalHistory(
            account_id=account.id,
            buyer_id=callback.from_user.id,
            method="test",
            amount=price,
            hours=hours,
            started_at=datetime.utcnow(),
        ))
        await session.commit()

        notifications.push("🧪 Тестовая аренда", f"#{account.id} · {account.rank} · {hours}ч", level="warning")

        text = (
            f"⚠️ **ТЕСТОВЫЙ РЕЖИМ**\n"
            f"Оплата пропущена, аккаунт выдан!\n\n"
            f"🎮 Аккаунт #{account.id}\n"
            f"Логин: `{account.login}`\n"
            f"Пароль: `{account.password}`\n"
            f"Ранг: {account.rank}\n\n"
            f"⏱ Аренда до: {account.rented_until.strftime('%d.%m.%Y %H:%M')} UTC"
        )
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="Markdown")
        await notify_admin(callback.bot, account)
        return

    if method_code == "funpay":
        text = (
            f"🟡 Оплата через FunPay\n\n"
            f"Аккаунт: {account.rank}, аренда на {hours} ч\n"
            f"💰 Сумма: {price:.0f} ₽\n\n"
            f"🔗 Перейдите на FunPay и оплатите лот:\n"
            f"«{account.rank} — аренда {hours}ч»\n\n"
            f"После оплаты бот автоматически выдаст данные в чат FunPay."
        )
    elif method_code == "cryptobot":
        account.status = "reserved"
        account.buyer_id = callback.from_user.id
        account.rental_hours = hours
        account.reserved_at = datetime.utcnow()
        await session.commit()

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
                f"⏱ Счёт действует 15 минут.\n"
                f"После оплаты бот автоматически выдаст данные."
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
