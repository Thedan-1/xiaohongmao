import json,threading,unittest
from contextlib import nullcontext
from unittest.mock import Mock,patch
import app,studio,batch_comments,test_studio

class WorkflowBoundaryTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown

    def test_malformed_plans_are_clear_validation_errors(self):
        for bad in (None,[],42,'BIM',{'topic':None,'queries':['A']},{'topic':'A','queries':None}):
            with self.subTest(plan=bad),self.assertRaises(ValueError):studio.validate_plan(bad)

    def test_counts_outside_bounds_are_not_silently_changed(self):
        for count in (True,False,0,-1,101,100000,1.5,'2.5',None,'很多'):
            with self.subTest(count=count),self.assertRaises(ValueError):studio.validate_plan({'topic':'A','queries':['A'],'count':count})
        for count in (1,100,'20'):
            with self.subTest(count=count):self.assertEqual(studio.validate_plan({'topic':'A','queries':['A'],'count':count})['count'],int(count))

    def test_error_categories_do_not_confuse_budget_and_platform_limits(self):
        cases=[('已达到AI预算上限','预算'),('DeepSeek HTTP 429','AI'),('DeepSeek HTTP 503','AI'),('初筛ID不匹配','AI'),('需要登录或安全验证','登录'),('操作过于频繁','平台'),('Target closed','浏览器')]
        for raw,label in cases:
            with self.subTest(error=raw):self.assertIn(label,studio.readable_error(RuntimeError(raw),'search')['title'])

    def test_resume_never_reuses_another_topic_or_goal(self):
        old={'topic':'BIM','goal':'推广建模工具','queries':['Revit'],'count':10}
        with app.connect() as con:
            rid=con.execute('INSERT INTO comment_runs(topic,criteria,report) VALUES(?,?,?)',(old['topic'],old['goal'],json.dumps({'queries':old['queries']}))).lastrowid
            con.execute('INSERT INTO studio_runs(project_id,run_id) VALUES(1,?)',(rid,))
            studio.compatible_resume(con,1,old)
            for change in ({'topic':'LOL'},{'goal':'学习教程'},{'queries':['王者荣耀剪辑']}):
                with self.subTest(change=change),self.assertRaisesRegex(ValueError,'搜索条件'):studio.compatible_resume(con,1,{**old,**change})

    def test_empty_search_finishes_truthfully_without_ai_or_send(self):
        worker=Mock();worker.browser_operation.side_effect=lambda *a:nullcontext()
        worker.page.locator.return_value.filter.return_value.first.get_attribute.return_value='/user/profile/own'
        with patch.object(batch_comments.ai,'budget',return_value={'reserved_or_peak_cost':0}),patch.object(batch_comments.adapter,'collect_search',return_value=[]),patch.object(batch_comments.ai,'complete') as ai_call:
            batch_comments.find(worker,{'topic':'王者荣耀剪辑','criteria':'找创作者','count':10,'queries':['王者荣耀剪辑']},threading.Event(),app.connect,Mock(),Mock())
            ai_call.assert_not_called();worker.send.assert_not_called()
        with app.connect() as con:
            r=con.execute('SELECT status,report FROM comment_runs ORDER BY id DESC LIMIT 1').fetchone()
            self.assertEqual(r['status'],'insufficient');self.assertEqual(json.loads(r['report'])['read'],0)

    def test_unavailable_note_does_not_abort_other_notes(self):
        from test_batch_comments import capture
        worker=Mock();worker.browser_operation.side_effect=lambda *a:nullcontext()
        worker.page.locator.return_value.filter.return_value.first.get_attribute.return_value='/user/profile/own'
        rows=[{'note_url':capture(i)['note_url'],'note_title':'王者荣耀剪辑'} for i in range(3)]
        def read(page,r,stop):
            i=int(r['note_url'].split('/n')[-1])
            if i==0:raise RuntimeError('笔记已删除')
            return capture(i)
        with patch.object(batch_comments.ai,'budget',return_value={'reserved_or_peak_cost':0}),patch.object(batch_comments.adapter,'collect_search',return_value=rows),patch('comment_flow.screen_notes',side_effect=lambda t,ns:[{'id':n['id'],'relevant':True} for n in ns]),patch.object(batch_comments.note_collector,'collect_ready',side_effect=read),patch.object(batch_comments.adapter,'checkpoint'),patch.object(batch_comments,'decide',side_effect=lambda t,g,ns:[{'id':batch_comments.compact(n)['id'],'relevant':True,'contacts':[],'author_contact':False} for n in ns]):
            batch_comments.find(worker,{'topic':'王者荣耀剪辑','criteria':'找创作者','count':2,'queries':['王者荣耀剪辑']},threading.Event(),app.connect,Mock(),Mock())
        with app.connect() as con:
            r=json.loads(con.execute('SELECT report FROM comment_runs ORDER BY id DESC LIMIT 1').fetchone()[0]);self.assertEqual(r['read'],2);self.assertEqual(r['failed_reads'],1)

    def test_body_analysis_repairs_missing_note_once_without_guessing_ids(self):
        from test_batch_comments import capture
        replies=[{'notes':[]},{'notes':[{'id':'n0','relevant':True,'author_contact':True,'contacts':[]}]}]
        with patch.object(batch_comments.ai,'complete',side_effect=lambda p,d,l,v,**kw:v(replies.pop(0))) as complete:
            rows=batch_comments.decide('王者荣耀剪辑','找创作者',[capture(0)])
        self.assertEqual(complete.call_count,2);self.assertTrue(rows[0]['author_contact']);self.assertEqual(rows[0]['id'],'n0')

    def test_evidence_review_repairs_format_but_never_accepts_fabricated_evidence(self):
        import lead_review
        item={'source_text':'分享王者荣耀混剪教程','title':'王者荣耀','kind':'note'}
        replies=[{'results':[]},{'results':[{'id':'0','decision':'keep','category':'provider','evidence':'我需要建模工具','reason':'错误引用'}]}]
        with patch.object(lead_review.ai,'complete',side_effect=lambda p,d,l,v,**kw:v(replies.pop(0))) as complete:
            rows=lead_review.refine('王者荣耀剪辑','找创作者',[item])
        self.assertEqual(complete.call_count,2);self.assertEqual(rows[0]['decision'],'skip')

    def test_body_analysis_correction_stops_after_second_invalid_response(self):
        from test_batch_comments import capture
        with patch.object(batch_comments.ai,'complete',side_effect=lambda p,d,l,v,**kw:v({'notes':[]})) as complete:
            with self.assertRaisesRegex(ValueError,'仍未通过核验'):batch_comments.decide('剪辑','找创作者',[capture(0)])
        self.assertEqual(complete.call_count,2)

    def test_ai_transport_or_budget_failure_is_never_retried_as_schema_repair(self):
        import workflow_ai
        for message in ('HTTP 429','预算不足','Timeout'):
            with self.subTest(error=message),patch.object(workflow_ai,'complete',side_effect=RuntimeError(message)) as complete:
                with self.assertRaises(RuntimeError):workflow_ai.complete_verified('prompt',{},'test',lambda raw:raw)
                complete.assert_called_once()

if __name__=='__main__':unittest.main()
