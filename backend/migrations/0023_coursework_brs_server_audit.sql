-- Recheck data written after the 0022 preflight before switching writers.
CREATE TEMP TABLE coursework_brs_audit_preflight (missing_audit INTEGER CHECK (missing_audit = 0));
INSERT INTO coursework_brs_audit_preflight
SELECT 1 FROM coursework_brs_sources s JOIN brs_attempt_versions v ON v.id=s.version_id
WHERE NOT EXISTS (
 SELECT 1 FROM staff_audit a
 WHERE (a.actor_id,a.action,a.resource_kind,a.resource_id,a.version,a.created_at)=
       (v.actor_id,'brs.attempt.coursework','brs_attempt_version',v.id,v.result_version,v.published_at)
) LIMIT 1;
DROP TABLE coursework_brs_audit_preflight;

DROP TRIGGER coursework_brs_source_authorized;
DROP TRIGGER coursework_brs_publication_audit;
