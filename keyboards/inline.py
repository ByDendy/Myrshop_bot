from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Магазин 🛒", callback_data="shop")],
        [InlineKeyboardButton(text="Партнёрам 🤝", callback_data="partner_main")],
        [InlineKeyboardButton(text="Поддержка 🛟", callback_data="support")],
    ])


def tiers_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Standard", callback_data="tier|standard")],
        [InlineKeyboardButton(text="💎 Premium (со скинами)", callback_data="tier|premium")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")],
    ])


def ranks_keyboard(ranks: list, tier: str):
    buttons = []
    for rank in ranks:
        buttons.append([InlineKeyboardButton(
            text=rank, callback_data=f"rank|{tier}|{rank}",
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="shop")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def accounts_keyboard(accounts: list, tier: str):
    buttons = []
    for acc in accounts:
        if acc.status == "free":
            buttons.append([InlineKeyboardButton(
                text=f"#{acc.id} — {acc.rank}",
                callback_data=f"view|{acc.id}",
            )])
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад", callback_data=f"tier|{tier}",
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
            text="◀️ Назад", callback_data=f"rank|{acc.tier}|{acc.rank}",
        )],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def payment_methods_keyboard(methods: list, acc_id: int, hours: int):
    buttons = []
    for m in methods:
        buttons.append([InlineKeyboardButton(
            text=m.name, callback_data=f"pay|{acc_id}|{hours}|{m.code}",
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
            text=f"{icon} {m.name}", callback_data=f"toggle_pay|{m.id}",
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── Партнёрская программа ───

def partner_not_registered_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤝 Стать партнёром", callback_data="partner_register")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")],
    ])


def partner_main_menu(partner):
    balance = partner.balance or 0
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Профиль", callback_data="partner_profile")],
        [InlineKeyboardButton(text="📁 Мои аккаунты", callback_data="partner_accounts")],
        [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="partner_add")],
        [InlineKeyboardButton(
            text=f"💰 Запросить выплату ({balance:.0f} ₽)",
            callback_data="partner_payout",
        )],
        [InlineKeyboardButton(text="💳 Реквизиты для выплат", callback_data="partner_details")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")],
    ])


def partner_back_to_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В кабинет партнёра", callback_data="partner_main")],
    ])


def partner_accounts_keyboard(accounts: list):
    buttons = []
    for acc in accounts:
        if acc.status == "free":
            buttons.append([InlineKeyboardButton(
                text=f"🗑 Удалить #{acc.id} — {acc.rank}",
                callback_data=f"partner_del|{acc.id}",
            )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="partner_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
