"""Render the real native loading/closing surface without starting the app."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent
PROBE=r'''
using System;using System.IO;using System.Drawing;using System.Windows.Forms;
class RenderLifecycle {
 [STAThread]static void Main(string[] args){
  Application.EnableVisualStyles();
  foreach(string mode in new[]{"opening","closing","error","small"})using(var surface=new LifecycleSurface()){
   bool small=mode=="small";surface.Size=small?new Size(940,600):new Size(1364,812);
   surface.Font=new Font("Microsoft YaHei UI",10);
   if(mode=="error"){
    surface.Primary=new LifecycleButton{Text="重新连接",Accent=true};surface.Secondary=new LifecycleButton{Text="AI 设置"};
    surface.Controls.AddRange(new Control[]{surface.Primary,surface.Secondary});
   }
   surface.SetPhase(mode=="small"?"opening":mode);
   surface.Message=mode=="closing"?"正在结束后台操作，保存执行记录…":mode=="error"?"工作台暂时没有响应，请检查后重新连接。":"正在连接你的工作台…";
   surface.CreateControl();surface.PerformLayout();
   if(!surface.ClientRectangle.Contains(surface.SceneBounds))throw new Exception("Centered scene outside viewport");
   if(surface.Primary!=null&&(!surface.ClientRectangle.Contains(surface.Primary.Bounds)||!surface.ClientRectangle.Contains(surface.Secondary.Bounds)))throw new Exception("Actions outside viewport");
   using(var bitmap=new Bitmap(surface.Width,surface.Height)){surface.DrawToBitmap(bitmap,surface.ClientRectangle);bitmap.Save(Path.Combine(args[0],mode+".png"));}
  }
  File.WriteAllText(Path.Combine(args[0],"result.json"),"{\"rendered\":4,\"centered\":true,\"actions_visible\":true}");
 }
}
'''

class LifecycleDesignTests(unittest.TestCase):
    def test_open_close_error_and_small_window_render(self):
        output=ROOT/'data/desktop-qa/lifecycle-v063';output.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='xhm-lifecycle-render-') as tmp:
            folder=Path(tmp);source=folder/'Render.cs';source.write_text(PROBE,encoding='utf-8')
            sdk=ROOT/'build-tools/webview2'
            names=['Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll']
            for name in names:shutil.copy2(sdk/name,folder/name)
            cmd=[r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe','/nologo','/utf8output','/target:exe','/platform:x64','/main:RenderLifecycle','/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.Web.Extensions.dll','/out:'+str(folder/'Render.exe')]
            cmd+=['/reference:'+str(folder/n) for n in names]
            cmd+=[str(ROOT/'build-tools'/n) for n in ['NativeClient.cs','NativeLogin.cs','NativeLifecycle.cs']]+[str(source)]
            p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8');self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(folder/'Render.exe'),str(output)],capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW);self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads((output/'result.json').read_text())['rendered'],4)
        for name in ['opening','closing','error','small']:self.assertGreater((output/(name+'.png')).stat().st_size,5000)

if __name__=='__main__':unittest.main()
