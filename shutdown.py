"""Request a clean exit from this copy of the workbench."""
import ctypes
import json
import urllib.request
from pathlib import Path
from app_paths import data_dir

try:
    info=json.loads((data_dir()/'runtime.json').read_text(encoding='utf-8'))
    if not info['url'].startswith('http://127.0.0.1:'):
        raise ValueError('Unexpected service address')
    req=urllib.request.Request(info['url']+'/api/command',data=b'{"command":"shutdown"}',
                              headers={'X-App-Token':info['token'],'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=5) as response:
        json.load(response)
except Exception:
    ctypes.windll.user32.MessageBoxW(None,'未找到正在运行的本程序。若仍有专用 Edge 窗口，可以手动关闭。','小红帽',64)
