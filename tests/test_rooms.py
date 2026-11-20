import shutil
import sqlite3
import unittest
from contextlib import closing
from datetime import datetime
from backend.db import connection
from backend.schedule.service import MOSCOW,change_in_transaction
from backend.academics import attestation
from backend.brs import service
from backend.migrations.manager import DIRECTORY,update,status,MigrationError
from tests import test_brs_foundation as base
from tests import forecast_fixture

PATH='/api/v1/me/rooms/availability'
class RoomTests(unittest.TestCase):
 def setUp(self):
  self.case=base.BRSFoundationTests();self.addCleanup(self.case.doCleanups);self.case.setUp()
  with connection(self.case.settings,write=True) as db:
   db.execute("INSERT INTO rooms VALUES ('second','building','2',30,'')")
   db.execute("INSERT INTO buildings VALUES ('unknown','Unknown building')")
   db.execute("INSERT INTO rooms VALUES ('third','unknown','3',70,'')")
   db.execute("INSERT INTO building_open_hours VALUES ('building',0,480,1080)")
 def query(self,who='alice',**kw):
  params=dict(date='2027-03-01',start='10:00',end='10:30');params.update(kw)
  return self.case.clients[who].get(PATH,params=params)
 def ids(self,**kw):
  response=self.query(**kw);self.assertEqual(response.status_code,200,response.text)
  return {r['id']:r['access_rules'] for r in response.json()['items']}
 def stamp(self,value):return int(datetime.fromisoformat(value).replace(tzinfo=MOSCOW).timestamp())
 def test_adjacent_overlap_multiple_groups_and_filters(self):
  self.assertEqual(self.ids(),{'room':'known','second':'known','third':'unknown'})
  self.assertNotIn('room',self.ids(start='09:59'))
  self.assertNotIn('room',self.ids(end='10:31'))
  self.assertNotIn('room',self.ids(start='10:30',end='11:00'))
  self.assertEqual(self.ids(capacity='50'),{'third':'unknown'})
  self.assertEqual(set(self.ids(building='building')),{'room','second'})
 def test_cancel_and_move_are_read_from_current_lesson(self):
  with connection(self.case.settings,write=True) as db:
   change_in_transaction(db,'l',1,'Synthetic cancel',{'status':'cancelled'},self.case.now)
  self.assertIn('room',self.ids(start='09:00',end='10:00'))
  with connection(self.case.settings,write=True) as db:
   change_in_transaction(db,'l',2,'Synthetic move',{'date':'2027-03-02','status':'scheduled'},self.case.now)
  self.assertIn('room',self.ids(start='09:00',end='10:00'))
  self.assertNotIn('room',self.ids(date='2027-03-02',start='09:00',end='10:00'))
 def test_known_closed_unknown_and_temporary_permanent_restrictions(self):
  self.assertEqual(self.ids(start='07:00',end='08:00'),{'third':'unknown'})
  self.assertEqual(self.ids(start='18:00',end='19:00'),{'third':'unknown'})
  with connection(self.case.settings,write=True) as db:
   db.execute("INSERT INTO building_open_hours VALUES ('building',1,NULL,NULL)")
   db.execute('INSERT INTO room_unavailability VALUES (?,?,?,?,?)',('temp','second',self.stamp('2027-03-01T10:30'),self.stamp('2027-03-01T11:00'),'Private closure reason'))
   db.execute('INSERT INTO room_unavailability VALUES (?,?,?,?,?)',('permanent','third',self.stamp('2027-03-01T00:00'),None,'Private reason'))
  self.assertEqual(self.ids(),{'room':'known','second':'known'})
  self.assertNotIn('second',self.ids(start='10:30',end='11:00'))
  self.assertEqual(self.ids(date='2027-03-02'),{})
  self.assertNotIn('third',self.ids(date='2027-03-10'))
 def test_exam_and_cancellation(self):
  courses=forecast_fixture.prepare(self.case);course=courses['exam']['course_id']
  with connection(self.case.settings,write=True) as db:
   db.executemany('INSERT INTO attestation_permissions VALUES (?,?,?)',[('admin','f','schedule'),('teacher','f','examiner')])
   attestation.activate(db,forecast_fixture.ADMIN,self.case.now,course)
   result=attestation.execute(db,forecast_fixture.ADMIN,self.case.now,course,'scheduled',dict(expected_version=0,request_key='room-exam-schedule',starts_at=self.stamp('2027-03-01T10:00'),ends_at=self.stamp('2027-03-01T10:30'),examiner_id='teacher',room_id='room',commission=[]))
  self.assertNotIn('room',self.ids())
  with connection(self.case.settings,write=True) as db:
   attestation.execute(db,forecast_fixture.ADMIN,self.case.now,course,'cancelled',dict(expected_version=1,request_key='room-exam-cancel',slot_id=result['slot_id'],reason='Synthetic cancellation'))
  self.assertIn('room',self.ids())
  with connection(self.case.settings,write=True) as db:
   attestation.execute(db,forecast_fixture.ADMIN,self.case.now,course,'scheduled',dict(expected_version=2,request_key='room-exam-move',starts_at=self.stamp('2027-03-01T10:00'),ends_at=self.stamp('2027-03-01T10:30'),examiner_id='teacher',room_id='second',commission=[]))
  self.assertIn('room',self.ids());self.assertNotIn('second',self.ids())
 def test_auth_privacy_invalid_filters_and_no_writes(self):
  with connection(self.case.settings) as db:before=list(db.iterdump())
  for who in ('alice','bobby','teacher'):
   response=self.query(who);self.assertEqual(response.status_code,200)
   for row in response.json()['items']:
    self.assertEqual(set(row),{'id','number','capacity','building_id','building','access_rules'})
  self.assertEqual(self.case.clients['alice'].get(PATH).status_code,422)
  for kw in ({'date':'2027-02-30'},{'start':'10:30'},{'end':'09:00'},{'start':'24:00'},{'capacity':'0'},{'capacity':'1.5'},{'building':'missing'},{'student_id':'bobby'}):
   self.assertEqual(self.query(**kw).status_code,422,kw)
  client=self.case.clients['bobby'];client.cookies.clear();self.assertEqual(self.query('bobby').status_code,401)
  with connection(self.case.settings) as db:self.assertEqual(list(db.iterdump()),before)
 def test_rule_constraints(self):
  with connection(self.case.settings,write=True) as db:
   for sql in ("INSERT INTO building_open_hours VALUES ('building',0,0,1440)","INSERT INTO building_open_hours VALUES ('building',9,0,1440)","INSERT INTO building_open_hours VALUES ('building',2,NULL,800)","INSERT INTO building_open_hours VALUES ('building',2,800,800)","INSERT INTO building_open_hours VALUES ('missing',2,0,1440)","INSERT INTO room_unavailability VALUES ('bad','room',10,10,'reason')","INSERT INTO room_unavailability VALUES ('bad','room',10,NULL,'   ')"):
    with self.assertRaises(sqlite3.IntegrityError,msg=sql):db.execute(sql)
 def prepare_0024(self):
  root=self.enterContext(base.temporary())
  prior=root/'through-0024';prior.mkdir()
  release=root/'through-0025';release.mkdir()
  files=sorted(p for p in DIRECTORY.glob('*.sql') if p.name[:4]<='0025')
  self.assertEqual(files[-1].stem,'0025_room_availability')
  self.assertEqual(len(files),25)
  for source in files:
   shutil.copyfile(source,release/source.name)
   if source.name[:4]<='0024':shutil.copyfile(source,prior/source.name)
  self.assertEqual(len(list(prior.glob('*.sql'))),24)
  path=root/'old.sqlite3'
  update(path,create=True,directory=prior)
  with closing(sqlite3.connect(path)) as db,db:
   db.execute("INSERT INTO buildings VALUES ('kept','Synthetic preserved')")
   db.execute("INSERT INTO rooms VALUES ('kept-room','kept','101',25,'Synthetic')")
  self.assertEqual(status(path,directory=release)['applied'][-1],'0024_attendance')
  self.assertEqual(status(path,directory=release)['pending'],['0025_room_availability'])
  return root,path,release
 def database_dump(self,path):
  with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
   self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(),[('ok',)])
   self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
   return list(db.iterdump())
 def test_upgrade_filled_0024_and_migrator_repeat(self):
  root,path,release=self.prepare_0024()
  before=self.database_dump(path);backup=root/'before.sqlite3'
  result=update(path,backup=backup,directory=release)
  self.assertEqual(result['applied'][-1],'0025_room_availability')
  self.assertEqual(len(result['applied']),25);self.assertEqual(result['pending'],[])
  self.assertTrue(backup.is_file())
  self.assertEqual(self.database_dump(backup),before)
  self.assertEqual(status(backup,directory=release)['pending'],['0025_room_availability'])
  with closing(sqlite3.connect(path)) as db:
   self.assertEqual(db.execute('SELECT * FROM buildings').fetchall(),[('kept','Synthetic preserved')])
   self.assertEqual(db.execute('SELECT * FROM rooms').fetchall(),[('kept-room','kept','101',25,'Synthetic')])
   self.assertEqual(db.execute("SELECT count(*) FROM schema_migrations WHERE id='0025_room_availability'").fetchone()[0],1)
   self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('building_open_hours','room_unavailability') ORDER BY name").fetchall(),[('building_open_hours',),('room_unavailability',)])
  after=self.database_dump(path);noop=root/'must-not-be-created.sqlite3'
  self.assertEqual(update(path,backup=noop,directory=release)['pending'],[])
  self.assertFalse(noop.exists());self.assertEqual(self.database_dump(path),after)
  self.assertEqual(self.database_dump(backup),before)
 def test_failed_0025_rolls_back_schema_data_and_history(self):
  root,path,release=self.prepare_0024()
  before=self.database_dump(path)
  broken=root/'broken';shutil.copytree(release,broken)
  migration=broken/'0025_room_availability.sql'
  migration.write_text(migration.read_text(encoding='utf-8')+'\nSELECT * FROM missing_room_table;\n',encoding='utf-8')
  backup=root/'before-failed.sqlite3'
  with self.assertRaisesRegex(MigrationError,'0025_room_availability') as error:
   update(path,backup=backup,directory=broken)
  self.assertIsInstance(error.exception.__cause__,sqlite3.OperationalError)
  self.assertTrue(backup.is_file());self.assertEqual(self.database_dump(backup),before)
  self.assertEqual(self.database_dump(path),before)
  self.assertEqual(status(path,directory=release)['pending'],['0025_room_availability'])
  with closing(sqlite3.connect(path)) as db:
   self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE name IN ('building_open_hours','room_unavailability','room_unavailability_interval')").fetchall(),[])
   self.assertEqual(db.execute("SELECT count(*) FROM schema_migrations WHERE id='0025_room_availability'").fetchone()[0],0)
  self.assertEqual(update(path,backup=root/'retry.sqlite3',directory=release)['pending'],[])
  self.database_dump(path)
