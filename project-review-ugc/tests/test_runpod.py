import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from app import app, GenerationRequest
from backend_router import SetupRequired
from remote_worker.worker import app as worker
from remote_client import worker_health
from runpod_manager import RunPodManager
from voice import prepare_voice
from personas import persona_details
from config import ROOT

class RunPodTests(unittest.TestCase):
    def test_worker_health_auth_missing_key_and_ready_fields(self):
        with TestClient(worker) as client,patch.dict(os.environ,{'UGC_REMOTE_API_KEY':''}):
            self.assertEqual(client.get('/health').status_code,503)
        with TestClient(worker) as client,patch.dict(os.environ,{'UGC_REMOTE_API_KEY':'test-key'}):
            self.assertEqual(client.get('/health').status_code,401)
            response=client.get('/health',headers={'Authorization':'Bearer test-key'})
            self.assertEqual(response.status_code,200)
            health=response.json()
            for key in ['ok','role','gpu_available','cuda_available','gpu_name','persona_ready','upstream_ready','models_ready','elevenlabs_configured','generation_ready']:
                self.assertIn(key,health)
            self.assertEqual(health['role'],'remote_gpu_worker')
            self.assertFalse(health['generation_ready'])
            self.assertNotIn('test-key',response.text)
            self.assertEqual(client.post('/render',headers={'Authorization':'Bearer test-key'},json={}).status_code,422)

    def test_remote_health_success_unauthorized_failed_and_missing_secrets(self):
        real_client=httpx.Client
        for code in [200,401,503]:
            def handle(request):
                self.assertEqual(request.headers['Authorization'],'Bearer hidden-key')
                return httpx.Response(code,json={'role':'remote_gpu_worker','gpu_name':'A40','cuda_available':True,'unexpected_secret':'never return'})
            with patch.dict(os.environ,{'UGC_REMOTE_API_URL':'https://worker.example','UGC_REMOTE_API_KEY':'hidden-key'}),patch('remote_client.httpx.Client',side_effect=lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw)):
                result=worker_health()
                self.assertEqual(result['online'],code==200)
                self.assertNotIn('unexpected_secret',result)
        with patch.dict(os.environ,{'UGC_REMOTE_API_URL':'','UGC_REMOTE_API_KEY':''}):
            self.assertFalse(worker_health()['online'])
        def broken(request):raise httpx.ConnectError('offline')
        with patch.dict(os.environ,{'UGC_REMOTE_API_URL':'https://worker.example','UGC_REMOTE_API_KEY':'hidden-key'}),patch('remote_client.httpx.Client',side_effect=lambda **kw:real_client(transport=httpx.MockTransport(broken),**kw)):
            self.assertIn('offline',worker_health()['error'])

    def test_elevenlabs_mock_missing_key_and_http_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=prepare_voice(['One tap makes reviews easier'],'project_review',Path(tmp),mock=True)
            self.assertTrue(Path(result['path']).stat().st_size>0)
            self.assertTrue(result['mock'])
            with patch.dict(os.environ,{'ELEVENLABS_API_KEY':'','ELEVENLABS_VOICE_ID':''}):
                with self.assertRaises(SetupRequired):prepare_voice(['Hello'],'project_review',Path(tmp))
            real_client=httpx.Client
            with patch.dict(os.environ,{'ELEVENLABS_API_KEY':'test-only','ELEVENLABS_VOICE_ID':'testvoice'}),patch('voice.httpx.Client',side_effect=lambda **kw:real_client(transport=httpx.MockTransport(lambda r:httpx.Response(401)),**kw)):
                with self.assertRaisesRegex(SetupRequired,'HTTP 401'):prepare_voice(['Hello'],'project_review',Path(tmp))

    def test_persona_validation_and_setup_no_secrets(self):
        self.assertIn('invalid persona id',persona_details('../escape')['missing'])
        self.assertEqual(persona_details('project_review')['status'],'Persona incomplete')
        with patch('remote_client.worker_health',return_value={'online':False,'error':'offline'}),TestClient(app) as client,patch.dict(os.environ,{'RUNPOD_API_KEY':'private-value','UGC_REMOTE_API_KEY':'private-value'}):
            status=client.get('/setup/status')
            self.assertNotIn('private-value',status.text)
            self.assertTrue(status.json()['runpod_api_key_configured'])
            self.assertEqual(client.get('/setup').status_code,200)
            self.assertTrue(client.get('/personas').json()['personas'])
            self.assertFalse(client.post('/gpu/test').json()['online'])
        self.assertEqual(GenerationRequest(topic='A bakery review').gpu_mode,'manual')

    def manager(self,tmp,now,calls,already=False):
        def handle(request):
            calls.append((request.method,request.url.path))
            self.assertEqual(request.headers['Authorization'],'Bearer fake-api-key')
            return httpx.Response(200,json={'desiredStatus':'RUNNING' if already else 'EXITED'})
        return RunPodManager(clock=lambda:now[0],transport=httpx.MockTransport(handle),state_file=Path(tmp)/'session.json')

    def test_auto_start_reuse_idle_stop(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'RUNPOD_API_KEY':'fake-api-key','RUNPOD_POD_ID':'testpod','RUNPOD_IDLE_SHUTDOWN_MINUTES':'5','RUNPOD_MAX_SESSION_MINUTES':'30'}):
            now=[100];calls=[];manager=self.manager(tmp,now,calls)
            manager.acquire();manager.acquire()
            self.assertEqual(sum(path.endswith('/start') for _,path in calls),1)
            manager.release();now[0]+=400;manager.tick()
            self.assertFalse(any(path.endswith('/stop') for _,path in calls))
            manager.release();now[0]+=301;manager.tick()
            self.assertEqual(manager.state,'Stopped')
            self.assertEqual(sum(path.endswith('/stop') for _,path in calls),1)
            manager.close()

    def test_auto_max_session_restart_and_stop_failure(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'RUNPOD_API_KEY':'fake-api-key','RUNPOD_POD_ID':'testpod','RUNPOD_MAX_SESSION_MINUTES':'1','RUNPOD_IDLE_SHUTDOWN_MINUTES':'5'}):
            now=[100];calls=[];manager=self.manager(tmp,now,calls,already=True)
            manager.acquire();self.assertFalse(any(path.endswith('/start') for _,path in calls))
            restarted=self.manager(tmp,now,calls,already=True)
            self.assertEqual(restarted.started,100)
            now[0]=161
            with patch.object(manager,'stop_pod',side_effect=SetupRequired('offline')):
                manager.tick();self.assertEqual(manager.state,'Error');self.assertIsNotNone(manager.started)
            manager.tick();self.assertEqual(manager.state,'Stopped');manager.close()
            restarted.tick();self.assertEqual(restarted.state,'Stopped');restarted.close()

    def test_manual_mode_needs_no_runpod_key_and_health_wait(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'RUNPOD_API_KEY':'','RUNPOD_POD_ID':''}):
            manager=RunPodManager(state_file=Path(tmp)/'state.json')
            self.assertFalse(manager.configured())
            with self.assertRaises(SetupRequired):manager.acquire()
            self.assertFalse((Path(tmp)/'state.json').exists())
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'RUNPOD_API_KEY':'fake-api-key','RUNPOD_POD_ID':'testpod'}):
            now=[100];calls=[];manager=self.manager(tmp,now,calls)
            manager.acquire()
            with patch('runpod_manager.worker_health',return_value={'online':True}):
                self.assertTrue(manager.wait_until_healthy()['online'])
            manager.release();manager.close()

    def test_shell_start_missing_key_and_occupied_port_no_chmod(self):
        env=dict(os.environ,UGC_REMOTE_API_KEY='')
        result=subprocess.run(['bash','remote_worker/start.sh'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
        self.assertNotEqual(result.returncode,0);self.assertIn('UGC_REMOTE_API_KEY',result.stderr)
        # Binding port 8091 proves the startup preflight catches conflicts.
        with socket.socket() as listener:
            listener.bind(('0.0.0.0',8091));listener.listen()
            result=subprocess.run(['bash','remote_worker/start.sh'],cwd=ROOT,env=dict(os.environ,UGC_REMOTE_API_KEY='test-only'),capture_output=True,text=True,timeout=30)
            self.assertNotEqual(result.returncode,0);self.assertIn('Port 8091',result.stderr)
        result=subprocess.run(['bash','remote_worker/runpod_bootstrap.sh'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0);self.assertIn('UGC_REMOTE_API_KEY',result.stderr)

if __name__=='__main__':unittest.main()

class TransportPipelineTests(unittest.TestCase):
    def test_render_preserves_controller_script_and_audio(self):
        # Patch only submission: validate real auth/body parsing and schema mapping.
        seen=[]
        def submit(request):seen.append(request);return {'job_id':'a'*32,'status':'queued'}
        with patch.dict(os.environ,{'UGC_REMOTE_API_KEY':'test-key'}),patch('remote_worker.worker.submit',side_effect=submit),TestClient(worker) as client:
            response=client.post('/render',headers={'Authorization':'Bearer test-key'},json={
                'request':{'topic':'Bakery reviews','gpu_mode':'auto','backend':'remote_gpu'},
                'segments':['One tap makes reviews easier'], 'voice_b64':base64.b64encode(b'example audio').decode()})
            self.assertEqual(response.status_code,202)
            self.assertEqual(seen[0]['_segments'],['One tap makes reviews easier'])
            self.assertEqual(seen[0]['backend'],'local_upstream')
            self.assertEqual(seen[0]['gpu_mode'],'manual')

    def test_remote_video_download_and_failed_worker(self):
        from generate import remote
        real_client=httpx.Client
        script=['One tap makes reviews easier'];jid='a'*32
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);audio=root/'speech.wav';audio.write_bytes(b'audio-fixture')
            payload=GenerationRequest(topic='Bakery reviews').model_dump()
            payload.update(_voice_path=str(audio))
            for status in ['completed','failed']:
                def handle(request):
                    self.assertEqual(request.headers['Authorization'],'Bearer test-key')
                    if request.url.path=='/render':
                        data=json.loads(request.content)
                        self.assertEqual(data['segments'],script)
                        self.assertEqual(base64.b64decode(data['voice_b64']),audio.read_bytes())
                        return httpx.Response(202,json={'job_id':jid})
                    if request.url.path=='/jobs/'+jid:
                        return httpx.Response(200,json={'status':status,'error':{'message':'Missing model'}})
                    return httpx.Response(200,content=b'not-real-video')
                with patch.dict(os.environ,{'UGC_REMOTE_API_URL':'https://worker.example','UGC_REMOTE_API_KEY':'test-key'}),patch('generate.httpx.Client',side_effect=lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw)):
                    if status=='failed':
                        with self.assertRaises(SetupRequired):remote(payload,root,{},lambda *a:None,script)
                    else:
                        target=remote(payload,root,{},lambda *a:None,script)
                        from editor import probe
                        with self.assertRaises(subprocess.CalledProcessError):probe(target)

    def test_tts_success_with_mock_provider_audio(self):
        # A locally created WAV exercises actual FFmpeg conversion, no paid calls.
        import io,wave
        blob=io.BytesIO()
        with wave.open(blob,'wb') as wav:
            wav.setparams((1,2,24000,0,'NONE','not compressed'));wav.writeframes(b'\0\0'*24000)
        real_client=httpx.Client
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'ELEVENLABS_API_KEY':'test-only','ELEVENLABS_VOICE_ID':'testvoice'}):
            def handle(request):
                self.assertEqual(request.headers['xi-api-key'],'test-only')
                self.assertEqual(json.loads(request.content)['text'],'One tap')
                return httpx.Response(200,content=blob.getvalue())
            with patch('voice.httpx.Client',side_effect=lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw)):
                result=prepare_voice(['One tap'],'project_review',Path(tmp))
            with wave.open(result['path']) as wav:
                self.assertEqual(wav.getframerate(),48000);self.assertEqual(wav.getnchannels(),2)

class StartupIntegrationTests(unittest.TestCase):
    def test_dependency_copy_without_chmod_or_copystat(self):
        script=(ROOT/'remote_worker/start.sh').read_text().split("<<'COPY'\n",1)[1].split('\nCOPY',1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'packages';(source/'example').mkdir(parents=True)
            (source/'example/test.py').write_text('installed=True')
            (source/'bin').mkdir();(source/'bin/unused').write_text('not needed')
            with patch('sys.argv',['copy',str(source),str(root/'target')]),patch('os.chmod',side_effect=OSError('unsupported')),patch('shutil.copystat',side_effect=OSError('unsupported')):
                exec(compile(script,'dependency-copy','exec'))
            self.assertTrue((root/'target/example/test.py').is_file())
            self.assertFalse((root/'target/bin').exists())

    def test_zip_bootstrap_first_run_and_repeat_preserves_persona(self):
        import zipfile
        script=(ROOT/'remote_worker/runpod_bootstrap.sh').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            workspace=Path(tmp)/'workspace';workspace.mkdir()
            archive=Path(tmp)/'main.zip'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('Projectreview-main/project-review-ugc/remote_worker/start.sh',
                           '#!/bin/bash\nset -eu\necho started > boot-confirmed.txt\n')
                z.writestr('Projectreview-main/project-review-ugc/personas/project_review/persona.json','{"display_name":"default"}')
            local=Path(tmp)/'bootstrap.sh'
            local.write_text(script.replace('/workspace',str(workspace)).replace('https://github.com/alejousaky-maker/Projectreview/archive/refs/heads/main.zip',archive.as_uri()))
            env=dict(os.environ,UGC_REMOTE_API_KEY='test-only')
            for repeat in [False,True]:
                result=subprocess.run(['bash',str(local)],env=env,capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stderr)
                project=workspace/'Projectreview/project-review-ugc'
                self.assertTrue((project/'boot-confirmed.txt').is_file())
                persona=project/'personas/project_review/persona.json'
                if not repeat:
                    persona.write_text('{"display_name":"preserved"}')
                    (project/'.env').write_text('LOCAL_SENTINEL=not-a-secret')
                else:
                    self.assertIn('preserved',persona.read_text())
                    self.assertEqual((project/'.env').read_text(),'LOCAL_SENTINEL=not-a-secret')

    def test_worker_live_system_python_without_venv_or_executable_scripts(self):
        import shutil,time
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'app';root.mkdir()
            for source in ROOT.glob('*.py'):shutil.copyfile(source,root/source.name)
            shutil.copyfile(ROOT/'requirements.txt',root/'requirements.txt')
            for directory in ['remote_worker','personas']:
                shutil.copytree(ROOT/directory,root/directory,ignore=shutil.ignore_patterns('__pycache__'),copy_function=shutil.copyfile)
            (root/'.worker-deps').symlink_to(next((ROOT/'.venv/lib').glob('python*/site-packages')),target_is_directory=True)
            self.assertFalse((root/'.venv').exists())
            env=dict(os.environ,UGC_REMOTE_API_KEY='startup-test-key',RUNPOD_API_KEY='',RUNPOD_POD_ID='')
            log=Path(tmp)/'worker.log'
            with log.open('w') as handle:
                process=subprocess.Popen(['bash',str(root/'remote_worker/start.sh')],env=env,stdout=handle,stderr=handle)
                try:
                    health=None
                    for _ in range(100):
                        if process.poll() is not None:self.fail(log.read_text())
                        try:
                            response=httpx.get('http://127.0.0.1:8091/health',headers={'Authorization':'Bearer startup-test-key'},timeout=1)
                            if response.status_code==200:health=response.json();break
                        except httpx.HTTPError:pass
                        time.sleep(.05)
                    self.assertIsNotNone(health,log.read_text())
                    self.assertEqual(health['role'],'remote_gpu_worker')
                    self.assertFalse(health['models_ready'])
                    self.assertEqual(httpx.get('http://127.0.0.1:8091/health').status_code,401)
                finally:
                    process.terminate();process.wait(timeout=10)
