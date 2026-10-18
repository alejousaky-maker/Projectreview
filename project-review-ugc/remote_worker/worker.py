import hmac
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.responses import JSONResponse
from fastapi import FastAPI
from app import app as controller, lifespan
app = FastAPI(lifespan=lifespan)

@app.middleware('http')
async def authenticate(request, call_next):
    key=os.getenv('UGC_REMOTE_API_KEY')
    if not key:
        return JSONResponse({'error':'Worker requires UGC_REMOTE_API_KEY'},status_code=503)
    if not hmac.compare_digest(request.headers.get('Authorization',''),'Bearer '+key):
        return JSONResponse({'error':'Unauthorized'},status_code=401)
    return await call_next(request)

app.mount("/", controller)
