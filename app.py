import os
import jwt
import psycopg2
import requests
import logging
import uuid
import threading
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, render_template, redirect
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

# Telegram imports
from telegram import (
    Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, MenuButtonWebApp
)
from telegram.ext import Application, CommandHandler, ContextTypes

# Load environment
load_dotenv()

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("SECRET_KEY")

# Constants
DATABASE_URL = os.getenv("DATABASE_URL")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
RENDER_URL = os.getenv("RENDER_URL", "https://anti-porn.onrender.com")
ADMIN_ID = os.getenv("ADMIN_ID")
SECRET_KEY = app.secret_key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- Database Helpers --------------------

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
    res = None
    if fetch_id:
        try:
            res = cur.fetchone()[0]
        except:
            res = None
    conn.commit()
    cur.close()
    conn.close()
    return res if fetch_id else True

def init_db_types():
    """Migrate all ID columns to TEXT and add new registration columns."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Migrate IDs
        cur.execute("ALTER TABLE users ALTER COLUMN user_id TYPE TEXT USING user_id::text")
        cur.execute("ALTER TABLE recovery_reflections ALTER COLUMN user_id TYPE TEXT USING user_id::text")
        cur.execute("ALTER TABLE recovery_mentorships ALTER COLUMN user_id TYPE TEXT USING user_id::text")
        cur.execute("ALTER TABLE recovery_mentorships ALTER COLUMN mentor_id TYPE TEXT USING mentor_id::text")
        cur.execute("ALTER TABLE recovery_messages ALTER COLUMN sender_id TYPE TEXT USING sender_id::text")
        cur.execute("ALTER TABLE recovery_messages ALTER COLUMN receiver_id TYPE TEXT USING receiver_id::text")
        cur.execute("ALTER TABLE recovery_live_sessions ALTER COLUMN host_id TYPE TEXT USING host_id::text")
        
        # Add new columns if they don't exist
        cols = {
            "real_name": "TEXT",
            "sex": "TEXT",
            "age": "INT",
            "educational_level": "TEXT",
            "addiction_year": "TEXT",
            "longest_free_streak": "INT DEFAULT 0",
            "profile_complete": "BOOLEAN DEFAULT FALSE",
            "work_status": "TEXT",
            "mentorship_experience_years": "INT DEFAULT 0",
            "professional_training": "TEXT",
            "self_recovery_testimony": "TEXT",
            "bio": "TEXT"
        }
        for col, dtype in cols.items():
            cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {dtype}")
            
        cur.execute("ALTER TABLE recovery_mentorships ALTER COLUMN status SET DEFAULT 'pending'")
        
        conn.commit()
        logger.info("✅ Database migrations successful.")
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"⚠️ Database migration note: {e}")

# Run migrations
init_db_types()

# -------------------- Authentication --------------------

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.args.get("token") or request.headers.get("Authorization")
        if not token:
            return jsonify({"error": "Missing token"}), 401
        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            request.user_id = str(data["user_id"])
        except:
            return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated

def generate_token(user_id):
    return jwt.encode({"user_id": str(user_id), "exp": datetime.utcnow() + timedelta(days=30)}, SECRET_KEY, algorithm="HS256")

def send_telegram_notification(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Failed to send notification to {chat_id}: {e}")

# -------------------- Flask Routes --------------------

@app.after_request
def add_header(response):
    if response.mimetype == 'text/html':
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, post-check=0, pre-check=0, max-age=0'
    elif response.mimetype == 'application/json':
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
    return response

@app.route("/ping", methods=['GET', 'HEAD'])
def ping():
    return jsonify({"status": "ok", "message": "OK"}), 200

@app.route("/")
def index():
    return redirect("/recovery")

@app.route("/landing")
def landing():
    token = request.args.get("token")
    if not token: return "Missing token", 400
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        u_id = str(data.get("user_id"))
        if u_id == str(ADMIN_ID):
            return redirect(f"/recovery?token={token}")
        
        # Check if user already completed profile
        row = db_fetch_one("SELECT profile_complete FROM users WHERE user_id = %s::text", (u_id,))
        if row and row[0]:
            return redirect(f"/recovery?token={token}")
    except:
        pass
    return render_template("landing.html", token=token)

@app.route("/register/user")
def user_reg_page():
    token = request.args.get("token")
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        if str(data.get("user_id")) == str(ADMIN_ID):
            return redirect(f"/recovery?token={token}")
    except:
        pass
    return render_template("user_registration.html", token=token)

@app.route("/register/mentor")
def mentor_reg_page():
    token = request.args.get("token")
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        if str(data.get("user_id")) == str(ADMIN_ID):
            return redirect(f"/recovery?token={token}")
    except:
        pass
    return render_template("mentor_registration.html", token=token)

@app.route("/recovery")
def recovery():
    token = request.args.get("token")
    if not token:
        return "Missing token. Please open via Telegram bot.", 400
    
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        u_id = str(data["user_id"])
        
        # Admin is always allowed
        if u_id == str(ADMIN_ID):
            return render_template("recovery_dashboard.html", token=token)
            
        row = db_fetch_one("SELECT profile_complete FROM users WHERE user_id = %s::text", (u_id,))
        if not row or not row[0]:
            return redirect(f"/landing?token={token}")
    except Exception as e:
        logger.error(f"Recovery route error: {e}")
        return redirect(f"/landing?token={token}")
        
    return render_template("recovery_dashboard.html", token=token)

@app.route("/admin")
def admin_page():
    token = request.args.get("token")
    if not token: return "Unauthorized", 401
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        if str(data.get("user_id")) != str(ADMIN_ID):
            return "Unauthorized", 403
    except:
        return "Unauthorized", 401
    return render_template("admin_dashboard.html", token=token)

@app.route("/api/user/me", methods=["GET"])
@require_auth
def get_user():
    row = db_fetch_one("""
        SELECT user_id, anonymous_name, recovery_role, recovery_streak, recovery_last_checkin, recovery_notifications, 
               profile_complete, sex, age, educational_level, addiction_year, longest_free_streak,
               real_name, work_status, mentorship_experience_years, professional_training, self_recovery_testimony, bio
        FROM users WHERE user_id = %s::text
    """, (request.user_id,))
    if not row:
        return jsonify({"error": "User not found"}), 404
    return jsonify({
        "user_id": row[0], "name": row[1], "role": row[2], "streak": row[3],
        "last_checkin": str(row[4]) if row[4] else None, "notifications": row[5],
        "profile_complete": row[6], "sex": row[7], "age": row[8], "education": row[9],
        "addiction_year": row[10], "longest_streak": row[11], "real_name": row[12],
        "work_status": row[13], "mentor_years": row[14], "training": row[15], "testimony": row[16], "bio": row[17]
    })

@app.route("/api/register/user", methods=["POST"])
@require_auth
def register_user_api():
    if str(request.user_id) == str(ADMIN_ID):
        return jsonify({"error": "Admin cannot register"}), 403
    data = request.json
    real_name = data.get("real_name")
    db_execute("""
        UPDATE users SET 
        real_name = %s, anonymous_name = COALESCE(NULLIF(anonymous_name, ''), %s),
        sex = %s, age = %s, educational_level = %s, addiction_year = %s, longest_free_streak = %s, 
        profile_complete = TRUE, recovery_role = 'user'
        WHERE user_id = %s::text
    """, (real_name, real_name, data.get("sex"), data.get("age"), data.get("educational_level"), data.get("addiction_year"), data.get("longest_free_streak"), request.user_id))
    return jsonify({"success": True})

@app.route("/api/register/mentor", methods=["POST"])
@require_auth
def register_mentor_api():
    if str(request.user_id) == str(ADMIN_ID):
        return jsonify({"error": "Admin cannot register"}), 403
    data = request.json
    real_name = data.get("real_name")
    db_execute("""
        UPDATE users SET 
        real_name = %s, anonymous_name = COALESCE(NULLIF(%s, ''), anonymous_name), sex = %s, age = %s, educational_level = %s, 
        work_status = %s, mentorship_experience_years = %s, professional_training = %s, self_recovery_testimony = %s,
        profile_complete = TRUE, recovery_role = 'mentor'
        WHERE user_id = %s::text
    """, (real_name, data.get("anonymous_name") or real_name, data.get("sex"), data.get("age"), data.get("educational_level"), 
          data.get("work_status"), data.get("mentorship_experience_years"), data.get("professional_training"), data.get("self_recovery_testimony"),
          request.user_id))
    return jsonify({"success": True})

@app.route("/api/checkin", methods=["POST"])
@require_auth
def checkin():
    data = request.json
    status = data.get("status")
    today = datetime.now().date()
    user_data = db_fetch_one("SELECT recovery_last_checkin, recovery_streak FROM users WHERE user_id = %s::text", (request.user_id,))
    if not user_data: return jsonify({"error": "User not found"}), 404
    last, current_streak = user_data
    if last == today: return jsonify({"error": "Already checked in today"}), 400
    new_streak = 1
    if status == "yes":
        if last:
            days_diff = (today - last).days
            if days_diff == 1: new_streak = (current_streak or 0) + 1
            elif days_diff == 0: new_streak = current_streak
            else: new_streak = 1
        else: new_streak = 1
    else: new_streak = 0
    db_execute("UPDATE users SET recovery_streak = %s, recovery_last_checkin = %s WHERE user_id = %s::text", (new_streak, today, request.user_id))
    return jsonify({"streak": new_streak})

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
    db_execute("INSERT INTO recovery_reflections (user_id, verse_text, reflection_text, voice_file_url) VALUES (%s::text, %s, %s, %s)",
               (request.user_id, verse, reflection, voice_url))
    return jsonify({"success": True})

@app.route("/api/mentor/messages", methods=["GET"])
@require_auth
def get_messages():
    receiver_id = request.args.get("receiver_id")
    current_user = request.user_id
    if receiver_id:
        mentorship = db_fetch_one("""
            SELECT id FROM recovery_mentorships
            WHERE status = 'active'
            AND ( (user_id = %s::text AND mentor_id = %s::text)
               OR (user_id = %s::text AND mentor_id = %s::text) )
        """, (current_user, receiver_id, receiver_id, current_user))
    else:
        mentorship = db_fetch_one("""
            SELECT id FROM recovery_mentorships
            WHERE status = 'active'
            AND (user_id = %s::text OR mentor_id = %s::text)
            LIMIT 1
        """, (current_user, current_user))
    if not mentorship: return jsonify([])
    mentorship_id = mentorship[0]
    rows = db_fetch_all("""
        SELECT m.sender_id, m.content, m.timestamp, u.anonymous_name
        FROM recovery_messages m
        JOIN users u ON m.sender_id = u.user_id
        WHERE m.mentorship_id = %s
        ORDER BY m.timestamp ASC
    """, (mentorship_id,))
    return jsonify([{"sender_id": r[0], "content": r[1], "timestamp": str(r[2]), "sender_name": r[3]} for r in rows])

@app.route("/api/mentor/message", methods=["POST"])
@require_auth
def send_message():
    data = request.json
    receiver = data.get("receiver_id")
    content = data.get("content")
    if not content or not receiver: return jsonify({"error": "Missing content or receiver"}), 400
    mentorship = db_fetch_one("""
        SELECT id FROM recovery_mentorships
        WHERE status = 'active'
        AND ( (user_id = %s::text AND mentor_id = %s::text)
           OR (user_id = %s::text AND mentor_id = %s::text) )
    """, (request.user_id, receiver, receiver, request.user_id))
    if not mentorship: return jsonify({"error": "No active mentorship"}), 400
    db_execute("INSERT INTO recovery_messages (mentorship_id, sender_id, receiver_id, content) VALUES (%s, %s::text, %s::text, %s)",
               (mentorship[0], request.user_id, receiver, content))
    user_row = db_fetch_one("SELECT recovery_notifications FROM users WHERE user_id = %s::text", (receiver,))
    if user_row and user_row[0]:
        sender_row = db_fetch_one("SELECT anonymous_name FROM users WHERE user_id = %s::text", (request.user_id,))
        send_telegram_notification(receiver, f"📩 New message from {sender_row[0] or 'Someone'} in Recovery App.")
    return jsonify({"success": True})

@app.route("/api/mentors", methods=["GET"])
@require_auth
def get_mentors():
    rows = db_fetch_all("SELECT user_id, anonymous_name, bio FROM users WHERE recovery_role = 'mentor'")
    return jsonify([{"id": r[0], "name": r[1], "bio": r[2]} for r in rows])

@app.route("/api/mentorship/request", methods=["POST"])
@require_auth
def request_mentorship():
    data = request.json
    mentor_id = data.get("mentor_id")
    exists = db_fetch_one("SELECT id FROM recovery_mentorships WHERE user_id = %s::text AND mentor_id = %s::text AND status != 'rejected'", (request.user_id, mentor_id))
    if exists: return jsonify({"error": "Request already pending or active"}), 400
    db_execute("INSERT INTO recovery_mentorships (user_id, mentor_id, status) VALUES (%s::text, %s::text, 'pending')", (request.user_id, mentor_id))
    user_row = db_fetch_one("SELECT anonymous_name FROM users WHERE user_id = %s::text", (request.user_id,))
    send_telegram_notification(mentor_id, f"🤝 New mentorship request from {user_row[0] or 'A user'}! Check the app.")
    return jsonify({"success": True})

@app.route("/api/mentorship/requests", methods=["GET"])
@require_auth
def get_mentorship_requests():
    rows = db_fetch_all("""
        SELECT m.id, u.user_id, u.anonymous_name, u.recovery_streak 
        FROM recovery_mentorships m 
        JOIN users u ON m.user_id = u.user_id 
        WHERE m.mentor_id = %s::text AND m.status = 'pending'
    """, (request.user_id,))
    return jsonify([{"id": r[0], "user_id": r[1], "name": r[2], "streak": r[3]} for r in rows])

@app.route("/api/mentorship/respond", methods=["POST"])
@require_auth
def respond_mentorship():
    data = request.json
    request_id = data.get("request_id")
    action = data.get("action")
    status = 'active' if action == 'accept' else 'rejected'
    row = db_fetch_one("SELECT user_id, mentor_id FROM recovery_mentorships WHERE id = %s", (request_id,))
    if not row or str(row[1]) != str(request.user_id): return jsonify({"error": "Unauthorized"}), 403
    db_execute("UPDATE recovery_mentorships SET status = %s WHERE id = %s", (status, request_id))
    mentor_row = db_fetch_one("SELECT anonymous_name FROM users WHERE user_id = %s::text", (request.user_id,))
    send_telegram_notification(row[0], f"🤝 Your mentorship request to {mentor_row[0] or 'Mentor'} was {status}!")
    return jsonify({"success": True})

@app.route("/api/user/active-mentorship", methods=["GET"])
@require_auth
def active_mentorship():
    row = db_fetch_one("""
        SELECT u.user_id, u.anonymous_name, u.bio, m.status
        FROM recovery_mentorships m
        JOIN users u ON m.mentor_id = u.user_id
        WHERE m.user_id = %s::text AND m.status IN ('active', 'pending')
        ORDER BY m.id DESC LIMIT 1
    """, (request.user_id,))
    if row:
        return jsonify({"has_mentor": row[3] == 'active', "mentor_id": row[0], "mentor_name": row[1], "mentor_bio": row[2], "status": row[3]})
    return jsonify({"has_mentor": False})

@app.route("/api/mentees", methods=["GET"])
@require_auth
def get_mentees():
    rows = db_fetch_all("""
        SELECT u.user_id, u.anonymous_name, u.recovery_streak
        FROM users u
        JOIN recovery_mentorships m ON u.user_id = m.user_id
        WHERE m.mentor_id = %s::text AND m.status = 'active'
    """, (request.user_id,))
    return jsonify([{"id": r[0], "name": r[1], "streak": r[2]} for r in rows])

@app.route("/api/sessions", methods=["GET"])
@require_auth
def get_sessions():
    rows = db_fetch_all("SELECT id, title, description, scheduled_time, jitsi_room, host_id FROM recovery_live_sessions WHERE scheduled_time > NOW() ORDER BY scheduled_time")
    return jsonify([{"id": r[0], "title": r[1], "description": r[2], "time": str(r[3]), "room": r[4], "host_id": r[5]} for r in rows])

@app.route("/api/sessions", methods=["POST"])
@require_auth
def create_session():
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s::text", (request.user_id,))
    if user[0] not in ('mentor', 'admin'): return jsonify({"error": "Unauthorized"}), 403
    data = request.json
    jitsi_room = f"recovery-{uuid.uuid4().hex[:8]}"
    db_execute("INSERT INTO recovery_live_sessions (title, description, host_id, scheduled_time, jitsi_room) VALUES (%s, %s, %s, %s, %s)",
               (data.get("title"), data.get("description"), request.user_id, data.get("scheduled_time"), jitsi_room))
    return jsonify({"success": True, "room": jitsi_room})

@app.route("/api/sessions/<int:session_id>", methods=["DELETE"])
@require_auth
def delete_session(session_id):
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s::text", (request.user_id,))
    session = db_fetch_one("SELECT host_id FROM recovery_live_sessions WHERE id = %s", (session_id,))
    if not session: return jsonify({"error": "Not found"}), 404
    if user[0] == 'admin' or str(session[0]) == request.user_id:
        db_execute("DELETE FROM recovery_live_sessions WHERE id = %s", (session_id,))
        return jsonify({"success": True})
    return jsonify({"error": "Unauthorized"}), 403

@app.route("/api/sessions/<int:session_id>/join", methods=["GET"])
@require_auth
def join_session(session_id):
    row = db_fetch_one("SELECT jitsi_room FROM recovery_live_sessions WHERE id = %s", (session_id,))
    if not row: return jsonify({"error": "Not found"}), 404
    return jsonify({"jitsi_url": f"https://meet.jit.si/{row[0]}"})

@app.route("/api/user/update", methods=["POST"])
@require_auth
def update_profile():
    data = request.json
    db_execute("UPDATE users SET anonymous_name = %s, bio = %s WHERE user_id = %s::text", (data.get("name"), data.get("bio"), request.user_id))
    return jsonify({"success": True})

@app.route("/api/admin/users", methods=["GET"])
@require_auth
def admin_users():
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s::text", (request.user_id,))
    if user[0] != 'admin': return jsonify({"error": "Admin only"}), 403
    rows = db_fetch_all("SELECT user_id, anonymous_name, recovery_role, profile_complete FROM users")
    return jsonify([{"id": r[0], "name": r[1], "role": r[2], "profile_complete": r[3]} for r in rows])

@app.route("/api/admin/set-role", methods=["POST"])
@require_auth
def set_role():
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s::text", (request.user_id,))
    if user[0] != 'admin': return jsonify({"error": "Admin only"}), 403
    data = request.json
    db_execute("UPDATE users SET recovery_role = %s WHERE user_id = %s::text", (data.get("role"), data.get("user_id")))
    return jsonify({"success": True})

@app.route("/api/admin/broadcast", methods=["POST"])
@require_auth
def broadcast():
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s::text", (request.user_id,))
    if user[0] != 'admin': return jsonify({"error": "Admin only"}), 403
    data = request.json
    message = data.get("message")
    rows = db_fetch_all("SELECT user_id FROM users WHERE recovery_notifications = TRUE")
    for row in rows:
        send_telegram_notification(row[0], f"📢 Admin announcement:\n\n{message}\n\n{RENDER_URL}/recovery?token={generate_token(row[0])}")
    return jsonify({"success": True})

# -------------------- Telegram Bot Logic --------------------

def register_user(user_id, username):
    try:
        user_id_str = str(user_id)
        existing = db_fetch_one("SELECT user_id FROM users WHERE user_id = %s::text", (user_id_str,))
        is_admin_user = user_id_str == str(ADMIN_ID)
        role = 'admin' if is_admin_user else 'user'
        anonymous_name = username if username else f"Warrior_{user_id_str[-4:]}"
        
        if not existing:
            db_execute(
                "INSERT INTO users (user_id, anonymous_name, recovery_role, profile_complete) VALUES (%s::text, %s, %s, %s)",
                (user_id_str, anonymous_name, role, is_admin_user)
            )
            logger.info(f"Registered user: {user_id_str} as {role}")
        elif is_admin_user:
            db_execute("UPDATE users SET recovery_role = 'admin', profile_complete = TRUE WHERE user_id = %s::text", (user_id_str,))
    except Exception as e:
        logger.error(f"Bot register error: {e}")

def generate_webapp_url(user_id: str) -> str:
    token = generate_token(user_id)
    nocache = int(datetime.utcnow().timestamp())
    # Admin directly to recovery
    if str(user_id) == str(ADMIN_ID):
        return f"{RENDER_URL}/recovery?token={token}&_={nocache}"
    return f"{RENDER_URL}/landing?token={token}&_={nocache}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username or user.first_name)
    url = generate_webapp_url(user.id)
    reply_kb = ReplyKeyboardMarkup([[KeyboardButton("🌐 Open Recovery App", web_app=WebAppInfo(url=url))]], resize_keyboard=True, is_persistent=True)
    await update.message.reply_text(
        "🙏 *Christian Recovery Companion*\n\nWelcome to your safe, anonymous space.\n\nTap the button below to start your journey.",
        reply_markup=reply_kb, parse_mode="Markdown"
    )

async def set_persistent_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    url = generate_webapp_url(user_id)
    await context.bot.set_chat_menu_button(chat_id=user_id, menu_button=MenuButtonWebApp(text="Recovery App", web_app=WebAppInfo(url=url)))
    await update.message.reply_text("✅ Menu button updated!")

def run_bot():
    if not TELEGRAM_TOKEN: return
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setmenu", set_persistent_menu_button))
    logger.info("✅ Bot starting...")
    application.run_polling()

# -------------------- Initialization --------------------

def check_upcoming_sessions():
    try:
        now = datetime.now()
        rows = db_fetch_all("SELECT id, title FROM recovery_live_sessions WHERE scheduled_time BETWEEN %s AND %s", (now, now + timedelta(minutes=15)))
        if not rows: return
        users = db_fetch_all("SELECT user_id FROM users WHERE recovery_notifications = TRUE")
        for r in rows:
            for u in users:
                send_telegram_notification(u[0], f"🔔 Live session in 15 minutes!\n\nTitle: {r[1]}\nJoin: {RENDER_URL}/recovery")
    except Exception as e:
        logger.error(f"Scheduler error: {e}")

# Start scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(func=check_upcoming_sessions, trigger="interval", minutes=1)
scheduler.start()

# Start bot in a background thread
bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)), debug=False)
