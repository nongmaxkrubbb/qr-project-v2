import io
import base64
import qrcode
from datetime import datetime, date


def next_queue_number(db, queue_type_id, prefix):
    """ออกเลขคิวแบบ atomic ผ่านฟังก์ชัน next_ticket_number() ใน database
    (แก้ปัญหาเดิมที่ใช้ COUNT(*) ซึ่งเกิดเลขซ้ำได้เมื่อมีคนกดรับคิวพร้อมกันหลายคน)"""
    cur = db.cursor()
    cur.execute("SELECT next_ticket_number(%s, %s) AS n", (queue_type_id, date.today()))
    n = cur.fetchone()[0]
    return f"{prefix}{n:03d}"


def avg_service_seconds(db, queue_type_id):
    from app.database import get_cursor
    cur = get_cursor(db)
    cur.execute(
        """SELECT called_at, completed_at FROM tickets
           WHERE queue_type_id = %s AND completed_at IS NOT NULL AND called_at IS NOT NULL
           ORDER BY completed_at DESC LIMIT 20""",
        (queue_type_id,),
    )
    rows = cur.fetchall()
    if not rows:
        return 600  # ค่าเดาเริ่มต้น: 10 นาที
    total, n = 0, 0
    for row in rows:
        diff = (row["completed_at"] - row["called_at"]).total_seconds()
        if diff > 0:
            total += diff
            n += 1
    return int(total / n) if n else 600


def people_ahead(db, ticket):
    from app.database import get_cursor
    cur = get_cursor(db)
    cur.execute(
        """SELECT COUNT(*) AS cnt FROM tickets
           WHERE queue_type_id = %s AND status = 'waiting' AND id < %s""",
        (ticket["queue_type_id"], ticket["id"]),
    )
    return cur.fetchone()["cnt"]


def make_qr_base64(url):
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def iso(dt):
    """แปลง datetime ของ Postgres ให้เป็น isoformat string เพื่อให้ template เดิม
    (ที่ตัด string เช่น created_at[11:16]) ยังใช้งานได้เหมือนเดิม"""
    if dt is None:
        return None
    return dt.isoformat(timespec="seconds") if isinstance(dt, datetime) else str(dt)
