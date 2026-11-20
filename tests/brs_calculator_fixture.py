"""Serialize real forecast service results for Python/Node contract tests."""
import copy
import json
from unittest.mock import patch

from backend.academics import attestation
from backend.academics.forecast import student_forecasts
from backend.brs import service
from backend.db import connection
from tests import forecast_fixture as fixture, test_brs_foundation as foundation
from tests.test_foundation import temporary

CATEGORIES = ('EXAM', 'ESSAY', 'QUIZ', 'FINAL')
EVENTS = ('EXAM_MAIN', 'EXAM_ESSAY', 'QUIZ_RESULT', 'FINAL_RESULT')


def real_forecasts():
    case = foundation.BRSFoundationTests()
    create_plan = service.create_plan
    approve = attestation.approve_policy

    def plan(db, actor, now, data):
        data = copy.deepcopy(data)
        for i, category in enumerate(data['categories']):
            category['code'] = CATEGORIES[i]
            category['admission_min'] = 10 if i == 0 else 0
        for i, event in enumerate(data['events']):
            event.update(code=EVENTS[i], category_code=CATEGORIES[i], admission_min=10 if i == 1 else 0)
        return create_plan(db, actor, now, data)

    try:
        case.initialize(case.enterContext(temporary()), with_http=False)
        with patch.object(service, 'create_plan', side_effect=plan), patch.object(
                attestation, 'approve_policy', side_effect=lambda db,a,n,p,c: approve(db,a,n,p,[EVENTS[1]])):
            courses = fixture.prepare(case)
        samples = {}
        with connection(case.settings, write=True) as db:
            cases = {'empty': None, 'zero': [0,0,0,0], '49': [20,20,9,0],
                     '50': [20,20,10,0], '51': [20,20,11,0], '60': [20,20,20,0],
                     'required_missing': [20,0,20,20], 'category_missing': [0,20,20,20]}
            for name, points in cases.items():
                db.execute('SAVEPOINT sample')
                if points is not None:
                    for course in courses.values():
                        for code, value in zip(EVENTS, points):
                            fixture.publish(db, case, course, code, value)
                before = list(db.iterdump())
                data = student_forecasts(db, {'id':'alice','role':'student'}, case.now)
                # Reads must preserve every table, including audit and official results.
                assert list(db.iterdump()) == before
                samples[name] = json.loads(json.dumps(data))
                db.execute('ROLLBACK TO sample')
                db.execute('RELEASE sample')
        return samples
    finally:
        case.doCleanups()


if __name__ == '__main__':
    print(json.dumps(real_forecasts()))
