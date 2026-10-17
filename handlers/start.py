from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from keyboards.inline import main_menu

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        f"Привет, {message.from_user.first_name}!\n\n"
        f"Добро пожаловать в магазин аккаунтов Valorant.\n"
        f"Выбери действие:",
        reply_markup=main_menu()
    )