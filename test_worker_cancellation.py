import json,threading,unittest
from contextlib import ExitStack
from unittest.mock import Mock,patch
import app,studio,test_studio

class WorkerCancellationTests(unittest.TestCase):
    def setUp(self):
        test_studio.StudioTests.setUp(self)
        self.stack.enter_context(patch.object(app,'STOP',threading.Event()))
        self.stack.enter_context(patch.object(app,'event'))
        self.stack.enter_context(patch.object(studio,'capture'))
    tearDown=test_studio.StudioTests.tearDown

    def job(self,kind):
        with app.connect() as con:
            jid=con.execute("INSERT INTO studio_jobs(project_id,kind,status,payload) VALUES(1,?,'queued','{}')",(kind,)).lastrowid
        return {'project_id':1,'action':kind,'job_id':jid}

    def test_pause_before_dispatch_prevents_every_action(self):
        for kind,method in [('chat','chat'),('search','search'),('draft','draft'),('send','execute')]:
            with self.subTest(kind=kind):
                payload=self.job(kind);app.STOP.set()
                with patch.object(studio,method) as action:
                    studio.run(app,Mock(),payload);action.assert_not_called()
                with app.connect() as con:
                    row=con.execute('SELECT status,error FROM studio_jobs WHERE id=?',(payload['job_id'],)).fetchone()
                    self.assertEqual(row['status'],'paused');self.assertIn('暂停',json.loads(row['error'])['title'])

    def test_pause_during_initial_progress_prevents_action(self):
        payload=self.job('chat')
        with patch.object(studio.store,'progress',side_effect=lambda *a:app.STOP.set()),patch.object(studio,'chat') as action:
            studio.run(app,Mock(),payload);action.assert_not_called()

    def test_replayed_completed_job_cannot_run_again(self):
        payload=self.job('chat')
        with patch.object(studio,'chat') as action:
            studio.run(app,Mock(),payload);studio.run(app,Mock(),payload)
            action.assert_called_once()

    def test_pause_after_valid_ai_response_does_not_apply_new_plan(self):
        raw={'kind':'search','reply':'规划完成','plan':{'topic':'LOL','queries':['LOL剪辑'],'count':2}}
        def response(*args,**kwargs):app.STOP.set();return args[3](raw)
        with patch.object(studio.ai,'complete',side_effect=response) as paid:
            studio.run(app,Mock(),self.job('chat'));paid.assert_called_once()
        with app.connect() as con:self.assertEqual(json.loads(studio.project(con,1)['plan']),{})

    def test_pause_after_invalid_ai_response_does_not_start_paid_repair(self):
        def response(*args,**kwargs):app.STOP.set();return args[3]({'kind':'invalid'})
        with patch.object(studio.ai,'complete',side_effect=response) as paid:
            studio.run(app,Mock(),self.job('chat'));paid.assert_called_once()

    def test_platform_stop_preserves_reason_and_required_user_action(self):
        for raw,label,advice in [('操作过于频繁','平台','限制'),('登录已失效','登录','登录'),('页面要求安全验证','登录','验证')]:
            with self.subTest(raw=raw):
                app.STOP.clear()
                def blocked(*a):app.STOP.set();raise RuntimeError(raw)
                with patch.object(studio,'chat',side_effect=blocked):studio.run(app,Mock(),self.job('chat'))
                self.assertIn(label,app.STATE['studio_error']['title'])
                self.assertIn(advice,app.STATE['studio_error']['advice'])

    def test_stop_event_does_not_mask_budget_or_ai_transport_error(self):
        for raw,label in [('已达到授权20元AI预算','预算'),('DeepSeek HTTP 429','AI 服务')]:
            with self.subTest(raw=raw):
                app.STOP.clear()
                def blocked(*a):app.STOP.set();raise RuntimeError(raw)
                with patch.object(studio,'chat',side_effect=blocked):studio.run(app,Mock(),self.job('chat'))
                self.assertIn(label,app.STATE['studio_error']['title'])

if __name__=='__main__':unittest.main()
