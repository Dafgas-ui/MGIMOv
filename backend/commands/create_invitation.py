"""Explicit local invitation issuance; secret shown only in the operator terminal."""
import argparse,secrets,sys,time
from ..config import Settings
from ..db import connection
from ..auth.service import digest

def issue(settings,group_id,now=None):
    now=int(time.time()) if now is None else now
    token=secrets.token_urlsafe(32)
    with connection(settings,write=True) as db:
        if not db.execute('SELECT 1 FROM study_groups WHERE id=?',(group_id,)).fetchone():raise ValueError('Unknown group')
        db.execute('INSERT INTO registration_invitations VALUES (?,?,?,NULL,?)',(digest(token),group_id,now+86400,now))
    return token

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',required=True);parser.add_argument('--group',required=True)
    args=parser.parse_args()
    if not sys.stdout.isatty():raise SystemExit('Use a private interactive terminal; do not redirect invitations.')
    token=issue(Settings(database=args.db),args.group)
    print('Одноразовое приглашение на 24 часа (не публикуйте):',token)
if __name__=='__main__':main()
