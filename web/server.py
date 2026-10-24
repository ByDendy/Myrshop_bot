import logging
from datetime import datetime, timedelta
from pathlib import Path

from aiohttp import web
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy import select, func, desc, or_
from jinja2 import Environment, FileSystemLoader, select_autoescape
from aiogram.types import BufferedInputFile

from config import WEB_ADMIN_PASSWORD, WEB_SECRET_KEY, ADMIN_IDS
from database.models import (
    Account, RentalHistory, RankSetting, Customer,
    Partner, PartnerPayout, PartnerEarning,
)
from database.session import async_session
from services.settings_service import get_setting, set_setting
from services.valorant_service import get_recent_matches
from services.partner_service import (
    approve_payout, reject_payout, manual_payout,
)
from web import notifications
from web.photo_proxy import register_photo_route


TEMPLATES_DIR = Path(__file__).parent / "templates"
env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)
serializer = URLSafeTimedSerializer(WEB_SECRET_KEY, salt="web-session")
SESSION_MAX_AGE = 60 * 60 * 24 * 7


# ─── Авторизация ───

def _current_user(request: web.Request):
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        return serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


@web.middleware
async def auth_middleware(request, handler):
    public = ("/login", "/api/photo/")
    if any(request.path.startswith(p) for p in public):
        return await handler(request)

    user = _current_user(request)
    if not user:
        raise web.HTTPFound("/login")

    request["user"] = user
    return await handler(request)


async def login_page(request: web.Request):
    error = None
    if request.method == "POST":
        data = await request.post()
        pwd = data.get("password", "")
        if pwd and pwd == WEB_ADMIN_PASSWORD:
            token = serializer.dumps({"user": "admin"})
            resp = web.HTTPFound("/")
            resp.set_cookie("session", token, max_age=SESSION_MAX_AGE, httponly=True)
            raise resp
        error = "Неверный пароль"
    html = env.get_template("login.html").render(error=error)
    return web.Response(text=html, content_type="text/html")


async def logout(request: web.Request):
    resp = web.HTTPFound("/login")
    resp.del_cookie("session")
    raise resp


# ─── Хелперы ───

async def _notify_partner_tg(bot, partner, text: str):
    if not partner or not partner.telegram_id:
        return
    try:
        await bot.send_message(partner.telegram_id, text, parse_mode="Markdown")
    except Exception as e:
        logging.warning(f"Не смог уведомить партнёра {partner.telegram_id}: {e}")


async def _upload_photo_to_telegram(bot, raw: bytes, filename: str):
    if not ADMIN_IDS:
        return None
    try:
        msg = await bot.send_photo(
            chat_id=ADMIN_IDS[0],
            photo=BufferedInputFile(raw, filename=filename or "photo.jpg"),
            disable_notification=True,
        )
        file_id = msg.photo[-1].file_id
        try:
            await bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
        except Exception:
            pass
        return file_id
    except Exception as e:
        logging.warning(f"photo upload: {e}")
        return None


def _maybe_photo_field(post):
    pf = post.get("photo")
    if pf and getattr(pf, "file", None) and getattr(pf, "filename", None):
        return pf
    return None


# ─── Дашборд ───

async def dashboard(request: web.Request):
    async with async_session() as session:
        accounts_total = (await session.execute(
            select(func.count(Account.id))
        )).scalar() or 0
        active = (await session.execute(
            select(func.count(Account.id)).where(Account.status == "rented")
        )).scalar() or 0
        awaiting = (await session.execute(
            select(func.count(Account.id)).where(Account.status == "awaiting_password_change")
        )).scalar() or 0
        total_rentals = (await session.execute(
            select(func.count(RentalHistory.id))
        )).scalar() or 0
        total_hours = (await session.execute(
            select(func.coalesce(func.sum(RentalHistory.hours), 0))
        )).scalar() or 0
        total_revenue = (await session.execute(
            select(func.coalesce(func.sum(RentalHistory.amount), 0))
        )).scalar() or 0
        recent = (await session.execute(
            select(RentalHistory).order_by(desc(RentalHistory.started_at)).limit(10)
        )).scalars().all()

        acc_map = {}
        if recent:
            ids = [r.account_id for r in recent]
            accs = (await session.execute(
                select(Account).where(Account.id.in_(ids))
            )).scalars().all()
            acc_map = {a.id: a for a in accs}

    html = env.get_template("dashboard.html").render(
        accounts_total=accounts_total, active=active, awaiting=awaiting,
        total_rentals=total_rentals, total_hours=total_hours,
        total_revenue=round(total_revenue, 2),
        recent=recent, acc_map=acc_map,
    )
    return web.Response(text=html, content_type="text/html")


# ─── Аккаунты ───

async def accounts_list(request: web.Request):
    rank = request.query.get("rank", "").strip()
    owner_filter = request.query.get("owner", "").strip()

    async with async_session() as session:
        q = select(Account).order_by(Account.rank, Account.id)
        if rank:
            q = q.where(Account.rank == rank)
        if owner_filter == "me":
            q = q.where(Account.partner_id.is_(None))
        elif owner_filter == "partner":
            q = q.where(Account.partner_id.isnot(None))

        accounts = (await session.execute(q)).scalars().all()
        ranks = (await session.execute(
            select(Account.rank).distinct().order_by(Account.rank)
        )).scalars().all()

    html = env.get_template("accounts.html").render(
        accounts=accounts, ranks=ranks, current_rank=rank,
        owner_filter=owner_filter, timedelta=timedelta,
    )
    return web.Response(text=html, content_type="text/html")


async def account_detail(request: web.Request):
    acc_id = int(request.match_info["id"])
    period = request.query.get("period", "all")
    now = datetime.utcnow()
    since = {"7d": now - timedelta(days=7), "30d": now - timedelta(days=30)}.get(
        period, datetime(1970, 1, 1)
    )

    async with async_session() as session:
        account = await session.get(Account, acc_id)
        if not account:
            raise web.HTTPNotFound()

        stats = (await session.execute(
            select(
                func.count(RentalHistory.id),
                func.coalesce(func.sum(RentalHistory.hours), 0),
                func.coalesce(func.sum(RentalHistory.amount), 0),
            ).where(
                RentalHistory.account_id == acc_id,
                RentalHistory.started_at >= since,
            )
        )).first()

        history = (await session.execute(
            select(RentalHistory)
            .where(RentalHistory.account_id == acc_id)
            .order_by(desc(RentalHistory.started_at))
            .limit(20)
        )).scalars().all()

    recent_matches = await get_recent_matches(account.riot_id) if account.riot_id else []

    html = env.get_template("account_detail.html").render(
        a=account, period=period,
        rentals=stats[0], hours=stats[1], revenue=round(stats[2], 2),
        history=history, recent_matches=recent_matches,
    )
    return web.Response(text=html, content_type="text/html")


async def account_add_page(request: web.Request):
    bot = request.app["bot"]
    error = None

    if request.method == "POST":
        post = await request.post()
        photo_id = None
        pf = _maybe_photo_field(post)
        if pf:
            try:
                photo_id = await _upload_photo_to_telegram(bot, pf.file.read(), pf.filename)
            except Exception as e:
                logging.warning(f"photo add: {e}")

        try:
            acc = Account(
                login=post["login"].strip(),
                password=post["password"].strip(),
                email=(post.get("email") or "").strip() or None,
                email_password=(post.get("email_password") or "").strip() or None,
                riot_id=(post.get("riot_id") or "").strip() or None,
                rank=post["rank"].strip(),
                tier=post.get("tier", "standard"),
                price_3h=float(post["price_3h"]),
                price_6h=float(post["price_6h"]),
                price_12h=float(post["price_12h"]),
                photo_id=photo_id,
                status="free",
            )
        except (KeyError, ValueError) as e:
            error = f"Ошибка: {e}"
        else:
            async with async_session() as session:
                session.add(acc)
                await session.commit()
                acc_id = acc.id
            notifications.push("Добавлен аккаунт", f"#{acc_id} · {acc.rank}", level="success")
            raise web.HTTPFound(f"/accounts/{acc_id}")

    html = env.get_template("account_add.html").render(error=error)
    return web.Response(text=html, content_type="text/html")


async def account_edit_page(request: web.Request):
    bot = request.app["bot"]
    acc_id = int(request.match_info["id"])
    error = None

    async with async_session() as session:
        account = await session.get(Account, acc_id)
        if not account:
            raise web.HTTPNotFound()

        if request.method == "POST":
            post = await request.post()

            if post.get("remove_photo"):
                account.photo_id = None
            else:
                pf = _maybe_photo_field(post)
                if pf:
                    try:
                        new_id = await _upload_photo_to_telegram(bot, pf.file.read(), pf.filename)
                        if new_id:
                            account.photo_id = new_id
                    except Exception as e:
                        logging.warning(f"photo edit: {e}")

            try:
                account.login = post["login"].strip()
                account.password = post["password"].strip()
                account.email = (post.get("email") or "").strip() or None
                account.email_password = (post.get("email_password") or "").strip() or None
                account.riot_id = (post.get("riot_id") or "").strip() or None
                account.rank = post["rank"].strip()
                account.tier = post.get("tier", "standard")
                account.price_3h = float(post["price_3h"])
                account.price_6h = float(post["price_6h"])
                account.price_12h = float(post["price_12h"])
                await session.commit()
                notifications.push("Аккаунт обновлён", f"#{acc_id}", level="success")
                raise web.HTTPFound(f"/accounts/{acc_id}")
            except (KeyError, ValueError) as e:
                error = f"Ошибка: {e}"

    html = env.get_template("account_edit.html").render(a=account, error=error)
    return web.Response(text=html, content_type="text/html")


async def account_delete(request: web.Request):
    acc_id = int(request.match_info["id"])
    async with async_session() as session:
        acc = await session.get(Account, acc_id)
        if acc:
            await session.delete(acc)
            await session.commit()
    raise web.HTTPFound("/accounts")


# ─── Ожидают смены пароля ───

async def awaiting_list(request: web.Request):
    async with async_session() as session:
        all_accounts = (await session.execute(
            select(Account).where(
                Account.status.in_(["awaiting_password_change", "awaiting_review"])
            )
        )).scalars().all()

    my_accounts = [a for a in all_accounts if not a.partner_id]
    partner_accounts = [a for a in all_accounts if a.partner_id]

    html = env.get_template("password_change.html").render(
        my_accounts=my_accounts,
        partner_accounts=partner_accounts,
    )
    return web.Response(text=html, content_type="text/html")


async def mark_password_changed(request: web.Request):
    acc_id = int(request.match_info["id"])
    data = await request.post()
    new_password = (data.get("new_password") or "").strip()
    async with async_session() as session:
        acc = await session.get(Account, acc_id)
        if acc:
            if new_password:
                acc.password = new_password
            acc.status = "free"
            acc.buyer_id = None
            acc.rental_hours = None
            acc.rented_until = None
            acc.reserved_at = None
            acc.payment_invoice_id = None
            acc.password_changed_at = datetime.utcnow()
            await session.commit()
            notifications.push("Пароль сменён", f"#{acc_id} — снова свободен", level="success")
    raise web.HTTPFound("/password-change")


# ─── Экспорт ───

async def export_page(request: web.Request):
    if request.query.get("download") == "1":
        async with async_session() as session:
            accounts = (await session.execute(
                select(Account).order_by(Account.id)
            )).scalars().all()
        lines = [
            f"{a.login};;{a.password};;{a.rank};;"
            f"{a.price_3h:g},{a.price_6h:g},{a.price_12h:g}"
            for a in accounts
        ]
        return web.Response(
            body="\n".join(lines), content_type="text/plain",
            headers={"Content-Disposition": 'attachment; filename="accounts.txt"'},
        )
    html = env.get_template("export.html").render()
    return web.Response(text=html, content_type="text/html")


# ─── API уведомлений ───

async def notifications_api(request: web.Request):
    since_id = int(request.query.get("since", "0"))
    return web.json_response(notifications.since(since_id))


async def notifications_page(request: web.Request):
    cat = request.query.get("cat", "all")
    events = notifications.get_all(category=cat)
    html = env.get_template("notifications.html").render(events=events, cat=cat)
    return web.Response(text=html, content_type="text/html")


# ─── Настройки ───

async def settings_page(request: web.Request):
    error = None
    success = None

    async with async_session() as session:
        if request.method == "POST":
            post = await request.post()
            action = post.get("action")

            if action == "save_commission":
                try:
                    commission = float(post.get("commission", "10"))
                    if commission < 0 or commission > 100:
                        raise ValueError("должно быть 0–100")
                    await set_setting(session, "partner_commission", str(commission))
                    success = f"Комиссия обновлена: {commission}%"
                except (ValueError, KeyError) as e:
                    error = f"Неверная комиссия: {e}"

            elif action == "add_rank":
                try:
                    rank_name = post["rank"].strip()
                    if not rank_name:
                        raise ValueError("название ранга обязательно")
                    p3 = float(post["price_3h"])
                    p6 = float(post["price_6h"])
                    p12 = float(post["price_12h"])
                    if p3 <= 0 or p6 <= 0 or p12 <= 0:
                        raise ValueError("все цены должны быть больше 0")
                    if p6 < p3 or p12 < p6:
                        raise ValueError("цены должны расти: 3ч ≤ 6ч ≤ 12ч")

                    existing = (await session.execute(
                        select(RankSetting).where(RankSetting.rank == rank_name)
                    )).scalar_one_or_none()

                    if existing:
                        existing.min_price_3h = p3
                        existing.min_price_6h = p6
                        existing.min_price_12h = p12
                        success = f"Ранг {rank_name} обновлён"
                    else:
                        session.add(RankSetting(
                            rank=rank_name,
                            min_price_3h=p3, min_price_6h=p6, min_price_12h=p12,
                        ))
                        success = f"Ранг {rank_name} добавлен"
                    await session.commit()
                except (ValueError, KeyError) as e:
                    error = f"Ошибка: {e}"

            elif action == "delete_rank":
                try:
                    rank_id = int(post["rank_id"])
                    rank_row = await session.get(RankSetting, rank_id)
                    if rank_row:
                        name = rank_row.rank
                        await session.delete(rank_row)
                        await session.commit()
                        success = f"Ранг {name} удалён"
                except (ValueError, KeyError) as e:
                    error = f"Ошибка удаления: {e}"

        commission_str = await get_setting(session, "partner_commission", "10")
        try:
            commission_float = float(commission_str)
        except (TypeError, ValueError):
            commission_float = 10.0
        partner_share = 100.0 - commission_float

        ranks = (await session.execute(
            select(RankSetting).order_by(RankSetting.rank)
        )).scalars().all()

    html = env.get_template("settings.html").render(
        commission=commission_float,
        partner_share=round(partner_share, 1),
        ranks=ranks, error=error, success=success,
    )
    return web.Response(text=html, content_type="text/html")


# ═══════════════════════════════════════════════════════════════
# ПАРТНЁРЫ (без изменений — оставь свою версию)
# ═══════════════════════════════════════════════════════════════

# ... все функции partners_* (partners_dashboard, partners_list, partner_detail,
#     partner_block, partner_unblock, partner_payout_direct, partners_approvals,
#     partner_approve, partner_reject, partners_passwords,
#     partner_password_approve, partner_password_reject, partners_payouts,
#     partner_payout_pay, partner_payout_reject) — ОСТАВЬ КАК ЕСТЬ, не трогай.
# ═══════════════════════════════════════════════════════════════
# ПОКУПАТЕЛИ
# ═══════════════════════════════════════════════════════════════

async def customers_list(request: web.Request):
    async with async_session() as session:
        buyer_ids = (await session.execute(
            select(RentalHistory.buyer_id).distinct()
            .where(RentalHistory.buyer_id.isnot(None))
        )).scalars().all()

        if buyer_ids:
            existing = (await session.execute(
                select(Customer.telegram_id).where(Customer.telegram_id.in_(buyer_ids))
            )).scalars().all()
            existing_set = set(existing)
            for bid in buyer_ids:
                if bid not in existing_set:
                    session.add(Customer(telegram_id=bid, is_banned=False))
            if len(existing_set) < len(buyer_ids):
                await session.commit()

        custs = (await session.execute(
            select(Customer).order_by(Customer.created_at.desc())
        )).scalars().all()

        stats_rows = (await session.execute(
            select(
                RentalHistory.buyer_id,
                func.coalesce(func.sum(RentalHistory.amount), 0),
                func.coalesce(func.sum(RentalHistory.hours), 0),
                func.count(RentalHistory.id),
            ).where(RentalHistory.buyer_id.isnot(None))
            .group_by(RentalHistory.buyer_id)
        )).all()

        stats = {
            r[0]: {"spent": round(r[1] or 0, 2), "hours": int(r[2] or 0), "count": int(r[3] or 0)}
            for r in stats_rows
        }

        result = []
        for c in custs:
            st = stats.get(c.telegram_id, {"spent": 0, "hours": 0, "count": 0})
            result.append({"customer": c, **st})
        result.sort(key=lambda x: x["spent"], reverse=True)

    html = env.get_template("customers.html").render(customers=result)
    return web.Response(text=html, content_type="text/html")


async def customer_detail(request: web.Request):
    customer_id = int(request.match_info["id"])

    async with async_session() as session:
        customer = await session.get(Customer, customer_id)
        if not customer:
            raise web.HTTPNotFound()

        stats = (await session.execute(
            select(
                func.coalesce(func.sum(RentalHistory.amount), 0),
                func.coalesce(func.sum(RentalHistory.hours), 0),
                func.count(RentalHistory.id),
            ).where(RentalHistory.buyer_id == customer_id)
        )).first()

        fav = (await session.execute(
            select(Account.rank, func.count(RentalHistory.id).label("cnt"))
            .join(Account, Account.id == RentalHistory.account_id)
            .where(RentalHistory.buyer_id == customer_id)
            .group_by(Account.rank)
            .order_by(func.count(RentalHistory.id).desc())
            .limit(1)
        )).first()

        since_30 = datetime.utcnow() - timedelta(days=30)
        activity = (await session.execute(
            select(func.date(RentalHistory.started_at), func.count(RentalHistory.id))
            .where(
                RentalHistory.buyer_id == customer_id,
                RentalHistory.started_at >= since_30,
            )
            .group_by(func.date(RentalHistory.started_at))
        )).all()

        activity_map = {}
        for d, cnt in activity:
            key = d.isoformat() if hasattr(d, "isoformat") else str(d)
            activity_map[key] = cnt

        days = []
        for i in range(29, -1, -1):
            day = (datetime.utcnow() - timedelta(days=i)).date()
            days.append({"date": day.isoformat(), "count": activity_map.get(day.isoformat(), 0)})

        history = (await session.execute(
            select(RentalHistory, Account.rank)
            .join(Account, Account.id == RentalHistory.account_id)
            .where(RentalHistory.buyer_id == customer_id)
            .order_by(desc(RentalHistory.started_at))
            .limit(50)
        )).all()

    html = env.get_template("customer_detail.html").render(
        c=customer,
        total_spent=round(stats[0] or 0, 2),
        total_hours=int(stats[1] or 0),
        total_rentals=int(stats[2] or 0),
        favorite_rank=fav[0] if fav else "—",
        activity_days=days,
        history=history,
    )
    return web.Response(text=html, content_type="text/html")


async def customer_ban(request: web.Request):
    customer_id = int(request.match_info["id"])
    data = await request.post()
    reason = (data.get("reason") or "").strip() or "Не указана"

    async with async_session() as session:
        customer = await session.get(Customer, customer_id)
        if customer:
            customer.is_banned = True
            customer.ban_reason = reason
            customer.banned_at = datetime.utcnow()
            await session.commit()
            notifications.push(
                "🚫 Покупатель забанен",
                f"ID {customer_id} · причина: {reason}",
                level="warning",
            )
    raise web.HTTPFound(f"/customers/{customer_id}")


async def customer_unban(request: web.Request):
    customer_id = int(request.match_info["id"])
    async with async_session() as session:
        customer = await session.get(Customer, customer_id)
        if customer:
            customer.is_banned = False
            customer.ban_reason = None
            customer.banned_at = None
            await session.commit()
            notifications.push("✅ Покупатель разбанен", f"ID {customer_id}", level="success")
    raise web.HTTPFound(f"/customers/{customer_id}")
    # Покупатели
    app.router.add_get("/customers", customers_list)
    app.router.add_get("/customers/{id}", customer_detail)
    app.router.add_post("/customers/{id}/ban", customer_ban)
    app.router.add_post("/customers/{id}/unban", customer_unban)
