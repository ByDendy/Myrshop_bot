import logging
from datetime import datetime, timedelta
from pathlib import Path

from aiohttp import web
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy import select, func, desc
from jinja2 import Environment, FileSystemLoader, select_autoescape
from aiogram.types import BufferedInputFile

from config import WEB_ADMIN_PASSWORD, WEB_SECRET_KEY, ADMIN_IDS
from database.models import Account, RentalHistory
from database.session import async_session
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


# ─── Загрузка фото в Telegram ───

async def _upload_photo_to_telegram(bot, raw: bytes, filename: str) -> str | None:
    if not ADMIN_IDS:
        logging.warning("photo upload: ADMIN_IDS пуст, некуда заливать")
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
        logging.warning(f"photo upload: ошибка {e}")
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
    async with async_session() as session:
        q = select(Account).order_by(Account.rank, Account.id)
        if rank:
            q = q.where(Account.rank == rank)
        accounts = (await session.execute(q)).scalars().all()
        ranks = (await session.execute(
            select(Account.rank).distinct().order_by(Account.rank)
        )).scalars().all()

    html = env.get_template("accounts.html").render(
        accounts=accounts, ranks=ranks, current_rank=rank,
        timedelta=timedelta,
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

    html = env.get_template("account_detail.html").render(
        a=account, period=period,
        rentals=stats[0], hours=stats[1], revenue=round(stats[2], 2),
        history=history,
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
                account.email_password = (post.get("email_password") or "").strip() or None
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
        accounts = (await session.execute(
            select(Account).where(Account.status == "awaiting_password_change")
        )).scalars().all()
    html = env.get_template("password_change.html").render(accounts=accounts)
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
    events = notifications.get_all()
    html = env.get_template("notifications.html").render(events=events)
    return web.Response(text=html, content_type="text/html")


# ─── Создание приложения ───

def create_web_app(bot):
    app = web.Application(middlewares=[auth_middleware])
    app["bot"] = bot

    app.router.add_get("/login", login_page)
    app.router.add_post("/login", login_page)
    app.router.add_get("/logout", logout)

    app.router.add_get("/", dashboard)
    app.router.add_get("/accounts", accounts_list)
    app.router.add_get("/accounts/add", account_add_page)
    app.router.add_post("/accounts/add", account_add_page)
    app.router.add_get("/accounts/{id}", account_detail)
    app.router.add_get("/accounts/{id}/edit", account_edit_page)
    app.router.add_post("/accounts/{id}/edit", account_edit_page)
    app.router.add_post("/accounts/{id}/delete", account_delete)

    app.router.add_get("/password-change", awaiting_list)
    app.router.add_post("/password-change/{id}/done", mark_password_changed)

    app.router.add_get("/export", export_page)
    app.router.add_get("/api/notifications", notifications_api)
    app.router.add_get("/notifications", notifications_page)

    register_photo_route(app, bot)
    return app
