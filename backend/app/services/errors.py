from fastapi import Request
from fastapi.responses import JSONResponse
from uuid import uuid4

async def http_exception_handler(request: Request, exc):
    request_id = request.headers.get('X-Request-ID') or str(uuid4())
    detail = exc.detail if hasattr(exc, 'detail') else 'Request failed'
    return JSONResponse(status_code=exc.status_code, content={
        'error': {'code': f'HTTP_{exc.status_code}', 'message': detail},
        'request_id': request_id,
    }, headers={'X-Request-ID': request_id})
