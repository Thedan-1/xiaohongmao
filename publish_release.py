"""Publish only audited public installer/preview assets; never bundle a local key."""
import argparse,hashlib,json,shutil,subprocess,tempfile,zipfile
from pathlib import Path
import release_config

ROOT=Path(__file__).resolve().parent

def prepare(destination,notes=''):
    cfg=release_config.load();version=cfg['version'];release=ROOT/'release'
    installer=release/f'小红帽-Windows-x64-v{version}-普通版-安装.exe'
    manifest=json.loads(installer.with_suffix('.manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version')!=version or manifest.get('credential_embedded') is not False or manifest.get('user_data_included') is not False or manifest.get('internal') is not False:raise ValueError('安装包不是已审查的公开版本')
    preview=release/f'小红帽-{version}-免安装公开版.zip'
    with zipfile.ZipFile(preview) as z:
        names=z.namelist();candidates=[n for n in names if n.endswith('/package-manifest.json')]
        if len(candidates)!=1:raise ValueError('预览包版本清单不唯一')
        meta=json.loads(z.read(candidates[0]))
        if meta.get('version')!=version or meta.get('credential_embedded') is not False or meta.get('user_data_included') is not False or meta.get('distribution')!='preview':raise ValueError('预览包不是公开版本')
        for name in names:
            if any(p in ('data','edge-profile','taobao-profile','ai-settings.json','deepseek.local.txt') for p in Path(name).parts):raise ValueError('预览包包含用户文件，拒绝发布')
    assets=[]
    for source,kind in [(installer,'installed'),(preview,'preview')]:
        target=destination/release_config.asset_name(version,kind);shutil.copy2(source,target);assets.append(target)
    sums=destination/'SHA256SUMS.txt';sums.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in assets),encoding='utf-8');assets.append(sums)
    for source in [installer.with_suffix('.manifest.json')]:
        target=destination/'setup.manifest.json';shutil.copy2(source,target);assets.append(target)
    feed={'schema':1,'repository':cfg['repository'],'tag_name':'v'+version,'draft':False,'prerelease':False,'body':notes,'assets':[]}
    for path in assets[:2]:
        feed['assets'].append({'name':path.name,'state':'uploaded','size':path.stat().st_size,'digest':'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest(),
                               'browser_download_url':f'https://github.com/{cfg["repository"]}/releases/download/v{version}/{path.name}'})
    metadata=destination/'update.json';metadata.write_text(json.dumps(feed,ensure_ascii=False,indent=2),encoding='utf-8');assets.append(metadata)
    return cfg,assets

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--publish',action='store_true',help='Publish after uploading; default creates a draft');parser.add_argument('--notes',type=Path,required=True);parser.add_argument('--target',default='main');parser.add_argument('--validate-only',action='store_true');args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='xhm-github-release-') as folder:
        config,assets=prepare(Path(folder),args.notes.read_text(encoding='utf-8'))
        if args.validate_only:print(json.dumps({'version':config['version'],'files':[p.name for p in assets],'credential_embedded':False},ensure_ascii=False));return
        subprocess.run(['gh','release','create','v'+config['version'],*[str(p) for p in assets],'--repo',config['repository'],'--title','小红帽 v'+config['version'],'--notes-file',str(args.notes),'--target',args.target,'--draft'],check=True)
        if args.publish:subprocess.run(['gh','release','edit','v'+config['version'],'--repo',config['repository'],'--draft=false','--latest'],check=True)

if __name__=='__main__':main()
