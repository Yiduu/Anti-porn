-- Database Schema for Christian Recovery Companion

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    anonymous_name TEXT NOT NULL,
    real_name TEXT, -- New: for mentors (admin only)
    recovery_role TEXT DEFAULT 'user', -- 'user', 'mentor', 'admin'
    recovery_streak INT DEFAULT 0,
    recovery_last_checkin DATE,
    recovery_notifications BOOLEAN DEFAULT TRUE,
    bio TEXT,
    
    -- Registration Fields
    sex TEXT,
    age INT,
    educational_level TEXT,
    addiction_year TEXT,
    longest_free_streak INT DEFAULT 0,
    profile_complete BOOLEAN DEFAULT FALSE,

    -- Extended Mentor Fields
    work_status TEXT, -- 'Employed full-time', 'Employed part-time', 'Student', 'Unemployed', 'Retired'
    mentorship_experience_years INT DEFAULT 0,
    professional_training TEXT,
    self_recovery_testimony TEXT,
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recovery_reflections (
    id SERIAL PRIMARY KEY,
    user_id TEXT REFERENCES users(user_id) ON DELETE CASCADE,
    verse_text TEXT,
    reflection_text TEXT,
    voice_file_url TEXT,
    timestamp TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recovery_mentorships (
    id SERIAL PRIMARY KEY,
    user_id TEXT REFERENCES users(user_id) ON DELETE CASCADE,
    mentor_id TEXT REFERENCES users(user_id) ON DELETE CASCADE,
    status TEXT DEFAULT 'pending', -- 'pending', 'active', 'rejected'
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recovery_messages (
    id SERIAL PRIMARY KEY,
    mentorship_id INT REFERENCES recovery_mentorships(id) ON DELETE CASCADE,
    sender_id TEXT REFERENCES users(user_id) ON DELETE CASCADE,
    receiver_id TEXT REFERENCES users(user_id) ON DELETE CASCADE,
    content TEXT,
    timestamp TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recovery_live_sessions (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    host_id TEXT REFERENCES users(user_id) ON DELETE CASCADE,
    scheduled_time TIMESTAMP NOT NULL,
    jitsi_room TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);


