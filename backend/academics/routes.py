from fastapi import APIRouter, Request
from ..auth.service import AuthError
from .service import read_academics


def install_academics(app,settings):
    router=APIRouter(prefix='/api/v1/me')
    def read(request):
        if request.query_params:raise AuthError(422,'Параметры выбора студента не поддерживаются.')
        return read_academics(app.state.auth_service,request.cookies.get(settings.session_cookie),request.headers.get('x-mgimov-user'))
    @router.get('/gradebook')
    def gradebook(request:Request):return read(request)
    @router.get('/exams')
    def exams(request:Request):
        data=read(request)
        return {key:data[key] for key in ('today','exams')}
    @router.get('/debts')
    def debts(request:Request):return {'debts':read(request)['debts']}
    @router.get('/progress')
    def progress(request:Request):
        data=read(request)
        return {key:data[key] for key in ('current_semester','progress')}
    app.include_router(router)
