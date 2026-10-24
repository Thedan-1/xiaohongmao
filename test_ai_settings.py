"""Per-user configuration, real model dispatch, budget preservation; no paid calls."""
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import closing
from unittest.mock import Mock,patch
import ai_config,deepseek_client as client,workflow_ai

class AiSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.patch=patch.object(client,'ROOT',self.root);self.patch.start()
        (self.root/'deepseek.local.txt').write_text('DEEPSEEK_API_KEY=offline-test-secret\n',encoding='utf-8')
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def save(self,**data):return ai_config.save(data,self.root)

    def test_save_preserve_clear_and_never_return_key(self):
        first=self.save(model='fixture-model');self.assertTrue(first['configured'])
        self.assertNotIn('offline-test-secret',json.dumps(first));self.assertNotIn('api_key',first)
        self.save(api_key='new-offline-secret');self.save(model='fixture-next',api_key='')
        self.assertEqual(ai_config.key(root=self.root),'new-offline-secret')
        self.save(clear_key=True);self.assertEqual(ai_config.key(root=self.root),'')
        self.assertFalse(ai_config.public(self.root)['configured'])

    def test_invalid_input_and_failed_write_preserve_previous_config(self):
        self.save(model='fixture-model');before=ai_config.path(self.root).read_bytes()
        for data in [{'api_key':'secret\nheader'},{'base_url':'http://example.test'},{'model':'bad model'},{'pricing':{'input':0,'cached_input':0,'output':1}}]:
            with self.subTest(field=list(data)),self.assertRaises(ValueError):self.save(**data)
        with patch.object(ai_config.os,'replace',side_effect=OSError('fixture disk failure')),self.assertRaises(RuntimeError):self.save(model='next')
        self.assertEqual(ai_config.path(self.root).read_bytes(),before)

    def test_new_service_cannot_silently_receive_old_key(self):
        with self.assertRaisesRegex(ValueError,'重新填写'):self.save(base_url='https://models.example.test/v1')
        cfg=self.save(base_url='https://models.example.test/v1',api_key='offline-new-service-key')
        self.assertEqual(cfg['base_url'],'https://models.example.test/v1')

    def test_saved_model_and_pricing_drive_real_dispatch_and_metering(self):
        self.save(model='fixture-model',pricing={'input':7,'cached_input':.2,'output':21})
        response={'usage':{'prompt_tokens':100,'completion_tokens':10,'total_tokens':110},'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}
        with patch.object(client,'request',return_value=response) as request:
            self.assertEqual(workflow_ai.complete('fixture',{},'test',lambda x:x),{'ok':True})
        self.assertEqual(request.call_args.args[1]['model'],'fixture-model')
        self.assertNotIn('thinking',request.call_args.args[1])
        self.assertAlmostEqual(workflow_ai.budget()['reserved_or_peak_cost'],.0009,places=4)
        with closing(workflow_ai._db()) as con:
            details=json.loads(con.execute('SELECT details FROM calls').fetchone()[0])
        self.assertEqual(details['pricing']['output'],21)

    def test_changing_ceiling_keeps_history_and_lower_limit_blocks_new_calls(self):
        with closing(workflow_ai._db()) as con:
            with con:con.execute('INSERT INTO calls(session,label,reserved,status,details) VALUES(?,?,?,?,?)',(client.SESSION,'old',4.5,'reserved','{}'))
        with patch('studio.is_busy',return_value=False):
            result=ai_config.handle(Mock(),{'action':'budget','limit':2})
        self.assertEqual(result['budget']['reserved_or_peak_cost'],4.5)
        self.assertEqual(result['budget']['remaining'],0)
        with patch.object(client,'request') as request,self.assertRaisesRegex(RuntimeError,'预算'):
            workflow_ai.complete('x',{},'blocked',lambda x:x)
        request.assert_not_called()

    def test_active_task_blocks_changes_and_model_network_query(self):
        with patch('studio.is_busy',return_value=True),patch.object(client,'request') as request:
            for action in ['save','models','budget']:
                with self.assertRaisesRegex(ValueError,'任务运行中'):ai_config.handle(Mock(),{'action':action})
        request.assert_not_called()

    def test_model_catalog_only_returns_valid_identifiers(self):
        with patch('studio.is_busy',return_value=False),patch.object(client,'request',return_value={'data':[{'id':'fixture-a'},{'id':'fixture-a'},{'id':'<script>'},{'wrong':'x'}]}):
            result=ai_config.handle(Mock(),{'action':'models'})
        self.assertEqual(result,{'models':['fixture-a']})

    def test_damaged_configuration_keeps_workbench_accessible_and_requires_explicit_repair(self):
        for broken in ['{broken',json.dumps({'models':None}),json.dumps({'api_key':{'secret':'invalid'}})]:
            with self.subTest(broken=broken):
                ai_config.path(self.root).write_text(broken,encoding='utf-8')
                public=ai_config.public(self.root)
                self.assertFalse(public['configured']);self.assertIn('configuration_error',public)
                with self.assertRaises(ValueError):self.save(model='fixture-model')
                self.assertEqual(ai_config.path(self.root).read_text(encoding='utf-8'),broken)
                self.save(base_url='https://api.deepseek.com',model='fixture-model',pricing=ai_config.DEFAULT_PRICING,clear_key=True)
                self.assertEqual(ai_config.load(self.root)['model'],'fixture-model')

    def test_malformed_catalog_is_a_recoverable_error(self):
        for response in [None,{'data':None},{'data':{}}]:
            with patch('studio.is_busy',return_value=False),patch.object(client,'request',return_value=response),self.assertRaisesRegex(RuntimeError,'模型列表'):
                ai_config.handle(Mock(),{'action':'models'})

    def test_missing_key_does_not_consume_budget_or_start_a_request(self):
        self.save(clear_key=True)
        with patch.object(client,'request') as request:
            for _ in range(3):
                with self.assertRaisesRegex(RuntimeError,'填写密钥'):workflow_ai.complete('s',{},'no-key',lambda x:x)
        request.assert_not_called()
        self.assertEqual(workflow_ai.budget()['reserved_or_peak_cost'],0)

if __name__=='__main__':unittest.main()
