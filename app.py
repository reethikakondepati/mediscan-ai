import os
import sqlite3
import json
import sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import pdfplumber
from PIL import Image
import pytesseract
from openai import OpenAI
BASE_DIR = os.getcwd()   # works on Render
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "mediscan.db")
from pdf2image import convert_from_path


# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DB_PATH    = os.path.join(BASE_DIR, "database", "mediscan.db")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "mediscan_secret_key_change_in_production"

# OpenRouter client
client = OpenAI(
    api_key=os.environ.get("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)

ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "txt"}

# ─────────────────────────────────────────────
#  ADMIN CREDENTIALS  (change these!)
# ─────────────────────────────────────────────
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin@mediscan123")

# ─────────────────────────────────────────────
#  DATABASE SETUP
# ─────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            username  TEXT    UNIQUE NOT NULL,
            email     TEXT    UNIQUE NOT NULL,
            password  TEXT    NOT NULL,
            created_at TEXT   DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS reports (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            filename        TEXT,
            file_path       TEXT,
            report_text     TEXT,
            abnormal_findings   TEXT,
            simple_explanation  TEXT,
            possible_conditions TEXT,
            severity            TEXT,
            next_steps          TEXT,
            disclaimer          TEXT,
            raw_response        TEXT,
            severity_level      INTEGER DEFAULT 0,
            uploaded_at         TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    """)
    conn.commit()
    conn.close()


init_db()


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Decorator — only allows access when logged in as admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Admin access required.", "danger")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


def extract_text(filepath):
    ext = filepath.rsplit(".", 1)[1].lower()
    try:
        if ext == "pdf":
            text = ""
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if isinstance(t, str) and t.strip():
                        text += t + "\n"
            if text.strip():
                return text
            
            images = convert_from_path(filepath)
            ocr_text = ""
            for img in images:
                ocr_text += pytesseract.image_to_string(img, config="--psm 6") + "\n"
            return ocr_text or ""

        elif ext in ("jpg", "jpeg", "png"):
            img = Image.open(filepath)
            return pytesseract.image_to_string(img, config="--psm 6") or ""

        elif ext == "txt":
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                return f.read() or ""

    except Exception as e:
        print("Text extraction error:", e)
        return ""
    return ""


def parse_severity_level(severity_text: str) -> int:
    if not severity_text:
        return 0
    t = severity_text.lower()
    if any(k in t for k in ["critical", "severe", "emergency", "immediate", "urgent"]):
        return 3
    if any(k in t for k in ["moderate", "significant", "concerning"]):
        return 2
    if any(k in t for k in ["mild", "low", "minor", "normal"]):
        return 1
    return 0


def analyze_with_ai(text: str) -> dict:
    prompt = f"""You are a medical AI assistant. Analyze the following medical report and return a structured JSON response.

Report:
\"\"\"
{text[:6000]}
\"\"\"

Return ONLY valid JSON (no markdown) with these exact keys:
{{
  "abnormal_findings": "...",
  "simple_explanation": "...",
  "possible_conditions": "...",
  "severity": "...",
  "next_steps": "...",
  "disclaimer": "This analysis is AI-generated for informational purposes only. Not a medical diagnosis. Always consult a qualified doctor.",
  "severity_level": <integer 0-3 where 0=unknown,1=mild,2=moderate,3=severe/critical>
}}
"""
    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        data = json.loads(raw)
    except Exception:
        data = {
            "abnormal_findings": "", "simple_explanation": "",
            "possible_conditions": "", "severity": "",
            "next_steps": "", "disclaimer": "", "raw": raw, "severity_level": 0,
        }
    data["raw"] = raw
    return data


def comparative_analysis_with_ai(prev_summaries: list, current: dict) -> str:
    prev_text = "\n\n---\n\n".join(
        f"Report {i+1} ({r['uploaded_at']}):\n"
        f"Findings: {r['abnormal_findings']}\n"
        f"Conditions: {r['possible_conditions']}\n"
        f"Severity: {r['severity']}"
        for i, r in enumerate(prev_summaries)
    )
    current_text = (
        f"Findings: {current.get('abnormal_findings','')}\n"
        f"Conditions: {current.get('possible_conditions','')}\n"
        f"Severity: {current.get('severity','')}"
    )
    prompt = f"""You are a medical AI assistant doing a comparative health analysis.

Previous Reports:
{prev_text}

Latest Report:
{current_text}

Provide a clear, patient-friendly comparative analysis covering:
1. What has improved compared to previous reports
2. What has worsened or is new
3. Overall health trend (improving / stable / declining)
4. Key recommendations based on the trend

Be concise but thorough. Use plain language."""

    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


# ─────────────────────────────────────────────
#  AUTH ROUTES  (user)
# ─────────────────────────────────────────────
@app.route("/")
def home():
    return render_template("home.html", logged_in="user_id" in session,
                           username=session.get("username", ""))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        confirm  = request.form.get("confirm_password", "").strip()

        if not all([username, email, password, confirm]):
            return render_template("register.html", error="All fields are required.")
        if password != confirm:
            return render_template("register.html", error="Passwords do not match.")
        if len(password) < 6:
            return render_template("register.html", error="Password must be at least 6 characters.")
        # Prevent using the reserved admin username
        if username.lower() == ADMIN_USERNAME.lower():
            return render_template("register.html", error="That username is reserved. Please choose another.")

        try:
            conn = get_db()
            conn.execute(
                "INSERT INTO users (username, email, password) VALUES (?,?,?)",
                (username, email, password),
            )
            conn.commit()
            conn.close()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            return render_template("register.html", error="Username or email already exists.")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND password=?", (username, password)
        ).fetchone()
        conn.close()

        if user:
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            flash(f"Welcome back, {user['username']}! 👋", "success")
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Invalid username or password.")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))


# ─────────────────────────────────────────────
#  USER DASHBOARD
# ─────────────────────────────────────────────
@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE id=?", (session["user_id"],)
    ).fetchone()

    if user is None:
        conn.close()
        session.clear()
        flash("Your session has expired or the account no longer exists. Please log in again.", "warning")
        return redirect(url_for("login"))

    reports = conn.execute(
        "SELECT * FROM reports WHERE user_id=? ORDER BY uploaded_at DESC",
        (session["user_id"],)
    ).fetchall()
    conn.close()

    total    = len(reports)
    critical = sum(1 for r in reports if r["severity_level"] == 3)
    moderate = sum(1 for r in reports if r["severity_level"] == 2)
    mild     = sum(1 for r in reports if r["severity_level"] == 1)

    return render_template("dashboard.html",
                           user=user, reports=reports,
                           total=total, critical=critical,
                           moderate=moderate, mild=mild)


# ─────────────────────────────────────────────
#  ANALYZE  (user)
# ─────────────────────────────────────────────
@app.route("/analyze", methods=["GET", "POST"])
@login_required
def analyze():
    if request.method == "POST":
        file = request.files.get("report")
        if not file or not file.filename:
            return render_template("analyze.html", error="Please select a file to upload.")
        if not allowed_file(file.filename):
            return render_template("analyze.html", error="Unsupported file type.")

        filename  = file.filename
        save_path = os.path.join(UPLOAD_DIR, filename)
        file.save(save_path)

        text = extract_text(save_path)
        if text is None:
            text = ""
        elif not isinstance(text, str):
            text = str(text)
        text = text.strip()

        if not text:
            return render_template("analyze.html", error="Could not extract text from the file.")

        result    = analyze_with_ai(text)
        sev_level = result.get("severity_level") or parse_severity_level(result.get("severity", ""))

        conn = get_db()
        conn.execute(
            """INSERT INTO reports
               (user_id, filename, file_path, report_text,
                abnormal_findings, simple_explanation, possible_conditions,
                severity, next_steps, disclaimer, raw_response, severity_level)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(session["user_id"]),
                str(filename), str(save_path), str(text),
                str(result.get("abnormal_findings", "")),
                str(result.get("simple_explanation", "")),
                str(result.get("possible_conditions", "")),
                str(result.get("severity", "")),
                str(result.get("next_steps", "")),
                str(result.get("disclaimer", "")),
                str(result.get("raw", "")),
                int(sev_level),
            )
        )
        conn.commit()
        report_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        result["filename"]       = filename
        result["severity_level"] = sev_level
        result["report_id"]      = report_id
        return render_template("result.html", data=result)

    return render_template("analyze.html")


# ─────────────────────────────────────────────
#  VIEW SINGLE REPORT  (user)
# ─────────────────────────────────────────────
@app.route("/report/<int:report_id>")
@login_required
def view_report(report_id):
    conn = get_db()
    report = conn.execute(
        "SELECT * FROM reports WHERE id=? AND user_id=?",
        (report_id, session["user_id"])
    ).fetchone()
    conn.close()

    if not report:
        flash("Report not found.", "danger")
        return redirect(url_for("dashboard"))

    data = dict(report)
    data["raw"] = data.get("raw_response", "")
    return render_template("result.html", data=data)


# ─────────────────────────────────────────────
#  COMPARATIVE ANALYSIS  (AJAX)
# ─────────────────────────────────────────────
@app.route("/compare/<int:report_id>", methods=["GET"])
@login_required
def compare(report_id):
    conn = get_db()
    current = conn.execute(
        "SELECT * FROM reports WHERE id=? AND user_id=?",
        (report_id, session["user_id"])
    ).fetchone()

    if not current:
        return jsonify({"error": "Report not found"}), 404

    previous = conn.execute(
        """SELECT abnormal_findings, possible_conditions, severity, uploaded_at
           FROM reports WHERE user_id=? AND id != ?
           ORDER BY uploaded_at DESC LIMIT 5""",
        (session["user_id"], report_id)
    ).fetchall()
    conn.close()

    if not previous:
        return jsonify({"error": "No previous reports to compare with. Upload at least 2 reports to enable comparison."}), 400

    analysis = comparative_analysis_with_ai(
        [dict(r) for r in previous], dict(current)
    )
    return jsonify({"analysis": analysis})


# ─────────────────────────────────────────────
#  DELETE REPORT  (user)
# ─────────────────────────────────────────────
@app.route("/report/<int:report_id>/delete", methods=["POST"])
@login_required
def delete_report(report_id):
    conn = get_db()
    conn.execute(
        "DELETE FROM reports WHERE id=? AND user_id=?",
        (report_id, session["user_id"])
    )
    conn.commit()
    conn.close()
    flash("Report deleted.", "info")
    return redirect(url_for("dashboard"))


# ─────────────────────────────────────────────
#  MEDICAL CHATBOT  (AJAX)
# ─────────────────────────────────────────────
@app.route("/chat", methods=["POST"])
@login_required
def chat():
    data         = request.get_json()
    user_message = (data.get("message") or "").strip()
    history      = data.get("history") or []

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    messages = [
        {
            "role": "system",
            "content": (
                "You are MediBot, a helpful and friendly medical AI assistant built into MediScan AI. "
                "You help users understand medical conditions, symptoms, medications, lab values, "
                "treatment options, and general health questions in simple, clear language. "
                "Be warm, empathetic, and concise (under 200 words unless more detail is genuinely needed). "
                "ALWAYS end with a one-line reminder: your answers are informational only and the user "
                "should consult a qualified doctor for personal medical advice. "
                "Never diagnose. Never prescribe specific medications."
            )
        }
    ]
    for turn in history[-6:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=messages,
            temperature=0.5,
            max_tokens=400,
        )
        return jsonify({"reply": response.choices[0].message.content.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═════════════════════════════════════════════
#  ADMIN — LOGIN / LOGOUT
# ═════════════════════════════════════════════
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    # Already logged in as admin → go to admin dashboard
    if session.get("is_admin"):
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session.clear()                    # wipe any user session first
            session["is_admin"]       = True
            session["admin_username"] = ADMIN_USERNAME
            flash("Welcome, Admin! 🛡️", "success")
            return redirect(url_for("admin_dashboard"))

        return render_template("admin_login.html", error="Invalid admin credentials.")

    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    flash("Admin logged out.", "info")
    return redirect(url_for("admin_login"))


# ─────────────────────────────────────────────
#  ADMIN — DASHBOARD  (overview of all users)
# ─────────────────────────────────────────────
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    conn = get_db()

    users = conn.execute(
        "SELECT * FROM users ORDER BY created_at DESC"
    ).fetchall()

    # Attach report stats per user
    users_data = []
    for u in users:
        reports = conn.execute(
            "SELECT * FROM reports WHERE user_id=? ORDER BY uploaded_at DESC",
            (u["id"],)
        ).fetchall()
        users_data.append({
            "user":     dict(u),
            "reports":  [dict(r) for r in reports],
            "total":    len(reports),
            "critical": sum(1 for r in reports if r["severity_level"] == 3),
            "moderate": sum(1 for r in reports if r["severity_level"] == 2),
            "mild":     sum(1 for r in reports if r["severity_level"] == 1),
        })

    # Platform totals
    total_users   = len(users)
    total_reports = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    total_critical= conn.execute(
        "SELECT COUNT(*) FROM reports WHERE severity_level=3"
    ).fetchone()[0]

    conn.close()

    return render_template(
        "admin_dashboard.html",
        users_data=users_data,
        total_users=total_users,
        total_reports=total_reports,
        total_critical=total_critical,
    )


# ─────────────────────────────────────────────
#  ADMIN — VIEW ONE USER'S FULL REPORT LIST
# ─────────────────────────────────────────────
@app.route("/admin/user/<int:user_id>")
@admin_required
def admin_view_user(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        conn.close()
        flash("User not found.", "danger")
        return redirect(url_for("admin_dashboard"))

    reports = conn.execute(
        "SELECT * FROM reports WHERE user_id=? ORDER BY uploaded_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()

    total    = len(reports)
    critical = sum(1 for r in reports if r["severity_level"] == 3)
    moderate = sum(1 for r in reports if r["severity_level"] == 2)
    mild     = sum(1 for r in reports if r["severity_level"] == 1)

    return render_template(
        "admin_user_detail.html",
        user=dict(user), reports=reports,
        total=total, critical=critical, moderate=moderate, mild=mild
    )


# ─────────────────────────────────────────────
#  ADMIN — VIEW ONE REPORT  (any user)
# ─────────────────────────────────────────────
@app.route("/admin/report/<int:report_id>")
@admin_required
def admin_view_report(report_id):
    conn = get_db()
    report = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    conn.close()

    if not report:
        flash("Report not found.", "danger")
        return redirect(url_for("admin_dashboard"))

    data = dict(report)
    data["raw"] = data.get("raw_response", "")
    # Pass flag so result.html knows it was opened by admin
    data["admin_view"] = True
    return render_template("result.html", data=data)


# ─────────────────────────────────────────────
#  ADMIN — DELETE A USER  (+ all their reports)
# ─────────────────────────────────────────────
@app.route("/admin/user/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    conn = get_db()
    conn.execute("DELETE FROM reports WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    flash("User and all their reports have been deleted.", "info")
    return redirect(url_for("admin_dashboard"))


# ─────────────────────────────────────────────
#  ADMIN — DELETE A SINGLE REPORT
# ─────────────────────────────────────────────
@app.route("/admin/report/<int:report_id>/delete", methods=["POST"])
@admin_required
def admin_delete_report(report_id):
    conn = get_db()
    # Find user_id so we can redirect back to their detail page
    row = conn.execute("SELECT user_id FROM reports WHERE id=?", (report_id,)).fetchone()
    user_id = row["user_id"] if row else None
    conn.execute("DELETE FROM reports WHERE id=?", (report_id,))
    conn.commit()
    conn.close()
    flash("Report deleted.", "info")
    if user_id:
        return redirect(url_for("admin_view_user", user_id=user_id))
    return redirect(url_for("admin_dashboard"))


# ─────────────────────────────────────────────
#  ADMIN — ANALYZE  (same as user analyze)
# ─────────────────────────────────────────────
@app.route("/admin/analyze", methods=["GET", "POST"])
@admin_required
def admin_analyze():
    """Admin can upload & analyze a report — result is NOT saved to any user account."""
    if request.method == "POST":
        file = request.files.get("report")
        if not file or not file.filename:
            return render_template("admin_analyze.html", error="Please select a file.")
        if not allowed_file(file.filename):
            return render_template("admin_analyze.html", error="Unsupported file type.")

        filename  = file.filename
        save_path = os.path.join(UPLOAD_DIR, "admin_" + filename)
        file.save(save_path)

        text = extract_text(save_path)
        if text is None:
            text = ""
        elif not isinstance(text, str):
            text = str(text)
        text = text.strip()

        if not text:
            return render_template("admin_analyze.html", error="Could not extract text from the file.")

        result    = analyze_with_ai(text)
        sev_level = result.get("severity_level") or parse_severity_level(result.get("severity", ""))

        result["filename"]       = filename
        result["severity_level"] = sev_level
        result["admin_view"]     = True   # hides "save to dashboard" links in result.html
        return render_template("result.html", data=result)

    return render_template("admin_analyze.html")


# ─────────────────────────────────────────────
#  ADMIN — CHATBOT  (same /chat endpoint works
#  because admin session is active; just reuse)
# ─────────────────────────────────────────────
@app.route("/admin/chat", methods=["POST"])
@admin_required
def admin_chat():
    data         = request.get_json()
    user_message = (data.get("message") or "").strip()
    history      = data.get("history") or []

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    messages = [
        {
            "role": "system",
            "content": (
                "You are MediBot, a medical AI assistant. "
                "Answer medical questions clearly and concisely. "
                "Always remind the user that answers are informational only."
            )
        }
    ]
    for turn in history[-6:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=messages,
            temperature=0.5,
            max_tokens=400,
        )
        return jsonify({"reply": response.choices[0].message.content.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    app.run()