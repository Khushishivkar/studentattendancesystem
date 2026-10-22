import csv
import io
import os
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, Response, flash, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import and_, case, func, or_
from werkzeug.security import check_password_hash, generate_password_hash

# ---------------------------------------------------------------- config

app = Flask(__name__)

db_url = os.environ.get("DATABASE_URL") or "sqlite:///attendance.db"
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
    SQLALCHEMY_DATABASE_URI=db_url,
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
)

TZ = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Kolkata"))
LOW = int(os.environ.get("LOW_ATTENDANCE_THRESHOLD", "75"))
STATUSES = ("Present", "Late", "Absent")

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Sign in to continue."


def today():
    return datetime.now(TZ).date()


# ---------------------------------------------------------------- models


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    roll_no = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    section = db.Column(db.String(30), nullable=False, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    records = db.relationship(
        "Attendance", backref="student", cascade="all, delete-orphan"
    )


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer, db.ForeignKey("student.id"), nullable=False, index=True
    )
    day = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False)
    __table_args__ = (db.UniqueConstraint("student_id", "day", name="one_per_day"),)


with app.app_context():
    db.create_all()


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------------------------------------------------------------- helpers


def parse_date(value, default):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


def natural_key(section, roll_no):
    parts = [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", roll_no)]
    return (section.lower(), parts)


def sections():
    rows = (
        db.session.query(Student.section)
        .filter(Student.section != "")
        .distinct()
        .order_by(Student.section)
        .all()
    )
    return [r[0] for r in rows]


def student_list(section="", q=""):
    query = Student.query
    if section:
        query = query.filter(Student.section == section)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Student.name.ilike(like), Student.roll_no.ilike(like)))
    return sorted(query.all(), key=lambda s: natural_key(s.section, s.roll_no))


def build_summary(start=None, end=None, section="", q=""):
    """One row per student with present/late/absent counts and attendance %."""
    join_on = Attendance.student_id == Student.id
    if start:
        join_on = and_(join_on, Attendance.day >= start)
    if end:
        join_on = and_(join_on, Attendance.day <= end)

    def count_of(status):
        return func.coalesce(
            func.sum(case((Attendance.status == status, 1), else_=0)), 0
        )

    query = (
        db.session.query(
            Student.id,
            Student.roll_no,
            Student.name,
            Student.section,
            count_of("Present"),
            count_of("Late"),
            count_of("Absent"),
        )
        .outerjoin(Attendance, join_on)
        .group_by(Student.id, Student.roll_no, Student.name, Student.section)
    )
    if section:
        query = query.filter(Student.section == section)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Student.name.ilike(like), Student.roll_no.ilike(like)))

    out = []
    for sid, roll, name, sec, p, l, a in query.all():
        p, l, a = int(p), int(l), int(a)
        total = p + l + a
        pct = round((p + l) * 100 / total) if total else None
        out.append(
            {
                "id": sid,
                "roll_no": roll,
                "name": name,
                "section": sec,
                "present": p,
                "late": l,
                "absent": a,
                "total": total,
                "pct": pct,
                "low": pct is not None and pct < LOW,
            }
        )
    out.sort(key=lambda r: natural_key(r["section"], r["roll_no"]))
    return out


def safe_cell(value):
    value = str(value)
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value


@app.context_processor
def inject_globals():
    return {"today": today(), "LOW": LOW}


@app.before_request
def require_setup():
    if request.endpoint in (None, "static", "setup"):
        return None
    if not User.query.first():
        return redirect(url_for("setup"))
    return None


# ---------------------------------------------------------------- auth


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if User.query.first():
        return redirect(url_for("login"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if not username:
            flash("Enter a username.", "error")
        elif len(password) < 8:
            flash("Use a password with at least 8 characters.", "error")
        elif password != confirm:
            flash("The passwords don't match.", "error")
        else:
            user = User(username=username, password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            login_user(user, remember=True)
            flash("Account created.", "ok")
            return redirect(url_for("dashboard"))
    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, request.form.get("password", "")):
            login_user(user, remember=True)
            nxt = request.args.get("next", "")
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("dashboard"))
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- dashboard


@app.route("/")
@login_required
def dashboard():
    t = today()
    total_students = Student.query.count()

    counts = dict(
        db.session.query(Attendance.status, func.count())
        .filter(Attendance.day == t)
        .group_by(Attendance.status)
        .all()
    )
    present = counts.get("Present", 0)
    late = counts.get("Late", 0)
    absent = counts.get("Absent", 0)
    marked = present + late + absent

    def share(n):
        return round(n * 100 / total_students, 1) if total_students else 0

    start = t - timedelta(days=13)
    rows = (
        db.session.query(Attendance.day, Attendance.status, func.count())
        .filter(Attendance.day >= start)
        .group_by(Attendance.day, Attendance.status)
        .all()
    )
    per_day = {}
    for d, status, n in rows:
        entry = per_day.setdefault(d, {"total": 0, "ok": 0})
        entry["total"] += n
        if status != "Absent":
            entry["ok"] += n

    trend = []
    for i in range(13, -1, -1):
        d = t - timedelta(days=i)
        e = per_day.get(d)
        trend.append({"day": d, "pct": round(e["ok"] * 100 / e["total"]) if e else None})

    low = [r for r in build_summary(start=t - timedelta(days=29)) if r["low"]]
    low.sort(key=lambda r: r["pct"])

    return render_template(
        "dashboard.html",
        total_students=total_students,
        present=present,
        late=late,
        absent=absent,
        marked=marked,
        unmarked=max(total_students - marked, 0),
        seg={"present": share(present), "late": share(late), "absent": share(absent)},
        trend=trend,
        low=low,
    )


# ---------------------------------------------------------------- students


@app.route("/students")
@login_required
def students():
    section = request.args.get("section", "")
    q = request.args.get("q", "").strip()
    rows = build_summary(section=section, q=q)
    return render_template(
        "students.html", rows=rows, section=section, q=q, all_sections=sections()
    )


def _read_student_form():
    return (
        request.form.get("roll_no", "").strip()[:20],
        request.form.get("name", "").strip()[:100],
        request.form.get("section", "").strip()[:30],
    )


@app.route("/students/new", methods=["GET", "POST"])
@login_required
def student_new():
    if request.method == "POST":
        roll_no, name, section = _read_student_form()
        if not roll_no or not name:
            flash("Roll number and name are required.", "error")
        elif Student.query.filter_by(roll_no=roll_no).first():
            flash(f"Roll number {roll_no} is already in use.", "error")
        else:
            db.session.add(Student(roll_no=roll_no, name=name, section=section))
            db.session.commit()
            flash(f"{name} added.", "ok")
            return redirect(url_for("students"))
    return render_template(
        "student_form.html",
        student=None,
        form=request.form,
        all_sections=sections(),
    )


@app.route("/students/bulk", methods=["GET", "POST"])
@login_required
def students_bulk():
    if request.method == "POST":
        existing = {r[0] for r in db.session.query(Student.roll_no).all()}
        added, skipped = 0, 0
        for line in request.form.get("lines", "").splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2 or not parts[0] or not parts[1]:
                if line.strip():
                    skipped += 1
                continue
            roll_no = parts[0][:20]
            if roll_no in existing:
                skipped += 1
                continue
            section = parts[2][:30] if len(parts) > 2 else ""
            db.session.add(Student(roll_no=roll_no, name=parts[1][:100], section=section))
            existing.add(roll_no)
            added += 1
        db.session.commit()
        if added:
            flash(f"{added} students added." + (f" {skipped} skipped." if skipped else ""), "ok")
            return redirect(url_for("students"))
        flash("No students added. Check the format and roll numbers.", "error")
    return render_template("students_bulk.html")


@app.route("/students/<int:sid>")
@login_required
def student_detail(sid):
    student = db.get_or_404(Student, sid)
    t = today()
    records = (
        Attendance.query.filter_by(student_id=sid).order_by(Attendance.day.desc()).all()
    )
    counts = {s: 0 for s in STATUSES}
    for r in records:
        counts[r.status] = counts.get(r.status, 0) + 1
    total = len(records)
    pct = round((counts["Present"] + counts["Late"]) * 100 / total) if total else None
    by_day = {r.day: r.status for r in records}
    dots = []
    for i in range(29, -1, -1):
        d = t - timedelta(days=i)
        dots.append((d, by_day.get(d)))
    return render_template(
        "student_detail.html",
        student=student,
        counts=counts,
        total=total,
        pct=pct,
        dots=dots,
        records=records[:40],
    )


@app.route("/students/<int:sid>/edit", methods=["GET", "POST"])
@login_required
def student_edit(sid):
    student = db.get_or_404(Student, sid)
    if request.method == "POST":
        roll_no, name, section = _read_student_form()
        clash = Student.query.filter(Student.roll_no == roll_no, Student.id != sid).first()
        if not roll_no or not name:
            flash("Roll number and name are required.", "error")
        elif clash:
            flash(f"Roll number {roll_no} is already in use.", "error")
        else:
            student.roll_no, student.name, student.section = roll_no, name, section
            db.session.commit()
            flash("Changes saved.", "ok")
            return redirect(url_for("student_detail", sid=sid))
    return render_template(
        "student_form.html",
        student=student,
        form=request.form if request.method == "POST" else {},
        all_sections=sections(),
    )


@app.route("/students/<int:sid>/delete", methods=["POST"])
@login_required
def student_delete(sid):
    student = db.get_or_404(Student, sid)
    name = student.name
    db.session.delete(student)
    db.session.commit()
    flash(f"{name} deleted.", "ok")
    return redirect(url_for("students"))


# ---------------------------------------------------------------- attendance sheet


@app.route("/attendance", methods=["GET", "POST"])
@login_required
def attendance():
    t = today()
    source = request.form if request.method == "POST" else request.args
    day = parse_date(source.get("date"), t)
    if day > t:
        day = t
    section = source.get("section", "")
    roster = student_list(section=section)

    if request.method == "POST":
        existing = {
            a.student_id: a
            for a in Attendance.query.filter(
                Attendance.day == day,
                Attendance.student_id.in_([s.id for s in roster]),
            )
        }
        saved = 0
        for s in roster:
            status = request.form.get(f"status_{s.id}")
            if status not in STATUSES:
                continue
            record = existing.get(s.id)
            if record:
                record.status = status
            else:
                db.session.add(Attendance(student_id=s.id, day=day, status=status))
            saved += 1
        db.session.commit()
        flash(f"Saved {saved} marks for {day.strftime('%d %b %Y')}.", "ok")
        return redirect(url_for("attendance", date=day.isoformat(), section=section))

    marks = {
        a.student_id: a.status
        for a in Attendance.query.filter(
            Attendance.day == day, Attendance.student_id.in_([s.id for s in roster])
        )
    }
    return render_template(
        "attendance.html",
        roster=roster,
        marks=marks,
        day=day,
        section=section,
        all_sections=sections(),
    )


# ---------------------------------------------------------------- reports


def _report_args():
    t = today()
    end = parse_date(request.args.get("to"), t)
    start = parse_date(request.args.get("from"), end - timedelta(days=29))
    if start > end:
        start, end = end, start
    return start, end, request.args.get("section", "")


@app.route("/reports")
@login_required
def reports():
    start, end, section = _report_args()
    rows = build_summary(start=start, end=end, section=section)
    return render_template(
        "reports.html",
        rows=rows,
        start=start,
        end=end,
        section=section,
        all_sections=sections(),
    )


@app.route("/reports.csv")
@login_required
def reports_csv():
    start, end, section = _report_args()
    rows = build_summary(start=start, end=end, section=section)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["Roll no", "Name", "Section", "Present", "Late", "Absent", "Days marked", "Attendance %"]
    )
    for r in rows:
        writer.writerow(
            [
                safe_cell(r["roll_no"]),
                safe_cell(r["name"]),
                safe_cell(r["section"]),
                r["present"],
                r["late"],
                r["absent"],
                r["total"],
                "" if r["pct"] is None else r["pct"],
            ]
        )
    filename = f"attendance_{start.isoformat()}_to_{end.isoformat()}.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", message="That page doesn't exist."), 404


if __name__ == "__main__":
    app.run(debug=True)
