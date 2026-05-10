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
@app.after_request
def add_header(response):
    # Prevent caching of HTML pages for fresh WebApp loads
    if response.mimetype == 'text/html':
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, post-check=0, pre-check=0, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

@app.route("/ping", methods=['GET', 'HEAD'])
def ping():
    """Simple health check for UptimeRobot and Frontend."""
    return jsonify({"status": "ok", "message": "OK"}), 200




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
            "self_recovery_testimony": "TEXT"
        }
        for col, dtype in cols.items():
            cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {dtype}")
            
        # Update mentorship status default
        cur.execute("ALTER TABLE recovery_mentorships ALTER COLUMN status SET DEFAULT 'pending'")
        
        # Ensure foreign keys have CASCADE DELETE (Note: This is complex in SQL if already exists, 
        # but for simplicity in this app we assume the admin can re-run schema or we handle it here)
        tables_to_cascade = [
            ("recovery_reflections", "user_id"),
            ("recovery_mentorships", "user_id"),
            ("recovery_mentorships", "mentor_id"),
            ("recovery_messages", "mentorship_id"),
            ("recovery_messages", "sender_id"),
            ("recovery_messages", "receiver_id"),
            ("recovery_live_sessions", "host_id")
        ]
        # Skip complex FK migration in Python script to avoid breakage, but it's in schema.sql

        
        conn.commit()
        logger.info("✅ Database migrations successful.")
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"⚠️ Database migration note: {e}")


init_db_types()

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
            request.user_id = str(data["user_id"])
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

@app.route("/landing")
def landing():
    token = request.args.get("token")
    if not token: return "Missing token", 400
    try:
        data = jwt.decode(token, app.secret_key, algorithms=["HS256"])
        if str(data.get("user_id")) == str(ADMIN_ID):
            return redirect(f"/recovery?token={token}")
    except:
        pass
    return render_template("landing.html", token=token)


@app.route("/register/user")
def user_reg_page():
    token = request.args.get("token")
    try:
        data = jwt.decode(token, app.secret_key, algorithms=["HS256"])
        if str(data.get("user_id")) == str(ADMIN_ID):
            return redirect(f"/recovery?token={token}")
    except:
        pass
    return render_template("user_registration.html", token=token)

@app.route("/register/mentor")
def mentor_reg_page():
    token = request.args.get("token")
    try:
        data = jwt.decode(token, app.secret_key, algorithms=["HS256"])
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
    
    # Robust check for profile completion
    try:
        data = jwt.decode(token, app.secret_key, algorithms=["HS256"])
        u_id = str(data["user_id"])
        row = db_fetch_one("SELECT profile_complete FROM users WHERE user_id = %s::text", (u_id,))
        
        # If user doesn't exist or profile is not complete, send to landing
        if not row or not row[0]:
            # Exception: Admin is always complete
            if u_id != str(ADMIN_ID):
                return redirect(f"/landing?token={token}")
    except Exception as e:
        logger.error(f"Recovery route error: {e}")
        pass
        
    return render_template("recovery_dashboard.html", token=token)



@app.route("/admin")
def admin_page():
    token = request.args.get("token")
    if not token:
        return "Unauthorized", 401
    return render_template("admin_dashboard.html", token=token)
@app.route("/api/user/me", methods=["GET"])
@require_auth
def get_user():
    row = db_fetch_one("""
        SELECT user_id, anonymous_name, recovery_role, recovery_streak, recovery_last_checkin, recovery_notifications, 
               profile_complete, sex, age, educational_level, addiction_year, longest_free_streak,
               real_name, work_status, mentorship_experience_years, professional_training, self_recovery_testimony
        FROM users WHERE user_id = %s::text
    """, (request.user_id,))
    if not row:
        return jsonify({"error": "User not found"}), 404
    return jsonify({
        "user_id": row[0],
        "name": row[1],
        "role": row[2],
        "streak": row[3],
        "last_checkin": str(row[4]) if row[4] else None,
        "notifications": row[5],
        "profile_complete": row[6],
        "sex": row[7],
        "age": row[8],
        "education": row[9],
        "addiction_year": row[10],
        "longest_streak": row[11],
        "real_name": row[12],
        "work_status": row[13],
        "mentor_years": row[14],
        "training": row[15],
        "testimony": row[16]
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
    # Explicitly set role to mentor, never admin
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
    if not user_data:
        return jsonify({"error": "User not found"}), 404
        
    last, current_streak = user_data
    
    if last == today:
        return jsonify({"error": "Already checked in today"}), 400
        
    new_streak = 1
    if status == "yes":
        if last:
            days_diff = (today - last).days
            if days_diff == 1:
                new_streak = (current_streak or 0) + 1
            elif days_diff == 0: # already handled but for safety
                new_streak = current_streak
            else:
                new_streak = 1 # Streak broken
        else:
            new_streak = 1 # First checkin
    else:
        new_streak = 0 # Relapse
        
    db_execute("UPDATE users SET recovery_streak = %s, recovery_last_checkin = %s WHERE user_id = %s::text", (new_streak, today, request.user_id))
    logger.info(f"User {request.user_id} checked in. New streak: {new_streak}")
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
    if not receiver_id:
        # Default to first active mentorship if none specified
        mentor_row = db_fetch_one("SELECT id FROM recovery_mentorships WHERE (user_id = %s::text OR mentor_id = %s::text) AND status = 'active' LIMIT 1", (request.user_id, request.user_id))
    else:
        # Robust fetch for specific mentorship
        mentor_row = db_fetch_one("""
            SELECT id FROM recovery_mentorships 
            WHERE ((user_id = %s::text AND mentor_id = %s::text) OR (user_id = %s::text AND mentor_id = %s::text)) 
            AND status = 'active'
        """, (request.user_id, receiver_id, receiver_id, request.user_id))
    
    if not mentor_row:
        return jsonify([])
    
    mentorship_id = mentor_row[0]
    rows = db_fetch_all("SELECT sender_id, content, timestamp FROM recovery_messages WHERE mentorship_id = %s ORDER BY timestamp", (mentorship_id,))
    
    user_names = {}
    all_sender_ids = list(set([str(r[0]) for r in rows]))
    if all_sender_ids:
        if len(all_sender_ids) == 1:
            name_rows = db_fetch_all("SELECT user_id, anonymous_name FROM users WHERE user_id = %s::text", (all_sender_ids[0],))
        else:
            name_rows = db_fetch_all("SELECT user_id, anonymous_name FROM users WHERE user_id IN %s", (tuple(all_sender_ids),))
        user_names = {r[0]: r[1] for r in name_rows}

    messages = [{"sender_id": r[0], "sender_name": user_names.get(str(r[0]), "Unknown"), "content": r[1], "timestamp": str(r[2])} for r in rows]
    return jsonify(messages)



@app.route("/api/mentor/message", methods=["POST"])
@require_auth
def send_message():
    data = request.json
    receiver_id = data.get("receiver_id")
    content = data.get("content")
    
    try:
        if receiver_id:
            mentorship = db_fetch_one("SELECT id FROM recovery_mentorships WHERE ((user_id = %s::text AND mentor_id = %s::text) OR (user_id = %s::text AND mentor_id = %s::text)) AND status = 'active'", (request.user_id, receiver_id, receiver_id, request.user_id))
        else:
            mentorship = db_fetch_one("SELECT id, CASE WHEN user_id = %s::text THEN mentor_id ELSE user_id END FROM recovery_mentorships WHERE (user_id = %s::text OR mentor_id = %s::text) AND status = 'active'", (request.user_id, request.user_id, request.user_id))
        
        if not mentorship:
            return jsonify({"error": "No active mentorship found."}), 400
            
        mentorship_id = mentorship[0]
        final_receiver_id = receiver_id if receiver_id else mentorship[1]
        
        db_execute("INSERT INTO recovery_messages (mentorship_id, sender_id, receiver_id, content) VALUES (%s, %s::text, %s::text, %s)",
                (mentorship_id, request.user_id, final_receiver_id, content))
        
        # Notify
        user_row = db_fetch_one("SELECT anonymous_name, recovery_notifications FROM users WHERE user_id = %s::text", (final_receiver_id,))
        if user_row and user_row[1]:
            sender_row = db_fetch_one("SELECT anonymous_name FROM users WHERE user_id = %s::text", (request.user_id,))
            sender_name = sender_row[0] if sender_row else "Someone"
            send_telegram_notification(final_receiver_id, f"📩 New message from {sender_name} in Recovery App.")
        
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/mentors", methods=["GET"])
@require_auth
def get_mentors():
    rows = db_fetch_all("SELECT user_id, anonymous_name, bio FROM users WHERE recovery_role = 'mentor'")
    mentors = [{"id": r[0], "name": r[1], "bio": r[2]} for r in rows]
    return jsonify(mentors)

@app.route("/api/mentorship/request", methods=["POST"])
@require_auth
def request_mentorship():
    data = request.json
    mentor_id = data.get("mentor_id")
    
    # Check if already exists
    exists = db_fetch_one("SELECT id FROM recovery_mentorships WHERE user_id = %s::text AND mentor_id = %s::text AND status != 'rejected'", (request.user_id, mentor_id))
    if exists:
        return jsonify({"error": "Request already pending or active"}), 400
        
    db_execute("INSERT INTO recovery_mentorships (user_id, mentor_id, status) VALUES (%s::text, %s::text, 'pending')", (request.user_id, mentor_id))
    
    # Notify mentor
    user_row = db_fetch_one("SELECT anonymous_name FROM users WHERE user_id = %s::text", (request.user_id,))
    user_name = user_row[0] if user_row else "A user"
    send_telegram_notification(mentor_id, f"🤝 New mentorship request from {user_name}! Check the app to accept or reject.")
    
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
    requests = [{"id": r[0], "user_id": r[1], "name": r[2], "streak": r[3]} for r in rows]
    return jsonify(requests)

@app.route("/api/mentorship/status", methods=["GET"])
@require_auth
def mentorship_status():
    # As a user, get my mentor or pending request
    row = db_fetch_one("""
        SELECT m.id, u.user_id, u.anonymous_name, m.status 
        FROM recovery_mentorships m 
        JOIN users u ON m.mentor_id = u.user_id 
        WHERE m.user_id = %s::text AND m.status IN ('pending', 'active')
        ORDER BY m.id DESC LIMIT 1
    """, (request.user_id,))
    if not row:
        return jsonify(None)
    return jsonify({"id": row[0], "mentor_id": row[1], "name": row[2], "status": row[3]})

@app.route("/api/mentorship/respond", methods=["POST"])
@require_auth
def respond_mentorship():
    data = request.json
    request_id = data.get("request_id")
    action = data.get("action") # 'accept' or 'reject'
    
    status = 'active' if action == 'accept' else 'rejected'
    
    # Verify ownership: mentorship request must belong to this mentor
    row = db_fetch_one("SELECT user_id, mentor_id FROM recovery_mentorships WHERE id = %s", (request_id,))
    if not row or str(row[1]) != str(request.user_id):
        return jsonify({"error": "Unauthorized"}), 403
        
    mentee_id = row[0]
    db_execute("UPDATE recovery_mentorships SET status = %s WHERE id = %s", (status, request_id))

    
    # Notify user
    mentor_row = db_fetch_one("SELECT anonymous_name FROM users WHERE user_id = %s::text", (request.user_id,))
    mentor_name = mentor_row[0] if mentor_row else "Mentor"
    send_telegram_notification(mentee_id, f"🤝 Your mentorship request to {mentor_name} was {status}!")
    
    return jsonify({"success": True})

@app.route("/api/user/active-mentorship", methods=["GET"])
@require_auth
def active_mentorship():
    return mentorship_status()



@app.route("/api/sessions", methods=["GET"])
@require_auth
def get_sessions():
    rows = db_fetch_all("SELECT id, title, description, scheduled_time, jitsi_room FROM recovery_live_sessions WHERE scheduled_time > NOW() ORDER BY scheduled_time")
    sessions = [{"id": r[0], "title": r[1], "description": r[2], "time": str(r[3]), "room": r[4]} for r in rows]
    return jsonify(sessions)

@app.route("/api/sessions", methods=["POST"])
@require_auth
def create_session():
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s::text", (request.user_id,))
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

@app.route("/api/sessions/<int:session_id>", methods=["DELETE"])
@require_auth
def delete_session(session_id):
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s::text", (request.user_id,))
    if user[0] not in ('mentor', 'admin'):
        return jsonify({"error": "Unauthorized"}), 403
    db_execute("DELETE FROM recovery_live_sessions WHERE id = %s", (session_id,))
    return jsonify({"success": True})

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
    try:
        user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s::text", (request.user_id,))
        if not user or user[0] not in ('mentor', 'admin'):
            logger.warning(f"Unauthorized mentee fetch attempt by {request.user_id}")
            return jsonify({"error": "Unauthorized"}), 403
            
        rows = db_fetch_all("SELECT u.user_id, u.anonymous_name, u.recovery_streak FROM users u JOIN recovery_mentorships m ON u.user_id = m.user_id WHERE m.mentor_id = %s::text AND m.status = 'active'", (request.user_id,))
        mentees = [{"id": r[0], "name": r[1], "streak": r[2]} for r in rows]
        logger.info(f"Fetched {len(mentees)} mentees for {request.user_id}")
        return jsonify(mentees)
    except Exception as e:
        logger.error(f"Error fetching mentees: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/users", methods=["GET"])
@require_auth
def admin_users():
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s::text", (request.user_id,))
    if user[0] != 'admin':
        return jsonify({"error": "Admin only"}), 403
    rows = db_fetch_all("""
        SELECT user_id, anonymous_name, recovery_role, sex, age, educational_level, addiction_year, longest_free_streak,
               real_name, work_status, mentorship_experience_years, professional_training, self_recovery_testimony, profile_complete
        FROM users
    """)
    users = [{
        "id": r[0], "name": r[1], "role": r[2], "sex": r[3], "age": r[4], "education": r[5], "addiction": r[6], "streak": r[7],
        "real_name": r[8], "work_status": r[9], "mentor_years": r[10], "training": r[11], "testimony": r[12], "profile_complete": r[13]
    } for r in rows]
    return jsonify(users)

@app.route("/api/admin/user/<user_id>", methods=["DELETE"])
@require_auth
def delete_user(user_id):
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s::text", (request.user_id,))
    if user[0] != 'admin':
        return jsonify({"error": "Admin only"}), 403
    
    # Due to ON DELETE CASCADE, deleting from users will clean up everything else
    db_execute("DELETE FROM users WHERE user_id = %s::text", (user_id,))
    return jsonify({"success": True})


@app.route("/api/user/update", methods=["POST"])
@require_auth
def update_profile():
    data = request.json
    name = data.get("name")
    bio = data.get("bio")
    db_execute("UPDATE users SET anonymous_name = %s, bio = %s WHERE user_id = %s::text", (name, bio, request.user_id))
    return jsonify({"success": True})

@app.route("/api/admin/set-role", methods=["POST"])
@require_auth
def set_role():
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s::text", (request.user_id,))
    if user[0] != 'admin':
        return jsonify({"error": "Admin only"}), 403
    data = request.json
    target_id = data.get("user_id")
    role = data.get("role")
    db_execute("UPDATE users SET recovery_role = %s WHERE user_id = %s::text", (role, target_id))
    return jsonify({"success": True})
def init_db():
    # Simple guard: check for a secret key in args
    if request.args.get("key") != app.secret_key:
        return "Unauthorized", 401
    try:
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path, "r") as f:
            schema = f.read()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(schema)
        conn.commit()
        cur.close()
        conn.close()
        return "Database initialized successfully", 200
    except Exception as e:
        return f"Error: {e}", 500

@app.route("/api/admin/assign-mentor", methods=["POST"])
@require_auth
def assign_mentor():
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s::text", (request.user_id,))
    if user[0] != 'admin':
        return jsonify({"error": "Admin only"}), 403
    data = request.json
    mentee_id = data.get("user_id")
    mentor_id = data.get("mentor_id")
    exists = db_fetch_one("SELECT id FROM recovery_mentorships WHERE user_id = %s::text AND mentor_id = %s::text", (mentee_id, mentor_id))
    if not exists:
        db_execute("INSERT INTO recovery_mentorships (user_id, mentor_id, status) VALUES (%s::text, %s::text, 'active')", (mentee_id, mentor_id))
    return jsonify({"success": True})

@app.route("/api/admin/broadcast", methods=["POST"])
@require_auth
def broadcast():
    user = db_fetch_one("SELECT recovery_role FROM users WHERE user_id = %s::text", (request.user_id,))
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
