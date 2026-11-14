"""One-use, group-bound invitations. Registration never accepts a role."""
import uuid
from .service import AuthError,digest,valid_token
from ..db import connection
from ..security.passwords import hash_password,valid_password
from ..requests.service import text
from ..events import notify

def register(service,login,password,full_name,invitation,peer):
    login=login.lower();full_name=text(full_name,120)
    if not valid_token(invitation) or not valid_password(password):raise AuthError(422,'Проверьте приглашение и пароль (15–128 символов).')
    def invitation_row(db):
        row=db.execute('SELECT * FROM registration_invitations WHERE token_hash=? AND consumed_by IS NULL AND expires_at>?',(digest(invitation),int(service.clock()))).fetchone()
        if not row:raise AuthError(422,'Приглашение недействительно или уже использовано.')
        return row
    with service.limits.verification('registration'):
        service.limits.reserve('registration',peer,int(service.clock()))
        with connection(service.settings) as db:invitation_row(db)
        encoded=hash_password(password)
        with connection(service.settings,write=True,timeout=.25) as db:
            row=invitation_row(db)
            if db.execute('SELECT 1 FROM users WHERE login=?',(login,)).fetchone():raise AuthError(409,'Выберите другой логин.')
            key=str(uuid.uuid4());now=int(service.clock())
            db.execute("INSERT INTO users VALUES (?,?,?,'student',1,?)",(key,login,encoded,now))
            db.execute('INSERT INTO student_profiles VALUES (?,?,?)',(key,full_name,row['group_id']))
            db.execute('UPDATE registration_invitations SET consumed_by=? WHERE token_hash=?',(key,digest(invitation)))
            notify(db,key,'Добро пожаловать','Это демонстрационный цифровой деканат. Учебные данные добавляет сотрудник.','message',None,now)
    return {'registered':True}
