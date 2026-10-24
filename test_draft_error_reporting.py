import json
import threading
import unittest
from unittest.mock import Mock,patch
import app,studio
from test_studio import StudioTests

class DraftErrorReportingTests(unittest.TestCase):
    setUp=StudioTests.setUp
    tearDown=StudioTests.tearDown

    def test_invalid_model_output_preserves_existing_draft_and_never_uses_browser(self):
        sources=[{'key':str(i),'author':'作者','title':'示例'} for i in range(2)]
        with app.connect() as con:
            old=con.execute("INSERT INTO studio_drafts(project_id,account_id,channel,items,status) VALUES(1,'own','note','[]','preview')").lastrowid
        for raw in ({'variants':[]},{'variants':['示例']},{'variants':['示例！','示例。']},{'variants':[None]},{},None,[],{'variants':'示例'}):
            with self.subTest(raw=raw):
                worker=Mock()
                def fake_ai(system,data,label,validate,**kwargs):return validate(raw)
                with patch.object(app,'STOP',threading.Event()),patch.object(studio,'state',return_value={'notes':sources,'people':[]}),patch.object(studio.ai,'complete',side_effect=fake_ai):
                    with self.assertRaises(ValueError) as caught:
                        studio.draft(app,worker,{'project_id':1,'channel':'note','mode':'ai_unique','template':'示例','ids':['0','1']})
                error=studio.readable_error(caught.exception,'draft')
                self.assertEqual(error['title'],'文案预览生成失败')
                self.assertIn('没有发送',error['advice'])
                self.assertEqual(worker.mock_calls,[])
                with app.connect() as con:
                    self.assertEqual([tuple(r) for r in con.execute('SELECT id,items,status FROM studio_drafts')],[(old,'[]','preview')])
                    self.assertEqual(con.execute('SELECT count(*) FROM studio_receipts').fetchone()[0],0)

    def test_existing_failed_job_renders_specific_preview_error(self):
        error={'detail':'AI 逐条文案数量不足或内容重复，未生成草稿，也没有发送','title':'本步骤未完成'}
        with app.connect() as con:
            con.execute("INSERT INTO studio_jobs(project_id,kind,status,payload,error,created_at,updated_at) VALUES(1,'draft','failed',?,?,?,?)",(json.dumps({'ids':['1']}),json.dumps(error),studio.now(),studio.now()))
            state=studio.state(con,1)
        self.assertEqual(json.loads(state['jobs'][0]['error'])['title'],'文案预览生成失败')

    def test_send_timeout_still_requires_verification(self):
        error=studio.readable_error(RuntimeError('Timeout after submission'),'send')
        self.assertIn('必须先核实',error['advice'])

if __name__=='__main__':unittest.main()
