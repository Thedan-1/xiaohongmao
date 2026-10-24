import json
import tempfile
import threading
import unittest
from contextlib import ExitStack,nullcontext
from pathlib import Path
from unittest.mock import Mock,patch
import app,batch_comments as batch,comment_flow,lead_review


def capture(i):
    return dict(title='BIM建模',body='提供BIM建模服务',author='作者',profile_url='https://www.xiaohongshu.com/user/profile/author',
                note_url=f'https://www.xiaohongshu.com/explore/n{i}',
                comments=[dict(id=f'comment-{i}c{j}',text='想找自动建模工具',author='客户',profile_url=f'https://www.xiaohongshu.com/user/profile/u{i}-{j}',parent_text='',parent_id='') for j in range(20)],
                seconds=.01,timings={'open_and_body':.005,'comments':.005},scrolls=0,notice='测试')


class BatchTests(unittest.TestCase):
    def test_connection_failure_keeps_confirmed_queries_for_resume(self):
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            stack.enter_context(patch.object(app,'DB',Path(folder)/'test.db'));app.init_db()
            worker=Mock();worker.background.side_effect=RuntimeError('fixture connection stalled')
            with patch.object(batch.ai,'budget',return_value={'reserved_or_peak_cost':0}):
                with self.assertRaisesRegex(RuntimeError,'connection stalled'):
                    batch.find(worker,{'topic':'MAD','criteria':'学剪辑','count':20,'queries':['MAD教程','MAD转场']},threading.Event(),app.connect,Mock(),Mock())
            with app.connect() as con:
                row=con.execute('SELECT status,report FROM comment_runs ORDER BY id DESC LIMIT 1').fetchone()
                self.assertEqual(row['status'],'failed');self.assertEqual(json.loads(row['report'])['queries'],['MAD教程','MAD转场'])

    def test_twenty_notes_two_requests_and_no_send(self):
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            stack.enter_context(patch.object(app,'DB',Path(folder)/'test.db'));app.init_db()
            worker=Mock();worker.browser_operation.side_effect=lambda *a:nullcontext()
            worker.page.locator.return_value.filter.return_value.first.get_attribute.return_value='/user/profile/me'
            rows=[dict(note_url=capture(i)['note_url'],note_title='BIM建模') for i in range(20)]
            requests=[];read_after_first=threading.Event()
            def read(page,r,stop):
                i=int(r['note_url'].split('/n')[-1])
                if i==10:read_after_first.set()
                return capture(i)
            def decide(topic,goal,notes):
                if not requests:self.assertTrue(read_after_first.wait(2),'第一批 AI 阻塞第二批读取')
                requests.append((len(notes),sum(len(n['comments']) for n in notes)))
                return [dict(id=batch.compact(n)['id'],relevant=True,author_contact=False,reason='找工具',contacts=[{'id':c['id'],'evidence':c['text']} for c in n['comments'][:2]]) for n in notes]
            for obj,name,kw in [(batch.ai,'budget',dict(return_value={'reserved_or_peak_cost':0})),(batch.ai,'plan',dict(return_value={'queries':['BIM','土建BIM接单']})),
                (batch.adapter,'collect_search',dict(return_value=iter(rows))),
                (comment_flow,'screen_notes',dict(side_effect=lambda t,items:[dict(id=i['id'],relevant=True) for i in items])),
                (batch.note_collector,'collect_ready',dict(side_effect=read)),(batch,'decide',dict(side_effect=decide)),(lead_review,'refine',dict(side_effect=lambda t,g,items:[dict(**r,decision='keep',category='need',evidence=r['source_text'],reason='需求明确') for r in items]))]:stack.enter_context(patch.object(obj,name,**kw))
            preflight=stack.enter_context(patch.object(comment_flow,'post_one',return_value={'submitted':False,'draft_cleared':True}))
            batch.find(worker,{'topic':'BIM','criteria':'推广建模工具','count':20,'auto_preflight':True,'expand_queries':True},threading.Event(),app.connect,Mock(),Mock())
            self.assertEqual(requests,[(10,200),(10,200)])
            preflight.assert_called_once()
            self.assertTrue(preflight.call_args.kwargs['preview_only'])
            with app.connect() as con:
                state=comment_flow.state(con)
                self.assertEqual(len(state['targets']),20)
                self.assertEqual(len(state['leads']),40)
                pending,seen=lead_review.unused_sources(con,'BIM')
                self.assertEqual(len(seen),20);self.assertEqual(pending,[])
                self.assertEqual(state['report']['comments_read'],400)
                self.assertEqual(state['report']['queries'],['土建BIM接单'])
                self.assertEqual(con.execute('SELECT COUNT(*) FROM comment_sends').fetchone()[0],0)
                self.assertTrue(all(t['message']=='1' and t['kind']=='reply' for t in state['targets']))
            with self.assertRaisesRegex(ValueError,'停在发送前'):
                comment_flow.send(worker,{'run_id':state['id']},threading.Event(),app.connect,Mock(),Mock())

    def test_invalid_ids_are_excluded_and_original_text_is_preserved(self):
        def fake(system,data,label,validator,**kwargs):
            return validator({'notes':[dict(id='n0',relevant=True,author_contact=False,contacts=['comment-1c0','c0']),dict(id='n1',relevant=True,author_contact=False,contacts=[])]})
        with patch.object(batch.ai,'complete',side_effect=fake):
            result=batch.decide('BIM','找客户',[capture(0),capture(1)])
            self.assertEqual(result[0]['contacts'],[dict(id='comment-0c0',evidence='想找自动建模工具')])
            self.assertEqual(result[0]['rejected_comment_ids'],['comment-1c0'])

    def test_missing_note_and_nonboolean_are_rejected(self):
        for rows in ([],[dict(id='n0',relevant='yes',author_contact=False,contacts=[])]):
            with patch.object(batch.ai,'complete',side_effect=lambda s,d,l,v,**k:v({'notes':rows})):
                with self.assertRaises(ValueError):batch.decide('BIM','找客户',[capture(0)])

    def test_batches_split_by_payload_size(self):
        notes=[capture(i) for i in range(10)]
        for n in notes:
            for c in n['comments']:c['text']='模'*600;c['parent_text']='型'*250
        groups=list(batch.batches(notes))
        self.assertGreater(len(groups),1)
        self.assertEqual(sum(map(len,groups)),10)


if __name__=='__main__':unittest.main()
