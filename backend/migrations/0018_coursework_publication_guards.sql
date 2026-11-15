CREATE VIEW coursework_brs_reservations AS
SELECT a.offering_id, o.plan_id, a.event_code, r.course_id
FROM coursework_recipients r
JOIN coursework_assignments a ON a.id=r.assignment_id
JOIN brs_offerings o ON o.id=a.offering_id
WHERE a.status='published' AND a.grading_mode='brs';

CREATE VIEW brs_published_event_scopes AS
SELECT n.offering_id, r.plan_id, r.event_code, r.course_id
FROM brs_attempt_versions v
JOIN brs_event_results r ON r.id=v.result_id
JOIN brs_enrollments n ON n.id=v.enrollment_id;

CREATE TRIGGER brs_coursework_publication_guard BEFORE INSERT ON brs_attempt_versions
WHEN NEW.revision_no=1 AND EXISTS (
    SELECT 1 FROM brs_event_results r
    JOIN brs_enrollments n ON n.id=NEW.enrollment_id
    JOIN coursework_brs_reservations c ON
        (c.offering_id,c.plan_id,c.event_code,c.course_id)=(n.offering_id,r.plan_id,r.event_code,r.course_id)
    WHERE r.id=NEW.result_id
)
BEGIN SELECT RAISE(ABORT,'Coursework owns the BRS publication scope'); END;

CREATE TRIGGER coursework_brs_recipient_guard BEFORE INSERT ON coursework_recipients
WHEN EXISTS (
    SELECT 1 FROM coursework_assignments a JOIN brs_offerings o ON o.id=a.offering_id
    JOIN brs_published_event_scopes p ON
        (p.offering_id,p.plan_id,p.event_code,p.course_id)=(a.offering_id,o.plan_id,a.event_code,NEW.course_id)
    WHERE a.id=NEW.assignment_id AND a.status='published' AND a.grading_mode='brs'
)
BEGIN SELECT RAISE(ABORT,'BRS result already published'); END;

CREATE TRIGGER coursework_brs_assignment_guard
BEFORE UPDATE OF status,grading_mode,event_code ON coursework_assignments
WHEN OLD.status='draft' AND NEW.status='published' AND NEW.grading_mode='brs' AND EXISTS (
    SELECT 1 FROM coursework_recipients r JOIN brs_offerings o ON o.id=NEW.offering_id
    JOIN brs_published_event_scopes p ON
        (p.offering_id,p.plan_id,p.event_code,p.course_id)=(NEW.offering_id,o.plan_id,NEW.event_code,r.course_id)
    WHERE r.assignment_id=OLD.id
)
BEGIN SELECT RAISE(ABORT,'BRS result already published'); END;

CREATE TRIGGER coursework_assignment_recipient_replace_guard
BEFORE INSERT ON coursework_assignments
WHEN EXISTS (SELECT 1 FROM coursework_recipients WHERE assignment_id=NEW.id)
BEGIN SELECT RAISE(ABORT,'An assignment with recipients cannot be replaced'); END;

CREATE TRIGGER coursework_recipient_identity_guard
BEFORE UPDATE OF assignment_id,course_id,enrollment_id ON coursework_recipients
WHEN (NEW.assignment_id,NEW.course_id,NEW.enrollment_id)<>(OLD.assignment_id,OLD.course_id,OLD.enrollment_id)
BEGIN SELECT RAISE(ABORT,'Coursework recipient identity is immutable'); END;

CREATE TRIGGER coursework_recipient_replace_guard BEFORE INSERT ON coursework_recipients
WHEN EXISTS (SELECT 1 FROM coursework_recipients r
    WHERE (r.assignment_id,r.course_id)=(NEW.assignment_id,NEW.course_id))
BEGIN SELECT RAISE(ABORT,'Coursework recipient identity is immutable'); END;

CREATE TRIGGER coursework_review_metadata_guard BEFORE INSERT ON coursework_reviews
WHEN typeof(NEW.reviewed_at)<>'integer' OR NEW.reviewed_at<=0
OR typeof(NEW.comment)<>'text' OR instr(NEW.comment,char(0))>0
OR length(trim(NEW.comment,char(9,10,11,12,13,28,29,30,31,32,133,160,5760,
    8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288))) NOT BETWEEN 1 AND 2000
OR (NEW.revision>1 AND (typeof(NEW.reason)<>'text' OR instr(NEW.reason,char(0))>0
    OR length(trim(NEW.reason,char(9,10,11,12,13,28,29,30,31,32,133,160,5760,
        8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288))) NOT BETWEEN 3 AND 500))
BEGIN SELECT RAISE(ABORT,'Invalid coursework review metadata'); END;

CREATE TRIGGER coursework_attempt_update_guard BEFORE UPDATE ON coursework_attempts
BEGIN SELECT RAISE(ABORT,'Coursework submission history is immutable'); END;

CREATE TRIGGER coursework_attempt_delete_guard BEFORE DELETE ON coursework_attempts
BEGIN SELECT RAISE(ABORT,'Coursework submission history is immutable'); END;

CREATE TRIGGER coursework_attempt_replace_guard BEFORE INSERT ON coursework_attempts
WHEN EXISTS (SELECT 1 FROM coursework_attempts a WHERE
    (a.assignment_id,a.course_id,a.number)=(NEW.assignment_id,NEW.course_id,NEW.number))
BEGIN SELECT RAISE(ABORT,'Coursework submission history is immutable'); END;
