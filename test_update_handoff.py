"""Real native -> local backend -> copied updater -> new fixture app.

Uses only test-owned processes, data and a synthetic ZIP. No external requests.
"""
import json,os,shutil,subprocess,sys,tempfile,time,unittest,zipfile
from pathlib import Path
import build_desktop,update_apply

ROOT=Path(__file__).resolve().parent
PROBE=r'''
using System;using System.IO;using System.Drawing;using System.Reflection;using System.Diagnostics;
using System.Threading.Tasks;using System.Windows.Forms;using System.Collections.Generic;
class UpdateProbe {
 [STAThread]static void Main(string[] args){Application.EnableVisualStyles();Application.Run(new Host(args));}
}
class Host:Form {
 string[] args;ClientForm client;
 void Set(string name,object value){typeof(ClientForm).GetField(name,BindingFlags.Instance|BindingFlags.NonPublic).SetValue(client,value);}
 public Host(string[] values){args=values;Opacity=0;ShowInTaskbar=false;StartPosition=FormStartPosition.Manual;Location=new Point(-24000,-24000);Shown+=async(s,e)=>await Run();}
 async Task Run(){try{
  client=new ClientForm(args[0],false);var handle=client.Handle;
  var runtime=NativeClient.Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(args[0],"data","runtime.json")));
  Set("root",args[1]);Set("runtime",runtime);Set("child",Process.GetProcessById(Convert.ToInt32(runtime["pid"])));Set("ownsBackend",true);
  await (Task)typeof(ClientForm).GetMethod("ApplyUpdateAsync",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(client,null);
  for(int i=0;i<200&&!client.IsDisposed;i++)await Task.Delay(100);
  if(!client.IsDisposed)throw new Exception("native updater did not close after backend handoff");
  File.WriteAllText(Path.Combine(args[0],"native-handoff-ok"),"ok");
 }catch(Exception ex){File.WriteAllText(Path.Combine(args[0],"native-handoff-error"),ex.ToString());}
 finally{if(client!=null)client.Dispose();Close();}}
}
'''

@unittest.skipUnless(os.name=='nt','Windows native handoff integration')
class UpdateHandoffTests(unittest.TestCase):
    def test_native_update_exits_before_preview_switch_and_preserves_user_files(self):
        with tempfile.TemporaryDirectory(prefix='xhm-handoff-') as temp:
            base=Path(temp);old=base/'preview/app-old';old.mkdir(parents=True);home=base/'user';data=home/'data';data.mkdir(parents=True)
            (home/'deepseek.local.txt').write_text('DEEPSEEK_API_KEY=offline-handoff-fixture\n',encoding='utf-8')
            (data/'keep.txt').write_text('preserve user state',encoding='utf-8')
            (old/'小红帽.exe').write_bytes(b'old fixture retained');(old/'package-manifest.json').write_text(json.dumps({'version':'0.7.0','distribution':'preview'}),encoding='utf-8')
            (old/'release-config.json').write_text(json.dumps({'version':'0.7.0','repository':'Thedan-1/xiaohongmao'}),encoding='utf-8')
            (old.parent/'current-app.txt').write_text(old.name,encoding='utf-8');(old.parent/'小红帽预览.exe').write_bytes(b'fixture launcher')
            shutil.copytree(build_desktop.STAGE/'python',old/'python');shutil.copy2(ROOT/'update_apply.py',old/'update_apply.py')
            compiler=r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
            tiny=base/'NewApp.cs';tiny.write_text('using System;using System.IO;class NewApp{[STAThread]static void Main(){File.WriteAllText(Path.Combine(Environment.GetEnvironmentVariable("XIAOHONGMAO_DATA_HOME"),"upgraded-marker"),"new version started");}}',encoding='utf-8')
            newexe=base/'NewApp.exe';subprocess.run([compiler,'/nologo','/target:winexe','/out:'+str(newexe),str(tiny)],check=True,capture_output=True)
            updates=data/'updates';updates.mkdir();package=updates/'fixture.zip';prefix='小红帽-免安装预览版/';source='app-0.7.1-fixture'
            with zipfile.ZipFile(package,'w') as z:
                z.writestr(prefix+'current-app.txt',source);z.writestr(prefix+'小红帽预览.exe',b'fixture launcher');z.writestr(prefix+'使用说明.txt','fixture')
                z.writestr(prefix+source+'/package-manifest.json',json.dumps({'version':'0.7.1','distribution':'preview','credential_embedded':False,'user_data_included':False,'files':['小红帽.exe','app.py']}))
                z.writestr(prefix+source+'/小红帽.exe',newexe.read_bytes());z.writestr(prefix+source+'/app.py','# fixture')
            backend=base/'backend.py';backend.write_text('''import sys,threading,json,os
from pathlib import Path
sys.path.insert(0,sys.argv[1]);import app,updater
app.ROOT=Path(sys.argv[2]);app.init_db()
manager=updater.manager(app);manager.staged=Path(sys.argv[3]);manager.selected={'version':'0.7.1','sha256':updater.digest_file(manager.staged)};manager.change(phase='ready')
app.SERVER=app.LocalServer(('127.0.0.1',0),app.Handler)
(app.DATA/'runtime.json').write_text(json.dumps({'url':'http://127.0.0.1:'+str(app.SERVER.server_port),'token':app.TOKEN,'pid':os.getpid()}),encoding='utf-8')
threading.Thread(target=app.BrowserWorker().run,daemon=True).start();app.SERVER.serve_forever();app.SERVER.server_close()
''',encoding='utf-8')
            probe=base/'Probe.cs';probe.write_text(PROBE,encoding='utf-8');probeexe=base/'Probe.exe'
            for name in ['Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll','WebView2Loader.dll']:shutil.copy2(ROOT/'build-tools/webview2'/name,base/name)
            cmd=[compiler,'/nologo','/utf8output','/target:winexe','/main:UpdateProbe','/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.Web.Extensions.dll','/out:'+str(probeexe)]
            cmd+=['/reference:'+str(base/name) for name in ['Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll']]
            cmd+=[str(ROOT/'build-tools'/name) for name in ['NativeClient.cs','NativeLogin.cs','NativeLifecycle.cs']]+[str(probe)]
            built=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8');self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            env=os.environ.copy();env['XIAOHONGMAO_DATA_HOME']=str(home);env['XIAOHONGMAO_DESKTOP_SMOKE']='1'
            child=subprocess.Popen([sys.executable,'-X','utf8',str(backend),str(ROOT),str(old),str(package)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                for _ in range(100):
                    if (data/'runtime.json').exists():break
                    time.sleep(.05)
                self.assertTrue((data/'runtime.json').is_file())
                subprocess.run([str(probeexe),str(home),str(old)],env=env,check=True,timeout=35)
                self.assertFalse((home/'native-handoff-error').exists(),(home/'native-handoff-error').read_text() if (home/'native-handoff-error').exists() else '')
                self.assertTrue((home/'native-handoff-ok').is_file())
                for _ in range(150):
                    if (home/'upgraded-marker').is_file() and (data/'update-result.json').is_file():break
                    time.sleep(.1)
                self.assertTrue((home/'upgraded-marker').is_file(),'new app was not launched by copied updater')
                self.assertTrue(json.loads((data/'update-result.json').read_text())['ok'])
                self.assertEqual((data/'keep.txt').read_text(),'preserve user state');self.assertIn('offline-handoff-fixture',(home/'deepseek.local.txt').read_text())
                self.assertNotEqual((old.parent/'current-app.txt').read_text(),old.name);self.assertEqual((old/'小红帽.exe').read_bytes(),b'old fixture retained')
                child.wait(timeout=10);self.assertEqual(child.returncode,0)
            finally:
                if child.poll() is None:child.terminate();child.wait(timeout=10)

if __name__=='__main__':unittest.main()
