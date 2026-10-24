"""Real protected local settings endpoints; isolated files and no paid traffic."""
import json
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
import app,ai_config,deepseek_client,test_studio

class AiSettingsHttpTests(unittest.TestCase):
    def setUp(self):
        test_studio.StudioTests.setUp(self)
        self.root=app.DB.parent
        self.stack.enter_context(patch.object(deepseek_client,'ROOT',self.root))
        self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(3)
        test_studio.StudioTests.tearDown(self)

    def call(self,path,data=None,token=True,origin=None):
        headers={'Content-Type':'application/json'}
        if token:headers['X-App-Token']=app.TOKEN
        if origin:headers['Origin']=origin
        request=urllib.request.Request('http://127.0.0.1:'+str(self.server.server_port)+path,
            data=None if data is None else json.dumps(data).encode(),headers=headers)
        try:
            with urllib.request.urlopen(request,timeout=5) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as response:return response.code,json.load(response)

    def test_key_requires_local_authorization_and_never_returns_in_state(self):
        data={'api_key':'offline-http-fixture-secret','model':'fixture-model'}
        self.assertEqual(self.call('/api/ai-settings',data,token=False)[0],403)
        self.assertEqual(self.call('/api/ai-settings',data,origin='https://evil.test')[0],403)
        self.assertFalse(ai_config.path(self.root).exists())
        status,saved=self.call('/api/ai-settings',data)
        self.assertEqual(status,200);self.assertTrue(saved['configured'])
        status,state=self.call('/api/studio?project=1')
        self.assertEqual(status,200);self.assertEqual(state['ai']['model'],'fixture-model')
        self.assertNotIn('offline-http-fixture-secret',json.dumps([saved,state]))
        self.assertNotIn('api_key',state['ai'])

    def test_corrupt_config_does_not_break_state_and_can_be_repaired(self):
        ai_config.path(self.root).write_text('{corrupt',encoding='utf-8')
        status,state=self.call('/api/studio?project=1')
        self.assertEqual(status,200);self.assertIn('configuration_error',state['ai'])
        self.assertEqual(self.call('/api/ai-settings',{'model':'x'})[0],400)
        status,cfg=self.call('/api/ai-settings',{'model':'x','base_url':'https://api.deepseek.com','pricing':ai_config.DEFAULT_PRICING,'clear_key':True})
        self.assertEqual(status,200);self.assertFalse(cfg['configured'])

if __name__=='__main__':unittest.main()
