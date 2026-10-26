<div align="center">

# 🎮 VARendy — Valorant Account Rental

**Telegram-бот + веб-панель для аренды аккаунтов Valorant**
Автоматизация оплаты, выдачи и учёта аренды через **FunPay** и **CryptoBot**

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0?style=flat-square&logo=telegram&logoColor=white)](https://docs.aiogram.dev/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

[🇷🇺 Русский](#-русский) · [🇬🇧 English](#-english)

</div>

---

## 🇷🇺 Русский

### 📖 О проекте

**VARendy** — это полностью автоматизированная система аренды игровых аккаунтов **Valorant** с двумя интерфейсами:

- 🤖 **Telegram-бот** — для покупателей: выбор ранга, срока аренды (3/6/12 часов), способа оплаты.
- 🖥 **Веб-панель** — для администратора: управление аккаунтами, статистика продаж, уведомления в реальном времени.

Система принимает оплату через **FunPay** и **CryptoBot**, автоматически выдаёт данные аккаунта покупателю и возвращает аккаунт в пул после истечения аренды.

---

### ✨ Возможности

#### Для покупателя (Telegram)
- 🛒 Магазин с фильтрацией по рангу (Iron → Radiant)
- ⏱ Аренда на 3, 6 или 12 часов
- 💳 Оплата через **FunPay** или **CryptoBot**
- 📸 Фото аккаунта, описание, характеристики
- 🎁 Автоматическая выдача логина и пароля после оплаты
- 🛟 Поддержка 24/7 через отдельную кнопку

#### Для администратора (веб-панель)
- 📊 Дашборд со статистикой: выручка, активные аренды, общее время
- ➕ Добавление аккаунтов поштучно (с загрузкой фото)
- 📥 Массовая загрузка (формат `login;;password;;rank;;p3,p6,p12`)
- ✏️ Редактирование любых полей аккаунта
- 📤 Экспорт всех аккаунтов в `.txt`
- 🔔 Уведомления в реальном времени (новая аренда, окончание аренды)
- 🔑 Раздел «Требуют смены пароля» с быстрым сбросом
- 💳 Управление способами оплаты (вкл/выкл)

#### Для администратора (Telegram)
- `/admin` — панель управления
- Добавление, удаление, список аккаунтов
- Управление способами оплаты и шаблоном описания
- Уведомления о каждой покупке

---

### 🏗 Архитектура
┌─────────────┐ ┌──────────────┐ ┌─────────────┐
│ Telegram │◄────►│ aiohttp │◄────►│ SQLite / │
│ (aiogram) │ │ Web Server │ │ PostgreSQL │
└─────────────┘ └──────────────┘ └─────────────┘
│ │ │
│ │ │
▼ ▼ ▼
┌─────────────┐ ┌──────────────┐ ┌─────────────┐
│ FunPay │ │ CryptoBot │ │ Rental │
│ Watcher │ │ Checker │ │ Checkers │
└─────────────┘ └──────────────┘ └─────────────┘

text

Один процесс запускает и бота (polling), и веб-сервер (на `PORT`). Фоновые задачи:
- `rental_checker` — освобождает аккаунты после аренды
- `payment_checker` — проверяет статус счетов CryptoBot
- `reservation_checker` — снимает просроченные брони (15 мин)
- `funpay_watcher` — слушает оплаты FunPay
- `lot_manager` — автосоздание/закрытие лотов на FunPay

---

### 🛠 Технологии

| Компонент | Стек |
|-----------|------|
| Telegram-бот | `aiogram 3.x` |
| Веб-сервер | `aiohttp` + `Jinja2` |
| База данных | `SQLAlchemy 2.0` (async) · SQLite / PostgreSQL |
| FunPay API | `aioFunPayAPI` |
| CryptoBot API | `aiohttp` + Crypto Pay API |
| Авторизация веб | `itsdangerous` (подписанные cookie) |
| Стилизация | Tailwind CSS (CDN) |

---

### 🚀 Установка

#### 1. Клонирование репозитория

```bash
git clone https://github.com/ByDendy/VARendy.git
cd VARendy
```
2. Виртуальное окружение
bash
python -m venv venv
source venv/bin/activate      # Linux/macOS
venv\Scripts\activate         # Windows
3. Зависимости
bash
pip install -r requirements.txt
4. Переменные окружения
Создайте файл .env в корне проекта:

env
# Telegram
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxyz
ADMIN_IDS=8792910093
SUPPORT_USERNAME=@varendy_support

# FunPay
FUNPAY_GOLDEN_KEY=your_golden_key_here
FUNPAY_USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
FUNPAY_CATEGORY_ID=1234
FUNPAY_AUTO_LOTS_ENABLED=true

# CryptoBot
CRYPTOBOT_TOKEN=12345:AAxxxxxxxxxxxxxxxxxxxxxxx

# Web-панель
WEB_ADMIN_PASSWORD=strong_password_here
WEB_SECRET_KEY=random_32_plus_characters_string_here

# База данных (опционально, по умолчанию SQLite)
DATABASE_URL=sqlite+aiosqlite:///valoshop.db
5. Запуск
bash
python bot.py
После старта:

Бот начнёт polling в Telegram

Веб-панель поднимется на http://localhost:8080

📂 Структура проекта
text
VARendy/
├── bot.py                    # точка входа
├── config.py                 # переменные окружения
├── requirements.txt
├── database/
│   ├── models.py             # Account, RentalHistory, Lot, ...
│   └── session.py            # async engine
├── handlers/                 # Telegram-обработчики
│   ├── start.py              # /start, поддержка
│   ├── buyer.py              # магазин, оплата
│   ├── admin.py              # админ-панель
│   ├── rental_checker.py     # освобождение после аренды
│   ├── payment_checker.py    # проверка CryptoBot
│   ├── reservation_checker.py
│   ├── funpay_watcher.py     # автовыдача FunPay
│   └── lot_manager.py        # автосоздание лотов
├── services/
│   ├── funpay_service.py
│   ├── cryptobot_service.py
│   ├── settings_service.py
│   └── notifications.py
└── web/
    ├── server.py             # aiohttp-приложение
    ├── notifications.py      # SSE-очередь
    ├── photo_proxy.py        # прокси фото из Telegram
    └── templates/            # Jinja2-шаблоны
        ├── base.html
        ├── login.html
        ├── dashboard.html
        ├── accounts.html
        ├── account_add.html
        ├── account_detail.html
        ├── account_edit.html
        ├── password_change.html
        └── export.html
⚙️ Как это работает
Жизненный цикл аккаунта
text
   ┌──────┐  бронь 15 мин   ┌──────────┐  оплата  ┌────────┐
   │ free │ ──────────────► │ reserved │ ───────► │ rented │
   └──────┘                 └──────────┘          └────────┘
      ▲                          │                    │
      │      не оплатил          │                    │ аренда истекла
      └──────────────────────────┘                    ▼
      │                                    ┌───────────────────────┐
      │          сменил пароль             │ awaiting_password_    │
      └────────────────────────────────────┤ change                │
                                           └───────────────────────┘
Автовыдача
Покупатель жмёт «Купить» → аккаунт reserved на 15 минут

Создаётся счёт (CryptoBot) или ссылка на лот (FunPay)

Фоновые payment_checker / funpay_watcher слушают оплату

При оплате → аккаунт rented, покупателю уходит логин/пароль

По истечении срока → awaiting_password_change, админ получает уведомление

Админ меняет пароль в веб-панели → аккаунт снова free

🌐 Деплой
Railway
Запушьте репозиторий на GitHub

Создайте новый проект на Railway

Подключите GitHub-репозиторий

Добавьте все переменные из .env в Variables

Railway автоматически определит Python и запустит python bot.py

Откройте публичный домен → /login → войти в веб-панель

⚠️ Важно: Railway не хранит SQLite между рестартами без Volume. Используйте либо PostgreSQL-сервис (Railway даёт DATABASE_URL автоматически), либо подключите Volume с mount path = /data и DATABASE_URL = sqlite+aiosqlite:////data/valoshop.db.

VPS / Docker
bash
# Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
bash
docker build -t varendy .
docker run -d --env-file .env -p 8080:8080 varendy
🔐 Безопасность
Все секреты — только в переменных окружения, никогда в коде

Веб-панель — авторизация по паролю + подписанные cookie (itsdangerous)

Фото аккаунтов хранятся в Telegram (file_id), отдаются через /api/photo/{id}

Валидация initData (если используется Mini App — не в этой версии)

Пароли аккаунтов хранятся в БД в открытом виде — защищайте доступ к БД

⚠️ Если БД скомпрометирована — скомпрометированы все аккаунты. Не выставляйте дашборд в публичный доступ без HTTPS.

📸 Скриншоты
Дашборд	Аккаунты	Карточка аккаунта
скоро	скоро	скоро
🤝 Вклад
PR и issues приветствуются. Если нашли баг — откройте issue с логами и шагами воспроизведения.

📄 Лицензия
MIT — используйте как хотите, но без гарантий.

⚠️ Дисклеймер
Проект не связан с Riot Games, FunPay, CryptoBot или Telegram. Использование автоматизации может нарушать правила этих платформ. Автор не несёт ответственности за баны, потерю аккаунтов и любые другие последствия. Используйте на свой страх и риск.

<div align="center">
⬆ Наверх

</div>
🇬🇧 English
📖 About
VARendy is a fully automated Valorant account rental system with two interfaces:

🤖 Telegram bot — for buyers: pick a rank, duration (3/6/12 hours), payment method.

🖥 Web panel — for admins: manage accounts, view sales stats, real-time notifications.

Payments go through FunPay and CryptoBot. The bot delivers credentials automatically after payment and returns the account to the pool once the rental ends.

✨ Features
Buyer (Telegram)
🛒 Shop with rank filter (Iron → Radiant)

⏱ Rental for 3, 6 or 12 hours

💳 Payment via FunPay or CryptoBot

📸 Account photo, description, specs

🎁 Automatic credential delivery after payment

🛟 24/7 support button

Admin (Web)
📊 Dashboard: revenue, active rentals, total hours

➕ Add accounts one by one (with photo upload)

📥 Bulk upload (login;;password;;rank;;p3,p6,p12)

✏️ Edit any account field

📤 Export all accounts to .txt

🔔 Real-time notifications (new rental, rental ended)

🔑 "Awaiting password change" section with quick reset

💳 Enable/disable payment methods

Admin (Telegram)
/admin — control panel

Add/delete/list accounts

Manage payment methods and description template

Purchase notifications

🏗 Architecture
text
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│  Telegram   │◄────►│   aiohttp    │◄────►│   SQLite /  │
│   (aiogram) │      │  Web Server  │      │  PostgreSQL │
└─────────────┘      └──────────────┘      └─────────────┘
       │                    │                     │
       │                    │                     │
       ▼                    ▼                     ▼
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   FunPay    │      │  CryptoBot   │      │  Rental     │
│   Watcher   │      │   Checker    │      │  Checkers   │
└─────────────┘      └──────────────┘      └─────────────┘
A single process runs both the bot (polling) and the web server (on PORT). Background jobs:

rental_checker — frees accounts after rental

payment_checker — polls CryptoBot invoices

reservation_checker — releases stale reservations (15 min)

funpay_watcher — listens to FunPay payments

lot_manager — auto-creates/closes FunPay lots

🛠 Tech Stack
Component	Stack
Telegram bot	aiogram 3.x
Web server	aiohttp + Jinja2
Database	SQLAlchemy 2.0 (async) · SQLite / PostgreSQL
FunPay API	aioFunPayAPI
CryptoBot API	aiohttp + Crypto Pay API
Web auth	itsdangerous (signed cookies)
Styling	Tailwind CSS (CDN)
🚀 Installation
1. Clone
bash
git clone https://github.com/ByDendy/VARendy.git
cd VARendy
2. Virtual environment
bash
python -m venv venv
source venv/bin/activate      # Linux/macOS
venv\Scripts\activate         # Windows
3. Dependencies
bash
pip install -r requirements.txt
4. Environment variables
Create .env in the project root:

env
# Telegram
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxyz
ADMIN_IDS=8792910093
SUPPORT_USERNAME=@varendy_support

# FunPay
FUNPAY_GOLDEN_KEY=your_golden_key_here
FUNPAY_USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
FUNPAY_CATEGORY_ID=1234
FUNPAY_AUTO_LOTS_ENABLED=true

# CryptoBot
CRYPTOBOT_TOKEN=12345:AAxxxxxxxxxxxxxxxxxxxxxxx

# Web panel
WEB_ADMIN_PASSWORD=strong_password_here
WEB_SECRET_KEY=random_32_plus_characters_string_here

# Database (optional, defaults to SQLite)
DATABASE_URL=sqlite+aiosqlite:///valoshop.db
5. Run
bash
python bot.py
After startup:

Bot starts Telegram polling

Web panel is available at http://localhost:8080

📂 Project Structure
text
VARendy/
├── bot.py                    # entrypoint
├── config.py                 # env vars
├── requirements.txt
├── database/
│   ├── models.py             # Account, RentalHistory, Lot, ...
│   └── session.py            # async engine
├── handlers/                 # Telegram handlers
│   ├── start.py              # /start, support
│   ├── buyer.py              # shop, checkout
│   ├── admin.py              # admin panel
│   ├── rental_checker.py     # post-rental release
│   ├── payment_checker.py    # CryptoBot polling
│   ├── reservation_checker.py
│   ├── funpay_watcher.py     # FunPay auto-delivery
│   └── lot_manager.py        # auto lot creation
├── services/
│   ├── funpay_service.py
│   ├── cryptobot_service.py
│   ├── settings_service.py
│   └── notifications.py
└── web/
    ├── server.py             # aiohttp app
    ├── notifications.py      # SSE-style event queue
    ├── photo_proxy.py        # Telegram photo proxy
    └── templates/            # Jinja2 templates
⚙️ How It Works
Account lifecycle
text
   ┌──────┐  reserve 15 min  ┌──────────┐  payment  ┌────────┐
   │ free │ ───────────────► │ reserved │ ────────► │ rented │
   └──────┘                  └──────────┘           └────────┘
      ▲                           │                     │
      │      not paid             │                     │ rental expired
      └───────────────────────────┘                     ▼
      │                                     ┌───────────────────────┐
      │       password changed              │ awaiting_password_    │
      └─────────────────────────────────────┤ change                │
                                            └───────────────────────┘
Auto-delivery
Buyer clicks "Buy" → account becomes reserved for 15 min

Invoice is created (CryptoBot) or lot link is provided (FunPay)

Background payment_checker / funpay_watcher listen for payment

On payment → account becomes rented, credentials are sent to buyer

When rental expires → awaiting_password_change, admin is notified

Admin updates password in web panel → account is free again

🌐 Deployment
Railway
Push repo to GitHub

Create a new project on Railway

Connect the GitHub repo

Add all .env variables under Variables

Railway auto-detects Python and runs python bot.py

Open the public domain → /login → sign in

⚠️ Important: Railway does not persist SQLite across restarts without a Volume. Use a PostgreSQL service (Railway provides DATABASE_URL automatically) or mount a Volume at /data with DATABASE_URL = sqlite+aiosqlite:////data/valoshop.db.

VPS / Docker
dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
bash
docker build -t varendy .
docker run -d --env-file .env -p 8080:8080 varendy
🔐 Security
All secrets live in env vars, never in code

Web panel uses password auth + signed cookies (itsdangerous)

Account photos are stored in Telegram (file_id), served via /api/photo/{id}

Account credentials are stored in plaintext in the DB — protect DB access carefully

⚠️ Compromised DB = compromised accounts. Do not expose the dashboard publicly without HTTPS.

📸 Screenshots
Dashboard	Accounts	Account card
coming soon	coming soon	coming soon
🤝 Contributing
PRs and issues are welcome. If you found a bug — open an issue with logs and reproduction steps.

📄 License
MIT — free to use, no warranty.

⚠️ Disclaimer
This project is not affiliated with Riot Games, FunPay, CryptoBot, or Telegram. Automating these platforms may violate their Terms of Service. The author is not responsible for bans, lost accounts, or any other consequences. Use at your own risk.

<div align="center">
⬆ Back to top

</div> ```
