import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent/'.runtime'))
from playwright.sync_api import sync_playwright
from edge_path import find_edge
from note_collector import collect_ready


class ReadyTests(unittest.TestCase):
    def test_empty_or_full_comment_sample_does_not_scroll(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=find_edge(),headless=True)
            for count in (0,19,21):
                comments='这是一片荒地点击评论' if count==0 else f'<div class="total">共 {count} 条评论</div>'+''.join(f'<div class="comment-item" id="comment-{i}"><div class="author"><a class="name" href="/user/profile/u{i}">客户</a></div><div class="content">需要建模</div></div>' for i in range(count))
                html='<div class="interaction-container"><div class="author-container"><a class="name" href="/user/profile/author">作者</a></div><div id="detail-desc">BIM正文无标题</div><div class="note-scroller"><div class="comments-container">'+comments+'</div></div></div>'
                if count==0:html=html.replace('class="comments-container"','class="no-comments-text"')
                page=browser.new_page();page.route('**/*',lambda route:route.fulfill(content_type='text/html',body=html))
                with patch.object(page.mouse,'wheel',side_effect=AssertionError('已经足够或为空，不该滚动')):
                    result=collect_ready(page,{'note_url':'https://www.xiaohongshu.com/explore/n1','note_title':'BIM'},threading.Event())
                self.assertEqual(len(result['comments']),min(count,20));self.assertEqual(result['scrolls'],0)
                self.assertEqual(result['title'],'BIM');page.close()
                if count==0:self.assertLess(result['timings']['comments'],2,'空评论区不应等满6秒')
            browser.close()


if __name__=='__main__':unittest.main()
