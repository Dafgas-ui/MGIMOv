"""BRS routes under the existing IdentityGuard prefixes."""
import sqlite3
from functools import partial

from fastapi import APIRouter, Request

from ..auth.service import resolve, verify_csrf
from ..db import connection
from . import models, results, service


def install_brs(app, settings):
    router = APIRouter(prefix="/api/v1")

    def run(request, action, *args, write=False):
        if request.query_params:
            service.fail(422, "Параметры запроса не поддерживаются.")
        token = request.cookies.get(settings.session_cookie)
        expected = request.headers.get("x-mgimov-user")

        def identity(db, now):
            user = resolve(db, token, now, expected)
            if write:
                if user["role"] != "staff":
                    service.fail(403, "Доступно сотруднику.")
                verify_csrf(user, request.headers.get("x-csrf-token"), request.cookies.get(settings.csrf_cookie))
            return user

        # Invalid sessions and CSRF do not take the writer lock. Check again under the lock.
        if write:
            with connection(settings) as db:
                identity(db, int(app.state.auth_service.clock()))
        try:
            with connection(settings, write=write, timeout=.5) as db:
                if not write:
                    db.execute("BEGIN")
                now = int(app.state.auth_service.clock())
                user = identity(db, now)
                if not db.execute(
                    "SELECT 1 FROM schema_migrations WHERE id='0011_brs_integer_points'"
                ).fetchone():
                    service.fail(503, "Требуется обновление схемы БРС.")
                if write:
                    return action(db, user, now, *args)
                return action(db, user, *args)
        except ValueError:
            service.fail(422, "Некорректная дата или параметры БРС.")
        except sqlite3.IntegrityError as error:
            service.constraint_conflict(error)

    @router.post("/staff/brs/admin/plans", status_code=201)
    def create_plan(body: models.Plan, request: Request):
        return run(request, service.create_plan, body.model_dump(), write=True)

    @router.post("/staff/brs/admin/plans/{key}/lock")
    def lock_plan(key: models.Key, body: models.Strict, request: Request):
        return run(request, service.lock_plan, key, write=True)

    @router.post("/staff/brs/admin/offerings", status_code=201)
    def create_offering(body: models.Offering, request: Request):
        return run(request, service.create_offering, body.model_dump(), write=True)

    @router.post("/staff/brs/admin/teacher-accounts", status_code=201)
    def bind_teacher(body: models.Teacher, request: Request):
        return run(request, service.bind_teacher, body.model_dump(), write=True)

    @router.post("/staff/brs/admin/offerings/{key}/grants", status_code=201)
    def grant(key: models.Key, body: models.Grant, request: Request):
        return run(request, service.grant_teaching, key, body.model_dump(), write=True)

    @router.post("/staff/brs/admin/grants/{key}/revoke")
    def revoke(key: models.Key, body: models.Strict, request: Request):
        return run(request, service.revoke_teaching, key, write=True)

    @router.post("/staff/brs/admin/offerings/{key}/enrollments", status_code=201)
    def enroll(key: models.Key, body: models.Enrollment, request: Request):
        return run(request, service.enroll, key, body.model_dump(), write=True)

    @router.post("/staff/brs/admin/enrollments/{key}/transfer", status_code=201)
    def transfer(key: models.Key, body: models.Transfer, request: Request):
        return run(request, service.transfer, key, body.model_dump(), write=True)

    @router.get("/staff/brs/offerings/{key}/access")
    def access(key: models.Key, request: Request):
        def check(db, user):
            service.teaching_access(db, user, int(app.state.auth_service.clock()), key)
            return {"id": key}
        return run(request, check)

    @router.get("/staff/brs/offerings/{key}/enrollments/{enrollment}/access")
    def enrollment_access(key: models.Key, enrollment: models.Key, request: Request):
        def check(db, user):
            service.teaching_access(db, user, int(app.state.auth_service.clock()), key, enrollment_id=enrollment)
            return {"id": enrollment}
        return run(request, check)

    @router.get("/staff/brs/offerings/{key}/enrollments/{enrollment}/events/{event}/access")
    def event_access(key: models.Key, enrollment: models.Key, event: models.Key, request: Request):
        def check(db, user):
            service.teaching_access(db, user, int(app.state.auth_service.clock()), key,
                                    enrollment_id=enrollment, event_code=event)
            return {"id": event}
        return run(request, check)

    @router.get("/me/brs/enrollments/{key}/plan")
    def own_plan(key: models.Key, request: Request):
        return run(request, service.student_plan, key)

    event_path = "/staff/brs/offerings/{key}/enrollments/{enrollment}/events/{event}"
    attempt_path = event_path + "/attempts/{attempt}"

    @router.get(event_path + "/result")
    def staff_result(key: models.Key, enrollment: models.Key, event: models.Key, request: Request):
        def read(db, user):
            return results.staff_result(db, user, int(app.state.auth_service.clock()), key, enrollment, event)
        return run(request, read)

    @router.post(attempt_path + "/submission")
    def register_submission(key: models.Key, enrollment: models.Key, event: models.Key,
                            attempt: models.AttemptNumber, body: models.Strict, request: Request):
        return run(request, results.register_submission, key, enrollment, event, attempt, write=True)

    @router.put(attempt_path + "/draft")
    def save_draft(key: models.Key, enrollment: models.Key, event: models.Key,
                   attempt: models.AttemptNumber, body: models.ResultDraft, request: Request):
        return run(request, results.save_draft, key, enrollment, event, attempt, body.model_dump(), write=True)

    @router.post(attempt_path + "/publish")
    def publish_result(key: models.Key, enrollment: models.Key, event: models.Key,
                       attempt: models.AttemptNumber, body: models.PublishResult, request: Request):
        return run(request, partial(results.change_result, command="publish"),
                   key, enrollment, event, attempt, body.model_dump(), write=True)

    @router.post(attempt_path + "/correct")
    def correct_result(key: models.Key, enrollment: models.Key, event: models.Key,
                       attempt: models.AttemptNumber, body: models.CorrectResult, request: Request):
        return run(request, partial(results.change_result, command="correct"),
                   key, enrollment, event, attempt, body.model_dump(), write=True)

    @router.get("/me/brs/courses/{course}/results")
    def student_results(course: models.Key, request: Request):
        return run(request, results.student_results, course)

    @router.get("/me/brs/courses/{course}/results/{result}/history")
    def student_history(course: models.Key, result: models.Key, request: Request):
        return run(request, results.student_history, course, result)

    app.include_router(router)
