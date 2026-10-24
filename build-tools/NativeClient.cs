using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
[assembly:System.Reflection.AssemblyTitle("小红帽")]
[assembly:System.Reflection.AssemblyProduct("小红帽 Windows 客户端")]

static class NativeClient {
    public static readonly JavaScriptSerializer Json=new JavaScriptSerializer();
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h,int command);
    [STAThread] static void Main(string[] args) {
        bool smoke=Array.IndexOf(args,"--smoke-test")>=0;
        bool preview=Array.IndexOf(args,"--preview")>=0;
        string home=Environment.GetEnvironmentVariable("XIAOHONGMAO_DATA_HOME");
        if(smoke&&String.IsNullOrWhiteSpace(home)){Environment.ExitCode=2;return;}
        if(String.IsNullOrWhiteSpace(home))home=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),preview?"XiaohongmaoPreview":"Xiaohongmao");
        home=Path.GetFullPath(home);
        string mutexName="Local\\XiaohongmaoDesktop_v05";
        if(preview)mutexName+="_preview";
        if(smoke)using(var sha=SHA256.Create())mutexName+="_test_"+BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(home))).Replace("-","");
        bool acquired;
        using(var mutex=new Mutex(true,mutexName,out acquired)) {
            if(!acquired) {
                try {
                    var state=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(home,"client.json")));
                    var handle=new IntPtr(Convert.ToInt64(state["handle"]));
                    if(!smoke){ShowWindow(handle,9);SetForegroundWindow(handle);}
                }catch{}
                return;
            }
            Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
            try {Directory.CreateDirectory(home);Application.Run(new ClientForm(home,smoke));}
            catch(Exception ex) {
                if(smoke)File.WriteAllText(Path.Combine(home,"desktop-test.json"),Json.Serialize(new {ok=false,error=ex.Message}));
                else MessageBox.Show("启动失败："+ex.Message,"小红帽",MessageBoxButtons.OK,MessageBoxIcon.Error);
                Environment.ExitCode=1;
            }
        }
    }
}

partial class ClientForm:Form {
    readonly string home,root;readonly bool smoke;
    WebView2 view;Panel content,splash;Label status;Button retry,settings;MenuStrip menu;
    Dictionary<string,object> runtime;
    Process child;bool ownsBackend,closing,allowClose,starting,smokeStarted,closeRequested,autoLoginPrompted;
    Panel loginPanel;WebView2 loginView;Label loginStatus;
    string backendOrigin="";System.Windows.Forms.Timer testTimer;
    readonly List<string> testChecks=new List<string>();
    bool updateInProgress;

    public ClientForm(string dataHome,bool test) {
        home=dataHome;smoke=test;root=AppDomain.CurrentDomain.BaseDirectory;
        Text="小红帽";Size=new Size(1380,900);MinimumSize=new Size(940,650);
        bool preview=Array.IndexOf(Environment.GetCommandLineArgs(),"--preview")>=0;
        if(preview)Text="小红帽 · 免安装预览";
        Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        StartPosition=FormStartPosition.CenterScreen;BackColor=Color.White;
        Font=new Font("Microsoft YaHei UI",10);AutoScaleMode=AutoScaleMode.Dpi;
        menu=new MenuStrip{BackColor=Color.FromArgb(250,249,250)};
        var appMenu=new ToolStripMenuItem("小红帽");
        appMenu.DropDownItems.Add("AI 设置…",null,(s,e)=>ShowSettings());
        appMenu.DropDownItems.Add("登录 / 切换小红书账号…",null,async(s,e)=>await OpenPlatformAccountAsync());
        if(preview){
            var reload=new ToolStripMenuItem("刷新预览界面（F5）");reload.ShortcutKeys=Keys.F5;
            reload.Click+=(s,e)=>{if(view!=null&&view.CoreWebView2!=null)view.CoreWebView2.Reload();};
            appMenu.DropDownItems.Add(reload);
        }
        appMenu.DropDownItems.Add("打开数据文件夹",null,(s,e)=>Process.Start("explorer.exe",home));
        appMenu.DropDownItems.Add("使用说明",null,(s,e)=>MessageBox.Show("登录：打开左下角设置中的账号与登录，在官方窗口完成登录。\n项目数据保存在本机，可在个人设置管理。\n关闭客户端会结束由本窗口启动的空闲后台；任务进行中会先提示。\n\n版本 "+typeof(NativeClient).Assembly.GetName().Version.ToString(3)+" · Windows 客户端","小红帽"));
        appMenu.DropDownItems.Add(new ToolStripSeparator());
        appMenu.DropDownItems.Add("退出",null,(s,e)=>Close());
        menu.Items.Add(appMenu);MainMenuStrip=menu;Controls.Add(menu);
        content=new Panel{Dock=DockStyle.Fill};Controls.Add(content);menu.SendToBack();
        CreateLifecycle();
        if(smoke){ShowInTaskbar=false;Opacity=0;StartPosition=FormStartPosition.Manual;Location=new Point(-24000,-24000);}
        Shown+=async(s,e)=>{
            File.WriteAllText(Path.Combine(home,"client.json"),NativeClient.Json.Serialize(new {pid=Process.GetCurrentProcess().Id,handle=Handle.ToInt64()}));
            if(smoke){testTimer=new System.Windows.Forms.Timer{Interval=120000};testTimer.Tick+=(ts,te)=>FinishTest(false,"Client test timed out");testTimer.Start();}
            await StartAsync();
        };
        FormClosing+=OnClosing;
        FormClosed+=(s,e)=>{if(view!=null)view.Dispose();if(testTimer!=null)testTimer.Dispose();try{File.Delete(Path.Combine(home,"client.json"));}catch{}};
    }

    string KeyPath {get{return Path.Combine(home,"deepseek.local.txt");}}
    string ReadKey(string path) {
        if(!File.Exists(path))return "";
        foreach(string line in File.ReadAllLines(path)){
            var pair=line.Split(new char[]{'='},2);
            if(pair.Length==2&&pair[0].Trim()=="DEEPSEEK_API_KEY")return pair[1].Trim().Trim('"','\'');
        }
        return "";
    }
    void InitializeData() {
        Directory.CreateDirectory(Path.Combine(home,"data"));
        // Upgrade never changes an existing user configuration, including an intentionally blank key.
        if(!File.Exists(KeyPath)){
            string seed=Path.Combine(root,"default-key.txt");
            File.WriteAllText(KeyPath,"DEEPSEEK_API_KEY="+(smoke?"":ReadKey(seed))+"\n",new UTF8Encoding(false));
        }
    }
    async void ShowSettings() {
        try {
            if(view!=null&&view.CoreWebView2!=null){await view.CoreWebView2.ExecuteScriptAsync("if(typeof openSettings==='function')openSettings('ai');");return;}
            MessageBox.Show(this,"请在工作台加载后，进入设置 → 模型与 API。","小红帽");
        }catch{MessageBox.Show(this,"设置页面尚未就绪，请稍后重试。","小红帽");}
    }
    async Task ApplyUpdateAsync() {
        if(smoke||starting||closing||updateInProgress)return;
        updateInProgress=true;
        string failure=null;
        try {
            if(!OwnsCurrentBackend())throw new InvalidOperationException("当前连接复用了另一个后台，请退出并重新独立启动客户端后更新。");
            var result=await ApiAsync("/api/update","{\"action\":\"prepare\"}");
            string plan=Path.GetFullPath(Convert.ToString(result["plan"]));
            string helper=Path.GetDirectoryName(plan);
            string prefix=Path.GetFullPath(Path.Combine(home,"data","updates","helpers"))+Path.DirectorySeparatorChar;
            string python=Path.GetFullPath(Convert.ToString(result["python"]));
            string script=Path.GetFullPath(Convert.ToString(result["script"]));
            if(!helper.StartsWith(prefix,StringComparison.OrdinalIgnoreCase)||Path.GetFileName(plan)!="plan.json"||python!=Path.Combine(helper,"python","pythonw.exe")||script!=Path.Combine(helper,"update_apply.py"))throw new InvalidOperationException("更新器路径校验失败。");
            var info=new ProcessStartInfo(python,"\""+script+"\" --plan \""+plan+"\" --parent "+Process.GetCurrentProcess().Id){WorkingDirectory=helper,UseShellExecute=false,CreateNoWindow=true};
            info.EnvironmentVariables.Remove("XIAOHONGMAO_DESKTOP_SMOKE");
            Process.Start(info);Close();
        }catch(Exception ex){failure=ex.Message;updateInProgress=false;}
        if(failure!=null&&view!=null&&view.CoreWebView2!=null)await view.CoreWebView2.ExecuteScriptAsync("if(window.updateApplyFailed)updateApplyFailed("+NativeClient.Json.Serialize(failure)+");");
    }

    async Task<Dictionary<string,object>> ApiAsync(string path,string body=null) {
        var request=(HttpWebRequest)WebRequest.Create(Convert.ToString(runtime["url"])+path);
        request.Proxy=null;request.Timeout=5000;request.ReadWriteTimeout=5000;
        request.Headers.Add("X-App-Token",Convert.ToString(runtime["token"]));
        if(body!=null){request.Method="POST";request.ContentType="application/json";byte[] bytes=Encoding.UTF8.GetBytes(body);request.ContentLength=bytes.Length;using(var stream=await request.GetRequestStreamAsync())await stream.WriteAsync(bytes,0,bytes.Length);}
        var operation=request.GetResponseAsync();
        if(await Task.WhenAny(operation,Task.Delay(6000))!=operation){request.Abort();throw new TimeoutException("本机后台响应超时");}
        using(var response=await operation)using(var reader=new StreamReader(response.GetResponseStream()))return NativeClient.Json.Deserialize<Dictionary<string,object>>(await reader.ReadToEndAsync());
    }
    async Task<bool> FindBackendAsync() {
        try {
            runtime=NativeClient.Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(home,"data","runtime.json")));
            var url=new Uri(Convert.ToString(runtime["url"]));
            if(url.Scheme!="http"||url.Host!="127.0.0.1"||url.Port<8765||url.Port>8785)return false;
            var alive=await ApiAsync("/api/state");
            return alive.ContainsKey("state");
        }catch{return false;}
    }
    async Task StartAsync() {
        if(starting)return;starting=true;ShowLifecycle("opening","正在准备你的工作台…");
        try {
            InitializeData();status.Text="正在准备运行环境…";
            bool needsRuntime=false;
            try{CoreWebView2Environment.GetAvailableBrowserVersionString();}
            catch(WebView2RuntimeNotFoundException) {needsRuntime=true;}
            if(needsRuntime) {
                if(smoke)throw new InvalidOperationException("WebView2 Runtime missing");
                if(MessageBox.Show(this,"首次启动需要安装微软 WebView2 运行组件。是否现在安装？","初始化小红帽",MessageBoxButtons.YesNo,MessageBoxIcon.Information)!=DialogResult.Yes)throw new InvalidOperationException("尚未安装客户端运行组件，可稍后重新连接。");
                string bootstrap=Path.Combine(root,"MicrosoftEdgeWebview2Setup.exe");
                var setup=Process.Start(new ProcessStartInfo(bootstrap,"/silent /install"){UseShellExecute=false,CreateNoWindow=true});
                status.Text="正在安装微软客户端组件，请稍候…";await Task.Run(()=>setup.WaitForExit());
                if(setup.ExitCode!=0)throw new InvalidOperationException("WebView2 安装未完成，错误码 "+setup.ExitCode);
                CoreWebView2Environment.GetAvailableBrowserVersionString();
            }
            status.Text="正在连接你的工作台…";
            if(!await FindBackendAsync()) {
                if(child!=null&&!child.HasExited)throw new InvalidOperationException("后台仍在初始化，请稍后重新连接。");
                string python=Path.Combine(root,"python","pythonw.exe");
                if(!File.Exists(python))throw new InvalidOperationException("缺少内置运行环境，请重新安装。");
                var info=new ProcessStartInfo(python,"-X utf8 -u \""+Path.Combine(root,"app.py")+"\" --no-browser"){WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8};
                info.EnvironmentVariables["XIAOHONGMAO_DATA_HOME"]=home;
                if(smoke)info.EnvironmentVariables["XIAOHONGMAO_DESKTOP_SMOKE"]="1";
                child=new Process{StartInfo=info};
                child.OutputDataReceived+=(s,e)=>Log(e.Data);child.ErrorDataReceived+=(s,e)=>Log(e.Data);
                child.Start();child.BeginOutputReadLine();child.BeginErrorReadLine();ownsBackend=true;
                bool ready=false;
                for(int i=0;i<80;i++) {await Task.Delay(250);if(await FindBackendAsync()){ready=true;break;}if(child.HasExited)throw new InvalidOperationException("后台启动失败，请查看数据文件夹内 client-server.log。");}
                if(!ready)throw new TimeoutException("后台初始化超时，可以重新连接。");
            }
            ownsBackend=OwnsCurrentBackend();
            backendOrigin=new Uri(Convert.ToString(runtime["url"])).GetLeftPart(UriPartial.Authority);
            if(view!=null){content.Controls.Remove(view);view.Dispose();}
            view=new WebView2{Dock=DockStyle.Fill};content.Controls.Add(view);splash.BringToFront();
            var environment=await CoreWebView2Environment.CreateAsync(null,Path.Combine(home,"client-webview"));
            await view.EnsureCoreWebView2Async(environment);
            view.CoreWebView2.Settings.AreDevToolsEnabled=false;
            view.CoreWebView2.Settings.AreDefaultContextMenusEnabled=false;
            view.CoreWebView2.Settings.IsStatusBarEnabled=false;
            view.CoreWebView2.Settings.IsWebMessageEnabled=true;
            view.CoreWebView2.Settings.AreHostObjectsAllowed=false;
            await view.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync("window.XIAOHONGMAO_NATIVE=true;window.XIAOHONGMAO_SMOKE="+(smoke?"true":"false")+";");
            view.CoreWebView2.WebMessageReceived+=async(s,e)=>{
                if(!IsLocal(e.Source))return;
                try{var message=NativeClient.Json.Deserialize<Dictionary<string,object>>(e.WebMessageAsJson);
                    if(message.ContainsKey("type")&&Convert.ToString(message["type"])=="install-update")await ApplyUpdateAsync();
                    else if(message.ContainsKey("type")&&Convert.ToString(message["type"])=="platform-login")await RequestPlatformLoginAsync(message.ContainsKey("switch_account")&&message["switch_account"] is bool&&(bool)message["switch_account"]);
                }catch{}
            };
            view.CoreWebView2.NewWindowRequested+=(s,e)=>{e.Handled=true;OpenExternal(e.Uri);};
            view.CoreWebView2.NavigationStarting+=(s,e)=>{if(!IsLocal(e.Uri)&&e.Uri!="about:blank"){e.Cancel=true;OpenExternal(e.Uri);}};
            view.CoreWebView2.DownloadStarting+=(s,e)=>{
                if(smoke){e.Cancel=true;return;}
                using(var dialog=new SaveFileDialog{Title="保存导出文件",FileName=Path.GetFileName(e.ResultFilePath),Filter="所有文件|*.*"}){
                    if(dialog.ShowDialog(this)==DialogResult.OK){e.ResultFilePath=dialog.FileName;e.Handled=true;}
                    else e.Cancel=true;
                }
            };
            view.CoreWebView2.ProcessFailed+=(s,e)=>ShowError("客户端页面进程异常，可点击重新连接恢复。后台记录已保存。");
            if(smoke) {
                view.CoreWebView2.AddWebResourceRequestedFilter("*",CoreWebView2WebResourceContext.All);
                view.CoreWebView2.WebResourceRequested+=(s,e)=>{
                    if(!IsLocal(e.Request.Uri)||e.Request.Method!="GET")e.Response=environment.CreateWebResourceResponse(new MemoryStream(Encoding.UTF8.GetBytes("{\"error\":\"offline client test\"}")),409,"Offline test","Content-Type: application/json");
                };
            }
            view.CoreWebView2.NavigationCompleted+=async(s,e)=>{
                if(!IsLocal(view.CoreWebView2.Source))return;
                if(!e.IsSuccess){ShowError("工作台页面未加载完成："+e.WebErrorStatus);return;}
                for(int i=0;i<80;i++){
                    if(IsDisposed||closing||closeRequested)break;
                    if(await view.CoreWebView2.ExecuteScriptAsync("Boolean(typeof model!=='undefined'&&model?.project&&document.querySelector('#prompt'))")=="true")break;
                    await Task.Delay(75);
                }
                if(!closing&&!closeRequested)splash.Visible=false;
                if(smoke&&!smokeStarted){smokeStarted=true;await RunSmokeAsync();}
                else if(!smoke&&!autoLoginPrompted){autoLoginPrompted=true;await PromptFirstLoginAsync();}
            };
            view.CoreWebView2.Navigate(backendOrigin+"/");
        }catch(Exception ex){ShowError(ex.Message);if(smoke)FinishTest(false,ex.Message);}
        finally{starting=false;if(closeRequested&&!IsDisposed){closeRequested=false;Close();}}
    }
    bool IsLocal(string value) {Uri uri;return Uri.TryCreate(value,UriKind.Absolute,out uri)&&uri.GetLeftPart(UriPartial.Authority)==backendOrigin&&uri.Scheme=="http";}
    void OpenExternal(string value) {
        if(smoke)return;
        Uri uri;if(!Uri.TryCreate(value,UriKind.Absolute,out uri)||(uri.Scheme!="https"&&uri.Scheme!="http"))return;
        try{Process.Start(new ProcessStartInfo(value){UseShellExecute=true});}catch(Exception ex){MessageBox.Show("无法打开链接："+ex.Message,"小红帽");}
    }
    readonly object logLock=new object();
    void Log(string line){if(line==null)return;try{lock(logLock)File.AppendAllText(Path.Combine(home,"client-server.log"),line+Environment.NewLine,Encoding.UTF8);}catch{}}
    void ShowError(string text){ShowLifecycle("error",text);}
    bool IsOfficialLoginUrl(string value) {
        Uri uri;return Uri.TryCreate(value,UriKind.Absolute,out uri)&&uri.Scheme=="https"&&
            (uri.Host=="xiaohongshu.com"||uri.Host.EndsWith(".xiaohongshu.com",StringComparison.OrdinalIgnoreCase));
    }
    async Task PromptFirstLoginAsync() {
        try {
            await Task.Delay(900);if(IsDisposed||closing||allowClose)return;
            var state=(Dictionary<string,object>)(await ApiAsync("/api/state"))["state"];
            if(Convert.ToString(state["login"])!="ready")await ShowPlatformLoginAsync();
        }catch{}
    }
    void HidePlatformLogin() {
        if(loginTimer!=null){loginTimer.Stop();loginTimer.Dispose();loginTimer=null;}
        var panel=loginPanel;loginPanel=null;loginView=null;loginLastAttempt="";
        if(panel!=null){content.Controls.Remove(panel);panel.Dispose();}
    }
    async Task<List<Dictionary<string,object>>> LoginCookiesAsync(WebView2 browser) {
        if(!IsOfficialLoginUrl(browser.CoreWebView2.Source))throw new InvalidOperationException("请先回到小红书官方登录页。");
        var result=new List<Dictionary<string,object>>();
        foreach(var cookie in await browser.CoreWebView2.CookieManager.GetCookiesAsync("https://www.xiaohongshu.com")){
            string domain=cookie.Domain.TrimStart('.').ToLowerInvariant();
            if(domain!="xiaohongshu.com"&&domain!="www.xiaohongshu.com")continue;
            result.Add(new Dictionary<string,object>{{"name",cookie.Name},{"value",cookie.Value},{"domain",cookie.Domain},{"path",cookie.Path},
                {"httpOnly",cookie.IsHttpOnly},{"secure",cookie.IsSecure},{"sameSite",cookie.SameSite.ToString()},
                {"expires",cookie.IsSession?-1:(cookie.Expires.ToUniversalTime()-new DateTime(1970,1,1,0,0,0,DateTimeKind.Utc)).TotalSeconds}});
        }
        if(!result.Exists(c=>Convert.ToString(c["name"])=="web_session"&&!String.IsNullOrEmpty(Convert.ToString(c["value"]))))
            throw new InvalidOperationException("请先扫码或完成手机号验证，完成后会自动连接。");
        return result;
    }
    async Task<string> LoginProfileAsync(WebView2 browser) {
        if(!IsOfficialLoginUrl(browser.CoreWebView2.Source))throw new InvalidOperationException("请先回到小红书官方登录页。");
        string result=await browser.CoreWebView2.ExecuteScriptAsync("(()=>{const a=[...document.querySelectorAll('a[href*=\"/user/profile/\"]')].find(a=>(a.textContent||'').trim()==='我'&&a.getBoundingClientRect().width>0);return a?'https://www.xiaohongshu.com'+new URL(a.href).pathname:''})()");
        string profile=NativeClient.Json.Deserialize<string>(result);
        if(String.IsNullOrEmpty(profile))throw new InvalidOperationException("尚未读到账号身份，请先完成扫码或手机号验证，再连接工作台。");
        return profile;
    }
    bool OwnsCurrentBackend() {
        try{return ownsBackend&&child!=null&&!child.HasExited&&runtime!=null&&Convert.ToInt32(runtime["pid"])==child.Id;}
        catch{return false;}
    }
    async Task<bool> StopOwnedBackendAsync() {
        if(!OwnsCurrentBackend()){
            // The spawned process may still be initializing. Keep its host alive
            // until it can be identified; never send shutdown to a replacement.
            if(ownsBackend&&child!=null&&!child.HasExited)return false;
            ownsBackend=false;return true;
        }
        try{await ApiAsync("/api/command","{\"command\":\"shutdown\"}");}catch{if(child!=null&&child.HasExited)return true;if(!updateInProgress)return false;}
        for(int i=0;i<200;i++){if(child!=null&&child.HasExited){ownsBackend=false;return true;}await Task.Delay(500);}
        return false;
    }
    async void OnClosing(object sender,FormClosingEventArgs e) {
        if(allowClose)return;e.Cancel=true;
        if(starting){closeRequested=true;ShowLifecycle("closing","正在完成初始化，随后安全退出…");return;}
        if(closing)return;closing=true;
        try {
            if(ownsBackend&&!smoke&&!updateInProgress) {
                try{
                    var response=await ApiAsync("/api/state");var state=(Dictionary<string,object>)response["state"];
                    if(Convert.ToString(state["task"])!="idle"&&MessageBox.Show(this,"任务仍在进行。退出会请求暂停并等待后台保存记录。是否退出？","退出小红帽",MessageBoxButtons.YesNo,MessageBoxIcon.Question,MessageBoxDefaultButton.Button2)!=DialogResult.Yes)return;
                }catch{}
                ShowLifecycle("closing","正在结束后台操作，保存执行记录…");
            }
            if(!await StopOwnedBackendAsync()){
                if(smoke){FinishTest(false,"Graceful shutdown did not complete");return;}
                MessageBox.Show(this,"后台还没有完成退出。客户端将保持打开，请等待当前操作结束后再退出。","小红帽");return;
            }
            allowClose=true;Close();
        }finally{closing=false;}
    }
    async Task RunSmokeAsync() {
        try {
            for(int i=0;i<60;i++){
                if(await view.CoreWebView2.ExecuteScriptAsync("Boolean(document.querySelector('#prompt') && typeof model !== 'undefined' && model?.project && document.querySelector('#settings')?.onclick)")=="true")break;
                await Task.Delay(250);
            }
            string valid=await view.CoreWebView2.ExecuteScriptAsync("document.title.includes('小红帽') && !!document.querySelector('#prompt') && !!document.querySelector('#settings')");
            if(valid!="true")throw new InvalidOperationException("Client workbench UI missing");testChecks.Add("native WebView2 workbench rendered");
            if(content.Top<menu.Bottom||view.Top!=0)throw new InvalidOperationException("Native menu overlaps workbench");testChecks.Add("native menu and workbench do not overlap");
            await view.CoreWebView2.ExecuteScriptAsync("openSettings('ai')");
            if(await view.CoreWebView2.ExecuteScriptAsync("!document.querySelector('#settings-page').hidden")!="true")throw new InvalidOperationException("Settings dialog did not open");
            await view.CoreWebView2.ExecuteScriptAsync("closeSettings()");testChecks.Add("workbench settings opens and closes");
            using(var file=File.Create(Path.Combine(home,"client-workbench.png")))await view.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png,file);
            await ShowPlatformLoginAsync(true);
            for(int i=0;i<60;i++){if(loginView.CoreWebView2!=null&&IsOfficialLoginUrl(loginView.CoreWebView2.Source)&&loginPageReady)break;await Task.Delay(100);}
            if(loginView.CoreWebView2==null||!loginPageReady)throw new InvalidOperationException("Embedded official login fixture did not load");
            var testCookie=loginView.CoreWebView2.CookieManager.CreateCookie("web_session","offline-login-fixture",".xiaohongshu.com","/");
            testCookie.IsHttpOnly=true;testCookie.IsSecure=true;loginView.CoreWebView2.CookieManager.AddOrUpdateCookie(testCookie);
            var loginCookies=await LoginCookiesAsync(loginView);
            if(await LoginProfileAsync(loginView)!="https://www.xiaohongshu.com/user/profile/FixtureOwner")throw new InvalidOperationException("Official login account identity bridge failed");
            if(!loginCookies.Exists(c=>Convert.ToString(c["name"])=="web_session"&&Convert.ToBoolean(c["httpOnly"])))throw new InvalidOperationException("Official login session bridge failed");
            loginCookies.Clear();
            if(await loginView.CoreWebView2.ExecuteScriptAsync("getComputedStyle(document.querySelector('#fixture-feed')).visibility==='hidden'&&getComputedStyle(document.querySelector('.login-container')).visibility==='visible'")!="true")throw new InvalidOperationException("Login feed masking failed");
            using(var file=File.Create(Path.Combine(home,"client-login.png")))await loginView.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png,file);
            await CheckPlatformLoginAsync();if(!loginDetected)throw new InvalidOperationException("Login auto detection failed");
            testChecks.Add("official login only: feed hidden, login visible, automatic identity detection");
            HidePlatformLogin();testChecks.Add("embedded official login and local HttpOnly session bridge (offline fixture)");
            var response=await ApiAsync("/api/state");var state=(Dictionary<string,object>)response["state"];
            if(Convert.ToString(state["task"])!="idle")throw new InvalidOperationException("Self-test unexpectedly started work");testChecks.Add("offline UI test: no browser task or paid calls");
            bool wasOwner=ownsBackend;
            if(!await StopOwnedBackendAsync())throw new InvalidOperationException("Graceful shutdown failed");testChecks.Add(wasOwner?"owned backend shuts down cleanly":"pre-existing backend preserved");
            FinishTest(true,"");
        }catch(Exception ex){FinishTest(false,ex.Message);}
    }
    void FinishTest(bool ok,string error) {
        if(testTimer!=null)testTimer.Stop();
        File.WriteAllText(Path.Combine(home,"desktop-test.json"),NativeClient.Json.Serialize(new {ok=ok,error=error,checks=testChecks}));
        Environment.ExitCode=ok?0:1;allowClose=true;Close();
    }
}
