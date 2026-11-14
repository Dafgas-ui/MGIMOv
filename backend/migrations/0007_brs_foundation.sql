CREATE TABLE brs_plans (
    id TEXT PRIMARY KEY NOT NULL,
    curriculum_id TEXT NOT NULL REFERENCES curriculum_items(id),
    source TEXT NOT NULL CHECK(length(trim(source)) BETWEEN 1 AND 500),
    approved_on TEXT NOT NULL,
    rounding TEXT NOT NULL CHECK(rounding IN ('exact','floor','half_up')),
    admission_min INTEGER NOT NULL CHECK(admission_min BETWEEN 0 AND 10000),
    locked_at INTEGER,
    locked_by TEXT REFERENCES staff_profiles(user_id),
    CHECK((locked_at IS NULL) = (locked_by IS NULL))
);
CREATE TABLE brs_categories (
    plan_id TEXT NOT NULL REFERENCES brs_plans(id),
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    maximum INTEGER NOT NULL CHECK(maximum BETWEEN 1 AND 10000),
    admission_min INTEGER CHECK(admission_min BETWEEN 0 AND maximum),
    PRIMARY KEY(plan_id,code)
);
CREATE TABLE brs_events (
    plan_id TEXT NOT NULL,
    code TEXT NOT NULL,
    category_code TEXT NOT NULL,
    title TEXT NOT NULL,
    maximum INTEGER NOT NULL CHECK(maximum BETWEEN 1 AND 10000),
    admission_min INTEGER CHECK(admission_min BETWEEN 0 AND maximum),
    attempt_limit INTEGER NOT NULL CHECK(attempt_limit BETWEEN 1 AND 10),
    retake_policy TEXT NOT NULL CHECK(retake_policy IN ('none','latest','highest')),
    retake_until TEXT,
    CHECK((attempt_limit=1 AND retake_policy='none' AND retake_until IS NULL)
       OR (attempt_limit>1 AND retake_policy!='none' AND retake_until IS NOT NULL)),
    PRIMARY KEY(plan_id,code),
    FOREIGN KEY(plan_id,category_code) REFERENCES brs_categories(plan_id,code)
);
CREATE TABLE brs_scale (
    plan_id TEXT NOT NULL REFERENCES brs_plans(id),
    minimum INTEGER NOT NULL CHECK(minimum BETWEEN 0 AND 10000),
    outcome TEXT NOT NULL CHECK(outcome IN ('2','3','4','5','fail','pass')),
    PRIMARY KEY(plan_id,minimum)
);
CREATE INDEX brs_plan_curriculum ON brs_plans(curriculum_id);

CREATE TRIGGER brs_plan_insert_guard BEFORE INSERT ON brs_plans
WHEN NEW.locked_at IS NOT NULL OR EXISTS(SELECT 1 FROM brs_plans WHERE id=NEW.id AND locked_at IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'Insert requires a new draft'); END;
CREATE TRIGGER brs_plan_update_guard BEFORE UPDATE ON brs_plans
WHEN OLD.locked_at IS NOT NULL OR EXISTS(SELECT 1 FROM brs_plans WHERE id=NEW.id AND locked_at IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;
CREATE TRIGGER brs_plan_delete_guard BEFORE DELETE ON brs_plans
WHEN OLD.locked_at IS NOT NULL
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;
CREATE TRIGGER brs_categories_insert_guard BEFORE INSERT ON brs_categories
WHEN EXISTS(SELECT 1 FROM brs_plans WHERE locked_at IS NOT NULL AND id=NEW.plan_id)
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;
CREATE TRIGGER brs_categories_update_guard BEFORE UPDATE ON brs_categories
WHEN EXISTS(SELECT 1 FROM brs_plans WHERE locked_at IS NOT NULL AND id IN (OLD.plan_id,NEW.plan_id))
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;
CREATE TRIGGER brs_categories_delete_guard BEFORE DELETE ON brs_categories
WHEN EXISTS(SELECT 1 FROM brs_plans WHERE locked_at IS NOT NULL AND id=OLD.plan_id)
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;
CREATE TRIGGER brs_events_insert_guard BEFORE INSERT ON brs_events
WHEN EXISTS(SELECT 1 FROM brs_plans WHERE locked_at IS NOT NULL AND id=NEW.plan_id)
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;
CREATE TRIGGER brs_events_update_guard BEFORE UPDATE ON brs_events
WHEN EXISTS(SELECT 1 FROM brs_plans WHERE locked_at IS NOT NULL AND id IN (OLD.plan_id,NEW.plan_id))
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;
CREATE TRIGGER brs_events_delete_guard BEFORE DELETE ON brs_events
WHEN EXISTS(SELECT 1 FROM brs_plans WHERE locked_at IS NOT NULL AND id=OLD.plan_id)
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;
CREATE TRIGGER brs_scale_insert_guard BEFORE INSERT ON brs_scale
WHEN EXISTS(SELECT 1 FROM brs_plans WHERE locked_at IS NOT NULL AND id=NEW.plan_id)
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;
CREATE TRIGGER brs_scale_update_guard BEFORE UPDATE ON brs_scale
WHEN EXISTS(SELECT 1 FROM brs_plans WHERE locked_at IS NOT NULL AND id IN (OLD.plan_id,NEW.plan_id))
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;
CREATE TRIGGER brs_scale_delete_guard BEFORE DELETE ON brs_scale
WHEN EXISTS(SELECT 1 FROM brs_plans WHERE locked_at IS NOT NULL AND id=OLD.plan_id)
BEGIN SELECT RAISE(ABORT,'Locked BRS plan'); END;

CREATE TABLE brs_offerings (
    id TEXT PRIMARY KEY NOT NULL,
    plan_id TEXT NOT NULL REFERENCES brs_plans(id),
    group_id TEXT NOT NULL REFERENCES study_groups(id),
    UNIQUE(plan_id,group_id)
);
CREATE INDEX brs_offering_group ON brs_offerings(group_id);
CREATE TRIGGER brs_offering_no_update BEFORE UPDATE ON brs_offerings
BEGIN SELECT RAISE(ABORT,'Offering is immutable'); END;
CREATE TRIGGER brs_offering_no_delete BEFORE DELETE ON brs_offerings
BEGIN SELECT RAISE(ABORT,'Offering is immutable'); END;
CREATE TRIGGER brs_offering_insert_guard BEFORE INSERT ON brs_offerings
WHEN EXISTS(SELECT 1 FROM brs_offerings o JOIN brs_plans p ON p.id=o.plan_id
    JOIN brs_plans target ON target.id=NEW.plan_id
    WHERE o.id=NEW.id OR (o.group_id=NEW.group_id AND p.curriculum_id=target.curriculum_id))
BEGIN SELECT RAISE(ABORT,'Offering already exists'); END;
CREATE TABLE brs_student_courses (
    id TEXT PRIMARY KEY NOT NULL,
    student_id TEXT NOT NULL REFERENCES student_profiles(user_id),
    curriculum_id TEXT NOT NULL REFERENCES curriculum_items(id),
    UNIQUE(student_id,curriculum_id)
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
CREATE UNIQUE INDEX brs_current_enrollment ON brs_enrollments(course_id) WHERE ends_on IS NULL;
CREATE INDEX brs_enrollment_offering ON brs_enrollments(offering_id,ends_on,course_id);
CREATE TRIGGER brs_enrollment_insert_guard BEFORE INSERT ON brs_enrollments
WHEN EXISTS(SELECT 1 FROM brs_enrollments WHERE id=NEW.id OR previous_id=NEW.previous_id
    OR (course_id=NEW.course_id AND ends_on IS NULL AND NEW.ends_on IS NULL))
  OR NOT EXISTS(SELECT 1 FROM brs_student_courses c JOIN brs_offerings o ON o.id=NEW.offering_id
      JOIN brs_plans p ON p.id=o.plan_id WHERE c.id=NEW.course_id AND p.curriculum_id=c.curriculum_id
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

CREATE TABLE brs_capabilities (
    staff_id TEXT NOT NULL REFERENCES staff_profiles(user_id),
    faculty_id TEXT NOT NULL REFERENCES faculties(id),
    capability TEXT NOT NULL CHECK(capability IN ('manage_plans','manage_teaching','manage_enrollments','allow_final_review')),
    PRIMARY KEY(staff_id,faculty_id,capability)
);
CREATE TABLE brs_teacher_accounts (
    staff_id TEXT PRIMARY KEY NOT NULL REFERENCES staff_profiles(user_id),
    teacher_id TEXT NOT NULL UNIQUE REFERENCES teachers(id)
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
CREATE INDEX brs_grants_scope ON brs_teaching_grants(staff_id,offering_id,expires_at)
WHERE revoked_at IS NULL;
CREATE INDEX brs_grants_responsible ON brs_teaching_grants(offering_id,expires_at)
WHERE can_confirm_final=1 AND revoked_at IS NULL;
