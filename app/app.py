from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = "gym_secret_key_change_in_production"
DATABASE = "gym.db"


# ─── Database helpers ────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables and seed default data."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            username  TEXT    UNIQUE NOT NULL,
            password  TEXT    NOT NULL,
            role      TEXT    DEFAULT 'staff'
        );

        CREATE TABLE IF NOT EXISTS plans (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT    NOT NULL,
            price          REAL    NOT NULL,
            duration_days  INTEGER NOT NULL,
            features       TEXT
        );

        CREATE TABLE IF NOT EXISTS members (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name   TEXT    NOT NULL,
            email       TEXT    UNIQUE NOT NULL,
            phone       TEXT,
            join_date   TEXT    NOT NULL,
            expiry_date TEXT    NOT NULL,
            plan_id     INTEGER REFERENCES plans(id),
            status      TEXT    DEFAULT 'active',
            notes       TEXT
        );

        CREATE TABLE IF NOT EXISTS checkins (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id   INTEGER NOT NULL REFERENCES members(id),
            checkin_at  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS payments (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id    INTEGER NOT NULL REFERENCES members(id),
            plan_id      INTEGER REFERENCES plans(id),
            amount       REAL    NOT NULL,
            payment_date TEXT    NOT NULL,
            status       TEXT    DEFAULT 'paid'
        );
    """)

    # Seed admin user
    if not db.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
        db.execute(
            "INSERT INTO users (username, password, role) VALUES (?,?,?)",
            ("admin", generate_password_hash("admin123"), "admin"),
        )

    # Seed plans
    if not db.execute("SELECT 1 FROM plans").fetchone():
        plans = [
            ("Basic", 29.99, 30, "Gym access, Locker"),
            ("Premium", 59.99, 30, "Gym access, Locker, Group classes, Sauna"),
            ("Elite", 99.99, 30, "All Premium + Personal trainer, Nutrition plan, Priority booking"),
            ("Annual Basic", 299.99, 365, "Gym access, Locker"),
            ("Annual Elite", 999.99, 365, "All Elite features, Yearly discount"),
        ]
        db.executemany(
            "INSERT INTO plans (name, price, duration_days, features) VALUES (?,?,?,?)",
            plans,
        )

    db.commit()
    db.close()


# ─── Auth decorator ──────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ─── Auth routes ─────────────────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        db.close()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ─── Dashboard ───────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")

    total_members  = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    active_members = db.execute("SELECT COUNT(*) FROM members WHERE status='active'").fetchone()[0]
    expired_members= db.execute("SELECT COUNT(*) FROM members WHERE expiry_date < ? AND status='active'", (today,)).fetchone()[0]
    today_checkins = db.execute("SELECT COUNT(*) FROM checkins WHERE DATE(checkin_at)=?", (today,)).fetchone()[0]
    month_revenue  = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM payments WHERE strftime('%Y-%m', payment_date)=strftime('%Y-%m','now')"
    ).fetchone()[0]

    # Recent members
    recent_members = db.execute(
        "SELECT m.*, p.name as plan_name FROM members m LEFT JOIN plans p ON m.plan_id=p.id ORDER BY m.id DESC LIMIT 5"
    ).fetchall()

    # Today's check-ins
    recent_checkins = db.execute("""
        SELECT c.checkin_at, m.full_name FROM checkins c
        JOIN members m ON c.member_id=m.id
        ORDER BY c.checkin_at DESC LIMIT 8
    """).fetchall()

    # Monthly revenue for chart (last 6 months)
    revenue_data = [dict(r) for r in db.execute("""
        SELECT strftime('%Y-%m', payment_date) as month, SUM(amount) as total
        FROM payments
        GROUP BY month ORDER BY month DESC LIMIT 6
    """).fetchall()]

    # Plan distribution
    plan_dist = db.execute("""
        SELECT p.name, COUNT(m.id) as cnt
        FROM plans p LEFT JOIN members m ON m.plan_id=p.id AND m.status='active'
        GROUP BY p.id
    """).fetchall()

    db.close()
    return render_template("dashboard.html",
        today=today,
        total_members=total_members,
        active_members=active_members,
        expired_members=expired_members,
        today_checkins=today_checkins,
        month_revenue=month_revenue,
        recent_members=recent_members,
        recent_checkins=recent_checkins,
        revenue_data=list(reversed(revenue_data)),
        plan_dist=[dict(r) for r in plan_dist],
    )


# ─── Members ─────────────────────────────────────────────────────────────────

@app.route("/members")
@login_required
def members():
    db = get_db()
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    plan_filter = request.args.get("plan", "")
    today = datetime.now().strftime("%Y-%m-%d")

    query = """
        SELECT m.*, p.name as plan_name,
               CASE WHEN m.expiry_date < ? THEN 'expired' ELSE m.status END as computed_status
        FROM members m LEFT JOIN plans p ON m.plan_id=p.id
        WHERE 1=1
    """
    params = [today]

    if search:
        query += " AND (m.full_name LIKE ? OR m.email LIKE ? OR m.phone LIKE ?)"
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]
    if status:
        if status == "expired":
            query += " AND m.expiry_date < ?"
            params.append(today)
        else:
            query += " AND m.status=? AND m.expiry_date >= ?"
            params += [status, today]
    if plan_filter:
        query += " AND m.plan_id=?"
        params.append(plan_filter)

    query += " ORDER BY m.id DESC"
    all_members = db.execute(query, params).fetchall()
    plans = db.execute("SELECT * FROM plans").fetchall()
    db.close()
    return render_template("members.html", members=all_members, plans=plans,
                           today=today, search=search, status=status, plan_filter=plan_filter)


@app.route("/members/add", methods=["GET", "POST"])
@login_required
def add_member():
    db = get_db()
    plans = db.execute("SELECT * FROM plans").fetchall()
    if request.method == "POST":
        full_name = request.form["full_name"].strip()
        email     = request.form["email"].strip()
        phone     = request.form.get("phone", "").strip()
        plan_id   = request.form["plan_id"]
        notes     = request.form.get("notes", "").strip()
        join_date = datetime.now().strftime("%Y-%m-%d")

        plan = db.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        expiry_date = (datetime.now() + timedelta(days=plan["duration_days"])).strftime("%Y-%m-%d")

        try:
            db.execute(
                "INSERT INTO members (full_name,email,phone,join_date,expiry_date,plan_id,notes) VALUES (?,?,?,?,?,?,?)",
                (full_name, email, phone, join_date, expiry_date, plan_id, notes),
            )
            member_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            # Auto-record payment
            db.execute(
                "INSERT INTO payments (member_id,plan_id,amount,payment_date) VALUES (?,?,?,?)",
                (member_id, plan_id, plan["price"], join_date),
            )
            db.commit()
            flash(f"Member '{full_name}' added successfully!", "success")
            return redirect(url_for("members"))
        except sqlite3.IntegrityError:
            flash("Email already exists.", "danger")
        finally:
            db.close()
    else:
        db.close()
    return render_template("add_member.html", plans=plans)


@app.route("/members/<int:member_id>")
@login_required
def member_detail(member_id):
    db = get_db()
    member = db.execute(
        "SELECT m.*, p.name as plan_name, p.price as plan_price FROM members m LEFT JOIN plans p ON m.plan_id=p.id WHERE m.id=?",
        (member_id,)
    ).fetchone()
    if not member:
        flash("Member not found.", "danger")
        return redirect(url_for("members"))
    checkins = db.execute(
        "SELECT * FROM checkins WHERE member_id=? ORDER BY checkin_at DESC LIMIT 20", (member_id,)
    ).fetchall()
    payments = db.execute(
        "SELECT pay.*, p.name as plan_name FROM payments pay LEFT JOIN plans p ON pay.plan_id=p.id WHERE pay.member_id=? ORDER BY pay.payment_date DESC",
        (member_id,)
    ).fetchall()
    plans = db.execute("SELECT * FROM plans").fetchall()
    db.close()
    return render_template("member_detail.html", member=member, checkins=checkins,
                           payments=payments, plans=plans, today=datetime.now().strftime("%Y-%m-%d"))


@app.route("/members/<int:member_id>/edit", methods=["GET", "POST"])
@login_required
def edit_member(member_id):
    db = get_db()
    member = db.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    plans = db.execute("SELECT * FROM plans").fetchall()
    if not member:
        db.close()
        flash("Member not found.", "danger")
        return redirect(url_for("members"))
    if request.method == "POST":
        full_name   = request.form["full_name"].strip()
        email       = request.form["email"].strip()
        phone       = request.form.get("phone", "").strip()
        plan_id     = request.form["plan_id"]
        status      = request.form["status"]
        expiry_date = request.form["expiry_date"]
        notes       = request.form.get("notes", "").strip()
        try:
            db.execute(
                "UPDATE members SET full_name=?,email=?,phone=?,plan_id=?,status=?,expiry_date=?,notes=? WHERE id=?",
                (full_name, email, phone, plan_id, status, expiry_date, notes, member_id),
            )
            db.commit()
            flash("Member updated.", "success")
            return redirect(url_for("member_detail", member_id=member_id))
        except sqlite3.IntegrityError:
            flash("Email already in use by another member.", "danger")
        finally:
            db.close()
    else:
        db.close()
    return render_template("edit_member.html", member=member, plans=plans)


@app.route("/members/<int:member_id>/delete", methods=["POST"])
@login_required
def delete_member(member_id):
    db = get_db()
    db.execute("DELETE FROM checkins WHERE member_id=?", (member_id,))
    db.execute("DELETE FROM payments WHERE member_id=?", (member_id,))
    db.execute("DELETE FROM members WHERE id=?", (member_id,))
    db.commit()
    db.close()
    flash("Member deleted.", "success")
    return redirect(url_for("members"))


@app.route("/members/<int:member_id>/renew", methods=["POST"])
@login_required
def renew_member(member_id):
    db = get_db()
    plan_id = request.form["plan_id"]
    plan = db.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    member = db.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    today = datetime.now().strftime("%Y-%m-%d")
    # Extend from today or current expiry (whichever is later)
    base = max(today, member["expiry_date"])
    new_expiry = (datetime.strptime(base, "%Y-%m-%d") + timedelta(days=plan["duration_days"])).strftime("%Y-%m-%d")
    db.execute(
        "UPDATE members SET plan_id=?, expiry_date=?, status='active' WHERE id=?",
        (plan_id, new_expiry, member_id),
    )
    db.execute(
        "INSERT INTO payments (member_id,plan_id,amount,payment_date) VALUES (?,?,?,?)",
        (member_id, plan_id, plan["price"], today),
    )
    db.commit()
    db.close()
    flash(f"Membership renewed until {new_expiry}.", "success")
    return redirect(url_for("member_detail", member_id=member_id))


# ─── Check-ins ───────────────────────────────────────────────────────────────

@app.route("/checkins")
@login_required
def checkins():
    db = get_db()
    date_filter = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    rows = db.execute("""
        SELECT c.id, c.checkin_at, m.full_name, m.id as member_id, p.name as plan_name
        FROM checkins c
        JOIN members m ON c.member_id = m.id
        LEFT JOIN plans p ON m.plan_id = p.id
        WHERE DATE(c.checkin_at) = ?
        ORDER BY c.checkin_at DESC
    """, (date_filter,)).fetchall()
    db.close()
    return render_template("checkins.html", checkins=rows, date_filter=date_filter)


@app.route("/checkins/log", methods=["POST"])
@login_required
def log_checkin():
    db = get_db()
    identifier = request.form.get("identifier", "").strip()
    today = datetime.now().strftime("%Y-%m-%d")

    member = db.execute(
        "SELECT m.*, p.name as plan_name FROM members m LEFT JOIN plans p ON m.plan_id=p.id WHERE m.email=? OR m.id=?",
        (identifier, identifier if identifier.isdigit() else -1),
    ).fetchone()

    if not member:
        flash("Member not found. Check ID or email.", "danger")
    elif member["status"] != "active":
        flash(f"{member['full_name']}'s membership is inactive.", "warning")
    elif member["expiry_date"] < today:
        flash(f"{member['full_name']}'s membership expired on {member['expiry_date']}.", "warning")
    else:
        db.execute(
            "INSERT INTO checkins (member_id, checkin_at) VALUES (?, ?)",
            (member["id"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        db.commit()
        flash(f"✓ Check-in recorded for {member['full_name']} ({member['plan_name']}).", "success")
    db.close()
    return redirect(url_for("checkins"))


# ─── Plans ───────────────────────────────────────────────────────────────────

@app.route("/plans")
@login_required
def plans():
    db = get_db()
    all_plans = db.execute("""
        SELECT p.*, COUNT(m.id) as member_count
        FROM plans p LEFT JOIN members m ON m.plan_id=p.id AND m.status='active'
        GROUP BY p.id
    """).fetchall()
    db.close()
    return render_template("plans.html", plans=all_plans)


@app.route("/plans/add", methods=["POST"])
@login_required
def add_plan():
    db = get_db()
    name          = request.form["name"].strip()
    price         = float(request.form["price"])
    duration_days = int(request.form["duration_days"])
    features      = request.form.get("features", "").strip()
    db.execute(
        "INSERT INTO plans (name,price,duration_days,features) VALUES (?,?,?,?)",
        (name, price, duration_days, features),
    )
    db.commit()
    db.close()
    flash(f"Plan '{name}' created.", "success")
    return redirect(url_for("plans"))


@app.route("/plans/<int:plan_id>/delete", methods=["POST"])
@login_required
def delete_plan(plan_id):
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM members WHERE plan_id=?", (plan_id,)).fetchone()[0]
    if count > 0:
        flash("Cannot delete plan with active members.", "danger")
    else:
        db.execute("DELETE FROM plans WHERE id=?", (plan_id,))
        db.commit()
        flash("Plan deleted.", "success")
    db.close()
    return redirect(url_for("plans"))


# ─── Payments ────────────────────────────────────────────────────────────────

@app.route("/payments")
@login_required
def payments():
    db = get_db()
    rows = db.execute("""
        SELECT pay.*, m.full_name, p.name as plan_name
        FROM payments pay
        JOIN members m ON pay.member_id = m.id
        LEFT JOIN plans p ON pay.plan_id = p.id
        ORDER BY pay.payment_date DESC
        LIMIT 100
    """).fetchall()
    total = db.execute("SELECT COALESCE(SUM(amount),0) FROM payments").fetchone()[0]
    db.close()
    return render_template("payments.html", payments=rows, total=total)


# ─── API ─────────────────────────────────────────────────────────────────────

@app.route("/api/member-search")
@login_required
def api_member_search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    db = get_db()
    rows = db.execute(
        "SELECT id, full_name, email FROM members WHERE full_name LIKE ? OR email LIKE ? LIMIT 8",
        (f"%{q}%", f"%{q}%"),
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/stats")
@login_required
def api_stats():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    checkins_today = db.execute(
        "SELECT COUNT(*) FROM checkins WHERE DATE(checkin_at)=?", (today,)
    ).fetchone()[0]
    db.close()
    return jsonify({"checkins_today": checkins_today})


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not os.path.exists(DATABASE):
        init_db()
    else:
        init_db()   # safe to re-run (CREATE IF NOT EXISTS)
    print("MY APP IS STARTING")
    app.run(debug=True)
