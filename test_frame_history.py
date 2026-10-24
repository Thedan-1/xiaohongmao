import json,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import Mock,patch
from contextlib import nullcontext
import app,studio
from test_http_admission import HttpAdmissionTests

class FrameHistoryTests(unittest.TestCase):
    setUp=HttpAdmissionTests.setUp
    tearDown=HttpAdmissionTests.tearDown
    def get(self,path):
        q=urllib.request.Request('http://127.0.0.1:'+str(self.server.server_port)+path,headers={'X-App-Token':app.TOKEN})
        try:
            with urllib.request.urlopen(q,timeout=4) as r:return r.status,r.read()
        except urllib.error.HTTPError as r:return r.code,r.read()
    def test_dm_proof_and_review_screenshots_are_project_scoped(self):
        folder=Path(app.DB).parent/'data';folder.mkdir()
        items=[{'source':{'profile_url':'https://www.xiaohongshu.com/user/profile/u','author':'A'},'message':'hello','status':'sent'},
               {'source':{'profile_url':'https://www.xiaohongshu.com/user/profile/v','author':'B'},'message':'hello','status':'needs_review'}]
        with app.connect() as con:
            did=con.execute("INSERT INTO studio_drafts(project_id,channel,items,status) VALUES(1,'dm',?,'needs_review')",(json.dumps(items),)).lastrowid
            other=studio.archive.create(con,'other')
        (folder/f'sent-project-1-draft-{did}-0.png').write_bytes(b'sent proof')
        (folder/f'send-review-project-1-draft-{did}-1.png').write_bytes(b'uncertain proof')
        with patch.object(app,'DATA',folder),patch.object(studio,'ROOT',folder.parent):
            with app.connect() as con:d=studio.state(con,1)['drafts'][0]
            self.assertEqual(len([x for x in d['items'] if x.get('dm_proof')]),2)
            self.assertEqual(self.get(f'/api/studio-dm-proof?project=1&draft={did}&item=0'),(200,b'sent proof'))
            self.assertEqual(self.get(f'/api/studio-dm-proof?project=1&draft={did}&item=1'),(200,b'uncertain proof'))
            self.assertEqual(self.get(f'/api/studio-dm-proof?project={other}&draft={did}&item=0')[0],404)
    def test_capture_links_job_and_history_http_is_scoped_to_project(self):
        folder=Path(app.DB).parent/'frames';folder.mkdir()
        with app.connect() as con:
            con.execute("INSERT INTO studio_jobs(id,project_id,kind,status,payload) VALUES(8,1,'search','running','{}')")
            con.execute("INSERT INTO studio_activity(job_id,project_id,body,created_at) VALUES(8,1,'first','now')")
        worker=Mock();worker.page.is_closed.return_value=False;worker.page.url='http://fixture/note';worker.studio_job_id=8
        worker.page.screenshot.return_value=b'first frame';worker.browser_operation.side_effect=lambda *a:nullcontext()
        with patch.object(app,'DATA',folder):
            studio.capture(worker,app,1,'first stage',True)
            worker.page.screenshot.return_value=b'second frame';studio.capture(worker,app,1,'second stage',True)
        with app.connect() as con:
            frames=studio.state(con,1)['jobs'][0]['frames'];other=studio.archive.create(con,'other')
        self.assertEqual(len(frames),2);self.assertEqual(frames[0]['label'],'first stage')
        self.assertIsNotNone(frames[0]['activity_id'])
        self.assertEqual(self.get('/api/studio-frame?project=1&frame='+str(frames[0]['id'])),(200,b'first frame'))
        self.assertEqual(self.get(f'/api/studio-frame?project={other}&frame='+str(frames[0]['id']))[0],404)
        with app.connect() as con:con.execute("UPDATE studio_projects SET archived_at='now' WHERE id=1")
        self.assertEqual(self.get('/api/studio-frame?project=1&frame='+str(frames[0]['id']))[0],404)
    def test_stage_storage_keeps_twenty_per_job(self):
        folder=Path(app.DB).parent/'frames';folder.mkdir()
        with app.connect() as con:con.execute("INSERT INTO studio_jobs(id,project_id,kind,status,payload) VALUES(8,1,'search','running','{}')")
        worker=Mock();worker.page.is_closed.return_value=False;worker.page.url='http://fixture/note';worker.studio_job_id=8
        worker.page.screenshot.return_value=b'frame';worker.browser_operation.side_effect=lambda *a:nullcontext()
        with patch.object(app,'DATA',folder):
            for i in range(24):studio.capture(worker,app,1,'stage '+str(i),True)
        with app.connect() as con:frames=studio.state(con,1)['jobs'][0]['frames']
        self.assertEqual(len(frames),20);self.assertEqual(frames[0]['label'],'stage 4');self.assertEqual(frames[-1]['label'],'stage 23')

if __name__=='__main__':unittest.main()
