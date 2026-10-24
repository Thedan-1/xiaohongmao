"""Installed data-home tests: all writes use temporary directories, no network."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import app_paths


class AppPathsTests(unittest.TestCase):
    def test_development_and_patched_root_keep_existing_layout(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XIAOHONGMAO_DATA_HOME': ''}):
            root = Path(directory) / '代码目录'
            self.assertEqual(app_paths.data_home(root), root)
            self.assertEqual(app_paths.data_dir(root), root / 'data')
            self.assertEqual(app_paths.config_file(root), root / 'deepseek.local.txt')
            self.assertFalse(root.exists(), 'Path lookup must not create or migrate files')

    def test_configured_home_supports_spaces_and_chinese(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'Program Files' / '小红帽'
            home = Path(directory) / '用户数据 空间' / '小红帽'
            with patch.dict(os.environ, {'XIAOHONGMAO_DATA_HOME': str(home)}):
                self.assertEqual(app_paths.data_dir(root), home / 'data')
                self.assertEqual(app_paths.config_file(root), home / 'deepseek.local.txt')
                self.assertFalse(root.exists())
                self.assertFalse(home.exists())

    def test_relative_environment_path_is_rejected_before_writing(self):
        with patch.dict(os.environ, {'XIAOHONGMAO_DATA_HOME': 'relative-data'}):
            with self.assertRaisesRegex(ValueError, '完整目录路径'):
                app_paths.data_dir()

    def test_backend_budget_and_receipts_share_installed_home(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / '个人 数据' / '小红帽'
            env = dict(os.environ, XIAOHONGMAO_DATA_HOME=str(home), PYTHONDONTWRITEBYTECODE='1')
            # A separate import checks startup behavior without replacing globals in
            # another test or reading the developer's credential/database/profile.
            code = r'''
import json, os
from pathlib import Path
from unittest.mock import Mock, patch
import app_paths, app, adapter, studio, comment_flow, workflow_ai
home=Path(os.environ['XIAOHONGMAO_DATA_HOME'])
assert app.DATA==home/'data'
assert adapter.DATA==app.DATA
assert app.DB==app.DATA/'workbench.sqlite3'
assert app.ROOT!=home
assert (app.ROOT/'ui.html').is_file()
assert not app_paths.config_file().exists()
app_paths.config_file().write_text('DEEPSEEK_API_KEY=TEST_ONLY_NOT_A_REAL_KEY',encoding='utf-8')
assert workflow_ai.client.credential()=='TEST_ONLY_NOT_A_REAL_KEY'
app.init_db()
with patch.object(workflow_ai.client,'request',side_effect=AssertionError('Network forbidden')):
    workflow_ai.budget()
assert workflow_ai.client.budget_file()==app.DATA/'ai-budget.sqlite3'
with comment_flow.CommentSubmissionTrace(Mock(),{'id':73,'note_key':'fixture'}):
    pass
assert (app.DATA/'comment-submit-73.json').is_file()
(app.DATA/'studio-frame-1.json').write_text(json.dumps({'project_id':1,'label':'temporary proof'}),encoding='utf-8')
with app.connect() as con:
    assert studio.state(con,1)['frame']['label']=='temporary proof'
assert app.DB.is_file()
print('PASS installed paths')
'''
            result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', code],
                                    cwd=Path(__file__).resolve().parent, env=env,
                                    text=True, encoding='utf-8', capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('PASS installed paths', result.stdout)
            self.assertTrue((home / 'data/workbench.sqlite3').is_file())


if __name__ == '__main__':
    unittest.main()
