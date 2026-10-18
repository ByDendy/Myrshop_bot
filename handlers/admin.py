from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, delete
from database.models import Account, Lot
from config import ADMIN_IDS

router = Router()


class AddAccount(StatesGroup):
    login = State()
    password = State()
    rank = State()
    description = State()
    photo = State()
    prices = State()


class BulkUpload(StatesGroup):
    wait_data = State()


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="admin_add")],
        [InlineKeyboardButton(text="📥 Массовая загрузка", callback_data="admin_bulk")],
        [InlineKeyboardButton(text="📋 Список аккаунтов", callback_data="admin_list")],
        [InlineKeyboardButton(text="🗑 Удалить аккаунт", callback_data="admin_delete")],
    ])


@router.message(Command("admin"), F.from_user.id.in_(ADMIN_IDS))
async def admin_panel(message: Message):
    await message.answer("🔧 Админ-панель:", reply_markup=admin_menu())


@router.callback_query(F.data == "admin_menu")
async def back_admin(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("🔧 Админ-панель:", reply_markup=admin_menu())


# ---------- ДОБАВЛЕНИЕ (пошаговое) ----------

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
    await state.set_state(AddAccount.description)
    await message.answer("Введите описание товара:")


@router.message(AddAccount.description)
async def add_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
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
async def add_prices(message: Message, state: FSMContext, session):
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
        description=data["description"],
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


# ---------- МАССОВАЯ ЗАГРУЗКА ----------

@router.callback_query(F.data == "admin_bulk")
async def bulk_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BulkUpload.wait_data)
    await callback.message.delete()
    await callback.message.answer(
        "📥 Массовая загрузка аккаунтов.\n\n"
        "Отправьте одним сообщением список, каждая строка — один аккаунт:\n\n"
        "`login;;password;;rank;;100,150,250`\n\n"
        "Где 100,150,250 — цены за 3ч, 6ч и 12ч.\n\n"
        "Пример:\n"
        "`user1;;pass1;;Diamond 1;;100,150,250`\n"
        "`user2;;pass2;;Platinum 3;;80,120,200`",
        parse_mode="Markdown",
    )


@router.message(BulkUpload.wait_data)
async def bulk_process(message: Message, state: FSMContext, session):
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

        account = Account(
            login=login,
            password=password,
            rank=rank,
            price_3h=prices[0],
            price_6h=prices[1],
            price_12h=prices[2],
            status="free",
        )
        session.add(account)
        created += 1

    await session.commit()
    await state.clear()

    result = f"✅ Загружено аккаунтов: {created}"
    if errors:
        result += "\n\n⚠️ Ошибки:\n" + "\n".join(errors[:10])
        if len(errors) > 10:
            result += f"\n... и ещё {len(errors) - 10}"

    await message.answer(result, reply_markup=admin_menu())


# ---------- СПИСОК ----------

@router.callback_query(F.data == "admin_list")
async def list_accounts(callback: CallbackQuery, session):
    result = await session.execute(select(Account).order_by(Account.id))
    accounts = result.scalars().all()

    await callback.message.delete()
    if not accounts:
        await callback.message.answer("📭 Аккаунтов пока нет.", reply_markup=admin_menu())
        return

    emoji = {"free": "🟢", "reserved": "🟡", "rented": "🟠"}
    text = "📋 Все аккаунты:\n\n"
    for acc in accounts:
        e = emoji.get(acc.status, "❓")
        text += f"{e} #{acc.id} | {acc.rank} | {acc.login}\n"

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
async def do_delete(callback: CallbackQuery, session):
    acc_id = int(callback.data.split("|")[1])
    account = await session.get(Account, acc_id)

    if not account:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    await session.delete(account)
    await session.commit()
    await callback.answer(f"✅ Аккаунт #{acc_id} удалён", show_alert=True)
    await _show_delete_menu(callback, session)