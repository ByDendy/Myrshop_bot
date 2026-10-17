import os

BOT_TOKEN = os.getenv("8982376797:AAFExZU5m315LVVv3aNiMjKSoM2ITurjsYQ")
ADMIN_IDS = [int(x) for x in os.getenv("8792910093", "").split(",") if x]
FUNPAY_GOLDEN_KEY = os.getenv("eh1mohrf59deqwi8gg9dg3l5a46ggd8i")
FUNPAY_USER_AGENT = os.getenv("FUNPAY_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/valoshop.db")
