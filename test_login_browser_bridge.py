"""Real execution-browser cookie import against intercepted official pages only."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import app
import login_session
from edge_path import find_edge
from playwright.sync_api import sync_playwright

HTML='''<!doctype html><meta charset="utf-8"><a href="/user/profile/FixtureOwner">我</a>
<div class="user-name">离线测试账号</div><div class="user-desc">fixture profile</div>
<div class="user-redId">fixture-id</div>'''

class BrowserBridgeTests(unittest.TestCase):
    def test_verified_official_session_enters_execution_browser_without_network(self):
        with tempfile.TemporaryDirectory(prefix='xhm-session-bridge-') as temp:
            data=Path(temp);state={**app.STATE,'login':'unknown','task':'idle'}
            with patch.object(app,'DATA',data),patch.object(app,'DB',data/'fixture.sqlite3'),patch.object(app,'STATE',state),patch.object(app,'STOP',threading.Event()):
                app.init_db()
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(executable_path=find_edge(),headless=True)
                    try:
                        context=browser.new_context()
                        context.route('**/*',lambda route:route.fulfill(content_type='text/html',body=HTML))
                        worker=app.BrowserWorker();worker.pw=pw;worker.context=context;worker.page=context.new_page();worker.visible=False
                        worker.page.goto('https://www.xiaohongshu.com/explore')
                        payload={'transfer_id':'a'*32,'expected_profile':'https://www.xiaohongshu.com/user/profile/FixtureOwner','cookies':[{'name':'web_session','value':'offline-fixture-session','domain':'.xiaohongshu.com','path':'/','secure':True,'httpOnly':True,'sameSite':'Lax'}]}
                        login_session.import_session(app,worker,payload)
                        self.assertEqual(state['login_transfer_status'],'complete')
                        self.assertEqual(state['account']['name'],'离线测试账号')
                        self.assertEqual(state['account']['profile_url'],'https://www.xiaohongshu.com/user/profile/FixtureOwner')
                        session=next(c for c in context.cookies() if c['name']=='web_session')
                        self.assertTrue(session['httpOnly']);self.assertEqual(session['value'],'offline-fixture-session')
                        self.assertNotIn('cookies',payload)
                        with app.connect() as con:
                            logs='\n'.join(r[0] for r in con.execute('SELECT message FROM events'))
                        self.assertNotIn('offline-fixture-session',logs)
                    finally:browser.close()

if __name__=='__main__':unittest.main()
