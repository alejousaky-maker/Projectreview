import base64
import hmac
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from app import app as controller, lifespan, GenerationRequest
from generate import submit
from readiness import worker_status
app=FastAPI(lifespan=lifespan)

@app.middleware('http')
async def authenticate(request,call_next):
    key=os.getenv('UGC_REMOTE_API_KEY','')
    if not key.strip():return JSONResponse({'error':'Worker requires UGC_REMOTE_API_KEY'},status_code=503)
    if not hmac.compare_digest(request.headers.get('Authorization',''),'Bearer '+key):
        return JSONResponse({'error':'Unauthorized'},status_code=401)
    # Bound incoming bodies before JSON/base64 parsing.
    if request.method=='POST':
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>12_000_000:return JSONResponse({'error':'Request too large'},status_code=413)
        request._body=bytes(body)
    return await call_next(request)

@app.get('/health')
def health():return worker_status()

class RenderRequest(BaseModel):
    request: GenerationRequest
    segments: list[str]=Field(min_length=1,max_length=20)
    voice_b64: str | None=Field(default=None,max_length=11_000_000)

@app.post('/render',status_code=202)
def render(body:RenderRequest):
    if any(not line.strip() or len(line)>300 for line in body.segments):raise HTTPException(422,'Invalid script segments')
    payload=body.request.model_dump()
    if payload['music']:raise HTTPException(422,'Filesystem music paths are not accepted')
    if body.voice_b64:
        try:base64.b64decode(body.voice_b64,validate=True)
        except ValueError:raise HTTPException(422,'Invalid voice data') from None
    payload.update(backend='local_upstream',gpu_mode='manual',_segments=body.segments,_voice_b64=body.voice_b64)
    return submit(payload)

@app.post('/generate',status_code=202)
def generate(request:GenerationRequest):
    payload=request.model_dump()
    if payload['music']:raise HTTPException(422,'Filesystem music paths are not accepted')
    payload.update(backend='local_upstream',gpu_mode='manual')
    return submit(payload)

app.mount('/',controller)
