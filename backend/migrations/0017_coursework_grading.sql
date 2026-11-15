ALTER TABLE coursework_assignments ADD COLUMN grading_mode TEXT NOT NULL DEFAULT 'ungraded';
ALTER TABLE coursework_assignments ADD COLUMN max_points INTEGER;
ALTER TABLE coursework_reviews ADD COLUMN reason TEXT;

UPDATE coursework_assignments SET grading_mode='brs' WHERE event_code IS NOT NULL;

CREATE TRIGGER coursework_grading_insert BEFORE INSERT ON coursework_assignments
WHEN NOT (
    (NEW.grading_mode='ungraded' AND NEW.event_code IS NULL AND NEW.max_points IS NULL)
    OR (NEW.grading_mode='independent' AND NEW.event_code IS NULL
        AND typeof(NEW.max_points)='integer' AND NEW.max_points BETWEEN 1 AND 100)
    OR (NEW.grading_mode='brs' AND NEW.event_code IS NOT NULL AND NEW.max_points IS NULL)
) OR EXISTS (SELECT 1 FROM coursework_assignments a WHERE a.status='published'
    AND (a.id=NEW.id OR (a.offering_id,a.event_code)=(NEW.offering_id,NEW.event_code)))
BEGIN SELECT RAISE(ABORT,'Invalid coursework grading or replacement'); END;

CREATE TRIGGER coursework_grading_update
BEFORE UPDATE OF id,grading_mode,max_points,event_code,status ON coursework_assignments
WHEN NEW.id<>OLD.id
OR (OLD.status='published' AND (NEW.status<>OLD.status OR NEW.grading_mode<>OLD.grading_mode
    OR NEW.max_points IS NOT OLD.max_points OR NEW.event_code IS NOT OLD.event_code))
OR NOT (
    (NEW.grading_mode='ungraded' AND NEW.event_code IS NULL AND NEW.max_points IS NULL)
    OR (NEW.grading_mode='independent' AND NEW.event_code IS NULL
        AND typeof(NEW.max_points)='integer' AND NEW.max_points BETWEEN 1 AND 100)
    OR (NEW.grading_mode='brs' AND NEW.event_code IS NOT NULL AND NEW.max_points IS NULL)
)
OR EXISTS (SELECT 1 FROM coursework_assignments a WHERE a.id<>OLD.id
    AND (a.offering_id,a.event_code)=(NEW.offering_id,NEW.event_code))
BEGIN SELECT RAISE(ABORT,'Invalid or immutable coursework grading'); END;

CREATE TRIGGER coursework_review_update BEFORE UPDATE ON coursework_reviews
BEGIN SELECT RAISE(ABORT,'Coursework review history is immutable'); END;

CREATE TRIGGER coursework_review_delete BEFORE DELETE ON coursework_reviews
BEGIN SELECT RAISE(ABORT,'Coursework review history is immutable'); END;

CREATE TRIGGER coursework_review_insert BEFORE INSERT ON coursework_reviews
WHEN NEW.revision IS NOT (
    SELECT coalesce(max(revision),0)+1 FROM coursework_reviews
    WHERE (assignment_id,course_id,attempt_no)=(NEW.assignment_id,NEW.course_id,NEW.attempt_no)
) OR (NEW.revision>1 AND (NEW.reason IS NULL OR length(trim(NEW.reason)) NOT BETWEEN 3 AND 500))
OR (NEW.revision=1 AND NEW.reason IS NOT NULL)
OR (NEW.points IS NOT NULL AND NEW.points > coalesce((
    SELECT CASE a.grading_mode WHEN 'independent' THEN a.max_points WHEN 'brs' THEN e.maximum END
    FROM coursework_assignments a JOIN brs_offerings o ON o.id=a.offering_id
    LEFT JOIN brs_events e ON (e.plan_id,e.code)=(o.plan_id,a.event_code)
    WHERE a.id=NEW.assignment_id
),-1))
BEGIN SELECT RAISE(ABORT,'Invalid coursework review revision or points'); END;
