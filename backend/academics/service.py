"""Deterministic academic rules and session-scoped reads."""
from datetime import datetime
import time
import uuid
from ..auth.service import AuthError, resolve
from ..config import ROOT
from ..db import connection
from ..schedule.service import MOSCOW, calendar_date


def successful(attempt):
    return bool(attempt and (attempt['outcome']=='pass' or
                (attempt['outcome']=='graded' and attempt['grade']>=3)))


def academic_status(item, attempts, today):
    # Local commands disallow an attempt after success; latest number is authoritative.
    if item['event_status']=='cancelled':return 'cancelled'
    latest=attempts[-1] if attempts else None
    if latest:
        if successful(latest):return 'passed'
        return 'absent' if latest['outcome']=='absent' else 'failed'
    if item['event_status']=='not_held':return 'not_held'
    if item['event_status']=='completed' and item['deadline_on'] and item['deadline_on']<today:
        return 'overdue'
    if item['event_status']=='scheduled' and item['scheduled_on'] and item['scheduled_on']>=today:
        return 'upcoming'
    return 'ungraded' if item['event_status']=='completed' else 'unscheduled'


def summarize(items):
    required=[x for x in items if x['required'] and x['status']!='cancelled']
    count=lambda status:sum(x['status'] in status for x in required)
    completed=count({'passed'})
    return {'state':'ready' if required else 'no_data','total':len(required),
            'completed':completed,'upcoming':count({'upcoming'}),
            'debts':count({'failed','absent','overdue'}),
            'pending':count({'not_held','ungraded','unscheduled'}),
            'percent':round(completed*100/len(required)) if required else None}


def read_academics(service, token, expected=None):
    today=datetime.fromtimestamp(service.clock(),MOSCOW).date().isoformat()
    with connection(service.settings) as db:
        db.execute('BEGIN')
        user=resolve(db,token,int(service.clock()),expected)
        if user['role']!='student':raise AuthError(403,'Успеваемость доступна только студенту.')
        # Ownership is fixed by session even if group/program changes later.
        rows=db.execute('''SELECT sa.id, a.id AS assessment_id, s.id AS semester_id,
            s.name AS semester, s.starts_on, s.ends_on, sub.name AS subject,
            c.control,c.required,a.scheduled_on,a.deadline_on,a.status AS event_status
            FROM student_assessments sa JOIN assessments a ON a.id=sa.assessment_id
            JOIN curriculum_items c ON c.id=a.curriculum_id
            JOIN subjects sub ON sub.id=c.subject_id JOIN semesters s ON s.id=c.semester_id
            WHERE sa.student_id=? ORDER BY s.starts_on,sub.name,sa.id''',(user['id'],)).fetchall()
        # Owner predicate repeated in attempts query: no arbitrary assignment lookup from HTTP.
        attempts={}
        for row in db.execute('''SELECT t.assignment_id,t.number,t.outcome,t.grade,t.performed_on,t.recorded_at
            FROM assessment_attempts t JOIN student_assessments sa ON sa.id=t.assignment_id
            WHERE sa.student_id=? ORDER BY t.assignment_id,t.number''',(user['id'],)):
            item=dict(row);attempts.setdefault(item.pop('assignment_id'),[]).append(item)
        semesters={}
        for row in rows:
            item=dict(row);key=item.pop('semester_id');name=item.pop('semester')
            start=item.pop('starts_on');end=item.pop('ends_on')
            semester=semesters.setdefault(key,{'id':key,'name':name,'starts_on':start,'ends_on':end,'items':[]})
            item['required']=bool(item['required']);item['attempts']=attempts.get(item['id'],[])
            item['status']=academic_status(item,item['attempts'],today)
            semester['items'].append(item)
        current=[s for s in semesters.values() if s['starts_on']<=today<=s['ends_on']]
        if len(current)>1:raise AuthError(503,'Учебный период временно недоступен.')
        session=current[0] if current else None
        current_items=session['items'] if session else []
        all_items=[i for s in semesters.values() for i in s['items']]
        return {'today':today,'timezone':'Europe/Moscow','semesters':list(semesters.values()),
                'current_semester':{k:session[k] for k in ('id','name')} if session else None,
                'progress':summarize(current_items),
                'exams':sorted(all_items,key=lambda i:(i['scheduled_on'] or '9999',i['id'])),
                'upcoming':sorted([i for i in all_items if i['status']=='upcoming'],key=lambda i:(i['scheduled_on'],i['id'])),
                'debts':[i for i in all_items if i['required'] and i['status'] in ('failed','absent','overdue')]}


def record_in_transaction(db,assignment_id,expected_attempts,outcome,grade,performed_on,now):
    if type(expected_attempts) is not int or expected_attempts<0:raise ValueError('Expected attempt count required')
    day=calendar_date(performed_on).isoformat()
    if type(now) is not int or now<=0 or day>datetime.fromtimestamp(now,MOSCOW).date().isoformat():raise ValueError('Future attempt')
    item=db.execute('''SELECT c.control,a.status,a.scheduled_on FROM student_assessments sa
        JOIN assessments a ON a.id=sa.assessment_id JOIN curriculum_items c ON c.id=a.curriculum_id
        WHERE sa.id=?''',(assignment_id,)).fetchone()
    if item is None or item['status']!='completed':raise ValueError('Completed assessment required')
    if item['scheduled_on'] and day<item['scheduled_on']:raise ValueError('Attempt before assessment')
    previous=[dict(r) for r in db.execute('SELECT * FROM assessment_attempts WHERE assignment_id=? ORDER BY number',(assignment_id,))]
    if len(previous)!=expected_attempts:raise ValueError('Attempt history changed')
    if previous and (successful(previous[-1]) or day<previous[-1]['performed_on'] or now<previous[-1]['recorded_at']):raise ValueError('Cannot replace success or reorder attempts')
    if item['control']=='credit':
        if outcome not in ('pass','fail','absent') or grade is not None:raise ValueError('Invalid credit result')
    elif not ((outcome=='graded' and type(grade) is int and 2<=grade<=5) or (outcome=='absent' and grade is None)):
        raise ValueError('Grade 2..5 or absence required')
    db.execute('INSERT INTO assessment_attempts VALUES (?,?,?,?,?,?,?)',
        (str(uuid.uuid4()),assignment_id,expected_attempts+1,outcome,grade,day,now))
    return expected_attempts+1


def record_result(settings,assignment_id,expected_attempts,outcome,grade,performed_on,now=None):
    # MVP write tool is for a separate demo database only, not a future staff permission.
    if settings.database==(ROOT/'data/deanery.sqlite3').resolve():raise ValueError('Working database forbidden')
    with connection(settings,write=True,timeout=.25) as db:
        return record_in_transaction(db,assignment_id,expected_attempts,outcome,grade,performed_on,int(time.time()) if now is None else now)
