import logging
from datetime import datetime
from sqlalchemy import select
from database.models import (
    Partner, PartnerEarning, PartnerPayout, Account,
)
from services.settings_service import get_setting


async def get_commission(session, partner=None) -> float:
    """
    Возвращает процент платформы.
    Если у партнёра задана индивидуальная — использует её.
    Иначе — глобальная из settings.
    """
    if partner and partner.commission_percent is not None:
        return float(partner.commission_percent)
    try:
        val = await get_setting(session, "partner_commission", "10")
        return float(val)
    except (TypeError, ValueError):
        return 10.0


async def on_rental_started(session, account, rental_id: int, price: float):
    """
    Вызывается когда аренда партнёрского аккаунта оплачена.
    Создаёт PartnerEarning в статусе frozen и увеличивает frozen_balance.
    """
    if not account.partner_id:
        return
    partner = await session.get(Partner, account.partner_id)
    if not partner:
        logging.warning(f"Партнёр {account.partner_id} не найден для аккаунта #{account.id}")
        return

    commission = await get_commission(session, partner)
    partner_share = round(price * (100 - commission) / 100, 2)
    platform_share = round(price * commission / 100, 2)

    session.add(PartnerEarning(
        partner_id=partner.id,
        account_id=account.id,
        rental_id=rental_id,
        amount=partner_share,
        platform_amount=platform_share,
        status="frozen",
    ))
    partner.frozen_balance = round((partner.frozen_balance or 0) + partner_share, 2)
    await session.commit()
    logging.info(
        f"Партнёр #{partner.id}: начислено (frozen) {partner_share}₽ "
        f"за аренду #{rental_id} аккаунта #{account.id}"
    )


async def on_rental_ended(session, account):
    """
    Вызывается когда аренда истекла.
    Размораживает соответствующее начисление и переводит в баланс партнёра.
    """
    if not account.partner_id:
        return

    earning = (await session.execute(
        select(PartnerEarning).where(
            PartnerEarning.account_id == account.id,
            PartnerEarning.status == "frozen",
        ).order_by(PartnerEarning.created_at.desc()).limit(1)
    )).scalar_one_or_none()

    if not earning:
        return

    partner = await session.get(Partner, earning.partner_id)
    if not partner:
        return

    earning.status = "available"
    partner.frozen_balance = round(
        max(0, (partner.frozen_balance or 0) - earning.amount), 2
    )
    partner.balance = round((partner.balance or 0) + earning.amount, 2)
    partner.total_earned = round((partner.total_earned or 0) + earning.amount, 2)
    await session.commit()
    logging.info(
        f"Партнёр #{partner.id}: разморожено {earning.amount}₽ "
        f"с аренды #{earning.rental_id}"
    )


async def request_payout(session, partner):
    """
    Партнёр запрашивает выплату.
    Возвращает (payout, error_message).
    """
    if (partner.balance or 0) < 300:
        return None, f"Минимальная сумма — 300₽. Сейчас: {partner.balance or 0:.0f}₽"

    if not partner.payment_details or len(partner.payment_details.strip()) < 5:
        return None, "Сначала укажи реквизиты для выплат"

    existing = (await session.execute(
        select(PartnerPayout).where(
            PartnerPayout.partner_id == partner.id,
            PartnerPayout.status == "requested",
        )
    )).scalar_one_or_none()

    if existing:
        return None, "У тебя уже есть активный запрос на выплату. Дождись обработки."

    amount = round(partner.balance, 2)
    payout = PartnerPayout(
        partner_id=partner.id,
        amount=amount,
        status="requested",
    )
    session.add(payout)

    # Сразу «блокируем» сумму
    partner.balance = 0
    await session.commit()

    return payout, None


async def approve_payout(session, payout):
    """
    Админ подтверждает выплату.
    Помечает все available earnings как paid (FIFO).
    Возвращает True/False.
    """
    if not payout or payout.status != "requested":
        return False

    partner = await session.get(Partner, payout.partner_id)
    if not partner:
        return False

    payout.status = "paid"
    payout.paid_at = datetime.utcnow()
    partner.total_paid = round((partner.total_paid or 0) + payout.amount, 2)

    # Помечаем earnings как paid (FIFO, пока не покроем amount)
    earnings = (await session.execute(
        select(PartnerEarning).where(
            PartnerEarning.partner_id == partner.id,
            PartnerEarning.status == "available",
        ).order_by(PartnerEarning.created_at)
    )).scalars().all()

    running = 0.0
    for e in earnings:
        if running + e.amount > payout.amount + 0.01:
            break
        e.status = "paid"
        e.paid_at = datetime.utcnow()
        running += e.amount

    await session.commit()
    logging.info(
        f"Выплата #{payout.id} партнёру #{partner.id}: {payout.amount}₽ подтверждена"
    )
    return True


async def reject_payout(session, payout, reason: str):
    """
    Админ отклоняет выплату. Деньги возвращаются на баланс.
    """
    if not payout or payout.status != "requested":
        return False

    partner = await session.get(Partner, payout.partner_id)
    if not partner:
        return False

    payout.status = "rejected"
    payout.note = reason

    # Возвращаем деньги
    partner.balance = round((partner.balance or 0) + payout.amount, 2)
    await session.commit()
    logging.info(
        f"Выплата #{payout.id} партнёру #{partner.id}: отклонена — {reason}"
    )
    return True


async def manual_payout(session, partner, amount: float = None):
    """
    Ручная выплата с карточки партнёра (кнопка «Выплатить»).
    Если amount=None — платит весь текущий баланс.
    Возвращает (payout, error).
    """
    balance = round(partner.balance or 0, 2)
    if balance <= 0:
        return None, "Баланс равен нулю"

    amount = round(amount if amount is not None else balance, 2)
    if amount <= 0 or amount > balance:
        return None, f"Неверная сумма (баланс: {balance:.0f}₽)"

    payout = PartnerPayout(
        partner_id=partner.id,
        amount=amount,
        status="paid",
        paid_at=datetime.utcnow(),
        note="Ручная выплата из админ-панели",
    )
    session.add(payout)

    partner.balance = round(balance - amount, 2)
    partner.total_paid = round((partner.total_paid or 0) + amount, 2)

    # Помечаем earnings как paid
    earnings = (await session.execute(
        select(PartnerEarning).where(
            PartnerEarning.partner_id == partner.id,
            PartnerEarning.status == "available",
        ).order_by(PartnerEarning.created_at)
    )).scalars().all()

    running = 0.0
    for e in earnings:
        if running + e.amount > amount + 0.01:
            break
        e.status = "paid"
        e.paid_at = datetime.utcnow()
        running += e.amount

    await session.commit()
    return payout, None
