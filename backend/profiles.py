"""Own profile only: identity, role and query are in one read snapshot."""
from .auth.service import AuthError, public_user, resolve
from .db import connection

def own_profile(service, token, expected=None):
    with connection(service.settings) as db:
        db.execute('BEGIN')
        user=resolve(db,token,int(service.clock()),expected)
        if user['role']=='student':
            row=db.execute("SELECT s.full_name, f.name AS faculty, p.name AS program, g.course, g.name AS study_group FROM student_profiles s JOIN study_groups g ON g.id=s.group_id JOIN programs p ON p.id=g.program_id JOIN faculties f ON f.id=p.faculty_id WHERE s.user_id=?",(user['id'],)).fetchone()
        elif user['role']=='staff':
            row=db.execute('SELECT full_name,position FROM staff_profiles WHERE user_id=?',(user['id'],)).fetchone()
        else:
            raise AuthError(403,'Операция не разрешена.')
        if row is None: raise AuthError(503,'Профиль временно недоступен.')
        return {'user':public_user(user),'profile':dict(row)}
