"""Session-protected HTTP adapter for coursework services."""
import sqlite3
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field, StringConstraints

from . import coursework
from .auth.service import resolve, verify_csrf
from .brs.models import Key, Strict
from .brs.service import constraint_conflict, fail
from .db import connection


class WorkFilters(Strict):
    offering_id: Key | None = None
    semester_id: Key | None = None


RequestKey = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{16,64}$')]


class Draft(Strict):
    request_key: RequestKey
    offering_id: Key
    kind: Literal['lab', 'test', 'practice', 'other']
    title: str = Field(max_length=160)
    description: str = Field(max_length=4000)
    due_at: int
    mode: Literal['in_person', 'online', 'both']


class Versioned(Strict):
    expected_version: int = Field(ge=1)
    request_key: RequestKey


class Submission(Versioned):
    response: str = Field(max_length=4000)


class Attachment(Strict):
    name: str = Field(max_length=80)
    content: str = Field(max_length=87384)


class Materials(Versioned):
    files: list[Attachment] = Field(min_length=1, max_length=2)


class FileSubmission(Submission, Materials):
    pass


class DraftEdit(Versioned):
    data: dict


class StaffCommand(DraftEdit):
    action: Literal['publish', 'copy', 'record_in_person', 'review', 'publish_brs']


async def published_result_conflict(request, error):
    return JSONResponse({'detail': error.message, 'code': error.code}, status_code=409)


def install_coursework(app, settings):
    router = APIRouter(prefix='/api/v1')

    def run(request, role, action, *args, write=False, filters=False):
        if request.query_params and (not filters or len(request.query_params.multi_items()) != len(request.query_params)):
            fail(422, 'Некорректные параметры запроса.')
        token = request.cookies.get(settings.session_cookie)
        expected = request.headers.get('x-mgimov-user')

        def identity(db, now):
            actor = resolve(db, token, now, expected)
            if actor['role'] != role:
                fail(403, 'Раздел недоступен для этой роли.')
            if write:
                verify_csrf(actor, request.headers.get('x-csrf-token'), request.cookies.get(settings.csrf_cookie))
            return actor

        if write:
            with connection(settings) as db:
                identity(db, int(app.state.auth_service.clock()))
        try:
            with connection(settings, write=write, timeout=.5) as db:
                if not write:
                    db.execute('BEGIN')
                now = int(app.state.auth_service.clock())
                actor = identity(db, now)
                if not db.execute("""SELECT 1 FROM schema_migrations
                    WHERE id='0023_coursework_brs_server_audit'""").fetchone():
                    fail(503, 'Требуется обновление схемы учебных работ.')
                return action(db, actor, now, *args)
        except sqlite3.IntegrityError as error:
            constraint_conflict(error)

    @router.get('/me/coursework')
    def student_list(request: Request, filters: Annotated[WorkFilters, Query()]):
        return run(request, 'student', coursework.student_works,
                   filters.offering_id, filters.semester_id, filters=True)

    @router.get('/me/coursework/{assignment_id}')
    def student_detail(assignment_id: Key, request: Request):
        return run(request, 'student', lambda db, actor, now: coursework.student_work(db, actor, assignment_id, now=now))

    @router.post('/me/coursework/{assignment_id}/submissions', status_code=201)
    def submit(assignment_id: Key, body: Submission, request: Request):
        return run(request, 'student', lambda db, actor, now: coursework.execute(
            db, actor, now, assignment_id, 'submit_text', expected_version=body.expected_version,
            request_key=body.request_key, data={'response': body.response}), write=True)

    @router.post('/me/coursework/{assignment_id}/submissions/with-files', status_code=201)
    def submit_files(assignment_id: Key, body: FileSubmission, request: Request):
        return run(request, 'student', lambda db, actor, now: coursework.execute(
            db, actor, now, assignment_id, 'submit_text', expected_version=body.expected_version,
            request_key=body.request_key, data=body.model_dump(include={'response', 'files'})), write=True)

    @router.post('/staff/coursework/{assignment_id}/materials')
    def materials(assignment_id: Key, body: Materials, request: Request):
        return run(request, 'staff', lambda db, actor, now: coursework.execute(
            db, actor, now, assignment_id, 'attach_materials', expected_version=body.expected_version,
            request_key=body.request_key, data=body.model_dump(include={'files'})), write=True)

    def download(request, role, file_id):
        name, content = run(request, role, coursework.download_file, file_id)
        return Response(content, media_type='application/octet-stream', headers={
            'Content-Disposition': "attachment; filename*=UTF-8''" + quote(name, safe=''),
            'Content-Security-Policy': 'sandbox',
        })

    @router.get('/me/coursework/files/{file_id}')
    def student_file(file_id: Key, request: Request):
        return download(request, 'student', file_id)

    @router.get('/staff/coursework/files/{file_id}')
    def staff_file(file_id: Key, request: Request):
        return download(request, 'staff', file_id)

    @router.get('/staff/coursework')
    def staff_list(request: Request, filters: Annotated[WorkFilters, Query()]):
        return run(request, 'staff', coursework.staff_works, filters.offering_id, filters.semester_id, filters=True)

    @router.post('/staff/coursework', status_code=201)
    def create(body: Draft, request: Request):
        return run(request, 'staff', coursework.create_work, body.offering_id, body.request_key,
                   body.model_dump(exclude={'offering_id', 'request_key'}), write=True)

    @router.get('/staff/coursework/{assignment_id}')
    def staff_detail(assignment_id: Key, request: Request):
        return run(request, 'staff', coursework.staff_work, assignment_id)

    @router.get('/staff/coursework/{assignment_id}/recipients/{course_id}')
    def staff_history(assignment_id: Key, course_id: Key, request: Request):
        return run(request, 'staff', coursework.staff_recipient_work, assignment_id, course_id)

    @router.patch('/staff/coursework/{assignment_id}')
    def edit(assignment_id: Key, body: DraftEdit, request: Request):
        return run(request, 'staff', lambda db, actor, now: coursework.execute(
            db, actor, now, assignment_id, 'edit_draft', **body.model_dump()), write=True)

    @router.post('/staff/coursework/{assignment_id}/commands')
    def command(assignment_id: Key, body: StaffCommand, request: Request):
        return run(request, 'staff', lambda db, actor, now: coursework.execute(
            db, actor, now, assignment_id, **body.model_dump()), write=True)

    app.add_exception_handler(coursework.PublishedBRSConflict, published_result_conflict)
    app.include_router(router)
