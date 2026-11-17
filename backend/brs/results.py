"""Drafts and published versions of BRS event results."""
import hashlib
import json
from uuid import uuid4

from ..events import audit
from .service import date_at, fail, get, teaching_access


def context(db, actor, now, offering_id, enrollment_id, event_code):
    flow = teaching_access(db, actor, now, offering_id, enrollment_id=enrollment_id, event_code=event_code)
    course = get(db, """SELECT c.id FROM brs_enrollments n JOIN brs_student_courses c ON c.id=n.course_id
        JOIN users u ON u.id=c.student_id WHERE n.id=? AND u.active=1 AND u.role='student'""", enrollment_id)
    plan_id = flow["plan_id"]
    event = get(db, "SELECT * FROM brs_events WHERE plan_id=? AND code=?", plan_id, event_code)
    return (course["id"], plan_id, event_code), event


def result_for(db, key):
    return db.execute("SELECT id FROM brs_event_results WHERE (course_id,plan_id,event_code)=(?,?,?)", key).fetchone()


def latest_versions(db, result_id):
    return db.execute("""SELECT v.* FROM brs_attempt_versions v WHERE v.result_id=?
        AND NOT EXISTS (SELECT 1 FROM brs_attempt_versions newer WHERE newer.result_id=v.result_id
            AND newer.attempt_no=v.attempt_no AND newer.revision_no>v.revision_no)
        ORDER BY v.attempt_no""", (result_id,)).fetchall()


def version_summary(row):
    return {field: row[field] for field in
            ("id", "result_id", "attempt_no", "revision_no", "result_version", "points", "published_at")}


def effective(attempts, policy):
    if not attempts:
        return None
    if policy == "highest":
        return max(attempts, key=lambda row: (row["points"], -row["attempt_no"]))
    if policy == "latest":
        return attempts[-1]
    return attempts[0]


def submission_for(db, enrollment, key, attempt):
    return db.execute("""SELECT registered_at,registered_by FROM brs_attempt_submissions
        WHERE (enrollment_id,course_id,plan_id,event_code,attempt_no)=(?,?,?,?,?)""",
        (enrollment, *key, attempt)).fetchone()


def draft_for(db, enrollment, key, attempt):
    return db.execute("""SELECT points,version,author_id,updated_at FROM brs_attempt_drafts
        WHERE (enrollment_id,course_id,plan_id,event_code,attempt_no)=(?,?,?,?,?)""",
        (enrollment, *key, attempt)).fetchone()


def stream(db, key):
    row = result_for(db, key)
    result = row["id"] if row else None
    attempts = latest_versions(db, result) if result else []
    version = max((item["result_version"] for item in attempts), default=0)
    return result, attempts, version


def check_next(event, attempts, attempt):
    if attempt > event["attempt_limit"] or (attempt > 1 and event["retake_policy"] == "none"):
        fail(422, "Попытка не предусмотрена планом.")
    if attempt != len(attempts) + 1:
        fail(409, "Номер следующей попытки изменился.")


def check_submission(db, enrollment, key, attempt, event, now):
    if attempt == 1:
        return
    submission = submission_for(db, enrollment, key, attempt)
    if (submission is None or submission["registered_at"] > now
            or date_at(submission["registered_at"]) > event["retake_until"]):
        fail(422, "Для пересдачи нужна своевременная регистрация сдачи.")


def register_submission(db, actor, now, offering, enrollment, event_code, attempt):
    key, event = context(db, actor, now, offering, enrollment, event_code)
    if attempt < 2:
        fail(422, "Регистрация сдачи предусмотрена для пересдач.")
    _, attempts, _ = stream(db, key)
    check_next(event, attempts, attempt)
    existing = submission_for(db, enrollment, key, attempt)
    if existing:
        return submission_summary(existing)
    if date_at(now) > event["retake_until"]:
        fail(422, "Срок регистрации сдачи истёк.")
    db.execute("INSERT INTO brs_attempt_submissions VALUES (?,?,?,?,?,?,?)",
               (enrollment, *key, attempt, now, actor["id"]))
    audit(db, actor, "brs.submission.register", "brs_attempt_submission",
          f"{enrollment}/{event_code}/{attempt}", None, now)
    return submission_summary({"registered_at": now, "registered_by": actor["id"]})


def submission_summary(row):
    return {"source": "teacher_registered", "registered_at": row["registered_at"],
            "registered_by": row["registered_by"], "independently_verified": False}


def staff_result(db, actor, now, offering, enrollment, event_code):
    key, event = context(db, actor, now, offering, enrollment, event_code)
    result, attempts, version = stream(db, key)
    next_attempt = len(attempts) + 1
    draft = draft_for(db, enrollment, key, next_attempt)
    submission = submission_for(db, enrollment, key, next_attempt)
    chosen = effective(attempts, event["retake_policy"])
    return {"result_id": result, "result_version": version, "next_attempt": next_attempt,
            "maximum": event["maximum"], "effective_points": chosen["points"] if chosen else None,
            "attempts": [{**version_summary(row), "from_current_enrollment": row["enrollment_id"] == enrollment}
                         for row in attempts],
            "draft": dict(draft) if draft else None,
            "submission": submission_summary(submission) if submission else None}


def save_draft(db, actor, now, offering, enrollment, event_code, attempt, data):
    key, event = context(db, actor, now, offering, enrollment, event_code)
    _, attempts, _ = stream(db, key)
    check_next(event, attempts, attempt)
    check_submission(db, enrollment, key, attempt, event, now)
    if data["points"] > event["maximum"]:
        fail(422, "Баллы превышают максимум мероприятия.")
    previous = draft_for(db, enrollment, key, attempt)
    version = previous["version"] if previous else 0
    if version != data["expected_draft_version"]:
        fail(409, "Версия черновика изменилась.")
    db.execute("""INSERT INTO brs_attempt_drafts VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(enrollment_id,plan_id,event_code,attempt_no) DO UPDATE SET
            points=excluded.points,version=excluded.version,author_id=excluded.author_id,updated_at=excluded.updated_at""",
        (enrollment, *key, attempt, data["points"], version + 1, actor["id"], now))
    audit(db, actor, "brs.draft.save", "brs_attempt_draft",
          f"{enrollment}/{event_code}/{attempt}", version + 1, now)
    return {"attempt_no": attempt, "draft_version": version + 1, "points": data["points"]}


def payload_hash(offering, enrollment, event, attempt, data):
    return hashlib.sha256(json.dumps([offering, enrollment, event, attempt, data],
                                     sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def replay(db, actor, command, offering, enrollment, event, attempt, data):
    row = db.execute("""SELECT r.payload_hash,r.fingerprint_unit,v.* FROM brs_operation_receipts r
        JOIN brs_attempt_versions v ON v.id=r.version_id
        WHERE (r.actor_id,r.command,r.request_key)=(?,?,?)""",
        (actor["id"], command, data["request_key"])).fetchone()
    if row is not None:
        # Old correction fingerprints include points expressed in hundredths.
        payload = data
        if row["fingerprint_unit"] == "hundredths" and command == "correct":
            payload = {**data, "points": data["points"] * 100}
        fingerprint = payload_hash(offering, enrollment, event, attempt, payload)
        if row["payload_hash"] != fingerprint:
            fail(409, "Ключ операции уже использован с другими данными.")
        return version_summary(row)


def save_receipt(db, actor, command, request_key, fingerprint, version_id):
    db.execute("""INSERT INTO brs_operation_receipts
        (actor_id,command,request_key,payload_hash,version_id,fingerprint_unit)
        VALUES (?,?,?,?,?,'whole')""",
               (actor["id"], command, request_key, fingerprint, version_id))


def change_result(db, actor, now, offering, enrollment, event_code, attempt, data, *, command):
    if not db.in_transaction:
        raise RuntimeError('BRS publication requires a write transaction.')
    key, event = context(db, actor, now, offering, enrollment, event_code)
    fingerprint = payload_hash(offering, enrollment, event_code, attempt, data)
    previous = replay(db, actor, command, offering, enrollment, event_code, attempt, data)
    if previous is not None:
        return previous
    result, attempts, version = stream(db, key)
    if command == "correct":
        current = next((row for row in attempts if row["attempt_no"] == attempt), None)
        if current is None or current["enrollment_id"] != enrollment:
            fail(404)
        if db.execute('SELECT 1 FROM coursework_brs_sources WHERE version_id=?', (current['id'],)).fetchone():
            fail(409, 'Исправьте результат через новую проверку учебной работы.')
    if version != data["expected_result_version"]:
        fail(409, "Версия результата изменилась.")

    if command == "publish":
        if db.execute("""SELECT 1 FROM coursework_brs_reservations
            WHERE (offering_id,course_id,plan_id,event_code)=(?,?,?,?) LIMIT 1""",
                      (offering, *key)).fetchone():
            fail(409, "Публикация недоступна: мероприятие связано с учебной работой.")
        check_next(event, attempts, attempt)
        check_submission(db, enrollment, key, attempt, event, now)
        draft = draft_for(db, enrollment, key, attempt)
        if draft is None or draft["version"] != data["expected_draft_version"]:
            fail(409, "Черновик отсутствует или изменился.")
        points, revision, reason = draft["points"], 1, None
    else:
        points, revision, reason = data["points"], current["revision_no"] + 1, data["reason"]
        if points == current["points"]:
            fail(422, "Укажите изменённое значение.")
    if points > event["maximum"]:
        fail(422, "Баллы превышают максимум мероприятия.")

    if result is None:
        result = uuid4().hex
        db.execute("INSERT INTO brs_event_results VALUES (?,?,?,?)", (result, *key))
    version_id = uuid4().hex
    db.execute("INSERT INTO brs_attempt_versions VALUES (?,?,?,?,?,?,?,?,?,?)",
               (version_id, result, enrollment, attempt, revision, version + 1, points, actor["id"], now, reason))
    if command == "publish":
        db.execute("""DELETE FROM brs_attempt_drafts
            WHERE (enrollment_id,course_id,plan_id,event_code,attempt_no)=(?,?,?,?,?)""",
            (enrollment, *key, attempt))
    audit(db, actor, "brs.attempt." + command, "brs_attempt_version", version_id, version + 1, now, required=True)
    save_receipt(db, actor, command, data["request_key"], fingerprint, version_id)
    return version_summary(get(db, "SELECT * FROM brs_attempt_versions WHERE id=?", version_id))


def own_course(db, actor, key):
    if actor["role"] != "student":
        fail(403, "Доступно студенту.")
    return get(db, "SELECT id FROM brs_student_courses WHERE id=? AND student_id=?", key, actor["id"])


def student_results(db, actor, course):
    own_course(db, actor, course)
    plans = db.execute("""SELECT DISTINCT o.plan_id FROM brs_enrollments n
        JOIN brs_offerings o ON o.id=n.offering_id JOIN brs_whole_plans p ON p.id=o.plan_id
        WHERE n.course_id=? AND p.locked_at IS NOT NULL ORDER BY o.plan_id""", (course,)).fetchall()
    summaries = []
    for plan in plans:
        plan_id = plan["plan_id"]
        categories = {row["code"]: {**dict(row), "points": 0} for row in db.execute(
            "SELECT code,maximum FROM brs_categories WHERE plan_id=? ORDER BY code", (plan_id,))}
        events = []
        for event in db.execute("SELECT * FROM brs_events WHERE plan_id=? ORDER BY code", (plan_id,)):
            result, attempts, version = stream(db, (course, plan_id, event["code"]))
            chosen = effective(attempts, event["retake_policy"])
            points = chosen["points"] if chosen else None
            if points is not None:
                categories[event["category_code"]]["points"] += points
            events.append({"event_code": event["code"], "maximum": event["maximum"],
                           "result_id": result, "result_version": version, "effective_points": points,
                           "effective_attempt": chosen["attempt_no"] if chosen else None,
                           "attempts": [version_summary(row) for row in attempts]})
        total = sum(row["points"] for row in categories.values())
        if total > 100 or any(row["points"] > row["maximum"] for row in categories.values()):
            fail(503, "Данные плана или результата недоступны.")
        summaries.append({"plan_id": plan_id, "events": events, "categories": list(categories.values()),
                          "published_points": total})
    return {"course_id": course, "plans": summaries,
            "combined_points": summaries[0]["published_points"] if len(summaries) == 1 else None}


def student_history(db, actor, course, result):
    own_course(db, actor, course)
    get(db, "SELECT id FROM brs_event_results WHERE id=? AND course_id=?", result, course)
    rows = db.execute("""SELECT v.*,p.full_name,previous.points AS old_points,s.registered_at
        FROM brs_attempt_versions v JOIN staff_profiles p ON p.user_id=v.actor_id
        JOIN brs_event_results r ON r.id=v.result_id
        LEFT JOIN brs_attempt_versions previous ON previous.result_id=v.result_id
            AND previous.attempt_no=v.attempt_no AND previous.revision_no=v.revision_no-1
        LEFT JOIN brs_attempt_submissions s ON
            (s.enrollment_id,s.plan_id,s.event_code,s.attempt_no)=(v.enrollment_id,r.plan_id,r.event_code,v.attempt_no)
        WHERE v.result_id=? ORDER BY v.result_version""", (result,))
    return {"result_id": result, "history": [
        {**version_summary(row), "old_points": row["old_points"], "reason": row["reason"],
         "submission": {"source": "teacher_registered", "independently_verified": False,
                        "registered_at": row["registered_at"]} if row["registered_at"] is not None else None,
         "author": row["full_name"], "state": "published" if row["revision_no"] == 1 else "corrected"}
        for row in rows]}
