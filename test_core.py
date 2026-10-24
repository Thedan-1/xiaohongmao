import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
import app
from adapter import canonical_profile, classify


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = app.DB
        app.DB = Path(self.tmp.name)/'test.sqlite3'
        app.init_db()
        self.server = app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        app.DB = self.original
        self.tmp.cleanup()

    def test_api_auth_and_origin(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.url+'/api/state')
        self.assertEqual(ctx.exception.code,403)
        req = urllib.request.Request(self.url+'/api/settings',data=b'{"message":"hello"}',headers={'X-App-Token':app.TOKEN,'Origin':'https://evil.invalid','Content-Type':'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code,403)
        self.assertNotEqual(app.settings()['message'],'hello')
        req = urllib.request.Request(self.url+'/api/state',headers={'X-App-Token':app.TOKEN})
        with urllib.request.urlopen(req) as r:
            self.assertEqual(json.load(r)['total'],0)

    def test_deduplication_and_send_uncertainty(self):
        profile=canonical_profile('https://www.xiaohongshu.com/user/profile/abc?source=search')
        with app.connect() as con:
            for _ in range(2):
                con.execute('INSERT OR IGNORE INTO leads(profile_url,name) VALUES(?,?)',(profile,'BIM 工作室'))
            self.assertEqual(con.execute('SELECT COUNT(*) FROM leads').fetchone()[0],1)
            con.execute('INSERT INTO contacts(lead_id,channel,message,status) VALUES(1,?,?,?)',('dm','test','needs_review'))
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute('INSERT INTO contacts(lead_id,channel,message,status) VALUES(1,?,?,?)',('dm','test','pending'))

    def test_filter_and_url_validation(self):
        self.assertEqual(classify('手工接单 美食工作室','小张')[0],0)
        self.assertGreaterEqual(classify('BIM Revit 建模接单','土建工作室')[0],65)
        with self.assertRaises(ValueError):
            canonical_profile('https://evil.invalid/user/profile/abc')


if __name__ == '__main__': unittest.main()
