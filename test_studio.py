import json
import queue
import tempfile
import unittest
from contextlib import ExitStack,nullcontext
from pathlib import Path
from unittest.mock import Mock,patch
import app,studio

class StudioTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();folder=self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.object(app,'DB',Path(folder)/'work.db'))
        self.stack.enter_context(patch.object(app,'STATE',{'task':'idle','account':{'profile_url':'https://www.xiaohongshu.com/user/profile/own','name':'本人'}}))
        self.stack.enter_context(patch.object(app,'COMMANDS',queue.Queue()))
        app.init_db();self.pid=1
    def tearDown(self):self.stack.close()
    def test_projects_isolate_messages_and_selected_plan(self):
        other=studio.request(app,{'action':'create'})['project_id']
        plan={'topic':'BIM','goal':'土建建模','queries':['Revit建模','土建建模'],'count':2}
        plan=studio.validate_plan(plan)
        with app.connect() as con:
            con.execute('UPDATE studio_projects SET plan=? WHERE id=?',(studio.dump(plan),self.pid))
            studio.store.set_step(con,self.pid,'ready')
        studio.request(app,{'project_id':self.pid,'action':'search','plan':plan})
        with app.connect() as con:
            self.assertEqual(studio.state(con,self.pid)['project']['plan']['queries'],plan['queries'])
            self.assertEqual(studio.state(con,other)['project']['plan'],{})
            self.assertEqual(len(studio.state(con,other)['messages']),1)
        command,payload=app.COMMANDS.get_nowait();self.assertEqual(command,'studio');self.assertEqual(payload['action'],'search')
    def test_chat_search_suggestion_never_executes_browser(self):
        with app.connect() as con:studio.message(con,self.pid,'user','搜BIM')
        raw={'kind':'search','reply':'请选择词','plan':{'topic':'BIM','goal':'工具','queries':['BIM建模','Revit'],'count':20}}
        with patch.object(studio.ai,'complete',side_effect=lambda s,d,l,v,**k:v(raw)):
            worker=Mock();studio.chat(app,worker,{'project_id':self.pid});self.assertFalse(worker.mock_calls)
        self.assertTrue(app.COMMANDS.empty())
    def test_account_changed_draft_cannot_send(self):
        with app.connect() as con:
            did=con.execute('INSERT INTO studio_drafts(project_id,account_id,channel,items) VALUES(?,?,?,?)',(self.pid,'another-account','dm','[]')).lastrowid
        worker=Mock()
        with patch.object(studio,'account'):
            with self.assertRaisesRegex(ValueError,'账号与预览时不同'):studio.execute(app,worker,{'project_id':self.pid,'draft_id':did,'confirmed':True})
        worker.send.assert_not_called()
    def test_send_requires_confirmation_and_preview_cannot_be_reused(self):
        with self.assertRaisesRegex(ValueError,'确认'):studio.execute(app,Mock(),{'project_id':self.pid,'draft_id':1})
        with app.connect() as con:
            did=con.execute('INSERT INTO studio_drafts(project_id,account_id,channel,items,status) VALUES(?,?,?,?,?)',(self.pid,'own','dm','[]','needs_review')).lastrowid
        with self.assertRaisesRegex(ValueError,'不能重复'):studio.execute(app,Mock(),{'project_id':self.pid,'draft_id':did,'confirmed':True})
    def test_discard_does_not_remove_history_or_sent_record(self):
        with app.connect() as con:
            a=con.execute("INSERT INTO studio_drafts(project_id,items,status) VALUES(?,'[]','preview')",(self.pid,)).lastrowid
            b=con.execute("INSERT INTO studio_drafts(project_id,items,status) VALUES(?,'[]','complete')",(self.pid,)).lastrowid
        studio.request(app,{'project_id':self.pid,'action':'discard','draft_id':a})
        with self.assertRaisesRegex(ValueError,'只能撤销'):studio.request(app,{'project_id':self.pid,'action':'discard','draft_id':b})
        with app.connect() as con:self.assertEqual(con.execute('SELECT status FROM studio_drafts WHERE id=?',(b,)).fetchone()[0],'complete')
    def test_failure_preserves_job_detail(self):
        studio.request(app,{'project_id':self.pid,'action':'chat','text':'搜索BIM'})
        _,payload=app.COMMANDS.get_nowait()
        with patch.object(studio.ai,'complete',side_effect=RuntimeError('DeepSeek HTTP 429')),patch.object(studio,'capture'),patch.object(app,'event'):
            studio.run(app,Mock(),payload)
        with app.connect() as con:
            s=studio.state(con,self.pid)
            self.assertEqual(s['jobs'][0]['status'],'failed');self.assertIn('429',s['jobs'][0]['error'])
            self.assertTrue(any(r['body']=='搜索BIM' for r in s['messages']))

    def test_uncertain_send_is_preserved_and_not_requeued(self):
        source={'profile_url':'https://www.xiaohongshu.com/user/profile/u1','author':'客户','note_url':'https://www.xiaohongshu.com/explore/n1','title':'BIM'}
        with app.connect() as con:
            did=con.execute('INSERT INTO studio_drafts(project_id,account_id,channel,items) VALUES(?,?,?,?)',(self.pid,app.STATE['account']['profile_url'],'dm',json.dumps([{'source':source,'message':'你好','status':'ready'}]))).lastrowid
        worker=Mock();worker.browser_operation.side_effect=lambda *a:nullcontext()
        with patch.object(studio,'account'),patch('adapter.send_direct_message',side_effect=RuntimeError('页面关闭，结果不明')):
            with self.assertRaises(RuntimeError):studio.execute(app,worker,{'project_id':self.pid,'draft_id':did,'confirmed':True})
        with app.connect() as con:
            d=dict(con.execute('SELECT * FROM studio_drafts WHERE id=?',(did,)).fetchone())
            self.assertEqual(d['status'],'needs_review');self.assertEqual(json.loads(d['items'])[0]['status'],'needs_review')

    def test_recovery_reuses_saved_text_without_new_search_or_reads(self):
        import batch_comments,threading
        from test_batch_comments import capture
        from contextlib import nullcontext
        worker=Mock();worker.browser_operation.side_effect=lambda *a:nullcontext()
        worker.page.locator.return_value.filter.return_value.first.get_attribute.return_value='/user/profile/own'
        with patch.object(batch_comments.ai,'budget',return_value={'reserved_or_peak_cost':0}),patch.object(batch_comments.adapter,'collect_search') as search,patch.object(batch_comments.note_collector,'collect_ready') as read,patch.object(batch_comments,'decide',side_effect=lambda t,g,ns:[{'id':batch_comments.compact(n)['id'],'relevant':True,'contacts':[],'author_contact':False} for n in ns]):
            batch_comments.find(worker,{'topic':'BIM','criteria':'土建工具','count':2,'resume_captures':[capture(0),capture(1)]},threading.Event(),app.connect,Mock(),Mock())
            search.assert_not_called();read.assert_not_called()
        with app.connect() as con:
            r=json.loads(con.execute('SELECT report FROM comment_runs ORDER BY id DESC LIMIT 1').fetchone()[0]);self.assertEqual(r['recovered_notes'],2);self.assertEqual(r['read'],2)

    def test_previously_contacted_person_is_skipped_not_counted_as_new_send(self):
        source={'profile_url':'https://www.xiaohongshu.com/user/profile/u1','author':'客户','note_url':'https://www.xiaohongshu.com/explore/n1','title':'BIM'}
        with app.connect() as con:
            studio.store.claim(con,self.pid,'dm',source,'old-account','此前已发送')
            studio.store.finish(con,self.pid,'dm',source,'sent')
            did=con.execute('INSERT INTO studio_drafts(project_id,account_id,channel,items) VALUES(?,?,?,?)',(self.pid,app.STATE['account']['profile_url'],'dm',json.dumps([{'source':source,'message':'你好','status':'ready'}]))).lastrowid
        worker=Mock()
        with patch.object(studio,'account'),patch.object(studio,'capture'):studio.execute(app,worker,{'project_id':self.pid,'draft_id':did,'confirmed':True})
        worker.send.assert_not_called()
        with app.connect() as con:
            self.assertEqual(json.loads(con.execute('SELECT items FROM studio_drafts WHERE id=?',(did,)).fetchone()[0])[0]['status'],'skipped')
            self.assertIn('已确认发送 0 条',con.execute('SELECT body FROM studio_messages ORDER BY id DESC LIMIT 1').fetchone()[0])

    def test_confirmed_comment_uses_existing_executor_with_frozen_text(self):
        import comment_flow
        source={'key':'n1','title':'标题','url':'https://www.xiaohongshu.com/explore/n1','author':'作者','profile_url':'https://www.xiaohongshu.com/user/profile/u1','body':'正文'}
        with app.connect() as con:did=con.execute('INSERT INTO studio_drafts(project_id,account_id,channel,items) VALUES(?,?,?,?)',(self.pid,app.STATE['account']['profile_url'],'note',json.dumps([{'source':source,'message':'已确认的原文','status':'ready'}]))).lastrowid
        def send(w,p,stop,db,update,event):
            with db() as con:
                target=dict(con.execute('SELECT * FROM comment_targets WHERE run_id=?',(p['run_id'],)).fetchone())
                self.assertEqual(target['message'],'已确认的原文');self.assertEqual(target['note_key'],'n1')
                con.execute("UPDATE comment_targets SET status='sent',result='测试回执' WHERE id=?",(target['id'],))
        with patch.object(studio,'account'),patch.object(studio,'capture'),patch.object(comment_flow,'send',side_effect=send) as sender:
            studio.execute(app,Mock(),{'project_id':self.pid,'draft_id':did,'confirmed':True});sender.assert_called_once()

if __name__=='__main__':unittest.main()
