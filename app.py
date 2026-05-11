import os
import threading
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, session, render_template, redirect
from flask_cors import CORS
from models import db, User, Message, Meeting
from functools import wraps
import uuid
import jwt
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///counseling.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
CORS(app, supports_credentials=True)

db.init_app(app)

# Helper: get user from token or session
def get_current_user():
    # Try to get from session first
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    # Then try Authorization header
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        try:
            payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            user_id = payload.get('user_id')
            if user_id:
                return User.query.get(user_id)
        except jwt.InvalidTokenError:
            pass
    return None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Unauthorized'}), 401
        # Store user in request context for easy access
        request.current_user = user
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user or user.role != 'admin':
            return jsonify({'error': 'Admin required'}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return decorated

def mentor_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user or user.role not in ['mentor', 'admin']:
            return jsonify({'error': 'Mentor access required'}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return decorated

def generate_jitsi_link(meeting_id):
    room_name = f"counseling_{meeting_id}_{uuid.uuid4().hex[:8]}"
    return f"https://meet.jit.si/{room_name}"

# ---------- Create tables and default users ----------
with app.app_context():
    db.create_all()
    if not User.query.filter_by(role='admin').first():
        admin = User(username='admin', email='admin@example.com', role='admin', full_name='System Admin')
        admin.set_password('admin123')
        db.session.add(admin)
        mentor = User(username='mentor_john', email='john@example.com', role='mentor', full_name='John Smith')
        mentor.set_password('mentor123')
        db.session.add(mentor)
        db.session.commit()
        print("✅ Default admin (admin/admin123) and mentor (mentor_john/mentor123) created.")

# ---------- JWT token endpoints ----------
@app.route('/api/generate-token', methods=['POST'])
@login_required
def generate_token():
    """Generate JWT token for Mini App (after login)"""
    user = request.current_user
    token = jwt.encode(
        {
            'user_id': user.id,
            'exp': datetime.now(timezone.utc) + timedelta(days=30)
        },
        app.config['SECRET_KEY'],
        algorithm='HS256'
    )
    return jsonify({'token': token})

@app.route('/api/verify-token', methods=['POST'])
def verify_token():
    """Verify JWT token and return user data"""
    data = request.json
    token = data.get('token')
    if not token:
        return jsonify({'error': 'No token provided'}), 401
    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        user = User.query.get(payload['user_id'])
        if not user:
            return jsonify({'error': 'User not found'}), 401
        return jsonify({'user': user.to_dict()})
    except jwt.ExpiredSignatureError:
        return jsonify({'error': 'Token expired'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'error': 'Invalid token'}), 401

# ---------- API routes (modified to use request.current_user) ----------
@app.route('/')
def index():
    return redirect('/miniapp')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username already exists'}), 400
    if User.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email already exists'}), 400
    user = User(username=data['username'], email=data['email'],
                role=data.get('role', 'user'), full_name=data.get('full_name'))
    user.set_password(data['password'])
    db.session.add(user)
    db.session.commit()
    return jsonify({'message': 'Registration successful', 'user_id': user.id})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data['username']).first()
    if not user or not user.check_password(data['password']):
        return jsonify({'error': 'Invalid credentials'}), 401
    session['user_id'] = user.id  # Keep session for web browser
    return jsonify({'message': 'Login successful', 'user': user.to_dict()})

@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    session.clear()
    return jsonify({'message': 'Logged out'})

@app.route('/api/me', methods=['GET'])
@login_required
def get_current_user():
    return jsonify(request.current_user.to_dict())

@app.route('/api/users/<int:user_id>', methods=['GET'])
@login_required
def get_user(user_id):
    user = User.query.get_or_404(user_id)
    return jsonify(user.to_dict())

@app.route('/api/users/<int:user_id>', methods=['PUT'])
@login_required
def update_user(user_id):
    if request.current_user.id != user_id:
        return jsonify({'error': 'Permission denied'}), 403
    user = User.query.get_or_404(user_id)
    data = request.json
    if 'full_name' in data:
        user.full_name = data['full_name']
    if 'email' in data:
        user.email = data['email']
    db.session.commit()
    return jsonify(user.to_dict())

@app.route('/api/admin/assign', methods=['POST'])
@admin_required
def assign_mentor():
    data = request.json
    user = User.query.get_or_404(data['user_id'])
    mentor = User.query.get_or_404(data['mentor_id'])
    if mentor.role != 'mentor':
        return jsonify({'error': 'Selected user is not a mentor'}), 400
    user.assigned_mentor_id = mentor.id
    db.session.commit()
    return jsonify({'message': 'Mentor assigned successfully'})

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def list_all_users():
    users = User.query.all()
    return jsonify([u.to_dict() for u in users])

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        return jsonify({'error': 'Cannot delete admin'}), 403
    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': 'User deleted'})

@app.route('/api/messages/send', methods=['POST'])
@login_required
def send_message():
    data = request.json
    sender = request.current_user
    recipient = User.query.get(data['recipient_id'])
    if sender.role == 'user' and sender.assigned_mentor_id != recipient.id:
        return jsonify({'error': 'You can only chat with your assigned mentor'}), 403
    if sender.role == 'mentor':
        client = User.query.get(data['recipient_id'])
        if not client or client.assigned_mentor_id != sender.id:
            return jsonify({'error': 'You can only chat with your assigned clients'}), 403
    message = Message(sender_id=sender.id, recipient_id=recipient.id, content=data['content'])
    db.session.add(message)
    db.session.commit()
    return jsonify(message.to_dict())

@app.route('/api/messages/conversation/<int:other_user_id>', methods=['GET'])
@login_required
def get_conversation(other_user_id):
    user_id = request.current_user.id
    messages = Message.query.filter(
        ((Message.sender_id == user_id) & (Message.recipient_id == other_user_id)) |
        ((Message.sender_id == other_user_id) & (Message.recipient_id == user_id))
    ).order_by(Message.timestamp).all()
    for msg in messages:
        if msg.recipient_id == user_id and not msg.is_read:
            msg.is_read = True
    db.session.commit()
    return jsonify([m.to_dict() for m in messages])

@app.route('/api/meetings', methods=['POST'])
@mentor_required
def create_meeting():
    data = request.json
    meeting = Meeting(
        mentor_id=request.current_user.id,
        client_id=data.get('client_id'),
        is_global=data.get('is_global', False),
        title=data['title'],
        description=data.get('description', ''),
        start_time=datetime.fromisoformat(data['start_time'].replace('Z', '+00:00')),
        duration_minutes=data.get('duration_minutes', 60)
    )
    db.session.add(meeting)
    db.session.commit()
    meeting.meeting_link = generate_jitsi_link(meeting.id)
    db.session.commit()
    return jsonify(meeting.to_dict()), 201

@app.route('/api/meetings', methods=['GET'])
@login_required
def get_meetings():
    user = request.current_user
    if user.role == 'mentor':
        meetings = Meeting.query.filter_by(mentor_id=user.id).order_by(Meeting.start_time).all()
    elif user.role == 'user':
        meetings = Meeting.query.filter(
            (Meeting.is_global == True) |
            ((Meeting.client_id == user.id) & (Meeting.is_global == False))
        ).order_by(Meeting.start_time).all()
    else:
        meetings = Meeting.query.order_by(Meeting.start_time).all()
    return jsonify([m.to_dict() for m in meetings])

@app.route('/api/meetings/instant/<int:mentor_id>', methods=['POST'])
@login_required
def instant_meeting(mentor_id):
    user = request.current_user
    mentor = User.query.get_or_404(mentor_id)
    if user.role == 'user' and user.assigned_mentor_id != mentor_id:
        return jsonify({'error': 'This is not your assigned mentor'}), 403
    meeting = Meeting(
        mentor_id=mentor_id,
        client_id=user.id if user.role == 'user' else None,
        is_global=False,
        title=f"Instant Meeting between {user.full_name} and {mentor.full_name}",
        start_time=datetime.utcnow(),
        duration_minutes=30
    )
    db.session.add(meeting)
    db.session.commit()
    meeting.meeting_link = generate_jitsi_link(meeting.id)
    db.session.commit()
    return jsonify({'meeting_link': meeting.meeting_link, 'meeting_id': meeting.id})

@app.route('/api/mentor/clients', methods=['GET'])
@login_required
def get_mentor_clients():
    user = request.current_user
    if user.role not in ['mentor', 'admin']:
        return jsonify({'error': 'Access denied'}), 403
    if user.role == 'admin':
        clients = User.query.filter_by(role='user').all()
    else:
        clients = User.query.filter_by(assigned_mentor_id=user.id).all()
    return jsonify([c.to_dict() for c in clients])

# Health check endpoints
@app.route('/ping', methods=['GET', 'HEAD'])
def ping():
    return '', 200

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'timestamp': datetime.utcnow().isoformat()}), 200

@app.route('/miniapp')
def miniapp():
    return render_template('miniapp.html')

# ---------- Start Flask in background thread, bot in main thread ----------
def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("🌐 Flask server started in background thread")
    time.sleep(2)
    from telegram_bot import main as bot_main
    bot_main()
