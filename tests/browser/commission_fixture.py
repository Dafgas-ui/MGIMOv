"""Prepare a historical snapshot on the disposable test copy only."""
import json
from contextlib import closing

from backend.migrations.manager import open_database


def prepare_commission(database, course, login):
    with closing(open_database(database, readonly=False)) as db:
        db.execute("BEGIN IMMEDIATE")
        slots = db.execute(
            "SELECT id,ends_at,examiner_id,commission FROM attestation_slots WHERE course_id=? AND number=3",
            (course,),
        ).fetchall()
        if len(slots) != 1 or slots[0][2] != "t02" or set(json.loads(slots[0][3])) != {"t02", "t03"}:
            raise ValueError("Expected the original T02/T03 commission")
        slot, ends_at, _, _ = slots[0]
        events = db.execute(
            "SELECT version,slot_id,kind,json_extract(data,'$.grade'),at FROM attestation_events "
            "WHERE course_id=? ORDER BY version", (course,),
        ).fetchall()
        third = [event for event in events if event[1] == slot]
        prefix = third[0][0]
        expected = [("scheduled", None), ("draft", 4), ("published", 4), ("completed", None)]
        if login == "s02" and [event[2:4] for event in third] == expected and events[-4:] == third:
            # Rewind a known terminal suffix and its side effects. Keep the
            # original appointment and both previous attempts verbatim.
            for trigger, table, predicate, params in (
                ("attestation_receipt_no_delete", "attestation_receipts", "course_id=? AND version>?", (course, prefix)),
                ("staff_audit_no_delete", "staff_audit", "resource_kind='brs_course' AND resource_id=? AND version>? AND action IN ('attestation.draft','attestation.published','attestation.completed')", (course, prefix)),
                ("attestation_event_no_delete", "attestation_events", "course_id=? AND version>?", (course, prefix)),
            ):
                sql, = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (trigger,)).fetchone()
                db.execute(f"DROP TRIGGER {trigger}")
                db.execute(f"DELETE FROM {table} WHERE {predicate}", params)
                db.execute(sql)
            db.execute("DELETE FROM notifications WHERE user_id=? AND event_key=?",
                       (login, f"attestation:{course}:{third[2][0]}"))
        elif login != "s05" or [event[2:4] for event in third] != [("scheduled", None), ("draft", 2)] or events[-2:] != third:
            raise ValueError("Unexpected commission fixture history")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Commission snapshot contains an invalid foreign key")
        db.commit()
        return max(ends_at, events[-1][4]) + 60
