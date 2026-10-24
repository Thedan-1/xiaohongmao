using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Windows.Forms;
using System.Runtime.InteropServices;

// Drawn by the native client: available before WebView2 and the backend start.
class LifecycleSurface:Panel {
    [DllImport("user32.dll",SetLastError=true)]static extern bool SystemParametersInfo(uint action,uint param,[MarshalAs(UnmanagedType.Bool)]ref bool enabled,uint flags);
    readonly Timer motion;
    int frame;
    string phase="opening",message="正在准备你的工作台…";
    public Button Primary,Secondary;
    public string Phase {get{return phase;}}
    public string Message {get{return message;}set{message=value??"";Invalidate();}}
    public Rectangle SceneBounds {get{return new Rectangle((Width-520)/2,(Height-370)/2,520,370);}}

    public LifecycleSurface() {
        SetStyle(ControlStyles.AllPaintingInWmPaint|ControlStyles.UserPaint|ControlStyles.OptimizedDoubleBuffer|ControlStyles.ResizeRedraw,true);
        BackColor=Color.FromArgb(253,252,253);
        motion=new Timer{Interval=40};motion.Tick+=(s,e)=>{frame=(frame+1)%1200;Invalidate();};
    }
    public void SetPhase(string value){phase=value;UpdateMotion();PerformLayout();Invalidate();}
    void UpdateMotion(){bool enabled=true;SystemParametersInfo(0x1042,0,ref enabled,0);motion.Enabled=Visible&&phase!="error"&&enabled;}
    protected override void OnVisibleChanged(EventArgs e){base.OnVisibleChanged(e);UpdateMotion();PerformLayout();}
    protected override void Dispose(bool disposing){if(disposing)motion.Dispose();base.Dispose(disposing);}
    internal static GraphicsPath Round(RectangleF r,float radius) {
        float d=Math.Min(radius*2,Math.Min(r.Width,r.Height));var p=new GraphicsPath();
        p.AddArc(r.Left,r.Top,d,d,180,90);p.AddArc(r.Right-d,r.Top,d,d,270,90);
        p.AddArc(r.Right-d,r.Bottom-d,d,d,0,90);p.AddArc(r.Left,r.Bottom-d,d,d,90,90);p.CloseFigure();return p;
    }
    protected override void OnLayout(LayoutEventArgs e) {
        base.OnLayout(e);int y=SceneBounds.Top+302;
        bool a=Primary!=null&&Primary.Visible,b=Secondary!=null&&Secondary.Visible;
        int total=(a?132:0)+(b?112:0)+(a&&b?12:0),x=(Width-total)/2;
        if(a){Primary.SetBounds(x,y,132,40);x+=144;}
        if(b)Secondary.SetBounds(x,y,112,40);
    }
    void TextLine(Graphics g,string text,Font font,Color color,RectangleF box) {
        using(var brush=new SolidBrush(color))using(var format=new StringFormat{Alignment=StringAlignment.Center,LineAlignment=StringAlignment.Center,Trimming=StringTrimming.EllipsisCharacter})
            g.DrawString(text,font,brush,box,format);
    }
    protected override void OnPaint(PaintEventArgs e) {
        base.OnPaint(e);var g=e.Graphics;g.SmoothingMode=SmoothingMode.AntiAlias;g.TextRenderingHint=TextRenderingHint.ClearTypeGridFit;
        float cx=Width/2f,top=SceneBounds.Top;Color red=Color.FromArgb(255,36,66),ink=Color.FromArgb(35,35,42),muted=Color.FromArgb(137,135,147);
        // A restrained blush behind the mark, with no image/network dependency.
        using(var halo=new GraphicsPath()) {
            halo.AddEllipse(cx-130,top-70,260,260);
            using(var glow=new PathGradientBrush(halo)){glow.CenterColor=Color.FromArgb(255,233,239);glow.SurroundColors=new[]{BackColor};g.FillPath(glow,halo);}
        }
        var tile=new RectangleF(cx-34,top+26,68,68);
        for(int n=5;n>=1;n--)using(var path=Round(new RectangleF(tile.X-n,tile.Y+4-n,tile.Width+2*n,tile.Height+2*n),22+n))using(var brush=new SolidBrush(Color.FromArgb(3,255,36,66)))g.FillPath(brush,path);
        using(var path=Round(tile,21))using(var brush=new LinearGradientBrush(tile,Color.FromArgb(255,65,91),red,90))g.FillPath(brush,path);
        var saved=g.Save();g.TranslateTransform(tile.X+12,tile.Y+11);g.ScaleTransform(1.38f,1.38f);
        using(var hat=new GraphicsPath())using(var white=new SolidBrush(Color.White)) {
            hat.AddBezier(9,20,9.5f,13.8f,11.6f,9.5f,16,9.5f);hat.AddBezier(16,9.5f,20.4f,9.5f,22.5f,13.8f,23,20);hat.CloseFigure();g.FillPath(white,hat);
            using(var brim=Round(new RectangleF(5,20,22,4),2))g.FillPath(white,brim);
            using(var band=new Pen(Color.FromArgb(255,113,133),1.1f)){band.StartCap=band.EndCap=LineCap.Round;g.DrawLine(band,12,17.8f,20,17.8f);}
        }
        g.Restore(saved);
        using(var title=new Font("Microsoft YaHei UI",23,FontStyle.Bold))using(var sub=new Font("Microsoft YaHei UI",10.5f))using(var label=new Font("Microsoft YaHei UI",10))using(var foot=new Font("Microsoft YaHei UI",9)) {
            TextLine(g,phase=="closing"?"正在退出小红帽":phase=="error"?"连接暂未完成":"小红帽",title,ink,new RectangleF(20,top+115,Width-40,48));
            TextLine(g,phase=="closing"?"正在结束后台连接，请稍候":phase=="error"?"处理完成后，可以从这里继续":"从一个话题，发现新的可能",sub,muted,new RectangleF(20,top+166,Width-40,32));
            float w=Math.Min(500,Width-64);
            TextLine(g,message,label,phase=="error"?Color.FromArgb(177,62,80):Color.FromArgb(94,90,104),new RectangleF(cx-w/2,top+221,w,62));
            if(phase!="error") {
                var track=new RectangleF(cx-78,top+304,156,3);
                using(var p=Round(track,1.5f))using(var b=new SolidBrush(Color.FromArgb(239,233,238)))g.FillPath(b,p);
                float t=motion.Enabled?(float)((Math.Sin(frame*.075-Math.PI/2)+1)/2):.5f;
                using(var p=Round(new RectangleF(track.X+112*t,track.Y,44,3),1.5f))using(var b=new SolidBrush(red))g.FillPath(b,p);
            }
            TextLine(g,phase=="closing"?"请等待窗口自动关闭":"本机运行 · 项目记录保存在本机",foot,Color.FromArgb(165,160,171),new RectangleF(20,Height-58,Width-40,28));
        }
    }
}

class LifecycleButton:Button {
    public bool Accent;
    bool hovered;
    public LifecycleButton(){SetStyle(ControlStyles.UserPaint|ControlStyles.AllPaintingInWmPaint|ControlStyles.OptimizedDoubleBuffer,true);FlatStyle=FlatStyle.Flat;FlatAppearance.BorderSize=0;Cursor=Cursors.Hand;Font=new Font("Microsoft YaHei UI",9.5f);}
    protected override void OnMouseEnter(EventArgs e){hovered=true;Invalidate();base.OnMouseEnter(e);}
    protected override void OnMouseLeave(EventArgs e){hovered=false;Invalidate();base.OnMouseLeave(e);}
    protected override void OnPaint(PaintEventArgs e){
        var g=e.Graphics;g.Clear(Parent==null?Color.White:Parent.BackColor);g.SmoothingMode=SmoothingMode.AntiAlias;
        using(var p=LifecycleSurface.Round(new RectangleF(1,1,Width-2,Height-2),12)) {
            using(var b=new SolidBrush(Accent?(hovered?Color.FromArgb(234,24,55):Color.FromArgb(255,36,66)):(hovered?Color.FromArgb(245,241,245):Color.White)))g.FillPath(b,p);
            if(!Accent)using(var pen=new Pen(Color.FromArgb(231,226,233)))g.DrawPath(pen,p);
        }
        TextRenderer.DrawText(g,Text,Font,ClientRectangle,Accent?Color.White:Color.FromArgb(91,84,101),TextFormatFlags.HorizontalCenter|TextFormatFlags.VerticalCenter);
        if(Focused)ControlPaint.DrawFocusRectangle(g,new Rectangle(6,6,Width-12,Height-12));
    }
}

partial class ClientForm {
    LifecycleSurface lifecycle;
    void CreateLifecycle() {
        lifecycle=new LifecycleSurface{Dock=DockStyle.Fill};splash=lifecycle;
        status=new Label{Text="正在准备你的工作台…",Visible=false};
        status.TextChanged+=(s,e)=>lifecycle.Message=closeRequested?"正在完成初始化，随后安全退出…":status.Text;
        retry=new LifecycleButton{Text="重新连接",Accent=true,Visible=false};retry.Click+=async(s,e)=>await StartAsync();
        settings=new LifecycleButton{Text="AI 设置",Visible=false};settings.Click+=(s,e)=>ShowSettings();
        lifecycle.Primary=retry;lifecycle.Secondary=settings;
        lifecycle.Controls.AddRange(new Control[]{status,retry,settings});content.Controls.Add(splash);splash.BringToFront();
    }
    void ShowLifecycle(string phase,string text) {
        lifecycle.SetPhase(phase);status.Text=text;lifecycle.Message=text;
        retry.Visible=settings.Visible=phase=="error";
        splash.Visible=true;splash.BringToFront();lifecycle.PerformLayout();
    }
}
