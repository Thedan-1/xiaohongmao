"""Replay comment/reply DOM locally. All Xiaohongshu requests are intercepted."""
import sys
import threading
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'.runtime'))
from playwright.sync_api import sync_playwright
from edge_path import find_edge
import comment_flow

HTML='''<html><head><meta charset="utf-8"></head><body><a href="/user/profile/me">我</a><a href="/user/profile/me" style="display:none">我</a><h1 id="detail-title">LOL混剪</h1>
<div class="interaction-container"><div class="note-scroller"><div class="comments-container"><div class="no-more">THE END</div>
<div class="parent-comment"><div id="comment-seller" class="comment-item"><div class="author"><a class="name" href="/user/profile/seller">卖家</a></div><div class="content"><span class="note-text">出售LOL素材20元</span></div><button class="reply" onclick="document.querySelector('#content-textarea').style.display='block';replying=true;document.querySelector('#reply-preview').style.display='block';document.querySelector('#label').textContent='回复 卖家'">回复</button></div><div id="replies"></div></div>
</div></div></div><div class="engage-bar"><div class="reply-content" id="reply-preview" style="display:none"><span id="label" class="reply">评论</span><div class="content">出售LOL素材20元</div></div><div><button onclick="document.querySelector('#content-textarea').style.display='block'">说点什么...</button><p id="content-textarea" contenteditable="true" style="display:none"></p></div><button class="btn submit" onclick="post()">发送</button></div>
<script>let replying=false;function render(x){let e=document.createElement('div');e.id=x.id;e.className='comment-item';e.innerHTML='<div class="author"><a class="name" href="/user/profile/me">我自己</a></div><div class="content"><span class="note-text">'+x.text+'</span></div>';document.querySelector(x.reply?'#replies':'.comments-container').append(e)}
function post(){let x={id:'comment-own'+Date.now(),text:document.querySelector('#content-textarea').innerText,reply:replying};localStorage.setItem('sent',JSON.stringify(x));render(x);document.querySelector('#content-textarea').innerText=''}
if(localStorage.sent)render(JSON.parse(localStorage.sent));</script></body></html>'''

class CommentUITests(unittest.TestCase):
    def test_preview_stops_before_submit_and_clears_only_its_draft(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=find_edge(),headless=True)
            for kind in ('note','reply'):
                page=browser.new_page();page.route('**/*',lambda route:route.fulfill(content_type='text/html',body=HTML))
                target={'id':902,'kind':kind,'note_key':'note1','note_url':'https://www.xiaohongshu.com/explore/note1','comment_id':'comment-seller' if kind=='reply' else '', 'parent_id':'','author':'卖家','profile_url':'https://www.xiaohongshu.com/user/profile/seller','source_text':'出售LOL素材20元','message':'1'}
                submitted=[False]
                result=comment_flow.post_one(page,target,threading.Event(),submitted,lambda *x:None,preview_only=True)
                self.assertFalse(submitted[0]);self.assertTrue(result['draft_cleared'])
                self.assertIsNone(page.evaluate('localStorage.getItem("sent")'))
                if kind=='reply':
                    with self.assertRaisesRegex(ValueError,'作者或原评论与目标不一致'):
                        comment_flow.post_one(page,{**target,'author':'另一个人'},threading.Event(),[False],lambda *x:None,preview_only=True)
                    self.assertIsNone(page.evaluate('localStorage.getItem("sent")'))
                page.context.close()
            browser.close()

    def test_comment_and_reply_confirmed_on_page_with_screenshot(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=find_edge(),headless=True)
            for kind in ('note','reply'):
                page=browser.new_page()
                page.route('**/*',lambda route:route.fulfill(content_type='text/html',body=HTML))
                target={'id':900 if kind=='note' else 901,'kind':kind,'note_key':'note1','note_url':'https://www.xiaohongshu.com/explore/note1','comment_id':'comment-seller' if kind=='reply' else '', 'parent_id':'','author':'卖家','profile_url':'https://www.xiaohongshu.com/user/profile/seller','source_text':'出售LOL素材20元','message':'5' if kind=='note' else '1'}
                submitted=[False]
                result=comment_flow.post_one(page,target,threading.Event(),submitted,lambda *x:None)
                self.assertTrue(submitted[0]);self.assertTrue(result['confirmed_on_page']);self.assertTrue(result['screenshot_saved'])
                self.assertFalse(result['verified_after_reload'])
                page.context.close()
            browser.close()

if __name__=='__main__':unittest.main()
