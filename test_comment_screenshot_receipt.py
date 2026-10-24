import tempfile,threading,unittest,json,sys
from pathlib import Path
from unittest.mock import patch
import comment_flow
sys.path.insert(0,str(Path(__file__).resolve().parent/'.runtime'))
from playwright.sync_api import sync_playwright
from edge_path import find_edge
from test_comment_ui import HTML

class ScreenshotReceiptTests(unittest.TestCase):
    def test_long_comment_input_is_not_cut_off_by_six_second_default(self):
        with tempfile.TemporaryDirectory() as folder,sync_playwright() as pw:
            root=Path(folder);(root/'data').mkdir()
            browser=pw.chromium.launch(executable_path=find_edge(),headless=True)
            try:
                page=browser.new_page();page.set_default_timeout(6000)
                page.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body=HTML))
                message='S16加油！期待精彩比赛。'+('祝所有参赛选手发挥出色。'*3)
                target={'id':4,'kind':'note','note_key':'note1','note_url':'https://www.xiaohongshu.com/explore/note1','comment_id':'','parent_id':'','message':message}
                with patch.object(comment_flow,'ROOT',root):
                    result=comment_flow.post_one(page,target,threading.Event(),[False],lambda *a:None,local_receipt_checked=True)
                self.assertTrue(result['confirmed_on_page']);self.assertTrue(result['screenshot_saved'])
            finally:browser.close()
    def test_rejected_ui_submission_records_platform_reason_without_retry(self):
        with tempfile.TemporaryDirectory() as folder,sync_playwright() as pw:
            root=Path(folder);(root/'data').mkdir()
            browser=pw.chromium.launch(executable_path=find_edge(),headless=True)
            try:
                page=browser.new_page()
                html=HTML.replace('function post(){',"function post(){fetch('/api/data',{method:'POST',body:JSON.stringify({note_id:'note1',content:'telemetry'})});fetch('/comment/post',{method:'POST',body:JSON.stringify({note_id:'note1',content:document.querySelector('#content-textarea').innerText})});return; ")
                calls=[]
                def route(r):
                    if r.request.method=='POST' and r.request.url.endswith('/comment/post'):
                        calls.append(1);r.fulfill(status=200,content_type='application/json',body=json.dumps({'success':False,'code':-9119,'msg':'作者设置了仅关注的人可以评论'}))
                    elif r.request.method=='POST':r.fulfill(content_type='application/json',body='{"success":true,"code":0}')
                    else:r.fulfill(content_type='text/html; charset=utf-8',body=html)
                page.route('**/*',route)
                target={'id':3,'kind':'note','note_key':'note1','note_url':'https://www.xiaohongshu.com/explore/note1','comment_id':'','parent_id':'','message':'fixture comment'}
                with patch.object(comment_flow,'ROOT',root):
                    with self.assertRaisesRegex(comment_flow.CommentSubmissionRejected,'仅关注的人可以评论') as error:
                        comment_flow.post_one(page,target,threading.Event(),[False],lambda *a:None,local_receipt_checked=True)
                self.assertTrue(error.exception.unavailable)
                self.assertEqual(len(calls),1)
                trace=json.loads((root/'data/comment-submit-3.json').read_text(encoding='utf-8'))
                self.assertEqual(len(trace['events']),1)
                self.assertEqual(trace['events'][0]['code'],-9119)
                self.assertTrue((root/'data/comment-submit-failed-3.png').is_file())
            finally:browser.close()

    def test_screenshot_failure_does_not_make_visible_comment_retryable(self):
        with tempfile.TemporaryDirectory() as folder,sync_playwright() as pw:
            root=Path(folder);(root/'data').mkdir()
            browser=pw.chromium.launch(executable_path=find_edge(),headless=True)
            try:
                page=browser.new_page();page.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body=HTML))
                target={'id':2,'kind':'note','note_key':'note1','note_url':'https://www.xiaohongshu.com/explore/note1','comment_id':'','parent_id':'','author':'author','profile_url':'https://www.xiaohongshu.com/user/profile/seller','source_text':'','message':'fixture comment'}
                with patch.object(comment_flow,'ROOT',root),patch.object(page,'screenshot',side_effect=OSError('fixture disk failure')):
                    result=comment_flow.post_one(page,target,threading.Event(),[False],lambda *a:None,local_receipt_checked=True)
                self.assertTrue(result['confirmed_on_page']);self.assertFalse(result['screenshot_saved'])
                self.assertTrue(result['receipt_saved']);self.assertTrue(result['evidence_errors'])
            finally:browser.close()

    def test_visible_own_comment_is_saved_with_photo_without_reload(self):
        with tempfile.TemporaryDirectory() as folder,sync_playwright() as pw:
            root=Path(folder);(root/'data').mkdir()
            browser=pw.chromium.launch(executable_path=find_edge(),headless=True)
            try:
                page=browser.new_page()
                html=HTML.replace("localStorage.setItem('sent',JSON.stringify(x));",'')
                page.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body=html))
                target={'id':1,'kind':'note','note_key':'note1','note_url':'https://www.xiaohongshu.com/explore/note1','comment_id':'','parent_id':'','author':'author','profile_url':'https://www.xiaohongshu.com/user/profile/seller','source_text':'','message':'fixture comment'}
                with patch.object(comment_flow,'ROOT',root),patch.object(page,'reload',side_effect=AssertionError('visible comment must not be hidden by forced reload')) as reload:
                    result=comment_flow.post_one(page,target,threading.Event(),[False],lambda *a:None,local_receipt_checked=True)
                    reload.assert_not_called()
                self.assertTrue(result['confirmed_on_page']);self.assertTrue(result['screenshot_saved'])
                self.assertFalse(result['verified_after_reload']);self.assertTrue((root/'data/comment-sent-1.png').is_file())
                receipt=json.loads((root/'data/comment-receipt-1.json').read_text(encoding='utf-8'))
                self.assertEqual(receipt['text'],'fixture comment');self.assertEqual(receipt['note_key'],'note1')
                self.assertTrue(page.locator('[id="'+result['comment_id']+'"]').is_visible())
            finally:browser.close()

if __name__=='__main__':unittest.main()
