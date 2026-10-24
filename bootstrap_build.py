"""Prepare a clean Windows build from official dependencies; no user runtime data."""
import hashlib,shutil,subprocess,sys,urllib.request,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
def download(url,dest,digest=None):
    dest.parent.mkdir(parents=True,exist_ok=True)
    if not dest.exists():urllib.request.urlretrieve(url,dest)
    if digest and hashlib.sha256(dest.read_bytes()).hexdigest()!=digest:raise RuntimeError('依赖文件校验失败：'+dest.name)

def main():
    if sys.version_info[:2]!=(3,11):raise RuntimeError('构建请使用 Python 3.11 x64')
    subprocess.run([sys.executable,'-m','pip','install','--target',str(ROOT/'.runtime'),'-r',str(ROOT/'requirements.txt')],check=True)
    download('https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip',ROOT/'build-tools/python-3.11.9-embed-amd64.zip','009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b')
    sdk=ROOT/'build-tools/webview2';package=sdk/'microsoft.web.webview2.1.0.4258.31.nupkg'
    download('https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/1.0.4258.31',package,'56f7f4b8bf9aee4b8efefbbdd4f67d5f74ebd1b100ed0806da71bf76af481aa9')
    with zipfile.ZipFile(package) as z:
        for source,target in [('lib/net462/Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.Core.dll'),('lib/net462/Microsoft.Web.WebView2.WinForms.dll','Microsoft.Web.WebView2.WinForms.dll'),('runtimes/win-x64/native/WebView2Loader.dll','WebView2Loader.dll')]:
            (sdk/target).write_bytes(z.read(source))
    bootstrap=sdk/'MicrosoftEdgeWebview2Setup.exe'
    download('https://go.microsoft.com/fwlink/p/?LinkId=2124703',bootstrap)
    command="$s=Get-AuthenticodeSignature -LiteralPath '"+str(bootstrap).replace("'","''")+"';if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'Microsoft Corporation'){throw 'Invalid Microsoft signature'}"
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],check=True)
    print('Official build dependencies prepared. Inno Setup 6 must also be installed.')

if __name__=='__main__':main()
