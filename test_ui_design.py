"""Layout and login affordances in the real compiled UI, with local API fixtures."""
import unittest
from pathlib import Path
from test_ui_async import UiAsyncTests

class UiDesignTests(unittest.TestCase):
    setUp=UiAsyncTests.setUp
    tearDown=UiAsyncTests.tearDown

    def welcome(self,login='unknown'):
        self.page.evaluate('''login=>{
          model.project.plan={};model.messages=[{id:1,role:'assistant',body:'old duplicate intro',created_at:'2026-10-23T01:00:00'}];
          model.jobs=[];model.state.login=login;lastMessages='';renderMessages();
          if(login!=='ready')model.state.account=null;renderAccount();
        }''',login)

    def test_centered_welcome_has_one_intro_and_hat_symbol(self):
        self.page.set_viewport_size({'width':1440,'height':950});self.welcome()
        self.assertEqual(self.page.locator('.brand .brand-logo use').get_attribute('href'),'#i-hat')
        self.assertEqual(self.page.locator('.message.assistant').count(),0)
        area=self.page.locator('#conversation').bounding_box();hero=self.page.locator('.welcome').bounding_box()
        self.assertLess(abs(hero['x']+hero['width']/2-area['x']-area['width']/2),3)
        self.assertLess(abs(hero['y']+hero['height']/2-area['y']-area['height']/2),22)
        self.assertFalse(self.page.locator('#execution').is_visible())
        self.assertEqual(self.errors,[])

    def test_starter_only_edits_prompt_and_does_not_submit(self):
        self.welcome();self.page.locator('[data-starter]').first.click()
        self.assertIn('BIM',self.page.locator('#prompt').input_value())
        self.assertEqual(len(self.page.evaluate('model.messages')),1)

    def test_native_login_uses_client_bridge_and_no_external_command(self):
        self.welcome()
        self.page.evaluate("()=>{window.XIAOHONGMAO_NATIVE=true;window.chrome.webview={postMessage:m=>window.lastNativeMessage=m};command=()=>{throw Error('External browser launched')}}")
        self.page.locator('[data-login]').click()
        self.assertEqual(self.page.evaluate('lastNativeMessage'),{'type':'platform-login','switch_account':False})
        self.assertEqual(self.errors,[])

    def test_reduced_motion_and_small_window_fit(self):
        self.page.emulate_media(reduced_motion='reduce');self.page.set_viewport_size({'width':980,'height':650});self.welcome()
        self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'),True)
        box=self.page.locator('#prompt').bounding_box();self.assertLessEqual(box['y']+box['height'],650)
        self.assertTrue(self.page.locator('[data-login]').is_visible())
        self.assertEqual(self.errors,[])

    def test_visual_capture(self):
        self.page.set_viewport_size({'width':1440,'height':950});self.welcome()
        self.page.wait_for_timeout(550)
        folder=Path('data/desktop-qa');folder.mkdir(parents=True,exist_ok=True)
        self.page.screenshot(path=str(folder/'v06-welcome.png'))
        self.assertTrue(self.page.evaluate('!!window.Motion?.animate'))

if __name__=='__main__':unittest.main()
