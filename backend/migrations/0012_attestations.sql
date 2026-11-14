CREATE TABLE attestation_permissions (
    staff_id TEXT NOT NULL REFERENCES staff_profiles(user_id),
    faculty_id TEXT NOT NULL REFERENCES faculties(id),
    permission TEXT NOT NULL CHECK(permission IN ('schedule','examiner','review','late_request','late_execute')),
    PRIMARY KEY(staff_id,faculty_id,permission)
) WITHOUT ROWID;

CREATE TABLE attestation_policies (
    plan_id TEXT PRIMARY KEY NOT NULL REFERENCES brs_whole_plans(id),
    required_events TEXT NOT NULL CHECK(json_valid(required_events) AND json_type(required_events)='array'),
    approved_by TEXT NOT NULL REFERENCES staff_profiles(user_id),
    approved_at INTEGER NOT NULL CHECK(approved_at>0)
) WITHOUT ROWID;

CREATE TABLE attestation_positions (
    course_id TEXT PRIMARY KEY NOT NULL REFERENCES brs_student_courses(id),
    activated_by TEXT NOT NULL REFERENCES staff_profiles(user_id),
    activated_at INTEGER NOT NULL CHECK(activated_at>0)
) WITHOUT ROWID;

CREATE TABLE attestation_slots (
    id TEXT PRIMARY KEY NOT NULL,
    course_id TEXT NOT NULL REFERENCES attestation_positions(course_id),
    enrollment_id TEXT NOT NULL,
    number INTEGER NOT NULL CHECK(typeof(number)='integer' AND number BETWEEN 1 AND 3),
    starts_at INTEGER NOT NULL CHECK(typeof(starts_at)='integer'),
    ends_at INTEGER NOT NULL CHECK(typeof(ends_at)='integer' AND ends_at>starts_at),
    examiner_id TEXT NOT NULL REFERENCES staff_profiles(user_id),
    room_id TEXT REFERENCES rooms(id),
    commission TEXT NOT NULL CHECK(json_valid(commission) AND json_type(commission)='array'),
    assigned_by TEXT NOT NULL REFERENCES staff_profiles(user_id),
    CHECK(examiner_id!=assigned_by),
    UNIQUE(id,course_id),
    FOREIGN KEY(enrollment_id,course_id) REFERENCES brs_enrollments(id,course_id)
) WITHOUT ROWID;

CREATE TABLE attestation_events (
    course_id TEXT NOT NULL REFERENCES attestation_positions(course_id),
    version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version>0),
    slot_id TEXT,
    kind TEXT NOT NULL CHECK(kind IN ('scheduled','cancelled','draft','published','completed',
        'excused','unexcused','review_requested','review_approved','review_revoked','corrected',
        'conflict_resolved','not_admitted','admission_restored')),
    actor_id TEXT NOT NULL REFERENCES staff_profiles(user_id),
    at INTEGER NOT NULL CHECK(typeof(at)='integer' AND at>0),
    data TEXT NOT NULL CHECK(json_valid(data) AND json_type(data)='object'),
    PRIMARY KEY(course_id,version),
    FOREIGN KEY(slot_id,course_id) REFERENCES attestation_slots(id,course_id)
) WITHOUT ROWID;
CREATE INDEX attestation_events_slot ON attestation_events(slot_id,version);
CREATE INDEX attestation_slots_interval ON attestation_slots(starts_at,ends_at);

CREATE TABLE account_languages (
    user_id TEXT PRIMARY KEY NOT NULL REFERENCES users(id),
    language TEXT NOT NULL CHECK(language IN ('ru','en'))
) WITHOUT ROWID;

CREATE TABLE attestation_receipts (
    actor_id TEXT NOT NULL REFERENCES staff_profiles(user_id),
    request_key TEXT NOT NULL,
    fingerprint TEXT NOT NULL CHECK(length(fingerprint)=64),
    course_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    PRIMARY KEY(actor_id,request_key),
    FOREIGN KEY(course_id,version) REFERENCES attestation_events(course_id,version)
) WITHOUT ROWID;

CREATE TRIGGER attestation_policy_insert BEFORE INSERT ON attestation_policies
WHEN EXISTS(SELECT 1 FROM attestation_policies WHERE plan_id=NEW.plan_id)
 OR NOT EXISTS(SELECT 1 FROM brs_whole_plans WHERE id=NEW.plan_id AND locked_at IS NOT NULL)
 OR EXISTS(SELECT 1 FROM json_each(NEW.required_events) j WHERE j.type!='text'
    OR NOT EXISTS(SELECT 1 FROM brs_events e WHERE e.plan_id=NEW.plan_id AND e.code=j.value))
 OR (SELECT count(*) FROM json_each(NEW.required_events))!=
    (SELECT count(DISTINCT value) FROM json_each(NEW.required_events))
BEGIN SELECT RAISE(ABORT,'Invalid attestation policy'); END;

CREATE TRIGGER attestation_position_insert BEFORE INSERT ON attestation_positions
WHEN EXISTS(SELECT 1 FROM attestation_positions WHERE course_id=NEW.course_id)
 OR NOT EXISTS(SELECT 1 FROM brs_student_courses WHERE id=NEW.course_id)
 OR EXISTS(SELECT 1 FROM brs_student_courses c JOIN student_assessments sa ON sa.student_id=c.student_id
    JOIN assessments a ON a.id=sa.assessment_id AND a.curriculum_id=c.curriculum_id
    JOIN assessment_attempts t ON t.assignment_id=sa.id WHERE c.id=NEW.course_id)
BEGIN SELECT RAISE(ABORT,'Conflicting official result source'); END;

CREATE TRIGGER attestation_legacy_insert BEFORE INSERT ON assessment_attempts
WHEN EXISTS(SELECT 1 FROM student_assessments sa JOIN assessments a ON a.id=sa.assessment_id
    JOIN brs_student_courses c ON (c.student_id,c.curriculum_id)=(sa.student_id,a.curriculum_id)
    JOIN attestation_positions p ON p.course_id=c.id WHERE sa.id=NEW.assignment_id)
 OR EXISTS(SELECT 1 FROM assessment_attempts WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'Conflicting official result source'); END;

CREATE TRIGGER attestation_legacy_assignment_identity
BEFORE UPDATE OF id,student_id,assessment_id ON student_assessments
WHEN EXISTS(SELECT 1 FROM assessment_attempts WHERE assignment_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'Legacy assignment identity is immutable'); END;

CREATE TRIGGER attestation_legacy_assessment_identity
BEFORE UPDATE OF id,curriculum_id,group_id ON assessments
WHEN EXISTS(SELECT 1 FROM student_assessments sa JOIN assessment_attempts t ON t.assignment_id=sa.id
    WHERE sa.assessment_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'Legacy assessment identity is immutable'); END;

CREATE TRIGGER attestation_slot_insert BEFORE INSERT ON attestation_slots
WHEN EXISTS(SELECT 1 FROM attestation_slots WHERE id=NEW.id)
 OR NOT EXISTS(SELECT 1 FROM attestation_positions p JOIN brs_enrollments n ON n.course_id=p.course_id
    WHERE p.course_id=NEW.course_id AND n.id=NEW.enrollment_id)
 OR (NEW.number=3 AND (json_array_length(NEW.commission)<2 OR NOT EXISTS(
    SELECT 1 FROM json_each(NEW.commission) WHERE value=NEW.examiner_id)))
 OR (NEW.number<3 AND json_array_length(NEW.commission)!=0)
BEGIN SELECT RAISE(ABORT,'Invalid attestation slot'); END;

CREATE TRIGGER attestation_event_insert BEFORE INSERT ON attestation_events
WHEN NEW.version!=1+COALESCE((SELECT max(version) FROM attestation_events WHERE course_id=NEW.course_id),0)
 OR NOT EXISTS(SELECT 1 FROM attestation_positions WHERE course_id=NEW.course_id)
 OR (NEW.slot_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM attestation_slots
    WHERE (id,course_id)=(NEW.slot_id,NEW.course_id)))
 OR (NEW.kind IN ('scheduled','cancelled','draft','published','completed','excused','unexcused','corrected')
    AND NEW.slot_id IS NULL)
BEGIN SELECT RAISE(ABORT,'Invalid attestation event'); END;

CREATE TRIGGER attestation_slot_transition BEFORE INSERT ON attestation_events
WHEN NEW.kind IN ('scheduled','cancelled','draft','published','completed','excused','unexcused') AND NOT EXISTS(
    SELECT 1 FROM attestation_slots s WHERE s.id=NEW.slot_id AND (
        (NEW.kind='scheduled' AND NEW.at<s.starts_at AND NOT EXISTS(
            SELECT 1 FROM attestation_events WHERE slot_id=s.id))
        OR (NEW.kind='cancelled' AND NEW.at<s.starts_at AND 'scheduled'=(
            SELECT kind FROM attestation_events WHERE slot_id=s.id AND kind IN ('scheduled','cancelled','draft',
                'published','completed','excused','unexcused') ORDER BY version DESC LIMIT 1))
        OR (NEW.kind IN ('draft','published','completed','excused','unexcused') AND NEW.at>=s.starts_at
            AND EXISTS(SELECT 1 FROM attestation_events previous
                WHERE previous.slot_id=s.id AND previous.version=(
                    SELECT max(version) FROM attestation_events WHERE slot_id=s.id AND kind IN ('scheduled',
                        'cancelled','draft','published','completed','excused','unexcused'))
                AND ((NEW.kind='draft' AND previous.kind IN ('scheduled','draft') AND NEW.actor_id=s.examiner_id)
                    OR (NEW.kind='published' AND previous.kind='draft' AND NEW.actor_id=s.examiner_id)
                    OR (NEW.kind='completed' AND previous.kind='published' AND NEW.actor_id=s.examiner_id)
                    OR (NEW.kind IN ('excused','unexcused') AND previous.kind IN ('scheduled','draft')
                        AND NEW.at>=s.ends_at))))))
BEGIN SELECT RAISE(ABORT,'Invalid attestation slot transition'); END;

CREATE TRIGGER attestation_event_outcome BEFORE INSERT ON attestation_events
WHEN NEW.kind IN ('published','corrected','unexcused') AND NOT EXISTS(
    SELECT 1 FROM brs_student_courses c JOIN curriculum_items i ON i.id=c.curriculum_id WHERE c.id=NEW.course_id
    AND ((NEW.kind='unexcused' AND json_extract(NEW.data,'$.outcome')='absent')
        OR (NEW.kind!='unexcused' AND (
           (i.control='credit' AND json_extract(NEW.data,'$.outcome') IN ('pass','fail')
             AND json_type(NEW.data,'$.grade')='null')
           OR (i.control!='credit' AND json_extract(NEW.data,'$.outcome')='graded'
             AND json_type(NEW.data,'$.grade')='integer' AND json_extract(NEW.data,'$.grade') BETWEEN 2 AND 5)))))
BEGIN SELECT RAISE(ABORT,'Invalid official attestation outcome'); END;

CREATE TRIGGER attestation_event_consumption BEFORE INSERT ON attestation_events
WHEN NEW.kind IN ('published','unexcused') AND (
    EXISTS(SELECT 1 FROM attestation_events WHERE slot_id=NEW.slot_id AND kind IN
        ('published','unexcused','cancelled','excused'))
    OR NOT EXISTS(SELECT 1 FROM attestation_slots WHERE id=NEW.slot_id AND number=1+(
        SELECT count(*) FROM attestation_events WHERE course_id=NEW.course_id AND kind IN ('published','unexcused')))
)
BEGIN SELECT RAISE(ABORT,'Invalid official attempt sequence'); END;

CREATE TRIGGER attestation_review_consumption BEFORE INSERT ON attestation_events
WHEN NEW.kind='corrected' AND (
    NOT EXISTS(SELECT 1 FROM attestation_events WHERE course_id=NEW.course_id AND slot_id=NEW.slot_id
        AND kind='review_approved' AND version=json_extract(NEW.data,'$.approval_version')
        AND actor_id!=NEW.actor_id
        AND json_extract(data,'$.review_version')=json_extract(NEW.data,'$.review_version'))
    OR EXISTS(SELECT 1 FROM attestation_events WHERE course_id=NEW.course_id
        AND kind IN ('review_revoked','corrected')
        AND json_extract(data,'$.review_version')=json_extract(NEW.data,'$.review_version'))
)
BEGIN SELECT RAISE(ABORT,'Invalid attestation review approval'); END;

CREATE TRIGGER attestation_receipt_insert BEFORE INSERT ON attestation_receipts
WHEN EXISTS(SELECT 1 FROM attestation_receipts WHERE (actor_id,request_key)=(NEW.actor_id,NEW.request_key))
 OR NOT EXISTS(SELECT 1 FROM attestation_events WHERE (course_id,version,actor_id)=
    (NEW.course_id,NEW.version,NEW.actor_id))
BEGIN SELECT RAISE(ABORT,'Invalid attestation receipt'); END;

CREATE TRIGGER attestation_policy_no_update BEFORE UPDATE ON attestation_policies
BEGIN SELECT RAISE(ABORT,'Attestation policy is immutable'); END;
CREATE TRIGGER attestation_policy_no_delete BEFORE DELETE ON attestation_policies
BEGIN SELECT RAISE(ABORT,'Attestation policy is immutable'); END;
CREATE TRIGGER attestation_position_no_update BEFORE UPDATE ON attestation_positions
BEGIN SELECT RAISE(ABORT,'Official source is immutable'); END;
CREATE TRIGGER attestation_position_no_delete BEFORE DELETE ON attestation_positions
BEGIN SELECT RAISE(ABORT,'Official source is immutable'); END;
CREATE TRIGGER attestation_slot_no_update BEFORE UPDATE ON attestation_slots
BEGIN SELECT RAISE(ABORT,'Attestation slot is immutable'); END;
CREATE TRIGGER attestation_slot_no_delete BEFORE DELETE ON attestation_slots
BEGIN SELECT RAISE(ABORT,'Attestation slot is immutable'); END;
CREATE TRIGGER attestation_event_no_update BEFORE UPDATE ON attestation_events
BEGIN SELECT RAISE(ABORT,'Attestation history is immutable'); END;
CREATE TRIGGER attestation_event_no_delete BEFORE DELETE ON attestation_events
BEGIN SELECT RAISE(ABORT,'Attestation history is immutable'); END;
CREATE TRIGGER attestation_receipt_no_update BEFORE UPDATE ON attestation_receipts
BEGIN SELECT RAISE(ABORT,'Attestation receipt is immutable'); END;
CREATE TRIGGER attestation_receipt_no_delete BEFORE DELETE ON attestation_receipts
BEGIN SELECT RAISE(ABORT,'Attestation receipt is immutable'); END;
