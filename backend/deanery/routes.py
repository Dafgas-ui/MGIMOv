"""Session-protected MVP workspace; no public document URLs."""
from typing import Literal
from fastapi import APIRouter,Request
from pydantic import BaseModel,ConfigDict,Field
from ..auth.service import AuthError
from .service import read,mutate

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
class Empty(Strict):pass
class Version(Strict):
    version:int=Field(ge=1)
class Reply(Version):
    comment:str=Field(min_length=1,max_length=1000)
class LessonTime(Strict):
    date:str=Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    start_minute:int=Field(ge=0,lt=1440)
    end_minute:int=Field(gt=0,le=1440)
    teacher_id:str=Field(min_length=1,max_length=100)
    room_id:str=Field(min_length=1,max_length=100)
    status:Literal['scheduled','cancelled']
    reason:str=Field(min_length=1,max_length=300)
class LessonCreate(LessonTime):
    group_id:str=Field(min_length=1,max_length=100)
    subject_id:str=Field(min_length=1,max_length=100)
    kind:Literal['lecture','seminar','practice','lab']
class LessonUpdate(LessonTime):
    version:int=Field(ge=1)
class Notice(Strict):
    student_id:str=Field(min_length=1,max_length=100)
    title:str=Field(min_length=1,max_length=160)
    body:str=Field(min_length=1,max_length=1000)

def install_deanery(app,settings):
    router=APIRouter(prefix='/api/v1')
    def call(request,resource,body=None,key=None):
        if request.query_params:raise AuthError(422,'Параметры выбора пользователя не принимаются.')
        args=dict(expected=request.headers.get('x-mgimov-user'),key=key)
        token=request.cookies.get(settings.session_cookie)
        try:
            if body is None:return read(app.state.auth_service,token,resource,**args)
            return mutate(app.state.auth_service,token,resource,body.model_dump(),header=request.headers.get('x-csrf-token'),cookie=request.cookies.get(settings.csrf_cookie),**args)
        except ValueError:raise AuthError(422,'Проверьте дату, интервал и изменения занятия.') from None
    @router.get('/me/notifications')
    def notices(request:Request,cursor:str|None=None):
        if any(k!='cursor' or len(request.query_params.getlist(k))!=1 for k in request.query_params):raise AuthError(422,'Недопустимые параметры уведомлений.')
        return read(app.state.auth_service,request.cookies.get(settings.session_cookie),'notifications',expected=request.headers.get('x-mgimov-user'),cursor=cursor)
    @router.post('/me/notifications/{key}/read')
    def seen(key:str,body:Empty,request:Request):return call(request,'read_notification',body,key)
    @router.get('/me/documents')
    def documents(request:Request):return call(request,'documents')
    @router.get('/me/documents/{key}')
    def document(key:str,request:Request):return call(request,'document',key=key)
    @router.get('/staff/students')
    def students(request:Request):return call(request,'students')
    @router.get('/staff/catalogue')
    def catalogue(request:Request):return call(request,'catalogue')
    @router.get('/staff/lessons')
    def lessons(request:Request):return call(request,'lessons')
    @router.post('/staff/lessons')
    def create(body:LessonCreate,request:Request):return call(request,'lesson',body)
    @router.post('/staff/lessons/{key}')
    def update(key:str,body:LessonUpdate,request:Request):return call(request,'lesson',body,key)
    @router.get('/staff/documents')
    def staff_documents(request:Request):return call(request,'staff_documents')
    @router.post('/staff/requests/{key}/reply')
    def reply(key:str,body:Reply,request:Request):return call(request,'reply',body,key)
    @router.post('/staff/requests/{key}/sign')
    def sign(key:str,body:Version,request:Request):return call(request,'sign',body,key)
    @router.post('/staff/documents/{key}/deliver')
    def deliver(key:str,body:Empty,request:Request):return call(request,'deliver',body,key)
    @router.post('/staff/notifications')
    def send(body:Notice,request:Request):return call(request,'notify',body)
    app.include_router(router)
