import json,tempfile,threading,time,unittest
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import workflow_ai
import app,studio,project_store,test_studio
from unittest.mock import Mock
from contextlib import nullcontext

class BudgetCampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name);(root/'data').mkdir();(root/'deepseek.local.txt').write_text('DEEPSEEK_API_KEY=offline-fixture\n',encoding='utf-8')
        self.patch=patch.object(workflow_ai.client,'ROOT',root);self.patch.start()
    def tearDown(self):self.patch.stop();self.tmp.cleanup()

    def test_authorization_increase_preserves_all_prior_liability(self):
        con=workflow_ai._db()
        with con:con.execute('INSERT INTO calls(session,label,reserved,status,details) VALUES(?,?,?,?,?)',(workflow_ai.client.SESSION,'previous',4.5,'reserved','{}'))
        con.close();before=workflow_ai.budget()
        after=workflow_ai.authorize_budget(20,'explicit test authorization')
        self.assertEqual(before['reserved_or_peak_cost'],after['reserved_or_peak_cost'])
        self.assertEqual(after['remaining'],15.5);self.assertEqual(workflow_ai.budget()['limit'],20)

    def test_concurrent_requests_cannot_reserve_over_the_budget(self):
        workflow_ai.authorize_budget(.05,'test cap');entered=threading.Event();release=threading.Event()
        response={'usage':{'total_tokens':2,'prompt_tokens':1,'completion_tokens':1},'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}
        def request(*a):entered.set();release.wait(4);return response
        def run(i):
            try:return workflow_ai.complete('x',{'i':i},'race',lambda x:x)
            except RuntimeError:return 'blocked'
        with patch.object(workflow_ai.client,'request',side_effect=request) as call,ThreadPoolExecutor(max_workers=4) as pool:
            futures=[pool.submit(run,i) for i in range(4)]
            self.assertTrue(entered.wait(3))
            deadline=time.monotonic()+3
            while sum(f.done() for f in futures)<3 and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(sum(f.done() for f in futures),3)
            self.assertLessEqual(workflow_ai.budget()['reserved_or_peak_cost'],.05)
            release.set();results=[f.result() for f in futures]
            self.assertEqual(results.count('blocked'),3);call.assert_called_once()

    def test_invalid_authorization_cannot_disable_budget_ceiling(self):
        for value in (float('inf'),float('nan'),-1,0,True,'20'):
            with self.subTest(value=value),self.assertRaises(ValueError):workflow_ai.authorize_budget(value,'test')
        with self.assertRaises(ValueError):workflow_ai.authorize_budget(20,'')

class ReceiptRaceTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown

    def test_two_accounts_race_for_one_person_only_one_can_claim(self):
        x={'profile_url':'https://www.xiaohongshu.com/user/profile/one?token=A'};barrier=threading.Barrier(8)
        def claim(i):
            barrier.wait(3)
            with app.connect() as con:return project_store.claim(con,1,'dm',{**x,'profile_url':x['profile_url'].replace('A',str(i))},'account-'+str(i),'hello')
        with ThreadPoolExecutor(max_workers=8) as pool:outcomes=list(pool.map(claim,range(8)))
        self.assertEqual(sum(outcomes),1)
        with app.connect() as con:self.assertEqual(project_store.status(con,1,'dm',x),'pending')

    def test_duplicate_execution_of_same_draft_is_rejected_atomically(self):
        x={'profile_url':'https://www.xiaohongshu.com/user/profile/one','author':'客户','note_url':'https://www.xiaohongshu.com/explore/n1','title':'标题'}
        with app.connect() as con:did=con.execute('INSERT INTO studio_drafts(project_id,account_id,channel,items) VALUES(?,?,?,?)',(1,app.STATE['account']['profile_url'],'dm',studio.dump([{'source':x,'message':'hello','status':'ready'}]))).lastrowid
        barrier=threading.Barrier(2)
        def execute(_):
            worker=Mock();worker.browser_operation.side_effect=lambda *a:nullcontext()
            try:studio.execute(app,worker,{'project_id':1,'draft_id':did,'confirmed':True});return 'executed'
            except ValueError:return 'rejected'
        with patch.object(studio,'account',side_effect=lambda *a:barrier.wait(3)),patch.object(studio,'capture'),patch('adapter.send_direct_message',return_value='sent') as send,ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(execute,range(2)))
            self.assertEqual(results.count('executed'),1);self.assertEqual(results.count('rejected'),1);send.assert_called_once()
            self.assertEqual(send.call_args.args[1].get('expected_account'),app.STATE['account']['profile_url'])
        with app.connect() as con:self.assertEqual(project_store.status(con,1,'dm',x),'sent')

class AdmissionRaceTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown

    def test_dequeued_job_still_blocks_new_submission(self):
        studio.request(app,{'action':'chat','project_id':1,'text':'搜索LOL'})
        app.COMMANDS.get_nowait()  # Worker dequeued, but has not published running state.
        with self.assertRaises(ValueError):
            studio.request(app,{'action':'chat','project_id':1,'text':'再次搜索'})
        with app.connect() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM studio_jobs').fetchone()[0],1)

    def test_simultaneous_submissions_only_admit_one(self):
        entered=threading.Event();release=threading.Event();original=app.COMMANDS.put
        def delayed_put(item):
            entered.set();release.wait(3);original(item)
        def submit(text):
            try:studio.request(app,{'action':'chat','project_id':1,'text':text});return 'accepted'
            except ValueError:return 'rejected'
        with patch.object(app.COMMANDS,'put',side_effect=delayed_put),ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(submit,'搜索LOL');self.assertTrue(entered.wait(2))
            second=pool.submit(submit,'搜索BIM');time.sleep(.1);release.set()
            results=[first.result(),second.result()]
        self.assertEqual(results.count('accepted'),1)
        self.assertEqual(results.count('rejected'),1)

    def test_archive_waits_for_committed_job_before_queue_publication(self):
        entered=threading.Event();release=threading.Event();original=app.COMMANDS.put
        def delayed_put(item):entered.set();release.wait(3);original(item)
        other=studio.request(app,{'action':'create'})['project_id']
        def archive_other():
            try:studio.request(app,{'action':'archive','project_id':other});return 'archived'
            except ValueError:return 'blocked'
        with patch.object(app.COMMANDS,'put',side_effect=delayed_put),ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(studio.request,app,{'action':'chat','project_id':1,'text':'搜索LOL'})
            self.assertTrue(entered.wait(2));second=pool.submit(archive_other)
            time.sleep(.1);release.set();first.result();self.assertEqual(second.result(),'blocked')

class WorkerFailureTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown

    def test_shutdown_does_not_admit_new_project_jobs(self):
        stopping=threading.Event();stopping.set()
        with patch.object(app,'SHUTTING_DOWN',stopping),self.assertRaises(ValueError):
            studio.request(app,{'action':'chat','project_id':1,'text':'搜索LOL'})
        with app.connect() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM studio_jobs').fetchone()[0],0)

    def test_progress_write_failure_is_recorded_and_job_does_not_stay_running(self):
        studio.request(app,{'action':'chat','project_id':1,'text':'搜索LOL'})
        _,payload=app.COMMANDS.get_nowait()
        with patch.object(studio.store,'progress',side_effect=sqlite3.OperationalError('injected write failure')),patch.object(studio,'chat') as execute,patch.object(app,'event'):
            studio.run(app,Mock(),payload)
            execute.assert_not_called()
        with app.connect() as con:
            row=con.execute('SELECT status,error FROM studio_jobs').fetchone()
            self.assertEqual(row['status'],'failed');self.assertIn('injected write failure',row['error'])

    def test_running_status_write_failure_is_recorded(self):
        studio.request(app,{'action':'chat','project_id':1,'text':'搜索LOL'})
        _,payload=app.COMMANDS.get_nowait()
        with app.connect() as con:
            con.execute("CREATE TRIGGER fail_running BEFORE UPDATE OF status ON studio_jobs WHEN NEW.status='running' BEGIN SELECT RAISE(ABORT,'injected running write failure'); END")
        with patch.object(studio,'chat') as execute,patch.object(app,'event'):
            studio.run(app,Mock(),payload)
            execute.assert_not_called()
        with app.connect() as con:
            row=con.execute('SELECT status,error FROM studio_jobs').fetchone()
            self.assertEqual(row['status'],'failed');self.assertIn('injected running write failure',row['error'])

    def test_persistent_write_failure_keeps_project_scoped_error_in_memory(self):
        studio.request(app,{'action':'chat','project_id':1,'text':'搜索LOL'})
        _,payload=app.COMMANDS.get_nowait()
        with app.connect() as con:
            con.execute("CREATE TRIGGER fail_all BEFORE UPDATE ON studio_jobs BEGIN SELECT RAISE(ABORT,'disk remains unavailable'); END")
        with patch.object(studio,'chat') as execute,patch.object(app,'event'):
            with self.assertRaises(sqlite3.Error):studio.run(app,Mock(),payload)
            execute.assert_not_called()
        self.assertEqual(app.STATE.get('studio_project'),1)
        self.assertIn('存储失败',app.STATE['studio_error']['title'])

    def test_ui_shows_unsaved_error_only_in_its_project(self):
        from playwright.sync_api import sync_playwright
        from edge_path import find_edge
        source=Path('ui.html').read_text(encoding='utf-8')
        function=source[source.index('function currentError()'):source.index('function errorHtml()')]
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=find_edge(),headless=True)
            try:
                page=browser.new_page()
                page.evaluate("let model={project:{id:1},jobs:[{id:7,status:'queued'}],state:{studio_project:1,studio_error:{title:'本地数据存储失败',detail:'disk unavailable',job_id:7}}};"+function+"window.probe=()=>currentError(); window.switchProject=()=>model.project.id=2; void 0;")
                self.assertEqual(page.evaluate('probe()')['title'],'本地数据存储失败')
                page.evaluate('switchProject()');self.assertIsNone(page.evaluate('probe()'))
            finally:browser.close()

if __name__=='__main__':unittest.main()
