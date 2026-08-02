import os
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from flask import g, current_app

_pool = None


def init_pool(app):
    """สร้าง connection pool ครั้งเดียวตอนแอปสตาร์ท (ไม่ใช่ต่อ request)
    เพื่อรองรับ concurrent users จำนวนมากโดยไม่เปิด/ปิด connection ใหม่ทุกครั้ง"""
    global _pool
    if _pool is None:
        dsn = app.config.get("DATABASE_URL") or os.getenv("DATABASE_URL")
        if not dsn:
            raise ValueError("DATABASE_URL is not set")

        # ลบ query parameter "pgbouncer" ออกเพื่อไม่ให้ psycopg2 แจ้ง invalid dsn error
        url = urlparse(dsn)
        query_params = dict(parse_qsl(url.query))
        query_params.pop("pgbouncer", None)
        clean_dsn = urlunparse(url._replace(query=urlencode(query_params)))

        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=app.config.get("DB_POOL_MIN", 1),
            maxconn=app.config.get("DB_POOL_MAX", 10),
            dsn=clean_dsn,
        )


def get_db():
    """คืน connection จาก pool ผูกกับ Flask request context (g)"""
    if "db" not in g:
        g.db = _pool.getconn()
        g.db.autocommit = False
    return g.db


def get_cursor(conn=None):
    """cursor แบบ dict-like (เทียบเท่า sqlite3.Row เดิม) ให้เข้าถึงด้วยชื่อคอลัมน์ได้"""
    conn = conn or get_db()
    return conn.cursor(cursor_factory=RealDictCursor)


def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        if exception:
            db.rollback()
        _pool.putconn(db)


def init_app(app):
    init_pool(app)
    app.teardown_appcontext(close_db)
    # หมายเหตุ: ไม่ทำ init_db()/CREATE TABLE จากฝั่งแอปอีกต่อไป
    # schema ทั้งหมดจัดการผ่าน supabase/schema.sql + migration tool (ดู README)
    # เพื่อให้ deploy หลาย instance พร้อมกันไม่ชน schema กันเอง