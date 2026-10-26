import logging
import json
import time
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
    Partner, PartnerPayout, PartnerEarning, Promocode,
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

env.filters["from_json"] = lambda s: json.loads(s) if s else {}
env.globals["timedelta"] = timedelta
env.globals["RESERVE_MINUTES"] = 15

serializer = URLSafeTimedSerializer(WEB_SECRET_KEY, salt="web-session")
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt_sha256", "bcrypt"], deprecated="auto"
)
SESSION_MAX_AGE = 60 * 60 * 24 * 7

ALL_PERMISSIONS = [
    "can_view_dashboard", "can_edit_accounts", "can_manage_partners",
    "can_check_passwords", "can_pay_partners", "can_ban_customers", "can_edit_settings"
]

_nav_cache = {}


async def get_nav_counts(session, user):
    if not user:
        return {"approvals": 0, "passwords": 0, "payouts": 0}

    cache_key = str(user.get("role")) + str(user.get("id")) + str(user.get("perms"))
    now = time.time()
    if cache_key in _nav_cache and _nav_cache[cache_key]["expires"] > now:
        return _nav_cache[cache_key]["data"]

    counts = {"approvals": 0, "passwords": 0, "payouts": 0}
    perms = user.get("perms", {})
    is_owner = user.get("all_perms", False)

    if is_owner or perms.get("can_manage_partners"):
        counts["approvals"] = (await session.execute(
            select(func.count(Account.id)).where(Account.status == "pending_approval")
        )).scalar() or 0

    if is_owner or perms.get("can_check_passwords"):
        counts["passwords"] = (await session.execute(
            select(func.count(Account.id)).where(
                Account.status.in_(["awaiting_approval", "awaiting_password_change"])
            )
        )).scalar() or 0

    if is_owner or perms.get("can_pay_partners"):
        counts["payouts"] = (await session.execute(
            select(func.count(PartnerPayout.id)).where(PartnerPayout.status == "requested")
        )).scalar() or 0

    _nav_cache[cache_key] = {"data": counts, "expires": now + 30}
    return counts


async def render_admin(request, template_name, **kwargs):
    async with async_session() as session:
        user = request.get("user")
        nav_counts = await get_nav_counts(session, user)
    kwargs["nav_counts"] = nav_counts
    kwargs["user"] = user
    return env.get_template(template_name).render(**kwargs)


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
    public_paths = (
        "/login", "/api/photo/", "/privacy", "/consent", "/terms",
        "/partner-auth", "/static"
    )
    if any(request.path.startswith(p) for p in public_paths):
        return await handler(request)

    data = _get_token_data(request)
    if not data:
        raise web.HTTPFound("/login")

    if data.get("type") == "partner":
        if not request.path.startswith("/partner-portal"):
            raise web.HTTPForbidden(text="Доступ только в личный кабинет.")
        request["user"] = {"role": "partner", "partner_id": data["id"]}
        return await handler(request)

    if data.get("type") == "owner":
        request["user"] = {"role": "owner", "all_perms": True, "perms": {}}
    elif data.get("type") == "manager":
        async with async_session() as session:
            mgr = await session.get(Manager, data["id"])
            if not mgr:
                raise web.HTTPFound("/login")
            perms = json.loads(mgr.permissions) if mgr.permissions else {}
            request["user"] = {"role": "manager", "id": mgr.id, "perms": perms, "all_perms": False}
    else:
        raise web.HTTPFound("/login")

    user = request["user"]
    if not user["all_perms"]:
        perms = user["perms"]
        if request.path == "/" and not perms.get("can_view_dashboard"):
            raise web.HTTPForbidden()
        if request.path.startswith("/accounts") and not perms.get("can_edit_accounts"):
            raise web.HTTPForbidden()
        if request.path.startswith("/customers") and not perms.get("can_ban_customers"):
            raise web.HTTPForbidden()
        if request.path.startswith("/partners") and not perms.get("can_manage_partners"):
            raise web.HTTPForbidden()
        if request.path.startswith("/partners/passwords") and not perms.get("can_check_passwords"):
            raise web.HTTPForbidden()
        if request.path.startswith("/partners/payouts") and not perms.get("can_pay_partners"):
            raise web.HTTPForbidden()
        if request.path.startswith("/settings") and not perms.get("can_edit_settings"):
            raise web.HTTPForbidden()

    return await handler(request)


async def login_page(request: web.Request):
    error = None
    if request.method == "POST":
        data = await request.post()
        login = data.get("login", "").strip()
        pwd = data.get("password", "")

        if not login and pwd == WEB_ADMIN_PASSWORD:
            token = serializer.dumps({"type": "owner"})
            resp = web.HTTPFound("/")
            resp.set_cookie("session", token, max_age=SESSION_MAX_AGE, httponly=True)
            raise resp

        if login:
            async with async_session() as session:
                mgr = (await session.execute(
                    select(Manager).where(Manager.login == login)
                )).scalar_one_or_none()
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
        data = serializer.loads(token, max_age=900)
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
        accounts = (await session.execute(
            select(Account).where(Account.partner_id == partner_id)
        )).scalars().all()
        payouts = (await session.execute(
            select(PartnerPayout)
            .where(PartnerPayout.partner_id == partner_id)
            .order_by(desc(PartnerPayout.requested_at))
            .limit(10)
        )).scalars().all()
        rentals = (await session.execute(
            select(func.count(RentalHistory.id)).join(Account)
            .where(Account.partner_id == partner_id)
        )).scalar() or 0

    html = env.get_template("partner_portal.html").render(
        p=partner, accounts=accounts, payouts=payouts, rentals=rentals
    )
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

    html = await render_admin(
        request, "dashboard.html",
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
    status_filter = request.query.get("status", "").strip()
    q = request.query.get("q", "").strip().lower()

    async with async_session() as session:
        query = select(Account).order_by(Account.rank, Account.id)
        if rank:
            query = query.where(Account.rank == rank)
        if owner_filter == "me":
            query = query.where(Account.partner_id.is_(None))
        elif owner_filter == "partner":
            query = query.where(Account.partner_id.isnot(None))
        if status_filter:
            query = query.where(Account.status == status_filter)

        accounts = (await session.execute(query)).scalars().all()
        if q:
            accounts = [
                a for a in accounts
                if q in str(a.id).lower() or q in a.login.lower()
                or q in a.rank.lower()
                or (a.riot_id and q in a.riot_id.lower())
            ]

        ranks = (await session.execute(
            select(Account.rank).distinct().order_by(Account.rank)
        )).scalars().all()

    html = await render_admin(
        request, "accounts.html",
        accounts=accounts, ranks=ranks, current_rank=rank,
        owner_filter=owner_filter, current_status=status_filter, q=q,
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

    html = await render_admin(
        request, "account_detail.html",
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
                photo_id = await _upload_photo_to_telegram(
                    bot, pf.file.read(), pf.filename
                )
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
            notifications.push(
                "Добавлен аккаунт", f"#{acc_id} · {acc.rank}", level="success"
            )
            raise web.HTTPFound(f"/accounts/{acc_id}")

    html = await render_admin(request, "account_add.html", error=error)
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
                        new_id = await _upload_photo_to_telegram(
                            bot, pf.file.read(), pf.filename
                        )
                        if new_id:
                            account.photo_id = new_id
                    except Exception as e:
                        logging.warning(f"photo edit: {e}")

            try:
                account.login = post["login"].strip()
                account.password = post["password"].strip()
                account.email = (post.get("email") or "").strip() or None
                account.email_password = (
                    post.get("email_password") or ""
                ).strip() or None
                account.riot_id = (post.get("riot_id") or "").strip() or None
                account.rank = post["rank"].strip()
                account.tier = post.get("tier", "standard")
                account.price_3h = float(post["price_3h"])
                account.price_6h = float(post["price_6h"])
                account.price_12h = float(post["price_12h"])
                await session.commit()
                notifications.push(
                    "Аккаунт обновлён", f"#{acc_id}", level="success"
                )
                raise web.HTTPFound(f"/accounts/{acc_id}")
            except (KeyError, ValueError) as e:
                error = f"Ошибка: {e}"

    html = await render_admin(
        request, "account_edit.html", a=account, error=error
    )
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

    html = await render_admin(
        request, "password_change.html",
        my_accounts=my_accounts, partner_accounts=partner_accounts,
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
            notifications.push(
                "Пароль сменён", f"#{acc_id} — снова свободен", level="success"
            )
    raise web.HTTPFound("/password-change")


# ─── Покупатели ───

async def customers_list(request: web.Request):
    q = request.query.get("q", "").strip().lower()

    async with async_session() as session:
        buyer_ids = (await session.execute(
            select(RentalHistory.buyer_id).distinct()
            .where(RentalHistory.buyer_id.isnot(None))
        )).scalars().all()

        if buyer_ids:
            existing = (await session.execute(
                select(Customer.telegram_id)
                .where(Customer.telegram_id.in_(buyer_ids))
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
            r[0]: {
                "spent": round(r[1] or 0, 2),
                "hours": int(r[2] or 0),
                "count": int(r[3] or 0),
            }
            for r in stats_rows
        }

        result = []
        for c in custs:
            st = stats.get(c.telegram_id, {"spent": 0, "hours": 0, "count": 0})
            if q and not (
                q in str(c.telegram_id)
                or q in (c.first_name or "").lower()
                or q in (c.username or "").lower()
            ):
                continue
            result.append({"customer": c, **st})
        result.sort(key=lambda x: x["spent"], reverse=True)

    html = await render_admin(
        request, "customers.html", customers=result, q=q
    )
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
        start_date = (datetime.utcnow() - timedelta(days=29)).date()
        for _ in range(start_date.weekday()):
            days.append({"date": "", "count": -1})
        for i in range(29, -1, -1):
            day = (datetime.utcnow() - timedelta(days=i)).date()
            days.append({
                "date": day.strftime("%d.%m.%Y"),
                "count": activity_map.get(day.isoformat(), 0),
            })

        history = (await session.execute(
            select(RentalHistory, Account.rank)
            .join(Account, Account.id == RentalHistory.account_id)
            .where(RentalHistory.buyer_id == customer_id)
            .order_by(desc(RentalHistory.started_at))
            .limit(50)
        )).all()

    html = await render_admin(
        request, "customer_detail.html",
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
            notifications.push(
                "✅ Покупатель разбанен", f"ID {customer_id}", level="success"
            )
    raise web.HTTPFound(f"/customers/{customer_id}")


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
    html = await render_admin(request, "export.html")
    return web.Response(text=html, content_type="text/html")


# ─── API уведомлений ───

async def notifications_api(request: web.Request):
    since_id = int(request.query.get("since", "0"))
    return web.json_response(notifications.since(since_id))


async def notifications_page(request: web.Request):
    cat = request.query.get("cat", "all")
    events = notifications.get_all(category=cat)
    html = await render_admin(
        request, "notifications.html", events=events, cat=cat
    )
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
                            min_price_3h=p3,
                            min_price_6h=p6,
                            min_price_12h=p12,
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

            elif action == "add_manager":
                try:
                    login = post["login"].strip()
                    pwd = post["password"].strip()
                    if len(login) < 3 or len(pwd) < 6:
                        raise ValueError("Логин от 3 символов, пароль от 6.")

                    existing = (await session.execute(
                        select(Manager).where(Manager.login == login)
                    )).scalar_one_or_none()
                    if existing:
                        raise ValueError("Такой логин уже существует")

                    perms = {
                        p: True for p in ALL_PERMISSIONS if post.get(p) == "on"
                    }
                    session.add(Manager(
                        login=login,
                        password_hash=pwd_context.hash(pwd),
                        permissions=json.dumps(perms),
                    ))
                    await session.commit()
                    success = f"Менеджер {login} создан"
                except (ValueError, KeyError) as e:
                    error = f"Ошибка: {e}"

            elif action == "delete_manager":
                try:
                    mid = int(post["manager_id"])
                    mgr = await session.get(Manager, mid)
                    if mgr:
                        await session.delete(mgr)
                        await session.commit()
                        success = "Менеджер удалён"
                except (ValueError, KeyError) as e:
                    error = f"Ошибка: {e}"

        commission_str = await get_setting(session, "partner_commission", "10")
        try:
            commission_float = float(commission_str)
        except (TypeError, ValueError):
            commission_float = 10.0
        partner_share = 100.0 - commission_float

        ranks = (await session.execute(
            select(RankSetting).order_by(RankSetting.rank)
        )).scalars().all()
        managers = (await session.execute(
            select(Manager).order_by(Manager.id)
        )).scalars().all()
        promocodes = (await session.execute(
            select(Promocode).order_by(desc(Promocode.created_at))
        )).scalars().all()

    html = await render_admin(
        request, "settings.html",
        commission=commission_float,
        partner_share=round(partner_share, 1),
        ranks=ranks, managers=managers, promocodes=promocodes,
        error=error, success=success,
    )
    return web.Response(text=html, content_type="text/html")


# ─── Промокоды ───

async def promo_add(request: web.Request):
    data = await request.post()
    error = None

    async with async_session() as session:
        try:
            code = data.get("code", "").strip().upper()
            if not code or len(code) < 2:
                raise ValueError("Код должен быть минимум 2 символа")

            existing = (await session.execute(
                select(Promocode).where(Promocode.code == code)
            )).scalar_one_or_none()
            if existing:
                raise ValueError(f"Промокод {code} уже существует")

            discount_type = data.get("discount_type", "percent")
            if discount_type not in ("percent", "fixed"):
                raise ValueError("Неверный тип скидки")

            discount_value = float(data.get("discount_value", "0"))
            if discount_value <= 0:
                raise ValueError("Размер скидки должен быть > 0")
            if discount_type == "percent" and discount_value > 100:
                raise ValueError("Процент не может быть больше 100")

            condition_type = data.get("condition_type", "any_order")
            if condition_type not in ("first_order", "any_order", "rental_12h"):
                raise ValueError("Неверное условие")

            max_uses = int(data.get("max_uses", "0"))
            if max_uses < 0:
                raise ValueError("Лимит не может быть отрицательным")

            valid_until_str = data.get("valid_until", "")
            try:
                valid_until = datetime.fromisoformat(valid_until_str)
            except ValueError:
                raise ValueError("Неверная дата окончания")

            if valid_until < datetime.utcnow():
                raise ValueError("Дата окончания должна быть в будущем")

            promo = Promocode(
                code=code,
                discount_type=discount_type,
                discount_value=discount_value,
                condition_type=condition_type,
                max_uses=max_uses,
                valid_until=valid_until,
                active=True,
            )
            session.add(promo)
            await session.commit()
            notifications.push(
                "🎟 Создан промокод",
                f"{code} · {discount_value}"
                f"{'%' if discount_type == 'percent' else '₽'}",
                level="success",
            )
        except (ValueError, KeyError) as e:
            error = str(e)

    if error:
        raise web.HTTPFound(f"/settings?promo_error={error}")
    raise web.HTTPFound("/settings?promo_success=1")


async def promo_delete(request: web.Request):
    promo_id = int(request.match_info["id"])
    async with async_session() as session:
        promo = await session.get(Promocode, promo_id)
        if promo:
            await session.delete(promo)
            await session.commit()
    raise web.HTTPFound("/settings")


async def promo_toggle(request: web.Request):
    promo_id = int(request.match_info["id"])
    async with async_session() as session:
        promo = await session.get(Promocode, promo_id)
        if promo:
            promo.active = not promo.active
            await session.commit()
    raise web.HTTPFound("/settings")


# ═══════════════════════════════════════════════════════════════
# ПАРТНЁРЫ
# ═══════════════════════════════════════════════════════════════

async def partners_dashboard(request: web.Request):
    async with async_session() as session:
        partners_active = (await session.execute(
            select(func.count(Partner.id)).where(Partner.status == "active")
        )).scalar() or 0

        accounts_total = (await session.execute(
            select(func.count(Account.id)).where(Account.partner_id.isnot(None))
        )).scalar() or 0

        pending_moderation = (await session.execute(
            select(func.count(Account.id)).where(
                Account.status.in_(["pending_approval", "awaiting_approval"])
            )
        )).scalar() or 0

        pending_payouts = (await session.execute(
            select(func.count(PartnerPayout.id)).where(
                PartnerPayout.status == "requested"
            )
        )).scalar() or 0

        pending_payout_amount = (await session.execute(
            select(func.coalesce(func.sum(PartnerPayout.amount), 0)).where(
                PartnerPayout.status == "requested"
            )
        )).scalar() or 0

        cutoff = datetime.utcnow() - timedelta(days=30)
        revenue_30d = (await session.execute(
            select(func.coalesce(func.sum(PartnerEarning.amount), 0)).where(
                PartnerEarning.created_at >= cutoff
            )
        )).scalar() or 0

        total_balance = (await session.execute(
            select(func.coalesce(func.sum(Partner.balance), 0))
        )).scalar() or 0
        total_frozen = (await session.execute(
            select(func.coalesce(func.sum(Partner.frozen_balance), 0))
        )).scalar() or 0
        total_paid = (await session.execute(
            select(func.coalesce(func.sum(Partner.total_paid), 0))
        )).scalar() or 0

        recent_events_raw = notifications.get_all(category="partner")[:10]
        recent_events = [
            {
                "partner_id": 0,
                "partner_name": "—",
                "event": e["title"] + (" — " + e["text"] if e["text"] else ""),
                "ts": e["ts"],
            }
            for e in recent_events_raw
        ]

    html = await render_admin(
        request, "partners_dashboard.html",
        partners_active=partners_active,
        accounts_total=accounts_total,
        pending_moderation=pending_moderation,
        pending_payouts=pending_payouts,
        pending_payout_amount=round(pending_payout_amount),
        revenue_30d=round(revenue_30d),
        total_balance=round(total_balance),
        total_frozen=round(total_frozen),
        total_paid=round(total_paid),
        recent_events=recent_events,
    )
    return web.Response(text=html, content_type="text/html")


async def partners_list(request: web.Request):
    q = request.query.get("q", "").strip()
    status_filter = request.query.get("status", "").strip()

    async with async_session() as session:
        query = select(Partner)
        if q:
            query = query.where(or_(
                Partner.full_name.ilike(f"%{q}%"),
                Partner.username.ilike(f"%{q}%"),
            ))
        if status_filter:
            query = query.where(Partner.status == status_filter)
        query = query.order_by(Partner.id.desc())

        partners_raw = (await session.execute(query)).scalars().all()

        partners_data = []
        for p in partners_raw:
            cnt = (await session.execute(
                select(func.count(Account.id)).where(Account.partner_id == p.id)
            )).scalar() or 0
            partners_data.append({
                "id": p.id,
                "full_name": p.full_name,
                "username": p.username,
                "telegram_id": p.telegram_id,
                "avatar_id": p.avatar_id,
                "balance": round(p.balance or 0),
                "total_earned": round(p.total_earned or 0),
                "status": p.status,
                "accounts_count": cnt,
            })

    html = await render_admin(
        request, "partners_list.html",
        partners=partners_data, q=q, status_filter=status_filter,
    )
    return web.Response(text=html, content_type="text/html")


async def partner_detail(request: web.Request):
    partner_id = int(request.match_info["id"])
    async with async_session() as session:
        partner = await session.get(Partner, partner_id)
        if not partner:
            raise web.HTTPNotFound()

        accounts = (await session.execute(
            select(Account).where(Account.partner_id == partner_id)
            .order_by(Account.id.desc())
        )).scalars().all()

        payouts = (await session.execute(
            select(PartnerPayout)
            .where(PartnerPayout.partner_id == partner_id)
            .order_by(desc(PartnerPayout.requested_at))
            .limit(20)
        )).scalars().all()

        earnings = (await session.execute(
            select(PartnerEarning)
            .where(PartnerEarning.partner_id == partner_id)
            .order_by(desc(PartnerEarning.created_at))
            .limit(30)
        )).scalars().all()

        acc_map = {a.id: a for a in accounts}

        pending_request = (await session.execute(
            select(PartnerPayout).where(
                PartnerPayout.partner_id == partner_id,
                PartnerPayout.status == "requested",
            ).limit(1)
        )).scalar_one_or_none()

    html = await render_admin(
        request, "partner_detail.html",
        p=partner, accounts=accounts, payouts=payouts,
        earnings=earnings, acc_map=acc_map,
        pending_request=pending_request,
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
        if not p:
            raise web.HTTPFound(f"/partners/{partner_id}")
        payout, error = await manual_payout(session, p)
        if error:
            raise web.HTTPFound(f"/partners/{partner_id}")
        notifications.push(
            "💸 Выплата партнёру",
            f"{p.full_name} — {payout.amount:.0f} ₽",
            level="success", category="partner",
        )
        await _notify_partner_tg(
            bot, p,
            f"💸 *Выплата выполнена*\n\n"
            f"Сумма: *{payout.amount:.0f} ₽*\n\n"
            f"Спасибо за работу! Продолжай в том же духе 🤝"
        )
    raise web.HTTPFound(f"/partners/{partner_id}")


async def partners_approvals(request: web.Request):
    async with async_session() as session:
        pending = (await session.execute(
            select(Account).where(Account.status == "pending_approval")
            .order_by(Account.created_at)
        )).scalars().all()

        items = []
        for acc in pending:
            partner = await session.get(Partner, acc.partner_id) if acc.partner_id else None
            rank_setting = (await session.execute(
                select(RankSetting).where(RankSetting.rank == acc.rank)
            )).scalar_one_or_none()
            items.append({
                "account": acc,
                "partner": partner,
                "min_3h": rank_setting.min_price_3h if rank_setting else 0,
                "min_6h": rank_setting.min_price_6h if rank_setting else 0,
                "min_12h": rank_setting.min_price_12h if rank_setting else 0,
            })

    html = await render_admin(
        request, "partners_approvals.html", accounts=items
    )
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
            notifications.push(
                "✅ Аккаунт одобрен", f"#{acc.id} · {acc.rank}",
                level="success", category="partner",
            )
            if acc.partner_id:
                partner = await session.get(Partner, acc.partner_id)
                await _notify_partner_tg(
                    bot, partner,
                    f"✅ *Твой аккаунт одобрен!*\n\n"
                    f"Аккаунт #{acc.id} · {acc.rank}\n"
                    f"Теперь он в магазине и доступен для аренды."
                )
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
            notifications.push(
                "❌ Аккаунт отклонён",
                f"#{acc.id} · {acc.rank} — {reason}",
                level="danger", category="partner",
            )
            if acc.partner_id:
                partner = await session.get(Partner, acc.partner_id)
                await _notify_partner_tg(
                    bot, partner,
                    f"❌ *Твой аккаунт отклонён*\n\n"
                    f"Аккаунт #{acc.id} · {acc.rank}\n\n"
                    f"*Причина:* {reason}\n\n"
                    f"Исправь проблему и добавь аккаунт заново."
                )
    raise web.HTTPFound("/partners/approvals")


async def partners_passwords(request: web.Request):
    async with async_session() as session:
        pending = (await session.execute(
            select(Account).where(Account.status == "awaiting_approval")
            .order_by(Account.password_changed_at)
        )).scalars().all()

        items = []
        for acc in pending:
            partner = await session.get(Partner, acc.partner_id) if acc.partner_id else None
            items.append({"account": acc, "partner": partner})

    html = await render_admin(
        request, "partners_passwords.html", accounts=items
    )
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
            notifications.push(
                "✅ Пароль принят",
                f"#{acc.id} — аккаунт снова в магазине",
                level="success", category="partner",
            )
            if acc.partner_id:
                partner = await session.get(Partner, acc.partner_id)
                await _notify_partner_tg(
                    bot, partner,
                    f"✅ *Пароль принят*\n\n"
                    f"Аккаунт #{acc.id} · {acc.rank}\n"
                    f"Снова в магазине, ждёт следующего арендатора."
                )
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
            notifications.push(
                "❌ Пароль отклонён",
                f"#{acc.id} · {acc.rank} — {reason}",
                level="danger", category="partner",
            )
            if acc.partner_id:
                partner = await session.get(Partner, acc.partner_id)
                await _notify_partner_tg(
                    bot, partner,
                    f"❌ *Пароль не принят*\n\n"
                    f"Аккаунт #{acc.id} · {acc.rank}\n\n"
                    f"*Причина:* {reason}\n\n"
                    f"Смени пароль правильно и отправь заново."
                )
    raise web.HTTPFound("/partners/passwords")


async def partners_payouts(request: web.Request):
    async with async_session() as session:
        payouts_raw = (await session.execute(
            select(PartnerPayout)
            .where(PartnerPayout.status == "requested")
            .order_by(PartnerPayout.requested_at)
        )).scalars().all()

        items = []
        for po in payouts_raw:
            partner = await session.get(Partner, po.partner_id)
            items.append({"payout": po, "partner": partner})

    html = await render_admin(
        request, "partners_payouts.html", payouts=items
    )
    return web.Response(text=html, content_type="text/html")


async def partner_payout_pay(request: web.Request):
    po_id = int(request.match_info["id"])
    data = await request.post()
    note = (data.get("note") or "").strip()
    bot = request.app["bot"]
    async with async_session() as session:
        po = await session.get(PartnerPayout, po_id)
        if not po:
            raise web.HTTPFound("/partners/payouts")

        if note:
            po.note = note

        success = await approve_payout(session, po)

        if success:
            partner = await session.get(Partner, po.partner_id)
            await _notify_partner_tg(
                bot, partner,
                f"💸 *Выплата выполнена*\n\n"
                f"Сумма: *{po.amount:.0f} ₽*\n\n"
                f"Спасибо за работу!"
            )
            notifications.push(
                "💸 Выплата партнёру",
                f"{partner.full_name if partner else '?'} — {po.amount:.0f} ₽",
                level="success", category="partner",
            )
    raise web.HTTPFound("/partners/payouts")


async def partner_payout_reject(request: web.Request):
    po_id = int(request.match_info["id"])
    data = await request.post()
    reason = (data.get("reason") or "Отклонено").strip()
    bot = request.app["bot"]
    async with async_session() as session:
        po = await session.get(PartnerPayout, po_id)
        if not po:
            raise web.HTTPFound("/partners/payouts")

        success = await reject_payout(session, po, reason)

        if success:
            partner = await session.get(Partner, po.partner_id)
            await _notify_partner_tg(
                bot, partner,
                f"❌ *Запрос на выплату отклонён*\n\n"
                f"Сумма: {po.amount:.0f} ₽\n"
                f"*Причина:* {reason}\n\n"
                f"Деньги возвращены на баланс. Проверь реквизиты и запроси снова."
            )
            notifications.push(
                "❌ Выплата отклонена",
                f"Партнёр #{po.partner_id} — {reason}",
                level="danger", category="partner",
            )
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

    app.router.add_post("/settings/promo/add", promo_add)
    app.router.add_post("/settings/promo/delete/{id}", promo_delete)
    app.router.add_post("/settings/promo/toggle/{id}", promo_toggle)

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

    app.router.add_static("/static", path="static")
    register_photo_route(app, bot)
    return app
