DROP TRIGGER brs_course_identity_no_replace;

CREATE TRIGGER brs_course_identity_no_replace
BEFORE INSERT ON brs_student_courses
WHEN EXISTS (SELECT 1 FROM brs_student_courses WHERE id=NEW.id)
  OR EXISTS (SELECT 1 FROM brs_student_courses
             WHERE student_id=NEW.student_id AND curriculum_id=NEW.curriculum_id)
BEGIN
    SELECT RAISE(ABORT,'BRS course identity is immutable');
END;

-- Keep one durable entry per course. Hidden rowids can change during VACUUM.
CREATE TABLE brs_course_insert_ledger (
    course_id TEXT PRIMARY KEY NOT NULL REFERENCES brs_student_courses(id)
) WITHOUT ROWID;

INSERT INTO brs_course_insert_ledger(course_id) SELECT id FROM brs_student_courses;

CREATE TRIGGER brs_course_ledger_no_update
BEFORE UPDATE ON brs_course_insert_ledger
BEGIN
    SELECT RAISE(ABORT,'BRS course identity is immutable');
END;

CREATE TRIGGER brs_course_ledger_no_delete
BEFORE DELETE ON brs_course_insert_ledger
BEGIN
    SELECT RAISE(ABORT,'BRS course identity is immutable');
END;

CREATE TRIGGER brs_course_ledger_insert_guard
BEFORE INSERT ON brs_course_insert_ledger
WHEN EXISTS (SELECT 1 FROM brs_course_insert_ledger WHERE course_id=NEW.course_id)
  OR NOT EXISTS (SELECT 1 FROM brs_student_courses WHERE id=NEW.course_id)
BEGIN
    SELECT RAISE(ABORT,'BRS course identity is immutable');
END;

-- REPLACE on an explicit rowid can silently remove an old course when
-- recursive_triggers is OFF. A successful new row must increase the count
-- by exactly one, even on a connection with foreign_keys disabled.
CREATE TRIGGER brs_course_identity_record_insert
AFTER INSERT ON brs_student_courses
BEGIN
    SELECT CASE WHEN (SELECT count(*) FROM brs_student_courses)
        != 1 + (SELECT count(*) FROM brs_course_insert_ledger)
        THEN RAISE(ABORT,'BRS course identity is immutable') END;
    INSERT INTO brs_course_insert_ledger(course_id) VALUES (NEW.id);
END;
