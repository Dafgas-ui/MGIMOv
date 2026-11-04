"""Bounded JSON requests with exact origin/host; no CORS or unsafe bypass."""
import asyncio
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

class IdentityGuard:
    def __init__(self, app, settings, body_timeout=10.0):
        self.app,self.settings=app,settings
        self.body_timeout=body_timeout

    async def __call__(self,scope,receive,send):
        path=scope.get('path','')
        if scope['type']!='http' or not path.startswith(('/api/v1/auth/','/api/v1/me/')):
            return await self.app(scope,receive,send)
        headers=Headers(scope=scope); config=self.settings
        async def secure_send(message):
            if message['type']=='http.response.start':
                message['headers']=list(message['headers'])+[(b'cache-control',b'no-store'),(b'referrer-policy',b'no-referrer'),(b'x-content-type-options',b'nosniff')]
            await send(message)
        async def reject(code):
            await JSONResponse({'detail':'Запрос отклонён проверкой безопасности.'},status_code=code)(scope,receive,secure_send)
        if headers.getlist('host')!=[config.host] or scope.get('scheme')!=('https' if config.secure else 'http'):
            return await reject(400)
        origins=headers.getlist('origin')
        if len(origins)>1 or (origins and origins!=[config.origin]) or headers.get('sec-fetch-site') not in (None,'same-origin','none'):
            return await reject(403)
        if len(headers.getlist('x-csrf-token'))>1 or len(headers.getlist('x-mgimov-user'))>1:
            return await reject(400)
        async def read_body():
            body=bytearray()
            while True:
                message=await receive()
                if message['type']=='http.disconnect':return None
                body.extend(message.get('body',b''))
                if len(body)>8192:return False
                if not message.get('more_body',False):return body
        try:
            body=await asyncio.wait_for(read_body(),timeout=self.body_timeout)
        except TimeoutError:
            return await reject(408)
        if body is None:return
        if body is False:return await reject(413)
        if scope['method'] in ('GET','HEAD'):
            if body:return await reject(422)
        elif scope['method'] in ('POST','PUT','PATCH','DELETE'):
            if origins!=[config.origin]:return await reject(403)
            if headers.get('content-type','').split(';')[0].strip().lower()!='application/json':return await reject(415)
        delivered=False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered=True
                return {'type':'http.request','body':bytes(body),'more_body':False}
            return await receive()
        await self.app(scope,replay,secure_send)
