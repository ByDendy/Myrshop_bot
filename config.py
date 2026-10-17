import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
FUNPAY_GOLDEN_KEY = os.getenv("FUNPAY_GOLDEN_KEY")
FUNPAY_USER_AGENT = os.getenv("FUNPAY_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/valoshop.db")
