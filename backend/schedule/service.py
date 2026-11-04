"""Moscow calendar dates and actual same-day intervals; all reads session-scoped."""
from datetime import date, datetime, timedelta, timezone
import json
import uuid
from ..auth.service import AuthError, resolve
from ..db import connection

MOSCOW = timezone(timedelta(hours=3), 'МСК')
KINDS = {'lecture','seminar','practice','lab'}
FIELDS = {'date','start_minute','end_minute','teacher_id','room_id','status'}

class ScheduleConflict(ValueError):
    pass

def calendar_date(value):
    if not isinstance(value,str) or len(value)!=10:
        raise ValueError('Expected YYYY-MM-DD')
    result=date.fromisoformat(value)
    if result.isoformat()!=value or not 1900<=result.year<=2100:raise ValueError('Invalid date')
    return result

def date_range(selected, view):
    day=calendar_date(selected)
    if view not in ('today','week'):raise ValueError('Unknown schedule view')
    start=day if view=='today' else day-timedelta(days=day.weekday())
    return [(start+timedelta(days=i)).isoformat() for i in range(1 if view=='today' else 7)]

SELECT = """SELECT l.*, s.name AS subject, t.full_name AS teacher, r.number AS room,
 b.name AS building, r.capacity, r.equipment FROM lessons l
 JOIN subjects s ON s.id=l.subject_id JOIN teachers t ON t.id=l.teacher_id
 JOIN rooms r ON r.id=l.room_id JOIN buildings b ON b.id=r.building_id """

def snapshot(db, lesson_id):
    row=db.execute(SELECT+' WHERE l.id=?',(lesson_id,)).fetchone()
    if row is None:raise ValueError('Lesson not found')
    return dict(row)

def read_schedule(service, token, *, selected=None, view='today', expected=None):
    today=datetime.fromtimestamp(service.clock(),MOSCOW).date().isoformat()
    days=date_range(selected or today,view)
    with connection(service.settings) as db:
        db.execute('BEGIN')
        user=resolve(db,token,int(service.clock()),expected)
        if user['role']!='student':raise AuthError(403,'Расписание доступно студенту своей группы.')
        group=db.execute('SELECT g.id,g.name FROM student_profiles p JOIN study_groups g ON g.id=p.group_id WHERE p.user_id=?',(user['id'],)).fetchone()
        if group is None:raise AuthError(503,'Учебная группа временно недоступна.')
        rows=db.execute(SELECT+" WHERE l.group_id=? AND (l.date BETWEEN ? AND ? OR EXISTS (SELECT 1 FROM lesson_changes c WHERE c.lesson_id=l.id AND c.before_date BETWEEN ? AND ?)) ORDER BY l.date,l.start_minute,l.id",(group['id'],days[0],days[-1],days[0],days[-1])).fetchall()
        result={day:[] for day in days}
        for row in rows:
            item=dict(row)
            changes=[]
            previous={}
            for change in db.execute('SELECT version,reason,before_json,after_json,created_at FROM lesson_changes WHERE lesson_id=? ORDER BY version',(item['id'],)):
                before=json.loads(change['before_json']);after=json.loads(change['after_json'])
                changed=[key for key in FIELDS if before[key]!=after[key]]
                changes.append({'version':change['version'],'reason':change['reason'],'fields':sorted(changed),'before':display(before),'after':display(after),'created_at':change['created_at']})
                if before['date'] in result and before['date']!=item['date']:
                    previous[before['date']]=before
            current=display(item)
            if item['date'] in result:
                result[item['date']].append({**current,'placement':'current','changes':changes})
            for day,old in previous.items():
                result[day].append({**display(old),'status':'moved','placement':'moved_from','actual':current,'changes':changes})
        for lessons in result.values():lessons.sort(key=lambda x:(x['start_minute'],x['end_minute'],x['id']))
        return {'timezone':'Europe/Moscow','today':today,'selected_date':selected or today,'view':view,
                'group':{'id':group['id'],'name':group['name']},'days':[{'date':day,'lessons':result[day]} for day in days]}

def display(item):
    return {key:item[key] for key in ('id','date','start_minute','end_minute','subject','teacher','room','building','capacity','equipment','kind','status','version')}

def validate_lesson(item):
    calendar_date(item['date'])
    if type(item['start_minute']) is not int or type(item['end_minute']) is not int or not 0<=item['start_minute']<item['end_minute']<=1440:
        raise ValueError('Invalid same-day interval')
    if item['status'] not in ('scheduled','cancelled'):raise ValueError('Invalid status')

def change_in_transaction(db, lesson_id, version, reason, changes, now):
    if type(version) is not int or version<1:raise ValueError('Expected version required')
    if not isinstance(reason,str) or not 1<=len(reason.strip())<=300:raise ValueError('Reason required')
    if not changes or not set(changes)<=FIELDS:raise ValueError('Unsupported lesson fields')
    before=snapshot(db,lesson_id)
    if before['version']!=version:raise ScheduleConflict('Lesson version changed')
    after={**before,**changes};validate_lesson(after)
    if all(before[key]==after[key] for key in FIELDS):raise ValueError('No changes')
    db.execute('UPDATE lessons SET date=?,start_minute=?,end_minute=?,teacher_id=?,room_id=?,status=?,version=version+1,updated_at=? WHERE id=? AND version=?',
               (*(after[key] for key in ('date','start_minute','end_minute','teacher_id','room_id','status')),now,lesson_id,version))
    after=snapshot(db,lesson_id)
    db.execute('INSERT INTO lesson_changes VALUES (?,?,?,?,?,?,?,?)',
               (str(uuid.uuid4()),lesson_id,after['version'],before['date'],reason.strip(),json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False),now))
    return display(after)

def change_lesson(settings, lesson_id, version, reason, changes, now):
    # Trusted local operator only; never an HTTP authorization shortcut.
    with connection(settings,write=True,timeout=.25) as db:
        return change_in_transaction(db,lesson_id,version,reason,changes,now)
