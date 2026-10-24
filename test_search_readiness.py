"""Intercepted search: await data and pace collection in integer milliseconds."""
import tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import app,adapter
from playwright.sync_api import sync_playwright
from edge_path import find_edge

class RecordedStop(threading.Event):
    def __init__(self):super().__init__();self.waits=[]
    def wait(self,seconds=None):self.waits.append(seconds);return self.is_set()

class SearchReadinessTests(unittest.TestCase):
    def test_default_search_keeps_readiness_and_short_millisecond_pacing(self):
        html='''<meta charset="utf-8"><input id="search-input-in-feeds"><main id="results"></main><script>
        document.querySelector('input').onkeydown=e=>{if(e.key==='Enter'){
          history.pushState({},'', '/search_result?keyword='+encodeURIComponent(e.target.value));
          setTimeout(()=>document.querySelector('main').innerHTML='<div><a href="/explore/n1">测试笔记</a><a href="/user/profile/u1">测试作者</a></div>',180);
        }};</script>'''
        with tempfile.TemporaryDirectory() as folder,patch.object(adapter,'DATA',Path(folder)),sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=find_edge(),headless=True)
            try:
                page=browser.new_page();page.route('**/*',lambda r:r.fulfill(content_type='text/html',body=html))
                page.goto('https://www.xiaohongshu.com/explore')
                stop=RecordedStop();start=time.perf_counter()
                rows=list(adapter.collect_search(page,'测试主题',1,stop,filter_rules=False))
                elapsed=time.perf_counter()-start
                self.assertEqual(len(rows),1);self.assertEqual(rows[0]['note_title'],'测试笔记')
                self.assertEqual(len(stop.waits),2)
                for wait in stop.waits:
                    self.assertGreaterEqual(wait,.1);self.assertLessEqual(wait,.9)
                    self.assertAlmostEqual(wait*1000,round(wait*1000),places=8)
                self.assertLess(elapsed,2,'ready local fixture should not wait seconds per action')
                print('Ready fixture retained; requested pacing (ms):',[round(x*1000) for x in stop.waits])
            finally:browser.close()

    def test_integer_millisecond_endpoints_and_fractional_values(self):
        stop=RecordedStop()
        with patch.object(adapter.random,'randint',side_effect=[100,617,900]) as sample:
            self.assertEqual([adapter.collection_pause(stop) for _ in range(3)],[100,617,900])
        self.assertEqual(stop.waits,[.1,.617,.9])
        self.assertTrue(all(c.args==(100,900) for c in sample.call_args_list))

    def test_pause_interrupts_delay_and_prevents_note_navigation(self):
        import note_collector
        stop=threading.Event();timer=threading.Timer(.03,stop.set);timer.start()
        try:
            start=time.perf_counter()
            with patch.object(adapter.random,'randint',return_value=900),self.assertRaisesRegex(RuntimeError,'暂停'):adapter.collection_pause(stop)
            self.assertLess(time.perf_counter()-start,.5)
        finally:timer.cancel();timer.join()
        page=Mock()
        with self.assertRaisesRegex(RuntimeError,'暂停'):
            note_collector.collect_ready(page,{'note_url':'https://www.xiaohongshu.com/explore/n1'},stop)
        page.goto.assert_not_called()

if __name__=='__main__':unittest.main()
