import json
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock,patch
import app,studio,project_store,lead_review
import test_studio

class FlowTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown

    def plan(self):
        p=studio.validate_plan({'topic':'BIM','goal':'需要自动建模工具的工作室','queries':['BIM建模','Revit'],'count':20})
        with app.connect() as con:con.execute('UPDATE studio_projects SET plan=? WHERE id=?',(studio.dump(p),self.pid))
        return p

    def test_sequence_persists_rejects_bypass_and_stale_confirmation(self):
        p=self.plan()
        with self.assertRaisesRegex(ValueError,'依次确认'):studio.request(app,{'action':'search','project_id':1})
        def step(**data):return studio.request(app,{'action':'setup','project_id':1,**data})
        step(step='direction',queries=['Revit'])
        with self.assertRaisesRegex(ValueError,'这一步已更新'):step(step='direction',queries=['BIM'])
        with self.assertRaises(ValueError):step(step='count',count=20.5)
        step(step='count',count=50)
        step(step='goal',goal='需要土建自动建模工具的人')
        with app.connect() as con:
            state=studio.state(con,1)
            self.assertEqual(state['project']['setup_step'],'ready')
            self.assertEqual(state['project']['plan']['queries'],['Revit'])
            self.assertEqual(state['project']['plan']['count'],50)
        with self.assertRaisesRegex(ValueError,'方案已变更'):studio.request(app,{'action':'search','project_id':1,'plan':p})
        studio.request(app,{'action':'search','project_id':1})
        self.assertEqual(app.COMMANDS.get_nowait()[1]['action'],'search')

    def test_natural_language_confirmation_advances_only_current_step(self):
        self.plan()
        with app.connect() as con:project_store.set_step(con,1,'count')
        raw={'kind':'confirm','reply':'好的','step':'count','count':30}
        with patch.object(studio.ai,'complete',side_effect=lambda s,d,l,v,**k:v(raw)):
            studio.chat(app,Mock(),{'project_id':1})
        with app.connect() as con:
            self.assertEqual(project_store.setup(con,1),'goal')
            self.assertEqual(studio.state(con,1)['project']['plan']['count'],30)
        self.assertTrue(app.COMMANDS.empty())

    def test_receipts_share_between_accounts_but_not_projects_and_channels(self):
        source={'profile_url':'https://www.xiaohongshu.com/user/profile/u1?token=a','note_key':'n1','comment_id':'comment-c1'}
        changed={**source,'profile_url':source['profile_url'].split('?')[0]+'?token=b'}
        with app.connect() as con:
            self.assertTrue(project_store.claim(con,1,'dm',source,'account-A','你好'))
            project_store.finish(con,1,'dm',source,'sent')
            self.assertFalse(project_store.claim(con,1,'dm',changed,'account-B','不同文本'))
            self.assertTrue(project_store.claim(con,2,'dm',changed,'account-B','你好'))
            self.assertTrue(project_store.claim(con,1,'note',source,'account-A','1'))
            self.assertTrue(project_store.claim(con,1,'reply',source,'account-A','1'))
            self.assertFalse(project_store.claim(con,1,'reply',source,'account-B','2'))
            self.assertTrue(project_store.claim(con,1,'reply',{**source,'comment_id':'comment-c2'},'account-B','2'))

    def test_uncertain_blocks_and_definite_not_sent_allows_retry(self):
        x={'profile_url':'https://www.xiaohongshu.com/user/profile/u1'}
        with app.connect() as con:
            project_store.claim(con,1,'dm',x,'A','hello')
            project_store.finish(con,1,'dm',x,'needs_review')
            self.assertFalse(project_store.claim(con,1,'dm',x,'B','hello'))
            project_store.finish(con,1,'dm',x,'not_sent')
            self.assertTrue(project_store.claim(con,1,'dm',x,'B','hello'))

    def test_legacy_global_contacts_do_not_block_new_project(self):
        source={'profile_url':'https://www.xiaohongshu.com/user/profile/u1','author':'客户','note_url':'https://www.xiaohongshu.com/explore/n1','title':'BIM'}
        with app.connect() as con:
            lid=con.execute('INSERT INTO leads(profile_url,name) VALUES(?,?)',(source['profile_url'],'客户')).lastrowid
            con.execute("INSERT INTO contacts(lead_id,channel,message,status) VALUES(?,'dm','历史消息','sent')",(lid,))
            did=con.execute('INSERT INTO studio_drafts(project_id,account_id,channel,items) VALUES(?,?,?,?)',(1,app.STATE['account']['profile_url'],'dm',studio.dump([{'source':source,'message':'新项目','status':'ready'}]))).lastrowid
        worker=Mock();worker.browser_operation.side_effect=lambda *a:nullcontext()
        with patch.object(studio,'account'),patch.object(studio,'capture'),patch('adapter.send_direct_message',return_value='sent') as sender:
            studio.execute(app,worker,{'project_id':1,'draft_id':did,'confirmed':True})
            sender.assert_called_once()
        with app.connect() as con:self.assertEqual(project_store.status(con,1,'dm',source),'sent')

    def test_restart_marks_pending_uncertain_without_resetting_other_items(self):
        x={'profile_url':'https://www.xiaohongshu.com/user/profile/u1'}
        with app.connect() as con:
            project_store.claim(con,1,'dm',x,'A','你好')
            items=[{'source':x,'message':'你好','status':s} for s in ['sent','pending','ready']]
            did=con.execute("INSERT INTO studio_drafts(project_id,account_id,channel,items,status) VALUES(1,'A','dm',?,'sending')",(studio.dump(items),)).lastrowid
            project_store.recover(con)
            self.assertEqual(project_store.status(con,1,'dm',x),'needs_review')
            d=con.execute('SELECT status,items FROM studio_drafts WHERE id=?',(did,)).fetchone()
            self.assertEqual(d['status'],'needs_review')
            self.assertEqual([x['status'] for x in json.loads(d['items'])],['sent','needs_review','ready'])
            self.assertFalse(project_store.claim(con,1,'dm',x,'B','你好'))

    def test_project_cumulative_notes_and_seen_survive_topic_change(self):
        from test_batch_comments import capture
        with app.connect() as con:
            for rid,topic in [(1,'BIM'),(2,'Revit')]:
                con.execute('INSERT INTO comment_runs(id,topic,report) VALUES(?,?,?)',(rid,topic,'{}'))
                con.execute('INSERT INTO studio_runs(project_id,run_id) VALUES(1,?)',(rid,))
                n=capture(rid)
                con.execute('INSERT INTO comment_captures(run_id,note_key,capture) VALUES(?,?,?)',(rid,'n'+str(rid),studio.dump(n)))
            self.assertEqual(len(studio.state(con,1)['notes']),2)
            self.assertEqual(lead_review.unused_sources(con,'另一个名称',1)[1],{'n1','n2'})
            other=con.execute("INSERT INTO studio_projects(title,created_at,updated_at) VALUES('新项目','','')").lastrowid
            self.assertEqual(studio.state(con,other)['notes'],[])
            self.assertEqual(lead_review.unused_sources(con,'BIM',other),([],set()))

    def test_project_comment_executor_does_not_use_global_legacy_receipt(self):
        import comment_flow,threading
        x={'note_key':'n1','comment_id':''}
        with app.connect() as con:
            con.execute("INSERT INTO comment_sends VALUES('n1','note','','旧项目评论','sent','','')")
            project_store.claim(con,1,'note',x,'account','1')
            rid=con.execute("INSERT INTO comment_runs(topic,report) VALUES('BIM',?)",(studio.dump({'ai_before':0}),)).lastrowid
            con.execute("INSERT INTO comment_targets(run_id,note_key,title,note_url,kind,comment_id,message) VALUES(?,'n1','标题','https://www.xiaohongshu.com/explore/n1','note','','1')",(rid,))
        worker=Mock();worker.browser_operation.side_effect=lambda *a:nullcontext()
        with patch.object(comment_flow,'post_one',return_value={'verified_after_reload':True}) as post,patch.object(comment_flow.ai,'budget',return_value={'reserved_or_peak_cost':0}):
            comment_flow.send(worker,{'run_id':rid,'project_id':1},threading.Event(),app.connect,Mock(),Mock())
            post.assert_called_once()
            self.assertTrue(post.call_args.kwargs['local_receipt_checked'])
        with app.connect() as con:self.assertEqual(con.execute('SELECT message FROM comment_sends').fetchone()[0],'旧项目评论')

    def test_ui_one_question_activity_collapse_and_real_frame_gate(self):
        from playwright.sync_api import sync_playwright
        from edge_path import find_edge
        import tempfile
        root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()));(root/'data').mkdir()
        self.stack.enter_context(patch.object(studio,'ROOT',root))
        self.plan();app.STATE.update(login='ready',message='就绪')
        frames=[]
        def route(r):
            url=r.request.url
            if '/api/studio-frame' in url:
                if frames:r.fulfill(content_type='image/jpeg',body=frames[0])
                else:r.fulfill(status=404)
                return
            if '/api/studio' in url:
                if r.request.method=='POST':
                    result=studio.request(app,r.request.post_data_json)
                else:
                    with app.connect() as con:result=studio.state(con,1)
                    result.update(state=dict(app.STATE),ai={'budget':{'remaining':3.46}})
                r.fulfill(content_type='application/json',body=studio.dump(result));return
            r.fulfill(content_type='text/html',body=Path('ui.html').read_text(encoding='utf-8'))
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=find_edge(),headless=True)
            page=browser.new_page(viewport={'width':1500,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.route('**/*',route)
            page.goto('http://127.0.0.1:8765/?project=1');page.wait_for_selector('#setup-next')
            self.assertFalse(page.locator('#execution').is_visible());self.assertEqual(page.locator('#setup-count,#setup-goal').count(),0)
            page.locator('#setup-next').click();page.wait_for_selector('#setup-count')
            self.assertEqual(page.locator('[name=query],#setup-goal').count(),0)
            page.locator('[data-count="50"]').click();page.locator('#setup-next').click();page.wait_for_selector('#setup-goal')
            self.assertEqual(page.locator('#setup-count').count(),0)
            page.locator('#setup-next').click();page.wait_for_selector('#start-search')
            self.assertFalse(page.locator('#execution').is_visible())
            page.locator('#prompt').fill('解释一下');page.locator('#send-chat').click();page.wait_for_selector('.chat-activity')
            self.assertFalse(page.locator('#execution').is_visible());self.assertTrue(page.locator('.chat-activity').evaluate('e=>e.open'))
            with app.connect() as con:con.execute("UPDATE studio_jobs SET status='complete'")
            page.evaluate('refresh()');page.wait_for_function("!document.querySelector('.chat-activity').open")
            self.assertFalse(page.locator('.turn-record').evaluate('e=>e.open'))
            page.locator('.turn-record>summary').click()
            page.locator('.chat-activity summary').click();self.assertTrue(page.locator('.chat-activity').evaluate('e=>e.open'))
            page.evaluate('lastMessages="";renderMessages()')
            self.assertTrue(page.locator('.turn-record').evaluate('e=>e.open'))
            self.assertTrue(page.locator('.chat-activity').evaluate('e=>e.open'))
            page.screenshot(path='data/studio-stepflow-test.png',full_page=True)
            page.set_viewport_size({'width':430,'height':900});page.screenshot(path='data/studio-stepflow-mobile-test.png',full_page=True)
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            with app.connect() as con:
                con.execute("INSERT INTO studio_jobs(id,project_id,kind,status,payload,created_at) VALUES(99,1,'search','running','{}','2026-10-22T12:30:00')")
            app.STATE.update(task='studio',studio_project=1)
            page.evaluate('refresh()')
            self.assertFalse(page.locator('#execution').is_visible())
            frames.append(page.screenshot(type='jpeg'))
            (root/'data'/'studio-frame-1.json').write_text(studio.dump({'project_id':1,'job_id':99,'time':'2026-10-22T12:30:01','label':'实际搜索画面'}),encoding='utf-8')
            page.evaluate('refresh()');page.wait_for_function("!document.querySelector('#execution').classList.contains('hidden')")
            page.locator('#close-panel').click();page.evaluate('refresh()')
            self.assertFalse(page.locator('#execution').is_visible())
            self.assertEqual(errors,[])
            browser.close()

if __name__=='__main__':unittest.main()
