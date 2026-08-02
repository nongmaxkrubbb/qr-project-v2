"""
สคริปต์สร้างบัญชีเจ้าหน้าที่คนแรก (super_admin) — รันครั้งเดียวตอน setup ระบบใหม่

การใช้งาน:
    python scripts/create_admin.py --username admin --branch-id <uuid หรือเว้นว่างได้ถ้าเป็น super_admin>

รหัสผ่านจะถูกถามแบบซ่อน (getpass) ไม่ต้องพิมพ์เป็น argument เพื่อไม่ให้หลุดใน shell history
"""
import argparse
import getpass
import os
import sys
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import psycopg2
from werkzeug.security import generate_password_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", default="super_admin",
                        choices=["staff", "branch_admin", "org_admin", "super_admin"])
    parser.add_argument("--branch-id", default=None)
    parser.add_argument("--organization-id", default=None)
    args = parser.parse_args()

    password = getpass.getpass("ตั้งรหัสผ่าน: ")
    confirm = getpass.getpass("ยืนยันรหัสผ่านอีกครั้ง: ")
    if password != confirm:
        print("รหัสผ่านไม่ตรงกัน", file=sys.stderr)
        sys.exit(1)
    if len(password) < 10:
        print("รหัสผ่านควรยาวอย่างน้อย 10 ตัวอักษรสำหรับระบบระดับองค์กร", file=sys.stderr)
        sys.exit(1)

    # ✅ 1. ดึง DIRECT_URL เป็นอันดับแรก (ถ้าไม่มีใน .env ค่อยสลับไปใช้ DATABASE_URL)
    dsn = os.getenv("DIRECT_URL") or os.getenv("DATABASE_URL")
    
    if not dsn:
        print("ไม่พบ DIRECT_URL หรือ DATABASE_URL ในไฟล์ .env", file=sys.stderr)
        sys.exit(1)

    # ✅ 2. กรองและลบ query parameter "pgbouncer" ออก เพื่อป้องกัน psycopg2.ProgrammingError
    url = urlparse(dsn)
    query_params = dict(parse_qsl(url.query))
    query_params.pop("pgbouncer", None)  # ลบ pgbouncer ออกถ้ามี
    clean_dsn = urlunparse(url._replace(query=urlencode(query_params)))

    try:
        conn = psycopg2.connect(clean_dsn)
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO staff (username, password_hash, role, branch_id, organization_id)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (username) DO UPDATE
                   SET password_hash = EXCLUDED.password_hash, role = EXCLUDED.role""",
            (args.username, generate_password_hash(password), args.role, args.branch_id, args.organization_id),
        )
        conn.commit()
        print(f"สร้าง/อัปเดตผู้ใช้ '{args.username}' (role={args.role}) เรียบร้อย")
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการเชื่อมต่อหรือบันทึกข้อมูล: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if 'conn' in locals() and conn:
            conn.close()


if __name__ == "__main__":
    main()