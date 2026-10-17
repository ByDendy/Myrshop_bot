from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from database.models import Account
from config import ADMIN_IDS

router = Router()


class AddAccount(StatesGroup):
    type = State()
    login = State()
    password = State()
    rank = State()
    description = State()
    photo = State()
    price = State()


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="admin_add")],
        [InlineKeyboardButton(text="📋 Список аккаунтов", callback_data="admin_list")],
        [InlineKeyboardButton(text="🗑 Удалить аккаунт", callback_data="admin_delete")],
        [InlineKeyboardButton(text="🔄 Снять все резервы", callback_data="admin_clear_reserves")],
    ])


def type_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Продажа", callback_data="acc_type|sale")],
        [InlineKeyboardButton(text="⏱ Аренда", callback_data="acc_type|rental")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_menu")],
    ])


@router.message(Command("admin"), F.from_user.id.in_(ADMIN_IDS))
async def admin_panel(message: Message):
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())


@router.callback_query(F.data == "admin_menu")
async def back_admin(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("🔧 Админ-панель:", reply_markup=admin_menu())


@router.callback_query(F.data == "admin_add")
async def add_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddAccount.type)
    await callback.message.delete()
    await callback.message.answer(
        "Выберите тип аккаунта:", reply_markup=type_keyboard()
    )


@router.callback_query(AddAccount.type, F.data.startswith("acc_type|"))
async def add_type(callback: CallbackQuery, state: FSMContext):
    acc_type = callback.data.split("|")[1]
    await state.update_data(type=acc_type)
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
    await message.answer("Введите ранг (например, Gold 2):")


@router.message(AddAccount.rank)
async def add_rank(message: Message, state: FSMContext):
    await state.update_data(rank=message.text.strip())
    await state.set_state(AddAccount.description)
    await message.answer("Введите описание товара:")


@router.message(AddAccount.description)
async def add_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(AddAccount.photo)
    await message.answer(
        "Отправьте фото товара.\n"
        "Или напишите «нет», чтобы пропустить."
    )


@router.message(AddAccount.photo)
async def add_photo(message: Message, state: FSMContext):
    if message.photo:
        photo_id = message.photo[-1].file_id
    else:
        photo_id = None

    await state.update_data(photo_id=photo_id)
    await state.set_state(AddAccount.price)

    data = await state.get_data()
    if data["type"] == "sale":
        await message.answer("Введите цену продажи в рублях:")
    else:
        await message.answer(
            "Введите цены аренды через пробел: 3ч 6ч 12ч\n"
            "Пример: 100 150 250"
        )


@router.message(AddAccount.price)
async def add_price(message: Message, state: FSMContext, session):
    data = await state.get_data()

    if data["type"] == "sale":
        try:
            price = float(message.text.replace(",", "."))
        except ValueError:
            await message.answer("❌ Введите число!")
            return

        account = Account(
            login=data["login"],
            password=data["password"],
            rank=data["rank"],
            description=data["description"],
            photo_id=data["photo_id"],
            type="sale",
            price=price,
            status="free",
        )
    else:
        try:
            prices = [float(x.replace(",", ".")) for x in message.text.split()]
            if len(prices) != 3:
                raise ValueError
        except ValueError:
            await message.answer(
                "❌ Введите три числа через пробел. Пример: 100 150 250"
            )
            return

        account = Account(
            login=data["login"],
            password=data["password"],
            rank=data["rank"],
            description=data["description"],
            photo_id=data["photo_id"],
            type="rental",
            price_3h=prices[0],
            price_6h=prices[1],
            price_12h=prices[2],
            status="free",
        )

    session.add(account)
    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ Аккаунт #{account.id} добавлен!",
        reply_markup=admin_menu()
    )


@router.callback_query(F.data == "admin_list")
async def list_accounts(callback: CallbackQuery, session):
    result = await session.execute(select(Account).order_by(Account.id))
    accounts = result.scalars().all()

    if not accounts:
        await callback.message.delete()
        await callback.message.answer(
            "📭 Аккаунтов пока нет.", reply_markup=admin_menu()
        )
        return

    status_emoji = {
        "free": "🟢", "reserved": "🟡",
        "sold": "🔴", "rented": "🟠",
    }
    text = "📋 Все аккаунты:\n\n"
    for acc in accounts:
        emoji = status_emoji.get(acc.status, "❓")
        type_text = "💰" if acc.type == "sale" else "⏱"
        text += f"{emoji}{type_text} #{acc.id} | {acc.rank} | {acc.login}\n"

    await callback.message.delete()
    await callback.message.answer(text, reply_markup=admin_menu())


def _delete_keyboard(accounts):
    buttons = []
    for acc in accounts:
        buttons.append([InlineKeyboardButton(
            text=f"🗑 #{acc.id} — {acc.rank} ({acc.login})",
            callback_data=f"del|{acc.id}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "admin_delete")
async def delete_menu(callback: CallbackQuery, session):
    result = await session.execute(select(Account).order_by(Account.id))
    accounts = result.scalars().all()

    await callback.message.delete()
    if not accounts:
        await callback.message.answer(
            "📭 Нет аккаунтов для удаления.", reply_markup=admin_menu()
        )
        return

    await callback.message.answer(
        "Выберите аккаунт для удаления:",
        reply_markup=_delete_keyboard(accounts)
    )


@router.callback_query(F.data.startswith("del|"))
async def do_delete(callback: CallbackQuery, session):
    acc_id = int(callback.data.split("|")[1])
    account = await session.get(Account, acc_id)

    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    await session.delete(account)
    await session.commit()
    await callback.answer(f"✅ Аккаунт #{acc_id} удалён", show_alert=True)

    result = await session.execute(select(Account).order_by(Account.id))
    accounts = result.scalars().all()

    await callback.message.delete()
    if not accounts:
        await callback.message.answer(
            "📭 Нет аккаунтов для удаления.", reply_markup=admin_menu()
        )
        return

    await callback.message.answer(
        "Выберите аккаунт для удаления:",
        reply_markup=_delete_keyboard(accounts)
    )


@router.callback_query(F.data == "admin_clear_reserves")
async def clear_reserves(callback: CallbackQuery, session):
    """Снимает все резервы вручную и пытается закрыть лоты на FunPay."""
    from services.funpay_service import FunPayService
    from database.models import Account

    funpay = FunPayService()
    result = await session.execute(
        select(Account).where(Account.status == "reserved")
    )
    reserved = result.scalars().all()

    if not reserved:
        await callback.answer("Нет активных резервов", show_alert=True)
        return

    closed = 0
    for acc in reserved:
        if acc.lot_id:
            try:
                await funpay.close_lot(acc.lot_id)
                closed += 1
            except Exception:
                pass
        acc.status = "free"
        acc.buyer_id = None
        acc.reserved_until = None
        acc.lot_id = None

    await session.commit()
    await callback.answer(
        f"✅ Снято резервов: {len(reserved)}\nЗакрыто лотов: {closed}",
        show_alert=True
    )
