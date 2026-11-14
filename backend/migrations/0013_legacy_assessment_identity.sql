-- Refuse to adopt a previously corrupted official source. Its original owner
-- cannot be recovered from the current parent rows.
CREATE TEMP TABLE legacy_source_preflight (valid INTEGER NOT NULL);
CREATE TEMP TRIGGER legacy_source_preflight_guard BEFORE INSERT ON legacy_source_preflight
WHEN NEW.valid IS NOT 1
BEGIN SELECT RAISE(ABORT,'Conflicting legacy and Phase 3 official sources'); END;
INSERT INTO legacy_source_preflight SELECT NOT EXISTS (
    SELECT 1 FROM assessment_attempts t
    JOIN student_assessments sa ON sa.id=t.assignment_id
    JOIN assessments a ON a.id=sa.assessment_id
    JOIN brs_student_courses c ON (c.student_id,c.curriculum_id)=(sa.student_id,a.curriculum_id)
    JOIN attestation_positions p ON p.course_id=c.id
);
DROP TABLE legacy_source_preflight;

-- Guard every declared conflict key before SQLite can delete a victim.
-- Before an INSERT, NEW.rowid is undefined when the caller omits it.
-- A replacement through rowid that retains the ID hits the declared-key
-- guard. A replacement that changes the ID is checked for orphaned history
-- after the insert, using the final rows rather than NEW.rowid.
CREATE TRIGGER legacy_assessment_insert_guard BEFORE INSERT ON assessments
WHEN EXISTS (
    SELECT 1 FROM assessments a
    WHERE (a.id=NEW.id OR (a.curriculum_id,a.group_id)=(NEW.curriculum_id,NEW.group_id))
    AND EXISTS(SELECT 1 FROM student_assessments sa
        JOIN assessment_attempts t ON t.assignment_id=sa.id WHERE sa.assessment_id=a.id)
)
BEGIN SELECT RAISE(ABORT,'Legacy assessment identity is immutable'); END;

CREATE TRIGGER legacy_assignment_insert_guard BEFORE INSERT ON student_assessments
WHEN EXISTS (
    SELECT 1 FROM student_assessments sa
    WHERE (sa.id=NEW.id OR (sa.student_id,sa.assessment_id)=(NEW.student_id,NEW.assessment_id))
    AND EXISTS(SELECT 1 FROM assessment_attempts WHERE assignment_id=sa.id)
)
BEGIN SELECT RAISE(ABORT,'Legacy assignment identity is immutable'); END;

CREATE TRIGGER legacy_assessment_orphan_guard AFTER INSERT ON assessments
WHEN EXISTS (
    SELECT 1 FROM student_assessments sa JOIN assessment_attempts t ON t.assignment_id=sa.id
    WHERE NOT EXISTS(SELECT 1 FROM assessments a WHERE a.id=sa.assessment_id)
)
BEGIN SELECT RAISE(ABORT,'Legacy assessment identity is immutable'); END;

CREATE TRIGGER legacy_assignment_orphan_guard AFTER INSERT ON student_assessments
WHEN EXISTS (
    SELECT 1 FROM assessment_attempts t
    WHERE NOT EXISTS(SELECT 1 FROM student_assessments sa WHERE sa.id=t.assignment_id)
)
BEGIN SELECT RAISE(ABORT,'Legacy assignment identity is immutable'); END;

-- UPDATE OR REPLACE can use an unprotected row to evict a protected one.
CREATE TRIGGER legacy_assessment_update_collision BEFORE UPDATE ON assessments
WHEN EXISTS (
    SELECT 1 FROM assessments a WHERE a.rowid!=OLD.rowid
    AND (a.id=NEW.id OR (a.curriculum_id,a.group_id)=(NEW.curriculum_id,NEW.group_id) OR a.rowid=NEW.rowid)
    AND EXISTS(SELECT 1 FROM student_assessments sa
        JOIN assessment_attempts t ON t.assignment_id=sa.id WHERE sa.assessment_id=a.id)
)
BEGIN SELECT RAISE(ABORT,'Legacy assessment identity is immutable'); END;

CREATE TRIGGER legacy_assignment_update_collision BEFORE UPDATE ON student_assessments
WHEN EXISTS (
    SELECT 1 FROM student_assessments sa WHERE sa.rowid!=OLD.rowid
    AND (sa.id=NEW.id OR (sa.student_id,sa.assessment_id)=(NEW.student_id,NEW.assessment_id) OR sa.rowid=NEW.rowid)
    AND EXISTS(SELECT 1 FROM assessment_attempts WHERE assignment_id=sa.id)
)
BEGIN SELECT RAISE(ABORT,'Legacy assignment identity is immutable'); END;

CREATE TRIGGER legacy_assessment_delete_guard BEFORE DELETE ON assessments
WHEN EXISTS(SELECT 1 FROM student_assessments sa JOIN assessment_attempts t ON t.assignment_id=sa.id
    WHERE sa.assessment_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'Legacy assessment identity is immutable'); END;

CREATE TRIGGER legacy_assignment_delete_guard BEFORE DELETE ON student_assessments
WHEN EXISTS(SELECT 1 FROM assessment_attempts WHERE assignment_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'Legacy assignment identity is immutable'); END;
