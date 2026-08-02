# QR Queue — Enterprise Edition (Supabase / Postgres)

ระบบคิว OPD เดิม (Flask + SQLite) ที่แปลงฐานข้อมูลเป็น **Supabase (PostgreSQL)**
พร้อมปรับสถาปัตยกรรมให้รองรับหลายสาขา/หลายแผนกพร้อมกันในระดับองค์กร

ทดสอบ end-to-end แล้ว (patient flow, admin login, call/complete, dashboard) กับ
Postgres จริงก่อนส่งมอบ — ดูสรุปผลทดสอบท้ายไฟล์นี้

## สิ่งที่เปลี่ยนจากเวอร์ชันเดิม

| เดิม | ใหม่ |
|---|---|
| SQLite ไฟล์เดียว | Supabase Postgres + connection pool |
| เลขคิวจาก `COUNT(*)` (เสี่ยงเลขซ้ำเวลามีคนกดพร้อมกัน) | atomic function `next_ticket_number()` ระดับ DB |
| กดเรียกคิวพร้อมกันได้คิวเดียวกันซ้ำ | `SELECT ... FOR UPDATE SKIP LOCKED` |
| รหัสผ่าน admin ฝังในโค้ด (`config.py`) | อยู่ใน ENV เท่านั้น + `scripts/create_admin.py` |
| ไม่มี role | `staff / branch_admin / org_admin / super_admin` |
| ไม่มีการแบ่งสาขา | `organizations → branches → queue_types → tickets` |
| ไม่มี audit trail | ตาราง `audit_log` บันทึกทุก login/call/complete/skip |
| ไม่มี CSRF protection | Flask-WTF CSRF ทุกฟอร์ม |
| ไม่มี rate limit | Flask-Limiter ที่ `/admin/*` และ `/*` (กัน brute-force / spam) |
| polling ทุก 5 วิ เท่านั้น | เปิด Supabase Realtime ไว้ที่ตาราง `tickets` แล้ว (ยังไม่ได้ต่อฝั่ง frontend — ดู UPGRADE_GUIDE) |
| ไม่มี health check | `/healthz` สำหรับ load balancer |

## Setup

### 1. สร้างโปรเจ็กต์ Supabase
สมัคร/สร้างโปรเจ็กต์ที่ [supabase.com](https://supabase.com) แล้วเปิด **SQL Editor**
รันไฟล์ `supabase/schema.sql` ทั้งไฟล์ (จะสร้างตาราง, function, RLS policy, และ seed
ข้อมูลตัวอย่าง 1 องค์กร / 1 สาขา / 5 แผนก)

### 2. ตั้งค่า environment
```bash
cp .env.example .env
# กรอก DATABASE_URL จาก Supabase Dashboard -> Project Settings -> Database
#   -> Connection string -> URI -> เลือก "Connection pooling" (port 6543)
```

### 3. ติดตั้งและรัน
```bash
pip install -r requirements.txt
python scripts/create_admin.py --username admin --role super_admin
python run.py          # dev
# production: gunicorn -w 4 -b 0.0.0.0:8000 run:app
```

เข้าหน้าคนไข้ที่ `/` และหน้าเจ้าหน้าที่ที่ `/admin/login`

### สร้าง admin ของสาขาใดสาขาหนึ่ง (ไม่ใช่ super_admin)
```bash
python scripts/create_admin.py --username nurse_a --role branch_admin --branch-id <uuid ของสาขา>
```
หา `branch_id` ได้จากตาราง `branches` ใน Supabase Table Editor

## โครงสร้างโปรเจ็กต์
```
supabase/schema.sql     ตาราง, RLS, atomic ticket counter, seed data
config.py               อ่าน secrets จาก ENV ทั้งหมด
app/database.py         connection pool ไป Supabase Postgres
app/utils.py             QR code, ETA, atomic queue numbering
app/routes/user_routes.py   หน้าคนไข้ + API สถานะ
app/routes/admin_routes.py  login, เรียกคิว, dashboard, role-based access
scripts/create_admin.py     bootstrap ผู้ใช้แรกแบบไม่ฝังรหัสผ่านในโค้ด
```

## ผลทดสอบ (รันจริงกับ Postgres ก่อนส่งมอบ)
- ✅ ออกบัตรคิว `A001` ผ่าน `/get_ticket` → บันทึกลง DB ถูกต้อง
- ✅ `/api/status/<id>` คืนสถานะ + ETA ถูกต้อง
- ✅ Login เจ้าหน้าที่ (role `super_admin`) เห็นครบทุกแผนก/ทุกสาขา
- ✅ กด "เรียกคิวถัดไป" → คิวที่เก่าสุดเปลี่ยนเป็น `in_service` ถูกใบ, ใบอื่นยัง `waiting`
- ✅ Audit log บันทึก `login`, `call_next` พร้อม ticket ที่เกี่ยวข้อง
- ✅ กด "เสร็จสิ้น" → สถานะเปลี่ยนเป็น `done`
- ✅ Dashboard คำนวณสถิติถูกต้อง (ทดสอบแล้วได้: คิววันนี้ 2, เสร็จแล้ว 1, รออยู่ 1, เวลารอเฉลี่ย 0.4 นาที)
- 🔧 พบและแก้บั๊กระหว่างทดสอบ: `hour` เป็นคำสงวนใน Postgres ทำให้ query dashboard พังตอน deploy จริง — แก้แล้วก่อนส่งมอบ

## สิ่งที่ยังไม่ได้ทำ (ดูรายละเอียดใน UPGRADE_GUIDE.md)
Realtime แทน polling ฝั่ง frontend, ระบบแจ้งเตือน (LINE/SMS), observability
(Sentry/metrics), Docker + CI/CD, Alembic migrations, load testing, automated tests
