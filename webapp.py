import os
import jwt
import psycopg2
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template, redirect
from functools import wraps
from apscheduler.schedulers.background import BackgroundScheduler
import uuid
import logging

load_dotenv()
app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
RENDER_URL = os.getenv("RENDER_URL")
ADMIN_ID = os.getenv("ADMIN_ID")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- Database helpers --------------------
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def db_fetch_one(query, params=()):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def db_fetch_all(query, params=()):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def db_execute(query, params=(), fetch_id=False):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    if fetch_id:
        try:
            id = cur.fetchone()[0]
        except:
            id = None
    conn.commit()
    cur.close()
    conn.close()
    return id if fetch_id else True

# -------------------- Authentication --------------------
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.args.get("token") or request.headers.get("Authorization")
        if not token:
            return jsonify({"error": "Missing token"}), 401
        try:
            data = jwt.decode(token, app.secret_key, algorithms=["HS256"])
            request.user_id = data["user_id"]
        except:
            return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated

def generate_token(user_id):
    return jwt.encode({"user_id": str(user_id), "exp": datetime.utcnow() + timedelta(days=30)}, app.secret_key)

def send_telegram_notification(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Failed to send notification to {chat_id}: {e}")

# -------------------- Routes --------------------
@app.route("/")
def index():
    return redirect("/recovery")

@app.route("/recovery")
def recovery():
    token = request.args.get("token")
    if not token:
        return "Missing token. Please open via Telegram bot.", 400
    return render_template("recovery_dashboard.html", token=token)

# -------------------- API Endpoints --------------------
@app.route("/api/user/me", methods=["GET"])
@require_auth
def get_user():
    row = db_fetch_one("SELECT user_id, anonymous_name, recovery_role, recovery_streak, recovery_last_checkin, recovery_notifications FROM users WHERE user_id = %s", (request.user_id,))
    if not row:
        return jsonify({"error": "User not found"}), 404
    return jsonify({
        "user_id": row[0],
        "name": row[1],
        "role": row[2],
        "streak": row[3],
        "last_checkin": str(row[4]) if row[4] else None,
        "notifications": row[5]
    })

@app.route("/api/checkin", methods=["POST"])
@require_auth
def checkin():
    data = request.json
    status = data.get("status")
    today = datetime.now().date()
    last_row = db_fetch_one("SELECT recovery_last_checkin FROM users WHERE user_id = %s", (request.user_id,))
    last = last_row[0] if last_row else None
    if last == today:
        return jsonify({"error": "Already checked in today"}), 400
    streak = 0
    if status == "yes":
        if last and (today - last).days == 1:
            cur = db_fetch_one("SELECT recovery_streak FROM users WHERE user_id = %s", (request.user_id,))[0]
            streak = cur + 1
        else:
            streak = 1
    else:
        streak = 0
    db_execute("UPDATE users SET recovery_streak = %s, recovery_last_checkin = %s WHERE user_id = %s", (streak, today, request.user_id))
    return jsonify({"streak": streak})

@app.route("/api/daily-verse", methods=["GET"])
@require_auth
def daily_verse():
    verses = [
        ("Psalm 51:10", "Create in me a clean heart, O God, renew a right spirit within me."),
        ("1 Corinthians 10:13", "God is faithful, and he will not let you be tempted beyond your ability."),
        ("Romans 6:14", "For sin will have no dominion over you, since you are not under law but under grace.")
    ]
    import random
    ref, text = random.choice(verses)
    return jsonify({"reference": ref, "text": text})

@app.route("/api/reflection", methods=["POST"])
@require_auth
def save_reflection():
    data = request.json
    verse = data.get("verse_text")
    reflection = data.get("reflection_text")
    voice_url = data.get("voice_file_url")
    db_execute("INSERT INTO recovery_reflections (user_id, verse_text, reflection_text, voice_file_url) VALUES (%s, %s, %s, %s)",
               (request.user_id, verse, reflection, voice_url))
    return jsonify({"success": True})

@app.route("/api/mentor/messages", methods=["GET"])
@require_auth
def get_messages():
    mentor_row = db_fetch_one("SELECT id FROM recovery_mentorships WHERE (user_id = %s OR mentor_id = %s) AND status = 'active'", (request.user_id, request.user_id))
    if not mentor_row:
        return jsonify([])
    mentorship_id = mentor_row[0]
    rows = db_fetch_all("SELECT sender_id, content, timestamp FROM recovery_messages WHERE mentorship_id = %s ORDER BY timestamp", (mentorship_id,))
    messages = [{"sender_id": r[0], "content": r[1], "timestamp": str(r[2])} for r in rows]
    return jsonify(messages)

@app.route("/api/mentor/message", methods=["POST"])
@require_auth
def send_message():
    data = request.json
    receiver_id = data.get("receiver_id")
    content = data.get("content")
    mentorship = db_fetch_one("SELECT id FROM recovery_mentorships WHERE (user_id = %s AND mentor_id = %s) OR (user_id = %s AND mentor_id = %s)",
                               (request.user_id, receiver_id, receiver_id, request.user_id))
    if not mentorship:
        return jsonify({"error": "No active mentorship"}), 400
    mentorship_id = mentorship[0]
    db_execute("INSERT INTO recovery_messages (mentorship_id, sender_id, receiver_id, content) VALUES (%s, %s, %s, %s)",
               (mentorship_id, request.user_id, receiver_id, content))
    user_row = db_fetch_one("SELECT anonymous_name, recovery_notifications FROM users WHERE user_id = %s", (receiver_id,))
    if user_row and user_row[1]:
        send_telegram_notification(receiver_id, f"📩 New message from your mentor/mentee. Open the app: {RENDER_URL}/recovery?token={generate_token(receiver_id)}")
    return jsonify({"success": True})

@app.route("/api/sessions", methods=["GET"])
@require_auth
def get_sessions():
    rows = db_fetch_all("SELECT id, title, description, scheduled_time, jitsi_room FROM recovery_live_sessions WHERE scheduled_time > NOW() ORDER BY scheduled_time")
    sessions = [{"id": r[0], "title": r[1], "description": r[2], "time": str(r[3]), "room": r[4]} for r in rows]
    return jsonify(sessions)

@app.route("/api/sessions", methods=["POST"])
@require_auth
def create_session():
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s", (request.user_id,))
    if user[0] not in ('mentor', 'admin'):
        return jsonify({"error": "Only mentors can create sessions"}), 403
    data = request.json
    title = data.get("title")
    description = data.get("description")
    scheduled_time = data.get("scheduled_time")
    jitsi_room = f"recovery-{uuid.uuid4().hex[:8]}"
    db_execute("INSERT INTO recovery_live_sessions (title, description, host_id, scheduled_time, jitsi_room) VALUES (%s, %s, %s, %s, %s)",
               (title, description, request.user_id, scheduled_time, jitsi_room))
    return jsonify({"success": True, "room": jitsi_room})

@app.route("/api/sessions/<int:session_id>/join", methods=["GET"])
@require_auth
def join_session(session_id):
    row = db_fetch_one("SELECT jitsi_room FROM recovery_live_sessions WHERE id = %s", (session_id,))
    if not row:
        return jsonify({"error": "Session not found"}), 404
    return jsonify({"jitsi_url": f"https://meet.jit.si/{row[0]}"})

@app.route("/api/mentees", methods=["GET"])
@require_auth
def get_mentees():
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s", (request.user_id,))
    if user[0] != 'mentor':
        return jsonify({"error": "Only mentors can view mentees"}), 403
    rows = db_fetch_all("SELECT u.user_id, u.anonymous_name, u.recovery_streak FROM users u JOIN recovery_mentorships m ON u.user_id = m.user_id WHERE m.mentor_id = %s AND m.status = 'active'", (request.user_id,))
    mentees = [{"id": r[0], "name": r[1], "streak": r[2]} for r in rows]
    return jsonify(mentees)

@app.route("/api/admin/users", methods=["GET"])
@require_auth
def admin_users():
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s", (request.user_id,))
    if user[0] != 'admin':
        return jsonify({"error": "Admin only"}), 403
    rows = db_fetch_all("SELECT user_id, anonymous_name, recovery_role FROM users")
    users = [{"id": r[0], "name": r[1], "role": r[2]} for r in rows]
    return jsonify(users)

@app.route("/api/admin/assign-mentor", methods=["POST"])
@require_auth
def assign_mentor():
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s", (request.user_id,))
    if user[0] != 'admin':
        return jsonify({"error": "Admin only"}), 403
    data = request.json
    mentee_id = data.get("user_id")
    mentor_id = data.get("mentor_id")
    exists = db_fetch_one("SELECT id FROM recovery_mentorships WHERE user_id = %s AND mentor_id = %s", (mentee_id, mentor_id))
    if not exists:
        db_execute("INSERT INTO recovery_mentorships (user_id, mentor_id, status) VALUES (%s, %s, 'active')", (mentee_id, mentor_id))
    return jsonify({"success": True})

@app.route("/api/admin/broadcast", methods=["POST"])
@require_auth
def broadcast():
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s", (request.user_id,))
    if user[0] != 'admin':
        return jsonify({"error": "Admin only"}), 403
    data = request.json
    message = data.get("message")
    rows = db_fetch_all("SELECT user_id FROM users WHERE recovery_notifications = TRUE")
    for row in rows:
        send_telegram_notification(row[0], f"📢 Admin announcement:\n\n{message}\n\n{RENDER_URL}/recovery?token={generate_token(row[0])}")
    return jsonify({"success": True})

# -------------------- Scheduler with error handling --------------------
def check_upcoming_sessions():
    try:
        now = datetime.now()
        reminder_time = now + timedelta(minutes=15)
        rows = db_fetch_all(
            "SELECT id, title, scheduled_time, jitsi_room FROM recovery_live_sessions WHERE scheduled_time BETWEEN %s AND %s",
            (now, reminder_time)
        )
        if not rows:
            return
        users = db_fetch_all("SELECT user_id FROM users WHERE recovery_notifications = TRUE")
        for row in rows:
            for u in users:
                msg = f"🔔 Live session in 15 minutes!\n\nTitle: {row[1]}\nJoin: {RENDER_URL}/recovery/sessions/{row[0]}"
                send_telegram_notification(u[0], msg)
    except Exception as e:
        logger.error(f"Error in check_upcoming_sessions: {e}")

try:
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=check_upcoming_sessions, trigger="interval", minutes=1)
    scheduler.start()
    logger.info("✅ Session reminder scheduler started.")
except Exception as e:
    logger.error(f"❌ Failed to start scheduler: {e}")

# -------------------- Run Flask --------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)), debug=False)
