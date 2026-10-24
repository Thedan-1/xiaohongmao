"""Run from a copied Python runtime after the old native client has exited."""
import argparse,ctypes,hashlib,json,os,re,shutil,stat,subprocess,sys,time,uuid,zipfile
from pathlib import Path,PurePosixPath

def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def atomic_text(path,text):
    path=Path(path);temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('x',encoding='utf-8') as f:f.write(text);f.flush();os.fsync(f.fileno())
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()

def safe_relative(value):
    if not isinstance(value,str) or not value or '\\' in value or ':' in value or PurePosixPath(value).is_absolute():return False
    parts=value.rstrip('/').split('/')
    reserved={'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}
    return all(p not in ('','.','..') and not p.endswith(('.', ' ')) and not any(ord(c)<32 for c in p) and p.split('.')[0].upper() not in reserved for p in parts)

def validate_plan(plan):
    if not isinstance(plan,dict) or not re.fullmatch(r'\d+\.\d+\.\d+',str(plan.get('version',''))):raise ValueError('更新计划版本号无效')
    if plan.get('distribution') not in ('preview','installed'):raise ValueError('更新方式无效')
    if not re.fullmatch(r'[a-f0-9]{64}',str(plan.get('sha256',''))):raise ValueError('更新校验值无效')
    age=time.time()-float(plan.get('created_at',0))
    if not 0<=age<=600:raise ValueError('更新计划已过期，请重新选择更新')
    root=Path(plan['app_root']).resolve();home=Path(plan['data_home']).resolve();package=Path(plan['package']).resolve()
    if len(root.parts)<3 or root==home or not (root/'小红帽.exe').is_file():raise ValueError('当前程序目录无效')
    if package.parent!=(home/'data/updates').resolve():raise ValueError('更新包不在本机更新缓存目录')
    if package.suffix!={ 'preview':'.zip','installed':'.exe'}[plan['distribution']]:raise ValueError('更新包类型不正确')
    if not package.is_file() or sha256(package)!=plan['sha256']:raise ValueError('更新包校验失败，当前版本未修改')
    manifest=json.loads((root/'package-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('distribution')!=plan['distribution']:raise ValueError('更新计划与当前客户端版本类型不符')
    return root,home,package

def wait_parent(pid,seconds=120):
    if not pid:return
    if os.name!='nt':raise RuntimeError('更新器仅支持 Windows')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.restype=ctypes.c_void_p;kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x00100000,False,int(pid))
    if not handle:
        if ctypes.get_last_error()==87:return
        raise RuntimeError('无法确认旧客户端是否已经退出')
    try:
        if kernel.WaitForSingleObject(handle,seconds*1000)!=0:raise RuntimeError('旧客户端尚未退出，未开始更新')
    finally:kernel.CloseHandle(handle)

def apply_preview(plan,root,package):
    parent=root.parent;pointer=parent/'current-app.txt'
    previous=pointer.read_text(encoding='utf-8').strip()
    if previous!=root.name or not (parent/'小红帽预览.exe').is_file():raise ValueError('预览版目录结构不完整，未更新')
    prefix='小红帽-免安装预览版/'
    with zipfile.ZipFile(package) as archive:
        entries=archive.infolist();names=[x.filename for x in entries]
        if len(entries)>10000 or len(set(names))!=len(names) or sum(x.file_size for x in entries)>512*1024*1024:raise ValueError('更新包内容或大小异常')
        for row in entries:
            p=PurePosixPath(row.filename)
            if not row.filename.startswith(prefix) or not safe_relative(row.filename) or stat.S_ISLNK(row.external_attr>>16):raise ValueError('更新包包含不安全的路径')
        source=archive.read(prefix+'current-app.txt').decode('utf-8').strip()
        if not re.fullmatch(r'app-[0-9A-Za-z.-]+',source):raise ValueError('更新包的程序目录名称无效')
        manifest=json.loads(archive.read(prefix+source+'/package-manifest.json').decode('utf-8'))
        if manifest.get('version')!=plan['version'] or manifest.get('distribution')!='preview' or manifest.get('credential_embedded') is not False or manifest.get('user_data_included') is not False:raise ValueError('更新包的版本或发行信息不正确')
        files=manifest.get('files')
        if not isinstance(files,list) or any(not safe_relative(n) or n.endswith('/') for n in files):raise ValueError('更新文件清单无效')
        expected={prefix+source+'/'+n for n in files+['package-manifest.json']}
        expected.update(prefix+n for n in ('小红帽预览.exe','使用说明.txt','current-app.txt'))
        if {n for n in names if not n.endswith('/')}!=expected:raise ValueError('更新包存在清单之外的文件')
        if '小红帽.exe' not in files or 'app.py' not in files:raise ValueError('更新包缺少程序文件')
        name='app-'+plan['version']+'-update-'+uuid.uuid4().hex[:10];target=parent/name;target.mkdir()
        for rel in files+['package-manifest.json']:
            dest=target/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            with dest.open('xb') as f:f.write(archive.read(prefix+source+'/'+rel))
        for leaf in ('小红帽预览.exe','使用说明.txt'):
            dest=parent/leaf;temporary=dest.with_name(leaf+'.'+uuid.uuid4().hex+'.tmp')
            temporary.write_bytes(archive.read(prefix+leaf));os.replace(temporary,dest)
        atomic_text(parent/'current-app.previous.txt',previous)
        atomic_text(pointer,name)
    return target,previous

def launch(root,home,preview):
    env=os.environ.copy();env['XIAOHONGMAO_DATA_HOME']=str(home);env.pop('XIAOHONGMAO_DESKTOP_SMOKE',None)
    return subprocess.Popen([str(root/'小红帽.exe')]+(['--preview'] if preview else []),cwd=root,env=env)

def run(plan_path,parent_pid):
    plan=json.loads(Path(plan_path).read_text(encoding='utf-8'));root,home,package=validate_plan(plan)
    result=home/'data/update-result.json';target=root;previous=None
    wait_parent(parent_pid)
    # Recheck after waiting for exit: a modified cache can never be executed.
    validate_plan(plan)
    try:
        if plan['distribution']=='preview':target,previous=apply_preview(plan,root,package)
        else:
            setup=subprocess.Popen([str(package),'/DIR='+str(root),'/SILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-'])
            if setup.wait()!=0:raise RuntimeError('安装程序未完成更新，原有用户数据保留')
            manifest=json.loads((root/'package-manifest.json').read_text(encoding='utf-8'))
            if manifest.get('version')!=plan['version']:raise RuntimeError('安装后的版本不匹配，请重新打开客户端检查')
        launch(target,home,plan['distribution']=='preview')
        atomic_text(result,json.dumps({'ok':True,'version':plan['version'],'time':time.time()},ensure_ascii=False))
    except Exception as exc:
        if previous:atomic_text(root.parent/'current-app.txt',previous)
        atomic_text(result,json.dumps({'ok':False,'message':str(exc),'time':time.time()},ensure_ascii=False))
        try:launch(root,home,plan['distribution']=='preview')
        except Exception:pass
        raise

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--plan',required=True);parser.add_argument('--parent',type=int,required=True);args=parser.parse_args()
    try:run(args.plan,args.parent)
    except Exception as exc:
        if os.name=='nt':ctypes.windll.user32.MessageBoxW(None,'更新未完成：'+str(exc)+'\n请重新打开原客户端；本机用户数据没有被清空。','小红帽更新',0x10)
        sys.exit(1)
