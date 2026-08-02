import os


def _require(name):
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in before running the app."
        )
    return val


class Config:
    # ----- Secrets: ต้องมาจาก ENV เท่านั้น ห้าม hardcode ในโค้ดเด็ดขาด -----
    SECRET_KEY = _require("SECRET_KEY")

    # Supabase Postgres connection string, e.g.
    # postgresql://postgres.xxxx:PASSWORD@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres
    # ใช้ pooler (พอร์ต 6543 / pgbouncer, transaction mode) ไม่ใช่ direct connection (5432)
    # เพราะรองรับ concurrent connections จำนวนมากจากหลาย instance ของแอปได้ดีกว่า
    DATABASE_URL = _require("DATABASE_URL")

    # Supabase project (ใช้เมื่อต่อ Supabase Auth / Storage / Realtime ฝั่ง client)
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
    SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    DB_POOL_MIN = int(os.environ.get("DB_POOL_MIN", 1))
    DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", 10))

    # ----- Session / cookie hardening -----
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_ENV") == "production"
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = int(os.environ.get("SESSION_LIFETIME_SECONDS", 8 * 3600))

    # ----- Rate limiting (ดู app/__init__.py) -----
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
