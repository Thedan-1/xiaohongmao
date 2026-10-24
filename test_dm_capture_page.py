import threading,unittest
from types import SimpleNamespace
from unittest.mock import Mock,MagicMock,patch
import adapter,studio,app
from contextlib import nullcontext

class DmCapturePageTests(unittest.TestCase):
    def test_account_refresh_does_not_replace_visible_login_context(self):
        worker=Mock();worker.visible=True;worker.page.is_closed.return_value=False
        worker.browser_operation.side_effect=lambda *a:nullcontext()
        with patch.object(app,'STATE',{'login':'required','message':'请完成登录'}):
            with self.assertRaisesRegex(RuntimeError,'请完成登录'):studio.account(app,worker,{})
        worker.check.assert_called_once();worker.background.assert_not_called();worker.context.close.assert_not_called()
    def test_popup_is_selected_before_conversation_progress_is_captured(self):
        source=Mock();chat=Mock();source.context.pages=[]
        chat.url='https://www.xiaohongshu.com/chat?openUid=target'
        chat.locator.return_value.inner_text.return_value='作者'
        popup=MagicMock();popup.__enter__.return_value=SimpleNamespace(value=chat)
        source.context.expect_page.return_value=popup
        active=[None];stages=[]
        with patch.object(adapter,'checkpoint'),patch.object(adapter,'paced'):
            result=adapter.prepare_chat(source,{'profile_url':'https://www.xiaohongshu.com/user/profile/target','name':'作者'},threading.Event(),focus=False,on_page=lambda p:active.__setitem__(0,p),progress=lambda stage:stages.append((stage,active[0])))
        self.assertIs(result,chat)
        self.assertIs(next(p for label,p in stages if label=='目标主页已打开'),source)
        self.assertIs(next(p for label,p in stages if label=='核对会话对象'),chat)

if __name__=='__main__':unittest.main()
