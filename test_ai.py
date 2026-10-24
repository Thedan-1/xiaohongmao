import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import deepseek_client as ai

class AnalysisTests(unittest.TestCase):
    def test_budget_is_reserved_even_when_call_fails(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(ai,'ROOT',Path(folder)),patch.object(ai,'MAX_CALLS',2):
            (Path(folder)/'data').mkdir()
            with patch.object(ai,'request',side_effect=RuntimeError('offline')) as request:
                for _ in range(2):
                    with self.assertRaises(RuntimeError):ai.analyze([{'id':1,'text':'建模太慢'}],'test')
                with self.assertRaisesRegex(RuntimeError,'额度已用完'):ai.analyze([{'id':1,'text':'建模太慢'}],'test')
                self.assertEqual(request.call_count,2)

    def test_evidence_must_belong_to_comment_author(self):
        items=[{'id':'c1','text':'收藏了','parent_text':'想找自动建模软件'}]
        row={'id':'c1','fit':'high','customer_type':'客户','intent':'找工具','evidence':'想找自动建模软件','uncertainty':''}
        result=ai.validate(items,{'results':[row]})
        self.assertFalse(result[0]['evidence_verified']);self.assertEqual(result[0]['fit'],'unclear')

    def test_duplicate_result_ids_and_oversized_input_rejected(self):
        with self.assertRaises(ValueError):ai.validate([{'id':1,'text':'a'},{'id':2,'text':'b'}],{'results':[{'id':1},{'id':1}]})
        with patch.object(ai,'request') as request:
            with self.assertRaises(ValueError):ai.analyze([{'id':1,'text':'大'*30000}],'too large')
            request.assert_not_called()

if __name__=='__main__':unittest.main()
