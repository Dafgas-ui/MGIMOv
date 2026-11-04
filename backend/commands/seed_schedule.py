"""Synthetic week only; explicit separate database, no startup seeding."""
import argparse
from datetime import datetime
import sqlite3
import time
from ..config import ROOT, Settings
from ..db import connection
from ..schedule.service import MOSCOW, date_range, change_in_transaction

def seed_schedule(settings,week_of=None):
    if settings.database==(ROOT/'data/deanery.sqlite3').resolve():raise ValueError('Working database is not a demo target')
    days=date_range(week_of or datetime.now(MOSCOW).date().isoformat(),'week')
    now=int(time.time())
    with connection(settings,write=True) as db:
        groups={r['login']:r['group_id'] for r in db.execute("SELECT u.login,p.group_id FROM users u JOIN student_profiles p ON p.user_id=u.id WHERE u.login IN ('student_a','student_b')")}
        if set(groups)!={'student_a','student_b'} or len(set(groups.values()))!=2:raise ValueError('Two separate demo groups required')
        if db.execute('SELECT 1 FROM lessons WHERE group_id IN (?,?) LIMIT 1',tuple(groups.values())).fetchone():raise ValueError('Demo timetable already exists')
        db.executemany('INSERT INTO buildings VALUES (?,?)',[('demo-alpha','Корпус Альфа (демо)'),('demo-beta','Корпус Бета (демо)')])
        db.executemany('INSERT INTO rooms VALUES (?,?,?,?,?)',[('demo-r1','demo-alpha','101',40,'Проектор'),('demo-r2','demo-alpha','202',20,'Компьютеры'),('demo-r3','demo-beta','301',80,'Проектор, доска')])
        db.executemany('INSERT INTO teachers VALUES (?,?)',[('demo-t1','Марк Примерный (вымышленный)'),('demo-t2','Анна Учебная (вымышленная)')])
        db.executemany('INSERT INTO subjects VALUES (?,?)',[('demo-s1','Моделирование будущего'),('demo-s2','Анализ вымышленных данных')])
        for name,group in groups.items():
            a=name=='student_a'
            for index,day in enumerate(days):
                db.execute('INSERT INTO lessons VALUES (?,?,?,?,?,?,?,?,?,?,1,?)',
                    (('demo-a-' if a else 'demo-b-')+str(index),group,'demo-s1' if a else 'demo-s2','demo-t1' if a else 'demo-t2','demo-r1' if a else 'demo-r3',day,540 if a else 840,630 if a else 930,'lecture' if index%2==0 else 'practice','scheduled',now))
        change_in_transaction(db,'demo-a-0',1,'Демонстрационная отмена занятия',{'status':'cancelled'},now)
        change_in_transaction(db,'demo-a-1',1,'Демонстрационный перенос занятия',{'date':days[3],'start_minute':660,'end_minute':750},now)
        change_in_transaction(db,'demo-a-2',1,'Смена аудитории',{'room_id':'demo-r2'},now)
        change_in_transaction(db,'demo-a-3',1,'Замена преподавателя',{'teacher_id':'demo-t2'},now)
    return days

def main():
    p=argparse.ArgumentParser(description='Seed synthetic timetable in a separate demo DB')
    p.add_argument('--db',required=True);p.add_argument('--week-of');p.add_argument('--confirm-demo',action='store_true',required=True)
    args=p.parse_args()
    try:
        seed_schedule(Settings(database=args.db),args.week_of);print('Synthetic timetable created.');return 0
    except (ValueError,OSError,sqlite3.Error):
        print('Timetable not created; check migration, demo groups and empty schedule.');return 1

if __name__=='__main__':raise SystemExit(main())
