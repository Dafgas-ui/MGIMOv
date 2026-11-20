-- One explicit daily window per weekday; NULL/NULL means explicitly closed.
CREATE TABLE building_open_hours (
 building_id TEXT NOT NULL REFERENCES buildings(id) ON DELETE RESTRICT,
 weekday INTEGER NOT NULL CHECK(typeof(weekday)='integer' AND weekday BETWEEN 0 AND 6),
 opens INTEGER, closes INTEGER,
 CHECK((opens IS NULL AND closes IS NULL) OR
   (typeof(opens)='integer' AND typeof(closes)='integer' AND opens>=0 AND opens<closes AND closes<=1440)),
 PRIMARY KEY(building_id,weekday)
) WITHOUT ROWID;
CREATE TABLE room_unavailability (
 id TEXT PRIMARY KEY NOT NULL,
 room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE RESTRICT,
 starts_at INTEGER NOT NULL CHECK(typeof(starts_at)='integer' AND starts_at>0),
 ends_at INTEGER CHECK(ends_at IS NULL OR (typeof(ends_at)='integer' AND ends_at>starts_at)),
 reason TEXT NOT NULL CHECK(length(trim(reason)) BETWEEN 1 AND 300)
) WITHOUT ROWID;
CREATE INDEX room_unavailability_interval ON room_unavailability(room_id,starts_at,ends_at);
