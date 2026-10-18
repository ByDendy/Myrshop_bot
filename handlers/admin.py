import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from database.models import Account, PaymentMethod
from keyboards.inline import admin_payments_keyboard
from services.settings_service import get_setting, set_setting
from services.funpay_service import FunPayService
from handlers.lot_manager import run_lot_manager_cycle
from config import ADMIN_IDS

router = Router()


class AddAccount(StatesGroup):
    login = State()
    password = State()
    rank = State()
    photo = State()
    prices = State()


class BulkUpload(StatesGroup):
    photo = State()
    wait_data = State()


class EditTemplate(StatesGroup):
    wait_text = State()


class ChangePassword(StatesGroup):
    new_password = State()


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="admin_add")],
        [InlineKeyboardButton(text="📥 Массовая загрузка", callback_data="admin_bulk")],
        [InlineKeyboardButton(text="📋 Список аккаунтов", callback_data="admin_list")],
        [InlineKeyboardButton(text="🗑 Удалить аккаунт", callback_data="admin_delete")],
        [InlineKeyboardButton(text="🔓 Снять все брони", callback_data="admin_unlock")],
        [InlineKeyboardButton(text="🔑 Ожидают смены пароля", callback_data="admin_awaiting")],
        [InlineKeyboardButton(text="💳 Способы оплаты", callback_data="admin_payments")],
        [InlineKeyboardButton(text="📝 Шаблон описания", callback_data="admin_template")],
    ])


async def _trigger_lot_manager(funpay: FunPayService):
    try:
        await run_lot_manager_cycle(funpay)
    except Exception as e:
        logging.error(f"lot_manager после действия админа: {e}")


@router.message(Command("admin"), F.from_user.id.in_(ADMIN_IDS))
async def admin_panel(message: Message):
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())


@router.callback_query(F.data == "admin_menu")
async def back_admin(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("🔧 Админ-панель:", reply_markup=admin_menu())


# ---------- ДОБАВЛЕНИЕ (одиночное) ----------

@router.callback_query(F.data == "admin_add")
async def add_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddAccount.login)
    await callback.message.delete()
    await callback.message.answer("Введите логин аккаунта:")


@router.message(AddAccount.login)
async def add_login(message: Message, state: FSMContext):
    await state.update_data(login=message.text.strip())
    await state.set_state(AddAccount.password)
    await message.answer("Введите пароль:")


@router.message(AddAccount.password)
async def add_password(message: Message, state: FSMContext):
    await state.update_data(password=message.text.strip())
    await state.set_state(AddAccount.rank)
    await message.answer("Введите ранг (например, Diamond 1):")


@router.message(AddAccount.rank)
async def add_rank(message: Message, state: FSMContext):
    await state.update_data(rank=message.text.strip())
    await state.set_state(AddAccount.photo)
    await message.answer("Отправьте фото товара.\nИли напишите «нет», чтобы пропустить.")


@router.message(AddAccount.photo)
async def add_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id if message.photo else None
    await state.update_data(photo_id=photo_id)
    await state.set_state(AddAccount.prices)
    await message.answer(
        "Введите цены аренды через пробел: 3ч 6ч 12ч\n"
        "Пример: 100 150 250"
    )


@router.message(AddAccount.prices)
async def add_prices(message: Message, state: FSMContext, session, funpay: FunPayService):
    try:
        prices = [float(x.replace(",", ".")) for x in message.text.split()]
        if len(prices) != 3:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите три числа через пробел. Пример: 100 150 250")
        return

    data = await state.get_data()
    account = Account(
        login=data["login"],
        password=data["password"],
        rank=data["rank"],
        photo_id=data["photo_id"],
        price_3h=prices[0],
        price_6h=prices[1],
        price_12h=prices[2],
        status="free",
    )
    session.add(account)
    await session.commit()
    await state.clear()

    await message.answer(f"✅ Аккаунт #{account.id} добавлен!", reply_markup=admin_menu())
    await _trigger_lot_manager(funpay)


# ---------- МАССОВАЯ ЗАГРУЗКА ----------

@router.callback_query(F.data == "admin_bulk")
async def bulk_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BulkUpload.photo)
    await callback.message.delete()
    await callback.message.answer(
        "📥 Массовая загрузка аккаунтов.\n\n"
        "Шаг 1 из 2: отправьте фото, которое будет прикреплено ко всем аккаунтам.\n\n"
        "Или напишите «нет», чтобы загрузить без фото."
    )


@router.message(BulkUpload.photo)
async def bulk_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id if message.photo else None
    await state.update_data(photo_id=photo_id)
    await state.set_state(BulkUpload.wait_data)
    await message.answer(
        "Шаг 2 из 2: отправьте список аккаунтов.\n\n"
        "Формат каждой строки:\n"
        "`login;;password;;rank;;100,150,250`\n\n"
        "Где 100,150,250 — цены за 3ч, 6ч и 12ч.\n\n"
        "Пример:\n"
        "`user1;;pass1;;Diamond 1;;100,150,250`\n"
        "`user2;;pass2;;Platinum 3;;80,120,200`",
        parse_mode="Markdown",
    )


@router.message(BulkUpload.wait_data)
async def bulk_process(message: Message, state: FSMContext, session, funpay: FunPayService):
    data = await state.get_data()
    photo_id = data.get("photo_id")

    lines = message.text.strip().split("\n")
    created = 0
    errors = []

    for i, line in enumerate(lines, 1):
        parts = line.strip().split(";;")
        if len(parts) != 4:
            errors.append(f"Строка {i}: неверный формат (нужно 4 части через `;;`)")
            continue

        login, password, rank, prices_str = [p.strip() for p in parts]

        try:
            prices = [float(x.replace(",", ".")) for x in prices_str.split(",")]
            if len(prices) != 3:
                raise ValueError
        except ValueError:
            errors.append(f"Строка {i}: цены должны быть три числа через запятую")
            continue

        session.add(Account(
            login=login,
            password=password,
            rank=rank,
            photo_id=photo_id,
            price_3h=prices[0],
            price_6h=prices[1],
            price_12h=prices[2],
            status="free",
        ))
        created += 1

    await session.commit()
    await state.clear()

    result = f"✅ Загружено аккаунтов: {created}"
    if errors:
        result += "\n\n⚠️ Ошибки:\n" + "\n".join(errors[:10])
        if len(errors) > 10:
            result += f"\n... и ещё {len(errors) - 10}"
    await message.answer(result, reply_markup=admin_menu())

    if created > 0:
        await message.answer("⏳ Создаю лоты на FunPay…")
        await _trigger_lot_manager(funpay)
        await message.answer("✅ Лоты обновлены.")


# ---------- СПИСОК ----------

@router.callback_query(F.data == "admin_list")
async def list_accounts(callback: CallbackQuery, session):
    result = await session.execute(select(Account).order_by(Account.id))
    accounts = result.scalars().all()

    await callback.message.delete()
    if not accounts:
        await callback.message.answer("📭 Аккаунтов пока нет.", reply_markup=admin_menu())
        return

    emoji = {
        "free": "🟢",
        "reserved": "🟡",
        "rented": "🟠",
        "awaiting_password_change": "🔑",
    }
    text = "📋 Все аккаунты:\n\n"
    for acc in accounts:
        e = emoji.get(acc.status, "❓")
        text += f"{e} #{acc.id} | {acc.rank} | {acc.login} | {acc.status}\n"

    await callback.message.answer(text, reply_markup=admin_menu())


# ---------- УДАЛЕНИЕ ----------

def _delete_keyboard(accounts):
    buttons = []
    for acc in accounts:
        buttons.append([InlineKeyboardButton(
            text=f"🗑 #{acc.id} — {acc.rank} ({acc.login})",
            callback_data=f"del|{acc.id}",
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _show_delete_menu(callback: CallbackQuery, session):
    result = await session.execute(select(Account).order_by(Account.id))
    accounts = result.scalars().all()

    await callback.message.delete()
    if not accounts:
        await callback.message.answer("📭 Нет аккаунтов для удаления.", reply_markup=admin_menu())
        return

    await callback.message.answer(
        "Выберите аккаунт для удаления:",
        reply_markup=_delete_keyboard(accounts),
    )


@router.callback_query(F.data == "admin_delete")
async def delete_menu(callback: CallbackQuery, session):
    await _show_delete_menu(callback, session)


@router.callback_query(F.data.startswith("del|"))
async def do_delete(callback: CallbackQuery, session, funpay: FunPayService):
    acc_id = int(callback.data.split("|")[1])
    account = await session.get(Account, acc_id)

    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    await session.delete(account)
    await session.commit()
    await callback.answer(f"✅ Аккаунт #{acc_id} удалён", show_alert=True)
    await _show_delete_menu(callback, session)
    await _trigger_lot_manager(funpay)


# ---------- СНЯТИЕ ВСЕХ БРОНЕЙ ----------

@router.callback_query(F.data == "admin_unlock")
async def unlock_all_reservations(callback: CallbackQuery, session, funpay: FunPayService):
    result = await session.execute(
        select(Account).where(Account.status == "reserved")
    )
    reserved = result.scalars().all()
    count = len(reserved)

    for acc in reserved:
        acc.status = "free"
        acc.buyer_id = None
        acc.rental_hours = None
        acc.payment_invoice_id = None
        acc.reserved_at = None
        acc.lot_id = None

    await session.commit()

    await callback.answer(
        f"✅ Освобождено аккаунтов: {count}",
        show_alert=True,
    )
    await callback.message.delete()
    await callback.message.answer("🔧 Админ-панель:", reply_markup=admin_menu())

    if count > 0:
        await _trigger_lot_manager(funpay)


# ---------- ОЖИДАЮТ СМЕНЫ ПАРОЛЯ ----------

def _awaiting_keyboard(accounts):
    buttons = []
    for acc in accounts:
        buttons.append([InlineKeyboardButton(
            text=f"#{acc.id} — {acc.rank} ({acc.login})",
            callback_data=f"chpw|{acc.id}",
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "admin_awaiting")
async def awaiting_menu(callback: CallbackQuery, session):
    result = await session.execute(
        select(Account)
        .where(Account.status == "awaiting_password_change")
        .order_by(Account.id)
    )
    accounts = result.scalars().all()

    await callback.message.delete()
    if not accounts:
        await callback.message.answer(
            "🔑 Нет аккаунтов, ожидающих смены пароля.",
            reply_markup=admin_menu(),
        )
        return

    await callback.message.answer(
        "🔑 Аккаунты, ожидающие смены пароля.\n\n"
        "Нажмите на аккаунт, чтобы ввести новый пароль "
        "и вернуть его в свободные:",
        reply_markup=_awaiting_keyboard(accounts),
    )


@router.callback_query(F.data.startswith("chpw|"))
async def change_password_start(callback: CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split("|")[1])
    await state.update_data(acc_id=acc_id)
    await state.set_state(ChangePassword.new_password)
    await callback.message.delete()
    await callback.message.answer(
        f"Введите новый пароль для аккаунта #{acc_id}:"
    )


@router.message(ChangePassword.new_password)
async def change_password_save(
    message: Message, state: FSMContext, session, funpay: FunPayService
):
    data = await state.get_data()
    acc_id = data["acc_id"]
    account = await session.get(Account, acc_id)

    if not account:
        await message.answer("❌ Аккаунт не найден.")
        await state.clear()
        return

    account.password = message.text.strip()
    account.status = "free"
    account.buyer_id = None
    account.rental_hours = None
    account.rented_until = None
    account.reserved_at = None
    account.payment_invoice_id = None
    await session.commit()
    await state.clear()

    await message.answer(
        f"✅ Пароль для #{acc_id} обновлён. Аккаунт снова свободен.",
        reply_markup=admin_menu(),
    )
    await _trigger_lot_manager(funpay)


# ---------- СПОСОБЫ ОПЛАТЫ ----------

@router.callback_query(F.data == "admin_payments")
async def payments_menu(callback: CallbackQuery, session):
    result = await session.execute(select(PaymentMethod).order_by(PaymentMethod.order))
    methods = result.scalars().all()

    await callback.message.delete()
    await callback.message.answer(
        "💳 Способы оплаты\n\n"
        "🟢 — включён, 🔴 — выключен.\n"
        "Нажмите на способ, чтобы переключить:",
        reply_markup=admin_payments_keyboard(methods),
    )


@router.callback_query(F.data.startswith("toggle_pay|"))
async def toggle_payment(callback: CallbackQuery, session):
    method_id = int(callback.data.split("|")[1])
    method = await session.get(PaymentMethod, method_id)

    if not method:
        await callback.answer("Способ не найден", show_alert=True)
        return

    method.enabled = not method.enabled
    await session.commit()

    result = await session.execute(select(PaymentMethod).order_by(PaymentMethod.order))
    methods = result.scalars().all()

    status = "включён" if method.enabled else "выключен"
    await callback.answer(f"{method.name} теперь {status}")
    await callback.message.edit_reply_markup(
        reply_markup=admin_payments_keyboard(methods),
    )


# ---------- ШАБЛОН ОПИСАНИЯ ----------

@router.callback_query(F.data == "admin_template")
async def template_menu(callback: CallbackQuery, session):
    current = await get_setting(session, "description_template", "")

    await callback.message.delete()
    await callback.message.answer(
        "📝 Текущий шаблон описания:\n\n"
        f"`{current}`\n\n"
        f"Используйте `{{rank}}` для подстановки ранга аккаунта.\n"
        f"Шаблон применяется ко всем аккаунтам сразу.",
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
    await callback.message.answer(
        "Отправьте новый шаблон описания одним сообщением.\n\n"
        "Не забудьте про `{rank}` — туда подставится ранг аккаунта.\n"
        "Пример:\n"
        "`Аккаунт VALORANT - ранг {rank}`\n"
        "`Полный доступ — логин, пароль от Riot Games`\n"
        "`Регион: Россия`",
        parse_mode="Markdown",
    )


@router.message(EditTemplate.wait_text)
async def template_save(message: Message, state: FSMContext, session):
    text = message.text or ""
    if len(text) < 10:
        await message.answer("❌ Шаблон слишком короткий. Попробуйте снова.")
        return

    await set_setting(session, "description_template", text)
    await state.clear()
    await message.answer(
        "✅ Шаблон обновлён! Он сразу применён ко всем аккаунтам.",
        reply_markup=admin_menu(),
    )
