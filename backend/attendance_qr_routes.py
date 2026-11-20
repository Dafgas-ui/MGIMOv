"""Authenticated QR commands; plaintext challenges only in POST bodies."""
from hashlib import sha256
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from . import attendance, attendance_qr
from .auth.service import resolve, verify_csrf
from .auth.limits import LoginLimits
from .db import connection


class Issue(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(ge=1)
    lesson_version: int = Field(ge=1)
    request_key: str = Field(pattern=r'^[a-f0-9]{32}$')


class Token(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    token: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')


class Empty(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


def install_qr(app, settings):
    router = APIRouter(prefix='/api/v1')

    def run(request, role, command, *args):
        if request.query_params:
            attendance.fail(422)
        now = int(app.state.auth_service.clock())
        with connection(settings) as db:
            actor = resolve(db, request.cookies.get(settings.session_cookie), now, request.headers.get('x-mgimov-user'))
            verify_csrf(actor, request.headers.get('x-csrf-token'), request.cookies.get(settings.csrf_cookie))
            if actor['role'] != role:
                attendance.fail(403)
        bucket = sha256(('attendance-qr:'+actor['id']).encode()).hexdigest()
        with connection(settings, write=True, timeout=.5) as db:
            LoginLimits.available(db, [(bucket, 30)], now)
            db.execute('''INSERT INTO auth_rate_limits VALUES (?,?,1)
                ON CONFLICT(bucket) DO UPDATE SET
                attempts=CASE WHEN window_start>? THEN attempts+1 ELSE 1 END,
                window_start=CASE WHEN window_start>? THEN window_start ELSE excluded.window_start END''',
                (bucket, now, now-60, now-60))
        with connection(settings, write=True, timeout=.5) as db:
            actor = resolve(db, request.cookies.get(settings.session_cookie), int(app.state.auth_service.clock()), request.headers.get('x-mgimov-user'))
            verify_csrf(actor, request.headers.get('x-csrf-token'), request.cookies.get(settings.csrf_cookie))
            if actor['role'] != role:
                attendance.fail(403)
            if not db.execute("SELECT 1 FROM schema_migrations WHERE id='0026_attendance_qr'").fetchone():
                attendance.fail(503, 'Требуется обновление схемы QR.')
            return command(db, actor, int(app.state.auth_service.clock()), *args)

    @router.post('/staff/attendance/lessons/{lesson_id}/qr')
    def issue(lesson_id: str, body: Issue, request: Request):
        return run(request, 'staff', attendance_qr.issue, lesson_id, body.model_dump(), settings.origin)

    @router.post('/staff/attendance/lessons/{lesson_id}/qr/{qr_id}/close')
    def close(lesson_id: str, qr_id: str, body: Empty, request: Request):
        return run(request, 'staff', attendance_qr.close, lesson_id, qr_id)

    @router.post('/me/attendance/qr/preview')
    def preview(body: Token, request: Request):
        return run(request, 'student', attendance_qr.preview, body.token)

    @router.post('/me/attendance/qr/check-in')
    def check_in(body: Token, request: Request):
        return run(request, 'student', attendance_qr.check_in, body.token)

    app.include_router(router)
