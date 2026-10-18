import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from config import ROOT, JOBS, OUTPUTS, persona_status
from doctor import report
from backend_router import route, SetupRequired
from generate import submit, read, save
logging.basicConfig(level=logging.INFO,format='%(message)s')

@asynccontextmanager
async def lifespan(app):
    for path in JOBS.glob('*.json'):
        job=json.loads(path.read_text())
        if job['status'] in ('queued','running'):
            job.update(status='failed',stage='interrupted',error={'code':'interrupted','message':'Server restarted; please submit again.'});save(job)
    from runpod_manager import manager
    manager.start_monitor()
    try:
        yield
    finally:
        manager.close()
app=FastAPI(title='Project Review UGC',lifespan=lifespan)

class GenerationRequest(BaseModel):
    topic: str=Field(min_length=3,max_length=1000)
    audience: str=Field(default='local business owners',max_length=150)
    business_type: str=Field(default='general local business',max_length=60)
    tone: str=Field(default='casual',max_length=60)
    duration: int=Field(default=25,ge=15,le=35)
    cta_style: str=Field(default='try one tap',max_length=100)
    style: str=Field(default='educational',max_length=60)
    persona: str=Field(default='project_review',pattern=r'^[a-zA-Z0-9_-]+$',max_length=80)
    backend: Literal['auto','local_upstream','remote_gpu']='auto'
    best_of: int=Field(default=1,ge=1,le=3)
    frames: Literal[121,129,161]=121
    gpu: int=Field(default=0,ge=0,le=15)
    captions: bool=False
    dry_run: bool=False
    music: str | None=None
    voice_provider: Literal['elevenlabs','reference','espeak']='elevenlabs'
    gpu_mode: Literal['manual','auto']='manual'

@app.get('/',response_class=HTMLResponse)
def index(): return (ROOT/'web.html').read_text()

@app.get('/health')
def health():
    status=report()
    try: backend={'status':'configured','selected':route()}
    except SetupRequired as exc: backend={'status':'setup_required','message':str(exc)}
    return {'server':'ok','backend':backend,'persona':persona_status(),'ffmpeg':status['ffmpeg'],
      'gpu':status['gpu'],'classification':status['classification'],'generation_assets_missing':status['missing_generation_assets']}

@app.post('/generate',status_code=202)
def generate(request:GenerationRequest):
    if request.music:
        raise HTTPException(422,'Music paths are accepted only by the trusted local editor API; public generation does not accept server filesystem paths.')
    return submit(request.model_dump())

@app.get('/jobs/{job_id}')
def job(job_id:str):
    try:return read(job_id)
    except FileNotFoundError:raise HTTPException(404,'Job not found')

@app.get('/videos/{job_id}')
def video(job_id:str):
    state=job(job_id);path=OUTPUTS/job_id/'final.mp4'
    if state['status']!='completed' or not path.is_file():raise HTTPException(404,'No completed video')
    return FileResponse(path,media_type='video/mp4')

@app.get('/personas')
def personas():
    from personas import list_personas
    return {'personas':list_personas()}

@app.post('/gpu/test')
def test_gpu():
    from remote_client import worker_health
    return worker_health()

@app.get('/gpu/status')
def gpu_status():
    from runpod_manager import manager
    return manager.snapshot()

@app.get('/setup',response_class=HTMLResponse)
def setup_page():return (ROOT/'setup.html').read_text()

@app.get('/setup/status')
def setup_status():
    from remote_client import worker_health
    from voice import configured
    from runpod_manager import manager
    return {'github_code':'ready','runpod_url_configured':bool(os.getenv('UGC_REMOTE_API_URL')),
      'runpod_api_key_configured':bool(os.getenv('RUNPOD_API_KEY')),
      'worker_key_configured':bool(os.getenv('UGC_REMOTE_API_KEY')),
      'elevenlabs_configured':configured(),'personas':personas()['personas'],
      'remote_worker':worker_health(),'gpu_lifecycle':manager.snapshot()}
