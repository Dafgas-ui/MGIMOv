from typing import Annotated, Literal, Union

from fastapi import APIRouter, Request
from pydantic import Field

from ..auth.service import AuthError, resolve, verify_csrf
from ..brs.models import Key, Strict, VersionNumber
from ..brs.service import fail
from ..db import connection
from . import attestation as service
from .forecast import student_forecasts

Reason = Annotated[str, Field(min_length=3,max_length=300,pattern=r"\S")]
Timestamp = Annotated[int, Field(ge=1,le=4102444800)]


class Command(Strict):
    expected_version: VersionNumber
    request_key: Key


class Schedule(Command):
    action: Literal['scheduled']
    starts_at: Timestamp
    ends_at: Timestamp
    examiner_id: Key
    room_id: Key | None = None
    commission: list[Key] = Field(default_factory=list,max_length=12)


class Result(Command):
    action: Literal['draft','published','completed']
    slot_id: Key
    grade: Annotated[int,Field(ge=2,le=5)] | None = None


class Absence(Command):
    action: Literal['excused','unexcused']
    slot_id: Key
    reason: Reason
    reference: Reason


class Cancellation(Command):
    action: Literal['cancelled']
    slot_id: Key
    reason: Reason


class RequestReview(Absence):
    action: Literal['review_requested']
    executor_id: Key
    grade: Annotated[int,Field(ge=2,le=5)] | None = None
    outcome: Literal['pass','fail'] | None = None


class Review(Command):
    action: Literal['review_approved','review_revoked','corrected']
    review_version: Annotated[int,Field(ge=1,le=2**63-1)]
    reason: Reason | None = None


class Admission(Command):
    action: Literal['not_admitted','admission_restored','conflict_resolved']
    reason: Reason
    reference: Reason | None = None


class Policy(Strict):
    required_events: list[Key] = Field(max_length=100)


class Language(Strict):
    language: Literal['ru','en']


Mutation = Annotated[Union[Schedule,Result,Absence,Cancellation,RequestReview,Review,Admission],
                     Field(discriminator='action')]


def install_attestations(app,settings):
    router = APIRouter(prefix='/api/v1')

    def run(request, action, *, write=False, staff=False):
        if request.query_params:
            fail(422,'Параметры запроса не поддерживаются.')
        token = request.cookies.get(settings.session_cookie)
        expected = request.headers.get('x-mgimov-user')
        with connection(settings,write=write,timeout=.5) as db:
            if not write:
                db.execute('BEGIN')
            now = int(app.state.auth_service.clock())
            actor = resolve(db,token,now,expected)
            if staff is not None and actor['role']!=('staff' if staff else 'student'):
                fail(403,'Недостаточно полномочий.')
            if write:
                verify_csrf(actor,request.headers.get('x-csrf-token'),request.cookies.get(settings.csrf_cookie))
            if not db.execute("SELECT 1 FROM schema_migrations WHERE id='0012_attestations'").fetchone():
                fail(503,'Требуется миграция аттестаций.')
            return action(db,actor,now)

    @router.get('/me/time')
    def server_time(request:Request):
        return run(request, lambda db,actor,now: {'server_time':now})

    @router.get('/me/brs/forecast')
    def forecast(request:Request):
        return run(request, student_forecasts)

    @router.get('/me/language')
    def get_language(request:Request):
        def read(db,actor,now):
            row = db.execute("SELECT language FROM account_languages WHERE user_id=?",(actor['id'],)).fetchone()
            return {'language':row['language'] if row else 'ru'}
        return run(request,read,staff=None)

    @router.post('/me/language')
    def set_language(body:Language,request:Request):
        def write(db,actor,now):
            db.execute("""INSERT INTO account_languages VALUES (?,?)
                ON CONFLICT(user_id) DO UPDATE SET language=excluded.language""",(actor['id'],body.language))
            return {'language':body.language}
        return run(request,write,write=True,staff=None)

    @router.post('/staff/attestations/policies/{plan}')
    def policy(plan:Key,body:Policy,request:Request):
        return run(request,lambda db,a,n:service.approve_policy(db,a,n,plan,body.required_events),
                   write=True,staff=True)

    @router.post('/staff/attestations/{course}/activate')
    def activate(course:Key,body:Strict,request:Request):
        return run(request,lambda db,a,n:service.activate(db,a,n,course),write=True,staff=True)

    @router.post('/staff/attestations/{course}/commands')
    def command(course:Key,body:Mutation,request:Request):
        return run(request,lambda db,a,n:service.execute(db,a,n,course,body.action,
                   body.model_dump(exclude={'action'})),write=True,staff=True)

    @router.get('/staff/attestations')
    def staff_list(request:Request):
        def listing(db,actor,now):
            return {'items':[dict(row) for row in db.execute("""SELECT c.id,sub.name AS subject,
                student.full_name AS student, i.control, (a.course_id IS NOT NULL) AS activated
                FROM brs_student_courses c JOIN curriculum_items i ON i.id=c.curriculum_id
                JOIN subjects sub ON sub.id=i.subject_id JOIN programs p ON p.id=i.program_id
                JOIN student_profiles student ON student.user_id=c.student_id
                LEFT JOIN attestation_positions a ON a.course_id=c.id
                WHERE EXISTS(SELECT 1 FROM attestation_permissions q
                    WHERE q.staff_id=? AND q.faculty_id=p.faculty_id AND (q.permission!='examiner'
                      OR EXISTS(SELECT 1 FROM attestation_slots x WHERE x.course_id=c.id AND x.examiner_id=q.staff_id)))
                ORDER BY student.full_name,sub.name,c.id LIMIT 200""",(actor['id'],))]}
        return run(request,listing,staff=True)

    @router.get('/staff/attestations/{course}')
    def staff_course(course:Key,request:Request):
        def read(db,actor,now):
            item = service.position(db,course)
            slots,events = service.load(db,course)
            service.staff_access(db,actor,item,slots)
            permissions = [r['permission'] for r in db.execute(
                "SELECT permission FROM attestation_permissions WHERE staff_id=? AND faculty_id=?",
                (actor['id'],item['faculty_id']))]
            current = service.state(slots,events)
            applicable_reviews = service.applicable_reviews(db,actor,now,item,slots,events,current)
            official_state = current.copy()
            allowed_internal = any(p in permissions for p in ('review','late_request'))
            events = [e for e in events if (e['kind'] in service.PUBLIC or e['actor_id']==actor['id']
                     or (allowed_internal and e['kind'].startswith('review_')))]
            current['official'] = {
                key:{**event,'data':{field:event['data'].get(field) for field in ('outcome','grade')}}
                for key,event in current['official'].items()
            }
            if current['latest']:
                latest = current['latest']
                current['latest'] = {**latest,'data':{field:latest['data'].get(field) for field in ('outcome','grade')}}
            if not allowed_internal:
                events = [{**event,'data':{field:event['data'].get(field) for field in ('outcome','grade')}}
                          if event['kind'] in service.PUBLIC else event for event in events]
            version = db.execute("SELECT max(version) FROM attestation_events WHERE course_id=?",
                                 (course,)).fetchone()[0] or 0
            examiners = [dict(row) for row in db.execute("""SELECT s.user_id AS id,s.full_name FROM staff_profiles s
                JOIN users u ON u.id=s.user_id JOIN attestation_permissions p ON p.staff_id=s.user_id
                WHERE u.active=1 AND p.faculty_id=? AND p.permission='examiner' ORDER BY s.full_name""",
                (item['faculty_id'],))] if 'schedule' in permissions else []
            rooms = [dict(row) for row in db.execute("""SELECT r.id,b.name||' '||r.number AS label
                FROM rooms r JOIN buildings b ON b.id=r.building_id ORDER BY b.name,r.number""")] if examiners else []
            reviewers = [dict(row) for row in db.execute("""SELECT s.user_id AS id,s.full_name FROM staff_profiles s
                JOIN users u ON u.id=s.user_id JOIN attestation_permissions p ON p.staff_id=s.user_id
                WHERE u.active=1 AND p.faculty_id=? AND p.permission='late_execute' ORDER BY s.full_name""",
                (item['faculty_id'],))] if 'late_request' in permissions else []
            calculated = None
            try:
                calculated = service.preview(db,item,service.enrollment(db,course,now))
            except AuthError as error:
                if error.status not in (404,409):
                    raise
            return {'version':version,'slots':slots,'events':events,'state':current,
                    'permissions':permissions,'control':item['control'],'examiners':examiners,'rooms':rooms,
                    'brs_changed':service.input_discrepancy(official_state,calculated),
                    'late':service.brs.date_at(now)>item['ends_on'],'reviewers':reviewers,
                    'applicable_review_versions':applicable_reviews}
        return run(request,read,staff=True)

    @router.get('/me/attestations')
    def own(request:Request):
        def read(db,actor,now):
            rows = db.execute("""SELECT c.id,sub.name AS subject,i.control
                FROM attestation_positions a JOIN brs_student_courses c ON c.id=a.course_id
                JOIN curriculum_items i ON i.id=c.curriculum_id JOIN subjects sub ON sub.id=i.subject_id
                WHERE c.student_id=? ORDER BY i.semester_id,sub.name,c.id""",(actor['id'],)).fetchall()
            items = []
            for row in rows:
                slots,events = service.load(db,row['id'])
                current = service.state(slots,events)
                item = service.position(db,row['id'])
                try:
                    calculated = service.preview(db,item,service.enrollment(db,row['id'],now))
                except AuthError as error:
                    if error.status not in (404,409):
                        raise
                    calculated = None
                items.append({**dict(row),**service.student_view(db,slots,events,current),
                              'preview':{key:calculated[key] for key in ('points','missing','admitted')}
                              if calculated else None})
            return {'items':items}
        return run(request,read)

    app.include_router(router)
