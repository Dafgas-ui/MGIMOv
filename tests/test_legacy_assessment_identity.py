import secrets
import shutil
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import patch

from backend.commands.seed_attestations import ACCOUNTS, seed
from backend.config import Settings
from backend.migrations.manager import DIRECTORY, MigrationError, status, update, verified_backup
from tests.test_foundation import temporary


CONFLICTS = """SELECT t.id FROM assessment_attempts t
    JOIN student_assessments sa ON sa.id=t.assignment_id
    JOIN assessments a ON a.id=sa.assessment_id
    JOIN brs_student_courses c ON (c.student_id,c.curriculum_id)=(sa.student_id,a.curriculum_id)
    JOIN attestation_positions p ON p.course_id=c.id"""
AUDITOR_REPLACEMENTS = (
    """INSERT OR REPLACE INTO assessments SELECT id,'law','g-a',scheduled_on,deadline_on,status
       FROM assessments WHERE id='prior-exam'""",
    """INSERT OR REPLACE INTO student_assessments SELECT id,'s01',assessment_id
       FROM student_assessments WHERE id='prior-s02'""",
)
ATTEMPT_ROWID_REPLACEMENT = """INSERT OR REPLACE INTO assessment_attempts
    (rowid,id,assignment_id,number,outcome,grade,performed_on,recorded_at)
    SELECT rowid,'replacement',assignment_id,2,'graded',4,performed_on,recorded_at+1
    FROM assessment_attempts WHERE assignment_id='prior-s02' AND number=1"""
APPEND_RETAKE = """INSERT INTO assessment_attempts
    SELECT 'legitimate-retake',assignment_id,2,'graded',4,performed_on,recorded_at+1
    FROM assessment_attempts WHERE assignment_id='prior-s02' AND number=1"""


def snapshot(db):
    return {
        table: db.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall()
        for table in ('assessments','student_assessments','assessment_attempts','attestation_positions',
                      'attestation_slots','attestation_events','attestation_receipts','staff_audit')
    }


class LegacyAssessmentIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = cls.enterClassContext(temporary())
        cls.prior = root/'migrations-0012'
        cls.prior.mkdir()
        for file in sorted(DIRECTORY.glob('*.sql'))[:12]:
            shutil.copyfile(file,cls.prior/file.name)
        cls.source = root/'source.sqlite3'
        with patch('backend.commands.seed_attestations.update',side_effect=lambda path,**args:
                   update(path,directory=cls.prior,**args)):
            seed(Settings(cls.source),{key:secrets.token_urlsafe(20) for key in ACCOUNTS})

    def copy(self):
        return verified_backup(self.source,self.enterContext(temporary())/'copy.sqlite3')

    def copy_at_0013(self):
        path = self.copy()
        migrations = path.parent/'migrations-0013'
        shutil.copytree(self.prior,migrations)
        migration = DIRECTORY/'0013_legacy_assessment_identity.sql'
        shutil.copyfile(migration,migrations/migration.name)
        self.assertEqual(update(path,backup=path.with_name('before-0013.sqlite3'),
                                directory=migrations)['applied'][-1],migration.stem)
        return path

    def test_attempt_rowid_replacement_reproduces_on_0013(self):
        path = self.copy_at_0013()
        with closing(sqlite3.connect(path,isolation_level=None)) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA recursive_triggers=OFF')
            query = "SELECT number,grade FROM assessment_attempts WHERE assignment_id='prior-s02'"
            self.assertEqual(db.execute(query).fetchall(),[(1,2)])
            db.execute(ATTEMPT_ROWID_REPLACEMENT)
            self.assertEqual(db.execute(query).fetchall(),[(2,4)])
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_attempt_history_upgrade_and_conflicts(self):
        path = self.copy_at_0013()
        with closing(sqlite3.connect(path,isolation_level=None)) as db:
            db.execute("UPDATE assessments SET status='cancelled' WHERE id='prior-exam'")
            before = snapshot(db)
        backup = path.with_name('before-0014.sqlite3')
        self.assertEqual(update(path,backup=backup)['applied'][-1],'0026_attendance_qr')
        self.assertEqual(status(backup)['applied'][-1],'0013_legacy_assessment_identity')
        self.assertEqual(update(path)['pending'],[])
        with closing(sqlite3.connect(path,isolation_level=None)) as db:
            self.assertEqual(snapshot(db),before)
            db.execute("UPDATE assessments SET status='completed' WHERE id='prior-exam'")
            baseline = snapshot(db)
            attempts = baseline['assessment_attempts']
            original_id,_,_,_,_,day,recorded = attempts[0]
            for foreign_keys in (0,1):
                db.execute(f'PRAGMA foreign_keys={foreign_keys}')
                for recursive in (0,1):
                    db.execute(f'PRAGMA recursive_triggers={recursive}')
                    with self.subTest(foreign_keys=foreign_keys,recursive=recursive):
                        with self.assertRaisesRegex(sqlite3.OperationalError,'rowid'):
                            db.execute(ATTEMPT_ROWID_REPLACEMENT)
                        for statement, params in (
                            ("INSERT OR REPLACE INTO assessment_attempts VALUES (?,'prior-s02',2,'graded',4,?,?)",
                             (original_id,day,recorded+1)),
                            ("REPLACE INTO assessment_attempts VALUES ('other','prior-s02',1,'graded',4,?,?)",
                             (day,recorded+1)),
                            ("UPDATE OR REPLACE assessment_attempts SET grade=4",()),
                            ("DELETE FROM assessment_attempts",()),
                            ("""INSERT INTO assessment_attempts VALUES ('other','prior-s02',1,'graded',4,?,?)
                                ON CONFLICT(assignment_id,number) DO UPDATE SET grade=excluded.grade""",
                             (day,recorded+1)),
                        ):
                            with self.assertRaises(sqlite3.IntegrityError):
                                db.execute(statement,params)
                            self.assertEqual(snapshot(db),baseline)
                        db.execute('BEGIN')
                        try:
                            with self.assertRaises(sqlite3.IntegrityError):
                                db.execute("""INSERT OR REPLACE INTO assessment_attempts VALUES
                                    ('valid-first','prior-s02',2,'graded',2,?,?),
                                    (?,'prior-s02',3,'graded',4,?,?)""",
                                    (day,recorded+1,original_id,day,recorded+2))
                            self.assertEqual(snapshot(db),baseline)
                            db.execute(APPEND_RETAKE)
                            self.assertEqual(db.execute("""SELECT number,grade FROM assessment_attempts
                                WHERE assignment_id='prior-s02' ORDER BY number""").fetchall(),[(1,2),(2,4)])
                            self.assertEqual(db.execute('SELECT * FROM assessment_attempts WHERE id=?',
                                                        (original_id,)).fetchone(),attempts[0])
                        finally:
                            db.rollback()
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))

    def test_auditor_reproduction_and_refusal_to_migrate_contaminated_0012(self):
        path = self.copy()
        with closing(sqlite3.connect(path,isolation_level=None)) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA recursive_triggers=OFF')
            for sql in AUDITOR_REPLACEMENTS:
                db.execute(sql)
            self.assertEqual(len(db.execute(CONFLICTS).fetchall()),1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            corrupted = snapshot(db)
        with self.assertRaisesRegex(MigrationError,'конфликтующие официальные источники'):
            update(path,backup=path.with_name('contaminated-backup.sqlite3'))
        self.assertEqual(status(path)['applied'][-1],'0012_attestations')
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(snapshot(db),corrupted)

    def test_upgrade_preserves_official_history_and_blocks_all_parent_replacements(self):
        path = self.copy()
        with closing(sqlite3.connect(path)) as db:
            # Exercise both the explicit and the automatically allocated rowid paths.
            db.execute("UPDATE assessments SET rowid=-1 WHERE id='prior-exam'")
            db.execute("UPDATE student_assessments SET rowid=-1 WHERE id='prior-s02'")
            db.commit()
            original = snapshot(db)
        backup = path.with_name('before-0013.sqlite3')
        self.assertEqual(update(path,backup=backup)['applied'][-1],'0026_attendance_qr')
        self.assertEqual(status(backup)['applied'][-1],'0012_attestations')
        self.assertEqual(update(path)['pending'],[])
        with closing(sqlite3.connect(path,isolation_level=None)) as db:
            self.assertEqual(snapshot(db),original)
            db.execute('PRAGMA foreign_keys=ON')
            db.execute("INSERT INTO assessments VALUES ('donor','law','g-a',NULL,NULL,'scheduled')")
            db.execute("INSERT INTO student_assessments VALUES ('donor','s01','donor')")
            baseline = snapshot(db)
            attacks = (*AUDITOR_REPLACEMENTS,
                "INSERT OR REPLACE INTO student_assessments VALUES ('prior-s02','s01','donor')",
                """INSERT OR REPLACE INTO assessments SELECT 'other',curriculum_id,group_id,scheduled_on,
                   deadline_on,status FROM assessments WHERE id='prior-exam'""",
                """INSERT OR REPLACE INTO student_assessments SELECT 'other',student_id,assessment_id
                   FROM student_assessments WHERE id='prior-s02'""",
                """INSERT OR REPLACE INTO assessments(rowid,id,curriculum_id,group_id,status)
                   VALUES (-1,'unused','language','g-a','scheduled')""",
                """INSERT OR REPLACE INTO student_assessments(rowid,id,student_id,assessment_id)
                   VALUES (-1,'unused','s03','donor')""",
                """INSERT OR REPLACE INTO assessments(rowid,id,curriculum_id,group_id,status)
                   VALUES (-1,'prior-exam','language','g-a','completed')""",
                """INSERT OR REPLACE INTO student_assessments(rowid,id,student_id,assessment_id)
                   VALUES (-1,'prior-s02','s03','donor')""",
                "UPDATE assessments SET curriculum_id='law' WHERE id='prior-exam'",
                "UPDATE assessments SET group_id='g-a' WHERE id='prior-exam'",
                "UPDATE student_assessments SET student_id='s04' WHERE id='prior-s02'",
                "UPDATE student_assessments SET assessment_id='donor' WHERE id='prior-s02'",
                "UPDATE OR REPLACE assessments SET id='prior-exam' WHERE id='donor'",
                "UPDATE OR REPLACE student_assessments SET id='prior-s02' WHERE id='donor'",
                "UPDATE OR REPLACE assessments SET (curriculum_id,group_id)=('prior-methods','g-b') WHERE id='donor'",
                "UPDATE OR REPLACE student_assessments SET (student_id,assessment_id)=('s02','prior-exam') WHERE id='donor'",
                "UPDATE OR REPLACE assessments SET rowid=-1 WHERE id='donor'",
                "UPDATE OR REPLACE student_assessments SET rowid=-1 WHERE id='donor'",
                "DELETE FROM assessments WHERE id='prior-exam'",
                "DELETE FROM student_assessments WHERE id='prior-s02'",
            )
            for foreign_keys in (0,1):
                db.execute(f'PRAGMA foreign_keys={foreign_keys}')
                for recursive in (0,1):
                    db.execute(f'PRAGMA recursive_triggers={recursive}')
                    for index, sql in enumerate(attacks):
                        with self.subTest(foreign_keys=foreign_keys,recursive=recursive,attack=index):
                            with self.assertRaisesRegex(sqlite3.IntegrityError,'Legacy .* identity is immutable'):
                                db.execute(sql)
                            self.assertEqual(snapshot(db),baseline)
                            self.assertEqual(db.execute(CONFLICTS).fetchall(),[])
                    with self.assertRaises(sqlite3.IntegrityError):
                        with db:
                            db.execute('BEGIN IMMEDIATE')
                            db.execute("UPDATE assessments SET status='cancelled' WHERE id='donor'")
                            db.execute(AUDITOR_REPLACEMENTS[0])
                    self.assertEqual(snapshot(db),baseline)
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA recursive_triggers=OFF')
            statements = (
                ("Legacy assessment", """INSERT OR REPLACE INTO assessments(rowid,id,curriculum_id,group_id,status)
                    VALUES (50,'first','language','g-b','scheduled'),(-1,'unused','language','g-a','scheduled')"""),
                ("Legacy assignment", """INSERT OR REPLACE INTO student_assessments(rowid,id,student_id,assessment_id)
                    VALUES (50,'first','s07','donor'),(-1,'unused','s03','donor')"""),
            )
            for kind, sql in statements:
                with self.subTest(statement=kind):
                    db.execute('BEGIN IMMEDIATE')
                    db.execute('PRAGMA defer_foreign_keys=ON')
                    try:
                        with self.assertRaisesRegex(sqlite3.IntegrityError,kind+' identity is immutable'):
                            db.execute(sql)
                        self.assertEqual(snapshot(db),baseline)
                    finally:
                        db.rollback()
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))

    def test_legacy_creation_metadata_changes_and_retake_still_work(self):
        path = self.copy()
        update(path,backup=path.with_name('before-0013.sqlite3'))
        with closing(sqlite3.connect(path,isolation_level=None)) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute("UPDATE assessments SET rowid=-1 WHERE id='prior-exam'")
            db.execute("UPDATE student_assessments SET rowid=-1 WHERE id='prior-s02'")
            for recursive, student in ((0,'s04'),(1,'s06')):
                db.execute(f'PRAGMA recursive_triggers={recursive}')
                group = 'g-a' if recursive==0 else 'g-b'
                db.execute("INSERT INTO assessments VALUES (?,'language',?,NULL,NULL,'scheduled')",
                           (student,group))
                db.execute("INSERT INTO student_assessments VALUES (?,?,'prior-exam')",(student,student))
                db.execute("INSERT OR REPLACE INTO student_assessments VALUES (?,?,'prior-exam')",(student,student))
                db.execute("""INSERT INTO assessment_attempts
                    SELECT ?,?,1,'graded',2,performed_on,recorded_at FROM assessment_attempts WHERE assignment_id='prior-s02'""",
                    (student,student))
            db.execute("UPDATE assessments SET deadline_on=scheduled_on WHERE id='prior-exam'")
            db.execute(APPEND_RETAKE)
            self.assertEqual(db.execute("""SELECT grade FROM assessment_attempts
                WHERE assignment_id='prior-s02' ORDER BY number""").fetchall(),[(2,),(4,)])
            self.assertEqual(db.execute(CONFLICTS).fetchall(),[])
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
