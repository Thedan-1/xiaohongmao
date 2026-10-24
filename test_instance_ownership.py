"""Real isolated server processes, never the user's data/profile/browser."""
import json,os,sqlite3,subprocess,sys,tempfile,time,unittest,urllib.request
from contextlib import closing
from pathlib import Path
ROOT=Path(__file__).resolve().parent

class InstanceOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.assertEqual(self.root.parent,Path(tempfile.gettempdir()).resolve())
        (self.root/'data/edge-profile').mkdir(parents=True)
        (self.root/'data/edge-profile/fixture-login').write_bytes(b'preserve-login')
        (self.root/'deepseek.local.txt').write_text('DEEPSEEK_API_KEY=DUMMY_TEST_KEY',encoding='utf-8')
        self.processes=[];self.infos={}
    def tearDown(self):
        for process in reversed(self.processes):
            if process.poll() is None:
                info=self.infos.get(process.pid)
                if info:
                    try:self.call(info,'/api/command',{'command':'shutdown'})
                    except Exception:pass
                try:process.wait(timeout=8)
                except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=8)
        self.assertEqual(self.root.parent,Path(tempfile.gettempdir()).resolve());self.tmp.cleanup()
    def spawn(self):
        script="import sys;from pathlib import Path;import app,studio,workflow_ai;root=Path("+repr(str(self.root))+");app.DATA=root/'data';app.DB=app.DATA/'workbench.sqlite3';studio.ROOT=root;workflow_ai.client.ROOT=root;sys.argv=['app.py','--no-browser'];app.main()"
        process=subprocess.Popen([sys.executable,'-X','utf8','-c',script],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.processes.append(process);return process
    def call(self,info,path,data=None):
        request=urllib.request.Request(info['url']+path,headers={'X-App-Token':info['token'],'Content-Type':'application/json'},data=None if data is None else json.dumps(data).encode())
        return json.load(urllib.request.urlopen(request,timeout=2))
    def ready(self,process):
        end=time.monotonic()+12
        while time.monotonic()<end:
            if process.poll() is not None:self.fail('Isolated fixture server exited before ready')
            try:
                info=json.loads((self.root/'data/runtime.json').read_text(encoding='utf-8'))
                if info['pid']==process.pid:
                    self.call(info,'/api/state');self.infos[process.pid]=info;return info
            except Exception:pass
            time.sleep(.1)
        self.fail('Isolated fixture server did not become ready')
    def pending(self):
        with closing(sqlite3.connect(self.root/'data/workbench.sqlite3')) as con:
            con.execute("INSERT INTO studio_jobs(project_id,kind,status,payload) VALUES(1,'send','running','{}')")
            con.execute("INSERT INTO studio_receipts(project_id,channel,target_key,account_id,status,message) VALUES(1,'dm','fixture-target','fixture-account','pending','fixture message')")
            con.execute("INSERT INTO studio_messages(project_id,role,body) VALUES(1,'user','preserve-project-message')")
            con.commit()
    def intact(self):
        self.assertEqual((self.root/'data/edge-profile/fixture-login').read_bytes(),b'preserve-login')
        self.assertEqual((self.root/'deepseek.local.txt').read_text(encoding='utf-8'),'DEEPSEEK_API_KEY=DUMMY_TEST_KEY')

    def test_second_start_cannot_recover_live_owner_jobs_or_replace_runtime(self):
        first=self.spawn();info=self.ready(first);self.pending()
        second=self.spawn()
        try:second.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                other=json.loads((self.root/'data/runtime.json').read_text(encoding='utf-8'))
                if other['pid']==second.pid:self.infos[second.pid]=other
            except Exception:pass
        with closing(sqlite3.connect(self.root/'data/workbench.sqlite3')) as con:
            job=con.execute('SELECT status FROM studio_jobs').fetchone()[0]
            receipt=con.execute('SELECT status FROM studio_receipts').fetchone()[0]
        self.assertIsNotNone(second.poll(),f'Duplicate server stayed alive and changed live-owner job={job}, receipt={receipt}')
        self.assertEqual(json.loads((self.root/'data/runtime.json').read_text())['pid'],first.pid)
        self.assertEqual((job,receipt),('running','pending'));self.call(info,'/api/state');self.intact()

    def test_owner_crash_releases_lock_and_restart_recovers_uncertainty(self):
        first=self.spawn();self.ready(first);self.pending()
        first.terminate();first.wait(timeout=8)  # Only this test-owned isolated process.
        restarted=self.spawn();self.ready(restarted)
        with closing(sqlite3.connect(self.root/'data/workbench.sqlite3')) as con:
            self.assertEqual(con.execute('SELECT status FROM studio_jobs').fetchone()[0],'failed')
            self.assertEqual(con.execute('SELECT status FROM studio_receipts').fetchone()[0],'needs_review')
            self.assertEqual(con.execute("SELECT COUNT(*) FROM studio_messages WHERE body='preserve-project-message'").fetchone()[0],1)
            self.assertEqual(con.execute('PRAGMA quick_check').fetchone()[0],'ok')
        self.intact()

if __name__=='__main__':unittest.main()
