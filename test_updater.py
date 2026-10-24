"""Update selection, download integrity, admission and safe preview switching."""
import hashlib,io,json,sqlite3,tempfile,time,unittest,zipfile
from pathlib import Path
from unittest.mock import Mock,patch
import updater,update_apply,release_config

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.root=self.base/'preview/app-old';self.root.mkdir(parents=True)
        self.home=self.base/'user';self.data=self.home/'data';self.data.mkdir(parents=True)
        (self.root/'release-config.json').write_text(json.dumps({'version':'0.7.0','repository':'Thedan-1/xiaohongmao'}),encoding='utf-8')
        (self.root/'package-manifest.json').write_text(json.dumps({'distribution':'preview','version':'0.7.0'}),encoding='utf-8')
        (self.root/'小红帽.exe').write_bytes(b'old')
        self.task=updater.UpdateManager(self.root,self.data)
        self.body=b'fixture-update';self.release=self.make_release()
    def tearDown(self):self.tmp.cleanup()
    def make_release(self,version='0.7.1',distribution='preview',body=None):
        body=self.body if body is None else body;name=release_config.asset_name(version,distribution)
        return {'draft':False,'prerelease':False,'tag_name':'v'+version,'body':'<script>untrusted notes</script>',
                'assets':[{'name':name,'state':'uploaded','size':len(body),'digest':'sha256:'+hashlib.sha256(body).hexdigest(),'browser_download_url':f'https://github.com/Thedan-1/xiaohongmao/releases/download/v{version}/{name}'}]}
    def selected(self):return updater.choose_release(self.release,self.task.config,'preview')

    def test_semantic_version_order_latest_drafts_and_prereleases(self):
        self.assertGreater(release_config.version('0.10.0'),release_config.version('0.9.9'))
        self.assertIsNone(updater.choose_release(self.make_release('0.6.9'),self.task.config,'preview'))
        for flag in ['draft','prerelease']:
            raw={**self.release,flag:True}
            with self.assertRaises(ValueError):updater.choose_release(raw,self.task.config,'preview')
        for value in ['v1.0.0','1.0','01.0.0','1.0.0-beta','1.0.0/evil']:
            with self.assertRaises(ValueError):release_config.version(value)

    def test_wrong_source_missing_digest_and_wrong_distribution_are_rejected(self):
        for delta in [{'browser_download_url':'https://evil.test/pkg.zip'},{'digest':None},{'size':True},{'size':2**40}]:
            raw={**self.release,'assets':[{**self.release['assets'][0],**delta}]}
            with self.assertRaises(ValueError):updater.choose_release(raw,self.task.config,'preview')
        with self.assertRaises(ValueError):updater.choose_release(self.release,self.task.config,'installed')

    def test_download_only_becomes_ready_after_size_and_sha_match(self):
        item=self.selected();self.task.selected=item
        response=io.BytesIO(self.body);opener=Mock();opener.open.return_value=response
        with patch.object(updater.urllib.request,'build_opener',return_value=opener):self.task._download(item)
        self.assertEqual(self.task.status()['phase'],'ready');self.assertEqual(self.task.staged.read_bytes(),self.body)

    def test_truncated_or_tampered_download_never_replaces_application(self):
        for body in [b'wrong',self.body[:-1],self.body+b'oversized']:
            with self.subTest(body=body):
                opener=Mock();opener.open.return_value=io.BytesIO(body)
                with patch.object(updater.urllib.request,'build_opener',return_value=opener):self.task._download(self.selected())
                self.assertEqual(self.task.status()['phase'],'error');self.assertEqual((self.root/'小红帽.exe').read_bytes(),b'old')
                self.assertEqual(list(self.task.folder.glob('*.part')),[])

    def test_download_cancellation_does_not_modify_application(self):
        self.task.cancel.set();opener=Mock();opener.open.return_value=io.BytesIO(self.body)
        with patch.object(updater.urllib.request,'build_opener',return_value=opener):self.task._download(self.selected())
        self.assertEqual(self.task.status()['phase'],'available');self.assertFalse(self.task.staged)

    def test_busy_task_cannot_prepare_or_request_shutdown(self):
        app=Mock();app.DATA=self.data;app.SHUTTING_DOWN.is_set.return_value=False
        with patch('studio.is_busy',return_value=True),self.assertRaisesRegex(ValueError,'任务仍在运行'):self.task.prepare(app)
        app.request_command.assert_not_called()

    def test_check_cache_avoids_network_and_current_version_is_latest(self):
        self.task.folder.mkdir();(self.task.folder/'release-cache.json').write_text(json.dumps({'repository':'Thedan-1/xiaohongmao','checked_at':time.time(),'release':self.make_release('0.7.0')}),encoding='utf-8')
        with patch.object(updater.urllib.request,'build_opener') as request:self.task._check(True)
        request.assert_not_called();self.assertEqual(self.task.status()['phase'],'latest')

    def test_redirects_cannot_leave_github_content_hosts(self):
        handler=updater.SafeRedirect()
        for url in ['http://github.com/file','https://evil.test/file','https://github.com.evil.test/file']:
            with self.assertRaises(RuntimeError):handler.redirect_request(None,None,302,'',{},url)

    def archive(self,extra=None):
        package=self.data/'updates/fixture.zip';package.parent.mkdir(exist_ok=True)
        files=['小红帽.exe','app.py'];manifest={'version':'0.7.1','distribution':'preview','credential_embedded':False,'user_data_included':False,'files':files}
        prefix='小红帽-免安装预览版/';source='app-0.7.1-fixture'
        with zipfile.ZipFile(package,'w') as z:
            z.writestr(prefix+'current-app.txt',source);z.writestr(prefix+'小红帽预览.exe',b'new launcher');z.writestr(prefix+'使用说明.txt','fixture')
            z.writestr(prefix+source+'/package-manifest.json',json.dumps(manifest));z.writestr(prefix+source+'/小红帽.exe',b'new');z.writestr(prefix+source+'/app.py',b'new source')
            if extra:z.writestr(extra,b'untrusted')
        (self.root.parent/'current-app.txt').write_text(self.root.name,encoding='utf-8');(self.root.parent/'小红帽预览.exe').write_bytes(b'old launcher')
        return {'version':'0.7.1','distribution':'preview','package':str(package),'sha256':updater.digest_file(package),'app_root':str(self.root),'data_home':str(self.home),'created_at':time.time()}

    def test_preview_switch_preserves_old_version_and_all_user_data(self):
        plan=self.archive();sentinel=self.data/'keep.sqlite3';sentinel.write_bytes(b'user-records')
        root,home,package=update_apply.validate_plan(plan);target,previous=update_apply.apply_preview(plan,root,package)
        self.assertEqual(previous,self.root.name);self.assertEqual((target/'小红帽.exe').read_bytes(),b'new')
        self.assertEqual((self.root/'小红帽.exe').read_bytes(),b'old');self.assertEqual(sentinel.read_bytes(),b'user-records')
        self.assertEqual((root.parent/'current-app.txt').read_text(encoding='utf-8'),target.name)

    def test_zip_traversal_and_unlisted_files_do_not_switch_pointer(self):
        for entry in ['小红帽-免安装预览版/../outside.txt','小红帽-免安装预览版/.. /outside.txt','小红帽-免安装预览版/CON.txt','小红帽-免安装预览版/unlisted.txt']:
            plan=self.archive(entry);root,home,package=update_apply.validate_plan(plan)
            with self.assertRaises(ValueError):update_apply.apply_preview(plan,root,package)
            self.assertEqual((root.parent/'current-app.txt').read_text(encoding='utf-8'),root.name)

    def test_changed_file_and_expired_plan_are_rejected(self):
        plan=self.archive();plan['created_at']=time.time()-700
        with self.assertRaises(ValueError):update_apply.validate_plan(plan)
        plan['created_at']=time.time();Path(plan['package']).write_bytes(b'changed')
        with self.assertRaises(ValueError):update_apply.validate_plan(plan)

if __name__=='__main__':unittest.main()
