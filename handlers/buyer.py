from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, distinct, func
from datetime import datetime, timedelta
from database.models import Account, PaymentMethod, RentalHistory, Customer, Promocode
from keyboards.inline import (
    tiers_keyboard, ranks_keyboard, accounts_keyboard,
    rental_keyboard, rent_step_keyboard,
    payment_methods_keyboard, payment_methods_with_promo_keyboard,
)
from services.funpay_service import FunPayService
from services.cryptobot_service import CryptoBotService
from services.settings_service import get_setting
from services.notifications import notify_admin
from services.partner_service import on_rental_started
from services.avatar_service import refresh_avatar
from services.promo_service import validate_promo, record_promo_use
from services.referral_service import calculate_checkout_discount, apply_bonus_spend
from web import notifications
from config import SUPPORT_USERNAME

router = Router()


class PromoCode(StatesGroup):
    wait_code = State()


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

    await callback.message.delete()
    await callback.message.answer(
        f"Аккаунт #{account.id} ({account.rank})\n"
        f"Аренда на {hours} ч\n\n"
        f"💰 Сумма: {price:.0f} ₽\n\n"
        f"Есть промокод? Примените его перед оплатой.",
        reply_markup=rent_step_keyboard(acc_id, hours),
    )


@router.callback_query(F.data.startswith("apply_promo|"))
async def apply_promo_start(callback: CallbackQuery, state: FSMContext, session):
    _, acc_id_str, hours_str = callback.data.split("|")

    methods = await _get_enabled_methods(session)
    if not any(m.code == "cryptobot" for m in methods):
        await callback.answer(
            "Промокоды доступны только при оплате через CryptoBot. "
            "Сейчас этот способ отключён.",
            show_alert=True,
        )
        return

    await state.set_state(PromoCode.wait_code)
    await state.update_data(acc_id=int(acc_id_str), hours=int(hours_str))
    await callback.message.delete()
    await callback.message.answer(
        "🎟 *Введите промокод* одним сообщением.\n\n"
        "Например: `SUMMER15`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"rent|{acc_id_str}|{hours_str}")],
        ]),
    )


@router.message(PromoCode.wait_code)
async def apply_promo_process(message: Message, state: FSMContext, session):
    code = (message.text or "").strip().upper()
    data = await state.get_data()
    acc_id = data.get("acc_id")
    hours = data.get("hours")

    if not acc_id or not hours:
        await message.answer("❌ Ошибка: сессия устарела. Начните заново.")
        await state.clear()
        return

    account = await session.get(Account, acc_id)
    if not account or account.status != "free":
        await message.answer("❌ Аккаунт больше не доступен. Начните заново.")
        await state.clear()
        return

    price = {3: account.price_3h, 6: account.price_6h, 12: account.price_12h}[hours]
    promo, discount, error = await validate_promo(
        session, code, message.from_user.id, hours, price
    )

    if error:
        await message.answer(
            f"❌ *{error}*\n\n"
            f"Попробуйте другой код или нажмите «Отмена».",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data=f"rent|{acc_id}|{hours}")],
            ]),
        )
        return

    final_price = round(price - discount, 2)
    await state.clear()

    methods = await _get_enabled_methods(session)
    await message.answer(
        f"✅ Промокод *{promo.code}* применён!\n\n"
        f"💰 Скидка: {discount:.0f} ₽\n"
        f"💵 К оплате: *{final_price:.0f} ₽* (вместо {price:.0f} ₽)\n\n"
        f"Выберите способ оплаты:",
        parse_mode="Markdown",
        reply_markup=payment_methods_with_promo_keyboard(
            methods, acc_id, hours, promo.id
        ),
    )


@router.callback_query(F.data.startswith("choose_method|"))
async def choose_method(callback: CallbackQuery, session):
    _, acc_id_str, hours_str, promo_id_str = callback.data.split("|")
    acc_id = int(acc_id_str)
    hours = int(hours_str)
    promo_id = int(promo_id_str)

    account = await session.get(Account, acc_id)
    if not account or account.status != "free":
        await callback.answer("Этот аккаунт уже занят!", show_alert=True)
        return

    original_price = {3: account.price_3h, 6: account.price_6h, 12: account.price_12h}[hours]
    price_after_promo = original_price
    promo_text = ""

    if promo_id > 0:
        result = await session.execute(select(Promocode).where(Promocode.id == promo_id))
        promo = result.scalar_one_or_none()
        if promo:
            _, discount, error = await validate_promo(
                session, promo.code, callback.from_user.id, hours, original_price
            )
            if not error:
                price_after_promo = round(original_price - discount, 2)
                promo_text = f"\n🎟 Промокод: *{promo.code}* (−{discount:.0f} ₽)"
            else:
                promo_id = 0
                promo_text = "\n⚠️ Промокод больше не действует"

    orders_count = (await session.execute(
        select(func.count(RentalHistory.id)).where(RentalHistory.buyer_id == callback.from_user.id)
    )).scalar() or 0
    is_first_order = (orders_count == 0)

    welcome_disc, bonus_spent, final_price, bonus_left = await calculate_checkout_discount(
        session, callback.from_user.id, price_after_promo, is_first_order
    )

    discount_lines = []
    if promo_text: discount_lines.append(promo_text.strip())
    if welcome_disc > 0: discount_lines.append(f"🎁 Приветств. скидка: −{welcome_disc:.0f} ₽")
    if bonus_spent > 0: discount_lines.append(f"💰 Бонусы: −{bonus_spent:.0f} ₽")
    
    discount_text = "\n" + "\n".join(discount_lines) if discount_lines else ""

    methods = await _get_enabled_methods(session)
    await callback.message.delete()
    await callback.message.answer(
        f"Аккаунт #{account.id} ({account.rank})\n"
        f"Аренда на {hours} ч\n\n"
        f"💰 Сумма: *{final_price:.0f} ₽*{discount_text}\n\n"
        f"Выберите способ оплаты:",
        parse_mode="Markdown",
        reply_markup=payment_methods_with_promo_keyboard(
            methods, acc_id, hours, promo_id
        ),
    )


@router.callback_query(F.data.startswith("pay|"))
async def handle_payment(
    callback: CallbackQuery,
    session,
    funpay: FunPayService,
    cryptobot: CryptoBotService,
):
    parts = callback.data.split("|")
    if len(parts) == 5:
        _, acc_id_str, hours_str, method_code, promo_id_str = parts
        promo_id = int(promo_id_str)
    else:
        _, acc_id_str, hours_str, method_code = parts
        promo_id = 0

    acc_id = int(acc_id_str)
    hours = int(hours_str)
    account = await session.get(Account, acc_id)

    if not account or account.status != "free":
        await callback.answer("Этот аккаунт уже занят!", show_alert=True)
        return

    if promo_id > 0 and method_code == "funpay":
        await callback.answer(
            "Промокод применяется только при оплате через CryptoBot. "
            "Выберите CryptoBot или вернитесь назад.",
            show_alert=True,
        )
        return

    cust = await session.get(Customer, callback.from_user.id)
    if cust and cust.is_banned:
        await callback.answer(
            f"🚫 Вы заблокированы.\nПричина: {cust.ban_reason or 'не указана'}\n\n"
            f"Напишите в поддержку {SUPPORT_USERNAME}",
            show_alert=True,
        )
        return

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

    if await refresh_avatar(callback.bot, cust):
        pass
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

    original_price = {3: account.price_3h, 6: account.price_6h, 12: account.price_12h}[hours]
    promo_discount = 0

    if promo_id > 0 and method_code == "cryptobot":
        result = await session.execute(select(Promocode).where(Promocode.id == promo_id))
        promo = result.scalar_one_or_none()
        if promo:
            _, discount, error = await validate_promo(
                session, promo.code, callback.from_user.id, hours, original_price
            )
            if not error:
                promo_discount = discount
            else:
                promo_id = 0

    price_after_promo = original_price - promo_discount

    orders_count = (await session.execute(
        select(func.count(RentalHistory.id)).where(RentalHistory.buyer_id == callback.from_user.id)
    )).scalar() or 0
    is_first_order = (orders_count == 0)

    welcome_disc, bonus_spent, final_price, bonus_left = await calculate_checkout_discount(
        session, callback.from_user.id, price_after_promo, is_first_order
    )

    test_mode = await get_setting(session, "test_mode", "0")
    price = final_price

    if test_mode == "1":
        account.status = "rented"
        account.buyer_id = callback.from_user.id
        account.rental_hours = hours
        account.rented_until = datetime.utcnow() + timedelta(hours=hours)
        account.reserved_at = None
        account.payment_invoice_id = None
        account.final_price = price
        account.bonus_spent = bonus_spent
        if promo_id > 0:
            account.promo_id = promo_id
            account.promo_discount = promo_discount

        rental = RentalHistory(
            account_id=account.id,
            buyer_id=callback.from_user.id,
            method="test",
            amount=price,
            hours=hours,
            started_at=datetime.utcnow(),
        )
        session.add(rental)
        await session.flush()
        await session.commit()

        if account.partner_id:
            await on_rental_started(session, account, rental.id, price)

        if promo_id > 0:
            await record_promo_use(session, account, "test")
            
        if bonus_spent > 0:
            await apply_bonus_spend(session, callback.from_user.id, bonus_spent, f"Аренда #{account.id}")

        notifications.push(
            "🧪 Тестовая аренда",
            f"#{account.id} · {account.rank} · {hours}ч",
            level="warning",
        )

        discount_lines = []
        if promo_discount > 0: discount_lines.append(f"🎟 Промо: −{promo_discount:.0f} ₽")
        if welcome_disc > 0: discount_lines.append(f"🎁 Приветств: −{welcome_disc:.0f} ₽")
        if bonus_spent > 0: discount_lines.append(f"💰 Бонусы: −{bonus_spent:.0f} ₽")
        discount_str = "\n" + "\n".join(discount_lines) if discount_lines else ""

        text = (
            f"⚠️ **ТЕСТОВЫЙ РЕЖИМ**\n"
            f"Оплата пропущена, аккаунт выдан!\n\n"
            f"🎮 Аккаунт #{account.id}\n"
            f"Логин: `{account.login}`\n"
            f"Пароль: `{account.password}`\n"
            f"Ранг: {account.rank}\n\n"
            f"💰 Оплачено: {price:.0f} ₽{discount_str}\n\n"
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
        account.final_price = price
        account.bonus_spent = bonus_spent
        if promo_id > 0:
            account.promo_id = promo_id
            account.promo_discount = promo_discount
        await session.commit()

        try:
            title = f"VARendy #{account.id} ({account.rank}) — {hours}ч"
            if promo_discount > 0:
                title += f" (промо −{promo_discount:.0f}₽)"
            data = await cryptobot.create_invoice(price, title)
            if not data.get("ok"):
                raise RuntimeError(data.get("error", "неизвестная ошибка"))

            invoice = data["result"]
            account.payment_invoice_id = str(invoice["invoice_id"])
            await session.commit()
            
            # СПИСЫВАЕМ БОНУСЫ ЗДЕСЬ, чтобы зарезервировать их
            if bonus_spent > 0:
                await apply_bonus_spend(session, callback.from_user.id, bonus_spent, f"Оплата аренды #{account.id}")

            discount_lines = []
            if promo_discount > 0: discount_lines.append(f"🎟 Промо: −{promo_discount:.0f} ₽")
            if welcome_disc > 0: discount_lines.append(f"🎁 Приветств: −{welcome_disc:.0f} ₽")
            if bonus_spent > 0: discount_lines.append(f"💰 Бонусы: −{bonus_spent:.0f} ₽")
            discount_str = "\n" + "\n".join(discount_lines) if discount_lines else ""

            text = (
                f"✅ Аккаунт #{account.id} зарезервирован на {hours} ч!\n\n"
                f"💰 Сумма: *{price:.0f} ₽*{discount_str}\n"
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
            account.promo_id = None
            account.promo_discount = None
            account.final_price = None
            account.bonus_spent = None
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
    await callback.message.answer(text, parse_mode="Markdown")