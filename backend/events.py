"""Transactional in-app events; no mail or external services."""
import uuid

def notify(db,user_id,title,body,kind,resource_id,now,event_key=None):
    db.execute('INSERT INTO notifications VALUES (?,?,?,?,?,?,?,NULL,?) ON CONFLICT(user_id,event_key) DO NOTHING',
        (uuid.uuid4().hex,user_id,title,body,kind,resource_id,now,event_key or uuid.uuid4().hex))

def audit(db,actor,action,kind,resource_id,version,now):
    db.execute('INSERT INTO staff_audit VALUES (?,?,?,?,?,?,?)',(uuid.uuid4().hex,actor['id'],action,kind,resource_id,version,now))

def notify_group(db,group_id,title,body,lesson_id,now):
    for row in db.execute('SELECT user_id FROM student_profiles WHERE group_id=?',(group_id,)):
        notify(db,row['user_id'],title,body,'lesson',lesson_id,now)
