"""Explicit local operator changes; no public editing endpoint in V4."""
import argparse
import sqlite3
import time
from ..config import Settings
from ..schedule.service import change_lesson

def main():
    p=argparse.ArgumentParser(description='Change one lesson and record history atomically')
    p.add_argument('--db',required=True);p.add_argument('--lesson',required=True);p.add_argument('--version',required=True,type=int);p.add_argument('--reason',required=True)
    p.add_argument('--date');p.add_argument('--start-minute',type=int);p.add_argument('--end-minute',type=int)
    p.add_argument('--teacher-id');p.add_argument('--room-id');p.add_argument('--status',choices=('scheduled','cancelled'))
    p.add_argument('--confirm-change',action='store_true',required=True)
    args=p.parse_args()
    changes={key:getattr(args,key) for key in ('date','start_minute','end_minute','teacher_id','room_id','status') if getattr(args,key) is not None}
    try:
        result=change_lesson(Settings(database=args.db),args.lesson,args.version,args.reason,changes,int(time.time()))
        print('Lesson updated; version:',result['version']);return 0
    except (ValueError,OSError,sqlite3.Error):
        print('Change rejected; check IDs, interval, version and database.');return 1

if __name__=='__main__':raise SystemExit(main())
