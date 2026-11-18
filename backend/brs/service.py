"""Server-side plan, teaching scope and enrollment operations."""
from datetime import datetime, timedelta
import json
import sqlite3
from uuid import uuid4

from ..auth.service import AuthError
from ..events import audit
from ..schedule.service import MOSCOW, calendar_date

SCALE = {"credit": ("fail", "pass"), "exam": ("2", "3", "4", "5"),
         "graded_credit": ("2", "3", "4", "5")}


def fail(status, message="Объект БРС недоступен."):
    raise AuthError(status, message)


def get(db, sql, *args):
    row = db.execute(sql, args).fetchone()
    if row is None:
        fail(404)
    return row


def scope(db, actor, faculty, capability):
    if not db.execute(
        "SELECT 1 FROM brs_capabilities WHERE staff_id=? AND faculty_id=? AND capability=?",
        (actor["id"], faculty, capability),
    ).fetchone():
        fail(404)


def set_capability(db, operator_id, now, staff_id, faculty_id, capability, *, enabled):
    """Trusted local provisioning only. There is no HTTP delegation of capabilities."""
    operator = get(db, "SELECT id FROM users WHERE id=? AND role='staff' AND active=1", operator_id)
    get(db, "SELECT id FROM users WHERE id=? AND role='staff' AND active=1", staff_id)
    if enabled:
        changed = db.execute("INSERT INTO brs_capabilities VALUES (?,?,?) ON CONFLICT DO NOTHING",
                             (staff_id, faculty_id, capability)).rowcount
    else:
        changed = db.execute("DELETE FROM brs_capabilities WHERE staff_id=? AND faculty_id=? AND capability=?",
                             (staff_id, faculty_id, capability)).rowcount
    if changed:
        action = 'grant' if enabled else 'revoke'
        audit(db, operator, f"brs.capability.{action}.{capability}", "faculty_staff", f"{faculty_id}/{staff_id}", None, now)


CURRICULUM = """SELECT c.*, p.faculty_id, s.starts_on, s.ends_on
    FROM curriculum_items c JOIN programs p ON p.id=c.program_id
    JOIN semesters s ON s.id=c.semester_id"""


def curriculum(db, key):
    return get(db, CURRICULUM + " WHERE c.id=?", key)


OFFERINGS = """SELECT o.*, c.id AS curriculum_id, c.subject_id, c.semester_id,
        pr.faculty_id, s.starts_on, s.ends_on, subject.name AS subject_name, gname.name AS group_name
        FROM brs_offerings o JOIN brs_whole_plans p ON p.id=o.plan_id
        JOIN curriculum_items c ON c.id=p.curriculum_id
        JOIN programs pr ON pr.id=c.program_id JOIN semesters s ON s.id=c.semester_id
        JOIN subjects subject ON subject.id=c.subject_id JOIN study_groups gname ON gname.id=o.group_id
        WHERE p.locked_at IS NOT NULL"""


def offering(db, key):
    return get(db, OFFERINGS + " AND o.id=?", key)


def plan_data(db, key):
    plan = dict(get(db, "SELECT * FROM brs_whole_plans WHERE id=?", key))
    for name, order in (("categories", "code"), ("events", "code"), ("scale", "minimum")):
        plan[name] = [dict(row) for row in db.execute(
            f"SELECT * FROM brs_{name} WHERE plan_id=? ORDER BY {order}", (key,))]
    return plan


def validate_credit_scale(plan, item):
    if item['control'] == 'credit' and sorted(
            (row['minimum'], row['outcome']) for row in plan['scale']) != [(0, 'fail'), (50, 'pass')]:
        fail(422, 'Для обычного зачёта порог «зачтено» фиксирован: 50 баллов.')


def validate_plan(plan, item):
    validate_credit_scale(plan, item)
    categories = {row["code"]: row["maximum"] for row in plan["categories"]}
    if (len(categories) != len(plan["categories"]) or sum(categories.values()) != 100
            or any(value <= 0 for value in categories.values())):
        fail(422, "Максимумы категорий должны составлять 100 баллов.")
    for row in (*plan["categories"], *plan["events"]):
        if row["admission_min"] is not None and row["admission_min"] > row["maximum"]:
            fail(422, "Условие допуска превышает максимум.")
    totals = dict.fromkeys(categories, 0)
    seen = set()
    for row in plan["events"]:
        code, category = row["code"], row["category_code"]
        if code in seen or category not in totals or row["maximum"] <= 0:
            fail(422, "Проверьте события и их категории.")
        seen.add(code)
        totals[category] += row["maximum"]
        until = row["retake_until"]
        if row["attempt_limit"] == 1:
            if row["retake_policy"] != "none" or until is not None:
                fail(422, "Пересдача не предусмотрена.")
        elif (row["retake_policy"] == "none" or until is None
              or calendar_date(until).isoformat() < item["starts_on"]
              or until > item["ends_on"]):
            fail(422, "Правила пересдачи выходят за границы семестра.")
    if totals != categories:
        fail(422, "Максимумы событий должны совпадать с максимумами категорий.")
    scale = sorted(plan["scale"], key=lambda row: row["minimum"])
    thresholds = [row["minimum"] for row in scale]
    if (tuple(row["outcome"] for row in scale) != SCALE[item["control"]]
            or thresholds[0] != 0 or len(set(thresholds)) != len(thresholds)):
        fail(422, "Шкала должна начинаться с нуля и содержать все исходы аттестации по порядку.")
    if (not plan["source"].strip()
            or calendar_date(plan["approved_on"]).isoformat() >= item["starts_on"]):
        fail(422, "Укажите источник утверждения и дату до начала семестра.")


def create_plan(db, actor, now, data):
    item = curriculum(db, data["curriculum_id"])
    scope(db, actor, item["faculty_id"], "manage_plans")
    validate_plan(data, item)
    key = uuid4().hex
    db.execute("""INSERT INTO brs_whole_plans
        (id,curriculum_id,source,approved_on,rounding,admission_min) VALUES (?,?,?,?,?,?)""",
        (key, data["curriculum_id"], data["source"].strip(), data["approved_on"],
         data["rounding"], data["admission_min"]))
    for table, fields in (
        ("categories", ("code", "title", "maximum", "admission_min")),
        ("events", ("code", "category_code", "title", "maximum", "admission_min", "attempt_limit", "retake_policy", "retake_until")),
        ("scale", ("minimum", "outcome")),
    ):
        columns = ",".join(fields)
        marks = ",".join("?" for _ in range(len(fields) + 1))
        db.executemany(f"INSERT INTO brs_{table}(plan_id,{columns}) VALUES ({marks})",
                       [(key, *(row[field] for field in fields)) for row in data[table]])
    audit(db, actor, "brs.plan.create", "brs_plan", key, None, now)
    return {"id": key}


def lock_plan(db, actor, now, key):
    plan = plan_data(db, key)
    item = curriculum(db, plan["curriculum_id"])
    scope(db, actor, item["faculty_id"], "manage_plans")
    if plan["locked_at"] is not None:
        fail(409, "План уже зафиксирован.")
    validate_plan(plan, item)
    db.execute("UPDATE brs_whole_plans SET locked_at=?,locked_by=? WHERE id=?", (now, actor["id"], key))
    audit(db, actor, "brs.plan.lock", "brs_plan", key, None, now)
    return {"id": key, "locked_at": now}


def create_offering(db, actor, now, data):
    plan = get(db, "SELECT * FROM brs_whole_plans WHERE id=? AND locked_at IS NOT NULL", data["plan_id"])
    item = curriculum(db, plan["curriculum_id"])
    scope(db, actor, item["faculty_id"], "manage_plans")
    get(db, "SELECT id FROM study_groups WHERE id=? AND program_id=?", data["group_id"], item["program_id"])
    if db.execute("""SELECT 1 FROM brs_offerings o JOIN brs_whole_plans p ON p.id=o.plan_id
        WHERE o.group_id=? AND p.curriculum_id=?""", (data["group_id"], item["id"])).fetchone():
        fail(409, "Для этой группы и позиции учебного плана поток уже существует.")
    key = uuid4().hex
    db.execute("INSERT INTO brs_offerings VALUES (?,?,?)", (key, plan["id"], data["group_id"]))
    audit(db, actor, "brs.offering.create", "brs_offering", key, None, now)
    return {"id": key}


def bind_teacher(db, actor, now, data):
    lesson = get(db, """SELECT l.*, p.faculty_id FROM lessons l
        JOIN study_groups g ON g.id=l.group_id JOIN programs p ON p.id=g.program_id
        WHERE l.id=? AND l.status='scheduled' AND l.teacher_id=?""", data["lesson_id"], data["teacher_id"])
    scope(db, actor, lesson["faculty_id"], "manage_teaching")
    if actor["id"] == data["staff_id"]:
        fail(403, "Самостоятельная привязка запрещена.")
    get(db, "SELECT id FROM users WHERE id=? AND role='staff' AND active=1", data["staff_id"])
    db.execute("INSERT INTO brs_whole_teacher_accounts VALUES (?,?)", (data["staff_id"], data["teacher_id"]))
    audit(db, actor, "brs.teacher.bind", "staff", data["staff_id"], None, now)
    return {"id": data["staff_id"]}


def date_at(timestamp):
    return datetime.fromtimestamp(timestamp, MOSCOW).date().isoformat()


def grant_teaching(db, actor, now, key, data):
    flow = offering(db, key)
    scope(db, actor, flow["faculty_id"], "manage_teaching")
    if actor["id"] == data["staff_id"]:
        fail(403, "Самоподтверждение запрещено.")
    lesson = get(db, """SELECT l.* FROM lessons l JOIN brs_whole_teacher_accounts t ON t.teacher_id=l.teacher_id
        JOIN users u ON u.id=t.staff_id WHERE l.id=? AND t.staff_id=? AND u.active=1
        AND u.role='staff' AND l.group_id=? AND l.subject_id=? AND l.status='scheduled'
        AND l.date BETWEEN ? AND ?""", data["lesson_id"], data["staff_id"], flow["group_id"],
        flow["subject_id"], flow["starts_on"], flow["ends_on"])
    if data["lesson_version"] != lesson["version"]:
        fail(409, "Расписание изменилось.")
    event_code = data["event_code"]
    if event_code is None:
        changes = db.execute("SELECT before_json,after_json FROM lesson_changes WHERE lesson_id=?", (lesson["id"],))
        if any(json.loads(row["before_json"])["teacher_id"] != json.loads(row["after_json"])["teacher_id"]
               for row in changes):
            fail(422, "Для замены укажите отдельное событие БРС.")
    if event_code is not None:
        if data["can_confirm_final"]:
            fail(422, "Назначение на отдельное событие не даёт права подтверждать итог.")
        get(db, "SELECT code FROM brs_events WHERE plan_id=? AND code=?", flow["plan_id"], event_code)
    end = calendar_date(flow["ends_on"]) + timedelta(days=1)
    boundary = int(datetime.combine(end, datetime.min.time(), MOSCOW).timestamp())
    if not now < data["expires_at"] <= boundary:
        fail(422, "Срок назначения должен завершаться в пределах семестра.")
    if data["can_confirm_final"] and db.execute("""SELECT 1 FROM brs_whole_teaching_grants
        WHERE offering_id=? AND can_confirm_final=1 AND revoked_at IS NULL AND expires_at>?""",
        (key, now)).fetchone():
        fail(409, "Ответственный преподаватель уже назначен.")
    grant = uuid4().hex
    db.execute("""INSERT INTO brs_whole_teaching_grants
        (id,offering_id,staff_id,lesson_id,lesson_version,approver_id,can_confirm_final,event_code,starts_at,expires_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)""", (grant, key, data["staff_id"], lesson["id"], lesson["version"],
        actor["id"], data["can_confirm_final"], event_code, now, data["expires_at"]))
    audit(db, actor, "brs.grant.approve", "brs_grant", grant, lesson["version"], now)
    return {"id": grant}


def revoke_teaching(db, actor, now, key):
    grant = get(db, "SELECT * FROM brs_whole_teaching_grants WHERE id=?", key)
    flow = offering(db, grant["offering_id"])
    scope(db, actor, flow["faculty_id"], "manage_teaching")
    if grant["revoked_at"] is not None:
        fail(409, "Назначение уже отозвано.")
    db.execute("UPDATE brs_whole_teaching_grants SET revoked_at=? WHERE id=?", (now, key))
    audit(db, actor, "brs.grant.revoke", "brs_grant", key, None, now)
    return {"id": key}


def teaching_offerings(db, actor, now, key=None, *, semester_id=None, event_code=None, confirm=False):
    if actor["role"] != "staff":
        fail(403, "Доступно преподавателю.")
    return db.execute(OFFERINGS + """ AND (? IS NULL OR o.id=?)
        AND (? IS NULL OR c.semester_id=?) AND ? BETWEEN s.starts_on AND s.ends_on
        AND EXISTS (
            SELECT 1 FROM brs_whole_teaching_grants g
            JOIN brs_whole_teacher_accounts t ON t.staff_id=g.staff_id JOIN lessons l ON l.id=g.lesson_id
            WHERE g.offering_id=o.id AND g.staff_id=? AND g.revoked_at IS NULL
            AND g.starts_at<=? AND g.expires_at>? AND l.teacher_id=t.teacher_id
            AND l.group_id=o.group_id AND l.subject_id=c.subject_id AND l.status='scheduled'
            AND l.date BETWEEN s.starts_on AND s.ends_on AND (?=0 OR g.can_confirm_final=1)
            AND (g.event_code IS NULL OR g.event_code=?)
            AND NOT EXISTS (
                SELECT 1 FROM lesson_changes ch WHERE ch.lesson_id=g.lesson_id
                AND ch.version>g.lesson_version
                AND (json_extract(ch.after_json,'$.teacher_id') IS NOT t.teacher_id
                     OR json_extract(ch.after_json,'$.status') IS NOT 'scheduled'
                     OR coalesce(json_extract(ch.after_json,'$.date') BETWEEN s.starts_on AND s.ends_on,0)=0)
            )
        ) ORDER BY o.id""",
        (key, key, semester_id, semester_id, date_at(now), actor["id"], now, now, int(confirm), event_code))


def teaching_access(db, actor, now, key, *, enrollment_id=None, event_code=None, confirm=False):
    flow = teaching_offerings(db, actor, now, key, event_code=event_code, confirm=confirm).fetchone()
    if flow is None:
        fail(404)
    if enrollment_id is not None:
        get(db, """SELECT id FROM brs_enrollments WHERE id=? AND offering_id=?
            AND starts_on<=? AND ends_on IS NULL""", enrollment_id, key, date_at(now))
    if event_code is not None:
        get(db, "SELECT code FROM brs_events WHERE plan_id=? AND code=?", flow["plan_id"], event_code)
    return flow


def enroll(db, actor, now, key, data):
    flow = offering(db, key)
    scope(db, actor, flow["faculty_id"], "manage_enrollments")
    student = get(db, """SELECT p.user_id FROM student_profiles p JOIN users u ON u.id=p.user_id
        WHERE p.user_id=? AND p.group_id=? AND u.role='student' AND u.active=1""",
        data["student_id"], flow["group_id"])
    day = calendar_date(data["starts_on"]).isoformat()
    if not flow["starts_on"] <= day <= flow["ends_on"]:
        fail(422, "Зачисление должно относиться к семестру.")
    if db.execute("""SELECT 1 FROM brs_student_courses WHERE student_id=? AND curriculum_id=?""",
                  (student["user_id"], flow["curriculum_id"])).fetchone():
        fail(409, "Курс студента уже существует. Для смены потока используйте перевод.")
    course, enrollment = uuid4().hex, uuid4().hex
    db.execute("INSERT INTO brs_student_courses VALUES (?,?,?)", (course, student["user_id"], flow["curriculum_id"]))
    db.execute("""INSERT INTO brs_enrollments (id,course_id,offering_id,starts_on,reason)
        VALUES (?,?,?,?,?)""", (enrollment, course, key, day, "initial"))
    audit(db, actor, "brs.enrollment.create", "brs_enrollment", enrollment, None, now)
    return {"id": enrollment, "course_id": course}


def transfer(db, actor, now, key, data):
    current = get(db, "SELECT * FROM brs_enrollments WHERE id=?", key)
    old = offering(db, current["offering_id"])
    scope(db, actor, old["faculty_id"], "manage_enrollments")
    new = offering(db, data["target_offering_id"])
    scope(db, actor, new["faculty_id"], "manage_enrollments")
    if current["ends_on"] is not None:
        fail(409, "Зачисление уже закрыто.")
    if old["curriculum_id"] != new["curriculum_id"] or old["group_id"] == new["group_id"]:
        fail(422, "Перевод возможен между разными группами одной позиции учебного плана.")
    day = calendar_date(data["starts_on"]).isoformat()
    if not current["starts_on"] < day <= new["ends_on"] or day > date_at(now):
        fail(422, "Дата перевода должна следовать за зачислением и приходиться на текущий или прошедший день семестра.")
    mapping = data["mapping"]
    if old["plan_id"] == new["plan_id"]:
        if mapping:
            fail(422, "Для идентичного плана сопоставление не нужно.")
    else:
        old_events = {row["code"]: row["maximum"] for row in plan_data(db, old["plan_id"])["events"]}
        new_events = {row["code"]: row["maximum"] for row in plan_data(db, new["plan_id"])["events"]}
        sources = {row["old_event"] for row in mapping}
        targets = {row["new_event"] for row in mapping}
        if (len(sources) != len(mapping) or len(targets) != len(mapping) or sources != old_events.keys()
                or not targets <= new_events.keys()
                or any(old_events[row["old_event"]] > new_events[row["new_event"]] for row in mapping)):
            fail(422, "Нужно полное однозначное сопоставление событий без уменьшения максимумов.")
    target = uuid4().hex
    db.execute("UPDATE brs_enrollments SET ends_on=? WHERE id=?", (day, key))
    db.execute("""INSERT INTO brs_enrollments (id,course_id,offering_id,starts_on,previous_id,reason)
        VALUES (?,?,?,?,?,?)""", (target, current["course_id"], new["id"], day, key, data["reason"]))
    db.executemany("INSERT INTO brs_transfer_events VALUES (?,?,?,?,?)",
                   [(target, old["plan_id"], row["old_event"], new["plan_id"], row["new_event"]) for row in mapping])
    audit(db, actor, "brs.enrollment.transfer", "brs_enrollment", target, None, now)
    return {"id": target, "course_id": current["course_id"]}


def student_plan(db, actor, key):
    if actor["role"] != "student":
        fail(403, "Доступно студенту.")
    row = get(db, """SELECT o.plan_id FROM brs_enrollments e JOIN brs_offerings o ON o.id=e.offering_id
        JOIN brs_student_courses c ON c.id=e.course_id JOIN brs_whole_plans p ON p.id=o.plan_id
        WHERE e.id=? AND c.student_id=? AND p.locked_at IS NOT NULL""", key, actor["id"])
    plan = plan_data(db, row["plan_id"])
    plan.pop("locked_by")
    return plan


def constraint_conflict(error):
    if error.sqlite_errorcode in (sqlite3.SQLITE_CONSTRAINT_UNIQUE, sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY):
        fail(409, "Запись уже существует или изменилась.")
    raise error
