"""Official attestation commands and projections. Commands run under BEGIN IMMEDIATE."""
import hashlib
import json
from datetime import datetime, timedelta
from uuid import uuid4

from ..auth.service import AuthError
from ..brs import results, service as brs
from ..events import audit, notify
from ..schedule.service import MOSCOW

PUBLIC = {'scheduled', 'cancelled', 'published', 'completed', 'excused', 'unexcused',
          'corrected', 'not_admitted', 'admission_restored', 'conflict_resolved'}
OUTCOMES = {'published', 'corrected', 'unexcused'}
FINAL_SLOT = {'cancelled', 'excused', 'unexcused', 'published', 'completed'}


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def permission(db, staff, faculty, name):
    return db.execute("""SELECT 1 FROM attestation_permissions p JOIN users u ON u.id=p.staff_id
        WHERE p.staff_id=? AND p.faculty_id=? AND p.permission=? AND u.active=1 AND u.role='staff'""",
        (staff, faculty, name)).fetchone() is not None


def require(db, actor, position, name):
    if actor['role'] != 'staff' or not permission(db, actor['id'], position['faculty_id'], name):
        brs.fail(404)


def position(db, key):
    return brs.get(db, """SELECT c.id,c.student_id,c.curriculum_id,i.control,i.required,i.semester_id,
        i.subject_id,p.faculty_id,s.ends_on,s.starts_on
        FROM brs_student_courses c JOIN curriculum_items i ON i.id=c.curriculum_id
        JOIN programs p ON p.id=i.program_id JOIN semesters s ON s.id=i.semester_id WHERE c.id=?""", key)


def enrollment(db, course, now):
    return brs.get(db, """SELECT n.id,o.plan_id,o.group_id,o.id AS offering_id
        FROM brs_enrollments n JOIN brs_offerings o ON o.id=n.offering_id
        WHERE n.course_id=? AND n.ends_on IS NULL AND n.starts_on<=?""", course, brs.date_at(now))


def activate(db, actor, now, course):
    item = position(db, course)
    require(db, actor, item, 'schedule')
    flow = enrollment(db, course, now)
    if not db.execute("SELECT 1 FROM attestation_policies WHERE plan_id=?",(flow['plan_id'],)).fetchone():
        brs.fail(409,'Сначала утвердите правила аттестации для плана.')
    if db.execute("SELECT 1 FROM attestation_positions WHERE course_id=?", (course,)).fetchone():
        return {'id':course}
    if db.execute("""SELECT 1 FROM student_assessments sa JOIN assessments a ON a.id=sa.assessment_id
        JOIN assessment_attempts t ON t.assignment_id=sa.id WHERE sa.student_id=? AND a.curriculum_id=?""",
        (item['student_id'],item['curriculum_id'])).fetchone():
        brs.fail(409, 'Учебная позиция уже содержит результаты прежней зачётки.')
    db.execute("INSERT INTO attestation_positions VALUES (?,?,?)", (course, actor['id'], now))
    audit(db, actor, 'attestation.activate', 'brs_course', course, None, now)
    return {'id': course}


def approve_policy(db, actor, now, plan_id, codes):
    plan = brs.plan_data(db, plan_id)
    item = brs.curriculum(db, plan['curriculum_id'])
    brs.scope(db, actor, item['faculty_id'], 'manage_plans')
    if (plan['locked_at'] is None or len(codes)!=len(set(codes))
            or not set(codes)<= {e['code'] for e in plan['events']}):
        brs.fail(422, 'Укажите обязательные мероприятия утверждённого плана.')
    if sorted(c['maximum'] for c in plan['categories']) != [20,20,20,40]:
        brs.fail(422, 'Для официальной аттестации нужен план 20/20/20/40.')
    encoded = encode(sorted(codes))
    existing = db.execute("SELECT required_events FROM attestation_policies WHERE plan_id=?",(plan_id,)).fetchone()
    if existing:
        if existing['required_events']!=encoded:
            brs.fail(409,'Политика уже утверждена.')
        return {'id':plan_id}
    db.execute("INSERT INTO attestation_policies VALUES (?,?,?,?)",
               (plan_id,encoded,actor['id'],now))
    audit(db,actor,'attestation.policy.approve','brs_plan',plan_id,None,now)
    return {'id':plan_id}


def preview(db, item, flow):
    policy = brs.get(db,"SELECT required_events FROM attestation_policies WHERE plan_id=?",flow['plan_id'])
    plan = brs.plan_data(db,flow['plan_id'])
    if db.execute("""SELECT 1 FROM brs_enrollments n JOIN brs_offerings o ON o.id=n.offering_id
        WHERE n.course_id=? AND o.plan_id!=?""",(item['id'],plan['id'])).fetchone():
        brs.fail(409,'Для сменившегося учебного плана требуется сверка результатов.')
    required = set(json.loads(policy['required_events']))
    inputs, missing = [], []
    categories = dict.fromkeys((c['code'] for c in plan['categories']),0)
    for event in plan['events']:
        _, attempts, version = results.stream(db,(item['id'],plan['id'],event['code']))
        chosen = results.effective(attempts,event['retake_policy'])
        points = chosen['points'] if chosen else None
        if event['code'] in required and (points is None or points < (event['admission_min'] or 0)):
            missing.append(event['code'])
        inputs.append({'event':event['code'],'version':version,'id':chosen['id'] if chosen else None,
                       'points':points})
        if points is not None:
            categories[event['category_code']] += points
    total = sum(categories.values())
    minima = [c['code'] for c in plan['categories'] if categories[c['code']]<(c['admission_min'] or 0)]
    control = item['control']
    if control=='graded_credit':
        grade = next((int(s['outcome']) for s in reversed(plan['scale']) if total>=s['minimum']),None)
    else:
        grade = None
    return {'plan_id':plan['id'],'enrollment_id':flow['id'],'inputs':inputs,
            'points':total,'missing':missing,'category_shortfalls':minima,
            'admitted':total>=max(50,plan['admission_min']) and not (missing or minima),
            'grade':grade,'outcome':'pass' if total>=50 else 'fail'}


def load(db, course):
    brs.get(db,"SELECT course_id FROM attestation_positions WHERE course_id=?",course)
    slots = {row['id']:{**dict(row),'commission':json.loads(row['commission'])}
             for row in db.execute("SELECT * FROM attestation_slots WHERE course_id=? ORDER BY starts_at,id",(course,))}
    events = [{**dict(row),'data':json.loads(row['data'])} for row in db.execute(
        "SELECT * FROM attestation_events WHERE course_id=? ORDER BY version",(course,))]
    return slots, events


def state(slots, events):
    stages = {key:'scheduled' for key in slots}
    official, consumption = {}, set()
    admitted = None
    conflict = False
    debts = []
    debt = False
    for event in events:
        kind, slot, data = event['kind'],event['slot_id'],event['data']
        if slot and kind in FINAL_SLOT | {'draft'}:
            stages[slot] = kind
        if kind in OUTCOMES:
            official[slot] = event
            consumption.add(slot)
            latest = max(official,key=lambda key:slots[key]['number'])
            current = official[latest]['data']
            failed = current['outcome'] in ('fail','absent') or current.get('grade')==2
            if debt!=failed:
                debts.append({'active':failed,'at':event['at'],'attempt':slots[latest]['number']})
                debt = failed
            conflict = conflict or data.get('conflict',False)
        elif kind=='conflict_resolved':
            conflict = False
        elif kind in ('not_admitted','admission_restored'):
            admitted = kind=='admission_restored'
    latest = max(official,key=lambda key:slots[key]['number'],default=None)
    return {'stages':stages,'official':official,'latest':official.get(latest),'used':len(consumption),
            'admitted':admitted,'conflict':conflict,'debt':debt,'debt_history':debts}


def staff_access(db, actor, item, slots):
    if actor['role']!='staff':
        brs.fail(403)
    faculty = item['faculty_id']
    if any(permission(db,actor['id'],faculty,name) for name in ('schedule','review','late_request','late_execute')):
        return
    if not permission(db,actor['id'],faculty,'examiner') or not any(
        slot['examiner_id']==actor['id'] for slot in slots.values()
    ):
        brs.fail(404)


def append(db, actor, now, course, version, kind, slot, data):
    db.execute("INSERT INTO attestation_events VALUES (?,?,?,?,?,?,?)",
               (course,version,slot,kind,actor['id'],now,encode(data)))
    audit(db,actor,'attestation.'+kind,'brs_course',course,version,now)
    return {'course_id':course,'version':version,'kind':kind,'slot_id':slot}


def conflicts(db, item, flow, starts, ends, people, room):
    active = db.execute("""SELECT a.*,c.student_id FROM attestation_slots a
        JOIN brs_student_courses c ON c.id=a.course_id WHERE a.starts_at<? AND a.ends_at>?
        AND NOT EXISTS(SELECT 1 FROM attestation_events e WHERE e.slot_id=a.id AND e.kind IN
            ('cancelled','excused','unexcused','completed','published'))""",(ends,starts))
    for row in active:
        if (row['student_id']==item['student_id'] or (room and row['room_id']==room)
                or people.intersection(json.loads(row['commission'])+[row['examiner_id']])):
            brs.fail(409,'Назначение пересекается с другой аттестацией.')
    start = datetime.fromtimestamp(starts,MOSCOW)
    end = datetime.fromtimestamp(ends,MOSCOW)
    day = start.date().isoformat()
    midnight = start.replace(hour=0,minute=0,second=0,microsecond=0)
    left = (starts-int(midnight.timestamp()))//60
    right = (ends-int(midnight.timestamp())+59)//60
    if end.date()!=start.date() and end!=midnight+timedelta(days=1):
        brs.fail(422,'Испытание должно укладываться в один календарный день.')
    groups = {flow['group_id'],brs.get(db,"SELECT group_id FROM student_profiles WHERE user_id=?",
                                     item['student_id'])['group_id']}
    for row in db.execute("""SELECT l.group_id,l.room_id,a.staff_id FROM lessons l
        LEFT JOIN brs_whole_teacher_accounts a ON a.teacher_id=l.teacher_id
        WHERE l.status='scheduled' AND l.date=? AND l.start_minute<? AND l.end_minute>?""",(day,right,left)):
        if row['group_id'] in groups or (room and row['room_id']==room) or row['staff_id'] in people:
            brs.fail(409,'Назначение пересекается с учебным расписанием.')


def check_lesson_conflict(db, lesson):
    if lesson['status']!='scheduled' or not db.execute(
        "SELECT 1 FROM schema_migrations WHERE id='0012_attestations'"
    ).fetchone():
        return
    day = datetime.fromisoformat(lesson['date']).replace(tzinfo=MOSCOW)
    starts = int(day.timestamp())+60*lesson['start_minute']
    ends = int(day.timestamp())+60*lesson['end_minute']
    rows = db.execute("""SELECT a.examiner_id,a.commission,a.room_id,p.group_id,o.group_id AS flow_group
        FROM attestation_slots a JOIN brs_student_courses c ON c.id=a.course_id
        JOIN student_profiles p ON p.user_id=c.student_id
        JOIN brs_enrollments n ON n.id=a.enrollment_id JOIN brs_offerings o ON o.id=n.offering_id
        WHERE a.starts_at<? AND a.ends_at>? AND NOT EXISTS(
          SELECT 1 FROM attestation_events e WHERE e.slot_id=a.id AND e.kind IN
          ('cancelled','excused','unexcused','published','completed'))""",(ends,starts))
    teacher = db.execute("SELECT staff_id FROM brs_whole_teacher_accounts WHERE teacher_id=?",
                         (lesson['teacher_id'],)).fetchone()
    for row in rows:
        if (lesson['group_id'] in (row['group_id'],row['flow_group']) or lesson['room_id']==row['room_id']
                or (teacher and teacher['staff_id'] in [row['examiner_id'],*json.loads(row['commission'])])):
            brs.fail(409,'Время занято назначенной аттестацией.')


def schedule(db, actor, now, item, flow, slots, current, data):
    require(db,actor,item,'schedule')
    if (current['used']>=3 or current['conflict'] or
            (current['latest'] and not current['debt']) or
            any(stage in ('scheduled','draft','published') for stage in current['stages'].values())):
        brs.fail(409,'Следующую попытку сейчас назначить нельзя.')
    starts, ends = data['starts_at'],data['ends_at']
    if starts<=now or ends<=starts or ends-starts>12*3600:
        brs.fail(422,'Укажите будущий интервал аттестации.')
    examiner, commission = data['examiner_id'],data['commission']
    people = set(commission)|{examiner}
    number = current['used']+1
    if (examiner==actor['id'] or actor['id'] in people or len(set(commission))!=len(commission)
            or (number==3 and (examiner not in commission or len(commission)<2))
            or (number!=3 and commission)):
        brs.fail(422,'Проверьте ответственного и состав комиссии.')
    for person in people:
        if not permission(db,person,item['faculty_id'],'examiner'):
            brs.fail(422,'У участника нет полномочий в этой учебной области.')
    if data['room_id']:
        brs.get(db,"SELECT id FROM rooms WHERE id=?",data['room_id'])
    conflicts(db,item,flow,starts,ends,people,data['room_id'])
    key = uuid4().hex
    db.execute("INSERT INTO attestation_slots VALUES (?,?,?,?,?,?,?,?,?,?)",
        (key,item['id'],flow['id'],number,starts,ends,examiner,data['room_id'],encode(commission),actor['id']))
    return key,{'number':number}


def outcome(item, data):
    grade = data.get('grade')
    if item['control']=='credit':
        if grade is not None or data.get('outcome') not in ('pass','fail'):
            brs.fail(422,'Для зачёта укажите результат без оценки.')
        return {'outcome':data['outcome'],'grade':None}
    if type(grade) is not int or grade not in (2,3,4,5) or data.get('outcome') is not None:
        brs.fail(422,'Укажите оценку от 2 до 5.')
    return {'outcome':'graded','grade':grade}


def draft(db, actor, now, item, flow, slot, current, data):
    calculated = preview(db,item,flow)
    if calculated['missing']:
        brs.fail(409,'Есть незавершённые обязательные мероприятия.')
    control = item['control']
    if control=='exam':
        if current['admitted'] is False or not calculated['admitted']:
            brs.fail(409,'Условия допуска к экзамену не выполнены.')
        value = outcome(item,data)
    elif data.get('grade') is not None or data.get('outcome') is not None:
        brs.fail(422,'Результат зачёта рассчитывается по утверждённому плану.')
    elif control=='credit':
        value = {'outcome':calculated['outcome'],'grade':None}
    elif calculated['grade'] is not None:
        value = {'outcome':'graded','grade':calculated['grade']}
    else:
        brs.fail(409,'Баллы ниже утверждённой шкалы.')
    return {**value,'snapshot':calculated}


def matching(events, kind, version):
    return next((e for e in events if e['kind']==kind and e['version']==version),None)


def review(db, actor, now, item, slots, events, current, command, data):
    late = brs.date_at(now)>item['ends_on']
    if command=='review_requested':
        slot = slots.get(data['slot_id'])
        target = current['official'].get(data['slot_id'])
        if not slot or not target or target['kind']=='unexcused':
            brs.fail(404)
        if late:
            require(db,actor,item,'late_request')
            if not permission(db,data['executor_id'],item['faculty_id'],'late_execute'):
                brs.fail(422,'Исполнитель не уполномочен на пересмотр.')
        else:
            require(db,actor,item,'examiner')
            if actor['id']!=slot['examiner_id'] or data['executor_id']!=actor['id']:
                brs.fail(404)
        value = outcome(item,data)
        if all(value[k]==target['data'].get(k) for k in value):
            brs.fail(422,'Укажите изменённый результат.')
        return slot['id'],{**value,'reason':data['reason'],'reference':data['reference'],
                           'executor_id':data['executor_id'],'target_version':target['version'],'late':late}
    request = matching(events,'review_requested',data['review_version'])
    if not request:
        brs.fail(404)
    slot_id = request['slot_id']
    payload = request['data']
    approval = next((e for e in events if e['kind']=='review_approved'
                     and e['data']['review_version']==request['version']),None)
    closed = any(e['kind'] in ('review_revoked','corrected')
                 and e['data']['review_version']==request['version'] for e in events)
    if closed:
        brs.fail(409,'Разрешение уже закрыто.')
    if command in ('review_approved','review_revoked'):
        require(db,actor,item,'review')
        if actor['id'] in (request['actor_id'],payload['executor_id']):
            brs.fail(403,'Согласующий должен быть независимым.')
        if command=='review_revoked':
            if not approval or not data['reason']:
                brs.fail(409,'Разрешение ещё не выдано.')
            return slot_id,{'review_version':request['version'],'reason':data['reason']}
        if approval or late!=payload['late'] or current['official'][slot_id]['version']!=payload['target_version']:
            brs.fail(409,'Основание для согласования изменилось.')
        return slot_id,{'review_version':request['version'],'expires_at':now+48*3600}
    require(db,actor,item,'late_execute' if late else 'examiner')
    if actor['id']!=payload['executor_id']:
        brs.fail(404)
    if (not approval or approval['data']['expires_at']<=now or late!=payload['late']
            or not permission(db,approval['actor_id'],item['faculty_id'],'review')
            or current['official'][slot_id]['version']!=payload['target_version']):
        brs.fail(409,'Разрешение устарело или отозвано.')
    if not late and enrollment(db,item['id'],now)['id']!=slots[slot_id]['enrollment_id']:
        brs.fail(409,'Зачисление изменилось.')
    target = current['official'][slot_id]
    snapshot = target['data'].get('snapshot')
    if item['control']!='exam':
        calculated = preview(db,item,enrollment(db,item['id'],now))
        expected = calculated['outcome'] if item['control']=='credit' else calculated['grade']
        if calculated['missing'] or expected!=payload['grade' if item['control']=='graded_credit' else 'outcome']:
            brs.fail(409,'Исправление должно соответствовать утверждённому плану.')
        snapshot = calculated
    later = any(other['number']>slots[slot_id]['number'] and
                (key in current['official'] or (other['starts_at']<=now and
                 current['stages'][key] in ('scheduled','draft'))) for key,other in slots.items())
    new_pass = payload['outcome']=='pass' or (payload['grade'] or 0)>=3
    return slot_id,{**payload,'review_version':request['version'],'approval_version':approval['version'],
                   'previous':{k:target['data'].get(k) for k in ('outcome','grade')},
                   'snapshot':snapshot,'conflict':later and new_pass}


def applicable_reviews(db, actor, now, item, slots, events, current):
    """Expose command references only, using the same checks as execution."""
    versions = []
    for event in events:
        if event['kind']!='review_requested' or event['data']['executor_id']!=actor['id']:
            continue
        try:
            review(db,actor,now,item,slots,events,current,'corrected',{'review_version':event['version']})
        except AuthError as error:
            if error.status not in (404,409):
                raise
        else:
            versions.append(event['version'])
    return versions


def input_discrepancy(current, calculated):
    official = current['latest']
    snapshot = official['data'].get('snapshot') if official else None
    if not snapshot or not calculated:
        return False
    return (snapshot['plan_id'],snapshot['inputs'])!=(calculated['plan_id'],calculated['inputs'])


def execute(db, actor, now, course, command, data):
    item = position(db,course)
    slots, events = load(db,course)
    staff_access(db,actor,item,slots)
    current = state(slots,events)
    fingerprint = hashlib.sha256(encode([course,command,data]).encode()).hexdigest()
    receipt = db.execute("""SELECT r.fingerprint,e.* FROM attestation_receipts r JOIN attestation_events e
        ON (e.course_id,e.version)=(r.course_id,r.version)
        WHERE r.actor_id=? AND r.request_key=?""",(actor['id'],data['request_key'])).fetchone()
    if receipt:
        if receipt['fingerprint']!=fingerprint:
            brs.fail(409,'Ключ уже использован для другой операции.')
        return {k:receipt[k] for k in ('course_id','version','kind','slot_id')}
    version = len(events)
    if data['expected_version']!=version:
        brs.fail(409,'Данные аттестации изменились.')
    slot_id = data.get('slot_id')
    if command=='scheduled':
        flow = enrollment(db,course,now)
        slot_id, value = schedule(db,actor,now,item,flow,slots,current,data)
    elif command in ('review_requested','review_approved','review_revoked','corrected'):
        slot_id,value = review(db,actor,now,item,slots,events,current,command,data)
    elif command in ('not_admitted','admission_restored','conflict_resolved'):
        require(db,actor,item,'review')
        if command=='conflict_resolved':
            if not current['conflict']:
                brs.fail(409,'Нет расхождения для рассмотрения.')
            if not data['reference']:
                brs.fail(422,'Укажите основание решения.')
            value = {'reason':data['reason'],'reference':data['reference']}
        else:
            calculated = preview(db,item,enrollment(db,course,now))
            restoring = command=='admission_restored'
            if (item['control']!='exam' or current['used'] or calculated['admitted']!=restoring
                    or (restoring and current['admitted'] is not False)
                    or (not restoring and current['admitted'] is False)):
                brs.fail(409,'Решение не соответствует состоянию допуска.')
            value = {'snapshot':calculated,'reason':data['reason']}
    else:
        slot = slots.get(slot_id)
        if not slot:
            brs.fail(404)
        stage = current['stages'][slot_id]
        if command in ('cancelled','excused','unexcused'):
            require(db,actor,item,'schedule')
        else:
            require(db,actor,item,'examiner')
            if slot['examiner_id']!=actor['id']:
                brs.fail(404)
        if command=='cancelled':
            if now>=slot['starts_at'] or stage!='scheduled':
                brs.fail(409,'Начатое испытание нельзя отменить.')
            value = {'reason':data['reason']}
        elif command=='completed':
            if stage!='published':
                brs.fail(409,'Завершить можно опубликованную попытку.')
            value = {}
        else:
            flow = enrollment(db,course,now)
            if (stage not in ('scheduled','draft') or current['conflict'] or (current['latest'] and not current['debt'])
                    or flow['id']!=slot['enrollment_id']
                    or now<slot['starts_at'] or slot['number']!=current['used']+1):
                brs.fail(409,'Испытание ещё не началось или его состояние изменилось.')
            if command in ('excused','unexcused'):
                if now<slot['ends_at']:
                    brs.fail(409,'Дождитесь окончания испытания.')
                if (command=='unexcused' and item['control']=='exam'
                        and (current['admitted'] is False or not preview(db,item,flow)['admitted'])):
                    brs.fail(409,'Недопуск не расходует попытку.')
                value = {'outcome':'absent','reason':data['reason'],'reference':data['reference']}
            elif command=='draft':
                value = draft(db,actor,now,item,flow,slot,current,data)
            else:
                saved = next((e for e in reversed(events) if e['kind']=='draft' and e['slot_id']==slot_id),None)
                if not saved or saved['actor_id']!=actor['id'] or saved['data']['snapshot']!=preview(db,item,flow):
                    brs.fail(409,'Черновик или опубликованные баллы изменились.')
                if item['control']=='exam' and (current['admitted'] is False or not saved['data']['snapshot']['admitted']):
                    brs.fail(409,'Допуск изменился.')
                value = saved['data']
    response = append(db,actor,now,course,version+1,command,slot_id,value)
    if command=='corrected' and (value['conflict'] or value['outcome']=='pass' or (value['grade'] or 0)>=3):
        next_version = version+2
        for key, slot in slots.items():
            if current['stages'][key]=='scheduled' and now<slot['starts_at']:
                append(db,actor,now,course,next_version,'cancelled',key,{'reason':'official_correction'})
                next_version += 1
    if command in PUBLIC - {'completed'}:
        notify(db,item['student_id'],'Изменение аттестации','Откройте раздел «Аттестации».',
               'message',course,now,f'attestation:{course}:{version+1}')
    db.execute("INSERT INTO attestation_receipts VALUES (?,?,?,?,?)",
               (actor['id'],data['request_key'],fingerprint,course,version+1))
    return response


def student_view(db, slots, events, current):
    history = []
    for e in events:
        if e['kind'] not in PUBLIC:
            continue
        slot = slots.get(e['slot_id'])
        row = {'kind':e['kind'],'at':e['at'],'slot_id':e['slot_id']}
        if slot:
            row.update({k:slot[k] for k in ('number','starts_at','ends_at','room_id')})
            row['commission'] = bool(slot['commission'])
            if e['kind']=='scheduled' and slot['commission']:
                row['commission_members'] = [r['full_name'] for r in db.execute(
                    "SELECT full_name FROM staff_profiles WHERE user_id IN (SELECT value FROM json_each(?)) ORDER BY full_name",
                    (encode(slot['commission']),))]
        if e['kind'] in OUTCOMES:
            row.update({k:e['data'].get(k) for k in ('outcome','grade')})
        history.append(row)
    return {'history':history,'used':current['used'],'debt':current['debt'],
            'debt_history':current['debt_history'],'awaiting_deanery':current['conflict'] or
            (current['used']==3 and current['debt'])}


def gradebook_items(db, student, today):
    if not db.execute("SELECT 1 FROM schema_migrations WHERE id='0012_attestations'").fetchone():
        return []
    rows = db.execute("""SELECT c.id,c.curriculum_id,sub.name AS subject,i.control,i.required,
        s.id AS semester_id,s.name AS semester,s.starts_on,s.ends_on
        FROM attestation_positions p JOIN brs_student_courses c ON c.id=p.course_id
        JOIN curriculum_items i ON i.id=c.curriculum_id JOIN subjects sub ON sub.id=i.subject_id
        JOIN semesters s ON s.id=i.semester_id WHERE c.student_id=?""",(student,)).fetchall()
    items = []
    for row in rows:
        slots,events = load(db,row['id'])
        current = state(slots,events)
        upcoming = next((slot for slot in slots.values() if current['stages'][slot['id']] in ('scheduled','draft')
                         and brs.date_at(slot['starts_at'])>=today),None)
        latest = current['latest']
        if latest:
            status = 'absent' if latest['kind']=='unexcused' else ('failed' if current['debt'] else 'passed')
        elif current['admitted'] is False:
            status = 'not_admitted'
        else:
            status = 'upcoming' if upcoming else 'ungraded'
        attempts = []
        for key,event in sorted(current['official'].items(),key=lambda pair:slots[pair[0]]['number']):
            attempts.append({'number':slots[key]['number'],'outcome':event['data']['outcome'],
                             'grade':event['data'].get('grade'),'performed_on':brs.date_at(slots[key]['starts_at']),
                             'recorded_at':event['at'],'corrected':event['kind']=='corrected'})
        items.append({**dict(row),'status':status,'attempts':attempts,'assessment_id':None,
                      'event_status':'scheduled' if upcoming else ('completed' if latest else None),
                      'scheduled_on':brs.date_at(upcoming['starts_at']) if upcoming else None,'deadline_on':None,
                      'official_result':attempts[-1] if attempts else None,
                      'awaiting_deanery':current['conflict'] or (current['used']==3 and current['debt'])})
    return items
