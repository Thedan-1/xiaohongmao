import json
import tempfile
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch
import app
import discovery


class DiscoverySpeedTests(unittest.TestCase):
    def run_fixture(self, overlap=False):
        second_read = threading.Event()
        calls = []
        raw = lambda n: dict(name='作者'+str(n), profile_url=f'https://www.xiaohongshu.com/user/profile/u{n}', note_url=f'https://www.xiaohongshu.com/explore/n{n}', note_title='LOL混剪教程')
        def search(page, query, *args, **kwargs):
            calls.append(('search', query))
            return iter([raw(n) for n in range(3)])
        def collect(page, source, stop):
            n = source['note_url'][-1]
            if n == '1': second_read.set()
            return dict(title=source['note_title'], body='分享LOL混剪制作教程', author=source['name'], profile_url=source['profile_url'], note_url=source['note_url'], comments=[])
        def intent(topic, items, purpose):
            calls.append(('intent', items[0]['id']))
            if overlap and items[0]['id'] == 'note-n0':
                if not second_read.wait(1):
                    raise AssertionError('读取第二篇一直等第一篇 AI 返回，仍然串行')
            return [dict(id=i['id'],fit='high',evidence_verified=True,evidence=i['text'],intent='分享教程',uncertainty='') for i in items]
        worker = Mock()
        worker.browser_operation.side_effect = lambda *a: nullcontext()
        with tempfile.TemporaryDirectory() as folder, patch.object(app, 'DB', Path(folder)/'test.db'):
            app.init_db()
            with patch.object(discovery.ai, 'plan', return_value={'queries':['LOL混剪','英雄联盟混剪','LOL剪辑教程']}), patch.object(discovery.ai, 'relevance', side_effect=lambda t,items:[dict(id=i['id'],relevant=True,reason='相关') for i in items]), patch.object(discovery.ai, 'intent', side_effect=intent), patch.object(discovery, 'collect_search', side_effect=search), patch.object(discovery, 'collect', side_effect=collect), patch.object(discovery, 'checkpoint'):
                discovery.run_round(worker,{'topic':'LOL混剪'},threading.Event(),app.connect,Mock(),Mock())
            with app.connect() as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM leads').fetchone()[0],3)
                self.assertEqual(con.execute('SELECT COUNT(*) FROM contacts').fetchone()[0],0)
        return calls

    def test_first_results_do_not_wait_for_all_search_queries(self):
        calls = self.run_fixture()
        before_ai = calls[:next(i for i,c in enumerate(calls) if c[0]=='intent')]
        self.assertEqual(len([c for c in before_ai if c[0]=='search']),1,
                         '首批候选等待了所有扩展词搜索')

    def test_read_next_note_while_ai_analyzes_previous(self):
        self.run_fixture(overlap=True)

if __name__ == '__main__': unittest.main()
