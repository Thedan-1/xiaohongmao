"""Real WebView2 + automatic login timer against an intercepted official page.

The session is synthetic; the bridge endpoint is an isolated localhost fixture.
No real account, desktop window, outbound message or paid AI is used.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

ROOT=Path(__file__).resolve().parent
PROBE=r'''
using System;using System.IO;using System.Drawing;using System.Reflection;
using System.Threading.Tasks;using System.Collections.Generic;using System.Windows.Forms;
using Microsoft.Web.WebView2.WinForms;
class NativeAutoLoginProbe {
 [STAThread] static void Main(string[] args){Application.EnableVisualStyles();Application.Run(new Host(args));}
}
class Host:Form {
 string[] args;ClientForm client;
 object Get(string field){return typeof(ClientForm).GetField(field,BindingFlags.NonPublic|BindingFlags.Instance).GetValue(client);}
 Task Call(string method,params object[] values){return (Task)typeof(ClientForm).GetMethod(method,BindingFlags.NonPublic|BindingFlags.Instance).Invoke(client,values);}
 public Host(string[] values){args=values;Opacity=0;ShowInTaskbar=false;Location=new Point(-24000,-24000);StartPosition=FormStartPosition.Manual;Shown+=async(s,e)=>await Run();}
 async Task Run(){try{
  client=new ClientForm(args[0],false);var handle=client.Handle;
  typeof(ClientForm).GetField("runtime",BindingFlags.NonPublic|BindingFlags.Instance).SetValue(client,new Dictionary<string,object>{{"url",args[1]},{"token","offline-fixture"}});
  await Call("ShowPlatformLoginAsync",true);
  WebView2 browser=(WebView2)Get("loginView");
  for(int i=0;i<100;i++){if(browser.CoreWebView2!=null&&((bool)Get("loginPageReady")))break;await Task.Delay(100);}
  if(args[2]=="retry"){
   Task pending=Call("CheckPlatformLoginAsync",true);
   string immediate=((Label)Get("loginStatus")).Text;
   await pending;
   File.WriteAllText(Path.Combine(args[0],"result.json"),NativeClient.Json.Serialize(new {returned=Get("loginPanel")==null,hint=((Label)Get("loginStatus")).Text,immediate=immediate}));
   return;
  }
  var cookie=browser.CoreWebView2.CookieManager.CreateCookie("web_session","offline-synthetic-session",".xiaohongshu.com","/");
  cookie.IsHttpOnly=true;cookie.IsSecure=true;browser.CoreWebView2.CookieManager.AddOrUpdateCookie(cookie);
  // No button or direct check call: the application's timer must detect and connect.
  for(int i=0;i<140;i++){
   if(Get("loginPanel")==null)break;
   if((args[2]=="failed"&&((Label)Get("loginStatus")).Text.Contains("fixture rejection"))||(args[2]=="incomplete"&&((Label)Get("loginStatus")).Text.Contains("未进入工作台"))){await Task.Delay(2200);break;}
   await Task.Delay(100);
  }
  bool returned=Get("loginPanel")==null;
  string hint=returned?"":((Label)Get("loginStatus")).Text;
  File.WriteAllText(Path.Combine(args[0],"result.json"),NativeClient.Json.Serialize(new {returned=returned,hint=hint}));
 }catch(Exception ex){File.WriteAllText(Path.Combine(args[0],"result.json"),NativeClient.Json.Serialize(new {error=ex.ToString()}));}
 finally{if(client!=null)client.Dispose();Close();}}
}
'''

@unittest.skipUnless(os.name=='nt','Windows native WebView2')
class NativeLoginReturnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='xhm-auto-login-');cls.root=Path(cls.tmp.name)
        (cls.root/'Probe.cs').write_text(PROBE,encoding='utf-8')
        sdk=ROOT/'build-tools/webview2'
        for name in ['Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll','WebView2Loader.dll']:
            shutil.copy2(sdk/name,cls.root/name)
        shutil.copy2(ROOT/'login-focus.js',cls.root/'login-focus.js')
        cls.exe=cls.root/'Probe.exe'
        cmd=[r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe','/nologo','/utf8output','/target:exe','/platform:x64','/main:NativeAutoLoginProbe','/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.Web.Extensions.dll','/out:'+str(cls.exe)]
        cmd+=['/reference:'+str(cls.root/n) for n in ['Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll']]
        cmd+=[str(ROOT/'build-tools/NativeClient.cs'),str(ROOT/'build-tools/NativeLogin.cs'),str(ROOT/'build-tools/NativeLifecycle.cs'),str(cls.root/'Probe.cs')]
        r=subprocess.run(cmd,capture_output=True,text=True);assert r.returncode==0,r.stdout+r.stderr

    @classmethod
    def tearDownClass(cls):
        # WebView2 releases its test-owned profile asynchronously after disposal.
        assert cls.root.resolve().parent==Path(tempfile.gettempdir()).resolve()
        assert cls.root.name.startswith('xhm-auto-login-')
        for attempt in range(24):
            try:cls.tmp.cleanup();return
            except (PermissionError,NotADirectoryError):
                if attempt==23:raise
                time.sleep(.25)

    def run_case(self,failed=False,incomplete=False,retry=False):
        mode='retry' if retry else 'incomplete' if incomplete else 'failed' if failed else 'success'
        home=self.root/mode;home.mkdir()
        posts=[];gets=[];transfer=[None]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def result(self,value):
                body=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_GET(self):
                gets.append(1)
                # Exercise waiting for user-owned active work before transferring.
                state={'task':'busy' if len(gets)<3 else 'idle','login':'required'}
                if transfer[0]:state.update(login='unknown' if failed else 'ready',login_verified_profile=None if failed else 'https://www.xiaohongshu.com/user/profile/FixtureOwner',login_transfer_id=transfer[0],login_transfer_status='failed' if failed else 'complete',message='fixture rejection' if failed else 'connected')
                if incomplete:state.update(login='connecting',login_verified_profile=None)
                self.result({'state':state})
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                posts.append(data);transfer[0]=data['transfer_id'];self.result({'ok':True})
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            p=subprocess.run([str(self.exe),str(home),f'http://127.0.0.1:{server.server_port}',mode],timeout=30,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(p.returncode,0,p.stderr)
            result=json.loads((home/'result.json').read_text(encoding='utf-8-sig'))
            self.assertNotIn('error',result,result)
            if retry:
                self.assertFalse(posts,'missing login must not start a transfer')
                return result
            self.assertEqual(len(posts),1,'automatic login should transfer once, never loop')
            self.assertEqual(posts[0]['command'],'login_session')
            self.assertEqual(posts[0]['expected_profile'],'https://www.xiaohongshu.com/user/profile/FixtureOwner')
            self.assertGreaterEqual(len(gets),4)
            return result
        finally:server.shutdown();server.server_close();thread.join()

    def test_timer_connects_and_returns_without_clicking(self):
        self.assertTrue(self.run_case()['returned'])

    def test_failed_transfer_keeps_login_visible_without_retry_loop(self):
        result=self.run_case(True);self.assertFalse(result['returned']);self.assertIn('fixture rejection',result['hint'])

    def test_complete_flag_alone_is_not_login_success(self):
        result=self.run_case(incomplete=True);self.assertFalse(result['returned']);self.assertIn('未进入工作台',result['hint'])

    def test_manual_retry_first_shows_checking_and_never_claims_success(self):
        result=self.run_case(retry=True)
        self.assertIn('正在检测',result['immediate']);self.assertIn('尚未检测到',result['hint']);self.assertFalse(result['returned'])

if __name__=='__main__':unittest.main()
