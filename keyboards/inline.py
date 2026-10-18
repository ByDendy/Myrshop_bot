from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Магазин 🛒", callback_data="shop")],
        [InlineKeyboardButton(text="Поддержка 🛟", callback_data="support")],
    ])


def ranks_keyboard(ranks: list):
    buttons = []
    for rank in ranks:
        buttons.append([InlineKeyboardButton(
            text=rank, callback_data=f"rank|{rank}",
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def accounts_keyboard(accounts: list, rank: str):
    buttons = []
    for acc in accounts:
        if acc.status == "free":
            buttons.append([InlineKeyboardButton(
                text=f"#{acc.id} — {acc.rank}",
                callback_data=f"view|{acc.id}",
            )])
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад", callback_data="shop",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def rental_keyboard(acc):
    buttons = [
        [InlineKeyboardButton(
            text=f"⏱ 3 часа — {acc.price_3h:.0f} ₽",
            callback_data=f"rent|{acc.id}|3",
        )],
        [InlineKeyboardButton(
            text=f"⏱ 6 часов — {acc.price_6h:.0f} ₽",
            callback_data=f"rent|{acc.id}|6",
        )],
        [InlineKeyboardButton(
            text=f"⏱ 12 часов — {acc.price_12h:.0f} ₽",
            callback_data=f"rent|{acc.id}|12",
        )],
        [InlineKeyboardButton(
            text="◀️ Назад", callback_data=f"rank|{acc.rank}",
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def payment_methods_keyboard(methods: list, acc_id: int, hours: int):
    buttons = []
    for m in methods:
        buttons.append([InlineKeyboardButton(
            text=m.name,
            callback_data=f"pay|{acc_id}|{hours}|{m.code}",
        )])
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад", callback_data=f"view|{acc_id}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_payments_keyboard(methods: list):
    buttons = []
    for m in methods:
        icon = "🟢" if m.enabled else "🔴"
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {m.name}",
            callback_data=f"toggle_pay|{m.id}",
        )])
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад", callback_data="admin_menu",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
