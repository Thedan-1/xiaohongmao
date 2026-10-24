"""Separate installed read-only resources from writable per-user application data.

The desktop host sets XIAOHONGMAO_DATA_HOME to a user's application directory.
Development and legacy portable launches retain their existing local layout.
No files are moved or credentials copied by these helpers.
"""
import os
from pathlib import Path

ENV_DATA_HOME = 'XIAOHONGMAO_DATA_HOME'


def resource_root():
    return Path(__file__).resolve().parent


def data_home(root=None):
    configured = os.environ.get(ENV_DATA_HOME, '').strip()
    if configured:
        home = Path(configured).expanduser()
        if not home.is_absolute():
            raise ValueError('XIAOHONGMAO_DATA_HOME 必须是完整目录路径')
        return home.resolve()
    return Path(root) if root is not None else resource_root()


def data_dir(root=None):
    return data_home(root) / 'data'


def config_file(root=None):
    return data_home(root) / 'deepseek.local.txt'
