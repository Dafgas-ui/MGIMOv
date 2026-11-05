"""Fictional requests and one explicit demo faculty scope; never startup or working DB."""
import argparse
import sqlite3
import time
import uuid
from ..auth.service import AuthError
from ..config import ROOT,Settings
from ..db import connection
from ..requests.service import create_in_transaction,transition_in_transaction


def seed_requests(settings,now=None):
    if settings.database==(ROOT/'data/deanery.sqlite3').resolve():raise ValueError('Working database forbidden')
    now=int(time.time()) if now is None else now
    with connection(settings,write=True) as db:
        users={r['login']:dict(r) for r in db.execute("SELECT id,login,role FROM users WHERE login IN ('student_a','student_b','staff_demo')")}
        if set(users)!={'student_a','student_b','staff_demo'}:raise ValueError('Three demo users required')
        if users['staff_demo']['role']!='staff' or any(users[n]['role']!='student' for n in ('student_a','student_b')):raise ValueError('Unexpected demo roles')
        if db.execute('SELECT 1 FROM student_requests LIMIT 1').fetchone() or db.execute('SELECT 1 FROM request_staff_scopes LIMIT 1').fetchone():raise ValueError('Existing requests/scopes are not overwritten')
        faculties={r[0] for r in db.execute("SELECT pr.faculty_id FROM student_profiles p JOIN study_groups g ON g.id=p.group_id JOIN programs pr ON pr.id=g.program_id WHERE p.user_id IN (?,?)",(users['student_a']['id'],users['student_b']['id']))}
        if faculties!={'demo-f'}:raise ValueError('Expected synthetic demo faculty')
        db.execute('INSERT INTO request_staff_scopes VALUES (?,?)',(users['staff_demo']['id'],'demo-f'))
        for name,kind,purpose,message,final in [
            ('student_a','study_certificate','Для демонстрации учёбы','Вымышленная справка для тестирования.','processing'),
            ('student_a','appeal','','Демонстрационный вопрос о порядке консультаций.','approved'),
            ('student_b','general_certificate','По месту требования (демо)','Проверка причины отказа на вымышленных данных.','rejected'),
            ('student_b','appeal','','Новый демонстрационный вопрос в деканат.',None)]:
            item,_=create_in_transaction(db,users[name],kind,purpose,message,uuid.uuid4().hex,now)
            if final:
                item=transition_in_transaction(db,users['staff_demo'],item['id'],1,'processing','Взято в демонстрационную обработку.',now)
                if final!='processing':transition_in_transaction(db,users['staff_demo'],item['id'],2,final,
                    'Демонстрационное обращение одобрено. Официальный документ не выпускается.' if final=='approved' else 'Демонстрационный отказ: выбран неподходящий вид справки.',now)


def main():
    p=argparse.ArgumentParser(description='Seed fictional requests and demo staff scope in a separate DB')
    p.add_argument('--db',required=True);p.add_argument('--confirm-demo',required=True,action='store_true');args=p.parse_args()
    try:
        seed_requests(Settings(database=args.db));print('Synthetic requests and demo scope created.');return 0
    except (AuthError,ValueError,OSError,sqlite3.Error):
        print('Request seed rejected; check migration, synthetic users and empty request tables.');return 1

if __name__=='__main__':raise SystemExit(main())
