CREATE VIEW coursework_protected_assignments AS
SELECT a.id, a.offering_id, a.event_code FROM coursework_assignments a
WHERE a.status='published'
   OR EXISTS (SELECT 1 FROM coursework_recipients r WHERE r.assignment_id=a.id)
   OR EXISTS (SELECT 1 FROM coursework_attempts t WHERE t.assignment_id=a.id)
   OR EXISTS (SELECT 1 FROM coursework_reviews v WHERE v.assignment_id=a.id);

CREATE TRIGGER coursework_assignment_delete_guard BEFORE DELETE ON coursework_assignments
WHEN EXISTS (SELECT 1 FROM coursework_protected_assignments a WHERE a.id=OLD.id)
BEGIN SELECT RAISE(ABORT,'Protected coursework assignment cannot be deleted'); END;

-- REPLACE may delete a conflicting row without running DELETE triggers.
CREATE TRIGGER coursework_assignment_parent_replace_guard BEFORE INSERT ON coursework_assignments
WHEN EXISTS (SELECT 1 FROM coursework_protected_assignments a
    WHERE a.id=NEW.id OR (a.offering_id,a.event_code)=(NEW.offering_id,NEW.event_code))
BEGIN SELECT RAISE(ABORT,'Protected coursework assignment cannot be replaced'); END;

CREATE TRIGGER coursework_recipient_delete_guard BEFORE DELETE ON coursework_recipients
WHEN EXISTS (SELECT 1 FROM coursework_attempts t
    WHERE (t.assignment_id,t.course_id)=(OLD.assignment_id,OLD.course_id))
OR EXISTS (SELECT 1 FROM coursework_reviews v
    WHERE (v.assignment_id,v.course_id)=(OLD.assignment_id,OLD.course_id))
BEGIN SELECT RAISE(ABORT,'Coursework recipient with history cannot be deleted'); END;
