"""Prepare synthetic accounts in an explicitly selected empty demo database."""
import argparse
import getpass
from pathlib import Path
import sqlite3
import sys
import time
import uuid
from ..config import ROOT, Settings
from ..db import connection
from ..migrations.manager import status
from ..security.passwords import hash_password

def seed_demo(settings,passwords):
    if settings.database == (ROOT/'data/deanery.sqlite3').resolve():
        raise ValueError('Default working database is not a demo target.')
    if '0002_identity' not in status(settings.database)['applied']:
        raise ValueError('Apply identity migration to the demo database first.')
    if set(passwords)!={'student_a','student_b','staff_demo'}:raise ValueError('Three credentials required.')
    hashes={login:hash_password(password) for login,password in passwords.items()}
    ids={login:str(uuid.uuid4()) for login in passwords}
    with connection(settings,write=True) as db:
        if db.execute('SELECT 1 FROM users LIMIT 1').fetchone():raise ValueError('Demo database must have no users.')
        db.execute("INSERT INTO faculties VALUES ('demo-f','Факультет вымышленных исследований')")
        db.execute("INSERT INTO programs VALUES ('demo-p','demo-f','Проектирование будущего')")
        db.executemany('INSERT INTO study_groups VALUES (?,?,?,?)',[('demo-a','demo-p','ДЕМО-А',1),('demo-b','demo-p','ДЕМО-Б',2)])
        for login in passwords:
            role='staff' if login=='staff_demo' else 'student'
            db.execute('INSERT INTO users VALUES (?,?,?,?,1,?)',(ids[login],login,hashes[login],role,int(time.time())))
        db.executemany('INSERT INTO student_profiles VALUES (?,?,?)',[(ids['student_a'],'Алексей Примеров — вымышленный','demo-a'),(ids['student_b'],'Вера Образцова — вымышленная','demo-b')])
        db.execute('INSERT INTO staff_profiles VALUES (?,?,?)',(ids['staff_demo'],'Ирина Демонстрационная — вымышленная','Сотрудник демонстрационного деканата'))
    return ids

def main():
    parser=argparse.ArgumentParser(description='Explicit synthetic demo accounts; no credential output')
    parser.add_argument('--db',required=True)
    parser.add_argument('--confirm-demo',action='store_true',required=True)
    args=parser.parse_args()
    try:
        if not sys.stdin.isatty():raise ValueError('Use an interactive terminal for hidden password entry.')
        settings=Settings(database=Path(args.db))
        credentials={}
        for login in ('student_a','student_b','staff_demo'):
            first=getpass.getpass(login+' — новый пароль: ')
            if first!=getpass.getpass('Повторите пароль: '):raise ValueError('Passwords differ.')
            credentials[login]=first
        seed_demo(settings,credentials)
        print('Созданы student_a, student_b, staff_demo. Пароли не выводятся и не сохраняются в документах.')
        return 0
    except (ValueError,OSError,sqlite3.Error):
        print('Демоданные не созданы: проверьте отдельную базу, миграции, отсутствие пользователей и пароль 15–128 символов.',file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
