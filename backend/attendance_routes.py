"""Session/CSRF adapter for lesson attendance."""
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from . import attendance
from .auth.service import resolve, verify_csrf
from .db import connection


class Confirm(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: Literal['confirm']
    expected_version: int = Field(ge=0)
    lesson_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=300)
    candidate_token: str = Field(pattern=r'^[a-f0-9]{64}$')


class Mark(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: Literal['mark']
    expected_version: int = Field(ge=1)
    lesson_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=300)
    student_id: str = Field(min_length=1, max_length=100)
    status: Literal['present','absent','late','unmarked']


def install_attendance(app, settings):
    router = APIRouter(prefix='/api/v1')

    def run(request, role, action, *args, write=False):
        if request.query_params:
            attendance.fail(422, 'Параметры выбора пользователя не поддерживаются.')
        with connection(settings, write=write, timeout=.5) as db:
            if not write:
                db.execute('BEGIN')
            now = int(app.state.auth_service.clock())
            actor = resolve(db, request.cookies.get(settings.session_cookie), now, request.headers.get('x-mgimov-user'))
            if actor['role'] != role:
                attendance.fail(403)
            if write:
                verify_csrf(actor, request.headers.get('x-csrf-token'), request.cookies.get(settings.csrf_cookie))
            if not db.execute("SELECT 1 FROM schema_migrations WHERE id='0024_attendance'").fetchone():
                attendance.fail(503, 'Требуется обновление схемы посещаемости.')
            return action(db, actor, now, *args) if write else action(db, actor, *args)

    @router.get('/staff/attendance/lessons')
    def lessons(request: Request):
        return run(request, 'staff', attendance.lessons)

    @router.get('/staff/attendance/lessons/{lesson_id}')
    def detail(lesson_id: str, request: Request):
        return run(request, 'staff', attendance.staff_detail, lesson_id)

    @router.post('/staff/attendance/lessons/{lesson_id}')
    def change(lesson_id: str, body: Confirm | Mark, request: Request):
        return run(request, 'staff', attendance.change, lesson_id, body.model_dump(), write=True)

    @router.get('/me/attendance/lessons/{lesson_id}')
    def own(lesson_id: str, request: Request):
        return run(request, 'student', attendance.student_detail, lesson_id)

    @router.get('/me/attendance')
    def own_list(request: Request):
        def read(db, actor):
            rows = db.execute("""SELECT DISTINCT e.lesson_id FROM attendance_events e,json_each(e.payload,'$.students') s
                WHERE e.kind='roster' AND json_extract(s.value,'$.id')=? ORDER BY e.lesson_id""", (actor['id'],))
            return {'items':[attendance.student_detail(db, actor, row['lesson_id']) for row in rows]}
        return run(request, 'student', read)

    app.include_router(router)
