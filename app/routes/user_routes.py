from flask import Blueprint, render_template, request, redirect, url_for, jsonify, current_app

from app.database import get_db, get_cursor
from app.utils import next_queue_number, make_qr_base64, people_ahead, avg_service_seconds, iso

user_bp = Blueprint('user', __name__)


@user_bp.route("/")
@user_bp.route("/b/<branch_id>")
def index(branch_id=None):
    """ถ้าไม่ระบุ branch_id จะ fallback ไปสาขาแรกที่ active — เผื่อ deploy รุ่นเดียวสาขาเดียว
    ถ้าเป็น chain หลายสาขา ให้ทำ QR/ลิงก์ต่อ kiosk แยกตาม /b/<branch_id>"""
    db = get_db()
    cur = get_cursor(db)
    if branch_id is None:
        cur.execute("SELECT id FROM branches WHERE is_active = true ORDER BY created_at LIMIT 1")
        row = cur.fetchone()
        if not row:
            return "ยังไม่มีสาขาที่ตั้งค่าไว้ในระบบ", 500
        branch_id = row["id"]

    cur.execute(
        "SELECT * FROM queue_types WHERE branch_id = %s AND is_active = true ORDER BY prefix",
        (branch_id,),
    )
    queue_types = cur.fetchall()
    return render_template("index.html", queue_types=queue_types, branch_id=branch_id)


@user_bp.route("/get_ticket", methods=["POST"])
def get_ticket():
    db = get_db()
    cur = get_cursor(db)
    queue_type_id = request.form.get("queue_type_id")
    cur.execute("SELECT * FROM queue_types WHERE id = %s", (queue_type_id,))
    qtype = cur.fetchone()
    if not qtype:
        return redirect(url_for("user.index"))

    queue_number = next_queue_number(db, qtype["id"], qtype["prefix"])
    cur.execute(
        """INSERT INTO tickets (queue_number, queue_type_id, branch_id, status)
           VALUES (%s, %s, %s, 'waiting') RETURNING id""",
        (queue_number, qtype["id"], qtype["branch_id"]),
    )
    ticket_id = cur.fetchone()["id"]
    db.commit()

    status_url = url_for("user.status_page", ticket_id=ticket_id, _external=True)
    qr_b64 = make_qr_base64(status_url)

    return render_template(
        "ticket.html",
        queue_number=queue_number,
        ticket_id=ticket_id,
        qr_b64=qr_b64,
        status_url=status_url,
    )


@user_bp.route("/status/<int:ticket_id>")
def status_page(ticket_id):
    return render_template("status.html", ticket_id=ticket_id)


@user_bp.route("/api/status/<int:ticket_id>")
def api_status(ticket_id):
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT * FROM tickets WHERE id = %s", (ticket_id,))
    ticket = cur.fetchone()
    if not ticket:
        return jsonify({"error": "ไม่พบคิวนี้"}), 404

    cur.execute("SELECT * FROM queue_types WHERE id = %s", (ticket["queue_type_id"],))
    qtype = cur.fetchone()

    cur.execute(
        """SELECT queue_number FROM tickets
           WHERE queue_type_id = %s AND status = 'in_service'
           ORDER BY called_at DESC LIMIT 1""",
        (ticket["queue_type_id"],),
    )
    now_calling = cur.fetchone()

    ahead = people_ahead(db, ticket) if ticket["status"] == "waiting" else 0
    avg_secs = avg_service_seconds(db, ticket["queue_type_id"])
    eta_minutes = round((ahead * avg_secs) / 60) if ticket["status"] == "waiting" else 0

    return jsonify(
        {
            "queue_number": ticket["queue_number"],
            "queue_type": qtype["name"],
            "status": ticket["status"],
            "now_calling": now_calling["queue_number"] if now_calling else "-",
            "people_ahead": ahead,
            "eta_minutes": eta_minutes,
            "created_at": iso(ticket["created_at"]),
        }
    )
