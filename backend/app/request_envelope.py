"""Count raw API bytes without buffering or trusting normalized payloads."""
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException


class RequestEnvelopeMiddleware:
    def __init__(self, app, maximum: int):
        self.app,self.maximum=app,maximum

    async def __call__(self, scope, receive, send):
        if scope['type']!='http' or not scope.get('path','').startswith('/v1/'):
            return await self.app(scope,receive,send)
        response=JSONResponse({'detail':'Request exceeds total byte limit.'},status_code=413,
            headers={'connection':'close'})
        # Authentication is outside this middleware. An honest large length
        # needs no body read, engine reservation, parser spool or source call.
        for name,value in scope.get('headers',[]):
            if name.lower()==b'content-length':
                try: declared=int(value)
                except ValueError: continue  # streaming count remains authoritative
                if declared>self.maximum: return await response(scope,receive,send)
        total=0
        exceeded=False
        started=False
        refused=False
        multipart=any(name.lower()==b'content-type' and value.lower().startswith(b'multipart/form-data')
            for name,value in scope.get('headers',[]))

        async def bounded_receive():
            nonlocal total,exceeded
            message=await receive()
            if message['type']=='http.request':
                total+=len(message.get('body',b''))
                if total>self.maximum:
                    exceeded=True
                    # Starlette's parser closes every opened spool on this
                    # exception. No multipart file is leaked on streaming refusal.
                    if multipart: raise MultiPartException('Request exceeds total byte limit.')
                    raise HTTPException(413,'Request exceeds total byte limit.')
            return message

        async def bounded_send(message):
            nonlocal started,refused
            if exceeded:
                if not refused:
                    if started: raise RuntimeError('Request exceeded byte limit after response started')
                    refused=True
                    await response(scope,receive,send)
                return
            if message['type']=='http.response.start': started=True
            await send(message)

        try:
            await self.app(scope,bounded_receive,bounded_send)
        except (HTTPException,MultiPartException):
            if not exceeded or started: raise
            if not refused: await response(scope,receive,send)
