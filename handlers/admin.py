from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from database.models import Account
from config import ADMIN_IDS

router = Router()

class AddAccount(StatesGroup):
    login = State()
    password = State()
    rank = State()
    price = State()

@router.message(Command("admin"), F.from_user.id.in_(ADMIN_IDS))
async def admin_panel(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="admin_add")],
        [InlineKeyboardButton(text="📋 Список аккаунтов", callback_data="admin_list")],
    ])
    await message.answer("🔧 Админ-панель:", reply_markup=kb)

@router.callback_query(F.data == "admin_add")
async def add_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddAccount.login)
    await callback.message.edit_text("Введите логин аккаунта:")

@router.message(AddAccount.login)
async def add_login(message: Message, state: FSMContext):
    await state.update_data(login=message.text)
    await state.set_state(AddAccount.password)
    await message.answer("Введите пароль:")

@router.message(AddAccount.password)
async def add_password(message: Message, state: FSMContext):
    await state.update_data(password=message.text)
    await state.set_state(AddAccount.rank)
    await message.answer("Введите ранг (например, Gold 2):")

@router.message(AddAccount.rank)
async def add_rank(message: Message, state: FSMContext):
    await state.update_data(rank=message.text)
    await state.set_state(AddAccount.price)
    await message.answer("Введите цену в рублях:")

@router.message(AddAccount.price)
async def add_price(message: Message, state: FSMContext, session):
    try:
        price = float(message.text)
    except ValueError:
        await message.answer("❌ Введите число!")
        return

    data = await state.get_data()
    account = Account(
        login=data["login"],
        password=data["password"],
        rank=data["rank"],
        price=price,
        status="free"
    )
    session.add(account)
    await session.commit()
    await state.clear()
    await message.answer(f"✅ Аккаунт добавлен! ID: {account.id}")

@router.callback_query(F.data == "admin_list")
async def list_accounts(callback: CallbackQuery, session):
    result = await session.execute(select(Account))
    accounts = result.scalars().all()

    if not accounts:
        await callback.message.edit_text("📭 Аккаунтов пока нет.")
        return

    text = "📋 Все аккаунты:\n\n"
    for acc in accounts:
        status = "🟢" if acc.status == "free" else "🔴"
        text += f"{status} #{acc.id} | {acc.rank} | {acc.login} | {acc.price} ₽\n"

    await callback.message.edit_text(text)