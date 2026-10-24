"""Human chat approval uses the same frozen draft and send ledger as the button.
All outgoing actions are intercepted. No real account or AI service is called.
"""
import json
import threading
from contextlib import nullcontext
import unittest
from unittest.mock import Mock,patch
import app,studio
import test_studio

class ChatAuthorizationTests(unittest.TestCase):
    def setUp(self):
        test_studio.StudioTests.setUp(self)
        self.stack.enter_context(patch.object(app,'STOP',threading.Event()))
    tearDown=test_studio.StudioTests.tearDown

    def preview(self,channel='dm'):
        source={'profile_url':'https://www.xiaohongshu.com/user/profile/FixtureTarget','author':'测试对象','note_url':'https://www.xiaohongshu.com/explore/FixtureNote','title':'fixture','key':'FixtureNote','url':'https://www.xiaohongshu.com/explore/FixtureNote','body':'fixture'}
        with app.connect() as con:
            return con.execute("INSERT INTO studio_drafts(project_id,account_id,channel,items,status) VALUES(1,?,?,?,'preview')",(app.STATE['account']['profile_url'],channel,studio.dump([{'source':source,'message':'离线测试，不真实发送','status':'ready'}]))).lastrowid

    def human(self,text):
        with app.connect() as con:
            studio.message(con,1,'user',text)
            return con.execute('SELECT MAX(id) FROM studio_messages').fetchone()[0]

    def worker(self):
        w=Mock();w.browser_operation.side_effect=lambda *a:nullcontext();return w

    def test_human_approval_sends_current_dm_preview_without_manual_button(self):
        did=self.preview();mid=self.human('确认发送这批私信')
        with patch.object(studio.ai,'complete',return_value={'kind':'answer','reply':'请点击界面确认'}),patch.object(studio,'account'),patch.object(studio,'capture'),patch('adapter.send_direct_message',return_value='sent') as send:
            studio.chat(app,self.worker(),{'project_id':1,'text':'确认发送这批私信','after_message_id':mid})
        send.assert_called_once()
        with app.connect() as con:self.assertEqual(con.execute('SELECT status FROM studio_drafts WHERE id=?',(did,)).fetchone()[0],'complete')

    def test_question_and_negation_never_send(self):
        self.preview()
        for text in ['能不能发送这批私信？','先不要发送','我没有允许发送','如果我说确认发送会怎么样','他说“确认发送这批私信”','为什么不能直接发']:
            with self.subTest(text=text):
                mid=self.human(text)
                with patch.object(studio.ai,'complete',return_value={'kind':'answer','reply':'说明'}),patch('adapter.send_direct_message') as send:
                    studio.chat(app,self.worker(),{'project_id':1,'text':text,'after_message_id':mid})
                send.assert_not_called()

    def test_approval_cannot_choose_other_project(self):
        other=studio.request(app,{'action':'create'})['project_id'];did=self.preview();mid=self.human('确认发送这批私信')
        with patch.object(studio.ai,'complete',return_value={'kind':'answer','reply':'说明'}),patch('adapter.send_direct_message') as send:
            studio.chat(app,self.worker(),{'project_id':other,'text':'确认发送这批私信','after_message_id':mid})
        send.assert_not_called()

    def test_explicit_comment_approval_uses_same_comment_executor(self):
        self.preview('note');mid=self.human('允许发送刚才预览的评论')
        def sent(worker,payload,*args):
            with app.connect() as con:con.execute("UPDATE comment_targets SET status='sent',result='offline fixture proof' WHERE run_id=?",(payload['run_id'],))
        with patch.object(studio,'account'),patch.object(studio,'capture'),patch.object(studio.ai,'budget',return_value={'reserved_or_peak_cost':0}),patch('comment_flow.send',side_effect=sent) as send:
            studio.chat(app,self.worker(),{'project_id':1,'text':'允许发送刚才预览的评论','after_message_id':mid})
        send.assert_called_once()

    def test_replayed_approval_does_not_send_new_preview(self):
        self.preview();mid=self.human('确认发送这批私信')
        payload={'project_id':1,'text':'确认发送这批私信','after_message_id':mid}
        with patch.object(studio,'account'),patch.object(studio,'capture'),patch('adapter.send_direct_message',return_value='sent') as send:
            studio.chat(app,self.worker(),payload)
            self.preview();studio.chat(app,self.worker(),dict(payload))
        send.assert_called_once()

    def test_pause_or_account_change_blocks_send(self):
        self.preview();text='确认发送这批私信';mid=self.human(text)
        app.STOP.set()
        with patch('adapter.send_direct_message') as send,self.assertRaisesRegex(RuntimeError,'暂停'):
            studio.chat(app,self.worker(),{'project_id':1,'text':text,'after_message_id':mid})
        send.assert_not_called();app.STOP.clear()
        with patch.object(studio,'account',side_effect=lambda *a:app.STATE.update(account={'profile_url':'other'})),patch('adapter.send_direct_message') as send,self.assertRaisesRegex(ValueError,'账号'):
            studio.chat(app,self.worker(),{'project_id':1,'text':text,'after_message_id':mid})
        send.assert_not_called()

    def test_mutated_draft_cannot_use_prior_authorization(self):
        did=self.preview();text='确认发送这批私信';mid=self.human(text)
        with app.connect() as con:
            consent,_=studio.chat_consent.authorize(con,1,mid,text,studio.now())
            con.execute("UPDATE studio_drafts SET items='[]' WHERE id=?",(did,))
        with patch.object(studio,'account'),patch('adapter.send_direct_message') as send,self.assertRaisesRegex(ValueError,'已变化'):
            studio.execute(app,self.worker(),{'project_id':1,'draft_id':did,'confirmed':True,'authorization_id':consent['authorization_id']})
        send.assert_not_called()

    def test_count_mismatch_ambiguity_and_outdated_approval_do_not_send(self):
        self.preview();self.preview()
        for text in ['确认发送这2条私信','确认发送私信']:
            mid=self.human(text)
            with patch('adapter.send_direct_message') as send:
                studio.chat(app,self.worker(),{'project_id':1,'text':text,'after_message_id':mid})
            send.assert_not_called()
        mid=self.human('确认发送这批私信');self.human('先别发')
        with patch('adapter.send_direct_message') as send:
            studio.chat(app,self.worker(),{'project_id':1,'text':'确认发送这批私信','after_message_id':mid})
        send.assert_not_called()

