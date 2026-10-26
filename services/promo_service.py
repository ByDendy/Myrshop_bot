import logging
from datetime import datetime
from sqlalchemy import select, func
from database.models import Promocode, PromocodeUse, RentalHistory


async def validate_promo(session, code: str, telegram_id: int, hours: int, price: float):
    """
    Проверяет промокод. Возвращает (promo, discount, error).
    Если error is None и promo не None — промокод валиден.
    Если promo is None и error is None — промокод не найден/не подходит (пограничный случай).
    """
    code = code.strip().upper()

    result = await session.execute(select(Promocode).where(Promocode.code == code))
    promo = result.scalar_one_or_none()

    if not promo:
        return None, 0, "Промокод не найден"
    if not promo.active:
        return None, 0, "Промокод неактивен"
    if promo.valid_until < datetime.utcnow():
        return None, 0, "Срок действия промокода истёк"
    if promo.max_uses > 0 and promo.used_count >= promo.max_uses:
        return None, 0, "Промокод больше не действует (лимит исчерпан)"

    used = await session.execute(
        select(PromocodeUse).where(
            PromocodeUse.promocode_id == promo.id,
            PromocodeUse.telegram_id == telegram_id,
        )
    )
    if used.scalar_one_or_none():
        return None, 0, "Вы уже использовали этот промокод"

    if promo.condition_type == "first_order":
        orders = await session.execute(
            select(func.count(RentalHistory.id)).where(
                RentalHistory.buyer_id == telegram_id
            )
        )
        if (orders.scalar() or 0) > 0:
            return None, 0, "Промокод только для первого заказа"

    elif promo.condition_type == "rental_12h":
        if hours != 12:
            return None, 0, "Промокод действует только для аренды на 12 часов"

    if promo.discount_type == "percent":
        discount = round(price * promo.discount_value / 100, 2)
    else:
        discount = min(promo.discount_value, price)

    if discount <= 0:
        return None, 0, "Скидка не может быть применена к этому заказу"

    return promo, discount, None


async def record_promo_use(session, account, method: str = "cryptobot"):
    """Записывает факт использования промокода после успешной оплаты."""
    if not account.promo_id:
        return

    result = await session.execute(
        select(Promocode).where(Promocode.id == account.promo_id)
    )
    promo = result.scalar_one_or_none()
    if not promo:
        logging.warning(f"Промокод #{account.promo_id} не найден для аккаунта #{account.id}")
        return

    price = {
        3: account.price_3h,
        6: account.price_6h,
        12: account.price_12h,
    }.get(account.rental_hours, 0)

    original_price = round(price, 2)
    discount = round(account.promo_discount or 0, 2)
    final_price = round(max(0, original_price - discount), 2)

    session.add(PromocodeUse(
        promocode_id=promo.id,
        telegram_id=account.buyer_id or 0,
        account_id=account.id,
        original_price=original_price,
        discount_applied=discount,
        final_price=final_price,
    ))
    promo.used_count = (promo.used_count or 0) + 1
    await session.commit()
    logging.info(
        f"Промокод {promo.code} применён: аккаунт #{account.id}, "
        f"скидка {discount}₽, итого {final_price}₽"
    )