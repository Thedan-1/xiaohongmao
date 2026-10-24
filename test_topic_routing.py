import unittest
from unittest.mock import Mock,patch
import app,studio,test_studio

class TopicRoutingTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown

    def test_first_topic_is_not_presented_to_ai_as_pending_confirmation(self):
        with app.connect() as con:studio.message(con,1,'user','我想搜英雄联盟剪辑相关内容')
        def model(prompt,data,label,validate,**kwargs):
            self.assertIsNone(data['confirmation_step'],'新项目还没有搜索方案，却告诉模型正在确认方向')
            self.assertNotIn('confirm',data['allowed_actions'])
            return validate({'kind':'search','reply':'先确认搜索方向','plan':{'topic':'英雄联盟剪辑','queries':['LOL混剪','英雄联盟剪辑教程'],'count':20,'goal':'了解相关内容'}})
        with patch.object(studio.ai,'complete',side_effect=model):studio.chat(app,Mock(),{'project_id':1})
        with app.connect() as con:
            s=studio.state(con,1)
            self.assertEqual(s['project']['plan']['topic'],'英雄联盟剪辑')
            self.assertEqual(s['project']['setup_step'],'direction')
        self.assertTrue(app.COMMANDS.empty())

    def test_bad_confirmation_on_first_request_is_repaired_once_without_execution(self):
        with app.connect() as con:studio.message(con,1,'user','我想搜英雄联盟剪辑相关内容')
        replies=[{'kind':'confirm','step':'search','reply':'好的'},
                 {'kind':'search','reply':'确认这些方向','plan':{'topic':'英雄联盟剪辑','queries':['LOL混剪'],'count':20,'goal':'了解剪辑'}}]
        def model(p,d,l,v,**kw):return v(replies.pop(0))
        worker=Mock()
        with patch.object(studio.ai,'complete',side_effect=model) as complete:
            studio.chat(app,worker,{'project_id':1})
            self.assertEqual(complete.call_count,2)
        self.assertFalse(worker.mock_calls);self.assertTrue(app.COMMANDS.empty())
        with app.connect() as con:self.assertEqual(studio.state(con,1)['project']['setup_step'],'direction')

    def test_topic_switch_can_replace_plan_during_any_confirmation_step(self):
        for step in ('direction','count','goal','ready','done'):
            with self.subTest(step=step):
                with app.connect() as con:
                    old={'topic':'BIM','queries':['Revit'],'goal':'推广建模工具','count':80}
                    con.execute('UPDATE studio_projects SET plan=? WHERE id=1',(studio.dump(old),))
                    studio.store.set_step(con,1,step)
                    studio.message(con,1,'user','不找BIM了，改找咖啡拉花教程')
                raw={'kind':'search','reply':'改为咖啡拉花方向','plan':{'topic':'咖啡拉花','queries':['咖啡拉花教程'],'goal':'了解学习方法','count':20}}
                with patch.object(studio.ai,'complete',side_effect=lambda p,d,l,v,**kw:v(raw)):studio.chat(app,Mock(),{'project_id':1})
                with app.connect() as con:
                    s=studio.state(con,1)
                    self.assertEqual(s['project']['plan']['topic'],'咖啡拉花')
                    self.assertNotIn('建模',s['project']['plan']['goal'])
                    self.assertEqual(s['project']['setup_step'],'direction')
                self.assertTrue(app.COMMANDS.empty())

    def test_repeated_invalid_actions_stop_after_one_repair_and_preserve_plan(self):
        raw={'kind':'confirm','reply':'好的','step':'count','count':20}
        with patch.object(studio.ai,'complete',side_effect=lambda p,d,l,v,**kw:v(raw)) as complete:
            with self.assertRaisesRegex(ValueError,'尚未执行'):studio.chat(app,Mock(),{'project_id':1})
            self.assertEqual(complete.call_count,2)
        with app.connect() as con:self.assertEqual(studio.state(con,1)['project']['plan'],{})

    def test_network_errors_are_not_retried_as_format_errors(self):
        with patch.object(studio.ai,'complete',side_effect=RuntimeError('HTTP 429')) as complete:
            with self.assertRaisesRegex(RuntimeError,'429'):studio.chat(app,Mock(),{'project_id':1})
            complete.assert_called_once()

if __name__=='__main__':unittest.main()
