import logging
from sqlalchemy import select, func
from database.models import Customer, Referral, BonusTransaction, RentalHistory
from services.settings_service import get_setting


async def bind_referral(session, referrer_id: int, new_user_id: int):
    """Привязывает нового пользователя к рефереру (если это возможно)."""
    if referrer_id == new_user_id:
        return  # защита от самоприглашения

    # Проверяем, не привязан ли уже этот пользователь
    existing = await session.get(Customer, new_user_id)
    if not existing or existing.referred_by is not None:
        return

    # Проверяем, существует ли реферер
    referrer = await session.get(Customer, referrer_id)
    if not referrer:
        return

    existing.referred_by = referrer_id
    session.add(Referral(referrer_id=referrer_id, referred_id=new_user_id))
    await session.commit()
    logging.info(f"Пользователь {new_user_id} привязан к рефереру {referrer_id}")


async def calculate_checkout_discount(session, customer_id: int, original_price: float, is_first_order: bool):
    """
    Считает скидки для чекаута: приветственная скидка (если реферал) + списание бонусов.
    Возвращает (welcome_discount, bonus_spent, final_price, bonus_left).
    """
    welcome_discount = 0.0
    bonus_spent = 0.0
    
    cust = await session.get(Customer, customer_id)
    if not cust:
        return 0.0, 0.0, original_price, 0.0

    # 1. Приветственная скидка для реферала (только если первый заказ и он привязан)
    if is_first_order and cust.referred_by:
        ref_prog = await get_setting(session, "referral_enabled", "1")
        if ref_prog == "1":
            disc_str = await get_setting(session, "referral_welcome_discount", "10")
            try:
                disc_pct = float(disc_str)
                welcome_discount = round(original_price * (disc_pct / 100), 2)
            except ValueError:
                pass

    price_after_welcome = original_price - welcome_discount

    # 2. Списание бонусов (с учетом лимита из настроек)
    if cust.bonus_balance > 0:
        max_pct_str = await get_setting(session, "max_bonus_percent", "50")
        try:
            max_pct = float(max_pct_str)
        except ValueError:
            max_pct = 50.0
            
        max_allowed = round(price_after_welcome * (max_pct / 100), 2)
        bonus_spent = min(cust.bonus_balance, max_allowed)
        bonus_spent = round(bonus_spent, 2)

    final_price = round(max(0, price_after_welcome - bonus_spent), 2)
    
    return welcome_discount, bonus_spent, final_price, cust.bonus_balance


async def apply_bonus_spend(session, customer_id: int, amount: float, desc: str):
    """Списывает бонусы с баланса."""
    if amount <= 0:
        return
    cust = await session.get(Customer, customer_id)
    if cust:
        cust.bonus_balance = round(max(0, cust.bonus_balance - amount), 2)
        session.add(BonusTransaction(
            customer_id=customer_id, amount=-amount, type="spend", description=desc
        ))
        await session.commit()


async def process_referral_rewards(session, account):
    """
    Начисляет бонусы рефереру после окончания аренды.
    Вызывается из rental_checker.
    """
    buyer_id = account.buyer_id
    if not buyer_id:
        return

    # Проверяем, включена ли рефералка
    ref_prog = await get_setting(session, "referral_enabled", "1")
    if ref_prog != "1":
        return

    cust = await session.get(Customer, buyer_id)
    if not cust or not cust.referred_by:
        return

    # Находим связь
    result = await session.execute(
        select(Referral).where(Referral.referred_id == buyer_id)
    )
    ref = result.scalar_one_or_none()
    if not ref:
        return

    # Считаем, каким по счету был этот заказ (включая только что завершенный)
    orders_count = (await session.execute(
        select(func.count(RentalHistory.id)).where(RentalHistory.buyer_id == buyer_id)
    )).scalar() or 0

    referrer = await session.get(Customer, ref.referrer_id)
    if not referrer:
        return

    price = {3: account.price_3h, 6: account.price_6h, 12: account.price_12h}.get(account.rental_hours, 0)
    bonus_to_add = 0.0
    desc = ""

    if orders_count == 1:
        # Первый заказ: 10% от суммы
        bonus_to_add = round(price * 0.10, 2)
        desc = f"10% от 1-го заказа реферала #{buyer_id}"
    elif 2 <= orders_count <= 11:
        # Заказы 2-11: 5 рублей
        bonus_to_add = 5.0
        desc = f"Бонус за {orders_count}-й заказ реферала #{buyer_id}"

    if bonus_to_add > 0:
        referrer.bonus_balance = round(referrer.bonus_balance + bonus_to_add, 2)
        ref.bonus_paid = round(ref.bonus_paid + bonus_to_add, 2)
        ref.orders_completed = orders_count
        
        session.add(BonusTransaction(
            customer_id=ref.referrer_id, amount=bonus_to_add, type="referral", description=desc
        ))
        await session.commit()
        logging.info(f"Начислено {bonus_to_add}₽ рефереру {ref.referrer_id} ({desc})")