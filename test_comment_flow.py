import json
import tempfile
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock,patch
import app,comment_flow

class CommentTests(unittest.TestCase):
    def test_author_restriction_skips_only_target_and_continues_batch(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'DB',Path(folder)/'test.db'):
            app.init_db();worker=Mock();worker.browser_operation.side_effect=lambda *x:nullcontext()
            with app.connect() as con:
                con.execute("INSERT INTO comment_runs(id,topic,report) VALUES(1,'fixture',?)",(json.dumps({'ai_before':0}),))
                for i in (1,2):con.execute("INSERT INTO comment_targets(id,run_id,note_key,title,kind,comment_id,message) VALUES(?,1,?,'fixture','note','','5')",(i,f'n{i}'))
            def post(page,target,stop,submitted,progress,**kwargs):
                submitted[0]=True
                if target['id']==1:raise comment_flow.CommentSubmissionRejected({'code':-9119,'success':False,'msg':'作者设置了仅关注的人可以评论'})
                return {'confirmed_on_page':True,'screenshot_saved':True}
            with patch.object(comment_flow.ai,'budget',return_value={'reserved_or_peak_cost':0}),patch.object(comment_flow,'post_one',side_effect=post) as submit:
                comment_flow.send(worker,{'run_id':1},threading.Event(),app.connect,Mock(),Mock())
            with app.connect() as con:
                self.assertEqual([r[0] for r in con.execute('SELECT status FROM comment_targets ORDER BY id')],['skipped','sent'])
                self.assertEqual(con.execute('SELECT status FROM comment_runs').fetchone()[0],'complete')
                self.assertIn('作者设置',con.execute('SELECT result FROM comment_targets WHERE id=1').fetchone()[0])
            self.assertEqual(submit.call_count,2)

    def test_seller_evidence_must_be_in_the_selected_comment(self):
        note=dict(title='LOL混剪',body='出售素材',comments=[dict(id='comment-a',author='甲',text='求素材',parent_text='')])
        def fake(system,data,label,validate):
            return validate(dict(relevant=True,reason='相关',seller_comment_id='comment-a',evidence='出售素材'))
        with patch.object(comment_flow.ai,'complete',side_effect=fake):
            with self.assertRaisesRegex(ValueError,'证据无法核实'):comment_flow.match_note('LOL混剪','出售素材',note)

    def test_twenty_notes_max_one_reply_each_and_no_implicit_send(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'DB',Path(folder)/'test.db'):
            app.init_db();worker=Mock();worker.browser_operation.side_effect=lambda *x:nullcontext()
            rows=[dict(name='作者',profile_url='https://www.xiaohongshu.com/user/profile/u1',note_url=f'https://www.xiaohongshu.com/explore/n{i}',note_title='LOL混剪') for i in range(25)]
            def collect(page,r,stop):return dict(title=r['note_title'],body='LOL混剪作品',author=r['name'],profile_url=r['profile_url'],note_url=r['note_url'],comments=[dict(id='comment-c1',author='卖家',profile_url='https://www.xiaohongshu.com/user/profile/u2',text='出售LOL素材20元',parent_id=None)])
            with patch.object(comment_flow.ai,'budget',return_value={'reserved_or_peak_cost':0}),patch.object(comment_flow.ai,'plan',return_value={'queries':['LOL混剪']}),patch.object(comment_flow,'collect_search',return_value=iter(rows)),patch.object(comment_flow,'screen_notes',side_effect=lambda t,items:[dict(id=i['id'],relevant=True) for i in items]),patch.object(comment_flow,'collect',side_effect=collect),patch.object(comment_flow,'match_note',return_value=dict(relevant=True,reason='混剪',seller_comment_id='comment-c1',evidence='出售LOL素材20元')):
                comment_flow.find(worker,{'topic':'LOL混剪','count':20},threading.Event(),app.connect,Mock(),Mock())
            with app.connect() as con:
                result=comment_flow.state(con)
                self.assertEqual(len(result['targets']),40)
                self.assertEqual(result['report']['accepted'],20)
                self.assertTrue(all(t['message']=='1' if t['kind']=='reply' else t['message'] in '123456789' for t in result['targets']))
                self.assertEqual(con.execute('SELECT COUNT(*) FROM comment_sends').fetchone()[0],0)

    def test_uncertain_submission_is_not_retried(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'DB',Path(folder)/'test.db'):
            app.init_db();worker=Mock();worker.browser_operation.side_effect=lambda *x:nullcontext()
            with app.connect() as con:
                con.execute("INSERT INTO comment_runs(id,topic,report) VALUES(1,'LOL混剪',?)",(json.dumps({'ai_before':0}),))
                con.execute("INSERT INTO comment_targets(id,run_id,note_key,title,kind,comment_id,message) VALUES(1,1,'n1','LOL混剪','note','','5')")
            def fail(page,target,stop,submitted,progress,*,local_receipt_checked=False):
                self.assertTrue(local_receipt_checked)
                submitted[0]=True
                raise RuntimeError('提交后无法确认')
            with patch.object(comment_flow.ai,'budget',return_value={'reserved_or_peak_cost':0}),patch.object(comment_flow,'post_one',side_effect=fail) as post:
                comment_flow.send(worker,{'run_id':1},threading.Event(),app.connect,Mock(),Mock())
                with app.connect() as con:
                    self.assertEqual(con.execute('SELECT status FROM comment_targets').fetchone()[0],'needs_review')
                    con.execute("UPDATE comment_targets SET status='ready'")
                comment_flow.send(worker,{'run_id':1},threading.Event(),app.connect,Mock(),Mock())
                self.assertEqual(post.call_count,1)

if __name__=='__main__':unittest.main()
