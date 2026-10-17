from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Магазин 🛒", callback_data="shop")],
        [InlineKeyboardButton(text="Поддержка 🛟", callback_data="support")],
    ])


def shop_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Покупка аккаунта", callback_data="shop_sale")],
        [InlineKeyboardButton(text="2️⃣ Аренда аккаунта", callback_data="shop_rental")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")],
    ])


def ranks_keyboard(ranks: list, acc_type: str):
    buttons = []
    for rank in ranks:
        buttons.append([InlineKeyboardButton(
            text=rank,
            callback_data=f"rank|{acc_type}|{rank}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="shop")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def accounts_keyboard(accounts: list, acc_type: str, rank: str):
    buttons = []
    for acc in accounts:
        buttons.append([InlineKeyboardButton(
            text=f"#{acc.id} — {acc.rank}",
            callback_data=f"view|{acc.id}"
        )])
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад",
        callback_data=f"shop_{acc_type}"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def account_details_keyboard(acc, acc_type: str):
    buttons = []
    if acc_type == "sale":
        buttons.append([InlineKeyboardButton(
            text=f"💰 Купить за {acc.price:.0f} ₽",
            callback_data=f"buy|{acc.id}"
        )])
    else:
        buttons.append([InlineKeyboardButton(
            text=f"⏱ 3 часа — {acc.price_3h:.0f} ₽",
            callback_data=f"rent|{acc.id}|3"
        )])
        buttons.append([InlineKeyboardButton(
            text=f"⏱ 6 часов — {acc.price_6h:.0f} ₽",
            callback_data=f"rent|{acc.id}|6"
        )])
        buttons.append([InlineKeyboardButton(
            text=f"⏱ 12 часов — {acc.price_12h:.0f} ₽",
            callback_data=f"rent|{acc.id}|12"
        )])
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад",
        callback_data=f"rank|{acc_type}|{acc.rank}"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
