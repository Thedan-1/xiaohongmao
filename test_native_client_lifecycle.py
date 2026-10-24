"""Compile the real native form, exercising it without showing or starting it.

Only test-owned child processes and a temporary local HTTP fixture are used.
No WebView navigation, platform browser, user data or paid AI is accessed.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROBE = r'''
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

class NativeLifecycleProbe {
    static object Get(object obj,string name) {
        return obj.GetType().GetField(name,BindingFlags.NonPublic|BindingFlags.Instance).GetValue(obj);
    }
    static void Set(object obj,string name,object value) {
        obj.GetType().GetField(name,BindingFlags.NonPublic|BindingFlags.Instance).SetValue(obj,value);
    }
    static object Call(object obj,string name,params object[] args) {
        return obj.GetType().GetMethod(name,BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.DeclaredOnly).Invoke(obj,args);
    }
    [STAThread] static void Main(string[] args) {
        string mode=args[0],home=args[1],url=args[2];
        Process child=null;
        using(var form=new ClientForm(home,true)) {
            try {
                SynchronizationContext.SetSynchronizationContext(null);
                var result=new Dictionary<string,object>();
                if(mode=="starting_close") {
                    Set(form,"starting",true);
                    var closingArgs=new FormClosingEventArgs(CloseReason.UserClosing,false);
                    Call(form,"OnClosing",form,closingArgs);
                    result["cancelled"]=closingArgs.Cancel;
                    result["close_requested"]=(bool)Get(form,"closeRequested");
                    result["disposed"]=form.IsDisposed;
                    result["allow_close"]=(bool)Get(form,"allowClose");
                } else if(mode=="login_layout") {
                    Call(form,"ShowPlatformLoginAsync",true);
                    form.PerformLayout();
                    var panel=(Control)Get(form,"loginPanel");panel.PerformLayout();
                    var button=(Control)Get(form,"loginBack");button.Parent.PerformLayout();
                    result["bottom_panels"]=System.Linq.Enumerable.Count(System.Linq.Enumerable.Cast<Control>(panel.Controls),c=>c.Dock==DockStyle.Bottom);
                    result["single_status"]=Object.ReferenceEquals(Get(form,"loginStatus"),Get(form,"loginWaiting"));
                    result["button_right"]=button.Right;result["footer_width"]=button.Parent.ClientSize.Width;
                    result["button_top"]=button.Top;result["footer_height"]=button.Parent.ClientSize.Height;
                    var origin=button.Location;var ancestor=button.Parent;
                    while(ancestor!=panel){origin.Offset(ancestor.Location);ancestor=ancestor.Parent;}
                    result["within_panel"]=origin.X>=0&&origin.Y>=0&&origin.X+button.Width<=panel.ClientSize.Width&&origin.Y+button.Height<=panel.ClientSize.Height;
                } else if(mode=="layout") {
                    var content=(Control)Get(form,"content");
                    var menu=(Control)Get(form,"menu");
                    form.PerformLayout();
                    result["content_top"]=content.Top;
                    result["menu_bottom"]=menu.Bottom;
                    result["content_bottom"]=content.Bottom;
                    result["client_height"]=form.ClientSize.Height;
                } else if(mode=="key") {
                    Call(form,"InitializeData");
                    result["config"]=File.ReadAllText(Path.Combine(home,"deepseek.local.txt"));
                } else if(mode=="official_origin") {
                    foreach(string item in new[]{"https://www.xiaohongshu.com/explore", "https://xiaohongshu.com/", "https://www.xiaohongshu.com.evil.test/", "https://notxiaohongshu.com/", "http://www.xiaohongshu.com/", "http://127.0.0.1:8765/", "file:///C:/Windows/", "javascript:alert(1)"})
                        result[item]=(bool)Call(form,"IsOfficialLoginUrl",item);
                } else if(mode=="origin") {
                    Set(form,"backendOrigin","http://127.0.0.1:8765");
                    foreach(string item in new[]{"http://127.0.0.1:8765/", "http://127.0.0.1:8765/?project=1", "http://127.0.0.1:8766/", "https://127.0.0.1:8765/", "http://localhost:8765/", "http://127.0.0.1:8765.evil.test/", "http://evil.test@127.0.0.1:8765/", "file:///C:/Windows/", "javascript:alert(1)"})
                        result[item]=(bool)Call(form,"IsLocal",item);
                } else {
                    bool reused=mode=="reused";
                    if(!reused) {
                        var info=new ProcessStartInfo(args[3],"\""+args[4]+"\""+(mode=="exited"?" --quick":"")) {UseShellExecute=false,CreateNoWindow=true};
                        info.EnvironmentVariables["XHM_QA_STOP_FILE"]=Path.Combine(home,"fixture-exit");
                        child=Process.Start(info);
                        if(mode=="exited")child.WaitForExit();
                        Set(form,"child",child);
                    }
                    int pid=reused?123:child.Id;
                    if(mode=="exited"||mode=="mismatch")pid++;
                    Set(form,"ownsBackend",!reused);
                    if(mode=="pending")Set(form,"runtime",null);
                    else Set(form,"runtime",new Dictionary<string,object>{{"url",url},{"token","fixture-only"},{"pid",pid}});
                    result["stopped"]=((Task<bool>)Call(form,"StopOwnedBackendAsync")).GetAwaiter().GetResult();
                    result["owns_after"]=(bool)Get(form,"ownsBackend");
                }
                Console.WriteLine(NativeClient.Json.Serialize(result));
            } finally {
                if(child!=null) {
                    if(!child.HasExited){child.Kill();child.WaitForExit();}
                    child.Dispose();
                }
            }
        }
    }
}
'''


@unittest.skipUnless(os.name == 'nt', 'Native Windows client tests')
class NativeLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix='xhm-native-fixture-')
        cls.root = Path(cls.folder.name)
        source = cls.root / 'NativeLifecycleProbe.cs'
        source.write_text(PROBE, encoding='utf-8')
        cls.exe = cls.root / 'NativeLifecycleProbe.exe'
        cls.child = cls.root / 'child.py'
        cls.child.write_text("import os,sys,time\nfrom pathlib import Path\nif '--quick' not in sys.argv:\n p=Path(os.environ['XHM_QA_STOP_FILE'])\n while not p.exists(): time.sleep(.05)\n", encoding='utf-8')
        stage = ROOT / 'build-tools/webview2'
        names = ['Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll']
        for name in names:
            shutil.copy2(stage / name, cls.root / name)
        command = [r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe', '/nologo', '/utf8output', '/target:exe', '/platform:x64', '/main:NativeLifecycleProbe', '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll', '/reference:System.Web.Extensions.dll', '/out:' + str(cls.exe)]
        command += ['/reference:' + str(cls.root / name) for name in names]
        command += [str(ROOT / 'build-tools/NativeClient.cs'), str(ROOT / 'build-tools/NativeLogin.cs'), str(ROOT / 'build-tools/NativeLifecycle.cs'), str(source)]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise AssertionError('Native fixture compile failed: ' + exc.stdout + exc.stderr) from exc

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def probe(self, mode, config=None):
        with tempfile.TemporaryDirectory(prefix='xhm-native-user-') as folder:
            home = Path(folder)
            if config is not None:
                (home / 'deepseek.local.txt').write_bytes(config.encode('utf-8'))
            requests = []

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_POST(self):
                    request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    requests.append(request)
                    if request.get('command') == 'shutdown':
                        (home / 'fixture-exit').touch()
                    body = b'{"ok":true}'
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = subprocess.run([str(self.exe), mode, str(home), f'http://127.0.0.1:{server.server_port}', sys.executable, str(self.child)], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout), requests
            finally:
                server.shutdown()
                server.server_close()
                thread.join(3)

    def test_exited_previous_child_does_not_shutdown_replacement(self):
        result, requests = self.probe('exited')
        self.assertTrue(result['stopped'])
        self.assertFalse(requests, 'Closed client stopped a replacement backend it never started')

    def test_live_child_with_mismatched_runtime_pid_does_not_shutdown_replacement(self):
        result, requests = self.probe('mismatch')
        self.assertFalse(result['stopped'])
        self.assertTrue(result['owns_after'])
        self.assertFalse(requests, 'Ownership was trusted without matching runtime PID')

    def test_pending_spawned_child_keeps_client_open_without_runtime(self):
        result, requests = self.probe('pending')
        self.assertFalse(result['stopped'])
        self.assertTrue(result['owns_after'])
        self.assertFalse(requests)

    def test_close_during_initialization_is_deferred_without_disposing_form(self):
        result, requests = self.probe('starting_close')
        self.assertTrue(result['cancelled'])
        self.assertTrue(result['close_requested'])
        self.assertFalse(result['disposed'])
        self.assertFalse(result['allow_close'])
        self.assertFalse(requests)

    def test_matching_owned_child_receives_graceful_shutdown(self):
        result, requests = self.probe('owner')
        self.assertTrue(result['stopped'])
        self.assertFalse(result['owns_after'])
        self.assertEqual(requests, [{'command': 'shutdown'}])

    def test_reused_backend_is_preserved(self):
        result, requests = self.probe('reused')
        self.assertTrue(result['stopped'])
        self.assertFalse(requests)

    def test_content_starts_below_native_menu(self):
        result, _ = self.probe('layout')
        self.assertGreaterEqual(result['content_top'], result['menu_bottom'])
        self.assertEqual(result['content_bottom'], result['client_height'])

    def test_login_has_no_bottom_footer_and_one_status_surface(self):
        result,_=self.probe('login_layout')
        self.assertEqual(result['bottom_panels'],0);self.assertTrue(result['single_status'])
        self.assertLessEqual(result['button_right'],result['footer_width'])
        self.assertTrue(result['within_panel'])
        self.assertGreaterEqual(result['button_top'],0)

    def test_exact_origin_only_is_internal(self):
        result, _ = self.probe('origin')
        for url, allowed in result.items():
            with self.subTest(url=url):
                self.assertEqual(allowed, url in ('http://127.0.0.1:8765/', 'http://127.0.0.1:8765/?project=1'))

    def test_existing_key_and_intentional_blank_survive_initialization(self):
        for config in ('DEEPSEEK_API_KEY=fixture-user-key\n', 'DEEPSEEK_API_KEY=\n'):
            with self.subTest(configured='fixture-user-key' in config):
                result, _ = self.probe('key', config)
                self.assertEqual(result['config'], config)

    def test_official_login_window_rejects_lookalike_and_insecure_origins(self):
        result,_=self.probe('official_origin')
        for url,allowed in result.items():
            with self.subTest(url=url):self.assertEqual(allowed,url in ('https://www.xiaohongshu.com/explore','https://xiaohongshu.com/'))


if __name__ == '__main__':
    unittest.main()
