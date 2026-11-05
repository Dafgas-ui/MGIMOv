CREATE TABLE request_staff_scopes (
    staff_id TEXT NOT NULL REFERENCES staff_profiles(user_id),
    faculty_id TEXT NOT NULL REFERENCES faculties(id),
    PRIMARY KEY(staff_id,faculty_id)
);
CREATE TABLE student_requests (
    id TEXT PRIMARY KEY NOT NULL,
    student_id TEXT NOT NULL REFERENCES student_profiles(user_id),
    faculty_id TEXT NOT NULL REFERENCES faculties(id),
    type TEXT NOT NULL CHECK(type IN ('study_certificate','general_certificate','appeal')),
    purpose TEXT NOT NULL CHECK(length(purpose)<=200),
    message TEXT NOT NULL CHECK(length(message) BETWEEN 1 AND 2000),
    status TEXT NOT NULL CHECK(status IN ('submitted','processing','approved','rejected','cancelled')),
    version INTEGER NOT NULL CHECK(version>0),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL CHECK(updated_at>=created_at),
    request_key TEXT NOT NULL CHECK(length(request_key)=32),
    payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64),
    UNIQUE(student_id,request_key),
    CHECK((type='appeal' AND purpose='') OR (type!='appeal' AND length(purpose)>0))
);
CREATE INDEX requests_owner_created ON student_requests(student_id,created_at DESC,id DESC);
CREATE INDEX requests_faculty_created ON student_requests(faculty_id,created_at DESC,id DESC);
CREATE TABLE request_history (
    id TEXT PRIMARY KEY NOT NULL,
    request_id TEXT NOT NULL REFERENCES student_requests(id),
    version INTEGER NOT NULL CHECK(version>0),
    from_status TEXT,
    to_status TEXT NOT NULL CHECK(to_status IN ('submitted','processing','approved','rejected','cancelled')),
    actor_id TEXT NOT NULL REFERENCES users(id),
    actor_role TEXT NOT NULL CHECK(actor_role IN ('student','staff')),
    comment TEXT NOT NULL CHECK(length(comment) BETWEEN 1 AND 1000),
    created_at INTEGER NOT NULL,
    UNIQUE(request_id,version)
);
CREATE TRIGGER request_history_insert BEFORE INSERT ON request_history BEGIN
    SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM student_requests r WHERE r.id=NEW.request_id
        AND r.version=NEW.version AND r.status=NEW.to_status)
        THEN RAISE(ABORT,'History does not match current request') END;
END;
CREATE TRIGGER request_history_no_update BEFORE UPDATE ON request_history BEGIN
    SELECT RAISE(ABORT,'Request history is append only');
END;
CREATE TRIGGER request_history_no_delete BEFORE DELETE ON request_history BEGIN
    SELECT RAISE(ABORT,'Request history is append only');
END;
