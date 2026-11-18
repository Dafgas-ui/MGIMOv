"""Measure unchanged seed coverage on new private synthetic databases, without credential output."""
from collections import Counter
from datetime import datetime
import json
import secrets
import shutil

from backend import attendance
from backend.commands import seed_attestations, seed_contest_demo
from backend.commands.seed_demo import seed_demo
from backend.commands.seed_schedule import seed_schedule
from backend.config import ROOT, Settings
from backend.db import connection
from backend.migrations.manager import update
from backend.schedule.service import MOSCOW, snapshot
from tests.test_foundation import temporary


def measure(settings):
    reasons = Counter()
    eligible = 0
    now = int(datetime.now(MOSCOW).timestamp())
    with connection(settings, write=True) as db:
        lessons = db.execute('SELECT id FROM lessons ORDER BY id').fetchall()
        for row in lessons:
            lesson = snapshot(db, row['id'])
            candidate, error = attendance.roster_candidates(db, lesson)
            actor = db.execute("""SELECT u.id,u.role FROM brs_whole_teacher_accounts t
                JOIN users u ON u.id=t.staff_id WHERE t.teacher_id=? AND u.active=1 AND u.role='staff'""",
                (lesson['teacher_id'],)).fetchone()
            failures = []
            if lesson['status'] != 'scheduled':
                failures.append('cancelled')
            if error:
                failures.append(error)
            if actor is None:
                failures.append('Нет подтверждённой привязки преподавателя к аккаунту Staff.')
            if failures:
                reasons['; '.join(failures)] += 1
                continue
            db.execute('SAVEPOINT attendance_coverage')
            detail = attendance.staff_detail(db, actor, lesson['id'])
            result = attendance.change(db, actor, now, lesson['id'], {
                'action':'confirm', 'expected_version':detail['version'], 'lesson_version':lesson['version'],
                'candidate_token':attendance.fingerprint(candidate), 'reason':'Synthetic coverage verification',
            })
            assert result['version'] == 1 and len(result['students']) > 0
            db.execute('ROLLBACK TO attendance_coverage')
            db.execute('RELEASE attendance_coverage')
            eligible += 1
        assert db.execute('SELECT count(*) FROM attendance_journals').fetchone()[0] == 0
    return {'lessons':len(lessons), 'can_confirm':eligible, 'blocked':len(lessons)-eligible,
            'reasons':dict(reasons)}


def main():
    today = datetime.now(MOSCOW).date()
    results = {'date':today.isoformat(), 'sets':{}}
    demo = seed_contest_demo.prepare({key:secrets.token_urlsafe(24) for key in seed_contest_demo.ACCOUNTS})
    try:
        results['sets']['seed_contest_demo'] = measure(Settings(demo))
    finally:
        parent = demo.parent.resolve()
        assert parent.is_relative_to(ROOT/'.tmp') and parent.name.startswith('contest-demo-')
        shutil.rmtree(parent)
    with temporary() as root:
        settings = Settings(root/'attestations.sqlite3')
        seed_attestations.seed(settings, {key:secrets.token_urlsafe(24) for key in seed_attestations.ACCOUNTS}, today=today)
        results['sets']['seed_attestations'] = measure(settings)
        settings = Settings(root/'schedule.sqlite3')
        update(settings.database, create=True)
        seed_demo(settings, {key:secrets.token_urlsafe(24) for key in ('student_a','student_b','staff_demo')})
        seed_schedule(settings, today.isoformat())
        results['sets']['seed_schedule'] = measure(settings)
    print(json.dumps(results))


if __name__ == '__main__':
    main()
