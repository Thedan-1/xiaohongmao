using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
class PreviewEntry {
 [STAThread] static void Main(string[] args) {
  string root=AppDomain.CurrentDomain.BaseDirectory;
  string name="app";
  string pointer=Path.Combine(root,"current-app.txt");
  if(File.Exists(pointer)) {
   name=File.ReadAllText(pointer).Trim();
   if(!System.Text.RegularExpressions.Regex.IsMatch(name,@"^app(?:-[0-9A-Za-z.-]+)?$")){MessageBox.Show("预览版本信息有误，请重新完整解压预览版。","小红帽预览");return;}
  }
  string app=Path.Combine(root,name);
  string exe=Path.Combine(app,"小红帽.exe");
  if(!File.Exists(exe)){MessageBox.Show("请先完整解压预览版，再双击“小红帽预览.exe”。","小红帽预览");return;}
  try{
   var info=new ProcessStartInfo(exe,"--preview"){WorkingDirectory=app,UseShellExecute=false};
   info.EnvironmentVariables.Remove("XIAOHONGMAO_DATA_HOME");
   info.EnvironmentVariables.Remove("XIAOHONGMAO_DESKTOP_SMOKE");
   Process.Start(info);
  }catch(Exception ex){MessageBox.Show("启动失败："+ex.Message,"小红帽预览");}
 }
}
