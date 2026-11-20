"""Read-only explanations of the existing attestation preview, never official results."""
import json

from ..auth.service import AuthError
from ..brs import results, service as brs
from . import attestation


def student_forecasts(db, actor, now):
    if actor['role'] != 'student':
        brs.fail(403, 'Доступно студенту.')
    rows = db.execute('''SELECT c.id,s.name AS subject,i.control,t.name AS semester
        FROM brs_student_courses c JOIN curriculum_items i ON i.id=c.curriculum_id
        JOIN subjects s ON s.id=i.subject_id JOIN semesters t ON t.id=i.semester_id
        WHERE c.student_id=? ORDER BY t.starts_on DESC,s.name,c.id''', (actor['id'],)).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            flow = attestation.enrollment(db, row['id'], now)
        except AuthError as error:
            if error.status != 404:
                raise
            items.append({**item, 'available': False, 'reason': 'no_active_enrollment'})
            continue
        plan = brs.plan_data(db, flow['plan_id'])
        if plan['locked_at'] is None or sorted(c['maximum'] for c in plan['categories']) != [20,20,20,40]:
            items.append({**item, 'available': False, 'reason': 'plan_not_ready'})
            continue
        try:
            brs.validate_credit_scale(plan, row)
            calculated = attestation.preview(db, attestation.position(db, row['id']), flow)
        except AuthError as error:
            reasons = {404: 'policy_not_ready', 409: 'transfer_reconciliation', 422: 'inconsistent_credit_scale'}
            if error.status not in reasons:
                raise
            items.append({**item, 'available': False, 'reason': reasons[error.status]})
            continue
        summary = next(p for p in results.student_results(db, actor, row['id'])['plans'] if p['plan_id']==plan['id'])
        events = {e['event']:e for e in calculated['inputs']}
        missing = [e['code'] for e in plan['events'] if events[e['code']]['points'] is None]
        present = len(missing) < len(plan['events'])
        predicted = None
        if row['control'] != 'exam' and present and not missing:
            predicted = calculated['outcome'] if row['control']=='credit' else calculated['grade']
        categories = {c['code']:c for c in summary['categories']}
        required = set(json.loads(brs.get(db,
            'SELECT required_events FROM attestation_policies WHERE plan_id=?',
            plan['id'])['required_events']))
        items.append({**item, 'available': True, 'plan_id': plan['id'],
            'published_points': calculated['points'] if present else None,
            'plan_maximum': 100, 'maximum_reachable': None,
            'maximum_reason': 'future_attempts_unknown',
            'admission': calculated['admitted'] if present else None,
            'admission_minimum': max(50,plan['admission_min']),
            'required_shortfalls': calculated['missing'],
            'category_shortfalls': calculated['category_shortfalls'],
            'predicted_result': predicted,
            'result_reason': ('examiner_decides' if row['control']=='exam' else
                              'no_published_results' if not present else 'unpublished_events' if missing else 'current_published_results'),
            'events': [{'code':e['code'], 'title':e['title'], 'maximum':e['maximum'],
                        'points':events[e['code']]['points'], 'retake_policy':e['retake_policy'],
                        'category_code':e['category_code'], 'required':e['code'] in required,
                        'admission_min':e['admission_min'] or 0}
                       for e in plan['events']],
            'categories': [{'code':c['code'], 'title':c['title'], 'maximum':c['maximum'],
                            'admission_min':c['admission_min'] or 0,
                            'points':categories[c['code']]['points'] if any(
                                e['category_code']==c['code'] and events[e['code']]['points'] is not None
                                for e in plan['events']) else None} for c in plan['categories']],
            'scale': [{'minimum':s['minimum'],'outcome':s['outcome']} for s in plan['scale']]})
    return {'items':items, 'calculated_at':now}
