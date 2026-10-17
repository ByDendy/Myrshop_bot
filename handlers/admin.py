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
from services.settings_service import get_rental_description, set_setting

router = Router()


class AddAccount(StatesGroup):
    type = State()
    login = State()
    password = State()
    rank = State()
    description = State()
    photo = State()
    price = State()


class EditRentalDesc(StatesGroup):
    text = State()


class BulkRental(StatesGroup):
    photo = State()
    accounts_text = State()


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="admin_add")],
        [InlineKeyboardButton(text="📦 Массовая загрузка (аренда)", callback_data="admin_bulk")],
        [InlineKeyboardButton(text="📋 Список аккаунтов", callback_data="admin_list")],
        [InlineKeyboardButton(text="📝 Описание аренды", callback_data="admin_edit_rental_desc")],
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


# ---------- Добавление одного аккаунта ----------

@router.callback_query(F.data == "admin_add")
async def add_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddAccount.type)
    await callback.message.delete()
    await callback.message.answer("Выберите тип аккаунта:", reply_markup=type_keyboard())


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
    data = await state.get_data()
    if data.get("type") == "rental":
        # Для аренды описание берётся из настроек — шаг пропускаем
        await state.set_state(AddAccount.photo)
        await message.answer("Отправьте фото товара.\nИли напишите «нет».")
    else:
        await state.set_state(AddAccount.description)
        await message.answer("Введите описание товара:")


@router.message(AddAccount.description)
async def add_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(AddAccount.photo)
    await message.answer("Отправьте фото товара.\nИли напишите «нет», чтобы пропустить.")


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
            description=data.get("description"),
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
            await message.answer("❌ Введите три числа через пробел. Пример: 100 150 250")
            return
        account = Account(
            login=data["login"],
            password=data["password"],
            rank=data["rank"],
            description=None,  # подставляется из настроек при показе
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


# ---------- Список аккаунтов ----------

@router.callback_query(F.data == "admin_list")
async def list_accounts(callback: CallbackQuery, session):
    result = await session.execute(select(Account).order_by(Account.id))
    accounts = result.scalars().all()
    if not accounts:
        await callback.message.delete()
        await callback.message.answer("📭 Аккаунтов пока нет.", reply_markup=admin_menu())
        return
    status_emoji = {"free": "🟢", "reserved": "🟡", "sold": "🔴", "rented": "🟠"}
    text = "📋 Все аккаунты:\n\n"
    for acc in accounts:
        emoji = status_emoji.get(acc.status, "❓")
        type_text = "💰" if acc.type == "sale" else "⏱"
        text += f"{emoji}{type_text} #{acc.id} | {acc.rank} | {acc.login}\n"
    await callback.message.delete()
    await callback.message.answer(text, reply_markup=admin_menu())


# ---------- Удаление ----------

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
        await callback.message.answer("📭 Нет аккаунтов для удаления.", reply_markup=admin_menu())
        return
    await callback.message.answer(
        "Выберите аккаунт для удаления:", reply_markup=_delete_keyboard(accounts)
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
        await callback.message.answer("📭 Нет аккаунтов для удаления.", reply_markup=admin_menu())
        return
    await callback.message.answer(
        "Выберите аккаунт для удаления:", reply_markup=_delete_keyboard(accounts)
    )


# ---------- Редактирование описания аренды ----------

@router.callback_query(F.data == "admin_edit_rental_desc")
async def show_rental_desc(callback: CallbackQuery, session):
    current = await get_rental_description(session)
    preview = current.replace("{rank}", "Gold 2")
    await callback.message.delete()
    await callback.message.answer(
        f"📝 Текущее описание аренды:\n\n{preview}\n\n"
        f"💡 Используйте {{rank}} — оно заменится на ранг конкретного аккаунта.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить", callback_data="edit_rental_start")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")],
        ])
    )


@router.callback_query(F.data == "edit_rental_start")
async def edit_rental_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditRentalDesc.text)
    await callback.message.delete()
    await callback.message.answer(
        "Отправьте новый текст описания аренды.\n\n"
        "Используйте {rank} для подстановки ранга.\n\n"
        "Отмена: /admin"
    )


@router.message(EditRentalDesc.text)
async def edit_rental_save(message: Message, state: FSMContext, session):
    new_text = message.text
    if not new_text or not new_text.strip():
        await message.answer("Отправьте текст.")
        return
    await set_setting(session, "rental_description", new_text)
    await state.clear()
    preview = new_text.replace("{rank}", "Gold 2")
    await message.answer(
        f"✅ Описание аренды обновлено!\n\n"
        f"Пример для Gold 2:\n\n{preview}",
        reply_markup=admin_menu()
    )


# ---------- Массовая загрузка (только аренда) ----------

@router.callback_query(F.data == "admin_bulk")
async def bulk_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BulkRental.photo)
    await callback.message.delete()
    await callback.message.answer(
        "📦 Массовая загрузка аккаунтов аренды\n\n"
        "Шаг 1 из 2: отправьте фото, которое будет общим для всей партии.\n"
        "Или напишите «нет», чтобы добавить без фото."
    )


@router.message(BulkRental.photo)
async def bulk_photo(message: Message, state: FSMContext):
    if message.photo:
        photo_id = message.photo[-1].file_id
    elif message.text and message.text.strip().lower() in ("нет", "no", "skip", "-"):
        photo_id = None
    else:
        await message.answer("Отправьте фото или напишите «нет».")
        return

    await state.update_data(photo_id=photo_id)
    await state.set_state(BulkRental.accounts_text)
    await message.answer(
        "Шаг 2 из 2: отправьте список аккаунтов.\n\n"
        "Формат (одна строка = один аккаунт):\n"
        "`login;;password;;rank;;3h,6h,12h`\n\n"
        "Пример:\n"
        "`test1;;pass123;;Gold 2;;100,150,250`\n"
        "`test2;;pass456;;Diamond 1;;200,350,600`\n\n"
        "⚠️ В пароле не должно быть `;;`.\n"
        "⚠️ Цены — через запятую, дробная часть через точку.",
        parse_mode="Markdown"
    )


@router.message(BulkRental.accounts_text)
async def bulk_parse(message: Message, state: FSMContext, session):
    text = message.text or ""
    if not text:
        await message.answer("Отправьте текстовый список аккаунтов.")
        return

    # Сразу удаляем сообщение с паролями — оно не должно висеть в чате
    try:
        await message.delete()
    except Exception:
        pass

    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    parsed = []
    errors = []

    for i, line in enumerate(lines, 1):
        parts = line.split(";;")
        if len(parts) != 4:
            errors.append(f"Строка {i}: неверный формат (нужно 4 части через `;;`)")
            continue
        login, password, rank, prices_str = [p.strip() for p in parts]
        if not login or not password or not rank:
            errors.append(f"Строка {i}: пустой логин/пароль/ранг")
            continue
        try:
            prices = [float(x.replace(",", ".")) for x in prices_str.split(",")]
            if len(prices) != 3:
                raise ValueError
        except ValueError:
            errors.append(f"Строка {i} ({login}): неверные цены (нужно 3 числа через запятую)")
            continue

        result = await session.execute(select(Account).where(Account.login == login))
        if result.scalar():
            errors.append(f"Строка {i} ({login}): логин уже есть в БД")
            continue

        parsed.append((login, password, rank, prices))

    if not parsed:
        await message.answer(
            "❌ Не удалось распарсить ни одного аккаунта.\n\n"
            + ("Ошибки:\n" + "\n".join(errors[:10]) if errors else ""),
            reply_markup=admin_menu()
        )
        await state.clear()
        return

    await state.update_data(parsed=parsed, errors=errors)

    preview = f"📋 Парсинг завершён\n\n"
    preview += f"✅ Валидных: {len(parsed)}\n"
    if errors:
        preview += f"❌ Ошибок: {len(errors)}\n\n"
        preview += "\n".join(errors[:5])
        if len(errors) > 5:
            preview += f"\n... и ещё {len(errors) - 5}"
        preview += "\n"

    preview += "\nПервые 3 аккаунта:\n"
    for login, _, rank, prices in parsed[:3]:
        preview += f"• {login} | {rank} | {prices[0]:.0f}/{prices[1]:.0f}/{prices[2]:.0f} ₽\n"
    if len(parsed) > 3:
        preview += f"... и ещё {len(parsed) - 3}\n"

    preview += "\n⚠️ Сообщение с паролями удалено из чата."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Подтвердить ({len(parsed)})", callback_data="bulk_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_menu")],
    ])
    await message.answer(preview, reply_markup=kb)


@router.callback_query(F.data == "bulk_confirm")
async def bulk_confirm(callback: CallbackQuery, state: FSMContext, session):
    data = await state.get_data()
    parsed = data.get("parsed", [])
    photo_id = data.get("photo_id")

    if not parsed:
        await callback.answer("Нет данных для сохранения", show_alert=True)
        return

    for login, password, rank, prices in parsed:
        session.add(Account(
            login=login,
            password=password,
            rank=rank,
            description=None,  # подставляется из настроек при показе
            photo_id=photo_id,
            type="rental",
            price_3h=prices[0],
            price_6h=prices[1],
            price_12h=prices[2],
            status="free",
        ))
    await session.commit()
    await state.clear()

    await callback.message.delete()
    await callback.message.answer(
        f"✅ Успешно добавлено: {len(parsed)} аккаунтов аренды.",
        reply_markup=admin_menu()
    )


# ---------- Снятие резервов ----------

@router.callback_query(F.data == "admin_clear_reserves")
async def clear_reserves(callback: CallbackQuery, session):
    from services.funpay_service import FunPayService
    funpay = FunPayService()
    result = await session.execute(select(Account).where(Account.status == "reserved"))
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
