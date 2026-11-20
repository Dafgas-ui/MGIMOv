"""Create a new, isolated Phase 3 SQLite with twenty synthetic accounts."""
import argparse
import getpass
import secrets
import sys
from datetime import datetime, time, timedelta
from uuid import uuid4

from ..academics import attestation as academic
from ..academics.service import record_in_transaction
from ..brs import service as brs
from ..config import ROOT, Settings
from ..db import connection
from ..migrations.manager import update
from ..schedule.service import MOSCOW
from ..security.passwords import hash_password

STUDENTS = tuple(f's{i:02d}' for i in range(1,12))
TEACHERS = tuple(f't{i:02d}' for i in range(1,6))
DEANERY = ('d01','d02','d03')
ACCOUNTS = STUDENTS+TEACHERS+DEANERY+('a01',)
SUBJECTS = (('law','Демонстрационное право','exam'),
            ('methods','Методы исследования','exam'),
            ('seminar','Академическое письмо','credit'),
            ('language','Деловой английский','graded_credit'))


def seed(settings, credentials, today=None, *, score_overrides=None, no_exam_students=()):
    path = settings.database
    if path.exists() or not path.is_relative_to((ROOT/'.tmp').resolve()) or path.suffix!='.sqlite3':
        raise ValueError('Choose a new .tmp/*.sqlite3 database.')
    if set(credentials)!=set(ACCOUNTS):
        raise ValueError('Expected exactly twenty demo credentials.')
    hashes = {key:hash_password(credentials[key]) for key in ACCOUNTS}
    score_overrides = score_overrides or {}
    no_exam_students = set(no_exam_students)
    if not no_exam_students <= set(STUDENTS):
        raise ValueError('Unknown student in no-exam scenario.')
    for (student, subject), scores in score_overrides.items():
        if (student not in STUDENTS or subject not in {item[0] for item in SUBJECTS}
                or len(scores) != len((20, 20, 20, 40))
                or any(type(points) is not int or points < 0 or points > maximum
                       for points, maximum in zip(scores, (20, 20, 20, 40)))):
            raise ValueError('Invalid synthetic BRS score override.')
    today = today or datetime.now(MOSCOW).date()
    start = today-timedelta(days=95)
    end = today+timedelta(days=45)

    def at(day, hour=10):
        return int(datetime.combine(day,time(hour),MOSCOW).timestamp())

    update(path,create=True)
    with connection(settings,write=True) as db:
        db.execute("INSERT INTO faculties VALUES ('phase3-f','Учебный факультет (демо)')")
        db.execute("INSERT INTO programs VALUES ('phase3-p','phase3-f','Демонстрационная программа')")
        db.executemany("INSERT INTO study_groups VALUES (?,'phase3-p',?,2)",
                       [('g-a','ДЕМО-А'),('g-b','ДЕМО-Б')])
        db.executemany("INSERT INTO semesters VALUES (?,?,?,?)",[
            ('phase3-current','Текущий семестр (демо)',start.isoformat(),end.isoformat()),
            ('phase3-prior','Предыдущий семестр (демо)',(start-timedelta(days=140)).isoformat(),
             (start-timedelta(days=1)).isoformat())])
        db.execute("INSERT INTO buildings VALUES ('phase3-building','Демонстрационный корпус')")
        db.execute("INSERT INTO rooms VALUES ('phase3-room','phase3-building','101',30,'Проектор')")
        actors = {}
        for index, key in enumerate(ACCOUNTS):
            role = 'student' if key in STUDENTS else 'staff'
            actors[key] = {'id':key,'role':role}
            db.execute("INSERT INTO users VALUES (?,?,?,?,1,?)",(key,key,hashes[key],role,at(start,8)))
            name = f'Вымышленный участник {key.upper()}'
            if role=='student':
                db.execute("INSERT INTO student_profiles VALUES (?,?,?)",(key,name,'g-a' if index%2==0 else 'g-b'))
            else:
                title = 'Преподаватель' if key in TEACHERS else ('Деканат' if key in DEANERY else 'Системный администратор')
                db.execute("INSERT INTO staff_profiles VALUES (?,?,?)",(key,name,title))
        db.executemany("INSERT INTO attestation_permissions VALUES (?,'phase3-f',?)",
                       [(key,'examiner') for key in TEACHERS]+[
                           ('d01','schedule'),('d01','late_request'),('d02','review'),('d03','late_execute')])
        db.executemany("INSERT INTO brs_capabilities VALUES ('d01','phase3-f',?)",
                       [('manage_plans',),('manage_enrollments',)])
        db.executemany("INSERT INTO request_staff_scopes VALUES (?,'phase3-f')",[(key,) for key in DEANERY])
        for key in TEACHERS:
            db.execute("INSERT INTO teachers VALUES (?,?)",(key,f'Демонстрационный преподаватель {key.upper()}'))
            db.execute("INSERT INTO brs_whole_teacher_accounts VALUES (?,?)",(key,key))
        for index,(subject,label,control) in enumerate(SUBJECTS):
            db.execute("INSERT INTO subjects VALUES (?,?)",(subject,label))
            db.execute("INSERT INTO curriculum_items VALUES (?,'phase3-p',?,'phase3-current',?,1)",
                       (subject,subject,control))
            maxima = (20,20,20,40)
            categories = [{'code':f'c{i}','title':f'Модуль {i+1}','maximum':m,'admission_min':None}
                          for i,m in enumerate(maxima)]
            scores = [(0,'fail'),(50,'pass')] if control=='credit' else [(0,'2'),(50,'3'),(65,'4'),(80,'5')]
            plan = {'curriculum_id':subject,'source':'Демонстрационная политика Phase 3',
                    'approved_on':(start-timedelta(days=1)).isoformat(),'rounding':'exact','admission_min':50,
                    'categories':categories,'scale':[{'minimum':n,'outcome':value} for n,value in scores],
                    'events':[{**c,'category_code':c['code'],'attempt_limit':1,'retake_policy':'none',
                               'retake_until':None} for c in categories]}
            plan_id = brs.create_plan(db,actors['d01'],at(start,8),plan)['id']
            brs.lock_plan(db,actors['d01'],at(start,8),plan_id)
            academic.approve_policy(db,actors['d01'],at(start,8),plan_id,[c['code'] for c in categories])
            flows = {group:brs.create_offering(db,actors['d01'],at(start,8),{'group_id':group,'plan_id':plan_id})['id']
                     for group in ('g-a','g-b')}
            for group in flows:
                db.execute("INSERT INTO lessons VALUES (?,?,?,?,?,?,?,?,?,'scheduled',1,?)",
                           (uuid4().hex,group,subject,TEACHERS[index],'phase3-room',
                            (today+timedelta(days=index+2)).isoformat(),540 if group=='g-a' else 660,
                            630 if group=='g-a' else 750,'seminar',at(start,8)))
            for number,student in enumerate(STUDENTS,1):
                group = db.execute("SELECT group_id FROM student_profiles WHERE user_id=?",(student,)).fetchone()[0]
                enrolled = brs.enroll(db,actors['d01'],at(start,8),flows[group],
                                      {'student_id':student,'starts_on':start.isoformat()})
                course = enrolled['course_id']
                academic.activate(db,actors['d01'],at(start,9),course)
                first = today-timedelta(days=88)+timedelta(days=number*6+index)
                for event,maximum in enumerate(maxima):
                    result = uuid4().hex
                    override = score_overrides.get((student, subject))
                    points = override[event] if override is not None else (maximum if number==1 else maximum-2)
                    db.execute("INSERT INTO brs_event_results VALUES (?,?,?,?)",
                               (result,course,plan_id,f'c{event}'))
                    db.execute("INSERT INTO brs_attempt_versions VALUES (?,?,?,1,1,1,?,'t01',?,NULL)",
                               (uuid4().hex,result,enrolled['id'],points,at(first,8)))

                def command(actor, when, action, **fields):
                    version = db.execute("SELECT count(*) FROM attestation_events WHERE course_id=?",(course,)).fetchone()[0]
                    return academic.execute(db,actors[actor],when,course,action,
                                            {'expected_version':version,'request_key':uuid4().hex,**fields})

                def attempt(day, grade=None, *, commission=False, absence=False, draft_only=False):
                    start_at = at(day,15)
                    slot = command('d01',at(day,9),'scheduled',starts_at=start_at,ends_at=start_at+3600,
                                   examiner_id='t02',room_id='phase3-room',
                                   commission=['t02','t03'] if commission else [])['slot_id']
                    if absence:
                        command('d01',start_at+3600,'excused',slot_id=slot,
                                reason='Демонстрационное основание',reference='DEMO-ABSENCE-01')
                    else:
                        command('t02',start_at+3600,'draft',slot_id=slot,grade=grade)
                        if not draft_only:
                            command('t02',start_at+3600,'published',slot_id=slot)
                            command('t02',start_at+3600,'completed',slot_id=slot)
                    return slot

                if control=='exam':
                    scenarios = {1:[5],2:[2],3:[2,4],4:[2],5:[2],6:[4],7:[4],8:[3],
                                 9:[2,2,3],10:[2,2,2],11:[]}
                    if student in no_exam_students:
                        scenarios[number] = []
                    for offset,grade in enumerate(scenarios[number]):
                        slot = attempt(first+timedelta(days=offset),grade,commission=offset==2,draft_only=number==7)
                    if number==4 and student not in no_exam_students:
                        instant = at(first+timedelta(days=1))
                        review = command('t02',instant,'review_requested',slot_id=slot,executor_id='t02',
                                         grade=3,reason='Проверен демонстрационный протокол',reference='DEMO-REVIEW-01')
                        command('d02',instant,'review_approved',review_version=review['version'])
                        command('t02',instant,'corrected',review_version=review['version'])
                    if number==11 and student not in no_exam_students:
                        attempt(first,absence=True)
                        future = at(today+timedelta(days=index+2),15)
                        command('d01',at(today,8),'scheduled',starts_at=future,ends_at=future+3600,
                                examiner_id='t02',room_id='phase3-room',commission=[])
                else:
                    attempt(first,draft_only=number==7)
                if number==5:
                    other = 'g-b' if group=='g-a' else 'g-a'
                    move = today-timedelta(days=2)
                    brs.transfer(db,actors['d01'],at(move),enrolled['id'],
                                 {'target_offering_id':flows[other],'starts_on':move.isoformat(),
                                  'reason':'Демонстрационный перевод','mapping':[]})
        db.execute("UPDATE student_profiles SET group_id='g-b' WHERE user_id='s05'")
        prior_day = (start-timedelta(days=1)).isoformat()
        db.execute("""INSERT INTO curriculum_items VALUES
            ('prior-methods','phase3-p','methods','phase3-prior','exam',1)""")
        db.execute("""INSERT INTO assessments VALUES
            ('prior-exam','prior-methods','g-b',?,?,'completed')""",(prior_day,prior_day))
        db.execute("INSERT INTO student_assessments VALUES ('prior-s02','s02','prior-exam')")
        record_in_transaction(db,'prior-s02',0,'graded',2,prior_day,at(start,8))
        if db.execute("PRAGMA foreign_key_check").fetchall() or db.execute("PRAGMA integrity_check").fetchone()[0]!='ok':
            raise ValueError('Demo integrity checks failed.')
    return len(ACCOUNTS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True)
    parser.add_argument('--confirm-demo',action='store_true',required=True)
    parser.add_argument('--credentials-file')
    args = parser.parse_args()
    settings = Settings(database=args.db)
    if (settings.database.exists() or settings.database.suffix!='.sqlite3'
            or not settings.database.is_relative_to((ROOT/'.tmp').resolve())):
        parser.error('Choose a new .tmp/*.sqlite3 database.')
    if args.credentials_file:
        from .demo_credentials import save
        credentials = {key:secrets.token_urlsafe(24) for key in ACCOUNTS}
        save(args.credentials_file,credentials)
    else:
        if not sys.stdin.isatty():
            raise SystemExit('Use a private interactive terminal or Windows DPAPI.')
        credentials = {key:getpass.getpass(f'{key}: ') for key in ACCOUNTS}
    print(f'Created {seed(settings,credentials)} synthetic accounts.')


if __name__=='__main__':
    main()
