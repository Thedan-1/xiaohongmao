import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
import app
import discovery
import workflow_ai

class DiscoveryTests(unittest.TestCase):
    def test_comment_targets_commenter_and_preserves_do_not_contact(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(app,'DB',Path(folder)/'test.sqlite3'):
            app.init_db()
            raw={'name':'笔记作者','profile_url':'https://www.xiaohongshu.com/user/profile/author1','note_url':'https://www.xiaohongshu.com/explore/note1','note_title':'BIM经验'}
            note={'author':'笔记作者','profile_url':raw['profile_url'],'title':raw['note_title'],'body':'建模经验','note_url':raw['note_url'],'comments':[{'id':'comment-c1','author':'求工具的人','profile_url':'https://www.xiaohongshu.com/user/profile/commenter1','text':'我想找平面图自动生成模型的工具','is_note_author':False,'parent_text':''}]}
            def intent(topic,items,purpose=""):
                return [{'id':i['id'],'fit':'potential' if i['source_type']=='comment' else 'low','intent':'寻找建模工具','customer_type':'使用者','evidence':i['text'],'uncertainty':'需求待核实','evidence_verified':True} for i in items]
            worker=Mock();updates=[]
            from contextlib import nullcontext
            worker.browser_operation.side_effect=lambda *args:nullcontext()
            with patch.object(discovery.ai,'plan',return_value={'queries':['BIM建模'],'scope':'BIM'}),patch.object(discovery.ai,'relevance',return_value=[{'id':'note1','relevant':True,'reason':'建筑建模'}]),patch.object(discovery.ai,'intent',side_effect=intent),patch.object(discovery,'collect_search',return_value=iter([raw])),patch.object(discovery,'collect',return_value=note),patch.object(discovery,'checkpoint'):
                discovery.run(worker,{'topic':'BIM'},threading.Event(),app.connect,lambda **x:updates.append(x),lambda *x:None)
            with app.connect() as con:
                rows=con.execute('SELECT * FROM leads').fetchall()
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]['profile_url'],note['comments'][0]['profile_url'])
                self.assertEqual(rows[0]['source_kind'],'commenter')
                self.assertEqual(con.execute('SELECT COUNT(*) FROM contacts').fetchone()[0],0)
                con.execute("UPDATE leads SET status='do_not_contact'")
                source={'author':'新昵称','profile_url':rows[0]['profile_url'],'kind':'commenter','note_url':raw['note_url'],'note_title':raw['note_title'],'text':'找工具','comment_id':'comment-c2'}
                discovery.save_candidate(con,'BIM',source,{'fit':'high','evidence_verified':True,'evidence':'找工具','intent':'找工具','uncertainty':''})
                self.assertEqual(con.execute('SELECT status FROM leads').fetchone()[0],'do_not_contact')
                source['author']='用户已注销';source['profile_url']='https://www.xiaohongshu.com/user/profile/deleted1'
                self.assertIsNone(discovery.save_candidate(con,'BIM',source,{'fit':'potential','evidence_verified':True}))
            worker.send.assert_not_called();worker.prepare.assert_not_called()

    def test_budget_and_cache(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(workflow_ai.client,'ROOT',Path(folder)):
            (Path(folder)/'data').mkdir();(Path(folder)/'deepseek.local.txt').write_text('DEEPSEEK_API_KEY=offline-fixture\n',encoding='utf-8')
            response={'usage':{'total_tokens':12,'prompt_tokens':10,'completion_tokens':2},'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}
            with patch.object(workflow_ai.client,'request',return_value=response) as request:
                for _ in range(2):self.assertTrue(workflow_ai.complete('test',{'a':1},'test',lambda x:x)['ok'])
                self.assertEqual(request.call_count,1)
                con=workflow_ai._db()
                with con:con.execute('INSERT INTO calls(session,label,reserved,status) VALUES(?,?,?,?)',(workflow_ai.client.SESSION,'uncertain',4.99,'reserved'))
                con.close()
                with self.assertRaisesRegex(RuntimeError,'5元'):workflow_ai.complete('test',{'a':2},'test2',lambda x:x)
                self.assertEqual(request.call_count,1)

if __name__=='__main__':unittest.main()
