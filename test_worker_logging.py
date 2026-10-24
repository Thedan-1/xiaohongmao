"""Closed desktop host pipes must not kill the backend command worker."""
import io
import queue
import sqlite3
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import app


class FinishedFixture(BaseException):
    pass


class FiniteQueue(queue.Queue):
    def get(self, *args, **kwargs):
        if self.empty():
            raise FinishedFixture()
        return super().get(*args, **kwargs)


class BrokenPipe:
    def write(self, text):
        raise BrokenPipeError('desktop host pipe closed')

    def flush(self):
        raise BrokenPipeError('desktop host pipe closed')


class WorkerLoggingTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(app, 'DATA', self.root))
        self.stack.enter_context(patch.object(app, 'DB', self.root / 'work.db'))
        self.stack.enter_context(patch.object(app, 'STATE', {'task': 'idle'}))
        self.stack.enter_context(patch.object(app, 'SERVER', None))
        self.stack.enter_context(patch.object(app, 'STOP', threading.Event()))
        app.init_db()

    def exercise_worker(self):
        commands = FiniteQueue()
        for name in ('check', 'snapshot', 'shutdown'):
            commands.put((name, {}))
        worker = app.BrowserWorker()
        worker.check = lambda: app.event('fixture: ready')
        worker.snapshot = Mock()
        worker.context = Mock()
        worker.pw = Mock()
        with patch.object(app, 'COMMANDS', commands):
            with self.assertRaises(FinishedFixture):
                worker.run()
        worker.snapshot.assert_called_once()
        worker.context.close.assert_called_once()
        worker.pw.stop.assert_called_once()
        self.assertEqual(commands.unfinished_tasks, 0)
        self.assertEqual(app.STATE['task'], 'idle')

    def test_closed_stdout_keeps_following_commands_and_shutdown_working(self):
        stream = io.StringIO()
        stream.close()
        with patch.object(app.sys, 'stdout', stream):
            self.exercise_worker()
        with app.connect() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM events WHERE message=?', ('fixture: ready',)).fetchone()[0], 1)

    def test_broken_stdout_and_stderr_keep_worker_alive_after_action_error(self):
        commands = FiniteQueue()
        for name in ('check', 'snapshot', 'shutdown'):
            commands.put((name, {}))
        worker = app.BrowserWorker()
        worker.check = Mock(side_effect=RuntimeError('fixture command failure'))
        worker.snapshot = Mock()
        worker.context = Mock()
        worker.pw = Mock()
        with patch.object(app, 'COMMANDS', commands), patch.object(app.sys, 'stdout', BrokenPipe()), patch.object(app.sys, 'stderr', BrokenPipe()):
            with self.assertRaises(FinishedFixture):
                worker.run()
        worker.snapshot.assert_called_once()
        worker.context.close.assert_called_once()
        self.assertEqual(commands.unfinished_tasks, 0)
        with app.connect() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM events WHERE message=?', ('fixture command failure',)).fetchone()[0], 1)
        diagnostic = (self.root / 'backend-diagnostics.log').read_text(encoding='utf-8')
        self.assertIn('Traceback (most recent call last)', diagnostic)
        self.assertIn('fixture command failure', diagnostic)

    def test_absent_streams_with_unwritable_fallback_and_event_storage_do_not_kill_worker(self):
        # Directory at the file path deterministically simulates a failed log
        # file open on Windows without changing real filesystem permissions.
        (self.root / 'backend-diagnostics.log').mkdir()
        with patch.object(app.sys, 'stdout', None), patch.object(app.sys, 'stderr', None), patch.object(app, 'connect', side_effect=sqlite3.OperationalError('fixture disk full')):
            self.exercise_worker()


if __name__ == '__main__':
    unittest.main()
