-- Preserve existing staff history; QR events have the real student as actor.
DROP TRIGGER attendance_event_insert;
DROP TRIGGER attendance_event_update;
DROP TRIGGER attendance_event_delete;
CREATE TABLE attendance_events_next (
 lesson_id TEXT NOT NULL REFERENCES attendance_journals(lesson_id),
 version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version>=1),
 kind TEXT NOT NULL CHECK(kind IN ('roster','mark','qr_mark')),
 actor_id TEXT NOT NULL REFERENCES users(id),
 created_at INTEGER NOT NULL CHECK(typeof(created_at)='integer' AND created_at>0),
 reason TEXT NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 300),
 payload TEXT NOT NULL CHECK(json_valid(payload)),
 PRIMARY KEY(lesson_id,version)
) WITHOUT ROWID;
INSERT INTO attendance_events_next SELECT * FROM attendance_events;
DROP TABLE attendance_events;
ALTER TABLE attendance_events_next RENAME TO attendance_events;
CREATE TRIGGER attendance_event_insert BEFORE INSERT ON attendance_events
WHEN EXISTS(SELECT 1 FROM attendance_events WHERE (lesson_id,version)=(NEW.lesson_id,NEW.version))
 OR NEW.version<>coalesce((SELECT max(version)+1 FROM attendance_events WHERE lesson_id=NEW.lesson_id),1)
 OR NOT EXISTS(SELECT 1 FROM attendance_journals WHERE lesson_id=NEW.lesson_id AND version=NEW.version)
 OR (NEW.kind IN ('roster','mark') AND NOT EXISTS(SELECT 1 FROM staff_profiles WHERE user_id=NEW.actor_id))
 OR (NEW.kind='qr_mark' AND (NOT EXISTS(SELECT 1 FROM student_profiles WHERE user_id=NEW.actor_id)
     OR json_extract(NEW.payload,'$.student_id') IS NOT NEW.actor_id
     OR json_extract(NEW.payload,'$.status') IS NOT 'present'))
BEGIN SELECT RAISE(ABORT,'Invalid attendance history version or actor'); END;
CREATE TRIGGER attendance_event_update BEFORE UPDATE ON attendance_events
BEGIN SELECT RAISE(ABORT,'Attendance history is immutable'); END;
CREATE TRIGGER attendance_event_delete BEFORE DELETE ON attendance_events
BEGIN SELECT RAISE(ABORT,'Attendance history is immutable'); END;

CREATE TABLE attendance_qr_sessions (
 id TEXT PRIMARY KEY NOT NULL,
 lesson_id TEXT NOT NULL REFERENCES attendance_journals(lesson_id),
 actor_id TEXT NOT NULL REFERENCES staff_profiles(user_id),
 -- Historical identifier: normal session cleanup must not delete QR history.
 issuer_session TEXT NOT NULL CHECK(typeof(issuer_session)='text' AND length(issuer_session) BETWEEN 1 AND 100),
 lesson_version INTEGER NOT NULL CHECK(lesson_version>0),
 roster_version INTEGER NOT NULL CHECK(roster_version>0),
 roster_hash TEXT NOT NULL CHECK(length(roster_hash)=64),
 token_hash TEXT NOT NULL UNIQUE CHECK(length(token_hash)=64),
 request_key TEXT NOT NULL CHECK(length(request_key) BETWEEN 16 AND 100),
 expected_version INTEGER NOT NULL CHECK(expected_version>0),
 created_at INTEGER NOT NULL CHECK(created_at>0),
 expires_at INTEGER NOT NULL CHECK(expires_at>created_at AND expires_at<=created_at+60),
 revoked_at INTEGER CHECK(revoked_at IS NULL OR revoked_at>=created_at),
 UNIQUE(issuer_session,lesson_id,request_key)
) WITHOUT ROWID;
CREATE INDEX attendance_qr_lesson ON attendance_qr_sessions(lesson_id,expires_at);
CREATE TABLE attendance_qr_receipts (
 qr_id TEXT NOT NULL REFERENCES attendance_qr_sessions(id),
 student_id TEXT NOT NULL REFERENCES student_profiles(user_id),
 created_at INTEGER NOT NULL CHECK(created_at>0),
 outcome TEXT NOT NULL CHECK(outcome IN ('present','manual_priority','already_present')),
 attendance_version INTEGER NOT NULL CHECK(attendance_version>0),
 PRIMARY KEY(qr_id,student_id)
) WITHOUT ROWID;
CREATE TRIGGER attendance_qr_session_insert BEFORE INSERT ON attendance_qr_sessions
WHEN EXISTS(SELECT 1 FROM attendance_qr_sessions WHERE id=NEW.id OR token_hash=NEW.token_hash
 OR (issuer_session,lesson_id,request_key)=(NEW.issuer_session,NEW.lesson_id,NEW.request_key))
BEGIN SELECT RAISE(ABORT,'QR session identity is immutable'); END;
CREATE TRIGGER attendance_qr_session_update BEFORE UPDATE ON attendance_qr_sessions
WHEN NEW.id IS NOT OLD.id OR NEW.lesson_id IS NOT OLD.lesson_id OR NEW.actor_id IS NOT OLD.actor_id
 OR NEW.issuer_session IS NOT OLD.issuer_session OR NEW.lesson_version IS NOT OLD.lesson_version
 OR NEW.roster_version IS NOT OLD.roster_version OR NEW.roster_hash IS NOT OLD.roster_hash
 OR NEW.token_hash IS NOT OLD.token_hash OR NEW.request_key IS NOT OLD.request_key
 OR NEW.expected_version IS NOT OLD.expected_version OR NEW.created_at IS NOT OLD.created_at
 OR NEW.expires_at IS NOT OLD.expires_at OR OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL
BEGIN SELECT RAISE(ABORT,'QR session is immutable except revocation'); END;
CREATE TRIGGER attendance_qr_session_delete BEFORE DELETE ON attendance_qr_sessions
BEGIN SELECT RAISE(ABORT,'QR session history is immutable'); END;
CREATE TRIGGER attendance_qr_receipt_insert BEFORE INSERT ON attendance_qr_receipts
WHEN EXISTS(SELECT 1 FROM attendance_qr_receipts WHERE (qr_id,student_id)=(NEW.qr_id,NEW.student_id))
BEGIN SELECT RAISE(ABORT,'QR receipt identity is immutable'); END;
CREATE TRIGGER attendance_qr_receipt_update BEFORE UPDATE ON attendance_qr_receipts
BEGIN SELECT RAISE(ABORT,'QR receipt is immutable'); END;
CREATE TRIGGER attendance_qr_receipt_delete BEFORE DELETE ON attendance_qr_receipts
BEGIN SELECT RAISE(ABORT,'QR receipt is immutable'); END;
