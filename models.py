from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import bcrypt

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='user')  # user, mentor, admin
    full_name = db.Column(db.String(100))
    telegram_id = db.Column(db.String(50), unique=True, nullable=True)
    assigned_mentor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    mentor = db.relationship('User', remote_side=[id], backref='clients', foreign_keys=[assigned_mentor_id])
    
    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def check_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role,
            'full_name': self.full_name,
            'assigned_mentor_id': self.assigned_mentor_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id', use_alter=True, name='fk_messages_sender'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id', use_alter=True, name='fk_messages_recipient'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)
    
    sender = db.relationship('User', foreign_keys=[sender_id])
    recipient = db.relationship('User', foreign_keys=[recipient_id])
    
    def to_dict(self):
        return {
            'id': self.id,
            'sender_id': self.sender_id,
            'recipient_id': self.recipient_id,
            'content': self.content,
            'timestamp': self.timestamp.isoformat(),
            'is_read': self.is_read
        }

class Meeting(db.Model):
    __tablename__ = 'meetings'
    id = db.Column(db.Integer, primary_key=True)
    mentor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    is_global = db.Column(db.Boolean, default=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    start_time = db.Column(db.DateTime, nullable=False)
    duration_minutes = db.Column(db.Integer, default=60)
    meeting_link = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    mentor = db.relationship('User', foreign_keys=[mentor_id])
    client = db.relationship('User', foreign_keys=[client_id])
    
    def to_dict(self):
        return {
            'id': self.id,
            'mentor_id': self.mentor_id,
            'client_id': self.client_id,
            'is_global': self.is_global,
            'title': self.title,
            'description': self.description,
            'start_time': self.start_time.isoformat(),
            'duration_minutes': self.duration_minutes,
            'meeting_link': self.meeting_link,
            'mentor_name': self.mentor.full_name if self.mentor else None,
            'client_name': self.client.full_name if self.client else None
        }
