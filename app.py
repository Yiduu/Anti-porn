import os
import threading
from datetime import datetime
from flask import Flask, request, jsonify, session, render_template, redirect
from flask_cors import CORS
from models import db, User, Message, Meeting
from functools import wraps
import uuid
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key')
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///counseling.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
CORS(app, supports_credentials=True)

db.init_app(app)

# ---------- Helpers ----------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        user = User.query.get(session['user_id'])
        if not user or user.role != 'admin':
            return jsonify({'error': 'Admin required'}), 403
        return f(*args, **kwargs)
    return decorated

def mentor_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        user = User.query.get(session['user_id'])
        if not user or user.role not in ['mentor', 'admin']:
            return jsonify({'error': 'Mentor required'}), 403
        return f(*args, **kwargs)
    return decorated

def generate_jitsi_link(meeting_id):
    return f"https://meet.jit.si/counseling_{meeting_id}_{uuid.uuid4().hex[:8]}"

# ---------- Create tables & default users ----------
with app.app_context():
    db.create_all()
    if not User.query.filter_by(role='admin').first():
        admin = User(username='admin', email='admin@example.com', role='admin', full_name='Admin')
        admin.set_password('admin123')
        db.session.add(admin)
        mentor = User(username='mentor_john', email='john@example.com', role='mentor', full_name='John Smith')
        mentor.set_password('mentor123')
        db.session.add(mentor)
        db.session.commit()
        print("✅ Default admin (admin/admin123) and mentor (mentor_john/mentor123) created.")

# ---------- API routes ----------
@app.route('/')
def index():
    return redirect('/miniapp')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username exists'}), 400
    if User.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email exists'}), 400
    user = User(username=data['username'], email=data['email'],
                role=data.get('role','user'), full_name=data.get('full_name'))
    user.set_password(data['password'])
    db.session.add(user)
    db.session.commit()
    return jsonify({'message': 'Registered', 'user_id': user.id})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data['username']).first()
    if not user or not user.check_password(data['password']):
        return jsonify({'error': 'Invalid credentials'}), 401
    session['user_id'] = user.id
    return jsonify({'message': 'OK', 'user': user.to_dict()})

@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    session.clear()
    return jsonify({'message': 'Logged out'})

@app.route('/api/me', methods=['GET'])
@login_required
def me():
    return jsonify(User.query.get(session['user_id']).to_dict())

@app.route('/api/users/<int:user_id>', methods=['GET'])
@login_required
def get_user(user_id):
    return jsonify(User.query.get_or_404(user_id).to_dict())

@app.route('/api/users/<int:user_id>', methods=['PUT'])
@login_required
def update_user(user_id):
    if session['user_id'] != user_id:
        return jsonify({'error': 'Forbidden'}), 403
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
        return jsonify({'error': 'Not a mentor'}), 400
    user.assigned_mentor_id = mentor.id
    db.session.commit()
    return jsonify({'message': 'Assigned'})

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def list_users():
    return jsonify([u.to_dict() for u in User.query.all()])

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        return jsonify({'error': 'Cannot delete admin'}), 403
    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': 'Deleted'})

@app.route('/api/messages/send', methods=['POST'])
@login_required
def send_message():
    data = request.json
    sender = User.query.get(session['user_id'])
    recipient = User.query.get(data['recipient_id'])
    if sender.role == 'user' and sender.assigned_mentor_id != recipient.id:
        return jsonify({'error': 'Can only chat with your mentor'}), 403
    if sender.role == 'mentor':
        client = User.query.get(data['recipient_id'])
        if not client or client.assigned_mentor_id != sender.id:
            return jsonify({'error': 'Can only chat with your clients'}), 403
    msg = Message(sender_id=sender.id, recipient_id=recipient.id, content=data['content'])
    db.session.add(msg)
    db.session.commit()
    return jsonify(msg.to_dict())

@app.route('/api/messages/conversation/<int:other_id>', methods=['GET'])
@login_required
def conversation(other_id):
    user_id = session['user_id']
    msgs = Message.query.filter(
        ((Message.sender_id == user_id) & (Message.recipient_id == other_id)) |
        ((Message.sender_id == other_id) & (Message.recipient_id == user_id))
    ).order_by(Message.timestamp).all()
    for m in msgs:
        if m.recipient_id == user_id and not m.is_read:
            m.is_read = True
    db.session.commit()
    return jsonify([m.to_dict() for m in msgs])

@app.route('/api/meetings', methods=['POST'])
@mentor_required
def create_meeting():
    data = request.json
    meeting = Meeting(
        mentor_id=session['user_id'],
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
    user = User.query.get(session['user_id'])
    if user.role == 'mentor':
        q = Meeting.query.filter_by(mentor_id=user.id)
    elif user.role == 'user':
        q = Meeting.query.filter((Meeting.is_global == True) | ((Meeting.client_id == user.id) & (Meeting.is_global == False)))
    else:
        q = Meeting.query
    return jsonify([m.to_dict() for m in q.order_by(Meeting.start_time).all()])

@app.route('/api/meetings/instant/<int:mentor_id>', methods=['POST'])
@login_required
def instant_meeting(mentor_id):
    user = User.query.get(session['user_id'])
    mentor = User.query.get_or_404(mentor_id)
    if user.role == 'user' and user.assigned_mentor_id != mentor_id:
        return jsonify({'error': 'Not your mentor'}), 403
    meeting = Meeting(
        mentor_id=mentor_id,
        client_id=user.id if user.role == 'user' else None,
        is_global=False,
        title=f"Instant meeting {user.full_name} – {mentor.full_name}",
        start_time=datetime.utcnow()
    )
    db.session.add(meeting)
    db.session.commit()
    meeting.meeting_link = generate_jitsi_link(meeting.id)
    db.session.commit()
    return jsonify({'meeting_link': meeting.meeting_link})

@app.route('/api/mentor/clients', methods=['GET'])
@login_required
def mentor_clients():
    user = User.query.get(session['user_id'])
    if user.role == 'mentor':
        clients = User.query.filter_by(assigned_mentor_id=user.id).all()
    elif user.role == 'admin':
        clients = User.query.filter_by(role='user').all()
    else:
        return jsonify({'error': 'Forbidden'}), 403
    return jsonify([c.to_dict() for c in clients])

@app.route('/miniapp')
def miniapp():
    return render_template('miniapp.html')

# ---------- Run Flask in background, bot in main ----------
def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("🌐 Flask started in background.")
    # Give Flask a moment to bind
    import time
    time.sleep(2)
    from telegram_bot import main as bot_main
    bot_main()
