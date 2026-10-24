"""Actual Inno upgrade through the helper; temporary AppId, paths and dummy app."""
import json,os,subprocess,tempfile,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import build_installer,update_apply

@unittest.skipUnless(os.name=='nt','Windows installer integration')
class InstallerUpdateTests(unittest.TestCase):
    def test_real_upgrade_keeps_data_and_uses_same_install_directory(self):
        with tempfile.TemporaryDirectory(prefix='xhm-update-install-') as temp:
            folder=Path(temp);identity='Xiaohongmao.UpdateFixture.'+uuid.uuid4().hex
            home=folder/'user';updates=home/'data/updates';updates.mkdir(parents=True);sentinel=home/'data/keep.sqlite3';sentinel.write_bytes(b'fixture user records')
            target=folder/'中文 程序目录';source=folder/'payload';source.mkdir()
            (source/'小红帽.exe').write_bytes(b'fixture-old-app')
            compiler=build_installer.find_compiler(None)
            def build(version,name):
                (source/'package-manifest.json').write_text(json.dumps({'version':version,'distribution':'installed'}),encoding='utf-8')
                subprocess.run([str(compiler),'/Qp','/DSourceDir='+str(source),'/DOutputDir='+str(folder),'/DOutputName='+name,'/DAppIdentity='+identity,'/DClientMutex=Local\\'+identity,'/DAppVersion='+version,str(build_installer.ROOT/'installer/小红帽.iss')],check=True,capture_output=True)
                return folder/(name+'.exe')
            first=build('0.6.6','old');subprocess.run([str(first),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/NOICONS','/DIR='+str(target)],check=True)
            try:
                (source/'小红帽.exe').write_bytes(b'fixture-new-app');second=build('0.7.0','new')
                package=updates/'update.exe';package.write_bytes(second.read_bytes())
                plan={'version':'0.7.0','distribution':'installed','package':str(package),'sha256':update_apply.sha256(package),'app_root':str(target),'data_home':str(home),'created_at':time.time()}
                path=folder/'plan.json';path.write_text(json.dumps(plan),encoding='utf-8')
                with patch.object(update_apply,'launch') as launch:update_apply.run(path,0)
                launch.assert_called_once_with(target.resolve(),home.resolve(),False)
                self.assertEqual((target/'小红帽.exe').read_bytes(),b'fixture-new-app')
                self.assertEqual(json.loads((target/'package-manifest.json').read_text(encoding='utf-8'))['version'],'0.7.0')
                self.assertEqual(sentinel.read_bytes(),b'fixture user records')
                self.assertTrue(json.loads((home/'data/update-result.json').read_text(encoding='utf-8'))['ok'])
            finally:
                uninstaller=target/'unins000.exe'
                if uninstaller.exists():subprocess.run([str(uninstaller),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'],check=True)

if __name__=='__main__':unittest.main()
