"""Build a sanitized, per-user Windows installer; --internal explicitly bundles a key."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile
import release_config

ROOT = Path(__file__).resolve().parent
RELEASE = ROOT / 'release'
DEFAULT_STAGE = RELEASE / '小红帽-Windows-x64-v0.6'
PROGRAM_FILES = {
    'release_config.py','release-config.json','updater.py','update_apply.py',
    '小红帽.exe', 'Microsoft.Web.WebView2.Core.dll',
    'Microsoft.Web.WebView2.WinForms.dll', 'WebView2Loader.dll',
    'MicrosoftEdgeWebview2Setup.exe', 'MicrosoftWebView2Setup.exe',
    'app.py', 'app_paths.py', 'adapter.py', 'edge_path.py', 'launcher.py',
    'shutdown.py', 'ui.html', 'login_session.py', 'chat_consent.py', 'login-focus.js',
    'ai_config.py', 'requirements.txt', 'discovery.py', 'workflow_ai.py', 'deepseek_client.py',
    'note_collector.py', 'browser_guard.py', 'topic_state.py', 'comment_flow.py',
    'batch_comments.py', 'lead_review.py', 'studio.py', 'legacy-ui.html',
    'benchmark_collect.py', 'project_store.py', 'studio_archive.py',
    'video_candidates.py', '小红帽.ico', '小红帽.exe.config',
}
REQUIRED = {'小红帽.exe', 'app.py', 'app_paths.py', 'ui.html',
            'Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll',
            'WebView2Loader.dll', 'python/pythonw.exe', 'python/python.exe',
            'python/python311.zip', '.runtime/playwright/driver/node.exe',
            '.runtime/playwright/sync_api/__init__.py'}


def read_key(path: Path) -> str:
    """Read only the configured key, never echoing its value or full config."""
    raw = path.read_text(encoding='utf-8-sig')
    for line in raw.splitlines():
        match = re.match(r'^\s*DEEPSEEK_API_KEY\s*=\s*(.*?)\s*$', line)
        if match and match.group(1):
            return match.group(1).strip('\"\'')
    value = raw.strip()
    if value.startswith('sk-') and not any(c.isspace() for c in value):
        return value
    raise ValueError('内部版未找到有效的 DEEPSEEK_API_KEY；未构建安装包。')


def allowed(rel: Path) -> bool:
    if any(part in ('__pycache__', 'data', 'edge-profile', 'logs') for part in rel.parts):
        return False
    if rel.suffix.lower() in ('.pyc', '.sqlite3', '.sqlite', '.db', '.log'):
        return False
    return rel.as_posix() in PROGRAM_FILES or rel.parts[0] in ('python', '.runtime')


def prepare_payload(source: Path, destination: Path, internal: bool, key_file: Path) -> dict:
    if not source.is_dir():
        raise ValueError('请先构建 v0.6 客户端目录：' + str(source))
    missing = sorted(name for name in REQUIRED if not (source / name).is_file())
    if missing:
        raise ValueError('客户端目录缺少文件：' + ', '.join(missing))
    included = []
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            raise ValueError('客户端目录包含符号链接，拒绝打包：' + str(path.relative_to(source)))
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        if not allowed(rel):
            continue
        dest = destination / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        included.append(rel.as_posix())
    key = read_key(key_file) if internal else ''
    (destination / 'default-key.txt').write_text('DEEPSEEK_API_KEY=' + key + '\n', encoding='utf-8')
    # The writable key file lives in the per-user data home, never in {app}.
    included.append('default-key.txt')
    shutil.copy2(ROOT / 'installer/桌面版使用说明.txt', destination / '桌面版使用说明.txt')
    guide=destination/'桌面版使用说明.txt'
    guide.write_text(re.sub(r'^小红帽 \d+\.\d+\.\d+', '小红帽 '+release_config.load()['version'],guide.read_text(encoding='utf-8'),count=1),encoding='utf-8')
    included.append('桌面版使用说明.txt')
    shutil.copy2(ROOT / 'vendor/Motion-LICENSE.txt', destination / 'Motion-LICENSE.txt')
    included.append('Motion-LICENSE.txt')
    sdk = ROOT / 'build-tools/webview2/microsoft.web.webview2.1.0.4258.31.nupkg'
    with zipfile.ZipFile(sdk) as package:
        for name in ('LICENSE.txt', 'NOTICE.txt'):
            target = 'WebView2-' + name
            (destination / target).write_bytes(package.read(name))
            included.append(target)
    manifest = {'version': release_config.load()['version'], 'distribution':'installed', 'internal': internal, 'files': included,
                'credential_embedded': bool(key), 'user_data_included': False}
    (destination / 'package-manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def find_compiler(explicit: str | None) -> Path:
    candidates = [Path(explicit)] if explicit else []
    candidates += [ROOT / 'build-tools/inno/compiler/ISCC.exe']
    for env in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
        base = Path(os.environ.get(env, 'C:/missing'))
        candidates += [base / 'Inno Setup 6/ISCC.exe', base / 'Programs/Inno Setup 6/ISCC.exe']
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError('未找到 Inno Setup 编译器；用 --compiler 指定 ISCC.exe。')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_STAGE)
    parser.add_argument('--internal', action='store_true')
    parser.add_argument('--key-file', type=Path, default=ROOT / 'deepseek.local.txt')
    parser.add_argument('--compiler')
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    RELEASE.mkdir(exist_ok=True)
    edition = '内部专用版' if args.internal else '普通版'
    output_name = f'小红帽-Windows-x64-v{release_config.load()["version"]}-{edition}-安装'
    with tempfile.TemporaryDirectory(prefix='xiaohongmao-installer-') as temp:
        payload = Path(temp) / 'payload'
        payload.mkdir()
        manifest = prepare_payload(args.source.resolve(), payload, args.internal, args.key_file)
        if args.validate_only:
            print(json.dumps({'ok': True, 'edition': edition, 'files': len(manifest['files']),
                              'credential_embedded': manifest['credential_embedded']}, ensure_ascii=False))
            return
        compiler = find_compiler(args.compiler)
        # Compiler sees a path to the payload; credentials never appear in arguments/output.
        subprocess.run([str(compiler), '/Qp', '/DSourceDir=' + str(payload),
                        '/DOutputDir=' + str(RELEASE), '/DOutputName=' + output_name,
                        '/DAppVersion='+release_config.load()['version'],
                        str(ROOT / 'installer/小红帽.iss')], check=True)
    result = RELEASE / (output_name + '.exe')
    digest = hashlib.sha256(result.read_bytes()).hexdigest()
    result.with_suffix('.sha256.txt').write_text(digest + '  ' + result.name + '\n', encoding='utf-8')
    result.with_suffix('.manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'installer': str(result), 'bytes': result.stat().st_size,
                      'sha256': digest, 'internal': args.internal}, ensure_ascii=False))


if __name__ == '__main__':
    main()
