import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app,discovery,topic_state,workflow_ai

class TopicTests(unittest.TestCase):
    def test_switch_restores_drafts_and_keeps_evidence_per_topic(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'DB',Path(tmp)/'test.db'):
            app.init_db()
            with app.connect() as con:
                bim={'topic':'BIM','purpose':'推广建模工具','message':'BIM draft','target_count':8}
                fresh=topic_state.switch(con,bim,'LOL混剪')
                self.assertEqual(fresh['message'],'')
                lol={'topic':'LOL混剪','purpose':'学习剪辑','message':'LOL draft','target_count':40}
                restored=topic_state.switch(con,lol,'BIM')
                self.assertEqual(restored,bim)
                self.assertEqual(topic_state.switch(con,restored,'LOL混剪'),lol)
                source={'author':'作者','profile_url':'https://www.xiaohongshu.com/user/profile/abc','kind':'note_author','note_url':'https://www.xiaohongshu.com/explore/abc','note_title':'BIM','text':'提供建筑建模服务'}
                result={'fit':'high','evidence_verified':True,'evidence':source['text'],'intent':'建模','uncertainty':''}
                lead_id=discovery.save_candidate(con,'BIM',source,result,'推广建模工具')
                con.execute("INSERT INTO contacts(lead_id,channel,message,status) VALUES(?,'dm','existing','sent')",(lead_id,))
                source.update(note_title='LOL混剪',text='分享我的游戏混剪教程')
                result.update(fit='potential',evidence=source['text'],intent='剪辑教程')
                self.assertEqual(discovery.save_candidate(con,'LOL混剪',source,result,'学习剪辑'),lead_id)
                self.assertEqual(topic_state.leads(con,'BIM','推广建模工具')[0]['ai_intent'],'建模')
                self.assertEqual(topic_state.leads(con,'LOL混剪','学习剪辑')[0]['ai_intent'],'剪辑教程')
                self.assertEqual(topic_state.leads(con,'LOL混剪','招聘剪辑师'),[])
                self.assertEqual(con.execute('SELECT COUNT(*) FROM contacts').fetchone()[0],1)

    def test_ai_uses_current_topic_and_purpose(self):
        with patch.object(workflow_ai,'complete',return_value=[]) as call:
            workflow_ai.intent('LOL混剪',[],'请教混剪怎么学')
            system,data=call.call_args.args[:2]
            self.assertEqual(data['topic'],'LOL混剪')
            self.assertEqual(data['contact_goal'],'请教混剪怎么学')
            self.assertNotIn('你是土建平面图',system)

if __name__=='__main__':unittest.main()
