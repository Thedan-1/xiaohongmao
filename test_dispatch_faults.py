import threading,unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock,patch
import app,studio,test_studio

class DispatchFaultTests(unittest.TestCase):
    def setUp(self):
        test_studio.StudioTests.setUp(self)
        self.stack.enter_context(patch.object(app,'STOP',threading.Event()))
        self.stack.enter_context(patch.object(app,'event'))
    tearDown=test_studio.StudioTests.tearDown

    def test_queue_failure_does_not_leave_job_permanently_queued(self):
        with patch.object(app.COMMANDS,'put',side_effect=OSError('injected publication failure')):
            with self.assertRaises(ValueError):studio.request(app,{'action':'chat','project_id':1,'text':'搜索LOL'})
        with app.connect() as con:
            row=con.execute('SELECT status,error FROM studio_jobs').fetchone()
            self.assertEqual(row['status'],'failed');self.assertIn('publication failure',row['error'])
        self.assertTrue(studio.request(app,{'action':'chat','project_id':1,'text':'重新规划'})['ok'])

    def test_published_then_raised_job_cannot_later_dispatch(self):
        original=app.COMMANDS.put
        def broken(item):original(item);raise OSError('injected late publication failure')
        with patch.object(app.COMMANDS,'put',side_effect=broken):
            with self.assertRaises(ValueError):studio.request(app,{'action':'chat','project_id':1,'text':'搜索LOL'})
        _,payload=app.COMMANDS.get_nowait()
        with patch.object(studio,'chat') as action:studio.run(app,Mock(),payload);action.assert_not_called()

    def test_two_workers_cannot_claim_same_job(self):
        studio.request(app,{'action':'chat','project_id':1,'text':'搜索LOL'})
        _,payload=app.COMMANDS.get_nowait();barrier=threading.Barrier(2)
        def run(_):barrier.wait(3);studio.run(app,Mock(),payload)
        with patch.object(studio,'chat') as action,ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(run,range(2)));action.assert_called_once()

    def test_publication_error_after_worker_finished_preserves_acceptance(self):
        original=app.COMMANDS.put
        def late_error(item):
            original(item);_,payload=app.COMMANDS.get_nowait()
            studio.run(app,Mock(),payload)
            raise OSError('late error after completed worker')
        with patch.object(app.COMMANDS,'put',side_effect=late_error),patch.object(studio,'chat') as action:
            result=studio.request(app,{'action':'chat','project_id':1,'text':'搜索LOL'})
            self.assertTrue(result['ok']);action.assert_called_once()
        with app.connect() as con:self.assertEqual(con.execute('SELECT status FROM studio_jobs').fetchone()[0],'complete')

    def test_wrong_project_or_kind_cannot_claim_or_mutate_job(self):
        studio.request(app,{'action':'chat','project_id':1,'text':'搜索LOL'})
        _,payload=app.COMMANDS.get_nowait()
        with patch.object(studio,'chat') as chat,patch.object(studio,'execute') as send:
            studio.run(app,Mock(),{**payload,'project_id':2})
            studio.run(app,Mock(),{**payload,'action':'send'})
            chat.assert_not_called();send.assert_not_called()
        with app.connect() as con:self.assertEqual(con.execute('SELECT status FROM studio_jobs').fetchone()[0],'queued')

    def test_cancel_after_context_read_prevents_paid_chat_call(self):
        original=studio.state
        def context(*a):result=original(*a);app.STOP.set();return result
        with patch.object(studio,'state',side_effect=context),patch.object(studio.ai,'complete',return_value={'kind':'answer','reply':'hello'}) as paid:
            with self.assertRaises(RuntimeError):studio.chat(app,Mock(),{'project_id':1})
            paid.assert_not_called()

    def draft_state(self):return {'notes':[{'key':'n1','author':'客户','title':'剪辑'}],'people':[]}
    def draft_payload(self):return {'project_id':1,'channel':'note','mode':'ai','template':'你好','ids':['n1']}

    def test_cancel_after_read_prevents_paid_wording_call(self):
        def context(*a):app.STOP.set();return self.draft_state()
        with patch.object(studio,'state',side_effect=context),patch.object(studio.ai,'complete',return_value=['你好']) as paid:
            with self.assertRaises(RuntimeError):studio.draft(app,Mock(),self.draft_payload())
            paid.assert_not_called()

    def test_cancel_during_wording_response_does_not_save_draft(self):
        def response(*a,**kw):app.STOP.set();return ['你好']
        with patch.object(studio,'state',return_value=self.draft_state()),patch.object(studio.ai,'complete',side_effect=response):
            with self.assertRaises(RuntimeError):studio.draft(app,Mock(),self.draft_payload())
        with app.connect() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM studio_drafts').fetchone()[0],0)

if __name__=='__main__':unittest.main()
