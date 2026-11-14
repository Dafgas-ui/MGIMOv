import hashlib
import uuid
import base64
import json
import re
from ..academics.attestation import check_lesson_conflict
from ..auth.service import AuthError,resolve,verify_csrf
from ..db import connection
from ..events import notify,notify_group,audit
from ..schedule.service import SELECT,snapshot,display,validate_lesson,change_in_transaction,ScheduleConflict,KINDS
from ..requests.service import authorized_request,details,history,text

def actor(db,service,token,expected=None,role=None,header=None,cookie=None,write=False):
    user=resolve(db,token,int(service.clock()),expected)
    if role and user['role']!=role:raise AuthError(403,'Недостаточно прав.')
    if write:verify_csrf(user,header,cookie)
    return user

def group_scope(db,user,group_id):
    row=db.execute('''SELECT g.id FROM study_groups g JOIN programs p ON p.id=g.program_id
      JOIN request_staff_scopes s ON s.faculty_id=p.faculty_id WHERE g.id=? AND s.staff_id=?''',(group_id,user['id'])).fetchone()
    if not row:raise AuthError(404,'Объект недоступен.')

def notification_cursor(row):
    return base64.urlsafe_b64encode(json.dumps([row['created_at'],row['id']],separators=(',',':')).encode()).decode().rstrip('=')

def notification_boundary(cursor):
    if cursor is None:return None
    try:
        if not isinstance(cursor,str) or not 1<=len(cursor)<=300 or re.fullmatch('[A-Za-z0-9_-]+',cursor) is None:raise ValueError
        value=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)))
        if not isinstance(value,list) or len(value)!=2 or type(value[0]) is not int or not 0<=value[0]<=2**63-1:raise ValueError
        if not isinstance(value[1],str) or re.fullmatch('[A-Za-z0-9_-]{1,100}',value[1]) is None:raise ValueError
        return value
    except (ValueError,TypeError,UnicodeError):raise AuthError(422,'Недопустимая страница уведомлений.') from None

def read(service,token,resource,expected=None,key=None,cursor=None):
    with connection(service.settings) as db:
        db.execute('BEGIN');user=actor(db,service,token,expected)
        if resource=='notifications':
            boundary=notification_boundary(cursor)
            sql='SELECT id,title,body,kind,resource_id,created_at,read_at FROM notifications WHERE user_id=?'
            args=[user['id']]
            if boundary:
                sql+=' AND (created_at,id)<(?,?)';args.extend(boundary)
            rows=[dict(r) for r in db.execute(sql+' ORDER BY created_at DESC,id DESC LIMIT 101',args)]
            return {'items':rows[:100],'next_cursor':notification_cursor(rows[99]) if len(rows)>100 else None,
                    'unread':db.execute('SELECT count(*) FROM notifications WHERE user_id=? AND read_at IS NULL',(user['id'],)).fetchone()[0]}
        if resource in ('documents','staff_documents'):
            if resource=='staff_documents' and user['role']!='staff':raise AuthError(403,'Доступно сотруднику.')
            if user['role']=='student':rows=db.execute('SELECT id,request_id,signed_at,delivered_at,content_hash FROM demo_documents WHERE student_id=? AND delivered_at IS NOT NULL ORDER BY signed_at DESC',(user['id'],)).fetchall()
            else:rows=db.execute('''SELECT d.id,d.request_id,d.signed_at,d.delivered_at,d.content_hash FROM demo_documents d WHERE EXISTS
              (SELECT 1 FROM request_staff_scopes s WHERE s.staff_id=? AND s.faculty_id=d.faculty_id) ORDER BY signed_at DESC''',(user['id'],)).fetchall()
            return {'items':[dict(r) for r in rows]}
        if resource=='document':
            row=document_scope(db,user,key)
            return {k:row[k] for k in ('id','content','content_hash','signed_at','delivered_at')}
        if user['role']!='staff':raise AuthError(403,'Доступно сотруднику.')
        if resource=='students':
            return {'items':[dict(r) for r in db.execute('''SELECT p.user_id AS id,p.full_name,g.name AS study_group,g.id AS group_id FROM student_profiles p
              JOIN study_groups g ON g.id=p.group_id JOIN programs pr ON pr.id=g.program_id
              WHERE EXISTS(SELECT 1 FROM request_staff_scopes s WHERE s.staff_id=? AND s.faculty_id=pr.faculty_id) ORDER BY g.name,p.full_name LIMIT 200''',(user['id'],))]}
        if resource=='catalogue':
            groups=[dict(r) for r in db.execute('''SELECT g.id,g.name FROM study_groups g JOIN programs p ON p.id=g.program_id WHERE EXISTS
              (SELECT 1 FROM request_staff_scopes s WHERE s.staff_id=? AND s.faculty_id=p.faculty_id) ORDER BY g.name''',(user['id'],))]
            return {'groups':groups,'subjects':[dict(r) for r in db.execute('SELECT * FROM subjects ORDER BY name')],
              'teachers':[dict(r) for r in db.execute('SELECT * FROM teachers ORDER BY full_name')],
              'rooms':[dict(r) for r in db.execute('SELECT r.id,r.number,b.name AS building FROM rooms r JOIN buildings b ON b.id=r.building_id ORDER BY b.name,r.number')]}
        if resource=='lessons':
            return {'items':[{**display(dict(r)),'group_id':r['group_id'],'subject_id':r['subject_id'],'teacher_id':r['teacher_id'],'room_id':r['room_id']} for r in db.execute(SELECT+''' WHERE EXISTS
              (SELECT 1 FROM study_groups g JOIN programs p ON p.id=g.program_id JOIN request_staff_scopes s ON s.faculty_id=p.faculty_id
               WHERE g.id=l.group_id AND s.staff_id=?) ORDER BY l.date DESC,l.start_minute LIMIT 200''',(user['id'],))]}
        raise AuthError(404,'Не найдено.')

def document_scope(db,user,key):
    if user['role']=='student':row=db.execute('SELECT * FROM demo_documents WHERE id=? AND student_id=? AND delivered_at IS NOT NULL',(key,user['id'])).fetchone()
    else:row=db.execute('''SELECT d.* FROM demo_documents d WHERE d.id=? AND EXISTS
      (SELECT 1 FROM request_staff_scopes s WHERE s.staff_id=? AND s.faculty_id=d.faculty_id)''',(key,user['id'])).fetchone()
    if not row:raise AuthError(404,'Документ не найден.')
    return row

def slot_available(db,item,key=''):
    if item['status']=='cancelled':return
    check_lesson_conflict(db,item)
    row=db.execute('''SELECT id FROM lessons WHERE id<>? AND date=? AND status='scheduled' AND start_minute<? AND end_minute>?
      AND (group_id=? OR room_id=? OR teacher_id=?) LIMIT 1''',(key,item['date'],item['end_minute'],item['start_minute'],item['group_id'],item['room_id'],item['teacher_id'])).fetchone()
    if row:raise AuthError(409,'Время группы, преподавателя или аудитории уже занято.')

def edit_lesson(db,user,data,now,key=None):
    if key:
        row=db.execute('SELECT * FROM lessons WHERE id=?',(key,)).fetchone()
        if not row:raise AuthError(404,'Объект недоступен.')
        group_scope(db,user,row['group_id'])
    else:group_scope(db,user,data['group_id'])
    for field,table in (('teacher_id','teachers'),('room_id','rooms'),('subject_id','subjects')):
        if field in data and not db.execute(f'SELECT 1 FROM {table} WHERE id=?',(data[field],)).fetchone():raise AuthError(422,'Неизвестный элемент справочника.')
    data['reason']=text(data['reason'],300)
    if key:
        if row['version']!=data['version']:raise AuthError(409,'Занятие уже изменено.')
        changes={k:data[k] for k in ('date','start_minute','end_minute','teacher_id','room_id','status')}
        after={**dict(row),**changes};validate_lesson(after);slot_available(db,after,key)
        try:result=change_in_transaction(db,key,data['version'],data['reason'],changes,now)
        except ScheduleConflict:raise AuthError(409,'Занятие уже изменено.') from None
    else:
        validate_lesson(data);slot_available(db,data)
        if data['kind'] not in KINDS:raise AuthError(422,'Некорректный тип занятия.')
        key=uuid.uuid4().hex
        db.execute('INSERT INTO lessons VALUES (?,?,?,?,?,?,?,?,?,?,1,?)',(key,*(data[k] for k in ('group_id','subject_id','teacher_id','room_id','date','start_minute','end_minute','kind','status')),now))
        result=display(snapshot(db,key))
    audit(db,user,'lesson.update' if data.get('version') else 'lesson.create','lesson',key,result['version'],now)
    group_id=db.execute('SELECT group_id FROM lessons WHERE id=?',(key,)).fetchone()[0]
    notify_group(db,group_id,'Изменение расписания',f"{result['subject']}: {result['date']}, {result['start_minute']//60:02}:{result['start_minute']%60:02}. {data['reason']}",key,now)
    return result

def sign_document(db,user,request_id,version,now):
    request=authorized_request(db,user,request_id,'staff')
    if request['version']!=version:raise AuthError(409,'Заявка уже изменена.')
    if request['status']!='approved' or request['type']=='appeal':raise AuthError(409,'Нужна одобренная заявка на справку.')
    if db.execute('SELECT 1 FROM demo_documents WHERE request_id=?',(request_id,)).fetchone():raise AuthError(409,'Справка уже подписана.')
    student=db.execute('SELECT full_name FROM student_profiles WHERE user_id=?',(request['student_id'],)).fetchone()[0]
    signer=db.execute('SELECT full_name FROM staff_profiles WHERE user_id=?',(user['id'],)).fetchone()[0]
    key=uuid.uuid4().hex
    content=f'ДЕМОНСТРАЦИОННАЯ СПРАВКА MGIMOv\nНЕОФИЦИАЛЬНО. НЕ ПОДТВЕРЖДАЕТ РЕАЛЬНОЕ ОБУЧЕНИЕ.\nНомер: {key}\nСтудент: {student}\nНазначение: {request["purpose"]}\nВымышленные сведения об обучении.\nДемонстрационно подписал: {signer}\nUTC timestamp: {now}\nНЕ ЯВЛЯЕТСЯ ЮРИДИЧЕСКИ ЗНАЧИМОЙ ЭЛЕКТРОННОЙ ПОДПИСЬЮ.\n'
    db.execute('INSERT INTO demo_documents VALUES (?,?,?,?,?,?,?,?,NULL)',(key,request['student_id'],request_id,request['faculty_id'],user['id'],content,hashlib.sha256(content.encode()).hexdigest(),now))
    audit(db,user,'document.sign','document',key,version,now)
    return {'id':key,'request_id':request_id,'signed_at':now,'delivered_at':None}

def mutate(service,token,operation,data,expected=None,header=None,cookie=None,key=None):
    role=None if operation=='read_notification' else 'staff'
    with connection(service.settings) as db:actor(db,service,token,expected,role,header,cookie,True)
    with connection(service.settings,write=True,timeout=.25) as db:
        user=actor(db,service,token,expected,role,header,cookie,True);now=int(service.clock())
        if operation=='read_notification':
            row=db.execute('SELECT id FROM notifications WHERE id=? AND user_id=?',(key,user['id'])).fetchone()
            if not row:raise AuthError(404,'Уведомление не найдено.')
            db.execute('UPDATE notifications SET read_at=coalesce(read_at,?) WHERE id=? AND user_id=?',(now,key,user['id']))
            return {'id':key,'read':True}
        if operation=='lesson':return edit_lesson(db,user,data,now,key)
        if operation=='sign':return sign_document(db,user,key,data['version'],now)
        if operation=='deliver':
            row=document_scope(db,user,key)
            if row['delivered_at'] is None:
                db.execute('UPDATE demo_documents SET delivered_at=? WHERE id=?',(max(now,row['signed_at']),key))
                notify(db,row['student_id'],'Готова демонстрационная справка','Документ доступен в разделе «Документы». Это не официальная справка.','document',key,now)
                audit(db,user,'document.deliver','document',key,None,now)
            return {'id':key,'delivered':True}
        if operation=='reply':
            row=authorized_request(db,user,key,'staff')
            if row['version']!=data['version'] or row['status'] not in ('submitted','processing'):raise AuthError(409,'Заявка уже изменена или завершена.')
            comment=text(data['comment'],1000)
            db.execute('UPDATE student_requests SET version=version+1,updated_at=? WHERE id=?',(max(now,row['updated_at']),key))
            updated=authorized_request(db,user,key,'staff');history(db,updated,user,row['status'],comment,now)
            notify(db,row['student_id'],'Ответ деканата',comment,'request',key,now);audit(db,user,'request.reply','request',key,updated['version'],now)
            return details(db,updated,'staff')
        if operation=='notify':
            target=db.execute('SELECT group_id FROM student_profiles WHERE user_id=?',(data['student_id'],)).fetchone()
            if not target:raise AuthError(404,'Объект недоступен.')
            group_scope(db,user,target['group_id'])
            title=text(data['title'],160);body=text(data['body'],1000)
            notify(db,data['student_id'],title,body,'message',None,now);audit(db,user,'notification.send','student',data['student_id'],None,now)
            return {'sent':True}
        raise AuthError(404,'Не найдено.')
