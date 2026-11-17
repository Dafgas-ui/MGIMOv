CREATE TABLE coursework_files (
    id TEXT PRIMARY KEY NOT NULL,
    assignment_id TEXT NOT NULL REFERENCES coursework_assignments(id),
    course_id TEXT,
    attempt_no INTEGER,
    slot INTEGER NOT NULL CHECK (slot IN (1, 2)),
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    content BLOB NOT NULL CHECK (typeof(content)='blob' AND length(content) BETWEEN 1 AND 65536),
    CHECK ((course_id IS NULL) = (attempt_no IS NULL)),
    FOREIGN KEY (assignment_id, course_id, attempt_no)
        REFERENCES coursework_attempts(assignment_id, course_id, number)
) WITHOUT ROWID;
CREATE UNIQUE INDEX coursework_file_material_slot ON coursework_files(assignment_id, slot)
    WHERE course_id IS NULL;
CREATE UNIQUE INDEX coursework_file_attempt_slot ON coursework_files(assignment_id, course_id, attempt_no, slot)
    WHERE course_id IS NOT NULL;

CREATE TRIGGER coursework_file_no_replace BEFORE INSERT ON coursework_files
WHEN EXISTS (SELECT 1 FROM coursework_files f WHERE f.id=NEW.id OR
    (f.assignment_id=NEW.assignment_id AND f.course_id IS NEW.course_id
      AND f.attempt_no IS NEW.attempt_no AND f.slot=NEW.slot))
BEGIN SELECT RAISE(ABORT, 'Coursework file already exists'); END;

CREATE TRIGGER coursework_file_no_update BEFORE UPDATE ON coursework_files
BEGIN SELECT RAISE(ABORT, 'Coursework files are immutable'); END;

CREATE TRIGGER coursework_file_no_delete BEFORE DELETE ON coursework_files
BEGIN SELECT RAISE(ABORT, 'Coursework files are immutable'); END;

CREATE TRIGGER coursework_file_assignment_no_delete BEFORE DELETE ON coursework_assignments
WHEN EXISTS (SELECT 1 FROM coursework_files f WHERE f.assignment_id=OLD.id)
BEGIN SELECT RAISE(ABORT, 'Coursework assignment has files'); END;

CREATE TRIGGER coursework_file_assignment_no_replace BEFORE INSERT ON coursework_assignments
WHEN EXISTS (SELECT 1 FROM coursework_assignments a JOIN coursework_files f ON f.assignment_id=a.id
             WHERE a.id=NEW.id)
BEGIN SELECT RAISE(ABORT, 'Coursework assignment has files'); END;

CREATE TRIGGER coursework_file_assignment_no_orphan AFTER INSERT ON coursework_assignments
WHEN EXISTS (SELECT 1 FROM coursework_files f LEFT JOIN coursework_assignments a ON a.id=f.assignment_id
             WHERE a.id IS NULL)
BEGIN SELECT RAISE(ABORT, 'Coursework assignment has files'); END;

CREATE TRIGGER coursework_file_assignment_no_rekey BEFORE UPDATE OF id ON coursework_assignments
WHEN OLD.id IS NOT NEW.id AND EXISTS (SELECT 1 FROM coursework_files f WHERE f.assignment_id=OLD.id)
BEGIN SELECT RAISE(ABORT, 'Coursework assignment has files'); END;
