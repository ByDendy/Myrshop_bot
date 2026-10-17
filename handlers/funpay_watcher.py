import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from aioFunPayAPI import Runner
from aioFunPayAPI.enums import EventTypes, OrderStatuses
from database.models import Account
from database.session import async_session
from services.funpay_service import FunPayService
from services.notifications import notify_admin


async def funpay_watcher_loop(bot, funpay: FunPayService):
    """
    Слушает события FunPay. При новом оплаченном заказе
    находит аккаунт по lot_id, выдаёт данные покупателю
    и обновляет статус.
    """
    while True:
        try:
            acc = await funpay.get_account()
            runner = Runner(acc)

            async for event in runner.listen(requests_delay=6.0):
                if event.type != EventTypes.NEW_ORDER:
                    continue

                # Очищаем ID от '#'
                clean_id = event.order.id.replace("#", "")

                if event.order.status != OrderStatuses.PAID:
                    logging.info(f"Заказ {clean_id} ещё не оплачен")
                    continue

                # Получаем полную информацию о заказе
                order_info = await acc.get_order(clean_id)

                # Ищем аккаунт в БД по lot_id
                async with async_session() as session:
                    result = await session.execute(
                        select(Account).where(
                            Account.lot_id == str(order_info.lot_id),
                            Account.status == "reserved",
                            Account.payment_method == "funpay",
                        )
                    )
                    account = result.scalar_one_or_none()

                    if not account:
                        logging.warning(
                            f"Не найден аккаунт для заказа {clean_id} "
                            f"(lot_id={order_info.lot_id})"
                        )
                        continue

                    # Выдаём аккаунт
                    await _deliver_funpay_account(
                        bot, session, account, order_info, acc
                    )

        except Exception as e:
            logging.error(f"funpay_watcher error: {e}")
            await asyncio.sleep(10)  # пауза перед переподключением


async def _deliver_funpay_account(bot, session, account: Account, order_info, fp_account):
    """
    Выдаёт данные покупателю в чат FunPay и в Telegram (если покупатель
    наш — по buyer_id), обновляет статус аккаунта.
    """
    if account.type == "sale":
        account.status = "sold"
        account.sold_at = datetime.utcnow()
    else:
        hours = account.rental_hours or 3
        account.status = "rented"
        account.rented_until = datetime.utcnow() + timedelta(hours=hours)

    account.order_id = str(order_info.id)
    await session.commit()

    # Сообщение для чата FunPay
    funpay_text = (
        f"Привет, {order_info.buyer_username}!\n\n"
        f"Вот данные твоего аккаунта:\n"
        f"Логин: {account.login}\n"
        f"Пароль: {account.password}\n"
        f"Ранг: {account.rank}\n\n"
    )
    if account.type == "rental":
        funpay_text += (
            f"⏱ Аренда действует до: "
            f"{account.rented_until.strftime('%d.%m.%Y %H:%M')} UTC\n\n"
        )
    funpay_text += "Смените пароль после первого входа!"

    try:
        await fp_account.send_message(order_info.chat_id, funpay_text)
    except Exception as e:
        logging.error(f"Не смог отправить сообщение в FunPay: {e}")

    # Дублируем в Telegram, если покупатель наш (у него есть buyer_id)
    if account.buyer_id:
        tg_text = (
            f"🎉 Оплата через FunPay получена! Аккаунт #{account.id}\n\n"
            f"Логин: {account.login}\n"
            f"Пароль: {account.password}\n"
            f"Ранг: {account.rank}\n\n"
        )
        if account.type == "rental":
            tg_text += (
                f"⏱ Аренда действует до: "
                f"{account.rented_until.strftime('%d.%m.%Y %H:%M')} UTC\n\n"
            )
        tg_text += "Смените пароль после первого входа!"
        try:
            await bot.send_message(account.buyer_id, tg_text)
        except Exception as e:
            logging.warning(f"Не смог отправить сообщение в Telegram: {e}")

    # Уведомляем админа
    await notify_admin(bot, account)

    logging.info(f"FunPay: аккаунт #{account.id} выдан по заказу {order_info.id}")