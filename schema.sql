-- Database Schema for Christian Recovery Companion

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    anonymous_name TEXT NOT NULL,
    recovery_role TEXT DEFAULT 'user', -- 'user', 'mentor', 'admin'
    recovery_streak INT DEFAULT 0,
    recovery_last_checkin DATE,
    recovery_notifications BOOLEAN DEFAULT TRUE,
    bio TEXT,
    
    -- New Registration Fields
    sex TEXT, -- 'male', 'female'
    age INT,
    educational_level TEXT,
    addiction_year TEXT, -- '<18', '18-22', '23-30', '>30'
    longest_free_streak INT DEFAULT 0,
    profile_complete BOOLEAN DEFAULT FALSE,
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recovery_reflections (
    id SERIAL PRIMARY KEY,
    user_id TEXT REFERENCES users(user_id),
    verse_text TEXT,
    reflection_text TEXT,
    voice_file_url TEXT,
    timestamp TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recovery_mentorships (
    id SERIAL PRIMARY KEY,
    user_id TEXT REFERENCES users(user_id),
    mentor_id TEXT REFERENCES users(user_id),
    status TEXT DEFAULT 'pending', -- 'pending', 'active', 'rejected'
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recovery_messages (
    id SERIAL PRIMARY KEY,
    mentorship_id INT REFERENCES recovery_mentorships(id),
    sender_id TEXT REFERENCES users(user_id),
    receiver_id TEXT REFERENCES users(user_id),
    content TEXT,
    timestamp TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recovery_live_sessions (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    host_id TEXT REFERENCES users(user_id),
    scheduled_time TIMESTAMP NOT NULL,
    jitsi_room TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

