"""Sender changes are simulated in intercepted DOM, never real accounts/messages."""
import tempfile,threading,unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
import app,adapter,comment_flow
from test_comment_ui import HTML
import test_external_history as history
from playwright.sync_api import sync_playwright
from edge_path import find_edge

DM='''<meta charset="utf-8"><style>.xhs-im-msg-list{min-height:60px}</style><a id="me" href="/user/profile/me">我</a><div class="xhs-im-chat-window__header-name">目标</div>
<div class="xhs-im-msg-list"><div class="xhs-im-msg-list__bottom"></div><div data-message-id="hint-stranger-1"></div></div>
<div class="xhs-im-input-bar-editor" contenteditable="true"></div><script>document.querySelector('[contenteditable]').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();localStorage.sent='1';let m=document.createElement('div');m.className='chat-item__content';m.textContent=e.target.innerText;document.querySelector('.xhs-im-msg-list').append(m);e.target.innerText=''}})</script>'''

class SenderIdentityTests(unittest.TestCase):
    def test_confirmed_dm_screenshot_failure_does_not_make_it_retryable(self):
        page=self.page(DM,'https://www.xiaohongshu.com/chat?openUid=target')
        lead={'id':'fixture','name':'目标','profile_url':'https://www.xiaohongshu.com/user/profile/target','expected_account':'https://www.xiaohongshu.com/user/profile/me'}
        with patch.object(adapter,'prepare_chat',return_value=page),patch.object(adapter,'paced'),patch.object(page,'reload'),patch.object(page,'screenshot',side_effect=OSError('fixture disk failure')):
            self.assertEqual(adapter.send_direct_message(page,lead,'hello',threading.Event()),'sent')
        self.assertEqual(page.evaluate('localStorage.sent'),'1')
    def setUp(self):
        self.stack=ExitStack();folder=self.stack.enter_context(tempfile.TemporaryDirectory());root=Path(folder);(root/'data').mkdir()
        self.stack.enter_context(patch.object(adapter,'DATA',root/'data'))
        self.stack.enter_context(patch.object(comment_flow,'ROOT',root))
        self.stack.enter_context(patch.object(adapter,'observe'))
        self.pw=self.stack.enter_context(sync_playwright());self.browser=self.pw.chromium.launch(executable_path=find_edge(),headless=True)
    def tearDown(self):self.browser.close();self.stack.close()
    def page(self,html,url):
        page=self.browser.new_page();page.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body=html));page.goto(url);return page

    def dm(self,mismatch=False,flip=False,history_flip=False,after_send=False,pause=False):
        page=self.page(DM,'https://www.xiaohongshu.com/chat?openUid=target')
        stop=threading.Event()
        if mismatch:page.locator('#me').evaluate("e=>e.href='/user/profile/other'")
        def progress(stage):
            if flip and stage=='提交消息并核实结果':page.locator('#me').evaluate("e=>e.href='/user/profile/other'")
            if pause and stage=='提交消息并核实结果':stop.set()
        def typing(editor,message,event):
            editor.fill(message)
            if history_flip:page.evaluate("document.querySelector('#me').href='/user/profile/other';let old=document.createElement('div');old.className='chat-item__content';old.textContent='其他账号的旧消息';document.querySelector('.xhs-im-msg-list').append(old)")
        def reload(*a,**kw):
            if after_send:page.locator('#me').evaluate("e=>e.href='/user/profile/other'")
        lead={'id':'isolated','name':'目标','profile_url':'https://www.xiaohongshu.com/user/profile/target','expected_account':'https://www.xiaohongshu.com/user/profile/me'}
        with patch.object(adapter,'prepare_chat',return_value=page),patch.object(adapter,'paced'),patch.object(adapter,'type_message_chunks',side_effect=typing),patch.object(page,'reload',side_effect=reload):
            if after_send:self.assertEqual(adapter.send_direct_message(page,lead,'hello',stop,progress),'needs_review')
            else:
                with self.assertRaisesRegex(RuntimeError,'暂停' if pause else '账号'):
                    adapter.send_direct_message(page,lead,'hello',stop,progress)
        self.assertEqual(page.evaluate('localStorage.getItem("sent")'),'1' if after_send else None)
    def test_dm_expected_sender_is_verified_before_preflight(self):self.dm(mismatch=True)
    def test_dm_sender_is_rechecked_after_final_progress_callback(self):self.dm(flip=True)
    def test_dm_other_account_late_history_cannot_be_marked_as_our_contact(self):self.dm(history_flip=True)
    def test_dm_sender_change_after_submission_requires_review(self):self.dm(after_send=True)
    def test_dm_pause_in_final_progress_callback_prevents_enter(self):self.dm(pause=True)

    def comment(self,mismatch=False,stage=None,preview=True,pause=False):
        target=history.ExternalHistoryTests().target();target['expected_account']='https://www.xiaohongshu.com/user/profile/me'
        page=self.page(HTML,target['note_url'])
        stop=threading.Event()
        def progress(current):
            if stage==current:
                if pause:stop.set()
                else:page.locator('body > a').first.evaluate("e=>e.href='/user/profile/other'")
        body=HTML.replace('href="/user/profile/me"','href="/user/profile/other"') if mismatch else HTML
        page.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body=body))
        submitted=[False]
        with self.assertRaisesRegex((ValueError,RuntimeError),'暂停' if pause else '账号'):
            comment_flow.post_one(page,target,stop,submitted,progress,preview_only=preview)
        self.assertFalse(submitted[0]);self.assertIsNone(page.evaluate('localStorage.getItem("sent")'))
    def test_comment_expected_sender_is_verified_even_in_preview(self):self.comment(mismatch=True)
    def test_comment_sender_change_during_typing_stops_preview(self):self.comment(stage='输入并核对评论')
    def test_comment_sender_change_at_final_submit_callback_stops_click(self):self.comment(stage='提交并核实评论',preview=False)
    def test_comment_pause_at_final_submit_callback_prevents_click(self):self.comment(stage='提交并核实评论',preview=False,pause=True)

if __name__=='__main__':unittest.main()
