"""Exercise a stalled browser transport through the real send batch; no network sends."""
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app
import adapter


class SendRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = app.DB
        app.DB = Path(self.tmp.name) / 'test.sqlite3'
        app.init_db()
        app.STOP.clear()
        with app.connect() as con:
            con.execute("INSERT INTO leads(id,profile_url,name) VALUES(1,'https://www.xiaohongshu.com/user/profile/test','Test')")

    def tearDown(self):
        app.DB = self.db
        app.STOP.clear()
        self.tmp.cleanup()

    def test_stalled_browser_exits_and_never_retries(self):
        # A real child stands in for the unresponsive Playwright driver.
        driver = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], creationflags=subprocess.CREATE_NO_WINDOW)
        worker = app.BrowserWorker()
        worker.page = SimpleNamespace(is_closed=lambda: False,bring_to_front=lambda:None)
        worker.context = object()
        worker.pw = SimpleNamespace(_impl_obj=SimpleNamespace(_connection=SimpleNamespace(_transport=SimpleNamespace(_proc=driver))))
        calls, failures = [], []
        def blocked(*args, **kwargs):
            calls.append(1)
            driver.wait()

            raise RuntimeError('Transport disconnected')
        def run():
            try: worker.send({'ids':[1], 'message':'not actually sent'})
            except Exception as exc: failures.append(str(exc))
        try:
            with patch('importlib.reload', lambda module: module), patch.object(adapter,'send_direct_message',blocked), patch.object(app,'SEND_DEADLINE_SECONDS',0.25,create=True):
                thread=threading.Thread(target=run,daemon=True)
                thread.start()
                thread.join(4)
                try:
                    self.assertFalse(thread.is_alive(), 'Send hangs forever when browser transport stops responding')
                    self.assertEqual(calls,[1])
                    self.assertTrue(failures)
                    with app.connect() as con:
                        self.assertEqual(con.execute('SELECT status FROM contacts').fetchone()[0],'needs_review')
                finally:
                    if driver.poll() is None:driver.kill()
                    thread.join(3)
        finally:
            if driver.poll() is None:driver.kill()
            driver.wait()

    def test_last_recipient_finishes_without_cooldown_or_resend(self):
        from contextlib import nullcontext
        worker=app.BrowserWorker()
        worker.page=SimpleNamespace(is_closed=lambda:False,bring_to_front=lambda:None)
        worker.browser_operation=lambda seconds:nullcontext()
        with patch('importlib.reload',lambda module:module), patch.object(adapter,'send_direct_message',return_value='sent') as send, patch.object(app.STOP,'wait',return_value=False) as wait:
            worker.send({'ids':[1],'message':'fixture'})
            worker.send({'ids':[1],'message':'fixture'})
            self.assertEqual(send.call_count,1)
            wait.assert_not_called()

    def test_real_playwright_stall_is_interrupted(self):
        from playwright.sync_api import sync_playwright
        from edge_path import find_edge
        from browser_guard import BrowserGuard, BrowserOperationTimeout
        pw=sync_playwright().start()
        try:
            browser=pw.chromium.launch(executable_path=find_edge(),headless=True)
            page=browser.new_page()
            started=time.monotonic()
            with self.assertRaises(BrowserOperationTimeout):
                with BrowserGuard(pw,app.STOP,1,lambda reason:None):
                    # Evaluate has no native timeout, like count/evaluate RPCs on a stalled tab.
                    page.evaluate('() => new Promise(() => {})')
            self.assertLess(time.monotonic()-started,8)
        finally:
            pw.stop()

    def test_crashed_source_tab_is_replaced_before_send(self):
        from unittest.mock import Mock
        worker=app.BrowserWorker()
        worker.page=Mock()
        worker.page.bring_to_front.side_effect=RuntimeError('Page.bring_to_front: Target crashed')
        replacement=Mock()
        worker.context=Mock()
        worker.context.new_page.return_value=replacement
        worker.recover_source_page()
        self.assertIs(worker.page,replacement)
        replacement.goto.assert_called_once()

    def test_only_confirmed_unsent_record_can_be_retried(self):
        from contextlib import nullcontext
        worker=app.BrowserWorker()
        worker.page=SimpleNamespace(is_closed=lambda:False,bring_to_front=lambda:None)
        worker.browser_operation=lambda seconds:nullcontext()
        with app.connect() as con:
            con.execute("INSERT INTO contacts(lead_id,channel,message,status) VALUES(1,'dm','old','needs_review')")
        with patch('importlib.reload',lambda module:module), patch.object(adapter,'send_direct_message',return_value='sent') as send:
            worker.send({'ids':[1],'message':'fixture'})
            send.assert_not_called()
            with app.connect() as con:con.execute("UPDATE contacts SET status='not_sent' WHERE lead_id=1")
            worker.send({'ids':[1],'message':'fixture'})
            self.assertEqual(send.call_count,1)
        with app.connect() as con:
            rows=list(con.execute('SELECT status,message FROM contacts'))
            self.assertEqual([(r['status'],r['message']) for r in rows],[('sent','fixture')])


if __name__=='__main__':unittest.main()
