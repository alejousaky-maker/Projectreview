"""Optional single-process RunPod lifecycle with persistent session deadlines."""
import json
import logging
import math
import os
import threading
import time
from pathlib import Path
import httpx
from backend_router import SetupRequired
from config import JOBS
from remote_client import worker_health
log=logging.getLogger('ugc.runpod')

class RunPodManager:
    def __init__(self,clock=time.time,transport=None,state_file=None):
        self.clock=clock;self.transport=transport;self.lock=threading.RLock()
        self.file=Path(state_file) if state_file else JOBS/'_runpod'/'session.json'
        self.active=0;self.started=None;self.idle_since=None;self.state='Stopped';self.pod_id=None
        self.closed=threading.Event();self.thread=None
        if self.file.is_file():
            try:
                data=json.loads(self.file.read_text());self.started=data.get('started');self.pod_id=data.get('pod_id')
                if self.started is not None:
                    if not isinstance(self.started,(int,float)) or not math.isfinite(self.started) or not isinstance(self.pod_id,str):raise ValueError('invalid session')
                    self.idle_since=self.clock();self.state='Running'
            except (OSError,ValueError,TypeError):
                self.started=None;self.state='Error'
                log.error(json.dumps({'event':'runpod_session_record_invalid','action':'verify Pod status in dashboard'}))

    def configured(self):return bool(os.getenv('RUNPOD_API_KEY') and os.getenv('RUNPOD_POD_ID'))
    def limits(self):
        try:idle=float(os.getenv('RUNPOD_IDLE_SHUTDOWN_MINUTES','5'))*60;maximum=float(os.getenv('RUNPOD_MAX_SESSION_MINUTES','30'))*60
        except ValueError:raise SetupRequired('RunPod timeout settings must be positive numbers','runpod_config')
        if not (math.isfinite(idle) and math.isfinite(maximum) and idle>0 and maximum>0):raise SetupRequired('RunPod timeouts must be positive','runpod_config')
        return idle,maximum
    def persist(self):
        self.file.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.file.with_suffix('.tmp');tmp.write_text(json.dumps({'started':self.started,'pod_id':self.pod_id}));tmp.replace(self.file)
    def api(self,method,action=''):
        if not self.configured():raise SetupRequired('Auto GPU mode requires RUNPOD_API_KEY and RUNPOD_POD_ID','runpod_config')
        pod=self.pod_id or os.environ['RUNPOD_POD_ID']
        if not all(c.isalnum() or c in '-_' for c in pod):raise SetupRequired('Invalid RunPod Pod ID','runpod_config')
        try:
            with httpx.Client(timeout=30,transport=self.transport) as client:
                result=client.request(method,'https://rest.runpod.io/v1/pods/'+pod+action,
                    headers={'Authorization':'Bearer '+os.environ['RUNPOD_API_KEY']})
            if not result.is_success:raise SetupRequired(f'RunPod API returned HTTP {result.status_code}','runpod_api')
            return result.json() if result.content else {}
        except (httpx.HTTPError,ValueError):raise SetupRequired('RunPod API unavailable','runpod_api') from None
    def get_pod_status(self):return self.api('GET')
    def start_pod(self):
        self.api('POST','/start');log.info(json.dumps({'event':'runpod_start','pod_id':self.pod_id}))
    def stop_pod(self):
        self.api('POST','/stop');log.info(json.dumps({'event':'runpod_stop','pod_id':self.pod_id}))
    def acquire(self):
        with self.lock:
            self.limits()
            if not self.configured():raise SetupRequired('Auto GPU mode is not configured; choose Manual','runpod_config')
            if self.state=='Error' and self.started is None:
                raise SetupRequired('GPU session record is invalid; verify the Pod stopped in RunPod before using Auto','runpod_state')
            if self.started is None and self.active:
                raise SetupRequired('Previous GPU session is finishing; retry after its jobs stop','runpod_session_limit')
            if self.started is None:
                self.pod_id=os.environ['RUNPOD_POD_ID'];self.started=self.clock();self.persist()
                self.state='Starting'
                try:
                    status=self.get_pod_status()
                    if status.get('desiredStatus')!='RUNNING':self.start_pod()
                except Exception:
                    # Retain session record: start may have reached RunPod even after a network timeout.
                    self.state='Error';self.idle_since=self.clock();raise
            if self.clock()-self.started>=self.limits()[1]:
                self.tick();raise SetupRequired('GPU session reached maximum time; wait for stop confirmation','runpod_session_limit')
            if self.state=='Error':raise SetupRequired('GPU lifecycle is in Error; inspect setup status','runpod_state')
            self.active+=1;self.idle_since=None
        self.start_monitor()
    def release(self):
        with self.lock:
            self.active=max(0,self.active-1)
            if not self.active:self.idle_since=self.clock()
    def wait_until_healthy(self,timeout=600):
        deadline=self.clock()+timeout
        while self.clock()<deadline:
            with self.lock:
                if not self.started or self.state=='Error':raise SetupRequired('GPU session stopped or entered Error','runpod_state')
            health=worker_health()
            if health.get('online'):
                with self.lock:self.state='Running'
                return health
            if self.closed.wait(5):break
        raise SetupRequired('Worker did not become healthy; inspect RunPod startup logs','worker_timeout')
    def tick(self):
        with self.lock:
            if self.started is None:return
            idle,maximum=self.limits();now=self.clock()
            reason='max_session' if now-self.started>=maximum else 'idle' if not self.active and self.idle_since is not None and now-self.idle_since>=idle else None
            if reason:
                try:
                    self.stop_pod();self.started=None;self.idle_since=None;self.state='Stopped';self.persist()
                    log.info(json.dumps({'event':'runpod_safety_stop','reason':reason}))
                except Exception:
                    self.state='Error';log.error(json.dumps({'event':'runpod_stop_failed','retry_seconds':5}))
            elif self.state!='Error' and not self.active and self.idle_since is not None:self.state='Idle countdown'
    def start_monitor(self):
        if self.thread and self.thread.is_alive():
            if not self.closed.is_set():return
            self.thread.join(timeout=1)
        self.closed.clear()
        def monitor():
            while not self.closed.wait(5):
                try:self.tick()
                except Exception:
                    self.state='Error';log.error(json.dumps({'event':'runpod_monitor_error'}))
        self.thread=threading.Thread(target=monitor,daemon=True);self.thread.start()
    def snapshot(self):
        with self.lock:
            remaining=None
            if self.started is not None and self.idle_since is not None:remaining=max(0,int(self.limits()[0]-(self.clock()-self.idle_since)))
            return {'configured':self.configured(),'state':self.state,'active_jobs':self.active,'idle_seconds_remaining':remaining,
                    'default_mode':'Manual','session_managed':self.started is not None}
    def close(self):
        self.closed.set()
        with self.lock:
            if self.started is not None:
                try:self.stop_pod();self.started=None;self.persist()
                except Exception:log.error(json.dumps({'event':'runpod_shutdown_stop_failed','action':'stop Pod in dashboard'}))
manager=RunPodManager()
