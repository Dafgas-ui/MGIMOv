"""Prepare a fresh local RC3.1 + Coursework demonstration on synthetic data."""
import argparse
from datetime import datetime, timedelta
import getpass
import os
from pathlib import Path
import secrets
import sys

from ..brs import service as brs
from ..config import ROOT, Settings
from ..coursework import create_draft, execute
from ..db import connection
from ..migrations.manager import status
from ..schedule.service import MOSCOW
from . import seed_attestations
from .contest_demo_permissions import (
    PrivateDemoDirectory, check_windows_chain, create_windows_directory, windows_user_sid,
)

ACCOUNTS = ('s01', 's02', 't01')


def prepare(credentials, *, parent=None):
    """Create a new private run directory. An existing run is never reopened for writes."""
    if set(credentials) != set(ACCOUNTS) or len(set(credentials.values())) != len(ACCOUNTS):
        raise ValueError('Provide three distinct demo passwords.')
    scratch = ROOT / '.tmp'
    if os.name == 'nt':
        sid = windows_user_sid()
        try:
            check_windows_chain(ROOT, sid)
        except PermissionError as error:
            raise PermissionError(
                'Prepare the demo from a private copy of MGIMOv under your Windows user profile.'
            ) from error
        if not os.path.lexists(scratch):
            create_windows_directory(scratch, sid)
    else:
        scratch.mkdir(exist_ok=True)
    parent = ROOT / Path(parent) if parent is not None else scratch
    if '..' in parent.parts or not parent.is_relative_to(scratch):
        raise ValueError('Demo runs must be created inside the project .tmp directory.')
    if os.name != 'nt' and parent.resolve(strict=True) != parent:
        raise ValueError('Expected a project-local .tmp directory without redirects.')

    now = datetime.now(MOSCOW)
    timestamp = int(now.timestamp())
    directory = PrivateDemoDirectory(parent)
    try:
        directory.check_directory()
        settings = Settings(database=directory.path / 'demo.sqlite3')
        passwords = {key: credentials[key] if key in credentials else secrets.token_urlsafe(24)
                     for key in seed_attestations.ACCOUNTS}
        seed_attestations.seed(settings, passwords, today=now.date())
        directory.check_database(settings.database)
        add_coursework(settings, now, timestamp)
        report = status(settings.database)
        if report['state'] != 'managed' or report['pending']:
            raise ValueError('The isolated demo did not pass migration verification.')
        directory.check_database(settings.database)
        return settings.database
    except Exception as error:
        raise RuntimeError(
            f'Demo not ready. Inspect and clean up only this run directory: {directory.path}. {error}'
        ) from error


def add_coursework(settings, now, timestamp):
    admin = {'id': 'd01', 'role': 'staff'}
    teacher = {'id': 't01', 'role': 'staff'}
    with connection(settings, write=True) as db:
        # The demo approver needs this permission only while preparing the two appointments.
        db.execute("INSERT INTO brs_capabilities VALUES ('d01','phase3-f','manage_teaching')")
        for group, title in (
            ('g-a', 'Демо A · Разбор учебного кейса'),
            ('g-b', 'Демо B · Сравнение учебных аргументов'),
        ):
            flow = brs.get(db, """SELECT o.id,l.id AS lesson_id,l.version FROM brs_offerings o
                JOIN brs_whole_plans p ON p.id=o.plan_id JOIN lessons l ON l.group_id=o.group_id
                WHERE o.group_id=? AND p.curriculum_id='law' AND l.subject_id='law' AND l.teacher_id='t01'""",
                           group)
            db.execute('UPDATE lessons SET date=? WHERE id=?', (now.date().isoformat(), flow['lesson_id']))
            brs.grant_teaching(db, admin, timestamp, flow['id'], {
                'staff_id': teacher['id'], 'lesson_id': flow['lesson_id'], 'lesson_version': flow['version'],
                'expires_at': int((now + timedelta(days=7)).timestamp()),
                'can_confirm_final': False, 'event_code': None,
            })
            assignment = create_draft(
                db, teacher, timestamp, flow['id'], kind='practice', title=title,
                description='Синтетическое задание: сформулируйте вывод и обоснуйте его двумя аргументами.',
                due_at=int((now + timedelta(days=2)).timestamp()), mode='online',
            )
            execute(db, teacher, timestamp, assignment, 'publish', expected_version=1,
                    request_key=secrets.token_hex(16), data={'grading_mode': 'independent', 'max_points': 10})
        db.execute("DELETE FROM brs_capabilities WHERE staff_id='d01' AND capability='manage_teaching'")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-demo', action='store_true', required=True)
    args = parser.parse_args()
    if not args.confirm_demo or not sys.stdin.isatty():
        parser.error('Use --confirm-demo from a private interactive terminal.')
    credentials = {who: getpass.getpass(f'{who} (new synthetic password, 15–128 characters): ')
                   for who in ACCOUNTS}
    try:
        path = prepare(credentials)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    print(f'DEMO_DB={path}')


if __name__ == '__main__':
    main()
