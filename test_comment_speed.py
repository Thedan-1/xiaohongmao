import json
import tempfile
import threading
import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from unittest.mock import Mock, patch
import app
import comment_flow as flow


class CommentSpeedTests(unittest.TestCase):
    def exercise(self, cached=False, overlap=False, own=False, failure=False, pause=False):
        second_read = threading.Event()
        stop = threading.Event()
        rows = [dict(name='作者', profile_url='https://www.xiaohongshu.com/user/profile/u',
                     note_url=f'https://www.xiaohongshu.com/explore/n{i}', note_title='LOL混剪') for i in range(2)]
        def note(raw):
            return dict(title=raw['note_title'], body='LOL混剪教程', author=raw['name'],
                        profile_url=raw['profile_url'], note_url=raw['note_url'], comments=[])
        def collect(page, raw, stop):
            if raw == rows[1]: second_read.set()
            return note(raw)
        def match(topic, criteria, capture):
            if failure: raise RuntimeError('模拟 AI 失败')
            if pause: stop.set()
            if overlap and capture['note_url'] == rows[0]['note_url']:
                self.assertTrue(second_read.wait(1), '第二篇读取仍在等待第一篇 AI，串行阻塞')
            return dict(relevant=True, reason='相关', seller_comment_id='')
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            stack.enter_context(patch.object(app, 'DB', Path(folder)/'test.db'))
            app.init_db()
            payload = dict(topic='LOL混剪', criteria='出售素材', count=2)
            if cached:
                with app.connect() as con:
                    report = dict(seconds={}, read=0, comments_read=0, accepted=0, seller_replies=0, failed_reads=0, ai_before=0)
                    con.execute("INSERT INTO comment_runs(id,topic,criteria,report) VALUES(1,?,?,?)", (payload['topic'], payload['criteria'], json.dumps(report)))
                    for i, raw in enumerate(rows):
                        if own:
                            con.execute('INSERT INTO comment_captures(run_id,note_key,raw,capture) VALUES(?,?,?,?)',
                                        (1, f'n{i}', json.dumps(raw), json.dumps(note(raw))))
                        else:
                            con.execute('INSERT INTO discovery_notes(topic,note_key,raw,capture) VALUES(?,?,?,?)',
                                        (payload['topic'], f'n{i}', json.dumps(raw), json.dumps(note(raw))))
                payload['run_id'] = 1
            for obj, attr, kw in [
                (flow.ai, 'budget', dict(return_value={'reserved_or_peak_cost': 0})),
                (flow.ai, 'plan', dict(return_value={'queries': ['LOL混剪']})),
                (flow, 'collect_search', dict(side_effect=lambda *a, **k: iter(rows))),
                (flow, 'screen_notes', dict(side_effect=lambda t, items: [dict(id=i['id'], relevant=True) for i in items])),
                (flow, 'match_note', dict(side_effect=match)),
            ]: stack.enter_context(patch.object(obj, attr, **kw))
            reader = stack.enter_context(patch.object(flow, 'collect', side_effect=collect))
            worker = Mock(); worker.browser_operation.side_effect = lambda *a: nullcontext()
            if failure or pause:
                with self.assertRaisesRegex(RuntimeError, '模拟 AI 失败' if failure else '已暂停'):
                    flow.find(worker, payload, stop, app.connect, Mock(), Mock())
            else: flow.find(worker, payload, stop, app.connect, Mock(), Mock())
            with app.connect() as con:
                result = flow.state(con)
                self.assertEqual(result['report']['accepted'], 0 if failure or pause else 2)
                if failure or pause:
                    self.assertEqual(result['status'], 'failed' if failure else 'paused')
                self.assertEqual(con.execute('SELECT COUNT(*) FROM comment_sends').fetchone()[0], 0)
            if cached:
                self.assertEqual(reader.call_count, 0, '已有正文和评论仍重复打开笔记')
            return result

    def test_read_and_ai_overlap(self): self.exercise(overlap=True)
    def test_resume_reuses_saved_captures(self): self.exercise(cached=True)
    def test_resume_reuses_comment_flow_captures(self): self.exercise(cached=True, own=True)
    def test_ai_error_stops_pipeline_without_sending(self): self.exercise(failure=True)
    def test_pause_does_not_save_pending_candidates(self): self.exercise(pause=True)


if __name__ == '__main__': unittest.main()
