CREATE TABLE brs_event_results (
    id TEXT PRIMARY KEY NOT NULL,
    course_id TEXT NOT NULL REFERENCES brs_student_courses(id),
    plan_id TEXT NOT NULL,
    event_code TEXT NOT NULL,
    UNIQUE(course_id,plan_id,event_code),
    FOREIGN KEY(plan_id,event_code) REFERENCES brs_events(plan_id,code)
) WITHOUT ROWID;

CREATE TABLE brs_attempt_submissions (
    enrollment_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    event_code TEXT NOT NULL,
    attempt_no INTEGER NOT NULL CHECK(typeof(attempt_no)='integer' AND attempt_no BETWEEN 2 AND 10),
    registered_at INTEGER NOT NULL CHECK(typeof(registered_at)='integer' AND registered_at>0),
    registered_by TEXT NOT NULL REFERENCES staff_profiles(user_id),
    PRIMARY KEY(enrollment_id,plan_id,event_code,attempt_no),
    FOREIGN KEY(enrollment_id,course_id) REFERENCES brs_enrollments(id,course_id),
    FOREIGN KEY(plan_id,event_code) REFERENCES brs_events(plan_id,code)
) WITHOUT ROWID;

CREATE TABLE brs_attempt_drafts (
    enrollment_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    event_code TEXT NOT NULL,
    attempt_no INTEGER NOT NULL CHECK(typeof(attempt_no)='integer' AND attempt_no BETWEEN 1 AND 10),
    points INTEGER NOT NULL CHECK(typeof(points)='integer' AND points BETWEEN 0 AND 10000),
    version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version>0),
    author_id TEXT NOT NULL REFERENCES staff_profiles(user_id),
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(enrollment_id,plan_id,event_code,attempt_no),
    FOREIGN KEY(enrollment_id,course_id) REFERENCES brs_enrollments(id,course_id),
    FOREIGN KEY(plan_id,event_code) REFERENCES brs_events(plan_id,code)
) WITHOUT ROWID;

CREATE TABLE brs_attempt_versions (
    id TEXT PRIMARY KEY NOT NULL,
    result_id TEXT NOT NULL REFERENCES brs_event_results(id),
    enrollment_id TEXT NOT NULL REFERENCES brs_enrollments(id),
    attempt_no INTEGER NOT NULL CHECK(typeof(attempt_no)='integer' AND attempt_no BETWEEN 1 AND 10),
    revision_no INTEGER NOT NULL CHECK(typeof(revision_no)='integer' AND revision_no>0),
    result_version INTEGER NOT NULL CHECK(typeof(result_version)='integer' AND result_version>0),
    points INTEGER NOT NULL CHECK(typeof(points)='integer' AND points BETWEEN 0 AND 10000),
    actor_id TEXT NOT NULL REFERENCES staff_profiles(user_id),
    published_at INTEGER NOT NULL CHECK(typeof(published_at)='integer' AND published_at>0),
    reason TEXT,
    CHECK((revision_no=1 AND reason IS NULL) OR (revision_no>1 AND reason IS NOT NULL AND length(trim(reason)) BETWEEN 3 AND 500)),
    UNIQUE(result_id,attempt_no,revision_no),
    UNIQUE(result_id,result_version)
) WITHOUT ROWID;

CREATE TABLE brs_operation_receipts (
    actor_id TEXT NOT NULL REFERENCES staff_profiles(user_id),
    command TEXT NOT NULL CHECK(command IN ('publish','correct')),
    request_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64),
    version_id TEXT NOT NULL REFERENCES brs_attempt_versions(id),
    PRIMARY KEY(actor_id,command,request_key)
) WITHOUT ROWID;

CREATE TRIGGER brs_result_insert_guard BEFORE INSERT ON brs_event_results
WHEN EXISTS(SELECT 1 FROM brs_event_results r WHERE r.id=NEW.id
       OR (r.course_id,r.plan_id,r.event_code)=(NEW.course_id,NEW.plan_id,NEW.event_code))
  OR NOT EXISTS(SELECT 1 FROM brs_student_courses c JOIN brs_plans p ON p.curriculum_id=c.curriculum_id
      JOIN brs_events e ON e.plan_id=p.id WHERE c.id=NEW.course_id AND p.id=NEW.plan_id
      AND p.locked_at IS NOT NULL AND e.code=NEW.event_code)
BEGIN SELECT RAISE(ABORT,'Invalid BRS result identity'); END;

CREATE TRIGGER brs_submission_insert_guard BEFORE INSERT ON brs_attempt_submissions
WHEN EXISTS(SELECT 1 FROM brs_attempt_submissions s WHERE
    (s.enrollment_id,s.plan_id,s.event_code,s.attempt_no)=(NEW.enrollment_id,NEW.plan_id,NEW.event_code,NEW.attempt_no))
 OR NOT EXISTS(SELECT 1 FROM brs_enrollments n JOIN brs_offerings o ON o.id=n.offering_id
    JOIN brs_plans p ON p.id=o.plan_id JOIN brs_events e ON e.plan_id=p.id AND e.code=NEW.event_code
    WHERE n.id=NEW.enrollment_id AND n.course_id=NEW.course_id AND o.plan_id=NEW.plan_id
    AND p.locked_at IS NOT NULL AND n.ends_on IS NULL AND NEW.attempt_no<=e.attempt_limit
    AND date(NEW.registered_at,'unixepoch','+3 hours') BETWEEN n.starts_on AND e.retake_until)
BEGIN SELECT RAISE(ABORT,'Invalid BRS submission'); END;

CREATE TRIGGER brs_attempt_version_insert_guard BEFORE INSERT ON brs_attempt_versions
WHEN EXISTS(SELECT 1 FROM brs_attempt_versions v WHERE v.id=NEW.id
       OR (v.result_id=NEW.result_id AND (v.result_version=NEW.result_version
       OR (v.attempt_no=NEW.attempt_no AND v.revision_no=NEW.revision_no))))
 OR NOT EXISTS(SELECT 1 FROM brs_event_results r JOIN brs_events e ON e.plan_id=r.plan_id AND e.code=r.event_code
    JOIN brs_enrollments n ON n.course_id=r.course_id JOIN brs_offerings o ON o.id=n.offering_id AND o.plan_id=r.plan_id
    WHERE r.id=NEW.result_id AND n.id=NEW.enrollment_id AND n.ends_on IS NULL
    AND NEW.points<=e.maximum AND NEW.attempt_no<=e.attempt_limit
    AND (NEW.attempt_no=1 OR EXISTS(SELECT 1 FROM brs_attempt_submissions s WHERE
        (s.enrollment_id,s.plan_id,s.event_code,s.attempt_no)=(n.id,r.plan_id,r.event_code,NEW.attempt_no)
        AND s.registered_at<=NEW.published_at)))
 OR NEW.result_version!=1+COALESCE((SELECT max(result_version) FROM brs_attempt_versions WHERE result_id=NEW.result_id),0)
 OR (NEW.revision_no=1 AND NEW.attempt_no!=1+COALESCE((SELECT max(attempt_no) FROM brs_attempt_versions WHERE result_id=NEW.result_id),0))
 OR (NEW.revision_no>1 AND NOT EXISTS(SELECT 1 FROM brs_attempt_versions v
    WHERE v.result_id=NEW.result_id AND v.attempt_no=NEW.attempt_no AND v.enrollment_id=NEW.enrollment_id
    AND v.revision_no=NEW.revision_no-1 AND v.points!=NEW.points AND v.published_at<=NEW.published_at
    AND NOT EXISTS(SELECT 1 FROM brs_attempt_versions newer WHERE newer.result_id=v.result_id
        AND newer.attempt_no=v.attempt_no AND newer.revision_no>v.revision_no)))
BEGIN SELECT RAISE(ABORT,'Invalid BRS attempt version'); END;

CREATE TRIGGER brs_receipt_insert_guard BEFORE INSERT ON brs_operation_receipts
WHEN EXISTS(SELECT 1 FROM brs_operation_receipts r WHERE
    (r.actor_id,r.command,r.request_key)=(NEW.actor_id,NEW.command,NEW.request_key))
BEGIN SELECT RAISE(ABORT,'BRS operation receipt is immutable'); END;

CREATE TRIGGER brs_event_results_no_update BEFORE UPDATE ON brs_event_results
BEGIN SELECT RAISE(ABORT,'Published BRS record is immutable'); END;

CREATE TRIGGER brs_event_results_no_delete BEFORE DELETE ON brs_event_results
BEGIN SELECT RAISE(ABORT,'Published BRS record is immutable'); END;

CREATE TRIGGER brs_attempt_submissions_no_update BEFORE UPDATE ON brs_attempt_submissions
BEGIN SELECT RAISE(ABORT,'Published BRS record is immutable'); END;

CREATE TRIGGER brs_attempt_submissions_no_delete BEFORE DELETE ON brs_attempt_submissions
BEGIN SELECT RAISE(ABORT,'Published BRS record is immutable'); END;

CREATE TRIGGER brs_attempt_versions_no_update BEFORE UPDATE ON brs_attempt_versions
BEGIN SELECT RAISE(ABORT,'Published BRS record is immutable'); END;

CREATE TRIGGER brs_attempt_versions_no_delete BEFORE DELETE ON brs_attempt_versions
BEGIN SELECT RAISE(ABORT,'Published BRS record is immutable'); END;

CREATE TRIGGER brs_operation_receipts_no_update BEFORE UPDATE ON brs_operation_receipts
BEGIN SELECT RAISE(ABORT,'Published BRS record is immutable'); END;

CREATE TRIGGER brs_operation_receipts_no_delete BEFORE DELETE ON brs_operation_receipts
BEGIN SELECT RAISE(ABORT,'Published BRS record is immutable'); END;
