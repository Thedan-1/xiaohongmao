import threading,unittest
from unittest.mock import patch
import app,comment_flow,project_store,test_studio
from playwright.sync_api import sync_playwright
from edge_path import find_edge
from test_comment_ui import HTML

class ProjectCommentLedgerTests(unittest.TestCase):
    def test_locked_local_receipt_does_not_scan_entire_native_history(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=find_edge(),headless=True)
            try:
                page=browser.new_page();page.route('**/*',lambda r:r.fulfill(content_type='text/html',body=HTML.replace('THE END','')))
                target={'id':800,'kind':'note','note_key':'note1','note_url':'https://www.xiaohongshu.com/explore/note1','comment_id':'','parent_id':'','author':'author','profile_url':'https://www.xiaohongshu.com/user/profile/seller','source_text':'','message':'fixture'}
                with patch.object(comment_flow,'verify_comment_history',side_effect=AssertionError('normal local-ledger flow must not scan all comments')):
                    result=comment_flow.post_one(page,target,threading.Event(),[False],lambda *a:None,preview_only=True,local_receipt_checked=True)
                self.assertTrue(result['prepared_only']);self.assertTrue(result['draft_cleared'])
            finally:browser.close()

    def test_note_id_survives_renaming_and_same_title_different_note_is_distinct(self):
        test_studio.StudioTests.setUp(self)
        try:
            first={'key':'note1','title':'旧标题'}
            with app.connect() as con:
                self.assertTrue(project_store.claim(con,1,'note',first,'account-A','hello'))
                project_store.finish(con,1,'note',first,'sent')
                self.assertFalse(project_store.claim(con,1,'note',{'key':'note1','title':'新标题'},'account-B','different'))
                self.assertTrue(project_store.claim(con,1,'note',{'key':'note2','title':'旧标题'},'account-A','hello'))
        finally:test_studio.StudioTests.tearDown(self)

if __name__=='__main__':unittest.main()
