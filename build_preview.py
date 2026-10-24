"""Build a clean unzip-and-run preview, with no installer or real user data."""
import hashlib
import argparse
import json
from pathlib import Path
import subprocess
import shutil
import zipfile
import time
import build_desktop
import build_installer
import release_config

ROOT=Path(__file__).resolve().parent
PREVIEW=ROOT/'release/小红帽-免安装预览版'

def build(internal=False):
    config=release_config.load();version=config['version']
    build_desktop.build()
    PREVIEW.mkdir(parents=True,exist_ok=True)
    # Each build publishes to its own directory, never overwriting a running client.
    app_name='app-'+version+'-'+str(time.time_ns())
    app_dir=PREVIEW/app_name
    manifest=build_installer.prepare_payload(build_desktop.STAGE,app_dir,internal,ROOT/'deepseek.local.txt')
    manifest['version']=version;manifest['distribution']='preview'
    (app_dir/'package-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    csc=Path(r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')
    subprocess.run([str(csc),'/nologo','/target:winexe','/platform:x64','/utf8output','/reference:System.Windows.Forms.dll',
                    '/win32icon:'+str(ROOT/'build-tools/小红帽.ico'),
                    '/win32manifest:'+str(ROOT/'build-tools/NativeClient.manifest'),
                    '/out:'+str(PREVIEW/'小红帽预览.exe'),str(ROOT/'build-tools/PreviewEntry.cs')],check=True)
    pointer=PREVIEW/'current-app.txt';temporary=pointer.with_suffix('.tmp')
    temporary.write_text(app_name,encoding='utf-8');temporary.replace(pointer)
    (PREVIEW/'使用说明.txt').write_text(f'小红帽 {version} 免安装预览版\n\n完整解压后，双击“小红帽预览.exe”即可。不要单独移动 EXE。\n首次使用只显示官方登录框，登录后自动核对账号、进入工作台。\n准备消息预览后，可说“确认发送这批评论”或“确认发送这批私信”。\n此确认仅针对当前预览；修改对象、内容或账号后需要重新确认。\n预览记录与登录资料保存在 %LOCALAPPDATA%\\XiaohongmaoPreview，与安装版分开。\n更新：把新版压缩包完整解压到原目录，再退出旧客户端，重新打开“小红帽预览.exe”。程序目录可更新，本机数据不会被覆盖。也可在设置 → 关于中检查 GitHub Releases 更新，下载后选择重启更新。\n首次使用请在个人设置 → 模型与 API 中填写自己的密钥，并在用量与预算中设置本机费用上限。公开版不含预填密钥；已有本机配置不会被覆盖。\n其他电脑若缺少 WebView2，首次启动需按微软提示安装。\n',encoding='utf-8')
    archive=ROOT/(f'release/小红帽-{version}-免安装'+('内部版' if internal else '公开版')+'.zip')
    # Use the sanitized manifest, never archive a preview's later runtime files.
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name in manifest['files']+['package-manifest.json']:
            z.write(app_dir/name,str(Path('小红帽-免安装预览版')/app_name/name))
        for name in ('小红帽预览.exe','使用说明.txt','current-app.txt'):
            z.write(PREVIEW/name,str(Path('小红帽-免安装预览版')/name))
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.sha256.txt').write_text(digest+'  '+archive.name+'\n',encoding='utf-8')
    print(json.dumps({'launcher':str(PREVIEW/'小红帽预览.exe'),'zip':str(archive),'bytes':archive.stat().st_size,'user_data_included':False},ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--ui-only',action='store_true');parser.add_argument('--internal',action='store_true');args=parser.parse_args()
    if args.ui_only:
        import build_ui
        pointer=PREVIEW/'current-app.txt'
        app_dir=PREVIEW/(pointer.read_text(encoding='utf-8').strip() if pointer.exists() else 'app')
        if app_dir.parent!=PREVIEW or not (app_dir/'小红帽.exe').exists():raise SystemExit('请先运行一次完整预览构建')
        build_ui.build();shutil.copy2(ROOT/'ui.html',app_dir/'ui.html')
        print('Preview UI updated. Press F5 in the preview client.')
    else:build(args.internal)
