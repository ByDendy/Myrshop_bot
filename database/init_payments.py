from sqlalchemy import select
from database.models import PaymentMethod


DEFAULT_METHODS = [
    {
        "code": "funpay",
        "name": "🟡 FunPay",
        "order": 1,
        "details": "Оплата через площадку FunPay. Ссылка генерируется автоматически.",
    },
    {
        "code": "cryptobot",
        "name": "🪙 CryptoBot",
        "order": 2,
        "details": "Оплата криптовалютой через CryptoBot.",
    },
]


async def seed_payment_methods(session):
    for m in DEFAULT_METHODS:
        exists = (await session.execute(
            select(PaymentMethod).where(PaymentMethod.code == m["code"])
        )).scalar_one_or_none()
        if not exists:
            session.add(PaymentMethod(
                code=m["code"],
                name=m["name"],
                details=m["details"],
                order=m["order"],
                enabled=True,
            ))
    await session.commit()