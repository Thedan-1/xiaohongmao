import copy
from contextlib import nullcontext
import json
from types import SimpleNamespace
import unittest
import threading
from unittest.mock import Mock,patch
import login_session

def cookies():return [{'name':'web_session','value':'offline-fixture','domain':'.xiaohongshu.com','path':'/','secure':True,'httpOnly':True,'sameSite':'Lax'}]

class LoginSessionTests(unittest.TestCase):
    def test_official_http_only_cookie_preserved(self):
        result=login_session.validate_cookies(cookies())
        self.assertEqual(result[0]['value'],'offline-fixture');self.assertTrue(result[0]['httpOnly'])

    def test_invalid_domains_values_expiry_and_missing_auth_rejected(self):
        variants=[[],[{'name':'a1','value':'id','domain':'.xiaohongshu.com'}]]
        for field,value in [('domain','.evil.test'),('domain','.xiaohongshu.com.evil.test'),('value','x\nsecret'),('expires',float('nan')),('path','relative'),('name','invalid;')]:
            v=cookies();v[0][field]=value;variants.append(v)
        v=cookies();v[0]['expires']=1;variants.append(v)
        variants.append(cookies()*2)
        for value in variants:
            with self.subTest(value_type=type(value).__name__),self.assertRaises(ValueError):login_session.validate_cookies(value)

    def transfer(self,ready=True,broken_restore=False,mismatch=False):
        state={};events=[];updates=[]
        def update(**kw):updates.append(dict(kw));state.update(kw)
        app=SimpleNamespace(STATE=state,update=update,event=lambda text,*a:events.append(text))
        worker=Mock();worker.browser_operation.return_value=nullcontext();worker.context.cookies.return_value=[{'name':'old','value':'retained'}]
        worker.page.locator.return_value.filter.return_value.first.get_attribute.return_value='/user/profile/'+('OtherOwner' if mismatch else 'FixtureOwner')
        def check(**kw):
            result={'login':'ready' if ready else 'required'}
            if kw.get('publish',True):state.update(result)
            return result
        worker.check.side_effect=check
        if broken_restore:worker.context.add_cookies.side_effect=RuntimeError('cookie secret must not be logged')
        payload={'transfer_id':'a'*32,'cookies':cookies(),'expected_profile':'https://www.xiaohongshu.com/user/profile/FixtureOwner'}
        with patch('studio.read_account_profile',return_value={'profile_url':payload['expected_profile'],'name':'Fixture'}) as account:
            login_session.import_session(app,worker,payload)
        worker.fixture_updates=updates
        return state,events,worker,payload

    def test_success_requires_verified_login_and_erases_payload(self):
        state,events,worker,payload=self.transfer()
        self.assertEqual(state['login_transfer_status'],'complete');self.assertEqual(state['login'],'ready')
        self.assertNotIn('cookies',payload);self.assertNotIn('offline-fixture',json.dumps(events))

    def test_failed_login_restores_old_cookie_and_does_not_claim_success(self):
        state,events,worker,payload=self.transfer(False)
        self.assertEqual(state['login_transfer_status'],'failed')
        self.assertEqual(worker.context.add_cookies.call_args.args[0],[{'name':'old','value':'retained'}])
        self.assertNotIn('cookies',payload);self.assertNotEqual(state['login'],'ready')

    def test_cookie_errors_never_include_raw_credentials(self):
        state,events,worker,payload=self.transfer(False,True)
        self.assertNotIn('secret',json.dumps(events));self.assertEqual(state['login_transfer_status'],'failed')

    def test_different_logged_in_account_is_rolled_back(self):
        state,events,worker,payload=self.transfer(mismatch=True)
        self.assertEqual(state['login_transfer_status'],'failed')
        self.assertEqual(worker.context.add_cookies.call_args.args[0],[{'name':'old','value':'retained'}])

    def test_success_is_published_once_after_identity_check(self):
        state,events,worker,payload=self.transfer()
        successful=[u for u in worker.fixture_updates if u.get('login')=='ready']
        self.assertEqual(len(successful),1)
        self.assertEqual(successful[0]['login_transfer_status'],'complete')
        self.assertEqual(successful[0]['login_verified_profile'],'https://www.xiaohongshu.com/user/profile/FixtureOwner')

    def test_identity_mismatch_never_briefly_publishes_success(self):
        state,events,worker,payload=self.transfer(mismatch=True)
        self.assertFalse(any(u.get('login')=='ready' for u in worker.fixture_updates))
        self.assertEqual(state['login_transfer_stage'],'identity_mismatch')

class ColdLoginSessionTests(unittest.TestCase):
    def test_cold_start_initializes_driver_before_browser_guard(self):
        import app
        state={};worker=app.BrowserWorker()
        process=Mock();process.returncode=0
        driver=Mock();driver._impl_obj._connection._transport._proc=process
        manager=Mock();manager.start.return_value=driver
        context=Mock();context.cookies.return_value=[]
        page=Mock();page.locator.return_value.filter.return_value.first.get_attribute.return_value='/user/profile/FixtureOwner'
        def launch(**kw):worker.context=context;worker.page=page
        worker.launch=Mock(side_effect=launch)
        def check(*args,**kw):
            result={'login':'ready','message':'identity available'}
            if kw.get('publish',True):state.update(result)
            return result
        worker.check=Mock(side_effect=check)
        fake=SimpleNamespace(STATE=state,update=lambda **kw:state.update(kw),event=Mock())
        payload={'transfer_id':'c'*32,'cookies':cookies(),'expected_profile':'https://www.xiaohongshu.com/user/profile/FixtureOwner'}
        with patch('playwright.sync_api.sync_playwright',return_value=manager),patch.object(app,'STOP',threading.Event()),patch.object(app,'update'),patch('studio.account'),patch('studio.read_account_profile',create=True,return_value={'profile_url':payload['expected_profile'],'name':'Fixture'}):
            login_session.import_session(fake,worker,payload)
        self.assertEqual(state['login_transfer_status'],'complete',state.get('message'))
        self.assertIs(worker.pw,driver)
        worker.launch.assert_called_once_with(visible=False,navigate=False)

    def test_login_launch_does_not_load_an_unneeded_guest_page(self):
        import app
        worker=app.BrowserWorker();worker.pw=Mock()
        page=Mock();context=Mock();context.pages=[page]
        worker.pw.chromium.launch_persistent_context.return_value=context
        with patch.object(app,'find_edge',return_value='fixture-edge.exe'),patch.object(app,'update'),patch.object(app,'event'):
            worker.launch(visible=False,navigate=False)
        page.goto.assert_not_called()

    def test_identity_probe_can_run_without_publishing_success(self):
        import app
        worker=app.BrowserWorker()
        worker.snapshot=Mock(return_value={'text':'首页 我','url':'https://www.xiaohongshu.com/explore','elements':[{'href':'/user/profile/FixtureOwner','text':'我'}]})
        with patch.object(app,'update') as update,patch.object(app,'event') as event:
            result=worker.check(publish=False)
        self.assertEqual(result['login'],'ready');update.assert_not_called();event.assert_not_called()

if __name__=='__main__':unittest.main()
