import unittest
from unittest.mock import patch
import comment_flow

class ScreenRecoveryTests(unittest.TestCase):
    def test_one_missing_id_does_not_abort_whole_batch(self):
        items=[{'id':str(i),'text':'王者荣耀剪辑'} for i in range(50,53)]
        seen=[]
        def model(p,d,l,v,**kw):
            seen.append([x['id'] for x in d['items']])
            if len(seen)==1:return v({'results':[{'id':'50','relevant':True},{'id':'52','relevant':False}]})
            return v({'results':[{'id':'51','relevant':True}]})
        with patch.object(comment_flow.ai,'complete',side_effect=model):rows=comment_flow.screen_notes('王者荣耀剪辑',items)
        self.assertEqual(seen,[['50','51','52'],['51']])
        self.assertEqual([(r['id'],r['relevant']) for r in rows],[('50',True),('51',True),('52',False)])

    def test_wrong_and_duplicate_ids_are_never_mapped_by_position(self):
        calls=[]
        def model(p,d,l,v,**kw):
            calls.append(d['items'])
            return v({'results':[{'id':'0','relevant':False},{'id':'50','relevant':True},{'id':'50','relevant':False}]})
        with patch.object(comment_flow.ai,'complete',side_effect=model):
            rows=comment_flow.screen_notes('王者荣耀',[{'id':'50','text':'高燃剪辑'},{'id':'51','text':'剪辑教程'}])
        self.assertEqual(len(calls),2)
        self.assertEqual([r['id'] for r in rows],['50','51'])
        self.assertTrue(all(r['screen_status']=='unresolved' for r in rows))
        self.assertTrue(all(r['relevant'] for r in rows),'待核实标题必须交给正文分析，不能伪造不相关结论')

    def test_no_extra_call_when_ids_are_complete_even_if_reordered(self):
        with patch.object(comment_flow.ai,'complete',side_effect=lambda p,d,l,v,**kw:v({'results':[{'id':2,'relevant':False},{'id':'1','relevant':True}]})) as complete:
            rows=comment_flow.screen_notes('剪辑',[{'id':'1','text':'A'},{'id':'2','text':'B'}])
        complete.assert_called_once();self.assertEqual([r['id'] for r in rows],['1','2'])

    def test_resume_reuses_saved_candidates_without_browser_search(self):
        import tempfile,threading
        from pathlib import Path
        from contextlib import ExitStack,nullcontext
        from unittest.mock import Mock
        import app,batch_comments
        from test_batch_comments import capture
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            stack.enter_context(patch.object(app,'DB',Path(folder)/'db.sqlite3'));app.init_db()
            worker=Mock();worker.browser_operation.side_effect=lambda *a:nullcontext()
            worker.page.locator.return_value.filter.return_value.first.get_attribute.return_value='/user/profile/own'
            stack.enter_context(patch.object(batch_comments.ai,'budget',return_value={'reserved_or_peak_cost':0}))
            search=stack.enter_context(patch.object(batch_comments.adapter,'collect_search'))
            stack.enter_context(patch.object(comment_flow,'screen_notes',side_effect=lambda t,ns:[{'id':n['id'],'relevant':True} for n in ns]))
            stack.enter_context(patch.object(batch_comments.note_collector,'collect_ready',side_effect=lambda p,r,s:capture(int(r['note_url'].split('/n')[-1]))))
            stack.enter_context(patch.object(batch_comments,'decide',side_effect=lambda t,g,ns:[{'id':batch_comments.compact(n)['id'],'relevant':True,'contacts':[],'author_contact':False} for n in ns]))
            candidates=[{'note_url':capture(i)['note_url'],'note_title':'王者荣耀剪辑'} for i in range(2)]
            batch_comments.find(worker,{'topic':'王者荣耀剪辑','criteria':'找创作者','count':2,'queries':['王者荣耀剪辑'],'resume_candidates':candidates},threading.Event(),app.connect,Mock(),Mock())
            search.assert_not_called()
            with app.connect() as con:
                import json
                r=con.execute('SELECT status,report FROM comment_runs ORDER BY id DESC LIMIT 1').fetchone()
                self.assertEqual(r['status'],'preview');self.assertEqual(json.loads(r['report'])['recovered_entrances'],2)

if __name__=='__main__':unittest.main()
