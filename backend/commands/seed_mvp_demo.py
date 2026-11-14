"""Reproducible synthetic MVP. New database only; never reset an existing environment."""
import argparse,getpass,secrets,sys,time,uuid
from ..config import ROOT,Settings
from ..db import connection
from ..migrations.manager import update
from ..security.passwords import hash_password
from .seed_demo import seed_demo
from .seed_schedule import seed_schedule
from .seed_academics import seed_academics
from .seed_requests import seed_requests
from ..requests.service import create_in_transaction,transition_in_transaction
from ..deanery.service import sign_document
from ..events import notify,audit

ACCOUNTS=('student_a','student_b','student_c','student_d','staff_demo')

def seed(settings,credentials,as_of=None):
    if settings.database.exists() or settings.database==(ROOT/'data/deanery.sqlite3').resolve():raise ValueError('Choose a NEW separate demo database; existing files are never changed.')
    if set(credentials)!=set(ACCOUNTS):raise ValueError('Five credentials required')
    # Validate/hash before creating a database; no plaintext credential persistence.
    extra={n:hash_password(credentials[n]) for n in ('student_c','student_d')}
    settings.database.parent.mkdir(parents=True,exist_ok=True)
    update(settings.database,create=True)
    ids=seed_demo(settings,{n:credentials[n] for n in ('student_a','student_b','staff_demo')})
    seed_schedule(settings,as_of);seed_academics(settings,as_of);seed_requests(settings)
    now=int(time.time())
    with connection(settings,write=True) as db:
        db.execute("INSERT INTO rooms VALUES ('demo-spare','demo-alpha','405',30,'Доска, проектор')")
        for letter,source,name in [('c','a','Михаил Макетов — вымышленный'),('d','b','Анна Пробная — вымышленная')]:
            login='student_'+letter;key=str(uuid.uuid4());ids[login]=key
            program='demo-p' if source=='a' else 'demo-p-b'
            db.execute('INSERT INTO study_groups VALUES (?,?,?,?)',('demo-'+letter,program,'ДЕМО-'+('В' if letter=='c' else 'Г'),1 if letter=='c' else 2))
            db.execute("INSERT INTO users VALUES (?,?,?,'student',1,?)",(key,login,extra[login],now))
            db.execute('INSERT INTO student_profiles VALUES (?,?,?)',(key,name,'demo-'+letter))
            for lesson in db.execute('SELECT * FROM lessons WHERE group_id=?',('demo-'+source,)).fetchall():
                teacher='mvp-'+letter+'-'+lesson['teacher_id'];room='mvp-'+letter+'-'+lesson['room_id']
                db.execute('INSERT OR IGNORE INTO teachers VALUES (?,?)',(teacher,'Преподаватель группы '+letter.upper()+' (вымышленный)'))
                db.execute("INSERT OR IGNORE INTO rooms SELECT ?,building_id,? ,capacity,equipment FROM rooms WHERE id=?",(room,letter.upper()+'-'+lesson['room_id'],lesson['room_id']))
                db.execute('INSERT INTO lessons VALUES (?,?,?,?,?,?,?,?,?,?,1,?)',(uuid.uuid4().hex,'demo-'+letter,lesson['subject_id'],teacher,room,lesson['date'],lesson['start_minute'],lesson['end_minute'],lesson['kind'],lesson['status'],now))
            for assignment in db.execute('''SELECT a.*,s.id AS assignment FROM assessments a JOIN student_assessments s ON s.assessment_id=a.id WHERE s.student_id=?''',(ids['student_'+source],)).fetchall():
                new=uuid.uuid4().hex
                db.execute('INSERT INTO assessments VALUES (?,?,?,?,?,?)',(new,assignment['curriculum_id'],'demo-'+letter,assignment['scheduled_on'],assignment['deadline_on'],assignment['status']))
                db.execute('INSERT INTO student_assessments VALUES (?,?,?)',(new,key,new))
                for attempt in db.execute('SELECT * FROM assessment_attempts WHERE assignment_id=?',(assignment['assignment'],)).fetchall():
                    grade=3 if attempt['grade'] and attempt['grade']>=3 else attempt['grade']
                    db.execute('INSERT INTO assessment_attempts VALUES (?,?,?,?,?,?,?)',(uuid.uuid4().hex,new,attempt['number'],attempt['outcome'],grade,attempt['performed_on'],now))
        staff=dict(db.execute('SELECT * FROM users WHERE id=?',(ids['staff_demo'],)).fetchone())
        for login in ACCOUNTS[:4]:
            student=dict(db.execute('SELECT * FROM users WHERE id=?',(ids[login],)).fetchone())
            if login in ('student_c','student_d'):create_in_transaction(db,student,'appeal','','Вымышленный вопрос о консультации.',uuid.uuid4().hex,now)
            item,_=create_in_transaction(db,student,'study_certificate','Для конкурса (демо)','Прошу демонстрационную справку.',uuid.uuid4().hex,now)
            item=transition_in_transaction(db,staff,item['id'],1,'processing','В демонстрационной обработке.',now)
            item=transition_in_transaction(db,staff,item['id'],item['version'],'approved','Одобрена демонстрационная справка.',now)
            doc=sign_document(db,staff,item['id'],item['version'],now)
            db.execute('UPDATE demo_documents SET delivered_at=? WHERE id=?',(now,doc['id']))
            notify(db,student['id'],'Готова демонстрационная справка','Документ доступен в личном кабинете.','document',doc['id'],now)
            audit(db,staff,'document.deliver','document',doc['id'],None,now)
    return ids

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--db',required=True);parser.add_argument('--confirm-demo',action='store_true',required=True)
    parser.add_argument('--credentials-file',help='Windows DPAPI encrypted credentials, project-local .tmp only')
    args=parser.parse_args();settings=Settings(database=args.db)
    if settings.database.exists():raise SystemExit('Existing database preserved. Choose a new path to redeploy.')
    if args.credentials_file:
        from .demo_credentials import save
        credentials={n:secrets.token_urlsafe(24) for n in ACCOUNTS}
        save(args.credentials_file,credentials)
    else:
        if not sys.stdin.isatty():raise SystemExit('Use an interactive terminal for hidden passwords, or Windows DPAPI credentials.')
        credentials={n:getpass.getpass(n+' (15–128 символов): ') for n in ACCOUNTS}
    seed(settings,credentials)
    print('Created synthetic MVP: four students, one scoped Staff, lessons, grades, requests, documents and notifications. No passwords printed.')
if __name__=='__main__':main()
