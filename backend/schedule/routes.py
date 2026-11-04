"""Read only: group derives from the live student session, never client input."""
from typing import Literal
from fastapi import APIRouter, Request
from ..auth.service import AuthError
from .service import calendar_date, read_schedule

def install_schedule(app, settings):
    router=APIRouter(prefix='/api/v1/me')
    @router.get('/schedule')
    def schedule(request:Request,view:Literal['today','week']='today',date:str|None=None):
        for key in request.query_params:
            if key not in ('view','date') or len(request.query_params.getlist(key))!=1:
                raise AuthError(422,'Недопустимые параметры расписания.')
        if date is not None:
            try:calendar_date(date)
            except ValueError:raise AuthError(422,'Укажите существующую дату ГГГГ-ММ-ДД.') from None
        return read_schedule(app.state.auth_service,request.cookies.get(settings.session_cookie),selected=date,view=view,expected=request.headers.get('x-mgimov-user'))
    app.include_router(router)
