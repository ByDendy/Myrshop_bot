from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton,
)
from keyboards.inline import main_menu
from config import SUPPORT_USERNAME

router = Router()

WELCOME_TEXT = (
    "Добро пожаловать в MyrShop — аренда аккаунтов Valorant! 👋\n\n"
    "Выберите действие:"
)


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(WELCOME_TEXT, reply_markup=main_menu())


@router.callback_query(lambda c: c.data == "main_menu")
async def back_to_main(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(WELCOME_TEXT, reply_markup=main_menu())


@router.callback_query(lambda c: c.data == "support")
async def show_support(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "🛟 Поддержка MyrShop\n\n"
        f"По всем вопросам пишите: {SUPPORT_USERNAME}\n\n"
        "Время ответа: до 30 минут.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")],
        ]),
    )
