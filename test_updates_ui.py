"""Compiled update UI, isolated browser fixtures, no downloads or real upgrades."""
import unittest
from pathlib import Path
import test_ui_async

class UpdatesUiTests(unittest.TestCase):
    setUp=test_ui_async.UiAsyncTests.setUp
    tearDown=test_ui_async.UiAsyncTests.tearDown
    def setup_update(self):
        self.page.evaluate('''()=>{
          window.updateFixture={phase:'available',current_version:'0.7.0',distribution:'preview',message:'发现新版本，可选择下载更新',release:{version:'0.7.1',notes:'<script>window.badUpdate=true</script>\\n测试发布说明',release_url:'https://github.com/Thedan-1/xiaohongmao/releases/tag/v0.7.1'}};
          api=async(path,data)=>{
            if(path==='update'){
              window.updateActions=(window.updateActions||[]);if(data)updateActions.push(data.action);
              if(data?.action==='download')updateFixture.phase='ready';
              if(data?.action==='cancel')updateFixture.phase='available';
              return structuredClone(updateFixture);
            }
            return fixtureApi(path,data);
          };
          renderUpdateStatus(updateFixture);openSettings('about');
        }''')
    def test_new_version_is_optional_and_notes_are_text_only(self):
        self.setup_update()
        self.assertTrue(self.page.locator('#download-update').is_visible())
        self.assertFalse(self.page.locator('#apply-update').is_visible())
        self.assertIsNone(self.page.evaluate('window.badUpdate'))
        self.assertIn('<script>',self.page.locator('#update-notes').inner_text())
        self.assertEqual(self.page.evaluate('window.updateActions||[]'),[])
        self.assertEqual(self.errors,[])
    def test_download_and_restart_require_separate_user_choices(self):
        self.setup_update();self.page.evaluate("()=>{window.XIAOHONGMAO_NATIVE=true;window.chrome.webview={postMessage:m=>window.updateNativeMessage=m}}")
        self.page.locator('#download-update').click();self.page.wait_for_selector('#apply-update',state='visible')
        self.assertIsNone(self.page.evaluate('window.updateNativeMessage'))
        self.page.locator('#apply-update').click()
        self.assertEqual(self.page.evaluate('updateNativeMessage'),{'type':'install-update'})
        self.assertEqual(self.errors,[])
    def test_busy_then_idle_updates_apply_button_without_restart(self):
        self.setup_update();self.page.evaluate("()=>{updateFixture.phase='ready';model.state.task='studio';renderUpdateStatus(updateFixture)}")
        self.assertTrue(self.page.locator('#apply-update').is_disabled())
        self.page.evaluate("()=>{model.state.task='idle';renderSettings()}")
        self.assertTrue(self.page.locator('#apply-update').is_enabled())
    def test_update_page_has_a_real_check_action_and_capture(self):
        self.setup_update();self.page.locator('#check-updates').click()
        self.page.wait_for_function("window.updateActions?.includes('check')")
        self.page.evaluate("()=>{updateFixture.release.notes='更新交互演示\\n下载后校验 SHA-256；空闲时由你选择重启。';renderUpdateStatus(updateFixture)}")
        folder=Path('data/desktop-qa/updates-v070');folder.mkdir(parents=True,exist_ok=True)
        self.page.screenshot(path=str(folder/'update-available.png'))
        self.assertEqual(self.errors,[])

if __name__=='__main__':unittest.main()
