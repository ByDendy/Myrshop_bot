from sqlalchemy.ext.asyncio import (
    create_async_engine, async_sessionmaker, AsyncSession,
)
from sqlalchemy import select
from config import DATABASE_URL


db_url = DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(db_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


DEFAULT_TEMPLATE = """Аккаунт VALORANT - ранг {rank}
Полный доступ — логин, пароль от Riot Games
Регион: Россия

Возможны редкие агенты, брелки, ранги и дополнительные скины

Если данные не подходят — моментальная замена!
Видео с момента покупки поможет решить вопрос быстрее.
Поддержка 24/7
Ответ в течение 1 минуты — 2 часов
Не спеши с негативным отзывом — всё решаем"""


async def init_db():
    from database.models import Base, PaymentMethod, Setting

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        for code, name, order in [
            ("funpay", "🟡 FunPay", 1),
            ("cryptobot", "🪙 CryptoBot", 2),
        ]:
            exists = (await session.execute(
                select(PaymentMethod).where(PaymentMethod.code == code)
            )).scalar_one_or_none()
            if not exists:
                session.add(PaymentMethod(
                    code=code, name=name, order=order, enabled=True,
                ))

        tpl = (await session.execute(
            select(Setting).where(Setting.key == "description_template")
        )).scalar_one_or_none()
        if not tpl:
            session.add(Setting(
                key="description_template", value=DEFAULT_TEMPLATE,
            ))

        await session.commit()


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
