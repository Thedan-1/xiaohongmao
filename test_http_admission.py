"""Real local HTTP handlers with isolated DB/queue; no browser or outbound actions."""
import json,sqlite3,threading,time,unittest,urllib.request,urllib.error
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import app,test_studio

class HttpAdmissionTests(unittest.TestCase):
    def setUp(self):
        test_studio.StudioTests.setUp(self)
        self.stack.enter_context(patch.object(app,'SHUTTING_DOWN',threading.Event()))
        self.stack.enter_context(patch.object(app,'STOP',threading.Event()))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(3)
        test_studio.StudioTests.tearDown(self)
    def post(self,path,data):
        return self.post_raw(path,json.dumps(data).encode())
    def post_raw(self,path,body):
        request=urllib.request.Request('http://127.0.0.1:'+str(self.server.server_port)+path,
            data=body,headers={'X-App-Token':app.TOKEN,'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request,timeout=5) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as response:return response.code,json.load(response)

    def test_legacy_command_and_studio_job_share_admission(self):
        entered=threading.Event();release=threading.Event();original=app.COMMANDS.put
        def delayed(item):
            if item[0]=='check':entered.set();release.wait(3)
            original(item)
        with patch.object(app.COMMANDS,'put',side_effect=delayed),ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.post,'/api/command',{'command':'check'})
            self.assertTrue(entered.wait(2))
            second=pool.submit(self.post,'/api/studio',{'action':'chat','project_id':1,'text':'搜索LOL'})
            time.sleep(.1);release.set()
            self.assertEqual(first.result()[0],200);self.assertGreaterEqual(second.result()[0],400)
        self.assertEqual(app.COMMANDS.qsize(),1)

    def test_legacy_command_sees_persisted_job_in_dequeue_window(self):
        self.assertEqual(self.post('/api/studio',{'action':'chat','project_id':1,'text':'搜索LOL'})[0],200)
        app.COMMANDS.get_nowait()
        self.assertGreaterEqual(self.post('/api/command',{'command':'check'})[0],400)

    def test_shutdown_cannot_overtake_job_being_published(self):
        entered=threading.Event();release=threading.Event();original=app.COMMANDS.put
        def delayed(item):
            if item[0]=='studio':entered.set();release.wait(3)
            original(item)
        with patch.object(app.COMMANDS,'put',side_effect=delayed),ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.post,'/api/studio',{'action':'chat','project_id':1,'text':'搜索LOL'})
            self.assertTrue(entered.wait(2));second=pool.submit(self.post,'/api/command',{'command':'shutdown'})
            time.sleep(.1);release.set()
            self.assertEqual(first.result()[0],200);self.assertEqual(second.result()[0],200)
        self.assertEqual([app.COMMANDS.get_nowait()[0],app.COMMANDS.get_nowait()[0]],['studio','shutdown'])
        self.assertTrue(app.STOP.is_set())

    def test_legacy_dequeue_window_blocks_another_command(self):
        self.assertEqual(self.post('/api/command',{'command':'check'})[0],200)
        app.COMMANDS.get_nowait()
        self.assertGreaterEqual(self.post('/api/command',{'command':'account'})[0],400)

    def test_legacy_dequeue_window_blocks_studio_and_archive(self):
        self.assertEqual(self.post('/api/command',{'command':'check'})[0],200)
        app.COMMANDS.get_nowait()
        self.assertGreaterEqual(self.post('/api/studio',{'action':'chat','project_id':1,'text':'搜索LOL'})[0],400)
        self.assertGreaterEqual(self.post('/api/studio',{'action':'archive','project_id':1})[0],400)

    def test_completed_legacy_command_does_not_keep_admission_blocked(self):
        self.assertEqual(self.post('/api/command',{'command':'check'})[0],200)
        app.COMMANDS.get_nowait();app.COMMANDS.task_done()
        self.assertEqual(self.post('/api/command',{'command':'account'})[0],200)

    def test_topic_switch_checks_persistent_queued_job(self):
        before=app.settings()['topic']
        self.assertEqual(self.post('/api/studio',{'action':'chat','project_id':1,'text':'搜索LOL'})[0],200)
        app.COMMANDS.get_nowait()
        self.assertGreaterEqual(self.post('/api/topic',{'topic':'LOL游戏剪辑'})[0],400)
        self.assertEqual(app.settings()['topic'],before)

    def test_topic_switch_cannot_race_command_publication(self):
        before=app.settings()['topic'];entered=threading.Event();release=threading.Event();original=app.COMMANDS.put
        def delayed(item):entered.set();release.wait(3);original(item)
        with patch.object(app.COMMANDS,'put',side_effect=delayed),ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.post,'/api/command',{'command':'check'})
            self.assertTrue(entered.wait(2));second=pool.submit(self.post,'/api/topic',{'topic':'LOL游戏剪辑'})
            time.sleep(.1);release.set();self.assertEqual(first.result()[0],200)
            self.assertGreaterEqual(second.result()[0],400)
        self.assertEqual(app.settings()['topic'],before)

    def test_topic_switch_is_rejected_during_shutdown(self):
        app.SHUTTING_DOWN.set();before=app.settings()['topic']
        self.assertGreaterEqual(self.post('/api/topic',{'topic':'LOL游戏剪辑'})[0],400)
        self.assertEqual(app.settings()['topic'],before)

    def test_non_object_json_is_rejected_without_connection_reset_or_mutation(self):
        before=app.settings()
        with patch.object(self.server,'handle_error'):
            for path in ('/api/studio','/api/topic','/api/settings','/api/command','/api/lead','/api/reply'):
                for data in (None,[],[1],'bad',True,7):
                    with self.subTest(path=path,data=data):
                        try:status,body=self.post(path,data)
                        except Exception as exc:self.fail('HTTP connection reset instead of structured 400: '+type(exc).__name__)
                        self.assertEqual(status,400);self.assertIsInstance(body.get('error'),str)
        self.assertEqual(app.settings(),before);self.assertTrue(app.COMMANDS.empty())
        self.assertEqual(self.post('/api/studio',{'action':'create','title':'Valid after rejection'})[0],200)

    def test_nonfinite_json_is_rejected_before_dispatch(self):
        with patch.object(self.server,'handle_error'):
            for value in (float('inf'),float('-inf'),float('nan')):
                with self.subTest(value=str(value)):
                    try:status,body=self.post('/api/studio',{'action':'create','project_id':value})
                    except Exception as exc:self.fail('Nonfinite JSON reset connection: '+type(exc).__name__)
                    self.assertEqual(status,400);self.assertIsInstance(body.get('error'),str)
            for body in (b'{"action":"create","project_id":1e999}',b'{"action":"create","ignored":{"number":NaN}}'):
                with self.subTest(body=body):self.assertEqual(self.post_raw('/api/studio',body)[0],400)
        self.assertTrue(app.COMMANDS.empty())

    def test_admission_storage_unavailable_returns_structured_error(self):
        with patch.object(self.server,'handle_error'),patch.object(app,'connect',side_effect=sqlite3.OperationalError('injected database is locked')):
            try:status,body=self.post('/api/studio',{'action':'chat','project_id':1,'text':'搜索LOL'})
            except Exception as exc:self.fail('Storage failure reset connection: '+type(exc).__name__)
        self.assertEqual(status,503);self.assertIn('核实',body['error']);self.assertTrue(app.COMMANDS.empty())
        with app.connect() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM studio_jobs').fetchone()[0],0)
        self.assertEqual(self.post('/api/studio',{'action':'chat','project_id':1,'text':'存储恢复后'})[0],200)

    def test_admission_transaction_write_failure_rolls_back_message_and_job(self):
        with app.connect() as con:
            before=con.execute('SELECT COUNT(*) FROM studio_messages').fetchone()[0]
            con.execute("CREATE TRIGGER reject_job BEFORE INSERT ON studio_jobs BEGIN SELECT RAISE(ABORT,'injected disk write failure'); END")
        with patch.object(self.server,'handle_error'):
            try:status,body=self.post('/api/studio',{'action':'chat','project_id':1,'text':'不得留下孤立消息'})
            except Exception as exc:self.fail('Transaction failure reset connection: '+type(exc).__name__)
        self.assertEqual(status,503);self.assertIn('可能未保存',body['error']);self.assertTrue(app.COMMANDS.empty())
        with app.connect() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM studio_messages').fetchone()[0],before)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM studio_jobs').fetchone()[0],0)

    def test_state_read_failure_returns_structured_error(self):
        request=urllib.request.Request('http://127.0.0.1:'+str(self.server.server_port)+'/api/studio',headers={'X-App-Token':app.TOKEN})
        with patch.object(self.server,'handle_error'),patch.object(app,'connect',side_effect=sqlite3.DatabaseError('injected disk read failure')):
            try:
                with urllib.request.urlopen(request,timeout=5) as response:self.fail('Bad storage returned success')
            except urllib.error.HTTPError as response:
                self.assertEqual(response.code,503);self.assertIn('核实',json.load(response)['error'])
            except Exception as exc:self.fail('State read reset connection: '+type(exc).__name__)

    def test_orphan_persistent_job_blocks_admission_with_zero_queue_counter(self):
        with app.connect() as con:con.execute("INSERT INTO studio_jobs(project_id,kind,status,payload) VALUES(1,'chat','queued','{}')")
        self.assertTrue(app.COMMANDS.empty());self.assertEqual(app.COMMANDS.unfinished_tasks,0)
        before=app.settings()['topic']
        for path,data in (('/api/command',{'command':'check'}),('/api/topic',{'topic':'LOL游戏剪辑'}),('/api/studio',{'action':'chat','project_id':1,'text':'搜索LOL'}),('/api/studio',{'action':'archive','project_id':1})):
            with self.subTest(path=path,data=data):self.assertGreaterEqual(self.post(path,data)[0],400)
        self.assertTrue(app.COMMANDS.empty());self.assertEqual(app.settings()['topic'],before)

if __name__=='__main__':unittest.main()
