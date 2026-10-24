using System;using System.Collections.Generic;using System.Drawing;using System.IO;
using System.Net;using System.Security.Cryptography;using System.Text;
using System.Threading.Tasks;using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;using Microsoft.Web.WebView2.WinForms;

partial class ClientForm {
    System.Windows.Forms.Timer loginTimer;
    bool loginSyncing,loginDetected,resetNextLogin;
    string loginLastAttempt="";
    Button loginBack;
    bool loginPageReady;
    Label loginWaiting;

    void StartLoginPolling() {
        if(loginTimer!=null||loginPanel==null)return;
        loginTimer=new System.Windows.Forms.Timer{Interval=1500};
        loginTimer.Tick+=async(s,e)=>await CheckPlatformLoginAsync();loginTimer.Start();
    }

    async Task OpenPlatformAccountAsync() {
        bool change=false;
        try {
            var state=(Dictionary<string,object>)(await ApiAsync("/api/state"))["state"];
            change=Convert.ToString(state["login"])=="ready";
        }catch{}
        await RequestPlatformLoginAsync(change);
    }

    async Task RequestPlatformLoginAsync(bool switchAccount=false) {
        resetNextLogin=switchAccount;
        await ShowPlatformLoginAsync();
    }
    async Task ResetPlatformLoginAsync() {
        if(loginSyncing||loginView==null||loginView.CoreWebView2==null)return;
        try {
            loginView.CoreWebView2.CookieManager.DeleteAllCookies();
            if(IsOfficialLoginUrl(loginView.CoreWebView2.Source))await loginView.CoreWebView2.ExecuteScriptAsync("localStorage.clear();sessionStorage.clear();");
            loginLastAttempt="";loginDetected=false;
            if(loginWaiting!=null)loginWaiting.Visible=false;
            loginStatus.Text="请在官方登录框登录新的账号，完成后会自动进入工作台。";
            loginView.CoreWebView2.Navigate("https://www.xiaohongshu.com/explore");
        }catch{loginStatus.Text="登录页暂未就绪，请稍后再试。";}
    }
    async Task CheckPlatformLoginAsync(bool retry=false) {
        if(loginSyncing||loginPanel==null||loginView==null||loginView.CoreWebView2==null||IsDisposed||closing||allowClose)return;
        var panel=loginPanel;var browser=loginView;var hint=loginStatus;
        loginSyncing=true;bool submitted=false;
        if(retry){hint.Text="正在检测登录，请稍候…";hint.Visible=true;hint.BringToFront();loginBack.Enabled=false;}
        try {
            string expected;
            List<Dictionary<string,object>> cookies;
            try {expected=await LoginProfileAsync(browser);cookies=await LoginCookiesAsync(browser);}
            catch{if(retry&&!panel.IsDisposed)hint.Text="尚未检测到完整登录状态，请完成官方登录后再检测。";return;}
            if(panel.IsDisposed||loginPanel!=panel)return;
            string token=Convert.ToString(cookies.Find(c=>Convert.ToString(c["name"])=="web_session")["value"]);
            string signature;using(var sha=SHA256.Create())signature=Convert.ToBase64String(sha.ComputeHash(Encoding.UTF8.GetBytes(expected+"\n"+token)));
            token=null;
            if(!retry&&signature==loginLastAttempt){cookies.Clear();return;}
            if(smoke){loginDetected=true;cookies.Clear();hint.Text="离线测试已自动识别账号，不连接真实账号。";return;}
            var state=(Dictionary<string,object>)(await ApiAsync("/api/state"))["state"];
            if(Convert.ToString(state["task"])!="idle"){
                cookies.Clear();hint.Text="正在等待当前任务结束，随后检测登录。";return;
            }
            if(state.ContainsKey("login")&&Convert.ToString(state["login"])=="restricted"&&!retry){
                cookies.Clear();hint.Text="平台提示安全限制。请先按官方提示处理，再重新检测。";return;
            }
            loginLastAttempt=signature;submitted=true;
            loginBack.Enabled=false;
            hint.Text="正在检测登录：连接后台并核对实际账号…";
            loginWaiting.Text=hint.Text+"\n核验通过后将自动进入工作台。";
            loginWaiting.Visible=true;loginWaiting.BringToFront();
            string transfer=Guid.NewGuid().ToString();
            await ApiAsync("/api/command",NativeClient.Json.Serialize(new {command="login_session",transfer_id=transfer,expected_profile=expected,cookies=cookies}));
            cookies.Clear();
            for(int i=0;i<180;i++){
                await Task.Delay(500);if(panel.IsDisposed||loginPanel!=panel||IsDisposed)return;
                state=(Dictionary<string,object>)(await ApiAsync("/api/state"))["state"];
                if(!state.ContainsKey("login_transfer_id")||Convert.ToString(state["login_transfer_id"])!=transfer)continue;
                string phase=Convert.ToString(state["login_transfer_status"]);
                if(phase=="failed")throw new InvalidOperationException(Convert.ToString(state["message"]));
                if(phase=="complete"){
                    if(!state.ContainsKey("login")||Convert.ToString(state["login"])!="ready"||!state.ContainsKey("login_verified_profile")||Convert.ToString(state["login_verified_profile"])!=expected)
                        throw new InvalidOperationException("后台尚未完成当前账号核验，未进入工作台。请重新检测。");
                    loginDetected=true;
                    HidePlatformLogin();
                    if(view!=null&&view.CoreWebView2!=null)await view.CoreWebView2.ExecuteScriptAsync("if(typeof refresh==='function')refresh();");
                    return;
                }
                if(state.ContainsKey("message")){hint.Text=Convert.ToString(state["message"]);loginWaiting.Text=hint.Text+"\n核验通过后将自动进入工作台。";}
            }
            throw new TimeoutException("核对尚未完成，登录资料已保留。请稍后重新检测。");
        }catch(Exception ex){
            if(!panel.IsDisposed&&loginPanel==panel){
                hint.Text=ex is WebException?"工作台暂时忙，请稍后重新检测。":ex.Message;
                if(loginWaiting!=null&&loginWaiting.Visible)loginWaiting.Text=hint.Text+"\n已有登录资料会保留。返回工作台后，可从个人设置重新打开登录。";
            }
        }finally{
            loginSyncing=false;
            if((submitted||retry)&&!panel.IsDisposed&&loginPanel==panel)loginBack.Enabled=true;
        }
    }
    async Task ShowPlatformLoginAsync(bool fixture=false) {
        if(IsDisposed||allowClose||(smoke&&!fixture))return;
        if(loginPanel!=null){loginPanel.BringToFront();if(resetNextLogin){resetNextLogin=false;await ResetPlatformLoginAsync();}return;}
        bool reset=resetNextLogin;resetNextLogin=false;
        loginLastAttempt="";loginDetected=false;loginPageReady=false;
        var panel=new Panel{Dock=DockStyle.Fill,BackColor=Color.FromArgb(250,249,252)};loginPanel=panel;
        var header=new TableLayoutPanel{Dock=DockStyle.Top,AutoSize=true,ColumnCount=2,RowCount=1,Padding=new Padding(24,16,24,14),BackColor=Color.White};
        header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));header.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        var headings=new FlowLayoutPanel{AutoSize=true,AutoSizeMode=AutoSizeMode.GrowAndShrink,FlowDirection=FlowDirection.TopDown,WrapContents=false,Anchor=AnchorStyles.Left};
        headings.Controls.Add(new Label{Text="连接你的小红书账号",AutoSize=true,Font=new Font(Font.FontFamily,16,FontStyle.Bold),Margin=new Padding(0,0,0,5)});
        headings.Controls.Add(new Label{Text="小红书官方登录页 · https://www.xiaohongshu.com",AutoSize=true,ForeColor=Color.FromArgb(137,123,141),Margin=new Padding(0)});
        var back=new Button{Text="返回工作台",AutoSize=true,MinimumSize=new Size(104,34),Anchor=AnchorStyles.Right};loginBack=back;
        back.Click+=(s,e)=>HidePlatformLogin();header.Controls.Add(headings,0,0);header.Controls.Add(back,1,0);
        var browser=new WebView2{Dock=DockStyle.Fill,Margin=new Padding(0)};loginView=browser;
        var body=new Panel{Dock=DockStyle.Fill};body.Controls.Add(browser);
        loginWaiting=new Label{Text="正在打开官方登录框…",Dock=DockStyle.Fill,Visible=true,TextAlign=ContentAlignment.MiddleCenter,BackColor=panel.BackColor,ForeColor=Color.FromArgb(90,76,96),Font=new Font(Font.FontFamily,13)};
        loginStatus=loginWaiting;var hint=loginWaiting;
        body.Controls.Add(loginWaiting);
        panel.Controls.Add(body);panel.Controls.Add(header);header.SendToBack();
        content.Controls.Add(panel);panel.BringToFront();
        try {
            var environment=await CoreWebView2Environment.CreateAsync(null,Path.Combine(home,"platform-webview"));
            if(panel.IsDisposed)return;
            await browser.EnsureCoreWebView2Async(environment);if(panel.IsDisposed)return;
            browser.CoreWebView2.Settings.AreDevToolsEnabled=false;browser.CoreWebView2.Settings.IsWebMessageEnabled=false;
            browser.CoreWebView2.Settings.AreHostObjectsAllowed=false;browser.CoreWebView2.Settings.AreDefaultContextMenusEnabled=false;
            browser.CoreWebView2.Settings.IsStatusBarEnabled=false;
            string focus=File.ReadAllText(Path.Combine(root,"login-focus.js"),Encoding.UTF8);
            await browser.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(focus);
            browser.CoreWebView2.DOMContentLoaded+=async(s,e)=>{
                if(panel.IsDisposed)return;
                loginPageReady=true;
                if(!loginSyncing){hint.Text="官方登录组件正在就绪；完成登录后会自动检测。";hint.Visible=false;}
                StartLoginPolling();
                try{await browser.CoreWebView2.ExecuteScriptAsync(focus);}catch{}
            };
            browser.CoreWebView2.NavigationStarting+=(s,e)=>{if(!IsOfficialLoginUrl(e.Uri)&&e.Uri!="about:blank"){e.Cancel=true;hint.Text="请在小红书官方登录页完成验证。";}};
            browser.CoreWebView2.NewWindowRequested+=(s,e)=>{e.Handled=true;if(IsOfficialLoginUrl(e.Uri))browser.CoreWebView2.Navigate(e.Uri);};
            browser.CoreWebView2.DownloadStarting+=(s,e)=>e.Cancel=true;
            browser.CoreWebView2.PermissionRequested+=(s,e)=>e.State=CoreWebView2PermissionState.Deny;
            if(fixture){
                browser.CoreWebView2.AddWebResourceRequestedFilter("*",CoreWebView2WebResourceContext.All);
                browser.CoreWebView2.WebResourceRequested+=(s,e)=>e.Response=environment.CreateWebResourceResponse(new MemoryStream(Encoding.UTF8.GetBytes("<!doctype html><meta charset='utf-8'><title>Official login fixture</title><div id='fixture-feed'><a href='/user/profile/FixtureOwner'>我</a><h1>不应显示的推荐内容</h1></div><div class='login-modal'><div class='login-container' style='background:white;width:640px;height:320px;padding:24px'><h2>官方登录测试</h2><input placeholder='手机号'><p>扫码或手机号登录</p></div></div>")),200,"OK","Content-Type: text/html; charset=utf-8");
            }
            if(reset)browser.CoreWebView2.CookieManager.DeleteAllCookies();
            browser.CoreWebView2.NavigationCompleted+=async(s,e)=>{
                if(panel.IsDisposed)return;
                loginPageReady=e.IsSuccess;
                if(!loginSyncing)hint.Text=e.IsSuccess?"完成官方扫码或手机号登录后，将自动检测并进入工作台。":"官方登录页未加载完成，请返回后重试。";
                if(!e.IsSuccess){hint.Visible=true;hint.BringToFront();return;}
                if(!loginSyncing)hint.Visible=false;
                try {
                    if(reset){reset=false;await browser.CoreWebView2.ExecuteScriptAsync("localStorage.clear();sessionStorage.clear();location.reload();");return;}
                    bool restricted=await browser.CoreWebView2.ExecuteScriptAsync("location.pathname.includes('/website-login/error')||document.title.includes('安全限制')")=="true";
                    if(restricted){hint.Text="小红书提示安全限制，请按官方提示处理。";hint.Visible=true;hint.BringToFront();return;}
                    await browser.CoreWebView2.ExecuteScriptAsync(focus);
                    StartLoginPolling();
                    await CheckPlatformLoginAsync();
                }catch{if(!panel.IsDisposed)hint.Text="正在等待官方登录页就绪…";}
            };
            browser.CoreWebView2.Navigate("https://www.xiaohongshu.com/explore");
        }catch(Exception ex){if(!panel.IsDisposed){hint.Text="登录页打开失败："+ex.Message;hint.Visible=true;hint.BringToFront();}}
    }
}
