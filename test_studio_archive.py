import json
import unittest
from pathlib import Path
from unittest.mock import patch
import app,studio,studio_archive,project_store,test_studio

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        test_studio.StudioTests.setUp(self)
        data=app.DB.parent/'data';data.mkdir()
        self.stack.enter_context(patch.object(app,'DATA',data))
        self.stack.enter_context(patch.object(studio,'ROOT',data.parent))
    tearDown=test_studio.StudioTests.tearDown
    def call(self,action,pid=1,**kw):return studio.request(app,{'action':action,'project_id':pid,**kw})

    def test_archive_restore_preserves_memory_and_receipts(self):
        source={'profile_url':'https://www.xiaohongshu.com/user/profile/u1'}
        with app.connect() as con:
            project_store.claim(con,1,'dm',source,'A','你好');project_store.finish(con,1,'dm',source,'sent')
            studio.message(con,1,'user','保留这句')
        self.call('archive')
        with app.connect() as con:
            state=studio.state(con,1)
            self.assertEqual(state['projects'],[]);self.assertEqual(state['project']['id'],0)
            self.assertEqual(state['archived'][0]['id'],1)
        with self.assertRaisesRegex(ValueError,'已归档'):self.call('chat',text='不能执行')
        self.call('restore')
        with app.connect() as con:
            self.assertIn('保留这句',[m['body'] for m in studio.state(con,1)['messages']])
            self.assertFalse(project_store.claim(con,1,'dm',source,'B','你好'))

    def test_delete_requires_archived_and_confirmed(self):
        with self.assertRaisesRegex(ValueError,'先归档'):self.call('delete',confirmed=True)
        self.call('archive')
        with self.assertRaisesRegex(ValueError,'确认永久删除'):self.call('delete')
        with app.connect() as con:self.assertIsNotNone(con.execute('SELECT * FROM studio_projects WHERE id=1').fetchone())

    def test_delete_cascades_only_owned_records_and_ids_never_reused(self):
        other=self.call('create')['project_id']
        with app.connect() as con:
            for pid in (1,other):
                rid=con.execute("INSERT INTO comment_runs(topic,report) VALUES('BIM','{}')").lastrowid
                con.execute('INSERT INTO studio_runs(project_id,run_id) VALUES(?,?)',(pid,rid))
                con.execute("INSERT INTO comment_captures(run_id,note_key,capture) VALUES(?,'n1','{}')",(rid,))
                con.execute("INSERT INTO studio_activity(project_id,body) VALUES(?,'进度')",(pid,))
                con.execute("INSERT INTO studio_jobs(project_id,kind,status,payload) VALUES(?,'chat','complete','{}')",(pid,))
                con.execute("INSERT INTO studio_drafts(project_id,items) VALUES(?,'[]')",(pid,))
                project_store.claim(con,pid,'dm',{'profile_url':'https://www.xiaohongshu.com/user/profile/u1'},'A','你好')
                project_store.set_step(con,pid,'goal')
                (app.DATA/f'studio-frame-{pid}.jpg').write_bytes(b'test')
        self.call('archive');self.call('delete',confirmed=True)
        with app.connect() as con:
            for table in ('studio_messages','studio_runs','studio_jobs','studio_activity','studio_drafts','studio_receipts','studio_setup'):
                self.assertEqual(con.execute(f'SELECT COUNT(*) FROM {table} WHERE project_id=1').fetchone()[0],0,table)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM comment_runs').fetchone()[0],1)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM studio_receipts WHERE project_id=?',(other,)).fetchone()[0],1)
        self.assertFalse((app.DATA/'studio-frame-1.jpg').exists());self.assertTrue((app.DATA/f'studio-frame-{other}.jpg').exists())
        self.call('archive',other);self.call('delete',other,confirmed=True)
        app.init_db()
        with app.connect() as con:self.assertEqual(studio.state(con)['projects'],[])
        self.assertGreater(self.call('create')['project_id'],other)

    def test_busy_project_cannot_be_archived_or_deleted(self):
        self.call('chat',text='工作中')
        with self.assertRaisesRegex(ValueError,'任务仍在运行'):self.call('archive')
        app.COMMANDS.get_nowait()
        with self.assertRaisesRegex(ValueError,'任务仍在运行'):self.call('archive')

    def test_personal_settings_archive_restore_delete_browser_flow(self):
        from playwright.sync_api import sync_playwright
        from edge_path import find_edge
        app.STATE.update(login='ready',message='就绪')
        def route(r):
            if '/api/studio-frame' in r.request.url:r.fulfill(status=404);return
            if '/api/studio' in r.request.url:
                if r.request.method=='POST':result=studio.request(app,r.request.post_data_json)
                else:
                    from urllib.parse import urlsplit,parse_qs
                    pid=parse_qs(urlsplit(r.request.url).query).get('project',[None])[0]
                    with app.connect() as con:result=studio.state(con,pid)
                    result.update(state=dict(app.STATE),ai={'configured':True,'model':'deepseek-flash','budget':{'remaining':3.46}})
                r.fulfill(content_type='application/json',body=studio.dump(result));return
            r.fulfill(content_type='text/html',body=Path('ui.html').read_text(encoding='utf-8'))
        with sync_playwright() as pw:
            b=pw.chromium.launch(executable_path=find_edge(),headless=True)
            page=b.new_page(viewport={'width':1400,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.route('**/*',route)
            page.goto('http://127.0.0.1:8765/?project=1');page.wait_for_selector('[data-archive="1"]',state='attached')
            page.locator('.project-row').hover();page.locator('[data-archive="1"]').click();page.wait_for_function("document.querySelectorAll('.project-row').length===0")
            page.evaluate("openSettings('account')");page.wait_for_selector('#settings-account')
            self.assertTrue(page.locator('#settings-login').is_visible())
            page.locator('[data-settings-tab="archive"]').click();page.wait_for_selector('[data-restore="1"]')
            page.screenshot(path='data/studio-archive-test.png')
            page.locator('[data-restore="1"]').click();page.wait_for_selector('.project-row')
            self.assertFalse(page.locator('#settings-page').is_visible())
            page.locator('.project-row').hover();page.locator('[data-archive="1"]').click();page.wait_for_function("document.querySelectorAll('.project-row').length===0")
            page.evaluate("openSettings('archive')");page.locator('[data-delete-project="1"]').click();page.wait_for_selector('#delete-project-dialog')
            page.locator('[data-close="delete-project-dialog"]').click()
            self.assertEqual(page.locator('[data-delete-project="1"]').count(),1)
            page.locator('[data-delete-project="1"]').click();page.locator('#delete-project-confirm').click();page.wait_for_selector('.settings-empty')
            page.set_viewport_size({'width':430,'height':900});page.screenshot(path='data/studio-settings-mobile-test.png')
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            page.locator('#settings-back').click();page.locator('#menu').click();page.locator('#new-project').click();page.wait_for_selector('.project-row',state='attached')
            self.assertEqual(errors,[])
            b.close()

if __name__=='__main__':unittest.main()
