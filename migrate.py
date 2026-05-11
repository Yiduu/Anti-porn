import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def run_migrations():
    print("🚀 Starting manual database migration...")
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # 1. Base tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                anonymous_name TEXT,
                recovery_role TEXT DEFAULT 'user',
                profile_complete BOOLEAN DEFAULT FALSE,
                recovery_notifications BOOLEAN DEFAULT TRUE,
                bio TEXT,
                streak INTEGER DEFAULT 0,
                last_checkin DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recovery_mentorships (
                id SERIAL PRIMARY KEY,
                mentor_id TEXT REFERENCES users(user_id),
                mentee_id TEXT REFERENCES users(user_id),
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recovery_messages (
                id SERIAL PRIMARY KEY,
                sender_id TEXT REFERENCES users(user_id),
                receiver_id TEXT REFERENCES users(user_id),
                content TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recovery_live_sessions (
                id SERIAL PRIMARY KEY,
                title TEXT,
                description TEXT,
                scheduled_time TIMESTAMP,
                jitsi_url TEXT,
                created_by TEXT REFERENCES users(user_id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS recovery_reflections (
                id SERIAL PRIMARY KEY,
                user_id TEXT REFERENCES users(user_id),
                content TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 2. Schema evolved columns
        cols = {
            "real_name": "TEXT",
            "sex": "TEXT",
            "age": "TEXT",
            "educational_level": "TEXT",
            "work_status": "TEXT",
            "mentorship_experience_years": "TEXT",
            "professional_training": "TEXT",
            "self_recovery_testimony": "TEXT"
        }
        for col, dtype in cols.items():
            cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {dtype}")
            
        cur.execute("ALTER TABLE recovery_mentorships ALTER COLUMN status SET DEFAULT 'pending'")
        
        conn.commit()
        print("✅ Database migrations successful!")
        cur.close()
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    run_migrations()
