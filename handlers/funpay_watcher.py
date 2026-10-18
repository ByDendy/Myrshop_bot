import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from aioFunPayAPI import Runner
from aioFunPayAPI.common.enums import EventTypes, OrderStatuses
from database.models import Account
from database.session import async_session
from services.funpay_service import FunPayService
from services.notifications import notify_admin


async def funpay_watcher_loop(bot, funpay: FunPayService):
    while True:
        try:
            acc = await funpay.get_account()
            runner = Runner(acc)

            async for event in runner.listen(requests_delay=6.0):
                if event.type != EventTypes.NEW_ORDER:
                    continue

                clean_id = event.order.id.replace("#", "")

                if event.order.status != OrderStatuses.PAID:
                    logging.info(f"Заказ {clean_id} ещё не оплачен")
                    continue

                order_info = await acc.get_order(clean_id)

                # Парсим из описания лота: "Valorant аккаунт Diamond 1 — аренда 3ч"
                desc = order_info.description or ""
                if "— аренда" not in desc:
                    logging.warning(f"Заказ {clean_id}: не удалось определить ранг/часы из «{desc}»")
                    continue

                try:
                    rank_part = desc.split("Valorant аккаунт ")[1].split(" — аренда")[0].strip()
                    hours_part = desc.split("— аренда ")[1].split("ч")[0].strip()
                    hours = int(hours_part)
                except Exception as e:
                    logging.error(f"Заказ {clean_id}: ошибка парсинга «{desc}»: {e}")
                    continue

                async with async_session() as session:
                    # Ищем свободный аккаунт этого ранга
                    result = await session.execute(
                        select(Account).where(
                            Account.rank == rank_part,
                            Account.status == "free",
                        ).limit(1)
                    )
                    account = result.scalar_one_or_none()

                    if not account:
                        logging.error(
                            f"Заказ {clean_id}: нет свободных аккаунтов для {rank_part}"
                        )
                        # В реальности здесь нужно вернуть деньги или написать покупателю
                        continue

                    account.status = "rented"
                    account.buyer_id = None  # покупатель FunPay не TG-пользователь
                    account.rental_hours = hours
                    account.rented_until = datetime.utcnow() + timedelta(hours=hours)
                    await session.commit()

                    funpay_text = (
                        f"Привет, {order_info.buyer_username}!\n\n"
                        f"Вот данные твоего аккаунта:\n"
                        f"Логин: {account.login}\n"
                        f"Пароль: {account.password}\n"
                        f"Ранг: {account.rank}\n\n"
                        f"⏱ Аренда действует до: "
                        f"{account.rented_until.strftime('%d.%m.%Y %H:%M')} UTC\n\n"
                        f"Смените пароль после первого входа!"
                    )

                    try:
                        await acc.send_message(order_info.chat_id, funpay_text)
                    except Exception as e:
                        logging.error(f"Не смог отправить сообщение в FunPay: {e}")

                    await notify_admin(bot, account)
                    logging.info(f"FunPay: аккаунт #{account.id} выдан по заказу {clean_id}")

        except Exception as e:
            logging.error(f"funpay_watcher error: {e}")
            await asyncio.sleep(10)
