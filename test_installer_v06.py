"""Install the identical payload under a separate QA identity; preserve the real app."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import build_installer

ROOT=Path(__file__).resolve().parent
REPORT=ROOT/'data/desktop-qa/v06-install-results.json'

def run():
    checks=[]
    with tempfile.TemporaryDirectory(prefix='xhm-v06-install-') as folder:
        root=Path(folder).resolve();target=root/'中文安装位置'/'小红帽'
        assert target.resolve().is_relative_to(root)
        payload=root/'payload';payload.mkdir()
        build_installer.prepare_payload(build_installer.DEFAULT_STAGE,payload,False,root/'unused.txt')
        identity='Xiaohongmao.QA06.'+str(time.time_ns());mutex='Local\\'+identity
        subprocess.run([str(build_installer.find_compiler(None)),'/Qp','/DSourceDir='+str(payload),'/DOutputDir='+str(root),'/DOutputName=qa-setup','/DAppIdentity='+identity,'/DClientMutex='+mutex,str(ROOT/'installer/小红帽.iss')],check=True)
        setup=root/'qa-setup.exe'
        args=['/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/NOICONS','/DIR='+str(target)]
        subprocess.run([str(setup),*args],check=True,timeout=90)
        exe=target/'小红帽.exe';assert exe.exists()
        for name in ['小红帽.exe','ui.html','login_session.py']:
            assert hashlib.sha256((target/name).read_bytes()).digest()==hashlib.sha256((build_installer.DEFAULT_STAGE/name).read_bytes()).digest()
        assert (target/'Motion-LICENSE.txt').exists();assert (target/'WebView2-LICENSE.txt').exists()
        assert (target/'default-key.txt').read_text(encoding='utf-8').strip()=='DEEPSEEK_API_KEY='
        checks.append('custom Chinese install path, exact client/UI/session code, blank ordinary key, licenses')
        # Protect the previous stage run evidence before the installed run writes its standard report.
        prior=ROOT/'data/desktop-qa/native-client-results.json'
        if prior.exists():shutil.copy2(prior,prior.with_name('v06-stage-client-results.json'))
        env=os.environ.copy();env['XIAOHONGMAO_TEST_INSTALL']=str(target)
        subprocess.run([sys.executable,'-X','utf8',str(ROOT/'test_desktop_client.py')],cwd=ROOT,env=env,check=True,timeout=300)
        shutil.copy2(prior,prior.with_name('v06-installed-client-results.json'))
        checks.append('installed client: fresh/reused backend, duplicate launch, native login fixture, settings, exit')
        sentinel=target/'data/keep.txt';sentinel.parent.mkdir();sentinel.write_text('preserve fixture records',encoding='utf-8')
        subprocess.run([str(setup),*args],check=True,timeout=90)
        assert sentinel.read_text(encoding='utf-8')=='preserve fixture records'
        checks.append('reinstallation preserves unknown user records')
        source=root/'HoldMutex.cs';source.write_text('using System;using System.Threading;class HoldMutex{static void Main(string[] args){using(var m=new Mutex(false,args[0])){Console.WriteLine("READY");Console.Out.Flush();Thread.Sleep(Timeout.Infinite);}}}',encoding='utf-8')
        holder=root/'hold.exe';subprocess.run([r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe','/nologo','/out:'+str(holder),str(source)],check=True)
        process=subprocess.Popen([str(holder),mutex],stdout=subprocess.PIPE,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            assert process.stdout.readline().strip()=='READY'
            refused=subprocess.run([str(setup),*args],timeout=30)
            assert refused.returncode!=0 and exe.exists()
            uninstaller=target/'unins000.exe'
            refused=subprocess.run([str(uninstaller),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'],timeout=30)
            assert refused.returncode!=0 and exe.exists()
            checks.append('running-client mutex blocks install and uninstall')
        finally:
            process.terminate();process.wait(timeout=10);process.stdout.close()
        subprocess.run([str(target/'unins000.exe'),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'],check=True,timeout=90)
        assert not exe.exists() and sentinel.exists()
        checks.append('uninstall removes executable and preserves user records')
    REPORT.write_text(json.dumps({'version':'0.6','ok':True,'checks':checks,'real_sends':0,'paid_calls':0,'real_app_identity_untouched':True},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Isolated installer QA passed:',REPORT)

if __name__=='__main__':run()
