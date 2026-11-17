-- Existing publications must have the audit entry written by the 0021 service.
CREATE TEMP TABLE coursework_brs_audit_preflight (missing_audit INTEGER CHECK (missing_audit = 0));
INSERT INTO coursework_brs_audit_preflight
SELECT 1 FROM coursework_brs_sources s JOIN brs_attempt_versions v ON v.id=s.version_id
WHERE NOT EXISTS (
 SELECT 1 FROM staff_audit a
 WHERE (a.actor_id,a.action,a.resource_kind,a.resource_id,a.version,a.created_at)=
       (v.actor_id,'brs.attempt.coursework','brs_attempt_version',v.id,v.result_version,v.published_at)
) LIMIT 1;
DROP TABLE coursework_brs_audit_preflight;

-- Only the authorized service registers this function for the exact pending source.
-- Keep it off the generic BRS table so ordinary publications need no callback.
CREATE TRIGGER coursework_brs_source_authorized BEFORE INSERT ON coursework_brs_sources
WHEN mgimov_coursework_publication(NEW.version_id,NEW.assignment_id,NEW.course_id,
                                 NEW.attempt_no,NEW.review_revision) IS NOT 1
BEGIN SELECT RAISE(ABORT,'Coursework BRS publication requires authorization'); END;

CREATE TRIGGER coursework_brs_publication_audit AFTER INSERT ON brs_attempt_versions
WHEN EXISTS (SELECT 1 FROM coursework_brs_sources WHERE version_id=NEW.id)
BEGIN
 INSERT INTO staff_audit (id,actor_id,action,resource_kind,resource_id,version,created_at)
 VALUES (lower(hex(randomblob(16))),NEW.actor_id,'brs.attempt.coursework','brs_attempt_version',
         NEW.id,NEW.result_version,NEW.published_at);
 SELECT CASE WHEN changes() <> 1 THEN RAISE(ABORT,'Coursework BRS publication requires audit') END;
END;
