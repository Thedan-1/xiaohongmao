import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import workflow_ai

class UsageBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name);(root/'data').mkdir();(root/'deepseek.local.txt').write_text('DEEPSEEK_API_KEY=offline-fixture\n',encoding='utf-8')
        self.root=patch.object(workflow_ai.client,'ROOT',root);self.root.start()
    def tearDown(self):self.root.stop();self.tmp.cleanup()
    def response(self,usage):return {'usage':usage,'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}

    def test_unverified_usage_never_releases_reserved_liability(self):
        cases=[{'total_tokens':12},{'total_tokens':12,'prompt_tokens':-1,'completion_tokens':13},
            {'total_tokens':12,'prompt_tokens':10,'completion_tokens':1},
            {'total_tokens':12,'prompt_tokens':10,'completion_tokens':2,'prompt_cache_hit_tokens':11},
            {'total_tokens':'12','prompt_tokens':'10','completion_tokens':'2'},
            {'total_tokens':12,'prompt_tokens':True,'completion_tokens':11}]
        for i,usage in enumerate(cases):
            with self.subTest(usage=usage),patch.object(workflow_ai.client,'request',return_value=self.response(usage)):
                self.assertEqual(workflow_ai.complete('s',{'i':i},'usage-boundary',lambda x:x),{'ok':True})
                con=workflow_ai._db()
                try:
                    row=con.execute('SELECT reserved,status,details FROM calls ORDER BY id DESC LIMIT 1').fetchone()
                    self.assertGreaterEqual(workflow_ai.liability([row]),row[0])
                finally:con.close()

    def test_valid_usage_can_replace_reservation_with_verified_cost(self):
        usage={'total_tokens':12,'prompt_tokens':10,'completion_tokens':2,'prompt_cache_hit_tokens':5}
        with patch.object(workflow_ai.client,'request',return_value=self.response(usage)):
            workflow_ai.complete('s',{},'valid-usage',lambda x:x)
        con=workflow_ai._db()
        try:
            row=con.execute('SELECT reserved,status,details FROM calls').fetchone()
            self.assertAlmostEqual(workflow_ai.liability([row]),(5*.04+5*2+2*8)/1_000_000)
            self.assertLess(workflow_ai.liability([row]),row[0])
        finally:con.close()

    def test_corrupt_cached_cost_never_frees_budget(self):
        usage={'total_tokens':12,'prompt_tokens':10,'completion_tokens':2}
        for cost in (float('nan'),float('inf'),-1,0,'wrong'):
            with self.subTest(cost=cost):
                self.assertGreaterEqual(workflow_ai.liability([(.2,'complete',json.dumps({'usage':usage,'cost_cny_peak':cost}))]),.2)

    def test_transport_timeout_remains_fully_reserved_and_never_retries(self):
        with patch.object(workflow_ai.client,'request',side_effect=RuntimeError('DeepSeek TimeoutError')) as call:
            with self.assertRaises(RuntimeError):workflow_ai.complete('s',{},'timeout',lambda x:x)
            call.assert_called_once()
        con=workflow_ai._db()
        try:
            row=con.execute('SELECT reserved,status,details FROM calls').fetchone()
            self.assertEqual(workflow_ai.liability([row]),row[0]);self.assertEqual(row[1],'failed_or_uncertain')
        finally:con.close()

if __name__=='__main__':unittest.main()
