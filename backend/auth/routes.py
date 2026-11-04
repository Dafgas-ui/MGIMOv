"""Public login bootstrap, login, and server-protected own identity routes."""
import hmac
import secrets
import sqlite3
from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from .service import AuthError, AuthService, valid_token
from .http import IdentityGuard
from ..profiles import own_profile
from ..security.passwords import PasswordCapacityError

class Login(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    login:str=Field(min_length=3,max_length=64,pattern=r'^[a-zA-Z0-9_.-]+$')
    password:SecretStr=Field(min_length=1,max_length=128)

class Empty(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)

def install_identity(app,settings):
    service=AuthService(settings)
    app.state.auth_service=service
    app.add_middleware(IdentityGuard,settings=settings)
    router=APIRouter(prefix='/api/v1')
    def clean_query(request):
        if request.query_params:raise AuthError(422,'Параметры выбора пользователя не принимаются.')
    def cookie(response,name,value,httponly,max_age):
        response.set_cookie(name,value,max_age=max_age,path='/',secure=settings.secure,httponly=httponly,samesite='strict')

    @app.exception_handler(AuthError)
    async def auth_error(request,error):
        return JSONResponse({'detail':error.message},status_code=error.status,headers={'Retry-After':'60'} if error.status==429 else None)
    @app.exception_handler(RequestValidationError)
    async def validation_error(request,error):
        if request.url.path.startswith(('/api/v1/auth/','/api/v1/me/')):
            return JSONResponse({'detail':'Проверьте формат и длину полей.'},status_code=422)
        return await request_validation_exception_handler(request,error)
    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(OSError)
    async def storage_error(request,error):
        return JSONResponse({'detail':'Сервис временно недоступен.'},status_code=503)
    @app.exception_handler(UnicodeError)
    async def encoding_error(request,error):
        return JSONResponse({'detail':'Некорректная кодировка поля.'},status_code=422)

    @app.exception_handler(PasswordCapacityError)
    async def busy(request,error):
        return JSONResponse({'detail':'Сервис входа занят. Повторите позже.'},status_code=503)

    @router.get('/auth/csrf')
    def bootstrap(request:Request,response:Response):
        clean_query(request)
        token=secrets.token_urlsafe(32)
        cookie(response,settings.login_csrf_cookie,token,True,600)
        return {'csrf':token}

    @router.post('/auth/login')
    def login(body:Login,request:Request,response:Response):
        clean_query(request)
        header=request.headers.get('x-csrf-token'); saved=request.cookies.get(settings.login_csrf_cookie)
        if not valid_token(header) or not valid_token(saved) or not hmac.compare_digest(header,saved):
            raise AuthError(403,'Проверка CSRF не пройдена.')
        user,token,csrf=service.login(body.login,body.password.get_secret_value(),request.client.host if request.client else 'unknown',request.cookies.get(settings.session_cookie))
        cookie(response,settings.session_cookie,token,True,settings.session_seconds)
        cookie(response,settings.csrf_cookie,csrf,False,settings.session_seconds)
        response.delete_cookie(settings.login_csrf_cookie,path='/',secure=settings.secure,httponly=True,samesite='strict')
        return {'user':user}

    @router.get('/auth/me')
    def me(request:Request):
        clean_query(request)
        return {'user':service.me(request.cookies.get(settings.session_cookie),request.headers.get('x-mgimov-user'))}

    @router.get('/me/profile')
    def profile(request:Request):
        clean_query(request)
        return own_profile(service,request.cookies.get(settings.session_cookie),request.headers.get('x-mgimov-user'))

    @router.post('/auth/logout',status_code=204)
    def logout(body:Empty,request:Request):
        clean_query(request)
        service.logout(request.cookies.get(settings.session_cookie),request.headers.get('x-csrf-token'),request.cookies.get(settings.csrf_cookie),request.headers.get('x-mgimov-user'))
        response=Response(status_code=204)
        for name,http in [(settings.session_cookie,True),(settings.csrf_cookie,False),(settings.login_csrf_cookie,True)]:
            response.delete_cookie(name,path='/',secure=settings.secure,httponly=http,samesite='strict')
        return response
    app.include_router(router)
