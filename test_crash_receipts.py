"""Real child-process crashes and SQLite persistence; no network/browser sends."""
import subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import app,project_store

CHILD=r'''
import os,sys
from pathlib import Path
import app,project_store
app.DB=Path(sys.argv[1]);phase=sys.argv[2];app.init_db()
x={'profile_url':'https://www.xiaohongshu.com/user/profile/u1'}
if phase=='before_claim':os._exit(0)
with app.connect() as con:
    project_store.claim(con,1,'dm',x,'A','hello')
if phase=='after_claim':os._exit(0)
Path(sys.argv[3]).write_text('simulated external side effect',encoding='utf-8')
if phase=='after_external':os._exit(0)
with app.connect() as con:project_store.finish(con,1,'dm',x,'sent')
os._exit(0)
'''

class CrashReceiptTests(unittest.TestCase):
    def test_process_crash_windows_do_not_turn_uncertain_sends_into_retryable_work(self):
        for phase in ('before_claim','after_claim','after_external','after_receipt'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as folder:
                db=Path(folder)/'db.sqlite3';marker=Path(folder)/'external.flag'
                subprocess.run([sys.executable,'-X','utf8','-c',CHILD,str(db),phase,str(marker)],cwd=Path(__file__).resolve().parent,timeout=15,check=True)
                with patch.object(app,'DB',db):
                    app.init_db()
                    with app.connect() as con:
                        project_store.recover(con)
                        status=project_store.status(con,1,'dm',{'profile_url':'https://www.xiaohongshu.com/user/profile/u1'})
                        claimed=project_store.claim(con,1,'dm',{'profile_url':'https://www.xiaohongshu.com/user/profile/u1'},'B','second')
                    if phase=='before_claim':self.assertTrue(claimed);self.assertFalse(marker.exists())
                    else:self.assertFalse(claimed);self.assertIn(status,('needs_review','sent'))
                    if phase in ('after_external','after_receipt'):self.assertTrue(marker.exists())

if __name__=='__main__':unittest.main()
