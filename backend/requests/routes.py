from typing import Literal
from fastapi import APIRouter,Request,Response
from pydantic import BaseModel,ConfigDict,Field
from ..auth.service import AuthError
from .service import create_request,read_requests,transition_request

class CreateRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    type:Literal['study_certificate','general_certificate','appeal']
    purpose:str=Field(default='',max_length=200)
    message:str=Field(min_length=1,max_length=2000)
    request_key:str=Field(pattern='^[a-f0-9]{32}$')

class Decision(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    version:int=Field(ge=1)
    action:Literal['processing','approved','rejected']
    comment:str=Field(min_length=1,max_length=1000)

class Cancel(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    version:int=Field(ge=1)
    comment:str=Field(default='Отменено студентом.',min_length=1,max_length=1000)


def install_requests(app,settings):
    router=APIRouter(prefix='/api/v1')
    def context(request,mutation=False):
        result={'expected':request.headers.get('x-mgimov-user')}
        if mutation:result.update(header=request.headers.get('x-csrf-token'),cookie=request.cookies.get(settings.csrf_cookie))
        return result
    def token(request):return request.cookies.get(settings.session_cookie)
    def clean(request,listing=False):
        if any(k!='offset' or not listing or len(request.query_params.getlist(k))!=1 for k in request.query_params):
            raise AuthError(422,'Недопустимые параметры обращения.')
    def listing(request,role,offset):
        clean(request,True)
        return read_requests(app.state.auth_service,token(request),role,offset=offset,**context(request))
    def detail(request,role,request_id):
        clean(request)
        return read_requests(app.state.auth_service,token(request),role,request_id=request_id,**context(request))

    @router.get('/me/requests')
    def student_list(request:Request,offset:int=0):return listing(request,'student',offset)
    @router.post('/me/requests')
    def create(body:CreateRequest,request:Request,response:Response):
        clean(request)
        data,created=create_request(app.state.auth_service,token(request),body.type,body.purpose,body.message,body.request_key,**context(request,True))
        response.status_code=201 if created else 200
        return data
    @router.get('/me/requests/{request_id}')
    def student_detail(request_id:str,request:Request):return detail(request,'student',request_id)
    @router.post('/me/requests/{request_id}/cancel')
    def cancel(request_id:str,body:Cancel,request:Request):
        clean(request)
        return transition_request(app.state.auth_service,token(request),'student',request_id,body.version,'cancel',body.comment,**context(request,True))
    @router.get('/staff/requests')
    def staff_list(request:Request,offset:int=0):return listing(request,'staff',offset)
    @router.get('/staff/requests/{request_id}')
    def staff_detail(request_id:str,request:Request):return detail(request,'staff',request_id)
    @router.post('/staff/requests/{request_id}/decision')
    def decision(request_id:str,body:Decision,request:Request):
        clean(request)
        return transition_request(app.state.auth_service,token(request),'staff',request_id,body.version,body.action,body.comment,**context(request,True))
    app.include_router(router)
