CREATE TABLE buildings (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT UNIQUE NOT NULL CHECK (length(name) BETWEEN 1 AND 150)
);
CREATE TABLE rooms (
    id TEXT PRIMARY KEY NOT NULL,
    building_id TEXT NOT NULL REFERENCES buildings(id) ON DELETE RESTRICT,
    number TEXT NOT NULL CHECK (length(number) BETWEEN 1 AND 30),
    capacity INTEGER NOT NULL CHECK (capacity BETWEEN 1 AND 1000),
    equipment TEXT NOT NULL DEFAULT '',
    UNIQUE(building_id, number)
);
CREATE TABLE teachers (id TEXT PRIMARY KEY NOT NULL, full_name TEXT NOT NULL CHECK (length(full_name) BETWEEN 1 AND 150));
CREATE TABLE subjects (id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 200));
CREATE TABLE lessons (
    id TEXT PRIMARY KEY NOT NULL,
    group_id TEXT NOT NULL REFERENCES study_groups(id) ON DELETE RESTRICT,
    subject_id TEXT NOT NULL REFERENCES subjects(id) ON DELETE RESTRICT,
    teacher_id TEXT NOT NULL REFERENCES teachers(id) ON DELETE RESTRICT,
    room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE RESTRICT,
    date TEXT NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    start_minute INTEGER NOT NULL CHECK (start_minute BETWEEN 0 AND 1439),
    end_minute INTEGER NOT NULL CHECK (end_minute BETWEEN 1 AND 1440 AND end_minute>start_minute),
    kind TEXT NOT NULL CHECK (kind IN ('lecture','seminar','practice','lab')),
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','cancelled')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version>0),
    updated_at INTEGER NOT NULL
);
CREATE INDEX lessons_group_date ON lessons(group_id, date);
CREATE INDEX lessons_room_interval ON lessons(room_id, date, start_minute, end_minute);
CREATE TABLE lesson_changes (
    id TEXT PRIMARY KEY NOT NULL,
    lesson_id TEXT NOT NULL REFERENCES lessons(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL CHECK (version>1),
    before_date TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (length(reason) BETWEEN 1 AND 300),
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(lesson_id, version)
);
CREATE INDEX changes_lesson_date ON lesson_changes(lesson_id, before_date);
