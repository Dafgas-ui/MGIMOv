CREATE TABLE coursework_brs_sources (
    version_id TEXT PRIMARY KEY NOT NULL
        REFERENCES brs_attempt_versions(id) DEFERRABLE INITIALLY DEFERRED,
    assignment_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,
    review_revision INTEGER NOT NULL,
    FOREIGN KEY (assignment_id, course_id, attempt_no, review_revision)
        REFERENCES coursework_reviews(assignment_id, course_id, attempt_no, revision),
    UNIQUE (assignment_id, course_id, attempt_no, review_revision)
) WITHOUT ROWID;

CREATE TRIGGER coursework_brs_source_no_replace BEFORE INSERT ON coursework_brs_sources
WHEN EXISTS(SELECT 1 FROM brs_attempt_versions WHERE id=NEW.version_id)
 OR EXISTS(SELECT 1 FROM coursework_brs_sources s WHERE s.version_id=NEW.version_id OR
 (s.assignment_id,s.course_id,s.attempt_no,s.review_revision)=
 (NEW.assignment_id,NEW.course_id,NEW.attempt_no,NEW.review_revision))
BEGIN SELECT RAISE(ABORT, 'Coursework BRS source is immutable'); END;

CREATE TRIGGER coursework_brs_source_no_update BEFORE UPDATE ON coursework_brs_sources
BEGIN SELECT RAISE(ABORT, 'Coursework BRS source is immutable'); END;

CREATE TRIGGER coursework_brs_source_no_delete BEFORE DELETE ON coursework_brs_sources
BEGIN SELECT RAISE(ABORT, 'Coursework BRS source is immutable'); END;

-- Preserve the exclusive-owner guard from 0018 and admit only a proven Coursework source.
DROP TRIGGER brs_coursework_publication_guard;
CREATE TRIGGER brs_coursework_publication_guard BEFORE INSERT ON brs_attempt_versions
WHEN (
    EXISTS (SELECT 1 FROM coursework_brs_sources WHERE version_id=NEW.id)
    OR (NEW.revision_no=1 AND EXISTS (
        SELECT 1 FROM brs_event_results r JOIN brs_enrollments n ON n.id=NEW.enrollment_id
        JOIN coursework_brs_reservations c ON
        (c.offering_id,c.plan_id,c.event_code,c.course_id)=(n.offering_id,r.plan_id,r.event_code,r.course_id)
        WHERE r.id=NEW.result_id))
    OR EXISTS (SELECT 1 FROM brs_attempt_versions v JOIN coursework_brs_sources s ON s.version_id=v.id
        WHERE v.result_id=NEW.result_id AND v.attempt_no=NEW.attempt_no)
) AND NOT EXISTS (
    SELECT 1 FROM coursework_brs_sources s
    JOIN coursework_assignments a ON a.id=s.assignment_id
    JOIN coursework_recipients c ON (c.assignment_id,c.course_id)=(a.id,s.course_id)
    JOIN coursework_reviews q ON (q.assignment_id,q.course_id,q.attempt_no,q.revision)=
        (s.assignment_id,s.course_id,s.attempt_no,s.review_revision)
    JOIN brs_event_results r ON r.id=NEW.result_id
    JOIN brs_offerings o ON o.id=a.offering_id
    JOIN brs_enrollments n ON n.id=c.enrollment_id AND n.offering_id=o.id
    WHERE s.version_id=NEW.id AND a.status='published' AND a.grading_mode='brs'
      AND (r.course_id,r.plan_id,r.event_code)=(s.course_id,o.plan_id,a.event_code)
      AND n.id=NEW.enrollment_id AND n.ends_on IS NULL
      AND q.decision='reviewed' AND q.points=NEW.points
      AND s.attempt_no=(SELECT max(t.number) FROM coursework_attempts t
            WHERE (t.assignment_id,t.course_id)=(s.assignment_id,s.course_id))
      AND s.review_revision=(SELECT max(v.revision) FROM coursework_reviews v
            WHERE (v.assignment_id,v.course_id,v.attempt_no)=(s.assignment_id,s.course_id,s.attempt_no))
      AND ((NEW.revision_no=1 AND NOT EXISTS (
            SELECT 1 FROM coursework_brs_sources earlier
            WHERE earlier.version_id<>s.version_id AND
            (earlier.assignment_id,earlier.course_id,earlier.attempt_no)=(s.assignment_id,s.course_id,s.attempt_no)))
        OR (NEW.revision_no>1 AND q.reason=NEW.reason AND EXISTS (
            SELECT 1 FROM brs_attempt_versions v JOIN coursework_brs_sources prior ON prior.version_id=v.id
            WHERE (v.result_id,v.attempt_no,v.revision_no)=(NEW.result_id,NEW.attempt_no,NEW.revision_no-1)
              AND (prior.assignment_id,prior.course_id,prior.attempt_no)=(s.assignment_id,s.course_id,s.attempt_no)
              AND prior.review_revision<s.review_revision)))
)
BEGIN SELECT RAISE(ABORT,'Coursework owns the BRS publication scope'); END;
