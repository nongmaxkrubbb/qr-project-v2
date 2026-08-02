# แผนอัพเกรดสู่ระดับองค์กร — QR Queue

เอกสารนี้แบ่งเป็น "ทำให้แล้วในโค้ด v2" กับ "แนะนำ แต่ยังไม่ได้ลงมือทำ" เรียงตามผลกระทบ

## ✅ ทำให้แล้วใน v2 (ดู README.md)
- ย้าย SQLite → Supabase Postgres + connection pooling
- แก้ race condition เรื่องเลขคิวซ้ำ และการเรียกคิวซ้ำ
- เอารหัสผ่านออกจากโค้ด, เพิ่ม role-based access, multi-branch, audit log
- CSRF protection, rate limiting, structured logging, `/healthz`

## 🔧 แนะนำลำดับถัดไป

### 1. Realtime แทน polling (ผลกระทบสูง, ทำง่าย)
ตอนนี้เปิด `supabase_realtime` publication ไว้ที่ตาราง `tickets` แล้วในสคีมา
แต่หน้า `status.html` ยังคง poll `/api/status/<id>` ทุก 5 วินาทีอยู่ ขั้นต่อไป:
เปลี่ยนหน้าคนไข้/หน้าจอทีวีในห้องรอให้ subscribe ผ่าน Supabase JS client
(`supabase.channel(...).on('postgres_changes', ...)`) แทน — ลด load ที่ server
ได้มากเมื่อมีคนไข้เปิดหน้าค้างพร้อมกันหลักพันคน และได้อัปเดตทันทีแทนที่จะรอ 5 วิ

### 2. แจ้งเตือนแบบ push แทนการนั่งเฝ้าหน้าจอ
เพิ่ม LINE Notify / LINE Official Account หรือ SMS gateway (เช่น Twilio) เมื่อเหลือ
คิวรออีก N คิวก่อนถึงคิวคนไข้ — ลดปัญหาคนพลาดคิวเพราะไม่ได้เปิดมือถือดู

### 3. Observability
- **Error tracking**: ต่อ Sentry เข้ากับ Flask (`sentry-sdk[flask]`) แทน log ธรรมดา
- **Metrics**: เวลารอเฉลี่ยต่อแผนก, throughput ต่อชั่วโมง ส่งเข้า Grafana/Datadog
- **Alerting**: แจ้งเตือนถ้าคิวค้างเกิน X นาทีโดยไม่มีการเรียก (บ่งชี้เจ้าหน้าที่ลืมกดหรือระบบมีปัญหา)

### 4. Deployment & CI/CD
- Dockerfile + docker-compose สำหรับ dev, และ deploy จริงผ่าน Fly.io/Render/Cloud Run
- GitHub Actions: run tests → build → deploy อัตโนมัติเมื่อ merge เข้า main
- แยก environment dev/staging/prod ให้ชัดเจน (Supabase project แยกกันต่อ environment)

### 5. Database migrations แบบมีเวอร์ชัน
ตอนนี้ schema.sql รันครั้งเดียวแบบ manual ระยะยาวควรใช้ Alembic หรือ Supabase CLI
migrations เพื่อ track การเปลี่ยนแปลง schema เป็นเวอร์ชัน ๆ และ rollback ได้

### 6. Testing
- Unit tests สำหรับ `next_ticket_number`, `avg_service_seconds`, `people_ahead`
- Integration tests ที่รันกับ Postgres จริง (เช่นผ่าน `pytest` + `testcontainers`)
- Load test (`locust` หรือ `k6`) จำลองคนกดรับบัตรพร้อมกันหลายร้อยคนต่อวินาที
  เพื่อยืนยันว่า atomic counter และ `FOR UPDATE SKIP LOCKED` รับได้จริง

### 7. Auth ที่แข็งแรงขึ้น
ตอนนี้ยังใช้ username/password + session ธรรมดา ระดับองค์กรควรพิจารณา:
- ย้ายไปใช้ Supabase Auth เต็มรูปแบบ (มี MFA, magic link, SSO/SAML ให้ในตัว)
- บังคับเปลี่ยนรหัสผ่านตามรอบ, lockout หลัง login ผิดติดกันหลายครั้ง

### 8. Data & Privacy
ข้อมูลคิวโรงพยาบาลอาจเข้าข่ายข้อมูลสุขภาพ/ข้อมูลส่วนบุคคลตาม PDPA — ควรมี
data retention policy (ลบ/anonymize ตั๋วเก่าหลังผ่านไป N เดือน) และ encryption
at rest (Supabase เข้ารหัสให้อยู่แล้ว แต่ควรตรวจสอบ compliance requirement ของ รพ.)

### 9. Multi-branch UI ที่ยังไม่ได้ทำ
Backend รองรับหลายสาขาแล้ว (route `/b/<branch_id>`, RLS ตาม branch, role
`org_admin`) แต่ยังไม่มีหน้า UI สำหรับ super_admin จัดการสาขา/แผนก/พนักงานผ่านเว็บ
— ตอนนี้ต้องทำผ่าน Supabase Table Editor หรือ SQL โดยตรง
