"""Fictional academic records in an explicitly selected demo database."""
import argparse
from datetime import date,datetime,timedelta
import sqlite3
import time
from ..config import ROOT,Settings
from ..db import connection
from ..schedule.service import MOSCOW,calendar_date
from ..academics.service import record_in_transaction


def seed_academics(settings,as_of=None):
    if settings.database==(ROOT/'data/deanery.sqlite3').resolve():raise ValueError('Working database forbidden')
    today=calendar_date(as_of) if as_of else datetime.now(MOSCOW).date()
    start=date(today.year,1 if today.month<=6 else 7,1)
    end=date(today.year,6,30) if today.month<=6 else date(today.year,12,31)
    previous_end=start-timedelta(days=1)
    previous_start=date(previous_end.year,1 if previous_end.month<=6 else 7,1)
    event_day=max(start,today-timedelta(days=2)).isoformat()
    future=min(end,today+timedelta(days=10)).isoformat()
    now=int(datetime.combine(today,datetime.min.time(),MOSCOW).timestamp()) if as_of else int(time.time())
    with connection(settings,write=True) as db:
        people={r['login']:dict(r) for r in db.execute("SELECT u.login,u.id,p.group_id,g.program_id FROM users u JOIN student_profiles p ON p.user_id=u.id JOIN study_groups g ON g.id=p.group_id WHERE u.login IN ('student_a','student_b')")}
        if set(people)!={'student_a','student_b'} or {p['group_id'] for p in people.values()}!={'demo-a','demo-b'}:raise ValueError('Separate demo profiles required')
        if db.execute('SELECT 1 FROM student_assessments LIMIT 1').fetchone():raise ValueError('Academic demo already exists')
        # Earlier demo accounts shared a program. Split only these synthetic references atomically.
        if people['student_b']['program_id']!='demo-p' or people['student_a']['program_id']!='demo-p':raise ValueError('Unexpected demo programs')
        db.execute("INSERT INTO programs VALUES ('demo-p-b','demo-f','Аналитика учебных систем (демо)')")
        db.execute("UPDATE study_groups SET program_id='demo-p-b' WHERE id='demo-b'")
        db.executemany('INSERT INTO semesters VALUES (?,?,?,?)',[
            ('academic-previous','Предыдущий семестр (демо)',previous_start.isoformat(),previous_end.isoformat()),
            ('academic-current','Текущий семестр (демо)',start.isoformat(),end.isoformat())])
        for letter,login in (('a','student_a'),('b','student_b')):
            person=people[login];program='demo-p' if letter=='a' else 'demo-p-b'
            titles=['Основы проектирования','Коммуникация будущего','Модели устойчивого развития','Практикум решений'] if letter=='a' else ['Аналитика сценариев','Цифровая этика','Статистика моделей','Методы исследования']
            specs=[('exam','completed',event_day,today.isoformat()),('credit','scheduled',future,None),('graded_credit','completed',event_day,None),('exam','completed',event_day,None)]
            if letter=='a':specs[1]=('credit','completed',event_day,None);specs[2]=('graded_credit','scheduled',future,None);specs[3]=('exam','not_held',None,None)
            for i,(control,status,scheduled,deadline) in enumerate(specs):
                key=f'academic-{letter}-{i}'
                db.execute('INSERT INTO subjects VALUES (?,?)',(key,titles[i]+' (демо)'))
                db.execute('INSERT INTO curriculum_items VALUES (?,?,?,?,?,1)',(key,program,key,'academic-current',control))
                db.execute('INSERT INTO assessments VALUES (?,?,?,?,?,?)',(key,key,person['group_id'],scheduled,deadline,status))
                db.execute('INSERT INTO student_assessments VALUES (?,?,?)',(key,person['id'],key))
            record_in_transaction(db,f'academic-{letter}-0',0,'graded',5 if letter=='a' else 2,event_day,now)
            if letter=='a':record_in_transaction(db,'academic-a-1',0,'pass',None,event_day,now)
            else:record_in_transaction(db,'academic-b-2',0,'graded',4,event_day,now)
            # A prior semester is independent of current progress.
            key=f'academic-{letter}-previous'
            db.execute('INSERT INTO subjects VALUES (?,?)',(key,'Введение в '+('проектирование' if letter=='a' else 'аналитику')+' (демо)'))
            db.execute('INSERT INTO curriculum_items VALUES (?,?,?,?,?,1)',(key,program,key,'academic-previous','graded_credit'))
            db.execute('INSERT INTO assessments VALUES (?,?,?,?,?,?)',(key,key,person['group_id'],previous_end.isoformat(),None,'completed'))
            db.execute('INSERT INTO student_assessments VALUES (?,?,?)',(key,person['id'],key))
            record_in_transaction(db,key,0,'graded',4,previous_end.isoformat(),now)


def main():
    p=argparse.ArgumentParser(description='Seed fictional academic data in separate demo DB')
    p.add_argument('--db',required=True);p.add_argument('--as-of')
    p.add_argument('--confirm-demo',required=True,action='store_true');args=p.parse_args()
    try:
        seed_academics(Settings(database=args.db),args.as_of);print('Synthetic academic records created.');return 0
    except (ValueError,OSError,sqlite3.Error):
        print('Academic seed rejected; check migration, demo profiles and empty academic data.');return 1

if __name__=='__main__':raise SystemExit(main())
