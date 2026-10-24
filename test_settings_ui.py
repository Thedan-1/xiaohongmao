"""Settings/model UX with a local API fixture, never sending real credentials."""
import unittest
from pathlib import Path
import test_ui_async

class SettingsUiTests(unittest.TestCase):
    setUp=test_ui_async.UiAsyncTests.setUp
    tearDown=test_ui_async.UiAsyncTests.tearDown

    def configure_fixture(self):
        self.page.evaluate('''()=>{
          const cfg={configured:true,base_url:'https://api.deepseek.com',model:'deepseek-flash',models:['deepseek-flash','fixture-model'],pricing:{input:2,cached_input:.04,output:8},budget:{limit:20,reserved_or_peak_cost:3.5,remaining:16.5}};
          fixtures[1].ai=cfg;model.ai=structuredClone(cfg);renderModelPicker();
          api=async(path,data)=>{
            if(path==='ai-settings'){
              window.lastSettingsRequest=structuredClone(data);
              if(data.action==='budget'){cfg.budget={limit:data.limit,reserved_or_peak_cost:3.5,remaining:Math.max(0,data.limit-3.5)};return {budget:cfg.budget}}
              if(data.action==='models')return {models:['deepseek-flash','fixture-model']};
              const {api_key,clear_key,action,...clean}=data;Object.assign(cfg,clean,{configured:!clear_key});return cfg;
            }
            return fixtureApi(path,data);
          };
        }''')

    def test_full_page_settings_and_removed_main_screen_copy(self):
        self.configure_fixture()
        for selector in ['.crumb','.brand small','.composer-hint','#budget','#account','#account-dialog']:self.assertEqual(self.page.locator(selector).count(),0)
        self.page.locator('#settings').click();self.page.locator('[data-open-settings="general"]').click()
        self.assertTrue(self.page.locator('#settings-page').is_visible());self.assertFalse(self.page.locator('.app').is_visible())
        self.assertEqual(self.page.locator('#settings-title').inner_text(),'常规')
        self.assertEqual(self.page.locator('dialog[open]').count(),0)
        self.page.locator('#settings-back').click();self.assertTrue(self.page.locator('.app').is_visible());self.assertEqual(self.errors,[])

    def test_model_picker_saves_real_model_and_clears_secret_field(self):
        self.configure_fixture();self.page.locator('#model-picker').click();self.page.locator('[data-choose-model="fixture-model"]').click()
        self.assertEqual(self.page.locator('#ai-model-id').input_value(),'fixture-model')
        self.page.locator('#ai-api-key').fill('offline-fixture-secret');self.page.locator('#save-ai-settings').click()
        self.page.wait_for_function("document.querySelector('#ai-save-status').textContent==='已保存'")
        self.assertEqual(self.page.evaluate('lastSettingsRequest.model'),'fixture-model')
        self.assertEqual(self.page.locator('#ai-api-key').input_value(),'')
        self.page.locator('#settings-back').click();self.assertEqual(self.page.locator('#current-model').inner_text(),'fixture-model');self.assertEqual(self.errors,[])

    def test_left_menu_still_opens_native_account_login_after_top_badge_removal(self):
        self.configure_fixture()
        self.page.evaluate("()=>{window.XIAOHONGMAO_NATIVE=true;window.chrome.webview={postMessage:m=>window.lastNativeMessage=m}}")
        self.assertEqual(self.page.locator('#account').count(),0)
        self.page.locator('#settings').click();self.page.locator('[data-open-settings="account"]').click()
        self.assertTrue(self.page.locator('#settings-profile').is_visible())
        self.page.locator('#settings-login').click()
        self.assertEqual(self.page.evaluate('lastNativeMessage.type'),'platform-login')
        self.assertFalse(self.page.locator('#settings-page').is_visible());self.assertEqual(self.errors,[])

    def test_refresh_does_not_erase_unsaved_model_or_key(self):
        self.configure_fixture();self.page.evaluate("openSettings('ai')")
        self.page.locator('#ai-model-id').fill('unfinished-model');self.page.locator('#ai-api-key').fill('offline-edit')
        self.page.evaluate('refresh()')
        self.assertEqual(self.page.locator('#ai-model-id').input_value(),'unfinished-model');self.assertEqual(self.page.locator('#ai-api-key').input_value(),'offline-edit')
        self.page.locator('#settings-back').click();self.page.evaluate("openSettings('ai')")
        self.assertEqual(self.page.locator('#ai-api-key').input_value(),'');self.assertEqual(self.errors,[])

    def test_budget_is_editable_and_keeps_previous_usage(self):
        self.configure_fixture();self.page.evaluate("openSettings('usage')");self.page.locator('#ai-budget-limit').fill('10');self.page.locator('#save-budget').click()
        self.page.wait_for_function("document.querySelector('#budget-save-status').textContent==='已保存'")
        self.assertEqual(self.page.evaluate('lastSettingsRequest.limit'),10)
        self.assertEqual(self.page.locator('#usage-spent').inner_text(),'¥3.50');self.assertEqual(self.page.locator('#usage-remaining').inner_text(),'¥6.50');self.assertEqual(self.errors,[])

    def test_shortcut_preference_and_reduced_motion_work(self):
        self.configure_fixture();self.page.evaluate("openSettings('general')");self.page.locator('#send-shortcut').select_option('ctrl');self.page.locator('#reduce-motion').check();self.page.locator('#settings-back').click()
        self.page.evaluate('()=>{window.sentFromShortcut=0;sendChat=()=>window.sentFromShortcut++}')
        self.page.locator('#prompt').fill('fixture');self.page.locator('#prompt').press('Enter');self.assertEqual(self.page.evaluate('sentFromShortcut'),0)
        self.page.locator('#prompt').press('Control+Enter');self.assertEqual(self.page.evaluate('sentFromShortcut'),1)
        self.assertTrue(self.page.evaluate("document.documentElement.classList.contains('reduce-motion')"));self.assertEqual(self.errors,[])

    def test_capture_layout_and_small_viewport(self):
        self.configure_fixture();folder=Path('data/desktop-qa/settings-v065');folder.mkdir(parents=True,exist_ok=True)
        self.page.set_viewport_size({'width':1440,'height':950})
        self.page.evaluate("()=>{model.project.plan={};model.messages=[];model.jobs=[];lastMessages='';renderMessages();renderModelPicker()}")
        self.page.screenshot(path=str(folder/'workspace.png'))
        self.page.locator('#model-picker').click();self.page.screenshot(path=str(folder/'model-picker.png'));self.page.locator('#model-picker').click()
        for tab in ['general','ai','usage','account']:
            self.page.evaluate('name=>openSettings(name)',tab);self.page.screenshot(path=str(folder/(tab+'.png')))
        self.page.set_viewport_size({'width':980,'height':650});self.page.evaluate("openSettings('ai')")
        self.assertTrue(self.page.evaluate("document.querySelector('.settings-scroll').scrollWidth<=document.querySelector('.settings-scroll').clientWidth"))
        self.page.locator('#save-ai-settings').scroll_into_view_if_needed();self.assertTrue(self.page.locator('#save-ai-settings').is_visible());self.assertEqual(self.errors,[])

if __name__=='__main__':unittest.main()
