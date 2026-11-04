CREATE TABLE users (
    id TEXT PRIMARY KEY NOT NULL,
    login TEXT UNIQUE NOT NULL CHECK (length(login) BETWEEN 3 AND 64 AND login = lower(login) AND login NOT GLOB '*[^a-z0-9_.-]*'),
    password_hash TEXT NOT NULL CHECK (password_hash LIKE '$argon2id$%'),
    role TEXT NOT NULL CHECK (role IN ('student', 'staff')),
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    created_at INTEGER NOT NULL
);
CREATE TABLE faculties (id TEXT PRIMARY KEY NOT NULL, name TEXT UNIQUE NOT NULL);
CREATE TABLE programs (id TEXT PRIMARY KEY NOT NULL, faculty_id TEXT NOT NULL REFERENCES faculties(id) ON DELETE RESTRICT, name TEXT NOT NULL, UNIQUE(faculty_id, name));
CREATE TABLE study_groups (id TEXT PRIMARY KEY NOT NULL, program_id TEXT NOT NULL REFERENCES programs(id) ON DELETE RESTRICT, name TEXT UNIQUE NOT NULL, course INTEGER NOT NULL CHECK (course BETWEEN 1 AND 6));
CREATE TABLE student_profiles (user_id TEXT PRIMARY KEY NOT NULL REFERENCES users(id) ON DELETE RESTRICT, full_name TEXT NOT NULL CHECK (length(full_name) BETWEEN 1 AND 150), group_id TEXT NOT NULL REFERENCES study_groups(id) ON DELETE RESTRICT);
CREATE TABLE staff_profiles (user_id TEXT PRIMARY KEY NOT NULL REFERENCES users(id) ON DELETE RESTRICT, full_name TEXT NOT NULL CHECK (length(full_name) BETWEEN 1 AND 150), position TEXT NOT NULL);
CREATE TABLE sessions (
    id TEXT PRIMARY KEY NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT UNIQUE NOT NULL CHECK (length(token_hash) = 64),
    csrf_hash TEXT NOT NULL CHECK (length(csrf_hash) = 64),
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL CHECK (expires_at > created_at),
    revoked_at INTEGER CHECK (revoked_at IS NULL OR revoked_at >= created_at)
);
CREATE INDEX sessions_user ON sessions(user_id);
CREATE TABLE auth_rate_limits (bucket TEXT PRIMARY KEY NOT NULL, window_start INTEGER NOT NULL, attempts INTEGER NOT NULL CHECK (attempts > 0));
