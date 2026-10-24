import json,threading,unittest
from unittest.mock import Mock,patch
import app,studio
from test_studio import StudioTests

class PreviewParityTests(unittest.TestCase):
    setUp=StudioTests.setUp
    tearDown=StudioTests.tearDown
    def test_ai_unique_rejects_duplicates_and_assigns_one_model_text_per_target(self):
        sources=[{'key':str(i),'author':'A','title':'英雄联盟 S16'} for i in range(2)]
        payload={'project_id':1,'channel':'note','mode':'ai_unique','template':'S16加油','ids':['0','1']}
        def duplicate(system,data,label,validate,**kwargs):return validate({'variants':['S16加油！','S16加油。']})
        def distinct(system,data,label,validate,**kwargs):return validate({'variants':['S16加油，期待精彩对局！','为S16打气，祝比赛顺利！']})
        with patch.object(app,'STOP',threading.Event()),patch.object(studio,'state',return_value={'notes':sources,'people':[]}),patch.object(studio.ai,'complete',side_effect=duplicate):
            with self.assertRaisesRegex(ValueError,'需要 2 条，返回 2 条.*有 1 条'):studio.draft(app,Mock(),payload)
        with app.connect() as con:self.assertEqual(con.execute('SELECT count(*) FROM studio_drafts').fetchone()[0],0)
        def placeholders(system,data,label,validate,**kwargs):return validate({'variants':['S16加油，{作者甲}！','为S16打气！']})
        with patch.object(app,'STOP',threading.Event()),patch.object(studio,'state',return_value={'notes':sources,'people':[]}),patch.object(studio.ai,'complete',side_effect=placeholders):
            with self.assertRaisesRegex(ValueError,'占位符'):studio.draft(app,Mock(),payload)
        with patch.object(app,'STOP',threading.Event()),patch.object(studio,'state',return_value={'notes':sources,'people':[]}),patch.object(studio.ai,'complete',side_effect=distinct):
            studio.draft(app,Mock(),payload)
        with app.connect() as con:
            items=json.loads(con.execute('SELECT items FROM studio_drafts').fetchone()[0]);self.assertEqual(len({x['message'] for x in items}),2)
    def compare(self,count):
        original=studio.state
        sources=[{'key':str(i),'author':'author'+str(i),'title':'BIM','body':'BIM教学','type':'image','contact_status':'ready','url':'https://www.xiaohongshu.com/explore/'+str(i)} for i in range(20)]
        def state(con,pid):
            s=original(con,pid);s['notes']=sources;return s
        payload={'channel':'note','mode':'exact','template':'想学习BIM从哪里开始 求佬教教','ids':[str(i) for i in range(count)]}
        worker=Mock()
        with patch.object(app,'STOP',threading.Event()),patch.object(studio,'state',side_effect=state),patch.object(studio.ai,'complete',return_value={'kind':'draft','reply':'preview','draft':payload}):
            studio.chat(app,worker,{'project_id':1,'text':'生成预览，不发送'})
            with app.connect() as con:
                first=con.execute('SELECT id,items FROM studio_drafts').fetchone();self.assertEqual(len(json.loads(first['items'])),count)
            studio.draft(app,worker,{'project_id':1,**payload})
            with app.connect() as con:
                self.assertEqual(con.execute('SELECT count(*) FROM studio_drafts').fetchone()[0],1)
                second=con.execute('SELECT id,items FROM studio_drafts').fetchone();self.assertEqual(tuple(first),tuple(second))
            studio.draft(app,worker,{'project_id':1,**payload,'template':'修改后的未发送预览'})
            with app.connect() as con:
                updated=con.execute('SELECT id,items FROM studio_drafts').fetchone();self.assertEqual(updated['id'],first['id'])
                self.assertTrue(all(x['message']=='修改后的未发送预览' for x in json.loads(updated['items'])))
                self.assertEqual(con.execute('SELECT count(*) FROM studio_receipts').fetchone()[0],0)
            if count==4:
                studio.draft(app,worker,{'project_id':1,**payload,'ids':[str(i) for i in range(20)]})
                with app.connect() as con:
                    rows=con.execute('SELECT id,items FROM studio_drafts').fetchall()
                    self.assertEqual(len(rows),1);self.assertEqual(rows[0]['id'],first['id']);self.assertEqual(len(json.loads(rows[0]['items'])),20)
        worker.send.assert_not_called()
    def test_four_selected_targets_match_natural_and_button_preview(self):self.compare(4)
    def test_twenty_selected_targets_match_natural_and_button_preview(self):self.compare(20)
    def test_empty_selection_is_rejected_before_a_job_is_created(self):
        with self.assertRaisesRegex(ValueError,'还没有选择对象'):
            studio.request(app,{'action':'draft','project_id':1,'channel':'note','mode':'exact','template':'hello','ids':[]})
        with app.connect() as con:self.assertEqual(con.execute('SELECT count(*) FROM studio_jobs').fetchone()[0],0)
        self.assertTrue(app.COMMANDS.empty())

if __name__=='__main__':unittest.main()
