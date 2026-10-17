from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купить аккаунт", callback_data="buy_account")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")],
    ])

def ranks_keyboard(ranks: list):
    buttons = []
    for rank in ranks:
        buttons.append([InlineKeyboardButton(text=rank, callback_data=f"rank_{rank}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def accounts_keyboard(accounts: list):
    buttons = []
    for acc in accounts:
        if acc.status == "free":
            buttons.append([InlineKeyboardButton(
                text=f"💰 Купить #{acc.id} ({acc.rank})",
                callback_data=f"buy_{acc.id}"
            )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="buy_account")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)