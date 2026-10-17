from sqlalchemy import select
from database.models import Setting


DEFAULT_RENTAL_DESCRIPTION = """Аккаунт VALORANT — ранг {rank}
Полный доступ — логин, пароль от Riot Games
Регион: Россия

Возможны редкие агенты, брелки, ранги и дополнительные скины

Если данные не подходят — моментальная замена!
Видео с момента покупки поможет решить вопрос быстрее.
Поддержка 24/7
Ответ в течение 1 минуты — 2 часов
Не спеши с негативным отзывом — всё решаем"""


async def get_setting(session, key: str, default: str = None) -> str:
    result = await session.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar()
    if setting is None:
        return default
    return setting.value


async def set_setting(session, key: str, value: str):
    result = await session.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar()
    if setting is None:
        session.add(Setting(key=key, value=value))
    else:
        setting.value = value
    await session.commit()


async def get_rental_description(session) -> str:
    return await get_setting(session, "rental_description", DEFAULT_RENTAL_DESCRIPTION)


async def seed_defaults(session):
    """Заполняет настройки значениями по умолчанию, если их ещё нет в БД."""
    existing = await get_setting(session, "rental_description")
    if existing is None:
        await set_setting(session, "rental_description", DEFAULT_RENTAL_DESCRIPTION)