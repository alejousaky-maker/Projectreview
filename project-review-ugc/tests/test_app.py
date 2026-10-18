import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import app
from backend_router import route, SetupRequired
from config import persona_status, UPSTREAM
from editor import edit, probe
from script_builder import build_script
from upstream_adapter import command

class ControllerTests(unittest.TestCase):
    def test_health_ui_and_persona(self):
        with TestClient(app) as client:
            self.assertEqual(client.get('/health').json()['server'],'ok')
            self.assertIn('One idea',client.get('/').text)
            self.assertEqual(client.get('/jobs/../secrets').status_code,404)
        self.assertEqual(persona_status()['status'],'persona incomplete')
        self.assertEqual(persona_status('../escape')['status'],'persona incomplete')

    def test_scripts_and_upstream_lint(self):
        import sys
        sys.path.insert(0,str(UPSTREAM))
        from factory.script_lint import lint_scripts
        for duration in [15,20,25,30,35]:
            script=build_script('Why a bakery needs reviews',business_type='bakery',duration=duration)
            self.assertTrue(script['segments'])
            self.assertTrue(all(1<=len(s.split())<=12 for s in script['segments']))
            self.assertEqual(lint_scripts(script['segments'],num_frames=121)[0],0)

    def test_worker_auth(self):
        from remote_worker.worker import app as worker
        with patch.dict(os.environ, {'UGC_REMOTE_API_KEY':'test-only-key'}), TestClient(worker) as client:
            self.assertEqual(client.get('/health').status_code,401)
            self.assertEqual(client.get('/health',headers={'Authorization':'Bearer test-only-key'}).status_code,200)

    def test_routes(self):
        with patch('backend_router.report',return_value={'gpu':{'cuda':False}}),patch.dict(os.environ,{'UGC_REMOTE_API_URL':''}):
            with self.assertRaises(SetupRequired):route()
        with patch('backend_router.report',return_value={'gpu':{'cuda':True}}):self.assertEqual(route(),'local_upstream')
        with patch('backend_router.report',return_value={'gpu':{'cuda':False}}),patch.dict(os.environ,{'UGC_REMOTE_API_URL':'https://worker.example'}):self.assertEqual(route(),'remote_gpu')

    def wait(self,client,jid):
        for _ in range(100):
            state=client.get('/jobs/'+jid).json()
            if state['status'] not in ('queued','running'):return state
            time.sleep(.02)
        self.fail('Job did not finish')

    def test_jobs_dry_run_and_no_false_completion(self):
        with TestClient(app) as client:
            r=client.post('/generate',json={'topic':'Bakery reviews','dry_run':True})
            self.assertEqual(r.status_code,202)
            state=self.wait(client,r.json()['job_id'])
            self.assertEqual(state['status'],'dry_run')
            self.assertIsNone(state['output_video'])
            self.assertIn('--scripts',state['command'])
            self.assertEqual(client.get('/videos/'+state['job_id']).status_code,404)
            with patch('generate.route',return_value='local_upstream'),patch('personas.persona_details',return_value={'status':'ready'}),patch('generate.prepare_voice',return_value={'path':'/tmp/unused.wav','mock':False}),patch('upstream_adapter.generate',return_value=Path('/tmp/nonexistent-video.mp4')):
                state=self.wait(client,client.post('/generate',json={'topic':'Bakery reviews'}).json()['job_id'])
                self.assertEqual(state['status'],'failed')
                self.assertIsNone(state['output_video'])
            self.assertEqual(client.post('/generate',json={'topic':'Hi','persona':'../escape'}).status_code,422)

    def test_editor_real_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=blue:s=180x320:r=24:d=0.5',
                '-f','lavfi','-i','sine=frequency=440:duration=0.5','-c:v','libx264','-threads','2','-c:a','aac','-shortest',str(source)],check=True)
            final=edit([source,source],root/'final.mp4',music=source,captions=True,lines=['Editor test only','Not generated creator footage'])
            data=probe(final)
            video=next(s for s in data['streams'] if s['codec_type']=='video')
            self.assertEqual((video['width'],video['height']),(1080,1920))
            self.assertGreater(float(data['format']['duration']),.8)

if __name__=='__main__':unittest.main()
