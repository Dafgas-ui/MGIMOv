-- Copy existing history without replaying insert-time business rules.
-- A historical assessment may have changed status since its result was recorded.
CREATE TEMP TABLE legacy_attempt_history AS
SELECT id,assignment_id,number,outcome,grade,performed_on,recorded_at FROM assessment_attempts;

DROP TABLE assessment_attempts;

CREATE TABLE assessment_attempts (
    id TEXT PRIMARY KEY NOT NULL,
    assignment_id TEXT NOT NULL REFERENCES student_assessments(id),
    number INTEGER NOT NULL CHECK(number > 0),
    outcome TEXT NOT NULL CHECK(outcome IN ('graded','pass','fail','absent')),
    grade INTEGER,
    performed_on TEXT NOT NULL CHECK(performed_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    recorded_at INTEGER NOT NULL CHECK(recorded_at > 0),
    CHECK((outcome='graded' AND grade IS NOT NULL AND grade BETWEEN 2 AND 5 AND typeof(grade)='integer')
        OR (outcome!='graded' AND grade IS NULL)),
    UNIQUE(assignment_id,number)
) WITHOUT ROWID;

INSERT INTO assessment_attempts (id,assignment_id,number,outcome,grade,performed_on,recorded_at)
SELECT id,assignment_id,number,outcome,grade,performed_on,recorded_at FROM legacy_attempt_history;
DROP TABLE legacy_attempt_history;

-- Both possible REPLACE conflicts are covered, even when implicit DELETE
-- triggers are disabled. The table has no third, hidden conflict key.
CREATE TRIGGER attempt_no_replace BEFORE INSERT ON assessment_attempts
WHEN EXISTS (SELECT 1 FROM assessment_attempts WHERE id=NEW.id)
 OR EXISTS (SELECT 1 FROM assessment_attempts WHERE (assignment_id,number)=(NEW.assignment_id,NEW.number))
BEGIN SELECT RAISE(ABORT,'Attempts are append only'); END;

CREATE TRIGGER attempt_control_insert BEFORE INSERT ON assessment_attempts BEGIN
    SELECT CASE WHEN NEW.number != 1+(SELECT count(*) FROM assessment_attempts WHERE assignment_id=NEW.assignment_id)
        THEN RAISE(ABORT,'Attempt sequence conflict') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM assessment_attempts WHERE assignment_id=NEW.assignment_id
        AND (outcome='pass' OR (outcome='graded' AND grade>=3) OR performed_on>NEW.performed_on)
    ) THEN RAISE(ABORT,'Attempt history conflict') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM student_assessments s JOIN assessments a ON a.id=s.assessment_id
        JOIN curriculum_items c ON c.id=a.curriculum_id
        WHERE s.id=NEW.assignment_id AND a.status='completed'
        AND ((c.control='credit' AND NEW.outcome IN ('pass','fail','absent'))
          OR (c.control IN ('exam','graded_credit') AND NEW.outcome IN ('graded','absent')))
    ) THEN RAISE(ABORT,'Invalid control outcome') END;
END;

CREATE TRIGGER attempt_no_update BEFORE UPDATE ON assessment_attempts BEGIN
    SELECT RAISE(ABORT,'Attempts are append only');
END;
CREATE TRIGGER attempt_no_delete BEFORE DELETE ON assessment_attempts BEGIN
    SELECT RAISE(ABORT,'Attempts are append only');
END;

CREATE TRIGGER attestation_legacy_insert BEFORE INSERT ON assessment_attempts
WHEN EXISTS(SELECT 1 FROM student_assessments sa JOIN assessments a ON a.id=sa.assessment_id
    JOIN brs_student_courses c ON (c.student_id,c.curriculum_id)=(sa.student_id,a.curriculum_id)
    JOIN attestation_positions p ON p.course_id=c.id WHERE sa.id=NEW.assignment_id)
BEGIN SELECT RAISE(ABORT,'Conflicting official result source'); END;
