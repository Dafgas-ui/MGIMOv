CREATE TABLE coursework_assignments_next (
    id TEXT PRIMARY KEY NOT NULL,
    offering_id TEXT NOT NULL REFERENCES brs_offerings(id),
    created_by TEXT NOT NULL REFERENCES staff_profiles(user_id),
    kind TEXT NOT NULL CHECK(kind IN ('lab','test','practice','other')),
    title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 160),
    description TEXT NOT NULL CHECK(length(trim(description)) BETWEEN 1 AND 4000),
    due_at INTEGER NOT NULL CHECK(typeof(due_at)='integer' AND due_at>0),
    mode TEXT NOT NULL CHECK(mode IN ('in_person','online','both')),
    created_at INTEGER NOT NULL CHECK(typeof(created_at)='integer' AND created_at>0),
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published')),
    version INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
    event_code TEXT
) WITHOUT ROWID;
INSERT INTO coursework_assignments_next (id,offering_id,created_by,kind,title,description,due_at,mode,created_at)
SELECT id,offering_id,created_by,kind,title,description,due_at,mode,created_at FROM coursework_assignments;
DROP TABLE coursework_assignments;
ALTER TABLE coursework_assignments_next RENAME TO coursework_assignments;
CREATE INDEX coursework_assignments_offering ON coursework_assignments(offering_id,id);
CREATE UNIQUE INDEX coursework_one_event_per_offering
    ON coursework_assignments(offering_id,event_code) WHERE event_code IS NOT NULL;

CREATE TABLE coursework_recipients (
    assignment_id TEXT NOT NULL REFERENCES coursework_assignments(id),
    course_id TEXT NOT NULL REFERENCES brs_student_courses(id),
    enrollment_id TEXT NOT NULL REFERENCES brs_enrollments(id),
    version INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
    PRIMARY KEY(assignment_id,course_id)
) WITHOUT ROWID;

CREATE TABLE coursework_attempts (
    assignment_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    number INTEGER NOT NULL CHECK(number>0),
    method TEXT NOT NULL CHECK(method IN ('text','in_person')),
    response TEXT,
    submitted_at INTEGER NOT NULL,
    submitted_by TEXT NOT NULL REFERENCES users(id),
    late INTEGER NOT NULL CHECK(late IN (0,1)),
    CHECK((method='text' AND response IS NOT NULL AND length(trim(response)) BETWEEN 1 AND 4000)
       OR (method='in_person' AND response IS NULL)),
    PRIMARY KEY(assignment_id,course_id,number),
    FOREIGN KEY(assignment_id,course_id) REFERENCES coursework_recipients(assignment_id,course_id)
) WITHOUT ROWID;

CREATE TABLE coursework_reviews (
    assignment_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,
    revision INTEGER NOT NULL CHECK(revision>0),
    decision TEXT NOT NULL CHECK(decision IN ('reviewed','returned','retry_allowed')),
    points INTEGER CHECK(points IS NULL OR (typeof(points)='integer' AND points BETWEEN 0 AND 100)),
    comment TEXT NOT NULL,
    reviewer_id TEXT NOT NULL REFERENCES staff_profiles(user_id),
    reviewed_at INTEGER NOT NULL,
    CHECK(decision='reviewed' OR points IS NULL),
    PRIMARY KEY(assignment_id,course_id,attempt_no,revision),
    FOREIGN KEY(assignment_id,course_id,attempt_no)
        REFERENCES coursework_attempts(assignment_id,course_id,number)
) WITHOUT ROWID;

CREATE TABLE coursework_receipts (
    actor_id TEXT NOT NULL REFERENCES users(id),
    request_key TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    result TEXT NOT NULL CHECK(json_valid(result)),
    PRIMARY KEY(actor_id,request_key)
) WITHOUT ROWID;

CREATE TRIGGER coursework_event_update BEFORE UPDATE OF event_code,offering_id ON coursework_assignments
WHEN NEW.offering_id<>OLD.offering_id OR (OLD.status='published' AND NEW.event_code IS NOT OLD.event_code)
    OR (NEW.event_code IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM brs_events e JOIN brs_offerings o ON o.plan_id=e.plan_id
        WHERE o.id=NEW.offering_id AND e.code=NEW.event_code))
BEGIN SELECT RAISE(ABORT,'Invalid coursework event binding'); END;

CREATE TRIGGER coursework_event_insert BEFORE INSERT ON coursework_assignments
WHEN NEW.event_code IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM brs_events e JOIN brs_offerings o ON o.plan_id=e.plan_id
    WHERE o.id=NEW.offering_id AND e.code=NEW.event_code)
BEGIN SELECT RAISE(ABORT,'Invalid coursework event binding'); END;

CREATE TRIGGER coursework_recipient_insert BEFORE INSERT ON coursework_recipients
WHEN NOT EXISTS (SELECT 1 FROM coursework_assignments a JOIN brs_enrollments n
    ON n.offering_id=a.offering_id
    WHERE a.id=NEW.assignment_id AND n.id=NEW.enrollment_id AND n.course_id=NEW.course_id)
BEGIN SELECT RAISE(ABORT,'Invalid coursework recipient'); END;
