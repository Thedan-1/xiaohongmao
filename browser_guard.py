"""Wall-clock limits independent of Playwright's potentially stalled event loop."""
import os
import subprocess
import threading
import time


class BrowserOperationTimeout(RuntimeError):
    pass


class BrowserGuard:
    def __init__(self, pw, stop, seconds, on_abort):
        # Capture this worker's driver process, never discover/kill browsers by name.
        self.process = pw._impl_obj._connection._transport._proc
        self.stop, self.seconds, self.on_abort = stop, seconds, on_abort
        self.done = threading.Event()
        self.reason = None

    def __enter__(self):
        self.deadline = time.monotonic() + self.seconds
        self.thread = threading.Thread(target=self._watch, daemon=True)
        self.thread.start()
        return self

    def _watch(self):
        cancelled_at = None
        while not self.done.wait(.1):
            now = time.monotonic()
            if self.stop.is_set():
                cancelled_at = cancelled_at or now
            if now < self.deadline and (cancelled_at is None or now-cancelled_at < 3):
                continue
            self.reason = ('已暂停；浏览器未响应，已关闭专用窗口。当前发送待核实，不会自动重发。'
                           if cancelled_at else
                           f'浏览器操作超过 {self.seconds:g} 秒，已停止本批次。当前发送待核实，不会自动重发；可重新打开小红书窗口。')
            self.stop.set()
            self.on_abort(self.reason)
            # The driver owns only this app's dedicated Edge, never the user's normal Edge.
            if self.process.returncode is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill','/PID',str(self.process.pid),'/T','/F'],
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW,timeout=10)
                else:
                    self.process.terminate()
            return

    def __exit__(self, kind, value, trace):
        self.done.set()
        self.thread.join(12)
        if self.reason:
            raise BrowserOperationTimeout(self.reason) from value
