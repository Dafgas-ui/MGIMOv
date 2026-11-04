"""Append a validated demo attempt locally; no credentials or grades in output."""
import argparse
import sqlite3
from ..config import Settings
from ..academics.service import record_result


def main():
    p=argparse.ArgumentParser(description='Append a demo result without overwriting history')
    p.add_argument('--db',required=True);p.add_argument('--assignment',required=True)
    p.add_argument('--expected-attempts',required=True,type=int)
    p.add_argument('--outcome',required=True,choices=('graded','pass','fail','absent'))
    p.add_argument('--grade',type=int);p.add_argument('--performed-on',required=True)
    p.add_argument('--confirm-demo',required=True,action='store_true')
    args=p.parse_args()
    try:
        record_result(Settings(database=args.db),args.assignment,args.expected_attempts,args.outcome,args.grade,args.performed_on)
        print('Demo attempt recorded.');return 0
    except (ValueError,OSError,sqlite3.Error):
        print('Result rejected; check demo database, control type, dates and expected attempt count.');return 1

if __name__=='__main__':raise SystemExit(main())
