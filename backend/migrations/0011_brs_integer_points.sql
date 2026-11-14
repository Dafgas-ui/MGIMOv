-- Convert only known hundredths columns. Historical IDs, versions and dates stay intact.
-- The migration manager runs this script and its final schema checks in one transaction.
CREATE TEMP TABLE brs_points_preflight (valid INTEGER NOT NULL);
CREATE TEMP TRIGGER brs_points_preflight_guard BEFORE INSERT ON brs_points_preflight
WHEN NEW.valid IS NOT 1
BEGIN SELECT RAISE(ABORT,'BRS hundredths contain fractional or incompatible data'); END;
INSERT INTO brs_points_preflight SELECT NOT EXISTS (SELECT 1 FROM brs_plans
    WHERE (typeof(admission_min)!='integer' OR admission_min NOT BETWEEN 0 AND 10000 OR admission_min%100!=0));
INSERT INTO brs_points_preflight SELECT NOT EXISTS (SELECT 1 FROM brs_categories
    WHERE (typeof(maximum)!='integer' OR maximum NOT BETWEEN 1 AND 10000 OR maximum%100!=0) OR (admission_min IS NOT NULL AND (typeof(admission_min)!='integer' OR admission_min NOT BETWEEN 0 AND 10000 OR admission_min%100!=0)));
INSERT INTO brs_points_preflight SELECT NOT EXISTS (SELECT 1 FROM brs_events
    WHERE (typeof(maximum)!='integer' OR maximum NOT BETWEEN 1 AND 10000 OR maximum%100!=0) OR (admission_min IS NOT NULL AND (typeof(admission_min)!='integer' OR admission_min NOT BETWEEN 0 AND 10000 OR admission_min%100!=0)));
INSERT INTO brs_points_preflight SELECT NOT EXISTS (SELECT 1 FROM brs_scale
    WHERE (typeof(minimum)!='integer' OR minimum NOT BETWEEN 0 AND 10000 OR minimum%100!=0));
INSERT INTO brs_points_preflight SELECT NOT EXISTS (SELECT 1 FROM brs_attempt_drafts
    WHERE (typeof(points)!='integer' OR points NOT BETWEEN 0 AND 10000 OR points%100!=0));
INSERT INTO brs_points_preflight SELECT NOT EXISTS (SELECT 1 FROM brs_attempt_versions
    WHERE (typeof(points)!='integer' OR points NOT BETWEEN 0 AND 10000 OR points%100!=0));
INSERT INTO brs_points_preflight SELECT NOT EXISTS (
    SELECT 1 FROM brs_plans p WHERE p.locked_at IS NOT NULL AND (
        (SELECT COALESCE(sum(c.maximum),0) FROM brs_categories c WHERE c.plan_id=p.id)!=10000
        OR EXISTS(SELECT 1 FROM brs_categories c WHERE c.plan_id=p.id AND c.maximum!=(
            SELECT COALESCE(sum(e.maximum),0) FROM brs_events e
            WHERE (e.plan_id,e.category_code)=(c.plan_id,c.code)))
    )
);
INSERT INTO brs_points_preflight SELECT NOT EXISTS (
    SELECT 1 FROM brs_attempt_versions v JOIN brs_event_results r ON r.id=v.result_id
    JOIN brs_events e ON (e.plan_id,e.code)=(r.plan_id,r.event_code) WHERE v.points>e.maximum
);
INSERT INTO brs_points_preflight SELECT NOT EXISTS (
    SELECT 1 FROM brs_attempt_drafts d JOIN brs_events e ON (e.plan_id,e.code)=(d.plan_id,d.event_code)
    WHERE d.points>e.maximum
);

-- Source values are retained for audit. This table is sealed before the migration commits.
CREATE TABLE brs_points_archive (
    source_table TEXT NOT NULL,
    source_key TEXT NOT NULL,
    field TEXT NOT NULL,
    hundredths INTEGER NOT NULL CHECK(typeof(hundredths)='integer' AND hundredths BETWEEN 0 AND 10000),
    PRIMARY KEY(source_table,source_key,field)
) WITHOUT ROWID;
INSERT INTO brs_points_archive SELECT 'brs_plans',json_array(id),'admission_min',admission_min
    FROM brs_plans WHERE admission_min IS NOT NULL;
INSERT INTO brs_points_archive SELECT 'brs_categories',json_array(plan_id,code),'maximum',maximum
    FROM brs_categories WHERE maximum IS NOT NULL;
INSERT INTO brs_points_archive SELECT 'brs_categories',json_array(plan_id,code),'admission_min',admission_min
    FROM brs_categories WHERE admission_min IS NOT NULL;
INSERT INTO brs_points_archive SELECT 'brs_events',json_array(plan_id,code),'maximum',maximum
    FROM brs_events WHERE maximum IS NOT NULL;
INSERT INTO brs_points_archive SELECT 'brs_events',json_array(plan_id,code),'admission_min',admission_min
    FROM brs_events WHERE admission_min IS NOT NULL;
INSERT INTO brs_points_archive SELECT 'brs_scale',json_array(plan_id,minimum),'minimum',minimum
    FROM brs_scale WHERE minimum IS NOT NULL;
INSERT INTO brs_points_archive SELECT 'brs_attempt_drafts',json_array(enrollment_id,plan_id,event_code,attempt_no),'points',points
    FROM brs_attempt_drafts WHERE points IS NOT NULL;
INSERT INTO brs_points_archive SELECT 'brs_attempt_versions',json_array(id),'points',points
    FROM brs_attempt_versions WHERE points IS NOT NULL;

-- Stage explicit projections, then drop dependent tables before their parents.
CREATE TEMP TABLE stage_brs_plans AS SELECT id,curriculum_id,source,approved_on,rounding,admission_min/100 AS admission_min,locked_at,locked_by
    FROM brs_plans;
CREATE TEMP TABLE stage_brs_categories AS SELECT plan_id,code,title,maximum/100 AS maximum,admission_min/100 AS admission_min
    FROM brs_categories;
CREATE TEMP TABLE stage_brs_events AS SELECT plan_id,code,category_code,title,maximum/100 AS maximum,admission_min/100 AS admission_min,attempt_limit,retake_policy,retake_until
    FROM brs_events;
CREATE TEMP TABLE stage_brs_scale AS SELECT plan_id,minimum/100 AS minimum,outcome
    FROM brs_scale;
CREATE TEMP TABLE stage_brs_offerings AS SELECT id,plan_id,group_id
    FROM brs_offerings;
CREATE TEMP TABLE stage_brs_enrollments AS SELECT id,course_id,offering_id,starts_on,ends_on,previous_id,reason
    FROM brs_enrollments;
CREATE TEMP TABLE stage_brs_transfer_events AS SELECT enrollment_id,old_plan_id,old_event,new_plan_id,new_event
    FROM brs_transfer_events;
CREATE TEMP TABLE stage_brs_teaching_grants AS SELECT id,offering_id,staff_id,lesson_id,lesson_version,approver_id,can_confirm_final,event_code,starts_at,expires_at,revoked_at
    FROM brs_teaching_grants;
CREATE TEMP TABLE stage_brs_event_results AS SELECT id,course_id,plan_id,event_code
    FROM brs_event_results;
CREATE TEMP TABLE stage_brs_attempt_submissions AS SELECT enrollment_id,course_id,plan_id,event_code,attempt_no,registered_at,registered_by
    FROM brs_attempt_submissions;
CREATE TEMP TABLE stage_brs_attempt_drafts AS SELECT enrollment_id,course_id,plan_id,event_code,attempt_no,points/100 AS points,version,author_id,updated_at
    FROM brs_attempt_drafts;
CREATE TEMP TABLE stage_brs_attempt_versions AS SELECT id,result_id,enrollment_id,attempt_no,revision_no,result_version,points/100 AS points,actor_id,published_at,reason
    FROM brs_attempt_versions;
CREATE TEMP TABLE stage_brs_operation_receipts AS SELECT actor_id,command,request_key,payload_hash,version_id
    FROM brs_operation_receipts;

DROP TABLE brs_operation_receipts;
DROP TABLE brs_attempt_versions;
DROP TABLE brs_attempt_drafts;
DROP TABLE brs_attempt_submissions;
DROP TABLE brs_event_results;
DROP TABLE brs_teaching_grants;
DROP TABLE brs_transfer_events;
DROP TABLE brs_enrollments;
DROP TABLE brs_offerings;
DROP TABLE brs_scale;
DROP TABLE brs_events;
DROP TABLE brs_categories;
DROP TABLE brs_plans;

-- Renaming the plan table also stops the old backend's score paths at SQL lookup.
CREATE TABLE brs_whole_plans (
    id TEXT PRIMARY KEY NOT NULL,
    curriculum_id TEXT NOT NULL REFERENCES curriculum_items(id),
    source TEXT NOT NULL CHECK(length(trim(source)) BETWEEN 1 AND 500),
    approved_on TEXT NOT NULL,
    rounding TEXT NOT NULL CHECK(rounding IN ('exact','floor','half_up')),
    admission_min NOT NULL CHECK(typeof(admission_min)='integer' AND admission_min BETWEEN 0 AND 100),
    locked_at INTEGER,
    locked_by TEXT REFERENCES staff_profiles(user_id),
    CHECK((locked_at IS NULL) = (locked_by IS NULL))
) WITHOUT ROWID;

CREATE TABLE brs_categories (
    plan_id TEXT NOT NULL REFERENCES brs_whole_plans(id),
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    maximum NOT NULL CHECK(typeof(maximum)='integer' AND maximum BETWEEN 1 AND 100),
    admission_min CHECK(admission_min IS NULL OR typeof(admission_min)='integer' AND admission_min BETWEEN 0 AND maximum),
    PRIMARY KEY(plan_id,code)
) WITHOUT ROWID;

CREATE TABLE brs_events (
    plan_id TEXT NOT NULL,
    code TEXT NOT NULL,
    category_code TEXT NOT NULL,
    title TEXT NOT NULL,
    maximum NOT NULL CHECK(typeof(maximum)='integer' AND maximum BETWEEN 1 AND 100),
    admission_min CHECK(admission_min IS NULL OR typeof(admission_min)='integer' AND admission_min BETWEEN 0 AND maximum),
    attempt_limit INTEGER NOT NULL CHECK(attempt_limit BETWEEN 1 AND 10),
    retake_policy TEXT NOT NULL CHECK(retake_policy IN ('none','latest','highest')),
    retake_until TEXT,
    CHECK((attempt_limit=1 AND retake_policy='none' AND retake_until IS NULL)
       OR (attempt_limit>1 AND retake_policy!='none' AND retake_until IS NOT NULL)),
    PRIMARY KEY(plan_id,code),
    FOREIGN KEY(plan_id,category_code) REFERENCES brs_categories(plan_id,code)
) WITHOUT ROWID;

CREATE TABLE brs_scale (
    plan_id TEXT NOT NULL REFERENCES brs_whole_plans(id),
    minimum NOT NULL CHECK(typeof(minimum)='integer' AND minimum BETWEEN 0 AND 100),
    outcome TEXT NOT NULL CHECK(outcome IN ('2','3','4','5','fail','pass')),
    PRIMARY KEY(plan_id,minimum)
) WITHOUT ROWID;

CREATE TABLE brs_offerings (
    id TEXT PRIMARY KEY NOT NULL,
    plan_id TEXT NOT NULL REFERENCES brs_whole_plans(id),
    group_id TEXT NOT NULL REFERENCES study_groups(id),
    UNIQUE(plan_id,group_id)
);

CREATE TABLE brs_enrollments (
    id TEXT PRIMARY KEY NOT NULL,
    course_id TEXT NOT NULL REFERENCES brs_student_courses(id),
    offering_id TEXT NOT NULL REFERENCES brs_offerings(id),
    starts_on TEXT NOT NULL,
    ends_on TEXT CHECK(ends_on>starts_on),
    previous_id TEXT UNIQUE,
    reason TEXT NOT NULL,
    UNIQUE(id,course_id),
    FOREIGN KEY(previous_id,course_id) REFERENCES brs_enrollments(id,course_id)
);

CREATE TABLE brs_transfer_events (
    enrollment_id TEXT NOT NULL REFERENCES brs_enrollments(id),
    old_plan_id TEXT NOT NULL,
    old_event TEXT NOT NULL,
    new_plan_id TEXT NOT NULL,
    new_event TEXT NOT NULL,
    PRIMARY KEY(enrollment_id,old_event),
    UNIQUE(enrollment_id,new_event),
    FOREIGN KEY(old_plan_id,old_event) REFERENCES brs_events(plan_id,code),
    FOREIGN KEY(new_plan_id,new_event) REFERENCES brs_events(plan_id,code)
);

CREATE TABLE brs_teaching_grants (
    id TEXT PRIMARY KEY NOT NULL,
    offering_id TEXT NOT NULL REFERENCES brs_offerings(id),
    staff_id TEXT NOT NULL REFERENCES brs_teacher_accounts(staff_id),
    lesson_id TEXT NOT NULL REFERENCES lessons(id),
    lesson_version INTEGER NOT NULL,
    approver_id TEXT NOT NULL REFERENCES staff_profiles(user_id),
    can_confirm_final INTEGER NOT NULL CHECK(can_confirm_final IN (0,1)),
    event_code TEXT,
    starts_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL CHECK(expires_at>starts_at),
    revoked_at INTEGER,
    CHECK(staff_id!=approver_id),
    CHECK(can_confirm_final=0 OR event_code IS NULL)
);

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
    points NOT NULL CHECK(typeof(points)='integer' AND points BETWEEN 0 AND 100),
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
    points NOT NULL CHECK(typeof(points)='integer' AND points BETWEEN 0 AND 100),
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
    fingerprint_unit TEXT NOT NULL CHECK(fingerprint_unit IN ('hundredths','whole')),
    PRIMARY KEY(actor_id,command,request_key)
) WITHOUT ROWID;

INSERT INTO brs_whole_plans(id,curriculum_id,source,approved_on,rounding,admission_min,locked_at,locked_by)
    SELECT id,curriculum_id,source,approved_on,rounding,admission_min,locked_at,locked_by FROM stage_brs_plans;
INSERT INTO brs_categories(plan_id,code,title,maximum,admission_min)
    SELECT plan_id,code,title,maximum,admission_min FROM stage_brs_categories;
INSERT INTO brs_events(plan_id,code,category_code,title,maximum,admission_min,attempt_limit,retake_policy,retake_until)
    SELECT plan_id,code,category_code,title,maximum,admission_min,attempt_limit,retake_policy,retake_until FROM stage_brs_events;
INSERT INTO brs_scale(plan_id,minimum,outcome)
    SELECT plan_id,minimum,outcome FROM stage_brs_scale;
INSERT INTO brs_offerings(id,plan_id,group_id)
    SELECT id,plan_id,group_id FROM stage_brs_offerings;
INSERT INTO brs_enrollments(id,course_id,offering_id,starts_on,ends_on,previous_id,reason)
    SELECT id,course_id,offering_id,starts_on,ends_on,previous_id,reason FROM stage_brs_enrollments;
INSERT INTO brs_transfer_events(enrollment_id,old_plan_id,old_event,new_plan_id,new_event)
    SELECT enrollment_id,old_plan_id,old_event,new_plan_id,new_event FROM stage_brs_transfer_events;
INSERT INTO brs_teaching_grants(id,offering_id,staff_id,lesson_id,lesson_version,approver_id,can_confirm_final,event_code,starts_at,expires_at,revoked_at)
    SELECT id,offering_id,staff_id,lesson_id,lesson_version,approver_id,can_confirm_final,event_code,starts_at,expires_at,revoked_at FROM stage_brs_teaching_grants;
INSERT INTO brs_event_results(id,course_id,plan_id,event_code)
    SELECT id,course_id,plan_id,event_code FROM stage_brs_event_results;
INSERT INTO brs_attempt_submissions(enrollment_id,course_id,plan_id,event_code,attempt_no,registered_at,registered_by)
    SELECT enrollment_id,course_id,plan_id,event_code,attempt_no,registered_at,registered_by FROM stage_brs_attempt_submissions;
INSERT INTO brs_attempt_drafts(enrollment_id,course_id,plan_id,event_code,attempt_no,points,version,author_id,updated_at)
    SELECT enrollment_id,course_id,plan_id,event_code,attempt_no,points,version,author_id,updated_at FROM stage_brs_attempt_drafts;
INSERT INTO brs_attempt_versions(id,result_id,enrollment_id,attempt_no,revision_no,result_version,points,actor_id,published_at,reason)
    SELECT id,result_id,enrollment_id,attempt_no,revision_no,result_version,points,actor_id,published_at,reason FROM stage_brs_attempt_versions;
INSERT INTO brs_operation_receipts(actor_id,command,request_key,payload_hash,version_id,fingerprint_unit)
    SELECT actor_id,command,request_key,payload_hash,version_id,'hundredths' FROM stage_brs_operation_receipts;
INSERT INTO brs_points_preflight SELECT (SELECT count(*) FROM brs_whole_plans)=
    (SELECT count(*) FROM stage_brs_plans);
DROP TABLE stage_brs_plans;
INSERT INTO brs_points_preflight SELECT (SELECT count(*) FROM brs_categories)=
    (SELECT count(*) FROM stage_brs_categories);
DROP TABLE stage_brs_categories;
INSERT INTO brs_points_preflight SELECT (SELECT count(*) FROM brs_events)=
    (SELECT count(*) FROM stage_brs_events);
DROP TABLE stage_brs_events;
INSERT INTO brs_points_preflight SELECT (SELECT count(*) FROM brs_scale)=
    (SELECT count(*) FROM stage_brs_scale);
DROP TABLE stage_brs_scale;
INSERT INTO brs_points_preflight SELECT (SELECT count(*) FROM brs_offerings)=
    (SELECT count(*) FROM stage_brs_offerings);
DROP TABLE stage_brs_offerings;
INSERT INTO brs_points_preflight SELECT (SELECT count(*) FROM brs_enrollments)=
    (SELECT count(*) FROM stage_brs_enrollments);
DROP TABLE stage_brs_enrollments;
INSERT INTO brs_points_preflight SELECT (SELECT count(*) FROM brs_transfer_events)=
    (SELECT count(*) FROM stage_brs_transfer_events);
DROP TABLE stage_brs_transfer_events;
INSERT INTO brs_points_preflight SELECT (SELECT count(*) FROM brs_teaching_grants)=
    (SELECT count(*) FROM stage_brs_teaching_grants);
DROP TABLE stage_brs_teaching_grants;
INSERT INTO brs_points_preflight SELECT (SELECT count(*) FROM brs_event_results)=
    (SELECT count(*) FROM stage_brs_event_results);
DROP TABLE stage_brs_event_results;
INSERT INTO brs_points_preflight SELECT (SELECT count(*) FROM brs_attempt_submissions)=
    (SELECT count(*) FROM stage_brs_attempt_submissions);
DROP TABLE stage_brs_attempt_submissions;
INSERT INTO brs_points_preflight SELECT (SELECT count(*) FROM brs_attempt_drafts)=
    (SELECT count(*) FROM stage_brs_attempt_drafts);
DROP TABLE stage_brs_attempt_drafts;
INSERT INTO brs_points_preflight SELECT (SELECT count(*) FROM brs_attempt_versions)=
    (SELECT count(*) FROM stage_brs_attempt_versions);
DROP TABLE stage_brs_attempt_versions;
INSERT INTO brs_points_preflight SELECT (SELECT count(*) FROM brs_operation_receipts)=
    (SELECT count(*) FROM stage_brs_operation_receipts);
DROP TABLE stage_brs_operation_receipts;
DROP TABLE brs_points_preflight;

CREATE INDEX brs_plan_curriculum ON brs_whole_plans(curriculum_id);

CREATE TRIGGER brs_plan_insert_guard BEFORE INSERT ON brs_whole_plans
WHEN NEW.locked_at IS NOT NULL OR EXISTS(SELECT 1 FROM brs_whole_plans WHERE id=NEW.id AND locked_at IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'Insert requires a new draft'); END;

CREATE TRIGGER brs_plan_update_guard BEFORE UPDATE ON brs_whole_plans
WHEN OLD.locked_at IS NOT NULL OR EXISTS(SELECT 1 FROM brs_whole_plans WHERE id=NEW.id AND locked_at IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;

CREATE TRIGGER brs_plan_delete_guard BEFORE DELETE ON brs_whole_plans
WHEN OLD.locked_at IS NOT NULL
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;

CREATE TRIGGER brs_categories_insert_guard BEFORE INSERT ON brs_categories
WHEN EXISTS(SELECT 1 FROM brs_whole_plans WHERE locked_at IS NOT NULL AND id=NEW.plan_id)
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;

CREATE TRIGGER brs_categories_update_guard BEFORE UPDATE ON brs_categories
WHEN EXISTS(SELECT 1 FROM brs_whole_plans WHERE locked_at IS NOT NULL AND id IN (OLD.plan_id,NEW.plan_id))
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;

CREATE TRIGGER brs_categories_delete_guard BEFORE DELETE ON brs_categories
WHEN EXISTS(SELECT 1 FROM brs_whole_plans WHERE locked_at IS NOT NULL AND id=OLD.plan_id)
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;

CREATE TRIGGER brs_events_insert_guard BEFORE INSERT ON brs_events
WHEN EXISTS(SELECT 1 FROM brs_whole_plans WHERE locked_at IS NOT NULL AND id=NEW.plan_id)
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;

CREATE TRIGGER brs_events_update_guard BEFORE UPDATE ON brs_events
WHEN EXISTS(SELECT 1 FROM brs_whole_plans WHERE locked_at IS NOT NULL AND id IN (OLD.plan_id,NEW.plan_id))
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;

CREATE TRIGGER brs_events_delete_guard BEFORE DELETE ON brs_events
WHEN EXISTS(SELECT 1 FROM brs_whole_plans WHERE locked_at IS NOT NULL AND id=OLD.plan_id)
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;

CREATE TRIGGER brs_scale_insert_guard BEFORE INSERT ON brs_scale
WHEN EXISTS(SELECT 1 FROM brs_whole_plans WHERE locked_at IS NOT NULL AND id=NEW.plan_id)
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;

CREATE TRIGGER brs_scale_update_guard BEFORE UPDATE ON brs_scale
WHEN EXISTS(SELECT 1 FROM brs_whole_plans WHERE locked_at IS NOT NULL AND id IN (OLD.plan_id,NEW.plan_id))
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;

CREATE TRIGGER brs_scale_delete_guard BEFORE DELETE ON brs_scale
WHEN EXISTS(SELECT 1 FROM brs_whole_plans WHERE locked_at IS NOT NULL AND id=OLD.plan_id)
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;

CREATE INDEX brs_offering_group ON brs_offerings(group_id);

CREATE TRIGGER brs_offering_no_update BEFORE UPDATE ON brs_offerings
BEGIN SELECT RAISE(ABORT,'Offering is immutable'); END;

CREATE TRIGGER brs_offering_no_delete BEFORE DELETE ON brs_offerings
BEGIN SELECT RAISE(ABORT,'Offering is immutable'); END;

CREATE TRIGGER brs_offering_insert_guard BEFORE INSERT ON brs_offerings
WHEN EXISTS(SELECT 1 FROM brs_offerings o JOIN brs_whole_plans p ON p.id=o.plan_id
    JOIN brs_whole_plans target ON target.id=NEW.plan_id
    WHERE o.id=NEW.id OR (o.group_id=NEW.group_id AND p.curriculum_id=target.curriculum_id))
BEGIN SELECT RAISE(ABORT,'Offering already exists'); END;

CREATE UNIQUE INDEX brs_current_enrollment ON brs_enrollments(course_id) WHERE ends_on IS NULL;

CREATE INDEX brs_enrollment_offering ON brs_enrollments(offering_id,ends_on,course_id);

CREATE TRIGGER brs_enrollment_insert_guard BEFORE INSERT ON brs_enrollments
WHEN EXISTS(SELECT 1 FROM brs_enrollments WHERE id=NEW.id OR previous_id=NEW.previous_id
    OR (course_id=NEW.course_id AND ends_on IS NULL AND NEW.ends_on IS NULL))
  OR NOT EXISTS(SELECT 1 FROM brs_student_courses c JOIN brs_offerings o ON o.id=NEW.offering_id
      JOIN brs_whole_plans p ON p.id=o.plan_id WHERE c.id=NEW.course_id AND p.curriculum_id=c.curriculum_id
      AND p.locked_at IS NOT NULL)
  OR (NEW.previous_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM brs_enrollments e
      WHERE e.id=NEW.previous_id AND e.course_id=NEW.course_id AND e.ends_on=NEW.starts_on))
BEGIN SELECT RAISE(ABORT,'Invalid enrollment history'); END;

CREATE TRIGGER brs_enrollment_guard BEFORE UPDATE ON brs_enrollments
WHEN OLD.ends_on IS NOT NULL OR NEW.ends_on IS NULL OR NEW.id IS NOT OLD.id
  OR NEW.course_id IS NOT OLD.course_id OR NEW.offering_id IS NOT OLD.offering_id
  OR NEW.starts_on IS NOT OLD.starts_on OR NEW.previous_id IS NOT OLD.previous_id
  OR NEW.reason IS NOT OLD.reason
BEGIN SELECT RAISE(ABORT,'Enrollment history is immutable'); END;

CREATE TRIGGER brs_enrollment_no_delete BEFORE DELETE ON brs_enrollments
BEGIN SELECT RAISE(ABORT,'Enrollment history is immutable'); END;

CREATE TRIGGER brs_transfer_no_update BEFORE UPDATE ON brs_transfer_events
BEGIN SELECT RAISE(ABORT,'Transfer mapping is immutable'); END;

CREATE TRIGGER brs_transfer_no_delete BEFORE DELETE ON brs_transfer_events
BEGIN SELECT RAISE(ABORT,'Transfer mapping is immutable'); END;

CREATE TRIGGER brs_transfer_insert_guard BEFORE INSERT ON brs_transfer_events
WHEN EXISTS(SELECT 1 FROM brs_transfer_events WHERE enrollment_id=NEW.enrollment_id
    AND (old_event=NEW.old_event OR new_event=NEW.new_event))
  OR NOT EXISTS(SELECT 1 FROM brs_enrollments next JOIN brs_enrollments prev ON prev.id=next.previous_id
      JOIN brs_offerings src ON src.id=prev.offering_id JOIN brs_offerings dst ON dst.id=next.offering_id
      WHERE next.id=NEW.enrollment_id AND src.plan_id=NEW.old_plan_id AND dst.plan_id=NEW.new_plan_id
      AND src.plan_id!=dst.plan_id)
BEGIN SELECT RAISE(ABORT,'Invalid transfer mapping'); END;

CREATE INDEX brs_grants_scope ON brs_teaching_grants(staff_id,offering_id,expires_at)
WHERE revoked_at IS NULL;

CREATE INDEX brs_grants_responsible ON brs_teaching_grants(offering_id,expires_at)
WHERE can_confirm_final=1 AND revoked_at IS NULL;

CREATE TRIGGER brs_result_insert_guard BEFORE INSERT ON brs_event_results
WHEN EXISTS(SELECT 1 FROM brs_event_results r WHERE r.id=NEW.id
       OR (r.course_id,r.plan_id,r.event_code)=(NEW.course_id,NEW.plan_id,NEW.event_code))
  OR NOT EXISTS(SELECT 1 FROM brs_student_courses c JOIN brs_whole_plans p ON p.curriculum_id=c.curriculum_id
      JOIN brs_events e ON e.plan_id=p.id WHERE c.id=NEW.course_id AND p.id=NEW.plan_id
      AND p.locked_at IS NOT NULL AND e.code=NEW.event_code)
BEGIN SELECT RAISE(ABORT,'Invalid BRS result identity'); END;

CREATE TRIGGER brs_submission_insert_guard BEFORE INSERT ON brs_attempt_submissions
WHEN EXISTS(SELECT 1 FROM brs_attempt_submissions s WHERE
    (s.enrollment_id,s.plan_id,s.event_code,s.attempt_no)=(NEW.enrollment_id,NEW.plan_id,NEW.event_code,NEW.attempt_no))
 OR NOT EXISTS(SELECT 1 FROM brs_enrollments n JOIN brs_offerings o ON o.id=n.offering_id
    JOIN brs_whole_plans p ON p.id=o.plan_id JOIN brs_events e ON e.plan_id=p.id AND e.code=NEW.event_code
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

CREATE TRIGGER brs_whole_plan_lock_totals BEFORE UPDATE OF locked_at ON brs_whole_plans
WHEN OLD.locked_at IS NULL AND NEW.locked_at IS NOT NULL AND (
    (SELECT COALESCE(sum(c.maximum),0) FROM brs_categories c WHERE c.plan_id=NEW.id)!=100
    OR EXISTS(SELECT 1 FROM brs_categories c WHERE c.plan_id=NEW.id AND c.maximum!=(
        SELECT COALESCE(sum(e.maximum),0) FROM brs_events e
        WHERE (e.plan_id,e.category_code)=(c.plan_id,c.code)))
)
BEGIN SELECT RAISE(ABORT,'Invalid BRS plan totals'); END;

CREATE TRIGGER brs_draft_points_insert BEFORE INSERT ON brs_attempt_drafts
WHEN NOT EXISTS(SELECT 1 FROM brs_events e JOIN brs_enrollments n ON n.id=NEW.enrollment_id
    JOIN brs_offerings o ON o.id=n.offering_id
    WHERE (e.plan_id,e.code)=(NEW.plan_id,NEW.event_code) AND e.plan_id=o.plan_id
    AND n.course_id=NEW.course_id AND n.ends_on IS NULL AND NEW.points<=e.maximum)
BEGIN SELECT RAISE(ABORT,'Invalid BRS draft points'); END;

CREATE TRIGGER brs_draft_points_update BEFORE UPDATE ON brs_attempt_drafts
WHEN NOT EXISTS(SELECT 1 FROM brs_events e JOIN brs_enrollments n ON n.id=NEW.enrollment_id
    JOIN brs_offerings o ON o.id=n.offering_id
    WHERE (e.plan_id,e.code)=(NEW.plan_id,NEW.event_code) AND e.plan_id=o.plan_id
    AND n.course_id=NEW.course_id AND n.ends_on IS NULL AND NEW.points<=e.maximum)
BEGIN SELECT RAISE(ABORT,'Invalid BRS draft points'); END;

CREATE TRIGGER brs_receipt_unit_insert BEFORE INSERT ON brs_operation_receipts
WHEN NEW.fingerprint_unit!='whole'
    OR NOT EXISTS(SELECT 1 FROM brs_attempt_versions WHERE id=NEW.version_id)
BEGIN SELECT RAISE(ABORT,'Invalid BRS receipt'); END;

CREATE TRIGGER brs_points_archive_no_insert BEFORE INSERT ON brs_points_archive
BEGIN SELECT RAISE(ABORT,'BRS points archive is sealed'); END;
CREATE TRIGGER brs_points_archive_no_update BEFORE UPDATE ON brs_points_archive
BEGIN SELECT RAISE(ABORT,'BRS points archive is sealed'); END;
CREATE TRIGGER brs_points_archive_no_delete BEFORE DELETE ON brs_points_archive
BEGIN SELECT RAISE(ABORT,'BRS points archive is sealed'); END;

-- These are the two administrative write paths that do not look up a plan.
ALTER TABLE brs_teaching_grants RENAME TO brs_whole_teaching_grants;
ALTER TABLE brs_teacher_accounts RENAME TO brs_whole_teacher_accounts;
