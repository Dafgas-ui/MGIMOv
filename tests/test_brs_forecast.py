import unittest
from unittest.mock import patch

from backend.academics import attestation
from backend.auth.service import AuthError
from backend.brs import service,results
from backend.db import connection
from tests import test_brs_foundation as foundation
from tests import forecast_fixture as fixture

PATH='/api/v1/me/brs/forecast'


class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.case=foundation.BRSFoundationTests()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.courses=fixture.prepare(self.case)

    def read(self,who='alice'):
        response=self.case.clients[who].get(PATH)
        self.assertEqual(response.status_code,200,response.text)
        return {row['control']:row for row in response.json()['items']}

    def test_boundaries_49_50_51_and_control_types(self):
        with connection(self.case.settings,write=True) as db:
            for value,grade in ((49,2),(50,3),(51,3),(64,3),(65,4),(79,4),(80,5),(100,5)):
                db.execute('SAVEPOINT score')
                for course in self.courses.values():fixture.total(db,self.case,course,value)
                from backend.academics.forecast import student_forecasts
                rows={x['control']:x for x in student_forecasts(db,{'id':'alice','role':'student'},self.case.now)['items']}
                self.assertEqual(rows['exam']['admission'],value>=50)
                self.assertIsNone(rows['exam']['predicted_result'])
                self.assertEqual(rows['credit']['predicted_result'],'pass' if value>=50 else 'fail')
                self.assertEqual(rows['graded_credit']['predicted_result'],grade)
                self.assertTrue(all(x['published_points']==value for x in rows.values()))
                self.assertTrue(all([c['maximum'] for c in x['categories']]==[20,20,20,40] for x in rows.values()))
                db.execute('ROLLBACK TO score');db.execute('RELEASE score')

    def test_http_empty_drafts_and_owner_isolation(self):
        first=self.read()
        self.assertTrue(all(x['published_points'] is None for x in first.values()))
        self.assertTrue(all(x['predicted_result'] is None for x in first.values()))
        self.assertEqual(self.read('bobby'),{})
        self.assertEqual(self.case.clients['teacher'].get(PATH).status_code,403)
        self.assertEqual(self.case.clients['alice'].get(PATH,headers={'X-Mgimov-User':'bobby'}).status_code,403)
        course=self.courses['exam']
        with connection(self.case.settings,write=True) as db:
            results.save_draft(db,fixture.TEACHER,self.case.now,course['offering'],course['id'],'c0',1,
                              {'points':20,'expected_draft_version':0})
        self.assertEqual(first,self.read())

    def test_http_published_result_and_graded_scale_boundaries(self):
        with connection(self.case.settings,write=True) as db:
            fixture.total(db,self.case,self.courses['credit'],50)
            fixture.total(db,self.case,self.courses['graded_credit'],65)
        rows=self.read()
        self.assertEqual(rows['credit']['predicted_result'],'pass')
        self.assertEqual(rows['graded_credit']['predicted_result'],4)
        self.assertEqual(rows['credit']['published_points'],50)
        with connection(self.case.settings) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM attestation_events').fetchone()[0],0)

    def test_create_lock_and_policy_reject_credit_70_without_changing_history(self):
        with connection(self.case.settings) as db:
            data=service.plan_data(db,self.courses['credit']['plan'])
        body={k:data[k] for k in ('curriculum_id','source','approved_on','rounding','admission_min','categories','events','scale')}
        body['categories']=[{k:v for k,v in row.items() if k!='plan_id'} for row in body['categories']]
        body['events']=[{k:v for k,v in row.items() if k!='plan_id'} for row in body['events']]
        body['scale']=[{'minimum':0,'outcome':'fail'},{'minimum':70,'outcome':'pass'}]
        self.assertEqual(self.case.post(foundation.ADMIN+'/plans',body).status_code,422)
        # Simulate a draft/locked plan created by the old validator, in this synthetic DB only.
        with connection(self.case.settings,write=True) as db:
            with patch.object(service,'validate_credit_scale'):
                key=service.create_plan(db,fixture.ADMIN,self.case.now,body)['id']
            with self.assertRaises(AuthError) as error:service.lock_plan(db,fixture.ADMIN,self.case.now,key)
            self.assertEqual(error.exception.status,422)
            self.assertIsNone(service.plan_data(db,key)['locked_at'])
            with patch.object(service,'validate_credit_scale'):
                service.lock_plan(db,fixture.ADMIN,self.case.now,key)
            before=service.plan_data(db,key)
            with self.assertRaises(AuthError):attestation.approve_policy(db,fixture.ADMIN,self.case.now,key,[])
            self.assertEqual(before,service.plan_data(db,key))
            self.assertIsNone(db.execute('SELECT 1 FROM attestation_policies WHERE plan_id=?',(key,)).fetchone())
        self.assertEqual(self.case.post(foundation.ADMIN+f'/plans/{key}/lock',{}).status_code,409)
        self.assertEqual(self.case.post('/api/v1/staff/attestations/policies/'+key,{'required_events':[]}).status_code,422)

    def test_retake_effective_highest_latest_and_incomplete_forecast(self):
        course=self.courses['credit']
        with connection(self.case.settings,write=True) as db:
            for code in ('c0','c1'):
                fixture.publish(db,self.case,course,code,18)
                results.register_submission(db,fixture.TEACHER,self.case.now,course['offering'],course['id'],code,2)
                fixture.publish(db,self.case,course,code,5,2)
        row=self.read()['credit']
        self.assertEqual([e['points'] for e in row['events']],[18,5,None,None])
        self.assertEqual(row['published_points'],23)
        self.assertIsNone(row['predicted_result'])
        self.assertIsNone(row['maximum_reachable'])

    def test_transfer_same_plan_preserves_scores_and_closed_enrollment_preserves_history(self):
        course=self.courses['credit']
        with connection(self.case.settings,write=True) as db:
            fixture.total(db,self.case,course,51)
            target=service.create_offering(db,fixture.ADMIN,self.case.now,{'plan_id':course['plan'],'group_id':'b'})['id']
            moved=service.transfer(db,fixture.ADMIN,self.case.now,course['id'],
                {'target_offering_id':target,'starts_on':'2027-02-20','reason':'Synthetic transfer','mapping':[]})
        self.assertEqual(self.read()['credit']['published_points'],51)
        # Ending the active enrollment must not erase history or infer a new enrollment.
        with connection(self.case.settings,write=True) as db:
            db.execute("UPDATE brs_enrollments SET ends_on='2027-02-21' WHERE id=?",(moved['id'],))
        self.assertEqual(self.read()['credit']['reason'],'no_active_enrollment')
        with connection(self.case.settings) as db:
            self.assertEqual(len(results.student_results(db,{'id':'alice','role':'student'},course['course_id'])['plans'][0]['events']),4)

    def test_transfer_changed_plan_needs_reconciliation_and_no_cross_plan_sum(self):
        course=self.courses['credit']
        with connection(self.case.settings,write=True) as db:
            fixture.total(db,self.case,course,51)
            plan=service.plan_data(db,course['plan'])
            fields=('curriculum_id','source','approved_on','rounding','admission_min','categories','events','scale')
            data={key:plan[key] for key in fields}
            new=service.create_plan(db,fixture.ADMIN,self.case.now,data)['id']
            service.lock_plan(db,fixture.ADMIN,self.case.now,new)
            attestation.approve_policy(db,fixture.ADMIN,self.case.now,new,[])
            target=service.create_offering(db,fixture.ADMIN,self.case.now,{'plan_id':new,'group_id':'b'})['id']
            service.transfer(db,fixture.ADMIN,self.case.now,course['id'],{
                'target_offering_id':target,'starts_on':'2027-02-20','reason':'Synthetic changed plan',
                'mapping':[{'old_event':f'c{i}','new_event':f'c{i}'} for i in range(4)]})
        row=self.read()['credit']
        self.assertFalse(row['available']);self.assertEqual(row['reason'],'transfer_reconciliation')
        self.assertNotIn('published_points',row)

    def test_http_additive_calculator_contract_is_read_only(self):
        with connection(self.case.settings) as db:
            before = list(db.iterdump())
        rows = self.read()
        for path in ("/js/brs-calculator.js", "/js/brs-calculator-state.js", "/css/calculator.css"):
            self.assertEqual(self.case.clients["alice"].get(path).status_code,200,path)
        for row in rows.values():
            self.assertEqual(row['plan_maximum'], 100)
            self.assertIsNone(row['published_points'])
            self.assertIsNone(row['predicted_result'])
            categories = {category['code']:category for category in row['categories']}
            for event in row['events']:
                self.assertIn(event['category_code'], categories)
                self.assertEqual(event['required'], False)
                self.assertEqual(event['admission_min'], 0)
                self.assertIn('retake_policy', event)
            self.assertTrue(all(category['admission_min']==0 for category in categories.values()))
        with connection(self.case.settings) as db:
            self.assertEqual(list(db.iterdump()), before)
