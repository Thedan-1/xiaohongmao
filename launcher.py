"""Double-click entry; reuse an existing workbench without resetting its profile."""
import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from edge_path import find_edge

ROOT = Path(__file__).resolve().parent


def running():
    try:
        info = json.loads((ROOT / 'data/runtime.json').read_text(encoding='utf-8'))
        if not info['url'].startswith('http://127.0.0.1:'):
            return None
        req = urllib.request.Request(info['url']+'/api/state',headers={'X-App-Token':info['token']})
        with urllib.request.urlopen(req, timeout=2) as r:
            if 'state' in json.load(r):
                return info
    except Exception:
        return None


def main():
    try:
        edge=find_edge()
    except RuntimeError as exc:
        ctypes.windll.user32.MessageBoxW(None,str(exc),'小红帽',16)
        return
    info = running()
    if not info:
        log = (ROOT/'server.log').open('ab')
        err = (ROOT/'server-error.log').open('ab')
        subprocess.Popen([sys.executable,'-X','utf8','-u',str(ROOT/'app.py'),'--no-browser'],cwd=ROOT,
                         stdout=log,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(45):
            time.sleep(.5)
            info = running()
            if info: break
    if not info:
        ctypes.windll.user32.MessageBoxW(None,'启动失败，请查看项目目录中的 server-error.log。','小红帽',16)
        return
    subprocess.Popen([edge,'--app='+info['url']])


if __name__ == '__main__': main()
