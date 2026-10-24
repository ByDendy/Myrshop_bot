import logging
from aiogram import Bot


async def fetch_avatar(bot: Bot, telegram_id: int) -> str | None:
    """Возвращает file_id аватарки пользователя или None."""
    try:
        photos = await bot.get_user_profile_photos(telegram_id, limit=1)
        if photos.total_count > 0:
            return photos.photos[0][-1].file_id
    except Exception as e:
        logging.warning(f"Не удалось получить аватарку для {telegram_id}: {e}")
    return None


async def refresh_avatar(bot: Bot, user_obj) -> bool:
    """Обновляет avatar_id у объекта (Customer или Partner)."""
    new_id = await fetch_avatar(bot, user_obj.telegram_id)
    if new_id and new_id != user_obj.avatar_id:
        user_obj.avatar_id = new_id
        return True
    return False