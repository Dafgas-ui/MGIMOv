CREATE TABLE attendance_journals (
 lesson_id TEXT PRIMARY KEY NOT NULL REFERENCES lessons(id),
 version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version>=1)
) WITHOUT ROWID;
CREATE TABLE attendance_events (
 lesson_id TEXT NOT NULL REFERENCES attendance_journals(lesson_id),
 version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version>=1),
 kind TEXT NOT NULL CHECK(kind IN ('roster','mark')),
 actor_id TEXT NOT NULL REFERENCES staff_profiles(user_id),
 created_at INTEGER NOT NULL CHECK(typeof(created_at)='integer' AND created_at>0),
 reason TEXT NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 300),
 payload TEXT NOT NULL CHECK(json_valid(payload)),
 PRIMARY KEY(lesson_id,version)
) WITHOUT ROWID;
CREATE TRIGGER attendance_event_insert BEFORE INSERT ON attendance_events
WHEN EXISTS(SELECT 1 FROM attendance_events WHERE (lesson_id,version)=(NEW.lesson_id,NEW.version))
 OR NEW.version<>coalesce((SELECT max(version)+1 FROM attendance_events WHERE lesson_id=NEW.lesson_id),1)
 OR NOT EXISTS(SELECT 1 FROM attendance_journals WHERE lesson_id=NEW.lesson_id AND version=NEW.version)
BEGIN SELECT RAISE(ABORT,'Invalid attendance history version'); END;
CREATE TRIGGER attendance_event_update BEFORE UPDATE ON attendance_events
BEGIN SELECT RAISE(ABORT,'Attendance history is immutable'); END;
CREATE TRIGGER attendance_event_delete BEFORE DELETE ON attendance_events
BEGIN SELECT RAISE(ABORT,'Attendance history is immutable'); END;
CREATE TRIGGER attendance_journal_insert BEFORE INSERT ON attendance_journals
WHEN EXISTS(SELECT 1 FROM attendance_journals WHERE lesson_id=NEW.lesson_id)
BEGIN SELECT RAISE(ABORT,'Attendance journal identity is immutable'); END;
CREATE TRIGGER attendance_journal_update BEFORE UPDATE ON attendance_journals
WHEN NEW.lesson_id IS NOT OLD.lesson_id OR NEW.version<>OLD.version+1
BEGIN SELECT RAISE(ABORT,'Invalid attendance journal version'); END;
CREATE TRIGGER attendance_journal_delete BEFORE DELETE ON attendance_journals
BEGIN SELECT RAISE(ABORT,'Attendance journal is immutable'); END;
CREATE TRIGGER attendance_lesson_delete BEFORE DELETE ON lessons
WHEN EXISTS(SELECT 1 FROM attendance_journals WHERE lesson_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'Attendance lesson has history'); END;
CREATE TRIGGER attendance_lesson_rekey BEFORE UPDATE OF id,group_id,subject_id ON lessons
WHEN EXISTS(SELECT 1 FROM attendance_journals WHERE lesson_id=OLD.id)
 AND (NEW.id IS NOT OLD.id OR NEW.group_id IS NOT OLD.group_id OR NEW.subject_id IS NOT OLD.subject_id)
BEGIN SELECT RAISE(ABORT,'Attendance lesson identity is immutable'); END;
CREATE TRIGGER attendance_lesson_replace BEFORE INSERT ON lessons
WHEN EXISTS(SELECT 1 FROM attendance_journals WHERE lesson_id=NEW.id)
BEGIN SELECT RAISE(ABORT,'Attendance lesson has history'); END;
