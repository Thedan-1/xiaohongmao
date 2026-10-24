"""Locate the user's installed Edge without requiring a browser download."""
import os
from pathlib import Path


def find_edge():
    for variable, default in [('PROGRAMFILES(X86)', r'C:\Program Files (x86)'),
                              ('PROGRAMFILES', r'C:\Program Files'),
                              ('LOCALAPPDATA', '')]:
        base=os.environ.get(variable, default)
        if base:
            candidate=Path(base)/'Microsoft/Edge/Application/msedge.exe'
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError('未找到 Microsoft Edge。请先安装 Edge，再打开本程序。')
