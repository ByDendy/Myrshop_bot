import logging
import json
from datetime import datetime, timedelta
from pathlib import Path

from aiohttp import web
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from passlib.context import CryptContext
from sqlalchemy import select, func, desc, or_
from jinja2 import Environment, FileSystemLoader, select_autoescape
from aiogram.types import BufferedInputFile

from config import WEB_ADMIN_PASSWORD, WEB_SECRET_KEY, ADMIN_IDS
from database.models import (
    Account, RentalHistory, RankSetting, Customer, Manager,
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

# Регистрируем фильтр from_json для шаблона settings.html
env.filters["from_json"] = lambda s: json.loads(s) if s else {}

serializer = URLSafeTimedSerializer(WEB_SECRET_KEY, salt="web-session")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_MAX_AGE = 60 * 60 * 24 * 7

ALL_PERMISSIONS = [
    "can_view_dashboard", "can_edit_accounts", "can_manage_partners",
    "can_check_passwords", "can_pay_partners", "can_ban_customers", "can_edit_settings"
]


# ─── Авторизация ───

def _get_token_data(request: web.Request):
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        return serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


@web.middleware
async def auth_middleware(request, handler):
    public_paths = ("/login", "/api/photo/", "/privacy", "/consent", "/terms", "/partner-auth", "/static")
    if any(request.path.startswith(p) for p in public_paths):
        return await handler(request)

    data = _get_token_data(request)
    if not data:
        raise web.HTTPFound("/login")

    # Если это партнёр
    if data.get("type") == "partner":
        if not request.path.startswith("/partner-portal"):
            raise web.HTTPForbidden(text="Доступ только в личный кабинет.")
        request["user"] = {"role": "partner", "partner_id": data["id"]}
        return await handler(request)

    # Если это владелец или менеджер
    if data.get("type") == "owner":
        request["user"] = {"role": "owner", "all_perms": True, "perms": {}}
    elif data.get("type") == "manager":
        async with async_session() as session:
            mgr = await session.get(Manager, data["id"])
            if not mgr:
                raise web.HTTPFound("/login")
            perms = json.loads(mgr.permissions) if mgr.permissions else {}
            request["user"] = {"role": "manager", "perms": perms, "all_perms": False}
    else:
        raise web.HTTPFound("/login")

    # Защита URL от прямого ввода
    user = request["user"]
    if not user["all_perms"]:
        perms = user["perms"]
        if request.path == "/" and not perms.get("can_view_dashboard"): raise web.HTTPForbidden()
        if request.path.startswith("/accounts") and not perms.get("can_edit_accounts"): raise web.HTTPForbidden()
        if request.path.startswith("/customers") and not perms.get("can_ban_customers"): raise web.HTTPForbidden()
        if request.path.startswith("/partners") and not perms.get("can_manage_partners"): raise web.HTTPForbidden()
        if request.path.startswith("/partners/passwords") and not perms.get("can_check_passwords"): raise web.HTTPForbidden()
        if request.path.startswith("/partners/payouts") and not perms.get("can_pay_partners"): raise web.HTTPForbidden()
        if request.path.startswith("/settings") and not perms.get("can_edit_settings"): raise web.HTTPForbidden()

    return await handler(request)


async def login_page(request: web.Request):
    error = None
    if request.method == "POST":
        data = await request.post()
        login = data.get("login", "").strip()
        pwd = data.get("password", "")

        # 1. Владелец (пустой логин)
        if not login and pwd == WEB_ADMIN_PASSWORD:
            token = serializer.dumps({"type": "owner"})
            resp = web.HTTPFound("/")
            resp.set_cookie("session", token, max_age=SESSION_MAX_AGE, httponly=True)
            raise resp

        # 2. Менеджер
        if login:
            async with async_session() as session:
                mgr = (await session.execute(select(Manager).where(Manager.login == login))).scalar_one_or_none()
                if mgr and pwd_context.verify(pwd, mgr.password_hash):
                    token = serializer.dumps({"type": "manager", "id": mgr.id})
                    resp = web.HTTPFound("/")
                    resp.set_cookie("session", token, max_age=SESSION_MAX_AGE, httponly=True)
                    raise resp

        error = "Неверный логин или пароль"

    html = env.get_template("login.html").render(error=error)
    return web.Response(text=html, content_type="text/html")


async def partner_auth(request: web.Request):
    token = request.query.get("token")
    if not token:
        raise web.HTTPForbidden(text="Токен не передан")

    try:
        data = serializer.loads(token, max_age=900)  # 15 минут
    except SignatureExpired:
        raise web.HTTPForbidden(text="Ссылка истекла. Запросите новую в боте.")
    except BadSignature:
        raise web.HTTPForbidden(text="Неверная ссылка.")

    new_token = serializer.dumps({"type": "partner", "id": data["id"]})
    resp = web.HTTPFound("/partner-portal")
    resp.set_cookie("session", new_token, max_age=SESSION_MAX_AGE, httponly=True)
    raise resp


async def logout(request: web.Request):
    resp = web.HTTPFound("/login")
    resp.del_cookie("session")
    raise resp


# ─── Портал Партнёра ───

async def partner_portal(request: web.Request):
    partner_id = request["user"]["partner_id"]
    async with async_session() as session:
        partner = await session.get(Partner, partner_id)
        accounts = (await session.execute(select(Account).where(Account.partner_id == partner_id))).scalars().all()
        payouts = (await session.execute(select(PartnerPayout).where(PartnerPayout.partner_id == partner_id).order_by(desc(PartnerPayout.requested_at)).limit(10))).scalars().all()
        rentals = (await session.execute(select(func.count(RentalHistory.id)).join(Account).where(Account.partner_id == partner_id))).scalar() or 0

    html = env.get_template("partner_portal.html").render(p=partner, accounts=accounts, payouts=payouts, rentals=rentals)
    return web.Response(text=html, content_type="text/html")


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
        accounts_total = (await session.execute(select(func.count(Account.id)))).scalar() or 0
        active = (await session.execute(select(func.count(Account.id)).where(Account.status == "rented"))).scalar() or 0
        awaiting = (await session.execute(select(func.count(Account.id)).where(Account.status == "awaiting_password_change"))).scalar() or 0
        total_rentals = (await session.execute(select(func.count(RentalHistory.id)))).scalar() or 0
        total_hours = (await session.execute(select(func.coalesce(func.sum(RentalHistory.hours), 0)))).scalar() or 0
        total_revenue = (await session.execute(select(func.coalesce(func.sum(RentalHistory.amount), 0)))).scalar() or 0
        recent = (await session.execute(select(RentalHistory).order_by(desc(RentalHistory.started_at)).limit(10))).scalars().all()

        acc_map = {}
        if recent:
            ids = [r.account_id for r in recent]
            accs = (await session.execute(select(Account).where(Account.id.in_(ids)))).scalars().all()
            acc_map = {a.id: a for a in accs}

    html = env.get_template("dashboard.html").render(
        accounts_total=accounts_total, active=active, awaiting=awaiting,
        total_rentals=total_rentals, total_hours=total_hours,
        total_revenue=round(total_revenue, 2), recent=recent, acc_map=acc_map,
        user=request.get("user")
    )
    return web.Response(text=html, content_type="text/html")


# ─── Аккаунты ───

async def accounts_list(request: web.Request):
    rank = request.query.get("rank", "").strip()
    owner_filter = request.query.get("owner", "").strip()

    async with async_session() as session:
        q = select(Account).order_by(Account.rank, Account.id)
        if rank: q = q.where(Account.rank == rank)
        if owner_filter == "me": q = q.where(Account.partner_id.is_(None))
        elif owner_filter == "partner": q = q.where(Account.partner_id.isnot(None))

        accounts = (await session.execute(q)).scalars().all()
        ranks = (await session.execute(select(Account.rank).distinct().order_by(Account.rank))).scalars().all()

    html = env.get_template("accounts.html").render(
        accounts=accounts, ranks=ranks, current_rank=rank,
        owner_filter=owner_filter, timedelta=timedelta, user=request.get("user")
    )
    return web.Response(text=html, content_type="text/html")


async def account_detail(request: web.Request):
    acc_id = int(request.match_info["id"])
    period = request.query.get("period", "all")
    now = datetime.utcnow()
    since = {"7d": now - timedelta(days=7), "30d": now - timedelta(days=30)}.get(period, datetime(1970, 1, 1))

    async with async_session() as session:
        account = await session.get(Account, acc_id)
        if not account: raise web.HTTPNotFound()

        stats = (await session.execute(
            select(func.count(RentalHistory.id), func.coalesce(func.sum(RentalHistory.hours), 0), func.coalesce(func.sum(RentalHistory.amount), 0))
            .where(RentalHistory.account_id == acc_id, RentalHistory.started_at >= since)
        )).first()

        history = (await session.execute(select(RentalHistory).where(RentalHistory.account_id == acc_id).order_by(desc(RentalHistory.started_at)).limit(20))).scalars().all()

    recent_matches = await get_recent_matches(account.riot_id) if account.riot_id else []

    html = env.get_template("account_detail.html").render(
        a=account, period=period, rentals=stats[0], hours=stats[1], revenue=round(stats[2], 2),
        history=history, recent_matches=recent_matches, user=request.get("user")
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
            try: photo_id = await _upload_photo_to_telegram(bot, pf.file.read(), pf.filename)
            except Exception as e: logging.warning(f"photo add: {e}")

        try:
            acc = Account(
                login=post["login"].strip(), password=post["password"].strip(),
                email=(post.get("email") or "").strip() or None, email_password=(post.get("email_password") or "").strip() or None,
                riot_id=(post.get("riot_id") or "").strip() or None, rank=post["rank"].strip(), tier=post.get("tier", "standard"),
                price_3h=float(post["price_3h"]), price_6h=float(post["price_6h"]), price_12h=float(post["price_12h"]),
                photo_id=photo_id, status="free",
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

    html = env.get_template("account_add.html").render(error=error, user=request.get("user"))
    return web.Response(text=html, content_type="text/html")


async def account_edit_page(request: web.Request):
    bot = request.app["bot"]
    acc_id = int(request.match_info["id"])
    error = None

    async with async_session() as session:
        account = await session.get(Account, acc_id)
        if not account: raise web.HTTPNotFound()

        if request.method == "POST":
            post = await request.post()
            if post.get("remove_photo"): account.photo_id = None
            else:
                pf = _maybe_photo_field(post)
                if pf:
                    try:
                        new_id = await _upload_photo_to_telegram(bot, pf.file.read(), pf.filename)
                        if new_id: account.photo_id = new_id
                    except Exception as e: logging.warning(f"photo edit: {e}")

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

    html = env.get_template("account_edit.html").render(a=account, error=error, user=request.get("user"))
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
        all_accounts = (await session.execute(select(Account).where(Account.status.in_(["awaiting_password_change", "awaiting_review"])))).scalars().all()

    my_accounts = [a for a in all_accounts if not a.partner_id]
    partner_accounts = [a for a in all_accounts if a.partner_id]

    html = env.get_template("password_change.html").render(
        my_accounts=my_accounts, partner_accounts=partner_accounts, user=request.get("user")
    )
    return web.Response(text=html, content_type="text/html")


async def mark_password_changed(request: web.Request):
    acc_id = int(request.match_info["id"])
    data = await request.post()
    new_password = (data.get("new_password") or "").strip()
    async with async_session() as session:
        acc = await session.get(Account, acc_id)
        if acc:
            if new_password: acc.password = new_password
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


# ─── Покупатели ───

async def customers_list(request: web.Request):
    async with async_session() as session:
        buyer_ids = (await session.execute(select(RentalHistory.buyer_id).distinct().where(RentalHistory.buyer_id.isnot(None)))).scalars().all()

        if buyer_ids:
            existing = (await session.execute(select(Customer.telegram_id).where(Customer.telegram_id.in_(buyer_ids)))).scalars().all()
            existing_set = set(existing)
            for bid in buyer_ids:
                if bid not in existing_set: session.add(Customer(telegram_id=bid, is_banned=False))
            if len(existing_set) < len(buyer_ids): await session.commit()

        custs = (await session.execute(select(Customer).order_by(Customer.created_at.desc()))).scalars().all()

        stats_rows = (await session.execute(
            select(RentalHistory.buyer_id, func.coalesce(func.sum(RentalHistory.amount), 0), func.coalesce(func.sum(RentalHistory.hours), 0), func.count(RentalHistory.id))
            .where(RentalHistory.buyer_id.isnot(None)).group_by(RentalHistory.buyer_id)
        )).all()

        stats = {r[0]: {"spent": round(r[1] or 0, 2), "hours": int(r[2] or 0), "count": int(r[3] or 0)} for r in stats_rows}

        result = []
        for c in custs:
            st = stats.get(c.telegram_id, {"spent": 0, "hours": 0, "count": 0})
            result.append({"customer": c, **st})
        result.sort(key=lambda x: x["spent"], reverse=True)

    html = env.get_template("customers.html").render(customers=result, user=request.get("user"))
    return web.Response(text=html, content_type="text/html")


async def customer_detail(request: web.Request):
    customer_id = int(request.match_info["id"])
    async with async_session() as session:
        customer = await session.get(Customer, customer_id)
        if not customer: raise web.HTTPNotFound()

        stats = (await session.execute(
            select(func.coalesce(func.sum(RentalHistory.amount), 0), func.coalesce(func.sum(RentalHistory.hours), 0), func.count(RentalHistory.id))
            .where(RentalHistory.buyer_id == customer_id)
        )).first()

        fav = (await session.execute(
            select(Account.rank, func.count(RentalHistory.id).label("cnt"))
            .join(Account, Account.id == RentalHistory.account_id)
            .where(RentalHistory.buyer_id == customer_id).group_by(Account.rank)
            .order_by(func.count(RentalHistory.id).desc()).limit(1)
        )).first()

        since_30 = datetime.utcnow() - timedelta(days=30)
        activity = (await session.execute(
            select(func.date(RentalHistory.started_at), func.count(RentalHistory.id))
            .where(RentalHistory.buyer_id == customer_id, RentalHistory.started_at >= since_30)
            .group_by(func.date(RentalHistory.started_at))
        )).all()

        activity_map = {}
        for d, cnt in activity:
            key = d.isoformat() if hasattr(d, "isoformat") else str(d)
            activity_map[key] = cnt

        days = []
        start_date = (datetime.utcnow() - timedelta(days=29)).date()
        for _ in range(start_date.weekday()): days.append({"date": "", "count": -1})
        for i in range(29, -1, -1):
            day = (datetime.utcnow() - timedelta(days=i)).date()
            days.append({"date": day.strftime('%d.%m.%Y'), "count": activity_map.get(day.isoformat(), 0)})

        history = (await session.execute(
            select(RentalHistory, Account.rank).join(Account, Account.id == RentalHistory.account_id)
            .where(RentalHistory.buyer_id == customer_id).order_by(desc(RentalHistory.started_at)).limit(50)
        )).all()

    html = env.get_template("customer_detail.html").render(
        c=customer, total_spent=round(stats[0] or 0, 2), total_hours=int(stats[1] or 0), total_rentals=int(stats[2] or 0),
        favorite_rank=fav[0] if fav else "—", activity_days=days, history=history, user=request.get("user")
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
            notifications.push("🚫 Покупатель забанен", f"ID {customer_id} · причина: {reason}", level="warning")
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


# ─── Экспорт ───

async def export_page(request: web.Request):
    if request.query.get("download") == "1":
        async with async_session() as session:
            accounts = (await session.execute(select(Account).order_by(Account.id))).scalars().all()
        lines = [f"{a.login};;{a.password};;{a.rank};;{a.price_3h:g},{a.price_6h:g},{a.price_12h:g}" for a in accounts]
        return web.Response(body="\n".join(lines), content_type="text/plain", headers={"Content-Disposition": 'attachment; filename="accounts.txt"'})
    html = env.get_template("export.html").render(user=request.get("user"))
    return web.Response(text=html, content_type="text/html")


# ─── API уведомлений ───

async def notifications_api(request: web.Request):
    since_id = int(request.query.get("since", "0"))
    return web.json_response(notifications.since(since_id))


async def notifications_page(request: web.Request):
    cat = request.query.get("cat", "all")
    events = notifications.get_all(category=cat)
    html = env.get_template("notifications.html").render(events=events, cat=cat, user=request.get("user"))
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
                    if commission < 0 or commission > 100: raise ValueError("должно быть 0–100")
                    await set_setting(session, "partner_commission", str(commission))
                    success = f"Комиссия обновлена: {commission}%"
                except (ValueError, KeyError) as e: error = f"Неверная комиссия: {e}"

            elif action == "add_rank":
                try:
                    rank_name = post["rank"].strip()
                    if not rank_name: raise ValueError("название ранга обязательно")
                    p3 = float(post["price_3h"]); p6 = float(post["price_6h"]); p12 = float(post["price_12h"])
                    if p3 <= 0 or p6 <= 0 or p12 <= 0: raise ValueError("все цены должны быть больше 0")
                    if p6 < p3 or p12 < p6: raise ValueError("цены должны расти: 3ч ≤ 6ч ≤ 12ч")

                    existing = (await session.execute(select(RankSetting).where(RankSetting.rank == rank_name))).scalar_one_or_none()
                    if existing:
                        existing.min_price_3h = p3; existing.min_price_6h = p6; existing.min_price_12h = p12
                        success = f"Ранг {rank_name} обновлён"
                    else:
                        session.add(RankSetting(rank=rank_name, min_price_3h=p3, min_price_6h=p6, min_price_12h=p12))
                        success = f"Ранг {rank_name} добавлен"
                    await session.commit()
                except (ValueError, KeyError) as e: error = f"Ошибка: {e}"

            elif action == "delete_rank":
                try:
                    rank_id = int(post["rank_id"])
                    rank_row = await session.get(RankSetting, rank_id)
                    if rank_row:
                        name = rank_row.rank
                        await session.delete(rank_row)
                        await session.commit()
                        success = f"Ранг {name} удалён"
                except (ValueError, KeyError) as e: error = f"Ошибка удаления: {e}"

            elif action == "add_manager":
                try:
                    login = post["login"].strip()
                    pwd = post["password"].strip()
                    if len(login) < 3 or len(pwd) < 6: raise ValueError("Логин от 3 символов, пароль от 6.")
                    
                    existing = (await session.execute(select(Manager).where(Manager.login == login))).scalar_one_or_none()
                    if existing: raise ValueError("Такой логин уже существует")

                    perms = {p: True for p in ALL_PERMISSIONS if post.get(p) == "on"}
                    session.add(Manager(login=login, password_hash=pwd_context.hash(pwd), permissions=json.dumps(perms)))
                    await session.commit()
                    success = f"Менеджер {login} создан"
                except (ValueError, KeyError) as e: error = f"Ошибка: {e}"

            elif action == "delete_manager":
                try:
                    mid = int(post["manager_id"])
                    mgr = await session.get(Manager, mid)
                    if mgr:
                        await session.delete(mgr)
                        await session.commit()
                        success = "Менеджер удалён"
                except (ValueError, KeyError) as e: error = f"Ошибка: {e}"

        commission_str = await get_setting(session, "partner_commission", "10")
        try: commission_float = float(commission_str)
        except (TypeError, ValueError): commission_float = 10.0
        partner_share = 100.0 - commission_float

        ranks = (await session.execute(select(RankSetting).order_by(RankSetting.rank))).scalars().all()
        managers = (await session.execute(select(Manager).order_by(Manager.id))).scalars().all()

    html = env.get_template("settings.html").render(
        commission=commission_float, partner_share=round(partner_share, 1),
        ranks=ranks, managers=managers, error=error, success=success,
        user=request.get("user")
    )
    return web.Response(text=html, content_type="text/html")


# ═══════════════════════════════════════════════════════════════
# ПАРТНЁРЫ
# ═══════════════════════════════════════════════════════════════

async def partners_dashboard(request: web.Request):
    async with async_session() as session:
        partners_active = (await session.execute(select(func.count(Partner.id)).where(Partner.status == "active"))).scalar() or 0
        accounts_total = (await session.execute(select(func.count(Account.id)).where(Account.partner_id.isnot(None)))).scalar() or 0
        pending_moderation = (await session.execute(select(func.count(Account.id)).where(Account.status.in_(["pending_approval", "awaiting_approval"])))).scalar() or 0
        pending_payouts = (await session.execute(select(func.count(PartnerPayout.id)).where(PartnerPayout.status == "requested"))).scalar() or 0
        pending_payout_amount = (await session.execute(select(func.coalesce(func.sum(PartnerPayout.amount), 0)).where(PartnerPayout.status == "requested"))).scalar() or 0

        cutoff = datetime.utcnow() - timedelta(days=30)
        revenue_30d = (await session.execute(select(func.coalesce(func.sum(PartnerEarning.amount), 0)).where(PartnerEarning.created_at >= cutoff))).scalar() or 0

        total_balance = (await session.execute(select(func.coalesce(func.sum(Partner.balance), 0)))).scalar() or 0
        total_frozen = (await session.execute(select(func.coalesce(func.sum(Partner.frozen_balance), 0)))).scalar() or 0
        total_paid = (await session.execute(select(func.coalesce(func.sum(Partner.total_paid), 0)))).scalar() or 0

        recent_events_raw = notifications.get_all(category="partner")[:10]
        recent_events = [{"partner_id": 0, "partner_name": "—", "event": e["title"] + (" — " + e["text"] if e["text"] else ""), "ts": e["ts"]} for e in recent_events_raw]

    html = env.get_template("partners_dashboard.html").render(
        partners_active=partners_active, accounts_total=accounts_total, pending_moderation=pending_moderation,
        pending_payouts=pending_payouts, pending_payout_amount=round(pending_payout_amount),
        revenue_30d=round(revenue_30d), total_balance=round(total_balance),
        total_frozen=round(total_frozen), total_paid=round(total_paid), recent_events=recent_events,
        user=request.get("user")
    )
    return web.Response(text=html, content_type="text/html")


async def partners_list(request: web.Request):
    q = request.query.get("q", "").strip()
    status_filter = request.query.get("status", "").strip()

    async with async_session() as session:
        query = select(Partner)
        if q: query = query.where(or_(Partner.full_name.ilike(f"%{q}%"), Partner.username.ilike(f"%{q}%")))
        if status_filter: query = query.where(Partner.status == status_filter)
        query = query.order_by(Partner.id.desc())

        partners_raw = (await session.execute(query)).scalars().all()
        partners_data = []
        for p in partners_raw:
            cnt = (await session.execute(select(func.count(Account.id)).where(Account.partner_id == p.id))).scalar() or 0
            partners_data.append({"id": p.id, "full_name": p.full_name, "username": p.username, "telegram_id": p.telegram_id, "balance": round(p.balance or 0), "total_earned": round(p.total_earned or 0), "status": p.status, "accounts_count": cnt})

    html = env.get_template("partners_list.html").render(partners=partners_data, q=q, status_filter=status_filter, user=request.get("user"))
    return web.Response(text=html, content_type="text/html")


async def partner_detail(request: web.Request):
    partner_id = int(request.match_info["id"])
    async with async_session() as session:
        partner = await session.get(Partner, partner_id)
        if not partner: raise web.HTTPNotFound()

        accounts = (await session.execute(select(Account).where(Account.partner_id == partner_id).order_by(Account.id.desc()))).scalars().all()
        payouts = (await session.execute(select(PartnerPayout).where(PartnerPayout.partner_id == partner_id).order_by(desc(PartnerPayout.requested_at)).limit(20))).scalars().all()
        earnings = (await session.execute(select(PartnerEarning).where(PartnerEarning.partner_id == partner_id).order_by(desc(PartnerEarning.created_at)).limit(30))).scalars().all()
        acc_map = {a.id: a for a in accounts}

        pending_request = (await session.execute(select(PartnerPayout).where(PartnerPayout.partner_id == partner_id, PartnerPayout.status == "requested").limit(1))).scalar_one_or_none()

    html = env.get_template("partner_detail.html").render(
        p=partner, accounts=accounts, payouts=payouts, earnings=earnings, acc_map=acc_map, pending_request=pending_request,
        user=request.get("user")
    )
    return web.Response(text=html, content_type="text/html")


async def partner_block(request: web.Request):
    partner_id = int(request.match_info["id"])
    async with async_session() as session:
        p = await session.get(Partner, partner_id)
        if p:
            p.status = "blocked"
            await session.commit()
    raise web.HTTPFound(f"/partners/{partner_id}")


async def partner_unblock(request: web.Request):
    partner_id = int(request.match_info["id"])
    async with async_session() as session:
        p = await session.get(Partner, partner_id)
        if p:
            p.status = "active"
            await session.commit()
    raise web.HTTPFound(f"/partners/{partner_id}")


async def partner_payout_direct(request: web.Request):
    partner_id = int(request.match_info["id"])
    bot = request.app["bot"]
    async with async_session() as session:
        p = await session.get(Partner, partner_id)
        if not p: raise web.HTTPFound(f"/partners/{partner_id}")
        payout, error = await manual_payout(session, p)
        if error: raise web.HTTPFound(f"/partners/{partner_id}")
        notifications.push("💸 Выплата партнёру", f"{p.full_name} — {payout.amount:.0f} ₽", level="success", category="partner")
        await _notify_partner_tg(bot, p, f"💸 *Выплата выполнена*\n\nСумма: *{payout.amount:.0f} ₽*\n\nСпасибо за работу! Продолжай в том же духе 🤝")
    raise web.HTTPFound(f"/partners/{partner_id}")


async def partners_approvals(request: web.Request):
    async with async_session() as session:
        pending = (await session.execute(select(Account).where(Account.status == "pending_approval").order_by(Account.created_at))).scalars().all()
        items = []
        for acc in pending:
            partner = await session.get(Partner, acc.partner_id) if acc.partner_id else None
            rank_setting = (await session.execute(select(RankSetting).where(RankSetting.rank == acc.rank))).scalar_one_or_none()
            items.append({"account": acc, "partner": partner, "min_3h": rank_setting.min_price_3h if rank_setting else 0, "min_6h": rank_setting.min_price_6h if rank_setting else 0, "min_12h": rank_setting.min_price_12h if rank_setting else 0})

    html = env.get_template("partners_approvals.html").render(accounts=items, user=request.get("user"))
    return web.Response(text=html, content_type="text/html")


async def partner_approve(request: web.Request):
    acc_id = int(request.match_info["id"])
    bot = request.app["bot"]
    async with async_session() as session:
        acc = await session.get(Account, acc_id)
        if acc and acc.status == "pending_approval":
            acc.status = "free"
            acc.approved_at = datetime.utcnow()
            await session.commit()
            notifications.push("✅ Аккаунт одобрен", f"#{acc.id} · {acc.rank}", level="success", category="partner")
            if acc.partner_id:
                partner = await session.get(Partner, acc.partner_id)
                await _notify_partner_tg(bot, partner, f"✅ *Твой аккаунт одобрен!*\n\nАккаунт #{acc.id} · {acc.rank}\nТеперь он в магазине и доступен для аренды.")
    raise web.HTTPFound("/partners/approvals")


async def partner_reject(request: web.Request):
    acc_id = int(request.match_info["id"])
    data = await request.post()
    reason = (data.get("reason") or "Причина не указана").strip()
    bot = request.app["bot"]
    async with async_session() as session:
        acc = await session.get(Account, acc_id)
        if acc and acc.status == "pending_approval":
            acc.status = "rejected"
            acc.reject_reason = reason
            await session.commit()
            notifications.push("❌ Аккаунт отклонён", f"#{acc.id} · {acc.rank} — {reason}", level="danger", category="partner")
            if acc.partner_id:
                partner = await session.get(Partner, acc.partner_id)
                await _notify_partner_tg(bot, partner, f"❌ *Твой аккаунт отклонён*\n\nАккаунт #{acc.id} · {acc.rank}\n\n*Причина:* {reason}\n\nИсправь проблему и добавь аккаунт заново.")
    raise web.HTTPFound("/partners/approvals")


async def partners_passwords(request: web.Request):
    async with async_session() as session:
        pending = (await session.execute(select(Account).where(Account.status == "awaiting_approval").order_by(Account.password_changed_at))).scalars().all()
        items = []
        for acc in pending:
            partner = await session.get(Partner, acc.partner_id) if acc.partner_id else None
            items.append({"account": acc, "partner": partner})

    html = env.get_template("partners_passwords.html").render(accounts=items, user=request.get("user"))
    return web.Response(text=html, content_type="text/html")


async def partner_password_approve(request: web.Request):
    acc_id = int(request.match_info["id"])
    bot = request.app["bot"]
    async with async_session() as session:
        acc = await session.get(Account, acc_id)
        if acc and acc.status == "awaiting_approval":
            acc.status = "free"
            acc.password_changed_at = datetime.utcnow()
            acc.buyer_id = None
            acc.rental_hours = None
            acc.rented_until = None
            acc.reserved_at = None
            await session.commit()
            notifications.push("✅ Пароль принят", f"#{acc.id} — аккаунт снова в магазине", level="success", category="partner")
            if acc.partner_id:
                partner = await session.get(Partner, acc.partner_id)
                await _notify_partner_tg(bot, partner, f"✅ *Пароль принят*\n\nАккаунт #{acc.id} · {acc.rank}\nСнова в магазине, ждёт следующего арендатора.")
    raise web.HTTPFound("/partners/passwords")


async def partner_password_reject(request: web.Request):
    acc_id = int(request.match_info["id"])
    data = await request.post()
    reason = (data.get("reason") or "Пароль не работает").strip()
    bot = request.app["bot"]
    async with async_session() as session:
        acc = await session.get(Account, acc_id)
        if acc and acc.status == "awaiting_approval":
            acc.status = "awaiting_review"
            await session.commit()
            notifications.push("❌ Пароль отклонён", f"#{acc.id} · {acc.rank} — {reason}", level="danger", category="partner")
            if acc.partner_id:
                partner = await session.get(Partner, acc.partner_id)
                await _notify_partner_tg(bot, partner, f"❌ *Пароль не принят*\n\nАккаунт #{acc.id} · {acc.rank}\n\n*Причина:* {reason}\n\nСмени пароль правильно и отправь заново.")
    raise web.HTTPFound("/partners/passwords")


async def partners_payouts(request: web.Request):
    async with async_session() as session:
        payouts_raw = (await session.execute(select(PartnerPayout).where(PartnerPayout.status == "requested").order_by(PartnerPayout.requested_at))).scalars().all()
        items = []
        for po in payouts_raw:
            partner = await session.get(Partner, po.partner_id)
            items.append({"payout": po, "partner": partner})

    html = env.get_template("partners_payouts.html").render(payouts=items, user=request.get("user"))
    return web.Response(text=html, content_type="text/html")


async def partner_payout_pay(request: web.Request):
    po_id = int(request.match_info["id"])
    data = await request.post()
    note = (data.get("note") or "").strip()
    bot = request.app["bot"]
    async with async_session() as session:
        po = await session.get(PartnerPayout, po_id)
        if not po: raise web.HTTPFound("/partners/payouts")
        if note: po.note = note
        success = await approve_payout(session, po)
        if success:
            partner = await session.get(Partner, po.partner_id)
            await _notify_partner_tg(bot, partner, f"💸 *Выплата выполнена*\n\nСумма: *{po.amount:.0f} ₽*\n\nСпасибо за работу!")
            notifications.push("💸 Выплата партнёру", f"{partner.full_name if partner else '?'} — {po.amount:.0f} ₽", level="success", category="partner")
    raise web.HTTPFound("/partners/payouts")


async def partner_payout_reject(request: web.Request):
    po_id = int(request.match_info["id"])
    data = await request.post()
    reason = (data.get("reason") or "Отклонено").strip()
    bot = request.app["bot"]
    async with async_session() as session:
        po = await session.get(PartnerPayout, po_id)
        if not po: raise web.HTTPFound("/partners/payouts")
        success = await reject_payout(session, po, reason)
        if success:
            partner = await session.get(Partner, po.partner_id)
            await _notify_partner_tg(bot, partner, f"❌ *Запрос на выплату отклонён*\n\nСумма: {po.amount:.0f} ₽\n*Причина:* {reason}\n\nДеньги возвращены на баланс. Проверь реквизиты и запроси снова.")
            notifications.push("❌ Выплата отклонена", f"Партнёр #{po.partner_id} — {reason}", level="danger", category="partner")
    raise web.HTTPFound("/partners/payouts")


# ─── Создание приложения ───

def create_web_app(bot):
    app = web.Application(
        middlewares=[auth_middleware],
        client_max_size=20 * 1024**2,
    )
    app["bot"] = bot

    app.router.add_get("/login", login_page)
    app.router.add_post("/login", login_page)
    app.router.add_get("/logout", logout)
    app.router.add_get("/partner-auth", partner_auth)
    app.router.add_get("/partner-portal", partner_portal)

    app.router.add_get("/", dashboard)
    app.router.add_get("/accounts", accounts_list)
    app.router.add_get("/accounts/add", account_add_page)
    app.router.add_post("/accounts/add", account_add_page)
    app.router.add_get("/accounts/{id}", account_detail)
    app.router.add_get("/accounts/{id}/edit", account_edit_page)
    app.router.add_post("/accounts/{id}/edit", account_edit_page)
    app.router.add_post("/accounts/{id}/delete", account_delete)

    app.router.add_get("/customers", customers_list)
    app.router.add_get("/customers/{id}", customer_detail)
    app.router.add_post("/customers/{id}/ban", customer_ban)
    app.router.add_post("/customers/{id}/unban", customer_unban)

    app.router.add_get("/password-change", awaiting_list)
    app.router.add_post("/password-change/{id}/done", mark_password_changed)

    app.router.add_get("/export", export_page)
    app.router.add_get("/api/notifications", notifications_api)
    app.router.add_get("/notifications", notifications_page)

    app.router.add_get("/settings", settings_page)
    app.router.add_post("/settings", settings_page)

    app.router.add_get("/partners", partners_dashboard)
    app.router.add_get("/partners/list", partners_list)
    app.router.add_get("/partners/approvals", partners_approvals)
    app.router.add_post("/partners/approvals/{id}/approve", partner_approve)
    app.router.add_post("/partners/approvals/{id}/reject", partner_reject)
    app.router.add_get("/partners/passwords", partners_passwords)
    app.router.add_post("/partners/passwords/{id}/approve", partner_password_approve)
    app.router.add_post("/partners/passwords/{id}/reject", partner_password_reject)
    app.router.add_get("/partners/payouts", partners_payouts)
    app.router.add_post("/partners/payouts/{id}/pay", partner_payout_pay)
    app.router.add_post("/partners/payouts/{id}/reject", partner_payout_reject)
    app.router.add_get("/partners/{id}", partner_detail)
    app.router.add_post("/partners/{id}/block", partner_block)
    app.router.add_post("/partners/{id}/unblock", partner_unblock)
    app.router.add_post("/partners/{id}/payout", partner_payout_direct)

    app.router.add_static('/static', path='static')
    register_photo_route(app, bot)
    return app
