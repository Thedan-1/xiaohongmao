"""Build the native Windows client payload, excluding every user's runtime data."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import zipfile
import tempfile
import release_config
import build_portable

ROOT=Path(__file__).resolve().parent
STAGE=ROOT/'release/小红帽-Windows-x64-v0.6'
SDK=ROOT/'build-tools/webview2'

def build():
    import build_ui
    build_ui.build()
    STAGE.mkdir(parents=True,exist_ok=True)
    for name in list(dict.fromkeys(build_portable.FILES+['app_paths.py','login_session.py','chat_consent.py','login-focus.js','ai_config.py'])):
        shutil.copy2(ROOT/name,STAGE/name)
    shutil.copytree(ROOT/'.runtime',STAGE/'.runtime',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    assert hashlib.sha256(build_portable.EMBED.read_bytes()).hexdigest()==build_portable.EXPECTED
    with zipfile.ZipFile(build_portable.EMBED) as z:z.extractall(STAGE/'python')
    (STAGE/'python/python311._pth').write_text('python311.zip\n.\n..\nimport site\n',encoding='ascii')
    for name in ['Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll','WebView2Loader.dll','MicrosoftEdgeWebview2Setup.exe']:
        shutil.copy2(SDK/name,STAGE/name)
    (STAGE/'default-key.txt').write_text('DEEPSEEK_API_KEY=\n',encoding='utf-8')
    shutil.copy2(ROOT/'build-tools/小红帽.ico',STAGE/'小红帽.ico')
    compiler=Path(r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')
    command=[str(compiler),'/nologo','/target:winexe','/platform:x64','/utf8output','/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.Web.Extensions.dll','/out:'+str(STAGE/'小红帽.exe')]
    command+=['/reference:'+str(STAGE/name) for name in ['Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll']]
    command+=['/win32icon:'+str(STAGE/'小红帽.ico'),'/win32manifest:'+str(ROOT/'build-tools/NativeClient.manifest')]
    command += [str(ROOT/'build-tools/NativeClient.cs'), str(ROOT/'build-tools/NativeLogin.cs'),str(ROOT/'build-tools/NativeLifecycle.cs')]
    with tempfile.TemporaryDirectory(prefix='xhm-version-') as temporary:
        source=Path(temporary)/'Version.cs';version=release_config.load()['version']+'.0'
        source.write_text('[assembly:System.Reflection.AssemblyVersion("'+version+'")]\n[assembly:System.Reflection.AssemblyFileVersion("'+version+'")]\n',encoding='utf-8')
        subprocess.run(command+[str(source)],check=True)
    print('Native client built:',STAGE)

if __name__=='__main__':build()
