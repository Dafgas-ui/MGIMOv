"""Real HTTP/SQLite QR checks on isolated synthetic lesson rosters."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout
from datetime import datetime
import json
import io
import secrets
import shutil
import sqlite3
from threading import Barrier
import unittest
from unittest.mock import patch

from backend.db import connection
from backend import attendance
from backend.schedule.service import MOSCOW
from backend.migrations.manager import DIRECTORY, update, status, MigrationError, verified_backup
from backend.commands.cleanup_sessions import cleanup, main as cleanup_main
from tests import test_attendance as attendance_fixture
from tests.test_foundation import temporary
from tests.test_brs_foundation import ADMIN
from tests import test_brs_foundation as foundation

ME = attendance_fixture.ME
QR = attendance_fixture.STAFF+'/l/qr'
CHECK = ME+'/qr/check-in'


class AttendanceQRTests(unittest.TestCase):
    def setUp(self):
        self.att = attendance_fixture.AttendanceTests(); self.addCleanup(self.att.doCleanups); self.att.setUp()
        self.case = self.att.case
        self.case.now = int(datetime(2027,3,1,9,15,tzinfo=MOSCOW).timestamp())
        with connection(self.case.settings, write=True) as db:
            db.execute('UPDATE sessions SET expires_at=?', (self.case.now+86400,))
        self.assertEqual(self.att.confirm().status_code,200)

    def issue(self, who='teacher', body=None):
        detail = self.att.detail()
        return self.case.post(QR, body or dict(expected_version=detail['version'],
            lesson_version=detail['lesson']['version'],request_key=secrets.token_hex(16)), who)

    def challenge(self):
        result = self.issue(); self.assertEqual(result.status_code,200,result.text)
        data=result.json();return data,data['url'].split('#attendance-qr=')[1]

    def check(self, token, who='alice'):
        return self.case.post(CHECK,{'token':token},who)

    def test_happy_preview_hash_only_history_repeat_and_manual_correction(self):
        data,token=self.challenge()
        self.assertTrue(data['matrix']);self.assertLessEqual(data['expires_in'],60)
        with connection(self.case.settings) as db:
            self.assertNotIn(token,'\n'.join(db.iterdump()))
        preview=self.case.post(ME+'/qr/preview',{'token':token},'alice')
        self.assertEqual(preview.status_code,200);self.assertEqual(preview.json()['status'],'unmarked')
        self.assertEqual(self.case.count('attendance_events'),1)
        first=self.check(token);self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['status'],'present');self.assertEqual(first.json()['outcome'],'present')
        self.assertEqual(self.check(token).json(),first.json())
        self.assertEqual(self.case.count('attendance_qr_receipts'),1)
        detail=self.att.detail();event=detail['history'][-1]
        self.assertEqual(event['kind'],'qr_mark');self.assertEqual(event['actor_id'],'alice')
        self.assertEqual(self.att.mark(value='absent').status_code,200)
        before_events=self.case.count('attendance_events')
        before_receipts=self.case.count('attendance_qr_receipts')
        repeated=self.check(token)
        self.assertEqual(repeated.status_code,200)
        self.assertEqual(repeated.json()['status'],'absent')
        self.assertEqual(repeated.json()['outcome'],'present') # historical receipt, not current state
        self.assertEqual(self.case.count('attendance_events'),before_events)
        self.assertEqual(self.case.count('attendance_qr_receipts'),before_receipts)
        self.assertEqual(self.case.clients['alice'].get(ME+'/lessons/l').json()['status'],'absent')

    def test_all_manual_values_have_priority_including_unmarked(self):
        for value in ('present','absent','late','unmarked'):
            self.assertEqual(self.att.mark(value=value).status_code,200)
            before=self.case.count('attendance_events')
            _,token=self.challenge();result=self.check(token)
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['outcome'],'manual_priority')
            self.assertEqual(result.json()['status'],value)
            self.assertEqual(self.case.count('attendance_events'),before)

    def test_staff_can_manually_confirm_same_present_after_qr(self):
        _,token=self.challenge();self.assertEqual(self.check(token).status_code,200)
        self.assertEqual(self.att.mark(value='present').status_code,200)
        self.assertEqual(self.att.mark(value='present').status_code,409)
        _,other=self.challenge();self.assertEqual(self.check(other).json()['outcome'],'manual_priority')

    def test_expiry_revoke_rotation_and_issuer_logout(self):
        data,token=self.challenge()
        self.assertEqual(self.case.post(QR+'/'+data['id']+'/close',{},'teacher').status_code,200)
        self.assertEqual(self.case.post(QR+'/'+data['id']+'/close',{},'teacher').status_code,200)
        self.assertEqual(self.check(token).status_code,409)

        _,token=self.challenge();_,new=self.challenge()
        self.assertEqual(self.check(token).status_code,409)
        self.case.now+=60;self.assertEqual(self.check(new).status_code,409)
        _,token=self.challenge()
        with connection(self.case.settings,write=True) as db:
            db.execute("UPDATE sessions SET revoked_at=? WHERE user_id='teacher'",(self.case.now,))
        self.assertEqual(self.check(token).status_code,409)

    def test_cleanup_expired_issuer_preserves_qr_history_and_other_sessions(self):
        data,token=self.challenge()
        self.assertEqual(self.check(token).status_code,200)
        with connection(self.case.settings,write=True) as db:
            issuer=db.execute('SELECT issuer_session FROM attendance_qr_sessions WHERE id=?',(data['id'],)).fetchone()[0]
            db.execute("UPDATE sessions SET expires_at=? WHERE id=? OR user_id='bobby'",(self.case.now,issuer))
            expected=db.execute('SELECT count(*) FROM sessions WHERE expires_at<=?',(self.case.now,)).fetchone()[0]
            history=[tuple(row) for row in db.execute('SELECT * FROM attendance_qr_sessions')]
            receipts=[tuple(row) for row in db.execute('SELECT * FROM attendance_qr_receipts')]
            events=[tuple(row) for row in db.execute('SELECT * FROM attendance_events')]
        self.assertEqual(self.check(token).status_code,409)
        self.assertEqual(cleanup(self.case.settings,now=self.case.now),expected)
        with connection(self.case.settings) as db:
            self.assertFalse(any(row['table']=='sessions' for row in db.execute('PRAGMA foreign_key_list(attendance_qr_sessions)')))
            indexes=[row['name'] for row in db.execute('PRAGMA index_list(attendance_qr_sessions)')]
            self.assertTrue(any(db.execute('PRAGMA index_info("'+name+'")').fetchone()['name']=='issuer_session' for name in indexes))
            self.assertEqual(db.execute('SELECT count(*) FROM sessions WHERE id=?',(issuer,)).fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM sessions WHERE user_id='bobby'").fetchone()[0],0)
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM attendance_qr_sessions')],history)
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM attendance_qr_receipts')],receipts)
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM attendance_events')],events)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertEqual(self.check(token).status_code,409) # token itself has not expired
        self.assertEqual(cleanup(self.case.settings,now=self.case.now),0)

    def test_logout_then_physical_cleanup_rejects_token_before_and_after(self):
        data,token=self.challenge()
        with connection(self.case.settings) as db:
            issuer=db.execute('SELECT issuer_session FROM attendance_qr_sessions WHERE id=?',(data['id'],)).fetchone()[0]
        self.assertEqual(self.case.post('/api/v1/auth/logout',{},'teacher').status_code,204)
        self.assertEqual(self.check(token).status_code,409)

        with connection(self.case.settings,write=True) as db:
            # Model an old revoked session while keeping this challenge's 60s clock unchanged.
            db.execute('UPDATE sessions SET revoked_at=? WHERE id=?',(self.case.now-86400,issuer))
        self.assertEqual(cleanup(self.case.settings,now=self.case.now),1)
        with connection(self.case.settings) as db:
            self.assertIsNone(db.execute('SELECT 1 FROM sessions WHERE id=?',(issuer,)).fetchone())
            self.assertEqual(db.execute('SELECT issuer_session FROM attendance_qr_sessions WHERE id=?',(data['id'],)).fetchone()[0],issuer)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertEqual(self.check(token).status_code,409)

    def test_cleanup_cli_after_qr_uses_unmodified_production_command(self):
        data,token=self.challenge()
        with connection(self.case.settings,write=True) as db:
            issuer=db.execute('SELECT issuer_session FROM attendance_qr_sessions WHERE id=?',(data['id'],)).fetchone()[0]
            db.execute("UPDATE sessions SET expires_at=? WHERE id=? OR user_id='outside'",(self.case.now,issuer))
            expected=db.execute('SELECT count(*) FROM sessions WHERE expires_at<=?',(self.case.now,)).fetchone()[0]
        output=io.StringIO()
        # Only the fixture clock is injected; parser, confirmation guard and cleanup are real.
        with patch('backend.commands.cleanup_sessions.time.time',return_value=self.case.now),patch('sys.argv',
                ['cleanup_sessions','--db',str(self.case.settings.database),'--confirm-cleanup']),redirect_stdout(output):
            self.assertEqual(cleanup_main(),0)
        self.assertEqual(output.getvalue().strip(),f'Sessions removed: {expected}')
        self.assertEqual(self.check(token).status_code,409)
        with connection(self.case.settings) as db:
            self.assertIsNone(db.execute('SELECT id FROM sessions WHERE id=?',(issuer,)).fetchone())
            self.assertEqual(db.execute('SELECT count(*) FROM attendance_qr_sessions').fetchone()[0],1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_reconfirm_move_cancel_reassignment_and_permission_revocation(self):
        _,token=self.challenge();self.assertEqual(self.att.confirm().status_code,200)
        self.assertEqual(self.check(token).status_code,409)
        _,token=self.challenge();self.att.reschedule(start_minute=541)
        self.assertEqual(self.check(token).status_code,409)
        self.assertEqual(self.att.confirm().status_code,200)
        _,token=self.challenge();self.att.reschedule(status='cancelled')
        self.assertEqual(self.check(token).status_code,409)
        self.att.reschedule(status='scheduled');self.assertEqual(self.att.confirm().status_code,200)
        _,token=self.challenge()
        with connection(self.case.settings,write=True) as db:
            db.execute("DELETE FROM brs_whole_teacher_accounts WHERE staff_id='teacher'")
        self.assertIn(self.check(token).status_code,(404,409))

    def test_authorization_csrf_privacy_outside_window_and_stale_version(self):
        self.assertEqual(self.issue('alice').status_code,403)
        self.assertEqual(self.issue('outside').status_code,404)
        _,token=self.challenge()
        self.assertEqual(self.check(token,'bobby').status_code,404)
        self.assertEqual(self.check(token,'teacher').status_code,403)
        self.assertEqual(self.case.clients['alice'].post(CHECK,json={'token':token}).status_code,403)
        self.assertEqual(self.check('x'*43).status_code,404)
        self.assertEqual(self.case.post(CHECK,{'token':token,'student_id':'bobby'},'alice').status_code,422)
        body=dict(expected_version=100,lesson_version=1,request_key=secrets.token_hex(16))
        self.assertEqual(self.issue(body=body).status_code,409)
        self.case.now+=3600;self.assertEqual(self.issue().status_code,409)

    def test_issue_replay_never_stores_plaintext_or_reissues_secret(self):
        detail=self.att.detail();body=dict(expected_version=detail['version'],lesson_version=1,request_key=secrets.token_hex(16))
        gate=Barrier(2)
        def same_issue(_):gate.wait();return self.issue(body=body)
        with ThreadPoolExecutor(2) as pool:responses=list(pool.map(same_issue,range(2)))
        self.assertTrue(all(r.status_code==200 for r in responses),[r.status_code for r in responses])
        self.assertEqual(sum(r.json()['code_available'] for r in responses),1)
        self.assertEqual(len({r.json()['id'] for r in responses}),1)
        first=next(r for r in responses if r.json()['code_available'])
        again=self.issue(body=body);self.assertEqual(again.status_code,200)
        self.assertEqual(again.json()['id'],first.json()['id']);self.assertFalse(again.json()['code_available'])
        self.assertNotIn('url',again.json());self.assertEqual(self.case.count('attendance_qr_sessions'),1)
        self.assertEqual(self.issue(body={**body,'expected_version':99}).status_code,409)
        with connection(self.case.settings,write=True) as db:
            db.execute("DELETE FROM brs_whole_teacher_accounts WHERE staff_id='teacher'")
        self.assertEqual(self.case.post(QR,body,'teacher').status_code,404)

    def test_concurrent_identical_and_distinct_students(self):
        self.assertEqual(self.case.post(ADMIN+'/offerings/'+self.att.flow+'/enrollments',
            {'student_id':'bobby','starts_on':'2027-02-01'},'admin').status_code,201)
        self.assertEqual(self.att.confirm().status_code,200)
        _,token=self.challenge()
        for users in [('alice','alice'),('alice','bobby')]:
            gate=Barrier(2)
            def run(who):gate.wait();return self.check(token,who)
            with ThreadPoolExecutor(2) as pool:responses=list(pool.map(run,users))
            self.assertTrue(all(r.status_code==200 for r in responses),[r.status_code for r in responses])
        self.assertEqual(self.case.count('attendance_qr_receipts'),2)
        self.assertEqual(self.case.count('attendance_events'),4) # two rosters, two actual QR marks

    def test_audit_and_receipt_failure_roll_back_every_business_write(self):
        with patch('backend.attendance_qr.audit',side_effect=sqlite3.OperationalError('Synthetic audit failure')):
            self.assertEqual(self.issue().status_code,503)
        self.assertEqual(self.case.count('attendance_qr_sessions'),0)
        _,token=self.challenge();before=self.att.detail()
        # Persistent trigger exists only in this test's isolated database.
        with connection(self.case.settings,write=True) as db:
            db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON attendance_qr_receipts BEGIN SELECT RAISE(ABORT,'Synthetic receipt failure'); END")
        self.assertEqual(self.check(token).status_code,503)
        self.assertEqual(self.att.detail(),before);self.assertEqual(self.case.count('attendance_qr_receipts'),0)

    def test_failed_reissue_preserves_previous_token_and_ignored_receipt_rolls_back(self):
        _,token=self.challenge()
        with patch('backend.attendance_qr.audit',side_effect=sqlite3.OperationalError('Synthetic audit failure')):
            self.assertEqual(self.issue().status_code,503)
        self.assertEqual(self.case.post(ME+'/qr/preview',{'token':token},'alice').status_code,200)
        before=self.att.detail()
        with connection(self.case.settings,write=True) as db:
            db.execute('CREATE TRIGGER ignore_receipt BEFORE INSERT ON attendance_qr_receipts BEGIN SELECT RAISE(IGNORE); END')
        self.assertEqual(self.check(token).status_code,503)
        self.assertEqual(self.att.detail(),before)
        self.assertEqual(self.case.count('attendance_qr_receipts'),0)

    def test_limited_issuance_and_concurrent_manual_priority(self):
        _,token=self.challenge();gate=Barrier(2)
        def automatic():gate.wait();return self.check(token)
        def manual():gate.wait();return self.att.mark(value='absent')
        with ThreadPoolExecutor(2) as pool:
            a=pool.submit(automatic);b=pool.submit(manual);qr_result=a.result();manual_result=b.result()
        self.assertEqual(qr_result.status_code,200)
        self.assertIn(manual_result.status_code,(200,409))
        if manual_result.status_code==409:self.assertEqual(self.att.mark(value='absent').status_code,200)
        self.assertEqual(self.check(token).json()['status'],'absent')
        for _ in range(9):self.assertEqual(self.issue().status_code,200)
        self.assertEqual(self.issue().status_code,429)

    def test_upgrade_populated_0025_and_atomic_rollback(self):
        root=self.enterContext(temporary())
        prior=root/'prior';prior.mkdir()
        for p in DIRECTORY.glob('*.sql'):
            if p.name[:4]<='0025':shutil.copyfile(p,prior/p.name)
        old=foundation.BRSFoundationTests();self.addCleanup(old.doCleanups)
        old.initialize(root,definitions=prior)
        old.enroll_alice()
        self.assertEqual(old.bind().status_code,201)
        path=old.settings.database
        actor={'id':'teacher','role':'staff'}
        with connection(old.settings,write=True) as db:
            detail=attendance.staff_detail(db,actor,'l')
            attendance.change(db,actor,old.now,'l',dict(action='confirm',expected_version=0,lesson_version=1,
                candidate_token=detail['candidate_token'],reason='Historical roster'))
            attendance.change(db,actor,old.now,'l',dict(action='mark',expected_version=1,lesson_version=1,
                student_id='alice',status='late',reason='Historical correction'))
            preserved=[tuple(row) for row in db.execute('SELECT * FROM attendance_events ORDER BY version')]
        backup=root/'old-backup.sqlite3';update(path,backup=backup,directory=DIRECTORY)
        self.assertEqual(status(path)['applied'][-1],'0026_attendance_qr')
        self.assertEqual(update(path)['pending'],[])
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT * FROM attendance_events ORDER BY version').fetchall(),preserved)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok');self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        broken=root/'broken';shutil.copytree(DIRECTORY,broken,ignore=shutil.ignore_patterns('__pycache__'))
        migration=broken/'0026_attendance_qr.sql';migration.write_text(migration.read_text(encoding='utf-8')+'\nSELECT * FROM no_such_qr_table;\n',encoding='utf-8')
        with closing(sqlite3.connect(backup)) as db:before=list(db.iterdump())
        with self.assertRaisesRegex(MigrationError,'0026_attendance_qr'):
            update(backup,backup=root/'before-failure.sqlite3',directory=broken)
        self.assertEqual(status(backup)['pending'],['0026_attendance_qr'])
        with closing(sqlite3.connect(backup)) as db:
            self.assertTrue(list(db.iterdump())==before,'Failed migration changed schema, history or data')
