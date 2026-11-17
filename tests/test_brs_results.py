from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from backend.brs.results import payload_hash
from backend.db import connection
from backend.migrations.manager import DIRECTORY, MigrationError, status, update
from backend.schedule.service import MOSCOW
from tests import test_brs_foundation as foundation

ADMIN = foundation.ADMIN
STAFF = foundation.STAFF


class BRSResultsTests(unittest.TestCase):
    def setUp(self):
        self.case = foundation.BRSFoundationTests()
        self.addCleanup(self.case.doCleanups)

    def start(self, definitions=DIRECTORY):
        self.root = self.enterContext(foundation.temporary())
        self.case.initialize(self.root, definitions)

    def setup_course(self, policy="highest", deadline="2027-02-20", *, maximum=80):
        self.start()
        plan = self.case.plan()
        plan["events"][0].update(maximum=maximum, retake_policy=policy, retake_until=deadline)
        if maximum < 100:
            plan["events"].append({"code":"other","category_code":"all","title":"Other",
                                   "maximum":100-maximum,"attempt_limit":1,"retake_policy":"none"})
        self.plan = self.case.locked(plan)
        self.flow = self.case.flow(self.plan)
        enrollment = self.case.post(
            f"{ADMIN}/offerings/{self.flow}/enrollments", {"student_id":"alice","starts_on":"2027-02-01"})
        self.assertEqual(enrollment.status_code, 201, enrollment.text)
        self.enrollment = enrollment.json()["id"]
        self.course = enrollment.json()["course_id"]
        self.public = f"/api/v1/me/brs/courses/{self.course}/results"
        self.path = f"{STAFF}/offerings/{self.flow}/enrollments/{self.enrollment}/events/e"
        self.assertEqual(self.case.bind().status_code, 201)
        grant = self.case.grant(self.flow)
        self.assertEqual(grant.status_code, 201, grant.text)
        self.grant = grant.json()["id"]

    def command(self, suffix, body=None, who="teacher", path=None):
        return self.case.post((path or self.path) + suffix, body or {}, who)

    def draft(self, points, attempt=1, version=0, path=None):
        client = self.case.clients["teacher"]
        return client.put((path or self.path)+f"/attempts/{attempt}/draft",
                          json={"points":points,"expected_draft_version":version},
                          headers={"Origin":self.case.settings.origin,
                                   "X-CSRF-Token":client.cookies.get(self.case.settings.csrf_cookie)})

    def publish(self, attempt=1, draft=1, result=0, key="pub"):
        return self.command(f"/attempts/{attempt}/publish",
                            {"request_key":key,"expected_draft_version":draft,"expected_result_version":result})

    def results(self):
        response = self.case.clients["alice"].get(self.public)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def first_event(self):
        return self.results()["plans"][0]["events"][0]

    def test_coursework_blocks_brs_publication_and_direct_insert_in_its_scope(self):
        from backend.coursework import create_draft, execute

        self.setup_course()
        case = self.case
        teacher = dict(id='teacher', role='staff')
        self.assertEqual(self.draft(12).status_code, 200)
        with connection(case.settings, write=True) as db:
            assignment = create_draft(db, teacher, case.now, self.flow, kind='lab', title='Lab',
                                      description='Synthetic task', due_at=case.now+10, mode='both')
            execute(db, teacher, case.now, assignment, 'publish', expected_version=1,
                    request_key='coursework-first', data={'event_code': 'e'})
        before = self.results()
        response = self.publish()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(set(response.json()), {'detail'})
        self.assertEqual(self.results(), before)
        for table in ('brs_event_results', 'brs_attempt_versions', 'brs_operation_receipts'):
            self.assertEqual(case.count(table), 0)
        self.assertEqual(case.count('brs_attempt_drafts'), 1)
        with connection(case.settings, write=True) as db:
            db.execute('SAVEPOINT direct_probe')
            db.execute("INSERT INTO brs_event_results VALUES ('probe',?,?,'e')", (self.course, self.plan))
            for recursive in ('OFF', 'ON'):
                db.execute('PRAGMA recursive_triggers=' + recursive)
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'Coursework owns'):
                    db.execute("""INSERT INTO brs_attempt_versions
                        VALUES ('probe-version','probe',?,1,1,1,12,'teacher',?,NULL)""",
                               (self.enrollment, case.now))
            db.execute('ROLLBACK TO direct_probe')
            db.execute('RELEASE direct_probe')
        target = case.flow(self.plan, 'b')
        with connection(case.settings, write=True) as db:
            db.execute("UPDATE lessons SET teacher_id='t' WHERE id='lb'")
        self.assertEqual(case.grant(target, lesson='lb').status_code, 201)
        moved = self.transfer(target)
        self.assertEqual(moved.status_code, 201, moved.text)
        enrollment = moved.json()['id']
        path = f"{STAFF}/offerings/{target}/enrollments/{enrollment}/events/e"
        self.assertEqual(self.draft(12, path=path).status_code, 200)
        published = self.command('/attempts/1/publish',
                                 {'request_key':'other-flow','expected_draft_version':1,
                                  'expected_result_version':0}, path=path)
        self.assertEqual(published.status_code, 200, published.text)
        old_plan = case.locked(case.plan('math-old'))
        old_flow = case.flow(old_plan)
        prior = case.post(f'{ADMIN}/offerings/{old_flow}/enrollments',
                          {'student_id':'alice','starts_on':'2026-09-01'})
        self.assertEqual(prior.status_code, 201, prior.text)
        with connection(case.settings, write=True) as db:
            db.execute("INSERT INTO brs_event_results VALUES ('prior',?,?,'e')",
                       (prior.json()['course_id'], old_plan))
            db.execute("""INSERT INTO brs_attempt_versions
                VALUES ('prior-version','prior',?,1,1,1,12,'teacher',?,NULL)""",
                       (prior.json()['id'], case.now))

    def test_draft_invisible_publish_zero_and_correction_history(self):
        self.setup_course()
        legacy_before = self.case.clients["alice"].get("/api/v1/me/gradebook").json()
        before = self.results()
        self.assertIsNone(before["plans"][0]["events"][0]["effective_points"])
        self.assertEqual(self.draft(81).status_code, 422)
        self.assertEqual(self.draft(1).status_code, 200)
        self.assertEqual(self.draft(0,version=1).status_code, 200)
        self.assertEqual(self.draft(5,version=1).status_code, 409)
        self.assertEqual(self.results(), before)
        staff = self.case.clients["teacher"].get(self.path+"/result").json()
        self.assertEqual(staff["draft"]["points"], 0)
        self.assertEqual(self.publish().status_code, 409)
        publication = self.publish(draft=2)
        self.assertEqual(publication.status_code, 200, publication.text)
        self.assertEqual(self.publish(draft=2).json(), publication.json())
        self.assertEqual(self.publish(draft=1).status_code, 409)
        self.assertEqual(self.first_event()["effective_points"], 0)
        self.assertEqual(self.case.count("brs_attempt_drafts"), 0)
        result = publication.json()["result_id"]
        history = f"{self.public}/{result}/history"
        self.assertEqual(self.case.clients["bobby"].get(history).status_code, 404)
        self.assertEqual(self.case.clients["bobby"].get(self.public).status_code, 404)
        body = {"points":7,"reason":"Verified work","expected_result_version":1,"request_key":"cor"}
        self.assertEqual(self.command("/attempts/1/correct",{**body,"reason":"  "}).status_code, 422)
        corrected = self.command("/attempts/1/correct",body)
        self.assertEqual(corrected.status_code, 200, corrected.text)
        self.assertEqual(self.command("/attempts/1/correct",body).json(), corrected.json())
        rows = self.case.clients["alice"].get(history).json()["history"]
        self.assertEqual([(x["state"], x["old_points"], x["points"]) for x in rows],
                         [("published",None,0),("corrected",0,7)])
        self.assertEqual((rows[1]["reason"], rows[1]["author"], rows[1]["attempt_no"]), ("Verified work","teacher",1))
        self.assertEqual(self.first_event()["effective_points"], 7)
        self.assertEqual(self.case.clients["alice"].get("/api/v1/me/gradebook").json(), legacy_before)

    def test_retakes_latest_and_highest_use_server_registration_not_publication(self):
        for policy, expected in (("latest",2),("highest",3)):
            with self.subTest(policy=policy):
                self.setup_course(policy)
                self.assertEqual(self.draft(3).status_code, 200)
                self.assertEqual(self.publish().status_code, 200)
                self.assertEqual(self.draft(2,2).status_code, 422)
                cutoff = int(datetime(2027,2,20,23,59,55,tzinfo=MOSCOW).timestamp())
                with connection(self.case.settings,write=True) as db:
                    db.execute("UPDATE sessions SET expires_at=?", (cutoff+120,))
                    db.execute("UPDATE brs_whole_teaching_grants SET expires_at=? WHERE id=?", (cutoff+120,self.grant))
                self.case.now = cutoff
                self.assertEqual(self.command("/attempts/2/submission",{"registered_at":1}).status_code,422)
                receipt = self.command("/attempts/2/submission")
                self.assertEqual(receipt.status_code,200,receipt.text)
                self.assertEqual(receipt.json()["registered_at"], cutoff)
                self.assertFalse(receipt.json()["independently_verified"])
                self.case.now += 10
                self.assertEqual(self.draft(2,2).status_code, 200)
                publication = self.publish(2,result=1,key="retake")
                self.assertEqual(publication.status_code, 200, publication.text)
                result_id = publication.json()["result_id"]
                history = self.case.clients["alice"].get(f"{self.public}/{result_id}/history").json()["history"]
                self.assertEqual(history[-1]["published_at"], cutoff+10)
                self.assertEqual(history[-1]["submission"], {
                    "registered_at":cutoff, "source":"teacher_registered", "independently_verified":False,
                })
                self.assertEqual(self.first_event()["effective_points"], expected)
                self.assertEqual(self.draft(5,3).status_code, 422)
                correction = {"points":3,"reason":"Retake rechecked","expected_result_version":2,"request_key":"tie"}
                self.assertEqual(self.command("/attempts/2/correct",correction).status_code,200)
                self.assertEqual(self.first_event()["effective_attempt"], 1 if policy=="highest" else 2)

    def test_late_registration_and_event_without_retake(self):
        self.setup_course()
        self.assertEqual(self.draft(3).status_code,200)
        self.assertEqual(self.publish().status_code,200)
        self.case.now = int(datetime(2027,2,21,0,0,tzinfo=MOSCOW).timestamp())
        with connection(self.case.settings,write=True) as db:
            db.execute("UPDATE sessions SET expires_at=?", (self.case.now+60,))
            db.execute("UPDATE brs_whole_teaching_grants SET expires_at=?", (self.case.now+60,))
        self.assertEqual(self.command("/attempts/2/submission").status_code,422)
        self.assertEqual(self.command("/attempts/2/submission",{"date":"2027-02-20"}).status_code,422)
        self.assertEqual(self.draft(2,2).status_code,422)
        self.assertEqual(self.command("/attempts/2/submission",path=self.path[:-1]+"other").status_code,422)
        self.assertEqual(self.case.count("brs_attempt_submissions"),0)

    def test_authorization_expiry_origin_csrf_scope_and_replay(self):
        self.setup_course()
        self.assertEqual(self.case.clients["admin"].get(self.path+"/result").status_code,404)
        self.assertEqual(self.case.clients["outside"].get(self.path+"/result").status_code,404)
        self.assertEqual(self.case.clients["alice"].get(self.path+"/result").status_code,403)
        for path in (self.path[:-1]+"unknown", self.path.replace(self.enrollment,"unknown"),
                     self.path.replace(self.flow,"unknown")):
            self.assertEqual(self.case.clients["teacher"].get(path+"/result").status_code,404)
        other = self.case.flow(self.case.locked(self.case.plan("law-s")))
        self.assertEqual(self.case.clients["teacher"].get(self.path.replace(self.flow,other)+"/result").status_code,404)
        body = {"request_key":"pub","expected_result_version":0,"expected_draft_version":1}
        self.assertEqual(self.draft(1).status_code,200)
        self.assertEqual(self.case.post(self.path+"/attempts/1/publish",body,"outside").status_code,404)
        self.assertEqual(self.case.post(self.path+"/attempts/1/publish",body,"teacher",Origin="https://invalid.test").status_code,403)
        self.assertEqual(self.case.post(self.path+"/attempts/1/publish",body,"teacher",**{"X-CSRF-Token":"bad"}).status_code,403)
        self.assertEqual(self.publish().status_code,200)
        self.case.now += 60
        self.assertEqual(self.publish().status_code,404)
        self.case.now -= 60
        self.assertEqual(self.case.post(f"{ADMIN}/grants/{self.grant}/revoke",{}).status_code,200)
        self.assertEqual(self.publish().status_code,404)
        self.assertEqual(self.case.count("brs_attempt_versions"),1)

    def test_concurrent_draft_publish_and_atomic_failures(self):
        self.setup_course()
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = sorted(pool.map(lambda n:self.draft(n).status_code,(1,2)))
        self.assertEqual(codes,[200,409])
        for target in ("audit","save_receipt"):
            with patch("backend.brs.results."+target, side_effect=sqlite3.OperationalError("simulated failure")):
                self.assertEqual(self.publish().status_code,503)
            self.assertEqual(self.case.count("brs_attempt_drafts"),1)
            for table in ("brs_event_results","brs_attempt_versions","brs_operation_receipts"):
                self.assertEqual(self.case.count(table),0)
            with connection(self.case.settings) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM staff_audit WHERE action='brs.attempt.publish'").fetchone()[0],0)
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = sorted(pool.map(lambda key:self.publish(key=key).status_code,("one","two")))
        self.assertEqual(codes,[200,409])
        self.assertEqual(self.case.count("brs_attempt_versions"),1)
        self.assertEqual(self.case.count("brs_operation_receipts"),1)

    def test_silently_missing_audit_rolls_back_publish_and_correction(self):
        self.setup_course()
        self.assertEqual(self.draft(5).status_code, 200)
        correct = {"expected_result_version":1, "request_key":"correction", "points":6, "reason":"Correction"}
        for action, command, previous_count in (
            ('publish', self.publish, 0),
            ('correct', lambda: self.command('/attempts/1/correct', correct), 1),
        ):
            with self.subTest(action=action):
                with connection(self.case.settings, write=True) as db:
                    db.execute("""CREATE TRIGGER simulate_missing_audit BEFORE INSERT ON staff_audit
                        WHEN NEW.action LIKE 'brs.attempt.%' BEGIN SELECT RAISE(IGNORE); END""")
                self.assertEqual(command().status_code, 503)
                for table in ('brs_attempt_versions', 'brs_operation_receipts'):
                    self.assertEqual(self.case.count(table), previous_count)
                self.assertEqual(self.case.count('brs_attempt_drafts'), int(action == 'publish'))
                with connection(self.case.settings, write=True) as db:
                    self.assertIsNone(db.execute('SELECT 1 FROM staff_audit WHERE action=?',
                                                 ('brs.attempt.' + action,)).fetchone())
                    db.execute('DROP TRIGGER simulate_missing_audit')
                self.assertEqual(command().status_code, 200)

    def transfer(self, target, mapping=None):
        body = {"target_offering_id":target,"starts_on":"2027-02-20","reason":"Approved"}
        if mapping:
            body["mapping"] = mapping
        return self.case.post(f"{ADMIN}/enrollments/{self.enrollment}/transfer",body)

    def test_transfer_preserves_same_plan_and_separates_different_plans(self):
        for same in (True,False):
            with self.subTest(same_plan=same):
                self.setup_course()
                self.assertEqual(self.draft(25).status_code,200)
                self.assertEqual(self.publish().status_code,200)
                self.assertEqual(self.command("/attempts/2/submission").status_code,200)
                self.assertEqual(self.draft(15,2).status_code,200)
                plan = self.plan
                if not same:
                    body = self.case.plan()
                    body["events"] = [{"code":code,"category_code":"all","title":code,"maximum":maximum,
                                       "attempt_limit":1,"retake_policy":"none"} for code,maximum in (("new",80),("other",20))]
                    plan = self.case.locked(body)
                target = self.case.flow(plan,"b")
                moved = self.transfer(target,None if same else [{"old_event":"e","new_event":"new"},{"old_event":"other","new_event":"other"}])
                self.assertEqual(moved.status_code,201,moved.text)
                self.assertEqual(moved.json()["course_id"],self.course)
                self.assertEqual(self.publish().status_code,404)
                self.assertEqual(self.case.bind("second","t2","lb").status_code,201)
                self.assertEqual(self.case.grant(target,"second","lb").status_code,201)
                event = "e" if same else "new"
                path = f"{STAFF}/offerings/{target}/enrollments/{moved.json()['id']}/events/{event}"
                staff = self.case.clients["second"].get(path+"/result").json()
                self.assertIsNone(staff["draft"])
                self.assertIsNone(staff["submission"])
                body = {"points":5,"reason":"Recheck","expected_result_version":1,"request_key":"wrong"}
                self.assertEqual(self.command("/attempts/1/correct",body,"second",path).status_code,404)
                data = self.results()
                self.assertEqual(data["combined_points"],25 if same else None)
                self.assertEqual(sorted(x["published_points"] for x in data["plans"]),[25] if same else [0,25])

    def test_publish_races_with_transfer_and_revocation(self):
        for operation in ("transfer","revoke"):
            with self.subTest(operation=operation):
                self.setup_course()
                self.assertEqual(self.draft(25).status_code,200)
                if operation == "transfer":
                    target = self.case.flow(self.plan,"b")
                    change = lambda:self.transfer(target)
                    expected = 201
                else:
                    change = lambda:self.case.post(f"{ADMIN}/grants/{self.grant}/revoke",{})
                    expected = 200
                with ThreadPoolExecutor(max_workers=2) as pool:
                    publishing = pool.submit(self.publish)
                    changing = pool.submit(change)
                    self.assertEqual(changing.result().status_code,expected)
                    result = publishing.result()
                self.assertIn(result.status_code,(200,404))
                count = int(result.status_code==200)
                self.assertEqual(self.case.count("brs_attempt_versions"),count)
                self.assertEqual(self.case.count("brs_operation_receipts"),count)
                self.assertEqual(self.case.count("brs_attempt_drafts"),1-count)
                self.assertEqual(self.publish().status_code,404)

    def test_sql_history_and_identity_are_immutable(self):
        self.setup_course()
        self.assertEqual(self.draft(9).status_code,200)
        self.assertEqual(self.publish().status_code,200)
        with connection(self.case.settings,write=True) as db:
            for mode in ("OFF","ON"):
                db.execute(f"PRAGMA recursive_triggers={mode}")
                for sql in (
                    "UPDATE brs_attempt_versions SET points=0",
                    "DELETE FROM brs_attempt_versions",
                    "INSERT OR REPLACE INTO brs_attempt_versions SELECT * FROM brs_attempt_versions",
                    """INSERT OR REPLACE INTO brs_attempt_versions
                       SELECT 'new',result_id,enrollment_id,attempt_no,revision_no,result_version,0,actor_id,published_at,reason
                       FROM brs_attempt_versions""",
                    """INSERT INTO brs_attempt_versions SELECT 'bad',result_id,enrollment_id,attempt_no,2,2,90,actor_id,published_at,'bad score'
                       FROM brs_attempt_versions""",
                    "UPDATE brs_event_results SET plan_id='bad'",
                    "INSERT OR REPLACE INTO brs_event_results SELECT 'new',course_id,plan_id,event_code FROM brs_event_results",
                    "DELETE FROM brs_event_results",
                    "DELETE FROM brs_operation_receipts",
                ):
                    with self.subTest(sql=sql,recursive_triggers=mode),self.assertRaises(sqlite3.IntegrityError):
                        db.execute(sql)
                self.assertEqual(db.execute("SELECT points FROM brs_attempt_versions").fetchone()[0],9)
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])

    def test_migration_from_populated_0009_and_repeat(self):
        definitions = self.enterContext(foundation.temporary())
        for file in DIRECTORY.glob("000[1-9]_*.sql"):
            shutil.copyfile(file,definitions/file.name)
        self.start(definitions)
        self.case.seed_legacy_course()
        self.public = "/api/v1/me/brs/courses/old-course/results"
        def snapshot(settings, grants="brs_teaching_grants"):
            with connection(settings) as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])
                return {name:[tuple(row) for row in db.execute(f"SELECT * FROM {name} ORDER BY 1")]
                        for name in ("brs_student_courses","brs_course_insert_ledger","brs_enrollments",
                                     grants,"staff_audit","assessment_attempts")}
        before = snapshot(self.case.settings)
        backup = self.root/"before-0010.sqlite3"
        self.assertEqual(update(self.case.settings.database,backup=backup)["applied"][-1],"0023_coursework_brs_server_audit")
        self.assertEqual(update(self.case.settings.database)["pending"],[])
        self.assertEqual(status(backup,directory=definitions)["applied"][-1],"0009_brs_course_insert_guard")
        self.assertEqual(snapshot(type(self.case.settings)(backup)),before)
        after = snapshot(self.case.settings, "brs_whole_teaching_grants")
        after["brs_teaching_grants"] = after.pop("brs_whole_teaching_grants")
        self.assertEqual(after,before)
        self.assertIsNone(self.first_event()["effective_points"])

    def seed_0010_results(self, *, initial=700):
        definitions = self.enterContext(foundation.temporary())
        for file in sorted(DIRECTORY.glob("*.sql"))[:10]:
            shutil.copyfile(file, definitions / file.name)
        self.start(definitions)
        self.case.seed_legacy_course()
        self.public = "/api/v1/me/brs/courses/old-course/results"
        self.path = f"{STAFF}/offerings/old-flow/enrollments/old-enrollment/events/e"
        now = self.case.now
        correction = {"request_key":"legacy-correct","expected_result_version":1,
                      "points":4900,"reason":"Legacy correction"}
        publish = {"request_key":"legacy-publish","expected_result_version":0,"expected_draft_version":1}
        with connection(self.case.settings, write=True) as db:
            db.execute("INSERT INTO brs_event_results VALUES ('old-result','old-course','old-plan','e')")
            db.execute("""INSERT INTO brs_attempt_versions VALUES
                ('old-version','old-result','old-enrollment',1,1,1,?,'teacher',?,NULL)""", (initial, now))
            db.execute("""INSERT INTO brs_attempt_versions VALUES
                ('old-correction','old-result','old-enrollment',1,2,2,4900,'teacher',?,'Legacy correction')""",
                (now,))
            db.execute("""INSERT INTO brs_attempt_submissions VALUES
                ('old-enrollment','old-course','old-plan','e',2,?,'teacher')""", (now,))
            db.execute("""INSERT INTO brs_attempt_drafts VALUES
                ('old-enrollment','old-course','old-plan','e',2,5000,1,'teacher',?)""", (now,))
            db.execute("""INSERT INTO staff_audit VALUES
                ('old-audit','teacher','brs.attempt.correct','brs_attempt_version','old-correction',2,?)""", (now,))
            for action, payload, version in (("publish",publish,"old-version"),
                                             ("correct",correction,"old-correction")):
                fingerprint = payload_hash("old-flow","old-enrollment","e",1,payload)
                db.execute("INSERT INTO brs_operation_receipts VALUES ('teacher',?,?,?,?)",
                           (action,payload["request_key"],fingerprint,version))
        return definitions, {**correction,"points":49}, publish

    def test_populated_0010_preserves_results_receipts_draft_and_audit(self):
        _, correction, publish = self.seed_0010_results()
        database = self.case.settings.database
        backup = self.root / "before-0011.sqlite3"
        self.assertEqual(self.case.clients["alice"].get(self.public).status_code, 503)
        self.assertEqual(update(database,backup=backup)["applied"][-1],"0023_coursework_brs_server_audit")
        self.assertEqual(update(database)["pending"],[])
        with connection(self.case.settings,write=True) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])
            self.assertEqual(db.execute("""SELECT name FROM sqlite_schema WHERE name IN
                ('brs_plans','brs_teaching_grants','brs_teacher_accounts')""").fetchall(),[])
            self.assertEqual(db.execute("SELECT resource_id FROM staff_audit WHERE id='old-audit'").fetchone()[0],
                             "old-correction")
            self.assertEqual(db.execute("""SELECT hundredths FROM brs_points_archive
                WHERE source_table='brs_attempt_versions' AND source_key='["old-version"]'""").fetchone()[0],700)
            for sql in ("DELETE FROM brs_points_archive",
                        "INSERT OR REPLACE INTO brs_points_archive SELECT * FROM brs_points_archive"):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql)
        old = self.command("/attempts/1/publish",publish)
        self.assertEqual((old.status_code,old.json()["id"],old.json()["points"]),(200,"old-version",7))
        fixed = self.command("/attempts/1/correct",correction)
        self.assertEqual((fixed.status_code,fixed.json()["id"],fixed.json()["points"]),(200,"old-correction",49))
        self.assertEqual(self.command("/attempts/1/correct",{**correction,"points":50}).status_code,409)
        self.assertEqual(self.case.count("brs_attempt_versions"),2)
        retake = self.publish(2,result=2,key="retake-after-migration")
        self.assertEqual((retake.status_code,retake.json()["points"]),(200,50))
        history = self.case.clients["alice"].get(self.public+"/old-result/history").json()["history"]
        self.assertEqual([(x["old_points"],x["points"]) for x in history],[(None,7),(7,49),(None,50)])
        self.assertEqual(self.first_event()["effective_points"],50)

    def test_incompatible_source_blocks_migration_without_changes(self):
        for initial in (750,700):
            with self.subTest(initial=initial):
                definitions, _, _ = self.seed_0010_results(initial=initial)
                if initial == 700:
                    with connection(self.case.settings,write=True) as db:
                        db.execute("""INSERT INTO brs_plans VALUES
                            ('real-threshold','math-s','Fixture','2027-01-20','exact',7.5,NULL,NULL)""")
                database = self.case.settings.database
                before = database.read_bytes()
                backup = self.root / "rejected-0011.sqlite3"
                with self.assertRaisesRegex(MigrationError,"дробные или несовместимые данные БРС"):
                    update(database,backup=backup)
                self.assertEqual(database.read_bytes(),before)
                self.assertEqual(status(database,directory=definitions)["applied"][-1],"0010_brs_results")
                with connection(self.case.settings) as db:
                    self.assertEqual(db.execute(
                        "SELECT points FROM brs_attempt_versions WHERE id='old-version'").fetchone()[0],initial)
                    self.assertIsNone(db.execute(
                        "SELECT name FROM sqlite_schema WHERE name='brs_points_archive'").fetchone())

    def test_post_conversion_failure_rolls_back_schema_archive_and_data(self):
        definitions, _, _ = self.seed_0010_results()
        broken = definitions / "0011_brs_integer_points.sql"
        migration = (DIRECTORY / broken.name).read_bytes()
        broken.write_bytes(migration + b"\nINSERT INTO brs_points_archive VALUES ('fake','[]','points',700);\n")
        database = self.case.settings.database
        before = database.read_bytes()
        with self.assertRaises(MigrationError):
            update(database,backup=self.root / "rollback.sqlite3",directory=definitions)
        self.assertEqual(database.read_bytes(),before)
        with connection(self.case.settings) as db:
            self.assertEqual(db.execute("SELECT points FROM brs_attempt_versions WHERE id='old-version'").fetchone()[0],700)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])

    def test_whole_point_bounds_in_api_and_sql(self):
        self.setup_course(maximum=100)
        for invalid in (-1,101,7.5,7.0,"7",True,None):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.draft(invalid).status_code,422)
        self.assertIsNone(self.first_event()["effective_points"])
        self.assertEqual(self.draft(0).status_code,200)
        with connection(self.case.settings,write=True) as db:
            for value in (7.5,7.0,"7",101,-1):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("UPDATE brs_attempt_drafts SET points=?", (value,))
        self.assertEqual(self.publish().json()["points"],0)
        self.assertEqual(self.first_event()["effective_points"],0)
        for version, points in enumerate((7,49,50,100),start=1):
            payload = {"points":points,"request_key":f"bound-{points}","expected_result_version":version,
                       "reason":"Whole point boundary"}
            changed = self.command("/attempts/1/correct",payload)
            self.assertEqual((changed.status_code,changed.json()["points"]),(200,points))
            self.assertEqual(self.results()["combined_points"],points)
