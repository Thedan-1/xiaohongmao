"""All pages are intercepted fixtures. No real Xiaohongshu outbound actions."""
import sys,json,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent/'.runtime'))
from playwright.sync_api import sync_playwright
from edge_path import find_edge
import comment_flow,adapter
from test_comment_ui import HTML

class ExternalHistoryTests(unittest.TestCase):
    def target(self,kind='note'):
        return {'id':951,'kind':kind,'note_key':'note1','note_url':'https://www.xiaohongshu.com/explore/note1','comment_id':'comment-seller' if kind=='reply' else '', 'parent_id':'','author':'卖家','profile_url':'https://www.xiaohongshu.com/user/profile/seller','source_text':'出售LOL素材20元','message':'测试'}
    def test_manual_old_comment_with_different_text_is_not_posted_again(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=find_edge(),headless=True)
            page=browser.new_page();page.route('**/*',lambda r:r.fulfill(content_type='text/html',body=HTML))
            old={'id':'comment-previous','text':'这是一条以前手动发过的评论','reply':False}
            page.add_init_script('localStorage.setItem("sent",'+json.dumps(json.dumps(old,ensure_ascii=False))+')')
            target={'id':950,'kind':'note','note_key':'note1','note_url':'https://www.xiaohongshu.com/explore/note1','comment_id':'','parent_id':'','author':'卖家','profile_url':'https://www.xiaohongshu.com/user/profile/seller','source_text':'出售LOL素材20元','message':'新的测试文字'}
            submitted=[False]
            result=comment_flow.post_one(page,target,threading.Event(),submitted,lambda *a:None)
            self.assertFalse(submitted[0],'已有手动评论时不应再点击发送')
            self.assertTrue(result['already_present'])
            self.assertEqual(json.loads(page.evaluate('localStorage.sent'))['id'],'comment-previous')
            browser.close()

    def test_own_old_reply_is_detected_without_local_ledger(self):
        with sync_playwright() as pw:
            b=pw.chromium.launch(executable_path=find_edge(),headless=True);page=b.new_page();page.route('**/*',lambda r:r.fulfill(content_type='text/html',body=HTML))
            old={'id':'comment-oldreply','text':'以前已经追评过','reply':True}
            page.add_init_script('localStorage.setItem("sent",'+json.dumps(json.dumps(old,ensure_ascii=False))+')')
            submitted=[False];result=comment_flow.post_one(page,self.target('reply'),threading.Event(),submitted,lambda *a:None)
            self.assertTrue(result['already_present']);self.assertFalse(submitted[0]);b.close()

    def test_other_users_comment_does_not_count_as_our_history(self):
        with sync_playwright() as pw:
            b=pw.chromium.launch(executable_path=find_edge(),headless=True);page=b.new_page();page.route('**/*',lambda r:r.fulfill(content_type='text/html',body=HTML))
            result=comment_flow.post_one(page,self.target(),threading.Event(),[False],lambda *a:None,preview_only=True)
            self.assertTrue(result['prepared_only']);self.assertTrue(result['draft_cleared']);b.close()

    def test_incomplete_comment_history_fails_closed_instead_of_assuming_empty(self):
        with sync_playwright() as pw:
            b=pw.chromium.launch(executable_path=find_edge(),headless=True);page=b.new_page();page.route('**/*',lambda r:r.fulfill(content_type='text/html',body=HTML.replace('THE END','')))
            page.goto('https://www.xiaohongshu.com/explore/note1')
            with self.assertRaises(comment_flow.HistoryUnverified):comment_flow.verify_comment_history(page,self.target(),'https://www.xiaohongshu.com/user/profile/me',threading.Event(),max_steps=1)
            self.assertIsNone(page.evaluate('localStorage.getItem("sent")'));b.close()

    def test_changed_comment_markup_is_not_treated_as_empty_even_with_end_marker(self):
        with sync_playwright() as pw:
            b=pw.chromium.launch(executable_path=find_edge(),headless=True);page=b.new_page()
            changed=HTML.replace('class="comment-item"','class="new-comment-markup"')
            page.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body=changed));page.goto('https://www.xiaohongshu.com/explore/note1')
            with self.assertRaises(comment_flow.HistoryUnverified):comment_flow.verify_comment_history(page,self.target(),'https://www.xiaohongshu.com/user/profile/me',threading.Event(),max_steps=1)
            self.assertIsNone(page.evaluate('localStorage.getItem("sent")'));b.close()

    def test_existing_dm_is_skipped_even_if_platform_has_disabled_the_editor(self):
        html='<div class="xhs-im-msg-list"><div class="chat-item__content">旧消息</div></div>'
        with sync_playwright() as pw:
            b=pw.chromium.launch(executable_path=find_edge(),headless=True);page=b.new_page();page.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body=html));page.goto('https://www.xiaohongshu.com/chat?openUid=target')
            with patch.object(adapter,'prepare_chat',return_value=page),patch.object(adapter,'type_message_chunks') as typing:
                self.assertEqual(adapter.send_direct_message(page,{'name':'作者','id':'x','profile_url':'https://www.xiaohongshu.com/user/profile/target'},'新内容',threading.Event()),'already_present');typing.assert_not_called()
            b.close()

    def test_withdrawn_or_nontext_dm_marker_still_counts_as_previous_contact(self):
        html='<div class="xhs-im-msg-list"><div class="chat-item" data-message-id="old-message"><div class="chat-item__pure">你撤回了一条消息</div></div></div>'
        with sync_playwright() as pw:
            b=pw.chromium.launch(executable_path=find_edge(),headless=True);page=b.new_page();page.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body=html));page.goto('https://www.xiaohongshu.com/chat?openUid=target')
            with patch.object(adapter,'prepare_chat',return_value=page),patch.object(adapter,'type_message_chunks') as typing:
                self.assertEqual(adapter.send_direct_message(page,{'name':'作者','id':'x','profile_url':'https://www.xiaohongshu.com/user/profile/target'},'新内容',threading.Event()),'already_present');typing.assert_not_called()
            b.close()

    def exercise_dm_change(self,change):
        html='''<div class="xhs-im-chat-window__header-name">作者</div><div class="xhs-im-msg-list"><div class="chat-item" data-message-id="hint-stranger-target">对方关注或回复你之前，只能发送1条消息</div><div class="xhs-im-msg-list__bottom"></div></div><div class="xhs-im-input-bar-editor" contenteditable="true" onkeydown="if(event.key==='Enter')window.submissions++"></div><script>window.submissions=0</script>'''
        with sync_playwright() as pw:
            b=pw.chromium.launch(executable_path=find_edge(),headless=True);page=b.new_page();page.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body=html));page.goto('https://www.xiaohongshu.com/chat?openUid=target')
            def type_message(editor,message,stop):
                editor.fill(message)
                if change=='recipient':page.evaluate("history.replaceState(null,'','/chat?openUid=other')")
                else:page.evaluate("document.querySelector('.xhs-im-msg-list').insertAdjacentHTML('afterbegin','<div class=chat-item__content>较晚加载的旧消息</div>')")
            with patch.object(adapter,'prepare_chat',return_value=page),patch.object(adapter,'paced'),patch.object(adapter,'type_message_chunks',side_effect=type_message):
                if change=='recipient':
                    with self.assertRaisesRegex(RuntimeError,'ID 发生变化'):adapter.send_direct_message(page,{'name':'作者','id':'x','profile_url':'https://www.xiaohongshu.com/user/profile/target'},'新内容',threading.Event())
                else:self.assertEqual(adapter.send_direct_message(page,{'name':'作者','id':'x','profile_url':'https://www.xiaohongshu.com/user/profile/target'},'新内容',threading.Event()),'already_present')
            self.assertEqual(page.evaluate('window.submissions'),0);b.close()

    def test_recipient_id_change_even_with_same_nickname_stops_before_submit(self):self.exercise_dm_change('recipient')
    def test_late_history_after_typing_is_rechecked_before_submit(self):self.exercise_dm_change('history')

    def test_delayed_dm_history_is_checked_before_typing(self):
        html='''<div class="xhs-im-chat-window__header-name">作者</div><div class="xhs-im-msg-list"><div class="xhs-im-msg-list__bottom"></div></div><div class="xhs-im-input-bar-editor" contenteditable="true"></div><script>setTimeout(()=>{document.querySelector('.xhs-im-msg-list').insertAdjacentHTML('afterbegin','<div class="chat-item__content">以前手动发过的私信</div>')},1200)</script>'''
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=find_edge(),headless=True)
            page=browser.new_page();page.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body=html))
            page.goto('https://www.xiaohongshu.com/chat?openUid=target',wait_until='domcontentloaded')
            with patch.object(adapter,'prepare_chat',return_value=page),patch.object(adapter,'paced'),patch.object(adapter,'type_message_chunks',side_effect=AssertionError('历史尚未加载就开始输入')) as typing:
                result=adapter.send_direct_message(page,{'profile_url':'https://www.xiaohongshu.com/user/profile/target','name':'作者','id':'fixture'},'新内容',threading.Event())
                self.assertEqual(result,'already_present');typing.assert_not_called()
            browser.close()

if __name__=='__main__':unittest.main()
