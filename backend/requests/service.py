"""Atomic transitions; roles, ownership and authors come from live server sessions."""
import hashlib
import json
import re
import uuid
from ..auth.service import AuthError,resolve,verify_csrf
from ..db import connection
from ..events import notify,audit

TYPES={'study_certificate','general_certificate','appeal'}
TRANSITIONS={'submitted':{'processing'},'processing':{'approved','rejected'}}
PAGE_SIZE=20


def text(value,maximum,*,empty=False):
    if not isinstance(value,str) or len(value)>maximum or any(ord(c)<32 and c not in '\n\t' for c in value):
        raise AuthError(422,'Проверьте формат и длину полей.')
    value=value.strip()
    if not value and not empty:raise AuthError(422,'Заполните обязательные поля.')
    return value


def validate_content(kind,purpose,message,key):
    if kind not in TYPES or not isinstance(key,str) or re.fullmatch('[a-f0-9]{32}',key) is None:
        raise AuthError(422,'Проверьте тип обращения и ключ отправки.')
    purpose=text(purpose,200,empty=kind=='appeal');message=text(message,2000)
    if kind=='appeal' and purpose:raise AuthError(422,'У свободного обращения нет назначения справки.')
    return kind,purpose,message


def identity(db,service,token,role,expected,header=None,cookie=None,mutation=False):
    user=resolve(db,token,int(service.clock()),expected)
    if user['role']!=role:raise AuthError(403,'Действие недоступно для этой роли.')
    if mutation:verify_csrf(user,header,cookie)
    return user


def preflight(service,token,role,expected,header,cookie):
    with connection(service.settings) as db:identity(db,service,token,role,expected,header,cookie,True)


def authorized_request(db,user,request_id,role):
    if role=='student':
        row=db.execute('SELECT * FROM student_requests WHERE id=? AND student_id=?',(request_id,user['id'])).fetchone()
    else:
        row=db.execute('''SELECT r.* FROM student_requests r WHERE r.id=? AND EXISTS
            (SELECT 1 FROM request_staff_scopes s WHERE s.staff_id=? AND s.faculty_id=r.faculty_id)''',(request_id,user['id'])).fetchone()
    if row is None:raise AuthError(404,'Обращение не найдено.')
    return row


def public_request(row):
    return {key:row[key] for key in ('id','type','purpose','message','status','version','created_at','updated_at')}


def details(db,row,role):
    result=public_request(row)
    result['history']=[dict(r) for r in db.execute('''SELECT h.version,h.from_status,h.to_status,
        h.actor_role,h.comment,h.created_at,
        CASE WHEN h.actor_role='staff' THEN sp.full_name ELSE p.full_name END AS actor_name
        FROM request_history h LEFT JOIN staff_profiles sp ON sp.user_id=h.actor_id
        LEFT JOIN student_profiles p ON p.user_id=h.actor_id WHERE h.request_id=? ORDER BY h.version''',(row['id'],))]
    result['actions']=(['cancel'] if row['status']=='submitted' else []) if role=='student' else sorted(TRANSITIONS.get(row['status'],set()))
    if role=='staff':
        owner=db.execute('SELECT p.full_name,g.name AS study_group FROM student_profiles p JOIN study_groups g ON g.id=p.group_id WHERE p.user_id=?',(row['student_id'],)).fetchone()
        result['student']=dict(owner)
        document=db.execute('SELECT id,signed_at,delivered_at FROM demo_documents WHERE request_id=?',(row['id'],)).fetchone()
        result['document']=dict(document) if document else None
    return result


def read_requests(service,token,role,*,expected=None,request_id=None,offset=0):
    with connection(service.settings) as db:
        db.execute('BEGIN');user=identity(db,service,token,role,expected)
        if request_id:return details(db,authorized_request(db,user,request_id,role),role)
        if type(offset) is not int or not 0<=offset<=1000000:raise AuthError(422,'Недопустимая страница.')
        if role=='student':
            rows=db.execute('SELECT * FROM student_requests WHERE student_id=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',(user['id'],PAGE_SIZE+1,offset)).fetchall()
        else:
            rows=db.execute('''SELECT r.* FROM student_requests r WHERE EXISTS
                (SELECT 1 FROM request_staff_scopes s WHERE s.staff_id=? AND s.faculty_id=r.faculty_id)
                ORDER BY r.created_at DESC,r.id DESC LIMIT ? OFFSET ?''',(user['id'],PAGE_SIZE+1,offset)).fetchall()
        return {'items':[public_request(r) for r in rows[:PAGE_SIZE]],'offset':offset,'next_offset':offset+PAGE_SIZE if len(rows)>PAGE_SIZE else None}


def history(db,row,user,before,comment,now):
    db.execute('INSERT INTO request_history VALUES (?,?,?,?,?,?,?,?,?)',
        (str(uuid.uuid4()),row['id'],row['version'],before,row['status'],user['id'],user['role'],comment,now))


def create_in_transaction(db,user,kind,purpose,message,key,now):
    kind,purpose,message=validate_content(kind,purpose,message,key)
    fingerprint=hashlib.sha256(json.dumps([kind,purpose,message],ensure_ascii=False).encode('utf-8')).hexdigest()
    old=db.execute('SELECT * FROM student_requests WHERE student_id=? AND request_key=?',(user['id'],key)).fetchone()
    if old:
        if old['payload_hash']!=fingerprint:raise AuthError(409,'Ключ отправки уже использован для другого обращения.')
        return details(db,old,'student'),False
    # Count every created request, including cancelled ones. Retries above do not consume quota.
    counts=db.execute('''SELECT count(*) AS daily,coalesce(sum(created_at>?),0) AS recent
        FROM student_requests WHERE student_id=? AND created_at>?''',(now-600,user['id'],now-86400)).fetchone()
    if counts['recent']>=5 or counts['daily']>=20:raise AuthError(429,'Лимит обращений исчерпан. Повторите позже.')
    faculty=db.execute('''SELECT pr.faculty_id FROM student_profiles p JOIN study_groups g ON g.id=p.group_id
        JOIN programs pr ON pr.id=g.program_id WHERE p.user_id=?''',(user['id'],)).fetchone()
    if faculty is None:raise AuthError(503,'Учебный профиль временно недоступен.')
    key_id=uuid.uuid4().hex
    db.execute('INSERT INTO student_requests VALUES (?,?,?,?,?,?,?,1,?,?,?,?)',
        (key_id,user['id'],faculty['faculty_id'],kind,purpose,message,'submitted',now,now,key,fingerprint))
    row=authorized_request(db,user,key_id,'student');history(db,row,user,None,'Обращение отправлено студентом.',now)
    notify(db,user['id'],'Обращение отправлено','Статус и ответ появятся в разделе обращений.','request',key_id,now)
    return details(db,row,'student'),True


def create_request(service,token,kind,purpose,message,key,*,expected=None,header=None,cookie=None):
    validate_content(kind,purpose,message,key)
    preflight(service,token,'student',expected,header,cookie)
    with connection(service.settings,write=True,timeout=.25) as db:
        user=identity(db,service,token,'student',expected,header,cookie,True)
        return create_in_transaction(db,user,kind,purpose,message,key,int(service.clock()))


def transition_in_transaction(db,user,request_id,version,action,comment,now):
    role=user['role'];row=authorized_request(db,user,request_id,role)
    if type(version) is not int or version<1:raise AuthError(422,'Укажите версию обращения.')
    if version!=row['version']:raise AuthError(409,'Обращение уже изменилось. Обновите детали.')
    comment=text(comment,1000)
    target='cancelled' if action=='cancel' else action
    allowed=(action=='cancel' and row['status']=='submitted') if role=='student' else action in TRANSITIONS.get(row['status'],set())
    if not allowed:raise AuthError(409,'Этот переход статуса недоступен.')
    now=max(now,row['updated_at'])
    db.execute('UPDATE student_requests SET status=?,version=version+1,updated_at=? WHERE id=? AND version=?',
        (target,now,request_id,version))
    updated=authorized_request(db,user,request_id,role);history(db,updated,user,row['status'],comment,now)
    if role=='staff':
        notify(db,row['student_id'],'Статус обращения изменён',comment,'request',request_id,now)
        audit(db,user,'request.'+target,'request',request_id,updated['version'],now)
    return details(db,updated,role)


def transition_request(service,token,role,request_id,version,action,comment,*,expected=None,header=None,cookie=None):
    preflight(service,token,role,expected,header,cookie)
    with connection(service.settings,write=True,timeout=.25) as db:
        user=identity(db,service,token,role,expected,header,cookie,True)
        return transition_in_transaction(db,user,request_id,version,action,comment,int(service.clock()))
