import subprocess,sys,time,threading,unittest
from types import SimpleNamespace
from unittest.mock import patch
import app
import studio,test_studio
from browser_guard import BrowserOperationTimeout

class BrowserConnectStallTests(unittest.TestCase):
    def test_stalled_reused_connection_is_bounded_and_releases_worker(self):
        process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],creationflags=subprocess.CREATE_NO_WINDOW)
        worker=app.BrowserWorker();worker.pw=SimpleNamespace(_impl_obj=SimpleNamespace(_connection=SimpleNamespace(_transport=SimpleNamespace(_proc=process))))
        stop=threading.Event();original=worker.browser_operation
        def stalled_launch(**kw):
            deadline=time.monotonic()+1.2
            while process.poll() is None and time.monotonic()<deadline:time.sleep(.02)
            raise RuntimeError('fixture stalled page.title')
        try:
            with patch.object(app,'STOP',stop),patch.object(app,'update'),patch.object(worker,'launch',side_effect=stalled_launch),patch.object(worker,'browser_operation',side_effect=lambda seconds=90:original(.2)):
                with self.assertRaises(BrowserOperationTimeout):worker.background()
            self.assertIsNone(worker.pw);self.assertTrue(stop.is_set());self.assertIsNotNone(process.poll())
        finally:
            if process.poll() is None:process.terminate()
            process.wait(timeout=4)

    def test_welcome_is_short_for_new_and_existing_records(self):
        test_studio.StudioTests.setUp(self)
        try:
            with app.connect() as con:
                studio.message(con,1,'assistant','这个项目有独立的对话、搜索结果和消息草稿。你今天想找什么？')
                self.assertEqual(studio.state(con,1)['messages'][-1]['body'],'你今天想找什么？')
            pid=studio.request(app,{'action':'create'})['project_id']
            with app.connect() as con:self.assertEqual(studio.state(con,pid)['messages'][0]['body'],'你今天想找什么？')
        finally:test_studio.StudioTests.tearDown(self)

    def test_search_updates_stale_complete_message_before_dispatch(self):
        from unittest.mock import Mock
        test_studio.StudioTests.setUp(self)
        try:
            app.STATE['message']='本步完成，结果已保存'
            with app.connect() as con:
                jid=con.execute("INSERT INTO studio_jobs(project_id,kind,status,payload) VALUES(1,'search','queued','{}')").lastrowid
            seen=[]
            with patch.object(app,'STOP',threading.Event()),patch.object(studio,'search',side_effect=lambda *a:seen.append(app.STATE['message'])):
                studio.run(app,Mock(),{'project_id':1,'action':'search','job_id':jid})
            self.assertEqual(len(seen),1);self.assertIn('正在连接',seen[0])
        finally:test_studio.StudioTests.tearDown(self)

if __name__=='__main__':unittest.main()
