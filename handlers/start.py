import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from keyboards.inline import main_menu
from config import SUPPORT_USERNAME, WEB_BASE_URL
from database.models import Customer
from services.avatar_service import refresh_avatar

router = Router()

WELCOME_TEXT = (
    "Добро пожаловать в MyrShop — аренда аккаунтов Valorant! 👋\n\n"
    "Выберите действие:"
)

ONBOARDING_TEXT = (
    "👋 Добро пожаловать в MyrShop!\n\n"
    "Перед началом работы, пожалуйста, ознакомьтесь с документами:\n\n"
    "📄 Политика конфиденциальности\n"
    "📋 Согласие на обработку персональных данных\n"
    "📜 Условия аренды\n\n"
    "Нажмите «✅ Согласен», если принимаете условия — и мы начнём!"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session):
    await state.clear()

    cust = await session.get(Customer, message.from_user.id)
    if not cust:
        cust = Customer(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        session.add(cust)
        await session.commit()
    else:
        if message.from_user.username and cust.username != message.from_user.username:
            cust.username = message.from_user.username
        if message.from_user.first_name and cust.first_name != message.from_user.first_name:
            cust.first_name = message.from_user.first_name
        await session.commit()

    if await refresh_avatar(message.bot, cust):
        await session.commit()

    if not cust.agreed_to_terms:
        await message.answer(ONBOARDING_TEXT, reply_markup=_onboarding_keyboard())
        return

    await message.answer(WELCOME_TEXT, reply_markup=main_menu())


@router.callback_query(F.data == "agree_terms")
async def agree_terms(callback: CallbackQuery, state: FSMContext, session):
    await state.clear()

    cust = await session.get(Customer, callback.from_user.id)
    if not cust:
        cust = Customer(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )
        session.add(cust)

    cust.agreed_to_terms = True
    cust.agreed_at = datetime.utcnow()
    await session.commit()

    await callback.message.delete()
    await callback.message.answer(
        "✅ Спасибо! Условия приняты.\n\n" + WELCOME_TEXT,
        reply_markup=main_menu(),
    )


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


def _onboarding_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Политика конфиденциальности", url=f"{WEB_BASE_URL}/privacy")],
        [InlineKeyboardButton(text="📋 Согласие на обработку ПД", url=f"{WEB_BASE_URL}/consent")],
        [InlineKeyboardButton(text="📜 Условия аренды", url=f"{WEB_BASE_URL}/terms")],
        [InlineKeyboardButton(text="✅ Согласен с условиями", callback_data="agree_terms")],
    ])
