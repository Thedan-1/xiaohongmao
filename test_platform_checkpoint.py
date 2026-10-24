"""Native challenge discrimination on intercepted pages, no live platform traffic."""
import threading,unittest
import app,adapter,studio
from playwright.sync_api import sync_playwright
from edge_path import find_edge

class PlatformCheckpointTests(unittest.TestCase):
    def test_native_ip_restriction_is_not_misreported_as_login_failure(self):
        self.page.goto('https://www.xiaohongshu.com/website-login/error')
        self.page.set_content('<h1>安全限制</h1><p>IP存在风险，请切换正常网络环境后重试</p><div>300012</div>')
        self.challenge(self.page.content(),'300012','安全限制')

    def setUp(self):
        self.pw=sync_playwright().start();self.browser=self.pw.chromium.launch(executable_path=find_edge(),headless=True)
        self.page=self.browser.new_page();self.page.route('**/*',lambda r:r.fulfill(content_type='text/html; charset=utf-8',body='<meta charset="utf-8"><body>fixture</body>'))
        self.page.goto('https://www.xiaohongshu.com/explore/fixture')
    def tearDown(self):self.browser.close();self.pw.stop()
    def challenge(self,html,text,title):
        self.page.set_content(html);stop=threading.Event()
        with self.assertRaises(RuntimeError) as caught:adapter.checkpoint(self.page,stop)
        self.assertTrue(stop.is_set());self.assertIn(text,str(caught.exception))
        self.assertIn(title,studio.readable_error(caught.exception,'search')['title'])

    def test_verification_dialog_preserves_specific_reason(self):
        self.challenge('<div role="dialog">安全验证</div>','安全验证','登录')

    def test_frequency_alert_preserves_specific_reason(self):
        self.challenge('<div role="alert">访问频次异常</div>','访问频次异常','平台')

    def test_note_titles_descriptions_comments_and_search_cards_are_not_challenges(self):
        for html in ('<h1 id="detail-title">安全验证</h1>','<div id="detail-desc">请完成验证</div>',
                '<div class="comments-container"><span>操作过于频繁</span></div>',
                '<section class="note-item"><span>访问频次异常</span></section>'):
            with self.subTest(html=html):
                self.page.set_content(html);stop=threading.Event()
                adapter.checkpoint(self.page,stop);self.assertFalse(stop.is_set())

    def test_note_text_cannot_hide_a_real_visible_dialog_with_same_text(self):
        self.challenge('<h1 id="detail-title">安全验证</h1><div role="dialog"><h2>安全验证</h2></div>','安全验证','登录')

    def test_dialog_nested_inside_note_content_still_requires_verification(self):
        self.challenge('<div class="comments-container"><div role="dialog">请完成验证</div></div>','请完成验证','登录')

    def test_hidden_challenge_does_not_stop_but_login_input_does(self):
        self.page.set_content('<div role="dialog" style="display:none">安全验证</div>');stop=threading.Event()
        adapter.checkpoint(self.page,stop);self.assertFalse(stop.is_set())
        self.page.set_content('<input placeholder="输入验证码">')
        with self.assertRaisesRegex(RuntimeError,'登录'):adapter.checkpoint(self.page,stop)
        self.assertTrue(stop.is_set())

if __name__=='__main__':unittest.main()
