"""Protected update HTTP endpoints and atomic idle/shutdown handoff."""
import json,threading,unittest
from pathlib import Path
from unittest.mock import patch
import app,updater,test_studio
import test_ai_settings_http

class UpdateHttpTests(unittest.TestCase):
    call=test_ai_settings_http.AiSettingsHttpTests.call
    def setUp(self):
        test_studio.StudioTests.setUp(self)
        self.root=app.DB.parent;self.stack.enter_context(patch.object(app,'ROOT',self.root));self.stack.enter_context(patch.object(app,'DATA',self.root/'data'));app.DATA.mkdir()
        self.stack.enter_context(patch.object(app,'SHUTTING_DOWN',threading.Event()));self.stack.enter_context(patch.object(app,'STOP',threading.Event()))
        (self.root/'release-config.json').write_text(json.dumps({'version':'0.7.0','repository':'Thedan-1/xiaohongmao'}),encoding='utf-8')
        (self.root/'package-manifest.json').write_text(json.dumps({'distribution':'preview'}),encoding='utf-8')
        self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(3)
        updater.MANAGERS.pop((str(app.ROOT),str(app.DATA)),None)
        test_studio.StudioTests.tearDown(self)
    def test_authorization_and_no_implicit_download(self):
        self.assertEqual(self.call('/api/update',token=False)[0],403)
        self.assertEqual(self.call('/api/update',{'action':'check'},origin='https://evil.test')[0],403)
        status,value=self.call('/api/update');self.assertEqual(status,200);self.assertEqual(value['phase'],'idle')
        self.assertEqual(self.call('/api/update',{'action':'download'})[0],400)
        self.assertTrue(app.COMMANDS.empty())
    def test_prepare_freezes_new_jobs_and_enqueues_one_graceful_shutdown(self):
        manager=updater.manager(app);manager.folder.mkdir();package=manager.folder/'fixture.zip';package.write_bytes(b'fixture')
        manager.staged=package;manager.selected={'version':'0.7.1','sha256':updater.digest_file(package)};manager.change(phase='ready')
        (self.root/'python').mkdir();(self.root/'python/pythonw.exe').write_bytes(b'fixture runtime');(self.root/'update_apply.py').write_text('# fixture',encoding='utf-8')
        status,value=self.call('/api/update',{'action':'prepare'})
        self.assertEqual(status,200);self.assertTrue(Path(value['plan']).is_file());self.assertTrue(app.SHUTTING_DOWN.is_set())
        self.assertEqual(app.COMMANDS.qsize(),1);self.assertEqual(app.COMMANDS.get_nowait()[0],'shutdown');app.COMMANDS.task_done()
        self.assertEqual(self.call('/api/studio',{'action':'chat','project_id':1,'text':'搜索 BIM'})[0],400)
        self.assertEqual(self.call('/api/update',{'action':'prepare'})[0],400)

if __name__=='__main__':unittest.main()
