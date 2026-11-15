CREATE TABLE coursework_assignments (
    id TEXT PRIMARY KEY NOT NULL,
    offering_id TEXT NOT NULL REFERENCES brs_offerings(id),
    created_by TEXT NOT NULL REFERENCES staff_profiles(user_id),
    kind TEXT NOT NULL CHECK(kind IN ('lab','test','practice','other')),
    title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 160),
    description TEXT NOT NULL CHECK(length(trim(description)) BETWEEN 1 AND 4000),
    due_at INTEGER NOT NULL CHECK(typeof(due_at)='integer' AND due_at>0),
    mode TEXT NOT NULL CHECK(mode IN ('in_person','online','both')),
    created_at INTEGER NOT NULL CHECK(typeof(created_at)='integer' AND created_at>0)
) WITHOUT ROWID;

CREATE INDEX coursework_assignments_offering ON coursework_assignments(offering_id,id);
