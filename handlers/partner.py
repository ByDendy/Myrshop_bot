import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func

from database.models import (
    Account, Partner, RankSetting, RentalHistory,
)
from database.session import async_session
from keyboards.inline import (
    partner_not_registered_keyboard, partner_main_menu,
    partner_accounts_keyboard, partner_back_to_main,
)
from config import ADMIN_IDS

router = Router()


class AddPartnerAccount(StatesGroup):
    login = State()
    password = State()
    riot_id = State()
    rank = State()
    prices = State()
    photo = State()


class EditPaymentDetails(StatesGroup):
    wait_text = State()


async def _get_partner(session, telegram_id: int):
    return (await session.execute(
        select(Partner).where(Partner.telegram_id == telegram_id)
    )).scalar_one_or_none()


# ─── Вход в раздел ───

@router.callback_query(F.data == "partner_main")
async def partner_main(callback: CallbackQuery, session):
    partner = await _get_partner(session, callback.from_user.id)

    if not partner:
        await callback.message.delete()
        await callback.message.answer(
            "🤝 **Партнёрская программа MyrShop**\n\n"
            "Сдавай свои аккаунты Valorant в аренду через нашу платформу "
            "и получай **90%** с каждой аренды.\n\n"
            "**Что ты получаешь:**\n"
            "• Автоматизация оплат и выдачи\n"
            "• Трафик покупателей\n"
            "• Прозрачная статистика и история начислений\n"
            "• Выплаты по запросу\n\n"
            "**Что нужно:**\n"
            "• Свои аккаунты Valorant (Standard или Premium)\n"
            "• Менять пароль после каждой аренды (5 минут)\n\n"
            "Нажми кнопку ниже, чтобы присоединиться.",
            parse_mode="Markdown",
            reply_markup=partner_not_registered_keyboard(),
        )
        return

    if partner.status == "blocked":
        await callback.message.delete()
        await callback.message.answer(
            "🚫 Твой партнёрский аккаунт заблокирован.\n"
            "Свяжись с администратором для выяснения причин."
        )
        return

    await callback.message.delete()
    await callback.message.answer(
        f"🤝 **Кабинет партнёра**\n\n"
        f"Привет, {callback.from_user.first_name}!\n"
        f"Твой процент: **{100 - (partner.commission_percent or 10):.0f}%** "
        f"с каждой аренды.",
        parse_mode="Markdown",
        reply_markup=partner_main_menu(partner),
    )


@router.callback_query(F.data == "partner_register")
async def partner_register(callback: CallbackQuery, session):
    existing = await _get_partner(session, callback.from_user.id)
    if existing:
        await callback.answer("Ты уже партнёр", show_alert=True)
        return

    partner = Partner(
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
        status="active",
    )
    session.add(partner)
    await session.commit()

    await callback.message.delete()
    await callback.message.answer(
        f"🎉 Добро пожаловать в партнёрскую программу!\n\n"
        f"Теперь ты можешь добавлять свои аккаунты и получать 90% с каждой аренды.\n\n"
        f"Твой процент: **90%** (платформа берёт 10%).",
        parse_mode="Markdown",
        reply_markup=partner_main_menu(partner),
    )


# ─── Профиль ───

@router.callback_query(F.data == "partner_profile")
async def partner_profile(callback: CallbackQuery, session):
    partner = await _get_partner(session, callback.from_user.id)
    if not partner:
        await callback.answer("Сначала стань партнёром", show_alert=True)
        return

    # Статистика по аккаунтам
    accs = (await session.execute(
        select(Account).where(Account.partner_id == partner.id)
    )).scalars().all()

    total_accounts = len(accs)
    free = sum(1 for a in accs if a.status == "free")
    rented = sum(1 for a in accs if a.status == "rented")
    pending = sum(1 for a in accs if a.status == "pending_approval")
    awaiting = sum(1 for a in accs if a.status in ("awaiting_review", "awaiting_approval"))

    # Аренды и заработок
    if accs:
        acc_ids = [a.id for a in accs]
        rental_count = (await session.execute(
            select(func.count(RentalHistory.id)).where(
                RentalHistory.account_id.in_(acc_ids)
            )
        )).scalar() or 0
    else:
        rental_count = 0

    text = (
        f"📊 **Профиль партнёра**\n\n"
        f"👤 {partner.full_name or 'Партнёр'}"
        f"{' (@' + partner.username + ')' if partner.username else ''}\n"
        f"📅 С нами с {partner.created_at.strftime('%d.%m.%Y')}\n\n"
        f"**Аккаунты:**\n"
        f"• Всего: {total_accounts}\n"
        f"• 🟢 Свободных: {free}\n"
        f"• 🟠 В аренде: {rented}\n"
        f"• 🟡 На проверке: {pending}\n"
        f"• ⏳ Ждут пароля: {awaiting}\n\n"
        f"**Финансы:**\n"
        f"• Всего аренд: {rental_count}\n"
        f"• Заработано всего: **{partner.total_earned or 0:.0f} ₽**\n"
        f"• Доступно к выводу: **{partner.balance or 0:.0f} ₽**\n"
        f"• Заморожено: {partner.frozen_balance or 0:.0f} ₽\n"
        f"• Выплачено: {partner.total_paid or 0:.0f} ₽"
    )

    await callback.message.edit_text(
        text, parse_mode="Markdown",
        reply_markup=partner_back_to_main(),
    )


# ─── Мои аккаунты ───

@router.callback_query(F.data == "partner_accounts")
async def partner_accounts(callback: CallbackQuery, session):
    partner = await _get_partner(session, callback.from_user.id)
    if not partner:
        await callback.answer("Сначала стань партнёром", show_alert=True)
        return

    accounts = (await session.execute(
        select(Account)
        .where(Account.partner_id == partner.id)
        .order_by(Account.id.desc())
    )).scalars().all()

    if not accounts:
        await callback.message.edit_text(
            "📁 У тебя пока нет аккаунтов.\n\n"
            "Нажми «➕ Добавить аккаунт», чтобы добавить первый.",
            reply_markup=partner_back_to_main(),
        )
        return

    status_labels = {
        "free": "🟢 Свободен",
        "reserved": "🟡 Бронь",
        "rented": "🟠 В аренде",
        "pending_approval": "⏳ На проверке",
        "rejected": "❌ Отклонён",
        "awaiting_review": "🔑 Ждёт смены пароля",
        "awaiting_approval": "🔍 Пароль на проверке",
    }

    text = f"📁 **Твои аккаунты ({len(accounts)})**\n\n"
    for acc in accounts:
        label = status_labels.get(acc.status, "❓")
        text += f"#{acc.id} · {acc.rank} — {label}\n"
        if acc.status == "rejected" and acc.reject_reason:
            text += f"   ⚠️ {acc.reject_reason}\n"
        if acc.status == "awaiting_review":
            text += f"   ⚠️ Смени пароль и отправь через «Сменить пароль»\n"

    await callback.message.edit_text(
        text, parse_mode="Markdown",
        reply_markup=partner_accounts_keyboard(accounts),
    )


@router.callback_query(F.data.startswith("partner_del|"))
async def partner_delete_account(callback: CallbackQuery, session):
    acc_id = int(callback.data.split("|")[1])
    account = await session.get(Account, acc_id)

    if not account or account.partner_id != (await _get_partner(session, callback.from_user.id)).id:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    if account.status != "free":
        await callback.answer(
            f"Удалить можно только свободные. Сейчас: {account.status}",
            show_alert=True,
        )
        return

    await session.delete(account)
    await session.commit()

    await callback.answer(f"✅ Аккаунт #{acc_id} удалён", show_alert=True)
    await partner_accounts(callback, session)


# ─── Добавление аккаунта ───

@router.callback_query(F.data == "partner_add")
async def partner_add_start(callback: CallbackQuery, state: FSMContext, session):
    partner = await _get_partner(session, callback.from_user.id)
    if not partner:
        await callback.answer("Сначала стань партнёром", show_alert=True)
        return

    # Проверяем, что настроены ранги
    ranks = (await session.execute(select(RankSetting))).scalars().all()
    if not ranks:
        await callback.message.delete()
        await callback.message.answer(
            "⚠️ Ранги ещё не настроены администратором.\n"
            "Пожалуйста, свяжитесь с поддержкой."
        )
        return

    await state.set_state(AddPartnerAccount.login)
    await callback.message.delete()
    await callback.message.answer(
        "➕ **Добавление аккаунта**\n\n"
        "Шаг 1/6: Введи **логин** Riot Games:",
        parse_mode="Markdown",
    )


@router.message(AddPartnerAccount.login)
async def add_login(message: Message, state: FSMContext):
    login = (message.text or "").strip()
    if len(login) < 3:
        await message.answer("❌ Логин слишком короткий (минимум 3 символа). Попробуй снова:")
        return
    await state.update_data(login=login)
    await state.set_state(AddPartnerAccount.password)
    await message.answer("Шаг 2/6: Введи **пароль** от Riot Games:", parse_mode="Markdown")


@router.message(AddPartnerAccount.password)
async def add_password(message: Message, state: FSMContext):
    pwd = (message.text or "").strip()
    if len(pwd) < 6:
        await message.answer("❌ Пароль слишком короткий (минимум 6 символов). Попробуй снова:")
        return
    await state.update_data(password=pwd)
    await state.set_state(AddPartnerAccount.riot_id)
    await message.answer(
        "Шаг 3/6: Введи **Riot ID** (например, `Player#RU1`):",
        parse_mode="Markdown",
    )


@router.message(AddPartnerAccount.riot_id)
async def add_riot_id(message: Message, state: FSMContext):
    riot_id = (message.text or "").strip()
    if "#" not in riot_id or len(riot_id) < 4:
        await message.answer("❌ Riot ID должен быть в формате `Player#RU1`. Попробуй снова:")
        return
    await state.update_data(riot_id=riot_id)
    await state.set_state(AddPartnerAccount.rank)
    await message.answer(
        "Шаг 4/6: Введи **ранг** (например, `Diamond 1`):",
        parse_mode="Markdown",
    )


@router.message(AddPartnerAccount.rank)
async def add_rank(message: Message, state: FSMContext, session):
    rank = (message.text or "").strip()

    # Проверяем, что ранг существует в RankSetting (регистронезависимо)
    rank_setting = (await session.execute(
        select(RankSetting).where(func.lower(RankSetting.rank) == rank.lower())
    )).scalar_one_or_none()

    if not rank_setting:
        available = (await session.execute(
            select(RankSetting.rank).order_by(RankSetting.rank)
        )).scalars().all()
        avail_str = ", ".join(available)
        await message.answer(
            f"❌ Ранг `{rank}` не настроен.\n\n"
            f"Доступные ранги:\n{avail_str}\n\n"
            f"Попробуй снова:",
            parse_mode="Markdown",
        )
        return

    await state.update_data(rank=rank_setting.rank, rank_setting_id=rank_setting.id)
    await state.set_state(AddPartnerAccount.prices)

    await message.answer(
        f"Шаг 5/6: Введи **три цены** через пробел — за 3ч, 6ч и 12ч.\n\n"
        f"Минимумы для ранга `{rank_setting.rank}`:\n"
        f"• 3ч: не ниже **{rank_setting.min_price_3h:.0f} ₽**\n"
        f"• 6ч: не ниже **{rank_setting.min_price_6h:.0f} ₽**\n"
        f"• 12ч: не ниже **{rank_setting.min_price_12h:.0f} ₽**\n\n"
        f"Пример: `{rank_setting.min_price_3h:.0f} {rank_setting.min_price_6h:.0f} {rank_setting.min_price_12h:.0f}`",
        parse_mode="Markdown",
    )


@router.message(AddPartnerAccount.prices)
async def add_prices(message: Message, state: FSMContext, session):
    data = await state.get_data()
    rank_setting = await session.get(RankSetting, data["rank_setting_id"])
    if not rank_setting:
        await message.answer("❌ Ошибка: настройки ранга не найдены. Начни заново.")
        await state.clear()
        return

    parts = (message.text or "").replace(",", ".").split()
    if len(parts) != 3:
        await message.answer("❌ Нужно ровно три числа через пробел. Пример: `200 350 600`")
        return

    try:
        p3, p6, p12 = [float(x) for x in parts]
    except ValueError:
        await message.answer("❌ Введи числа. Пример: `200 350 600`")
        return

    # Проверки
    if p3 < rank_setting.min_price_3h:
        await message.answer(
            f"❌ Цена за 3ч ({p3:.0f}₽) ниже минимума ({rank_setting.min_price_3h:.0f}₽). "
            f"Попробуй снова:"
        )
        return
    if p6 < rank_setting.min_price_6h:
        await message.answer(
            f"❌ Цена за 6ч ({p6:.0f}₽) ниже минимума ({rank_setting.min_price_6h:.0f}₽). "
            f"Попробуй снова:"
        )
        return
    if p12 < rank_setting.min_price_12h:
        await message.answer(
            f"❌ Цена за 12ч ({p12:.0f}₽) ниже минимума ({rank_setting.min_price_12h:.0f}₽). "
            f"Попробуй снова:"
        )
        return
    if not (p3 <= p6 <= p12):
        await message.answer(
            "❌ Цены должны расти: 3ч ≤ 6ч ≤ 12ч. Попробуй снова:"
        )
        return

    await state.update_data(price_3h=p3, price_6h=p6, price_12h=p12)
    await state.set_state(AddPartnerAccount.photo)
    await message.answer(
        "Шаг 6/6: Отправь **фото аккаунта** (скриншот инвентаря / ранга).\n\n"
        "Или напиши «нет», чтобы пропустить.",
        parse_mode="Markdown",
    )


@router.message(AddPartnerAccount.photo)
async def add_photo(message: Message, state: FSMContext, session):
    photo_id = message.photo[-1].file_id if message.photo else None
    data = await state.get_data()

    partner = await _get_partner(session, message.from_user.id)
    if not partner:
        await message.answer("❌ Ошибка: партнёр не найден.")
        await state.clear()
        return

    # Проверка на дубликат логина
    existing = (await session.execute(
        select(Account).where(Account.login == data["login"])
    )).scalar_one_or_none()
    if existing:
        await message.answer(
            f"❌ Аккаунт с логином `{data['login']}` уже есть в системе.\n"
            f"Проверь данные и попробуй снова.",
            parse_mode="Markdown",
        )
        await state.clear()
        return

    account = Account(
        login=data["login"],
        password=data["password"],
        riot_id=data["riot_id"],
        rank=data["rank"],
        tier="standard",
        price_3h=data["price_3h"],
        price_6h=data["price_6h"],
        price_12h=data["price_12h"],
        photo_id=photo_id,
        status="pending_approval",
        partner_id=partner.id,
    )
    session.add(account)
    await session.commit()

    await state.clear()

    await message.answer(
        f"✅ Аккаунт **#{account.id}** отправлен на проверку!\n\n"
        f"Обычно это занимает до 24 часов. Мы уведомим тебя, когда админ одобрит аккаунт.",
        parse_mode="Markdown",
        reply_markup=partner_back_to_main(),
    )

    # Уведомление админам
    admin_text = (
        f"🤝 **Новая заявка на партнёрский аккаунт**\n\n"
        f"Партнёр: {partner.full_name or 'без имени'}"
        f"{' (@' + partner.username + ')' if partner.username else ''}\n"
        f"TG ID: `{partner.telegram_id}`\n\n"
        f"Аккаунт #{account.id}\n"
        f"Ранг: **{account.rank}**\n"
        f"Riot ID: `{account.riot_id}`\n"
        f"Цены: 3ч {account.price_3h:.0f}₽ / 6ч {account.price_6h:.0f}₽ / 12ч {account.price_12h:.0f}₽\n\n"
        f"Проверить и одобрить: /admin → Аккаунты"
    )
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, admin_text, parse_mode="Markdown")
        except Exception as e:
            logging.warning(f"Не смог уведомить админа {admin_id}: {e}")


# ─── Реквизиты ───

@router.callback_query(F.data == "partner_details")
async def partner_details(callback: CallbackQuery, session):
    partner = await _get_partner(session, callback.from_user.id)
    if not partner:
        await callback.answer("Сначала стань партнёром", show_alert=True)
        return

    current = partner.payment_details or "не указаны"
    await callback.message.edit_text(
        f"💳 **Реквизиты для выплат**\n\n"
        f"Текущие: `{current}`\n\n"
        f"Нажми «Изменить», чтобы обновить (карта, USDT-кошелёк, СБП и т.д.).",
        parse_mode="Markdown",
        reply_markup=__import__("aiogram").types.InlineKeyboardMarkup(
            inline_keyboard=[
                [__import__("aiogram").types.InlineKeyboardButton(
                    text="✏️ Изменить", callback_data="partner_details_edit"
                )],
                [__import__("aiogram").types.InlineKeyboardButton(
                    text="◀️ Назад", callback_data="partner_main"
                )],
            ]
        ),
    )


@router.callback_query(F.data == "partner_details_edit")
async def partner_details_edit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditPaymentDetails.wait_text)
    await callback.message.delete()
    await callback.message.answer(
        "Отправь реквизиты одним сообщением.\n"
        "Например: `Карта 2200 7000 1234 5678` или `USDT TRC-20: TXxx...`"
    )


@router.message(EditPaymentDetails.wait_text)
async def partner_details_save(message: Message, state: FSMContext, session):
    text = (message.text or "").strip()
    if len(text) < 5:
        await message.answer("❌ Слишком коротко. Попробуй снова:")
        return

    partner = await _get_partner(session, message.from_user.id)
    if partner:
        partner.payment_details = text
        await session.commit()

    await state.clear()
    await message.answer(
        "✅ Реквизиты обновлены.",
        reply_markup=partner_back_to_main(),
    )


# ─── Запрос выплаты (заглушка до Этапа 4) ───

@router.callback_query(F.data == "partner_payout")
async def partner_payout(callback: CallbackQuery, session):
    partner = await _get_partner(session, callback.from_user.id)
    if not partner:
        await callback.answer("Сначала стань партнёром", show_alert=True)
        return

    if (partner.balance or 0) < 300:
        await callback.answer(
            f"Минимальная сумма для выплаты — 300₽.\n"
            f"Сейчас у тебя: {partner.balance or 0:.0f}₽",
            show_alert=True,
        )
        return

    await callback.answer(
        "Функция выплат будет доступна после полного запуска программы. "
        "Пока что администратор свяжется с тобой для выплаты.",
        show_alert=True,
    )