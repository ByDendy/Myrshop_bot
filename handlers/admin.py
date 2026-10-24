import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from database.models import Account, PaymentMethod, RentalHistory, Partner
from keyboards.inline import admin_payments_keyboard
from services.settings_service import get_setting, set_setting
from services.funpay_service import FunPayService
from services.partner_service import on_rental_ended
from handlers.lot_manager import run_lot_manager_cycle
from web import notifications
from config import ADMIN_IDS

router = Router()


class AddAccount(StatesGroup):
    tier = State()
    login = State()
    password = State()
    rank = State()
    photo = State()
    prices = State()


class BulkUpload(StatesGroup):
    tier = State()
    photo = State()
    wait_data = State()


class EditTemplate(StatesGroup):
    wait_text = State()


class ChangePassword(StatesGroup):
    new_password = State()


def cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_menu")]
    ])


async def admin_menu(session):
    test_mode = await get_setting(session, "test_mode", "0")
    test_icon = "🟢 ВКЛ" if test_mode == "1" else "🔴 ВЫКЛ"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="admin_add")],
        [InlineKeyboardButton(text="📥 Массовая загрузка", callback_data="admin_bulk")],
        [InlineKeyboardButton(text="📋 Список аккаунтов", callback_data="admin_list")],
        [InlineKeyboardButton(text="🗑 Удалить аккаунт", callback_data="admin_delete")],
        [InlineKeyboardButton(text="🔓 Снять все брони", callback_data="admin_unlock")],
        [InlineKeyboardButton(text="⏹ Завершить все аренды", callback_data="admin_end_all_rentals")],
        [InlineKeyboardButton(text="🔑 Ожидают смены пароля", callback_data="admin_awaiting")],
        [InlineKeyboardButton(text="💳 Способы оплаты", callback_data="admin_payments")],
        [InlineKeyboardButton(text="📝 Шаблон описания", callback_data="admin_template")],
        [InlineKeyboardButton(text=f"🧪 Тестовый режим: {test_icon}", callback_data="admin_test_mode")],
    ])


def tier_keyboard(prefix: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Standard", callback_data=f"{prefix}|standard")],
        [InlineKeyboardButton(text="💎 Premium (со скинами)", callback_data=f"{prefix}|premium")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_menu")],
    ])


async def _trigger_lot_manager(funpay: FunPayService):
    try:
        await run_lot_manager_cycle(funpay)
    except Exception as e:
        logging.error(f"lot_manager после действия админа: {e}")


@router.message(Command("admin"), F.from_user.id.in_(ADMIN_IDS))
async def admin_panel(message: Message, session):
    await message.answer("🔧 Админ-панель:", reply_markup=await admin_menu(session))


@router.callback_query(F.data == "admin_menu")
async def back_admin(callback: CallbackQuery, state: FSMContext, session):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("🔧 Админ-панель:", reply_markup=await admin_menu(session))


@router.callback_query(F.data == "admin_test_mode")
async def toggle_test_mode(callback: CallbackQuery, session):
    current = await get_setting(session, "test_mode", "0")
    new_val = "0" if current == "1" else "1"
    await set_setting(session, "test_mode", new_val)
    status = "ВКЛЮЧЕН" if new_val == "1" else "ВЫКЛЮЧЕН"
    await callback.answer(f"🧪 Тестовый режим {status}", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=await admin_menu(session))


# ---------- ЗАВЕРШЕНИЕ ВСЕХ АРЕНД ----------

@router.callback_query(F.data == "admin_end_all_rentals")
async def end_all_rentals(callback: CallbackQuery, session, funpay: FunPayService):
    result = await session.execute(select(Account).where(Account.status == "rented"))
    rented = result.scalars().all()
    count = len(rented)

    if count == 0:
        await callback.answer("Нет активных аренд", show_alert=True)
        return

    now = datetime.utcnow()
    for acc in rented:
        # Закрываем историю аренды
        hist = (await session.execute(
            select(RentalHistory).where(
                RentalHistory.account_id == acc.id,
                RentalHistory.ended_at.is_(None)
            ).order_by(RentalHistory.started_at.desc())
        )).scalar_one_or_none()
        
        if hist:
            hist.ended_at = now
            hist.ended_reason = "manual"

        # Размораживаем партнёрские начисления
        await on_rental_ended(session, acc)

        # Меняем статус аккаунта
        if acc.partner_id:
            acc.status = "awaiting_review"
        else:
            acc.status = "awaiting_password_change"
        
        acc.last_rental_ended_at = now
        await session.commit()

        # Уведомление партнёру
        if acc.partner_id:
            partner = await session.get(Partner, acc.partner_id)
            if partner and partner.telegram_id:
                try:
                    await callback.bot.send_message(
                        partner.telegram_id,
                        f"⏰ *Аренда окончена (вручную администратором)*\n\n"
                        f"Аккаунт #{acc.id} · {acc.rank}\n\n"
                        f"Смени пароль от Riot Games и отправь его через "
                        f"«🤝 Партнёрам» → «📁 Мои аккаунты» → «Сменить пароль».",
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logging.warning(f"Не смог уведомить партнёра {partner.telegram_id}: {e}")
        
        notifications.push(
            "Аренда завершена вручную", 
            f"#{acc.id} · {acc.rank}", 
            level="warning", 
            category="partner" if acc.partner_id else "general"
        )

    await callback.answer(f"✅ Завершено аренд: {count}", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=await admin_menu(session))
    await _trigger_lot_manager(funpay)


# ---------- ДОБАВЛЕНИЕ ----------

@router.callback_query(F.data == "admin_add")
async def add_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddAccount.tier)
    await callback.message.delete()
    await callback.message.answer("Выберите тип аккаунта:", reply_markup=tier_keyboard("add_tier"))


@router.callback_query(AddAccount.tier, F.data.startswith("add_tier|"))
async def add_tier(callback: CallbackQuery, state: FSMContext):
    tier = callback.data.split("|")[1]
    await state.update_data(tier=tier)
    await state.set_state(AddAccount.login)
    await callback.message.delete()
    await callback.message.answer("Введите логин аккаунта:", reply_markup=cancel_kb())


@router.message(AddAccount.login)
async def add_login(message: Message, state: FSMContext):
    await state.update_data(login=message.text.strip())
    await state.set_state(AddAccount.password)
    await message.answer("Введите пароль:", reply_markup=cancel_kb())


@router.message(AddAccount.password)
async def add_password(message: Message, state: FSMContext):
    await state.update_data(password=message.text.strip())
    await state.set_state(AddAccount.rank)
    await message.answer("Введите ранг (например, Diamond 1):", reply_markup=cancel_kb())


@router.message(AddAccount.rank)
async def add_rank(message: Message, state: FSMContext):
    await state.update_data(rank=message.text.strip())
    await state.set_state(AddAccount.photo)
    await message.answer("Отправьте фото товара.\nИли напишите «нет», чтобы пропустить.", reply_markup=cancel_kb())


@router.message(AddAccount.photo)
async def add_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id if message.photo else None
    await state.update_data(photo_id=photo_id)
    await state.set_state(AddAccount.prices)
    await message.answer("Введите цены аренды через пробел: 3ч 6ч 12ч\nПример: 100 150 250", reply_markup=cancel_kb())


@router.message(AddAccount.prices)
async def add_prices(message: Message, state: FSMContext, session, funpay: FunPayService):
    try:
        prices = [float(x.replace(",", ".")) for x in message.text.split()]
        if len(prices) != 3:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите три числа через пробел. Пример: 100 150 250", reply_markup=cancel_kb())
        return

    data = await state.get_data()
    account = Account(
        login=data["login"], password=data["password"],
        rank=data["rank"], photo_id=data["photo_id"],
        tier=data["tier"],
        price_3h=prices[0], price_6h=prices[1], price_12h=prices[2],
        status="free",
    )
    session.add(account)
    await session.commit()
    await state.clear()

    await message.answer(f"✅ Аккаунт #{account.id} добавлен!", reply_markup=await admin_menu(session))
    await _trigger_lot_manager(funpay)


# ---------- МАССОВАЯ ЗАГРУЗКА ----------

@router.callback_query(F.data == "admin_bulk")
async def bulk_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BulkUpload.tier)
    await callback.message.delete()
    await callback.message.answer("Выберите тип для загружаемых аккаунтов:", reply_markup=tier_keyboard("bulk_tier"))


@router.callback_query(BulkUpload.tier, F.data.startswith("bulk_tier|"))
async def bulk_tier(callback: CallbackQuery, state: FSMContext):
    tier = callback.data.split("|")[1]
    await state.update_data(tier=tier)
    await state.set_state(BulkUpload.photo)
    await callback.message.delete()
    await callback.message.answer(
        "📥 Шаг 1 из 2: отправьте фото для всех аккаунтов.\nИли напишите «нет».",
        reply_markup=cancel_kb()
    )


@router.message(BulkUpload.photo)
async def bulk_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id if message.photo else None
    await state.update_data(photo_id=photo_id)
    await state.set_state(BulkUpload.wait_data)
    await message.answer(
        "Шаг 2 из 2: отправьте список.\n"
        "`login;;password;;rank;;100,150,250`\n\n"
        "Пример:\n`user1;;pass1;;Diamond 1;;100,150,250`",
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )


@router.message(BulkUpload.wait_data)
async def bulk_process(message: Message, state: FSMContext, session, funpay: FunPayService):
    data = await state.get_data()
    photo_id = data.get("photo_id")
    tier = data.get("tier", "standard")
    lines = message.text.strip().split("\n")
    created = 0
    errors = []

    for i, line in enumerate(lines, 1):
        parts = line.strip().split(";;")
        if len(parts) != 4:
            errors.append(f"Строка {i}: нужно 4 части через `;;`")
            continue
        login, password, rank, prices_str = [p.strip() for p in parts]
        try:
            prices = [float(x.replace(",", ".")) for x in prices_str.split(",")]
            if len(prices) != 3:
                raise ValueError
        except ValueError:
            errors.append(f"Строка {i}: цены должны быть 3 числа через запятую")
            continue

        session.add(Account(
            login=login, password=password, rank=rank, photo_id=photo_id,
            tier=tier,
            price_3h=prices[0], price_6h=prices[1], price_12h=prices[2], status="free",
        ))
        created += 1

    await session.commit()
    await state.clear()
    result = f"✅ Загружено: {created} ({'premium' if tier == 'premium' else 'standard'})"
    if errors:
        result += "\n\n⚠️ Ошибки:\n" + "\n".join(errors[:10])
    await message.answer(result, reply_markup=await admin_menu(session))
    if created > 0:
        await message.answer("⏳ Создаю лоты…")
        await _trigger_lot_manager(funpay)


# ---------- СПИСОК / УДАЛЕНИЕ / ОЖИДАНИЕ ----------

@router.callback_query(F.data == "admin_list")
async def list_accounts(callback: CallbackQuery, session):
    result = await session.execute(select(Account).order_by(Account.tier, Account.rank, Account.id))
    accounts = result.scalars().all()
    await callback.message.delete()
    if not accounts:
        await callback.message.answer("📭 Аккаунтов нет.", reply_markup=await admin_menu(session))
        return
    emoji = {"free": "🟢", "reserved": "🟡", "rented": "🟠", "awaiting_password_change": "🔑"}
    text = "📋 Все аккаунты:\n\n"
    for a in accounts:
        tier_icon = "💎" if a.tier == "premium" else "🟢"
        text += f"{emoji.get(a.status, '❓')}{tier_icon} #{a.id} | {a.rank} | {a.login}\n"
    await callback.message.answer(text, reply_markup=await admin_menu(session))


def _delete_keyboard(accounts):
    buttons = [[InlineKeyboardButton(text=f"🗑 #{a.id} — {a.rank} ({a.tier})", callback_data=f"del|{a.id}")] for a in accounts]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _show_delete_menu(callback: CallbackQuery, session):
    result = await session.execute(select(Account).order_by(Account.id))
    accounts = result.scalars().all()
    await callback.message.delete()
    if not accounts:
        await callback.message.answer("📭 Нет аккаунтов.", reply_markup=await admin_menu(session))
        return
    await callback.message.answer("Выберите аккаунт для удаления:", reply_markup=_delete_keyboard(accounts))


@router.callback_query(F.data == "admin_delete")
async def delete_menu(callback: CallbackQuery, session):
    await _show_delete_menu(callback, session)


@router.callback_query(F.data.startswith("del|"))
async def do_delete(callback: CallbackQuery, session, funpay: FunPayService):
    acc_id = int(callback.data.split("|")[1])
    account = await session.get(Account, acc_id)
    if account:
        await session.delete(account)
        await session.commit()
    await callback.answer(f"✅ #{acc_id} удалён", show_alert=True)
    await _show_delete_menu(callback, session)
    await _trigger_lot_manager(funpay)


@router.callback_query(F.data == "admin_unlock")
async def unlock_all_reservations(callback: CallbackQuery, session, funpay: FunPayService):
    result = await session.execute(select(Account).where(Account.status == "reserved"))
    reserved = result.scalars().all()
    for acc in reserved:
        acc.status = "free"
        acc.buyer_id = None
        acc.rental_hours = None
        acc.payment_invoice_id = None
        acc.reserved_at = None
        acc.lot_id = None
    await session.commit()
    await callback.answer(f"✅ Освобождено: {len(reserved)}", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=await admin_menu(session))
    if reserved:
        await _trigger_lot_manager(funpay)


def _awaiting_keyboard(accounts):
    buttons = []
    for acc in accounts:
        tier_icon = "💎" if acc.tier == "premium" else "🟢"
        buttons.append([InlineKeyboardButton(text=f"{tier_icon} #{acc.id} — {acc.rank}", callback_data=f"chpw|{acc.id}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "admin_awaiting")
async def awaiting_menu(callback: CallbackQuery, session):
    result = await session.execute(select(Account).where(Account.status == "awaiting_password_change").order_by(Account.id))
    accounts = result.scalars().all()
    await callback.message.delete()
    if not accounts:
        await callback.message.answer("🔑 Нет аккаунтов.", reply_markup=await admin_menu(session))
        return
    await callback.message.answer("🔑 Ожидают смены пароля:", reply_markup=_awaiting_keyboard(accounts))


@router.callback_query(F.data.startswith("chpw|"))
async def change_password_start(callback: CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split("|")[1])
    await state.update_data(acc_id=acc_id)
    await state.set_state(ChangePassword.new_password)
    await callback.message.delete()
    await callback.message.answer(f"Введите новый пароль для #{acc_id}:", reply_markup=cancel_kb())


@router.message(ChangePassword.new_password)
async def change_password_save(message: Message, state: FSMContext, session, funpay: FunPayService):
    data = await state.get_data()
    acc_id = data["acc_id"]
    account = await session.get(Account, acc_id)
    if account:
        account.password = message.text.strip()
        account.status = "free"
        account.buyer_id = None
        account.rental_hours = None
        account.rented_until = None
        account.reserved_at = None
        account.payment_invoice_id = None
        await session.commit()
    await state.clear()
    await message.answer(f"✅ Пароль для #{acc_id} обновлён.", reply_markup=await admin_menu(session))
    await _trigger_lot_manager(funpay)


# ---------- ОПЛАТА / ШАБЛОН ----------

@router.callback_query(F.data == "admin_payments")
async def payments_menu(callback: CallbackQuery, session):
    result = await session.execute(select(PaymentMethod).order_by(PaymentMethod.order))
    methods = result.scalars().all()
    await callback.message.delete()
    await callback.message.answer("💳 Способы оплаты:", reply_markup=admin_payments_keyboard(methods))


@router.callback_query(F.data.startswith("toggle_pay|"))
async def toggle_payment(callback: CallbackQuery, session):
    method_id = int(callback.data.split("|")[1])
    method = await session.get(PaymentMethod, method_id)
    if method:
        method.enabled = not method.enabled
        await session.commit()
    result = await session.execute(select(PaymentMethod).order_by(PaymentMethod.order))
    methods = result.scalars().all()
    await callback.answer(f"{method.name} теперь {'включён' if method.enabled else 'выключен'}")
    await callback.message.edit_reply_markup(reply_markup=admin_payments_keyboard(methods))


@router.callback_query(F.data == "admin_template")
async def template_menu(callback: CallbackQuery, session):
    current = await get_setting(session, "description_template", "")
    await callback.message.delete()
    await callback.message.answer(
        f"📝 Текущий шаблон:\n\n`{current}`\n\nИспользуйте `{{rank}}`.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить", callback_data="template_edit")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")],
        ]),
    )


@router.callback_query(F.data == "template_edit")
async def template_edit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditTemplate.wait_text)
    await callback.message.delete()
    await callback.message.answer("Отправьте новый шаблон:", reply_markup=cancel_kb())


@router.message(EditTemplate.wait_text)
async def template_save(message: Message, state: FSMContext, session):
    if len(message.text) < 10:
        await message.answer("❌ Слишком короткий.", reply_markup=cancel_kb())
        return
    await set_setting(session, "description_template", message.text)
    await state.clear()
    await message.answer("✅ Шаблон обновлён.", reply_markup=await admin_menu(session))
