"""One release version/repository for packaging, the UI and update validation."""
import json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'0|[1-9]\d*',value.split('.')[0]):raise ValueError('版本号无效')
    if not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)',value):raise ValueError('版本号必须为 x.y.z')
    if any(int(x)>65535 for x in value.split('.')):raise ValueError('版本号超出 Windows 支持范围')
    return tuple(map(int,value.split('.')))

def load(root=None):
    value=json.loads(((Path(root) if root else ROOT)/'release-config.json').read_text(encoding='utf-8'))
    version(value['version']);repo=value.get('repository','')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}',repo):raise ValueError('GitHub 仓库配置无效')
    return {'version':value['version'],'repository':repo}

def asset_name(ver,distribution):
    version(ver)
    suffix={'installed':'setup.exe','preview':'preview.zip'}.get(distribution)
    if not suffix:raise ValueError('此运行方式暂不支持自动安装更新')
    return f'xiaohongmao-{ver}-windows-x64-{suffix}'
