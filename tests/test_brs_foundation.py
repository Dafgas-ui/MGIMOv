import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
import secrets
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.auth.service import digest
from backend.brs.service import set_capability
from backend.config import ROOT, Settings
from backend.db import connection
from backend.migrations.manager import DIRECTORY, status, update
from backend.schedule.service import MOSCOW, change_in_transaction
from tests.test_foundation import temporary

ADMIN = "/api/v1/staff/brs/admin"
STAFF = "/api/v1/staff/brs"


class BRSFoundationTests(unittest.TestCase):
    def setUp(self):
        self.initialize(self.enterContext(temporary()))

    def initialize(self, folder, definitions=DIRECTORY):
        self.settings = Settings(folder / "brs.sqlite3")
        update(self.settings.database, create=True, directory=definitions)
        self.now = int(datetime(2027, 2, 20, 12, tzinfo=MOSCOW).timestamp())
        self.app = create_app(self.settings)
        self.app.state.auth_service.clock = lambda: self.now
        self.clients = {}
        with connection(self.settings, write=True) as db:
            for sql, rows in [
                ("INSERT INTO faculties VALUES (?,?)", [("f","Faculty"),("x","Other")]),
                ("INSERT INTO programs VALUES (?,?,?)", [("p","f","Program"),("q","x","Other")]),
                ("INSERT INTO study_groups VALUES (?,?,?,1)", [("a","p","A"),("b","p","B"),("x","q","X")]),
                ("INSERT INTO semesters VALUES (?,?,?,?)", [("s","Spring","2027-02-01","2027-06-30"),("old","Fall","2026-09-01","2026-12-30")]),
                ("INSERT INTO subjects VALUES (?,?)", [("math","Math"),("law","Law")]),
                ("INSERT INTO curriculum_items VALUES (?,?,?,?,'exam',1)",
                 [("math-s","p","math","s"),("law-s","p","law","s"),("math-x","q","math","s"),("math-old","p","math","old")]),
                ("INSERT INTO teachers VALUES (?,?)", [("t","Teacher"),("t2","Second")]),
            ]:
                db.executemany(sql, rows)
            db.execute("INSERT INTO buildings VALUES ('building','Building')")
            db.execute("INSERT INTO rooms VALUES ('room','building','1',20,'')")
            for index, (key, group, subject, teacher, day) in enumerate([
                ("l","a","math","t","2027-03-01"),("lb","b","math","t2","2027-03-01"),
                ("ll","a","law","t","2027-03-01"),("lx","x","math","t","2027-03-01"),
                ("lo","a","math","t","2026-11-01"),
            ]):
                start = 540 + index*90
                db.execute("INSERT INTO lessons VALUES (?,?,?,?,?,?,?,?,'lecture','scheduled',1,?)",
                           (key, group, subject, teacher, "room", day, start, start+60, self.now))
            for who in ("admin", "teacher", "second", "outside", "alice", "bobby"):
                role = "student" if who in ("alice", "bobby") else "staff"
                db.execute("INSERT INTO users VALUES (?,?,?, ?,1,?)", (who, who, "$argon2id$fixture", role, self.now))
                if role == "student":
                    db.execute("INSERT INTO student_profiles VALUES (?,?,?)", (who, who, "a"))
                else:
                    db.execute("INSERT INTO staff_profiles VALUES (?,?,?)", (who, who, role))
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,NULL)",
                           (who, who, digest(token), digest(csrf), self.now, self.now+3600))
                client = self.enterContext(TestClient(self.app, base_url=self.settings.origin))
                client.cookies.set(self.settings.session_cookie, token)
                client.cookies.set(self.settings.csrf_cookie, csrf)
                self.clients[who] = client
            for capability in ("manage_plans", "manage_teaching", "manage_enrollments"):
                set_capability(db, "admin", self.now, "admin", "f", capability, enabled=True)
            set_capability(db, "admin", self.now, "outside", "x", "manage_teaching", enabled=True)
            db.execute("INSERT INTO request_staff_scopes VALUES ('teacher','f')")

    def post(self, path, body, who="admin", **headers):
        client = self.clients[who]
        return client.post(path, json=body, headers={
            "Origin": self.settings.origin, "X-CSRF-Token": client.cookies.get(self.settings.csrf_cookie),
            **headers,
        })

    def created(self, path, body):
        response = self.post(path, body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def plan(self, curriculum="math-s"):
        return {
            "curriculum_id": curriculum, "source": "Faculty record #1",
            "approved_on": "2026-08-20" if curriculum == "math-old" else "2027-01-20",
            "rounding": "half_up", "admission_min": 41,
            "categories": [{"code":"all","title":"Coursework","maximum":100}],
            "events": [{"code":"e","category_code":"all","title":"Assignment","maximum":100,
                        "attempt_limit":2,"retake_policy":"highest",
                        "retake_until":"2026-12-10" if curriculum == "math-old" else "2027-06-20"}],
            "scale": [{"minimum":value,"outcome":str(outcome)}
                      for value,outcome in [(0,2),(60,3),(78,4),(91,5)]],
        }

    def locked(self, body=None):
        key = self.created(ADMIN+"/plans", body or self.plan())
        self.assertEqual(self.post(f"{ADMIN}/plans/{key}/lock", {}).status_code, 200)
        return key

    def flow(self, plan, group="a"):
        return self.created(ADMIN+"/offerings", {"plan_id":plan,"group_id":group})

    def seed_legacy_course(self):
        """Seed the pre-0011 schema without using today's API or score models."""
        with connection(self.settings, write=True) as db:
            db.execute("""INSERT INTO brs_plans VALUES
                ('old-plan','math-s','Fixture','2027-01-20','exact',5000,NULL,NULL)""")
            db.execute("INSERT INTO brs_categories VALUES ('old-plan','all','Coursework',10000,5000)")
            db.execute("""INSERT INTO brs_events VALUES
                ('old-plan','e','all','Assignment',10000,NULL,2,'highest','2027-06-20')""")
            db.executemany("INSERT INTO brs_scale VALUES ('old-plan',?,?)",
                           [(0,"2"),(5000,"3"),(7500,"4"),(9000,"5")])
            db.execute("UPDATE brs_plans SET locked_at=?,locked_by='admin' WHERE id='old-plan'", (self.now,))
            db.execute("INSERT INTO brs_offerings VALUES ('old-flow','old-plan','a')")
            db.execute("INSERT INTO brs_student_courses VALUES ('old-course','alice','math-s')")
            db.execute("""INSERT INTO brs_enrollments VALUES
                ('old-enrollment','old-course','old-flow','2027-02-01',NULL,NULL,'Fixture')""")
            db.execute("INSERT INTO brs_teacher_accounts VALUES ('teacher','t')")
            db.execute("""INSERT INTO brs_teaching_grants VALUES
                ('old-grant','old-flow','teacher','l',1,'admin',1,NULL,?,?,NULL)""",
                (self.now, self.now+60))
        return {"id":"old-enrollment","course_id":"old-course"}

    def bind(self, staff="teacher", teacher="t", lesson="l"):
        return self.post(ADMIN+"/teacher-accounts", {"staff_id":staff,"teacher_id":teacher,"lesson_id":lesson})

    def grant(self, flow, staff="teacher", lesson="l", who="admin", version=1):
        return self.post(f"{ADMIN}/offerings/{flow}/grants",
                         {"staff_id":staff,"lesson_id":lesson,"lesson_version":version,
                          "expires_at":self.now+60,"can_confirm_final":True}, who)

    def count(self, table):
        with connection(self.settings) as db:
            return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def test_validation_rejects_bad_maxima_scale_dates_and_retakes(self):
        for change in (
            lambda p:p["categories"][0].update(maximum=99),
            lambda p:p["events"][0].update(maximum=99),
            lambda p:p["events"][0].update(maximum=99, admission_min=100),
            lambda p:p["scale"][0].update(minimum=1),
            lambda p:p["scale"][1].update(minimum=0),
            lambda p:p["events"][0].update(retake_policy="none"),
            lambda p:p["events"][0].update(retake_until="2027-02-30"),
            lambda p:p.update(approved_on="2027-02-01"),
        ):
            plan = self.plan()
            change(plan)
            self.assertEqual(self.post(ADMIN+"/plans", plan).status_code, 422)
        self.assertEqual(self.count("brs_whole_plans"), 0)

    def test_plan_immutable_in_sql_and_http(self):
        key = self.locked()
        draft = self.created(ADMIN+"/plans", self.plan())
        self.assertEqual(self.post(f"{ADMIN}/plans/{key}/lock", {}).status_code, 409)
        self.assertEqual(self.clients["admin"].patch(f"{ADMIN}/plans/{key}", json={},
                         headers={"Origin":self.settings.origin}).status_code, 404)
        commands = [
            ("UPDATE brs_whole_plans SET admission_min=1 WHERE id=?", (key,)),
            ("DELETE FROM brs_whole_plans WHERE id=?", (key,)),
            ("INSERT OR REPLACE INTO brs_whole_plans SELECT id,curriculum_id,source,approved_on,rounding,admission_min,NULL,NULL FROM brs_whole_plans WHERE id=?", (key,)),
            ("UPDATE OR REPLACE brs_whole_plans SET id=? WHERE id=?", (key,draft)),
            ("INSERT INTO brs_events SELECT plan_id,'new',category_code,title,maximum,admission_min,attempt_limit,retake_policy,retake_until FROM brs_events WHERE plan_id=?", (key,)),
            ("UPDATE brs_events SET maximum=1 WHERE plan_id=?", (key,)),
            ("DELETE FROM brs_events WHERE plan_id=?", (key,)),
            ("UPDATE OR REPLACE brs_events SET plan_id=? WHERE plan_id=?", (key,draft)),
            ("UPDATE brs_events SET plan_id=? WHERE plan_id=?", (draft,key)),
            ("UPDATE brs_categories SET title='Changed' WHERE plan_id=?", (key,)),
            ("DELETE FROM brs_scale WHERE plan_id=?", (key,)),
        ]
        with connection(self.settings, write=True) as db:
            for sql, args in commands:
                with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "Locked BRS plan|new draft"):
                    db.execute(sql, args)

    def test_scope_schedule_edit_self_approval_expiry_and_revocation(self):
        plan = self.locked()
        flow = self.flow(plan)
        wrong_group = self.flow(plan, "b")
        wrong_subject = self.flow(self.locked(self.plan("law-s")))
        wrong_semester = self.flow(self.locked(self.plan("math-old")))
        access = f"{STAFF}/offerings/{flow}/access"
        self.assertEqual(self.bind().status_code, 201)
        with connection(self.settings) as db:
            row = db.execute("SELECT * FROM lessons WHERE id='l'").fetchone()
        edit = {k:row[k] for k in ("date","start_minute","end_minute","teacher_id","room_id","status","version")}
        edit.update(start_minute=550, reason="Staff schedule edit")
        self.assertEqual(self.post("/api/v1/staff/lessons/l", edit, "teacher").status_code, 200)
        self.assertEqual(self.clients["teacher"].get(access).status_code, 404)
        self.assertEqual(self.grant(flow, who="teacher", version=2).status_code, 404)
        with connection(self.settings, write=True) as db:
            set_capability(db,"admin",self.now,"teacher","f","manage_teaching",enabled=True)
        self.assertEqual(self.grant(flow, who="teacher", version=2).status_code, 403)
        self.assertEqual(self.grant(flow, who="outside", version=2).status_code, 404)
        for invalid in (wrong_group, wrong_subject, wrong_semester):
            self.assertEqual(self.grant(invalid, version=2).status_code, 404)
        self.assertEqual(self.grant(flow).status_code, 409)
        result = self.grant(flow, version=2)
        self.assertEqual(result.status_code, 201, result.text)
        key = result.json()["id"]
        self.assertEqual(self.clients["teacher"].get(access).status_code, 200)
        for who in ("admin","second","outside"):
            self.assertEqual(self.clients[who].get(access).status_code, 404)
        self.assertEqual(self.post(f"{ADMIN}/grants/{key}/revoke", {}, "outside").status_code, 404)
        self.assertEqual(self.post(f"{ADMIN}/grants/{key}/revoke", {}).status_code, 200)
        self.assertEqual(self.clients["teacher"].get(access).status_code, 404)
        self.assertEqual(self.grant(flow, version=2).status_code, 201)
        self.now += 61
        self.assertEqual(self.clients["teacher"].get(access).status_code, 404)
        self.assertEqual(self.grant(flow, version=2).status_code, 201)
        self.assertEqual(self.clients["teacher"].get(access).status_code, 200)
        with connection(self.settings) as db:
            actions = [row[0] for row in db.execute("SELECT action FROM staff_audit")]
        self.assertEqual(actions.count("brs.grant.approve"), 3)
        self.assertEqual(actions.count("brs.grant.revoke"), 1)

    def test_replacement_invalidates_grant_even_if_original_teacher_returns(self):
        flow = self.flow(self.locked())
        self.assertEqual(self.bind().status_code, 201)
        self.assertEqual(self.grant(flow).status_code, 201)
        access = f"{STAFF}/offerings/{flow}/access"
        self.assertEqual(self.clients["teacher"].get(access).status_code, 200)
        with connection(self.settings, write=True) as db:
            change_in_transaction(db,"l",1,"Replacement",{"teacher_id":"t2"},self.now)
            change_in_transaction(db,"l",2,"Return",{"teacher_id":"t"},self.now+1)
        self.assertEqual(self.clients["teacher"].get(access).status_code, 404)

    def test_substitute_appointment_is_limited_to_approved_event(self):
        flow = self.flow(self.locked())
        student = self.created(f"{ADMIN}/offerings/{flow}/enrollments", {"student_id":"alice","starts_on":"2027-02-01"})
        self.assertEqual(self.bind("second","t2","lb").status_code, 201)
        with connection(self.settings, write=True) as db:
            change_in_transaction(db,"l",1,"Replacement",{"teacher_id":"t2"},self.now)
        self.assertEqual(self.grant(flow,"second","l",version=2).status_code, 422)
        path = f"{ADMIN}/offerings/{flow}/grants"
        body = {"staff_id":"second","lesson_id":"l","lesson_version":2,
                "expires_at":self.now+60,"can_confirm_final":True,"event_code":"e"}
        self.assertEqual(self.post(path,body).status_code, 422)
        body["can_confirm_final"] = False
        self.assertEqual(self.post(path,body).status_code, 201)
        access = f"{STAFF}/offerings/{flow}/enrollments/{student}"
        self.assertEqual(self.clients["second"].get(access+"/access").status_code, 404)
        self.assertEqual(self.clients["second"].get(access+"/events/e/access").status_code, 200)
        self.assertEqual(self.clients["second"].get(access+"/events/other/access").status_code, 404)

    def test_transfer_keeps_same_course_and_separates_teacher_access(self):
        plan = self.locked()
        old, new = self.flow(plan), self.flow(plan,"b")
        key = self.created(f"{ADMIN}/offerings/{old}/enrollments", {"student_id":"alice","starts_on":"2027-02-01"})
        with connection(self.settings, write=True) as db:
            db.execute("INSERT INTO assessments VALUES ('legacy','math-old','a','2026-11-01',NULL,'completed')")
            db.execute("INSERT INTO student_assessments VALUES ('legacy-alice','alice','legacy')")
            db.execute("INSERT INTO assessment_attempts VALUES ('attempt','legacy-alice',1,'graded',4,'2026-11-01',?)", (self.now,))
        self.assertEqual(self.bind().status_code, 201)
        self.assertEqual(self.bind("second","t2","lb").status_code, 201)
        self.assertEqual(self.grant(old).status_code, 201)
        self.assertEqual(self.grant(new,"second","lb").status_code, 201)
        path = f"{ADMIN}/enrollments/{key}/transfer"
        payload = {"target_offering_id":new,"starts_on":"2027-02-20","reason":"Transfer"}
        with patch("backend.brs.service.audit",side_effect=sqlite3.OperationalError("test rollback")):
            self.assertEqual(self.post(path,payload).status_code, 503)
        self.assertEqual(self.count("brs_enrollments"), 1)
        result = self.post(path,payload)
        self.assertEqual(result.status_code, 201, result.text)
        target = result.json()["id"]
        self.assertEqual(self.post(path,payload).status_code, 409)
        with connection(self.settings) as db:
            rows = [tuple(r) for r in db.execute(
                "SELECT course_id,starts_on,ends_on,previous_id FROM brs_enrollments ORDER BY starts_on")]
            identity = db.execute("SELECT student_id,curriculum_id FROM brs_student_courses WHERE id=?",
                                  (result.json()["course_id"],)).fetchone()
        self.assertEqual(tuple(identity), ("alice", "math-s"))
        self.assertEqual(rows, [(result.json()["course_id"],"2027-02-01","2027-02-20",None),
                                (result.json()["course_id"],"2027-02-20",None,key)])
        for enrollment in (key,target):
            path = f"/api/v1/me/brs/enrollments/{enrollment}/plan"
            self.assertEqual(self.clients["alice"].get(path).json()["id"], plan)
            self.assertEqual(self.clients["bobby"].get(path).status_code, 404)
        legacy = self.clients["alice"].get("/api/v1/me/gradebook").json()["semesters"][0]["items"][0]
        self.assertEqual(legacy["attempts"][0]["grade"], 4)
        for who, flow, enrollment, expected in [
            ("teacher",old,key,404),("teacher",new,target,404),
            ("second",new,key,404),("second",new,target,200),
        ]:
            self.assertEqual(self.clients[who].get(
                f"{STAFF}/offerings/{flow}/enrollments/{enrollment}/access").status_code, expected)

    def test_different_plan_requires_explicit_nonduplicating_mapping(self):
        old = self.flow(self.locked())
        body = copy.deepcopy(self.plan())
        body["events"][0]["code"] = "new"
        new = self.flow(self.locked(body),"b")
        key = self.created(f"{ADMIN}/offerings/{old}/enrollments", {"student_id":"alice","starts_on":"2027-02-01"})
        path = f"{ADMIN}/enrollments/{key}/transfer"
        payload = {"target_offering_id":new,"starts_on":"2027-02-20","reason":"Approved mapping"}
        self.assertEqual(self.post(path,payload).status_code, 422)
        payload["mapping"] = [{"old_event":"e","new_event":"new"}]*2
        self.assertEqual(self.post(path,payload).status_code, 422)
        payload["mapping"].pop()
        self.assertEqual(self.post(path,payload).status_code, 201)
        self.assertEqual(self.count("brs_transfer_events"), 1)

    def test_origin_csrf_role_and_concurrent_lock(self):
        path = ADMIN+"/plans"
        self.assertEqual(self.post(path,self.plan(),Origin="https://invalid.test").status_code, 403)
        self.assertEqual(self.post(path,self.plan(),**{"X-CSRF-Token":"invalid"}).status_code, 403)
        self.assertEqual(self.post(path,self.plan(),"alice").status_code, 403)
        self.assertEqual(self.post(path,self.plan(),"outside").status_code, 404)
        with TestClient(self.app,base_url=self.settings.origin) as anonymous:
            self.assertEqual(anonymous.post(path,json=self.plan(),headers={"Origin":self.settings.origin}).status_code,401)
        key = self.created(path,self.plan())
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(lambda _:self.post(f"{path}/{key}/lock",{}).status_code,range(2)))
        self.assertEqual(sorted(codes),[200,409])
        with connection(self.settings) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM staff_audit WHERE action='brs.plan.lock'").fetchone()[0],1)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")

    def test_migration_of_populated_v6_and_repeat(self):
        with temporary() as root:
            definitions = root/"v6"
            definitions.mkdir()
            for file in (ROOT/"backend/migrations").glob("000[1-6]_*.sql"):
                shutil.copyfile(file,definitions/file.name)
            database = root/"existing.sqlite3"
            update(database,create=True,directory=definitions)
            with connection(Settings(database),write=True) as db:
                db.execute("INSERT INTO faculties VALUES ('prior','Prior')")
            backup = root/"backup.sqlite3"
            self.assertEqual(update(database,backup=backup)["applied"][-1],"0014_legacy_attempt_history")
            self.assertEqual(update(database)["pending"],[])
            for target in (database,backup):
                with connection(Settings(target)) as db:
                    self.assertEqual(db.execute("SELECT name FROM faculties WHERE id='prior'").fetchone()[0],"Prior")
                    self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0],"ok")
                    self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])
            self.assertEqual(status(backup,directory=definitions)["applied"][-1],"0006_mvp")

    def enroll_alice(self):
        flow = self.flow(self.locked())
        path = f"{ADMIN}/offerings/{flow}/enrollments"
        body = {"student_id":"alice", "starts_on":"2027-02-01"}
        response = self.post(path, body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json(), path, body

    def assert_course_owner(self, enrollment):
        path = f"/api/v1/me/brs/enrollments/{enrollment['id']}/plan"
        self.assertEqual(self.clients["alice"].get(path).status_code, 200)
        self.assertEqual(self.clients["bobby"].get(path).status_code, 404)

    def test_course_identity_rejects_sql_mutations_and_preserves_api_ownership(self):
        enrollment, path, body = self.enroll_alice()
        key = enrollment["course_id"]
        self.assert_course_owner(enrollment)
        with connection(self.settings, write=True) as db:
            db.execute("PRAGMA recursive_triggers=OFF")
            queries = [
                ("UPDATE brs_student_courses SET student_id='bobby' WHERE student_id='alice'", ()),
                ("UPDATE brs_student_courses SET id='changed' WHERE id=?", (key,)),
                ("UPDATE OR REPLACE brs_student_courses SET rowid=rowid+100 WHERE id=?", (key,)),
                ("UPDATE OR REPLACE brs_student_courses SET curriculum_id='law-s' WHERE id=?", (key,)),
                ("INSERT OR REPLACE INTO brs_student_courses VALUES (?,'bobby','math-s')", (key,)),
                ("INSERT OR REPLACE INTO brs_student_courses VALUES ('replacement','alice','math-s')", ()),
                ("INSERT OR REPLACE INTO brs_student_courses(rowid,id,student_id,curriculum_id) SELECT rowid,'replacement','bobby','law-s' FROM brs_student_courses WHERE id=?", (key,)),
                ("INSERT OR IGNORE INTO brs_student_courses VALUES (?,'bobby','math-s')", (key,)),
                ("DELETE FROM brs_student_courses WHERE id=?", (key,)),
                ("INSERT INTO brs_student_courses VALUES (?,'bobby','law-s')", (key,)),
                ("INSERT OR REPLACE INTO brs_student_courses VALUES ('new-course','bobby','law-s'), (?,'bobby','math-s')", (key,)),
            ]
            for sql, args in queries:
                with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "course identity is immutable"):
                    db.execute(sql, args)
            for sql in ("DELETE FROM student_profiles WHERE user_id='alice'",
                        "UPDATE curriculum_items SET id='changed' WHERE id='math-s'",
                        "INSERT INTO brs_student_courses VALUES ('orphan','absent','math-s')"):
                with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "FOREIGN KEY"):
                    db.execute(sql)
            self.assertEqual([tuple(row) for row in db.execute("SELECT * FROM brs_student_courses")],
                             [(key, "alice", "math-s")])
            self.assertEqual([tuple(row) for row in db.execute("SELECT id,course_id FROM brs_enrollments")],
                             [(enrollment["id"], key)])
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.post(path, body).status_code, 409)
        self.assertEqual(self.post(path, {**body, "course_id":key, "student_id":"bobby"}).status_code, 422)
        self.assertEqual(self.count("brs_student_courses"), 1)
        self.assertEqual(self.count("brs_enrollments"), 1)
        self.assert_course_owner(enrollment)

    def test_upgrade_populated_v8_preserves_courses_enrollments_and_backup(self):
        root = self.enterContext(temporary())
        definitions = root / "v8"
        definitions.mkdir()
        for file in DIRECTORY.glob("000[1-8]_*.sql"):
            shutil.copyfile(file, definitions / file.name)
        self.initialize(root, definitions)
        enrollment = self.seed_legacy_course()
        with connection(self.settings, write=True) as db:
            db.execute("INSERT INTO brs_student_courses(rowid,id,student_id,curriculum_id) VALUES (-1,'negative','bobby','law-s')")

        def snapshot(settings):
            with connection(settings) as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
                return {table:[tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1")]
                        for table in ("brs_student_courses", "brs_enrollments", "staff_audit")}

        before = snapshot(self.settings)
        backup = root / "v8-backup.sqlite3"
        self.assertEqual(update(self.settings.database, backup=backup)["applied"][-1], "0014_legacy_attempt_history")
        self.assertEqual(update(self.settings.database)["pending"], [])
        self.assertEqual(status(backup, directory=definitions)["applied"][-1], "0008_brs_course_identity")
        self.assertEqual(snapshot(Settings(backup)), before)
        self.assertEqual(snapshot(self.settings), before)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "course identity is immutable"):
            with connection(self.settings, write=True) as db:
                db.execute("UPDATE brs_student_courses SET student_id='bobby' WHERE student_id='alice'")
        self.assert_course_owner(enrollment)
        law = self.flow(self.locked(self.plan("law-s")))
        response = self.post(f"{ADMIN}/offerings/{law}/enrollments",
                             {"student_id":"alice", "starts_on":"2027-02-01"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assert_course_owner(response.json())

    def test_negative_rowids_do_not_block_new_courses_or_allow_replacement(self):
        for recursive in ("OFF", "ON"):
            with self.subTest(recursive_triggers=recursive):
                self.initialize(self.enterContext(temporary()))
                with closing(sqlite3.connect(self.settings.database, isolation_level=None)) as db:
                    db.execute(f"PRAGMA recursive_triggers={recursive}")
                    # The trigger also protects ordinary SQL clients with FK enforcement off.
                    db.execute("PRAGMA foreign_keys=OFF")
                    db.execute("INSERT INTO brs_student_courses(rowid,id,student_id,curriculum_id) VALUES (-1,'negative','bobby','law-s')")
                    db.execute("INSERT INTO brs_student_courses(id,student_id,curriculum_id) VALUES ('legitimate','alice','law-s')")
                    self.assertEqual(db.execute("SELECT rowid FROM brs_student_courses WHERE id='negative'").fetchone(), (-1,))
                    self.assertNotEqual(db.execute("SELECT rowid FROM brs_student_courses WHERE id='legitimate'").fetchone(), (-1,))

                    def snapshot():
                        return tuple(db.execute("SELECT rowid,* FROM brs_student_courses ORDER BY id")), tuple(
                            db.execute("SELECT course_id FROM brs_course_insert_ledger ORDER BY course_id"))

                    before = snapshot()
                    for sql in (
                        "INSERT OR REPLACE INTO brs_student_courses(rowid,id,student_id,curriculum_id) VALUES (-1,'intruder','alice','math-s')",
                        "INSERT OR REPLACE INTO brs_student_courses VALUES ('legitimate','bobby','math-s')",
                        "INSERT OR REPLACE INTO brs_student_courses VALUES ('intruder','alice','law-s')",
                        "INSERT OR REPLACE INTO brs_student_courses(rowid,id,student_id,curriculum_id) VALUES (-20,'new-first','alice','math-s'),(-1,'intruder','bobby','math-s')",
                        "DELETE FROM brs_course_insert_ledger WHERE course_id='negative'",
                        "INSERT OR REPLACE INTO brs_course_insert_ledger VALUES ('negative')",
                        "INSERT INTO brs_course_insert_ledger VALUES ('invented')",
                    ):
                        with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "course identity is immutable"):
                            db.execute(sql)
                        self.assertEqual(snapshot(), before)
                    db.execute("INSERT INTO brs_student_courses(rowid,id,student_id,curriculum_id) VALUES (-20,'another','alice','math-s')")
                    db.execute("INSERT INTO brs_student_courses VALUES ('bulk-a','bobby','math-s'),('bulk-b','bobby','math-old')")
                    self.assertEqual(db.execute("SELECT count(*) FROM brs_course_insert_ledger").fetchone(), (5,))
                    db.execute("VACUUM")
                    db.execute("INSERT INTO brs_student_courses VALUES ('after-vacuum','alice','math-old')")
                    self.assertEqual(db.execute("PRAGMA integrity_check").fetchone(), ("ok",))
                    self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
