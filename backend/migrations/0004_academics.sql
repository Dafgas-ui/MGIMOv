CREATE TABLE semesters (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 100),
    starts_on TEXT NOT NULL CHECK(starts_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    ends_on TEXT NOT NULL CHECK(ends_on >= starts_on)
);
CREATE TABLE curriculum_items (
    id TEXT PRIMARY KEY NOT NULL,
    program_id TEXT NOT NULL REFERENCES programs(id),
    subject_id TEXT NOT NULL REFERENCES subjects(id),
    semester_id TEXT NOT NULL REFERENCES semesters(id),
    control TEXT NOT NULL CHECK(control IN ('exam','credit','graded_credit')),
    required INTEGER NOT NULL DEFAULT 1 CHECK(required IN (0,1)),
    UNIQUE(program_id,subject_id,semester_id,control)
);
CREATE TABLE assessments (
    id TEXT PRIMARY KEY NOT NULL,
    curriculum_id TEXT NOT NULL REFERENCES curriculum_items(id),
    group_id TEXT NOT NULL REFERENCES study_groups(id),
    scheduled_on TEXT,
    deadline_on TEXT,
    status TEXT NOT NULL CHECK(status IN ('scheduled','completed','not_held','cancelled')),
    CHECK(scheduled_on IS NULL OR scheduled_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    CHECK(deadline_on IS NULL OR deadline_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    UNIQUE(curriculum_id,group_id)
);
CREATE TABLE student_assessments (
    id TEXT PRIMARY KEY NOT NULL,
    student_id TEXT NOT NULL REFERENCES student_profiles(user_id),
    assessment_id TEXT NOT NULL REFERENCES assessments(id),
    UNIQUE(student_id,assessment_id)
);
CREATE INDEX student_assessments_owner ON student_assessments(student_id);
CREATE TABLE assessment_attempts (
    id TEXT PRIMARY KEY NOT NULL,
    assignment_id TEXT NOT NULL REFERENCES student_assessments(id),
    number INTEGER NOT NULL CHECK(number > 0),
    outcome TEXT NOT NULL CHECK(outcome IN ('graded','pass','fail','absent')),
    grade INTEGER,
    performed_on TEXT NOT NULL CHECK(performed_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    recorded_at INTEGER NOT NULL CHECK(recorded_at > 0),
    CHECK((outcome='graded' AND grade IS NOT NULL AND grade BETWEEN 2 AND 5 AND typeof(grade)='integer') OR (outcome!='graded' AND grade IS NULL)),
    UNIQUE(assignment_id,number)
);
CREATE TRIGGER assessment_program_insert BEFORE INSERT ON assessments BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM curriculum_items c JOIN study_groups g ON g.program_id=c.program_id
        WHERE c.id=NEW.curriculum_id AND g.id=NEW.group_id
    ) THEN RAISE(ABORT,'Assessment program mismatch') END;
END;
CREATE TRIGGER assignment_group_insert BEFORE INSERT ON student_assessments BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM student_profiles p JOIN assessments a ON a.group_id=p.group_id
        WHERE p.user_id=NEW.student_id AND a.id=NEW.assessment_id
    ) THEN RAISE(ABORT,'Assignment group mismatch') END;
END;
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
