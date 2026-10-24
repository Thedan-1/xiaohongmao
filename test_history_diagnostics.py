import json,threading,unittest
from unittest.mock import Mock,patch
import app,studio,comment_flow,test_studio

class HistoryDiagnosticsTests(unittest.TestCase):
    def test_scan_limit_reports_loaded_total_and_does_not_send(self):
        page=Mock();page.locator.return_value.evaluate_all.return_value=[]
        page.locator.return_value.get_by_text.return_value.count.return_value=0
        page.evaluate.return_value={'count':40,'total':621,'complete':False}
        stop=Mock();stop.is_set.return_value=False;stop.wait.return_value=False
        with patch.object(comment_flow,'checkpoint'):
            with self.assertRaisesRegex(comment_flow.HistoryUnverified,'40.*621.*2'):
                comment_flow.verify_comment_history(page,{'kind':'note'},'own',stop,max_steps=2)

    def test_partial_failure_displays_success_review_and_unstarted_counts(self):
        test_studio.StudioTests.setUp(self)
        try:
            items=[{'status':'sent'},{'status':'needs_review'}]+[{'status':'ready'} for _ in range(8)]
            with app.connect() as con:
                did=con.execute("INSERT INTO studio_drafts(project_id,channel,items,status) VALUES(1,'note',?,'needs_review')",(json.dumps(items),)).lastrowid
                con.execute("INSERT INTO studio_jobs(project_id,kind,status,payload,error) VALUES(1,'send','failed',?,?)",(json.dumps({'draft_id':did}),json.dumps({'title':'历史记录无法核实','advice':'请核实','detail':'本条未发送'})))
                error=json.loads(studio.state(con,1)['jobs'][0]['error'])
            self.assertIn('已确认发送 1 条',error['advice']);self.assertIn('待核实 1 条',error['advice']);self.assertIn('未执行 8 条',error['advice'])
        finally:test_studio.StudioTests.tearDown(self)

    def test_legacy_plain_error_does_not_break_project_read(self):
        test_studio.StudioTests.setUp(self)
        try:
            with app.connect() as con:
                con.execute("INSERT INTO studio_jobs(project_id,kind,status,payload,error) VALUES(1,'send','failed','{}','legacy error')")
                self.assertEqual(studio.state(con,1)['jobs'][0]['error'],'legacy error')
        finally:test_studio.StudioTests.tearDown(self)

    def test_other_project_draft_cannot_supply_batch_counts(self):
        test_studio.StudioTests.setUp(self)
        try:
            other=studio.request(app,{'action':'create'})['project_id']
            with app.connect() as con:
                did=con.execute("INSERT INTO studio_drafts(project_id,channel,items) VALUES(?,'note','[{\"status\":\"sent\"}]')",(other,)).lastrowid
                err={'title':'failed','advice':'original'}
                self.assertEqual(studio.send_error_context(con,1,{'draft_id':did},err),err)
        finally:test_studio.StudioTests.tearDown(self)

if __name__=='__main__':unittest.main()
