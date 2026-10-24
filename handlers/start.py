from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from aiogram.fsm.context import FSMContext
from keyboards.inline import main_menu
from config import SUPPORT_USERNAME

router = Router()

WELCOME_TEXT = (
    "Добро пожаловать в MyrShop — магазин по аренде и покупке аккаунтов Valorant! 👋\n\n"
    "Выберите действие:"
)

# Постоянная кнопка "Главное меню" снизу экрана
reply_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🏠 Главное меню")]],
    resize_keyboard=True,
    is_persistent=True,
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=main_menu())


@router.message(F.text == "🏠 Главное меню")
async def back_to_main_reply(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=main_menu())


@router.callback_query(F.data == "main_menu")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(WELCOME_TEXT, reply_markup=main_menu())


@router.callback_query(F.data == "support")
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
