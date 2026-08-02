from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from werkzeug.security import check_password_hash

from app.database import get_db, get_cursor
from app.utils import iso

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

ROLE_RANK = {"staff": 0, "branch_admin": 1, "org_admin": 2, "super_admin": 3}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("staff_id"):
            return redirect(url_for("admin.admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def role_required(min_role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("staff_id"):
                return redirect(url_for("admin.admin_login", next=request.path))
            if ROLE_RANK.get(session.get("staff_role"), 0) < ROLE_RANK[min_role]:
                flash("คุณไม่มีสิทธิ์เข้าถึงหน้านี้")
                return redirect(url_for("admin.admin"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def log_action(action, entity=None, details=None):
    db = get_db()
    cur = get_cursor(db)
    cur.execute(
        """INSERT INTO audit_log (staff_id, branch_id, action, entity, details)
           VALUES (%s, %s, %s, %s, %s)""",
        (session.get("staff_id"), session.get("staff_branch_id"), action, entity, details),
    )
    db.commit()


def scoped_branch_filter():
    """คืนเงื่อนไข branch สำหรับ query: super_admin/org_admin เห็นได้ทุกสาขาในองค์กร,
    role อื่นเห็นเฉพาะสาขาของตัวเอง"""
    if session.get("staff_role") in ("super_admin", "org_admin"):
        return None
    return session.get("staff_branch_id")


# Rate limiting ของ /login ใส่ผ่าน flask-limiter ที่ตั้งค่าไว้ใน app/__init__.py
# (ดู @limiter.limit ที่แปะไว้ตรงนั้น เพื่อกัน brute-force รหัสผ่าน)
@admin_bp.route("/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        db = get_db()
        cur = get_cursor(db)
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        cur.execute(
            "SELECT * FROM staff WHERE username = %s AND is_active = true", (username,)
        )
        staff = cur.fetchone()
        if staff and staff["password_hash"] and check_password_hash(staff["password_hash"], password):
            session.clear()
            session["staff_id"] = staff["id"]
            session["staff_username"] = staff["username"]
            session["staff_role"] = staff["role"]
            session["staff_branch_id"] = staff["branch_id"]
            session.permanent = True
            log_action("login")
            next_url = request.args.get("next") or url_for("admin.admin")
            return redirect(next_url)
        flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    return render_template("login.html")


@admin_bp.route("/logout", methods=["POST"])
@login_required
def admin_logout():
    log_action("logout")
    session.clear()
    return redirect(url_for("admin.admin_login"))


@admin_bp.route("/")
@login_required
def admin():
    db = get_db()
    cur = get_cursor(db)
    branch_id = scoped_branch_filter()
    if branch_id:
        cur.execute(
            "SELECT * FROM queue_types WHERE branch_id = %s AND is_active = true ORDER BY prefix",
            (branch_id,),
        )
    else:
        cur.execute("SELECT * FROM queue_types WHERE is_active = true ORDER BY branch_id, prefix")
    queue_types = cur.fetchall()
    return render_template("admin.html", queue_types=queue_types)


def _assert_room_access(cur, queue_type_id):
    """กันไม่ให้ staff สาขา A เข้าไปกดเรียก/จบคิวของสาขา B ผ่านการเดา URL"""
    branch_id = scoped_branch_filter()
    if branch_id is None:
        return True
    cur.execute("SELECT 1 FROM queue_types WHERE id = %s AND branch_id = %s", (queue_type_id, branch_id))
    return cur.fetchone() is not None


@admin_bp.route("/room/<queue_type_id>")
@login_required
def room(queue_type_id):
    db = get_db()
    cur = get_cursor(db)
    if not _assert_room_access(cur, queue_type_id):
        flash("ไม่มีสิทธิ์เข้าถึงห้องนี้")
        return redirect(url_for("admin.admin"))

    cur.execute("SELECT * FROM queue_types WHERE id = %s", (queue_type_id,))
    qtype = cur.fetchone()
    if not qtype:
        return redirect(url_for("admin.admin"))

    cur.execute(
        """SELECT * FROM tickets WHERE status = 'waiting' AND queue_type_id = %s
           ORDER BY priority = 'urgent' DESC, created_at ASC""", (queue_type_id,)
    )
    waiting = cur.fetchall()

    cur.execute(
        """SELECT * FROM tickets WHERE status = 'in_service' AND queue_type_id = %s
           ORDER BY called_at DESC""", (queue_type_id,)
    )
    in_service = cur.fetchall()

    return render_template("admin_room.html", qtype=qtype, waiting=waiting, in_service=in_service, iso=iso)


@admin_bp.route("/call_next/<queue_type_id>", methods=["POST"])
@login_required
def call_next(queue_type_id):
    db = get_db()
    cur = get_cursor(db)
    if not _assert_room_access(cur, queue_type_id):
        return redirect(url_for("admin.admin"))

    # SELECT ... FOR UPDATE SKIP LOCKED กันสองเจ้าหน้าที่กดเรียกคิวเดียวกันพร้อมกัน (race condition)
    cur.execute(
        """SELECT id FROM tickets WHERE queue_type_id = %s AND status = 'waiting'
           ORDER BY priority = 'urgent' DESC, created_at ASC
           LIMIT 1 FOR UPDATE SKIP LOCKED""",
        (queue_type_id,),
    )
    ticket = cur.fetchone()
    if ticket:
        cur.execute(
            """UPDATE tickets SET status = 'in_service', called_at = now(), called_by = %s
               WHERE id = %s""",
            (session.get("staff_id"), ticket["id"]),
        )
        db.commit()
        log_action("call_next", entity=f"ticket:{ticket['id']}")
    return redirect(url_for("admin.room", queue_type_id=queue_type_id))


@admin_bp.route("/complete/<int:ticket_id>", methods=["POST"])
@login_required
def complete_ticket(ticket_id):
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT queue_type_id FROM tickets WHERE id = %s", (ticket_id,))
    ticket = cur.fetchone()
    if ticket and _assert_room_access(cur, ticket["queue_type_id"]):
        cur.execute(
            "UPDATE tickets SET status = 'done', completed_at = now() WHERE id = %s",
            (ticket_id,),
        )
        db.commit()
        log_action("complete", entity=f"ticket:{ticket_id}")
        return redirect(url_for("admin.room", queue_type_id=ticket["queue_type_id"]))
    return redirect(url_for("admin.admin"))


@admin_bp.route("/skip/<int:ticket_id>", methods=["POST"])
@login_required
def skip_ticket(ticket_id):
    db = get_db()
    cur = get_cursor(db)
    cur.execute("SELECT queue_type_id FROM tickets WHERE id = %s", (ticket_id,))
    ticket = cur.fetchone()
    if ticket and _assert_room_access(cur, ticket["queue_type_id"]):
        cur.execute("UPDATE tickets SET status = 'skipped' WHERE id = %s", (ticket_id,))
        db.commit()
        log_action("skip", entity=f"ticket:{ticket_id}")
        return redirect(url_for("admin.room", queue_type_id=ticket["queue_type_id"]))
    return redirect(url_for("admin.admin"))


@admin_bp.route("/dashboard")
@login_required
@role_required("branch_admin")
def dashboard():
    db = get_db()
    cur = get_cursor(db)
    branch_id = scoped_branch_filter()
    branch_clause = "AND branch_id = %(branch_id)s" if branch_id else ""
    params = {"branch_id": branch_id}

    cur.execute(f"SELECT COUNT(*) cnt FROM tickets WHERE created_at::date = current_date {branch_clause}", params)
    total_today = cur.fetchone()["cnt"]

    cur.execute(f"SELECT COUNT(*) cnt FROM tickets WHERE created_at::date = current_date AND status='done' {branch_clause}", params)
    done_today = cur.fetchone()["cnt"]

    cur.execute(f"SELECT COUNT(*) cnt FROM tickets WHERE created_at::date = current_date AND status='skipped' {branch_clause}", params)
    skipped_today = cur.fetchone()["cnt"]

    cur.execute(f"SELECT COUNT(*) cnt FROM tickets WHERE status='waiting' {branch_clause}", params)
    waiting_now = cur.fetchone()["cnt"]

    cur.execute(
        f"""SELECT COALESCE(ROUND(AVG(EXTRACT(EPOCH FROM (called_at - created_at))) / 60, 1), 0) avg_min
            FROM tickets WHERE created_at::date = current_date AND called_at IS NOT NULL {branch_clause}""",
        params,
    )
    avg_wait_minutes = cur.fetchone()["avg_min"]

    cur.execute(
        f"""SELECT to_char(created_at, 'HH24:00') AS hour_label, COUNT(*) cnt
            FROM tickets WHERE created_at::date = current_date {branch_clause}
            GROUP BY 1 ORDER BY cnt DESC LIMIT 1""",
        params,
    )
    row = cur.fetchone()
    busiest_hour = row["hour_label"] if row else "-"

    qt_clause = "AND qt.branch_id = %(branch_id)s" if branch_id else ""
    cur.execute(
        f"""SELECT qt.name AS type_name, COUNT(t.id) AS cnt
            FROM queue_types qt
            LEFT JOIN tickets t ON t.queue_type_id = qt.id AND t.created_at::date = current_date
            WHERE 1=1 {qt_clause}
            GROUP BY qt.id, qt.name ORDER BY qt.name""",
        params,
    )
    per_type = cur.fetchall()

    return render_template(
        "dashboard.html",
        total_today=total_today,
        done_today=done_today,
        skipped_today=skipped_today,
        waiting_now=waiting_now,
        avg_wait_minutes=avg_wait_minutes,
        busiest_hour=busiest_hour,
        per_type=per_type,
    )
