CREATE TRIGGER brs_course_identity_no_update
BEFORE UPDATE ON brs_student_courses
BEGIN
    SELECT RAISE(ABORT,'BRS course identity is immutable');
END;

CREATE TRIGGER brs_course_identity_no_delete
BEFORE DELETE ON brs_student_courses
BEGIN
    SELECT RAISE(ABORT,'BRS course identity is immutable');
END;

-- REPLACE can delete a conflicting row without firing DELETE triggers when
-- recursive_triggers is OFF. Guard explicit rowid and both declared keys.
CREATE TRIGGER brs_course_identity_no_replace
BEFORE INSERT ON brs_student_courses
WHEN EXISTS (SELECT 1 FROM brs_student_courses WHERE rowid=NEW.rowid OR id=NEW.id)
  OR EXISTS (SELECT 1 FROM brs_student_courses
             WHERE student_id=NEW.student_id AND curriculum_id=NEW.curriculum_id)
BEGIN
    SELECT RAISE(ABORT,'BRS course identity is immutable');
END;
