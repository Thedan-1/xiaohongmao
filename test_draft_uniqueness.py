import json,unittest
from unittest.mock import Mock,patch
import app,studio,project_store as store
from test_studio import StudioTests

class DraftUniquenessTests(unittest.TestCase):
    setUp=StudioTests.setUp
    tearDown=StudioTests.tearDown
    def add(self,con,keys,status='needs_review',channel='note',pid=1):
        items=[{'source':{'key':k,'note_key':k,'comment_id':'c1','profile_url':'https://www.xiaohongshu.com/user/profile/'+k,'author':k,'title':'same title'},'message':'hello','status':'ready'} for k in keys]
        return con.execute('INSERT INTO studio_drafts(project_id,account_id,channel,items,status) VALUES(?,?,?,?,?)',(pid,'accountA',channel,json.dumps(items),status)).lastrowid
    def test_nested_retry_batches_show_ten_unique_final_results_without_changing_audit(self):
        with app.connect() as con:
            for count in (10,9,8,6,3):self.add(con,[str(x) for x in range(count)])
            for i in range(10):
                source={'key':str(i)};store.claim(con,1,'note',source,'accountB','hello')
                store.finish(con,1,'note',source,'skipped' if i==5 else 'sent','受限跳过' if i==5 else '{"screenshot_saved":true}')
            drafts=store.visible_drafts(con,1);items=[x for d in drafts for x in d['items']]
            self.assertEqual(len(items),10);self.assertEqual(len({x['source']['key'] for x in items}),10)
            self.assertEqual(sum(x['status']=='sent' for x in items),9)
            self.assertTrue(all(d['status']=='complete' for d in drafts))
            self.assertEqual(con.execute('SELECT count(*) FROM studio_drafts').fetchone()[0],5)
            self.assertEqual(json.loads(con.execute('SELECT items FROM studio_drafts ORDER BY id LIMIT 1').fetchone()[0])[0]['status'],'ready')
    def test_existing_preview_blocks_another_draft_until_discarded(self):
        with app.connect() as con:
            did=self.add(con,['a'],'preview');self.assertFalse(store.draftable(con,1,'note',{'key':'a'}))
            con.execute("UPDATE studio_drafts SET status='discarded' WHERE id=?",(did,))
            self.assertTrue(store.draftable(con,1,'note',{'key':'a'}))
    def test_projects_channels_and_reply_parents_are_independent(self):
        with app.connect() as con:
            self.add(con,['a'],'preview')
            self.add(con,['a'],'preview','reply')
            self.assertTrue(store.draftable(con,2,'note',{'key':'a'}))
            self.assertTrue(store.draftable(con,1,'dm',{'profile_url':'https://www.xiaohongshu.com/user/profile/a'}))
            self.assertTrue(store.draftable(con,1,'reply',{'key':'a','comment_id':'c2'}))
            self.assertEqual(len(store.visible_drafts(con,1)),2)
    def test_draft_generation_rejects_processed_target_before_ai_or_insertion(self):
        source={'key':'a','author':'A','title':'title'}
        with app.connect() as con:
            store.claim(con,1,'note',source,'accountA','old');store.finish(con,1,'note',source,'sent','done')
        with patch.object(studio,'state',return_value={'notes':[source],'people':[]}),patch.object(studio.ai,'complete') as ai:
            with self.assertRaisesRegex(ValueError,'不重复生成'):
                studio.draft(app,Mock(),{'project_id':1,'channel':'note','mode':'ai','template':'hello','ids':['a']})
            ai.assert_not_called()
        with app.connect() as con:self.assertEqual(con.execute('SELECT count(*) FROM studio_drafts').fetchone()[0],0)

if __name__=='__main__':unittest.main()
