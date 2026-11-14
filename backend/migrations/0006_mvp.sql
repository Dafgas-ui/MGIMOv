CREATE TABLE notifications (
 id TEXT PRIMARY KEY NOT NULL,
 user_id TEXT NOT NULL REFERENCES users(id),
 title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 160),
 body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 1000),
 kind TEXT NOT NULL CHECK(kind IN ('lesson','request','document','message')),
 resource_id TEXT,
 created_at INTEGER NOT NULL,
 read_at INTEGER,
 event_key TEXT NOT NULL,
 UNIQUE(user_id,event_key)
);
CREATE INDEX notifications_owner ON notifications(user_id,created_at DESC,id DESC);
CREATE TABLE demo_documents (
 id TEXT PRIMARY KEY NOT NULL,
 student_id TEXT NOT NULL REFERENCES student_profiles(user_id),
 request_id TEXT NOT NULL UNIQUE REFERENCES student_requests(id),
 faculty_id TEXT NOT NULL REFERENCES faculties(id),
 issuer_id TEXT NOT NULL REFERENCES staff_profiles(user_id),
 content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 12000),
 content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
 signed_at INTEGER NOT NULL,
 delivered_at INTEGER CHECK(delivered_at IS NULL OR delivered_at>=signed_at)
);
CREATE INDEX documents_owner ON demo_documents(student_id,delivered_at);
CREATE TRIGGER document_immutable BEFORE UPDATE OF student_id,request_id,faculty_id,issuer_id,content,content_hash,signed_at ON demo_documents BEGIN
 SELECT RAISE(ABORT,'Issued document is immutable');
END;
CREATE TABLE staff_audit (
 id TEXT PRIMARY KEY NOT NULL,
 actor_id TEXT NOT NULL REFERENCES staff_profiles(user_id),
 action TEXT NOT NULL,
 resource_kind TEXT NOT NULL,
 resource_id TEXT NOT NULL,
 version INTEGER,
 created_at INTEGER NOT NULL
);
CREATE TRIGGER staff_audit_no_update BEFORE UPDATE ON staff_audit BEGIN SELECT RAISE(ABORT,'Audit is append only'); END;
CREATE TRIGGER staff_audit_no_delete BEFORE DELETE ON staff_audit BEGIN SELECT RAISE(ABORT,'Audit is append only'); END;
CREATE TABLE registration_invitations (
 token_hash TEXT PRIMARY KEY NOT NULL CHECK(length(token_hash)=64),
 group_id TEXT NOT NULL REFERENCES study_groups(id),
 expires_at INTEGER NOT NULL,
 consumed_by TEXT REFERENCES users(id),
 created_at INTEGER NOT NULL
);
