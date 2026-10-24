"""Taobao prototype boundaries; local memory only, never contacting a shop."""
import sqlite3,unittest
from unittest.mock import Mock
import taobao_browser as browser,taobao_store as store

class TaobaoBoundaryTests(unittest.TestCase):
    def test_verification_code_is_reported_and_hidden_frames_are_ignored(self):
        page=Mock();page.url='https://s.taobao.com/search?q=BIM'
        main=Mock();main.locator.return_value.inner_text.return_value='搜索 BIM 代做'
        challenge=Mock();challenge.frame_element.return_value.is_visible.return_value=True
        challenge.locator.return_value.inner_text.return_value='请拖动下方滑块完成验证 通过验证以确保正常访问 验证失败，点击框体重试(error:r8qq)'
        page.main_frame=main;page.frames=[main,challenge]
        instance=browser.TaobaoBrowser()
        with self.assertRaisesRegex(browser.TaobaoVerificationRequired,'r8qq'):instance.check_verification(page)
        challenge.frame_element.return_value.is_visible.return_value=False
        instance.check_verification(page)
        self.assertIsNone(browser.verification_notice('BIM 工作室：提供建模服务'))

    def test_existing_verification_prevents_new_search_navigation(self):
        instance=browser.TaobaoBrowser();instance.page=Mock()
        instance.check_verification=Mock(side_effect=browser.TaobaoVerificationRequired('暂停'))
        with self.assertRaises(browser.TaobaoVerificationRequired):instance.search('BIM代做')
        instance.page.goto.assert_not_called()

    def test_official_hosts_do_not_accept_lookalike_domains(self):
        self.assertTrue(browser.official_url('https://login.taobao.com/'))
        for url in ['https://taobao.com.evil.test/','http://www.taobao.com/','https://evil@www.taobao.com/']:
            with self.subTest(url=url):self.assertFalse(browser.official_url(url))

    def test_shop_aliases_contact_dedup_and_reply_isolation(self):
        with sqlite3.connect(':memory:') as con:
            con.row_factory=sqlite3.Row;store.init(con)
            shop=store.save_shop(con,{'name':'BIM测试店','url':'https://shop123456.taobao.com/?source=test','evidence':'Revit建模代做'},'BIM代做')
            self.assertEqual(shop,store.shop_key('https://store.taobao.com/shop/view_shop.htm?shop_id=123456'))
            self.assertTrue(store.claim(con,'account-a',shop,'你好'));self.assertFalse(store.claim(con,'account-a',shop,'你好'))
            with self.assertRaises(ValueError):store.finish(con,'account-a',shop,'sent',{})
            store.finish(con,'account-a',shop,'sent',{'own_new_message_visible':True,'screenshot':'local-fixture.png'})
            self.assertTrue(store.add_reply(con,'account-a',shop,'message-id-1','你好','2026-10-24 04:15:00'))
            self.assertFalse(store.add_reply(con,'account-a',shop,'message-id-1','你好','2026-10-24 04:15:00'))
            self.assertEqual(store.state(con,'account-b')['replies'],[])

if __name__=='__main__':unittest.main()
