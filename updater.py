"""Public GitHub Releases checks/downloads. No GitHub credential ships to clients."""
import hashlib,json,os,re,shutil,threading,time,urllib.request,urllib.error,uuid
from pathlib import Path
from urllib.parse import urlsplit,unquote
from app_paths import data_dir
import release_config

MAX_PACKAGE=256*1024*1024
CONTENT_HOSTS={'github.com','release-assets.githubusercontent.com','objects.githubusercontent.com','github-releases.githubusercontent.com'}

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,url):
        u=urlsplit(url)
        if u.scheme!='https' or u.hostname not in CONTENT_HOSTS or u.username or u.password:raise RuntimeError('更新下载跳转地址不受信任，已停止')
        return super().redirect_request(request,fp,code,msg,headers,url)

def digest_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def choose_release(raw,config,distribution):
    if not isinstance(raw,dict) or raw.get('draft') is not False or raw.get('prerelease') is not False:raise ValueError('未找到已发布的正式版本')
    tag=raw.get('tag_name','');new=tag.removeprefix('v');release_config.version(new)
    if tag!='v'+new:raise ValueError('发布标签必须为 v版本号')
    if release_config.version(new)<=release_config.version(config['version']):return None
    expected=release_config.asset_name(new,distribution)
    assets=[x for x in raw.get('assets',[]) if isinstance(x,dict) and x.get('name')==expected and x.get('state')=='uploaded']
    if len(assets)!=1:raise ValueError('新版缺少当前版本对应的更新包，请稍后再试')
    item=assets[0];url=item.get('browser_download_url','');u=urlsplit(url)
    if u.scheme!='https' or u.netloc!='github.com' or unquote(u.path)!=f'/{config["repository"]}/releases/download/{tag}/{expected}' or u.query or u.fragment:raise ValueError('更新包来源与配置的 GitHub 仓库不一致')
    checksum=item.get('digest')
    if not isinstance(checksum,str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',checksum):raise ValueError('GitHub 尚未提供更新包校验值，未下载')
    size=item.get('size')
    if type(size) is not int or not 1<=size<=MAX_PACKAGE:raise ValueError('更新包大小不正确')
    return {'version':new,'tag':tag,'name':expected,'url':url,'sha256':checksum[7:],'size':size,'notes':str(raw.get('body') or '')[:12000],
            'release_url':f'https://github.com/{config["repository"]}/releases/tag/{tag}'}

class UpdateManager:
    def __init__(self,root=None,home=None):
        self.root=Path(root) if root else Path(__file__).resolve().parent
        self.folder=(Path(home) if home else data_dir(self.root))/'updates';self.config=release_config.load(self.root)
        try:self.distribution=json.loads((self.root/'package-manifest.json').read_text(encoding='utf-8'))['distribution']
        except (OSError,ValueError,KeyError):self.distribution='development'
        self.lock=threading.RLock();self.cancel=threading.Event();self.thread=None;self.last_request=0
        self.value={'phase':'idle','current_version':self.config['version'],'repository':self.config['repository'],'distribution':self.distribution,'message':'尚未检查更新'}
        self.selected=None;self.staged=None

    def status(self):
        with self.lock:return dict(self.value)

    def change(self,**values):
        with self.lock:self.value.update(values)

    def check(self,automatic=False):
        with self.lock:
            if self.thread and self.thread.is_alive():return self.status()
            if self.value['phase']=='ready':return self.status()
            if self.distribution not in ('installed','preview'):
                self.change(phase='unsupported',message='开发运行方式不执行自动更新，请使用客户端预览版或安装版');return self.status()
            if self.last_request and time.monotonic()-self.last_request<60:return self.status()
            self.last_request=time.monotonic();self.change(phase='checking',message='正在检查 GitHub Releases…',error='')
            self.thread=threading.Thread(target=self._check,args=(automatic,),daemon=True);self.thread.start()
        return self.status()

    def _check(self,automatic):
        try:
            cache=self.folder/'release-cache.json';raw=None
            if automatic:
                try:
                    saved=json.loads(cache.read_text(encoding='utf-8'))
                    if saved['repository']==self.config['repository'] and 0<=time.time()-saved['checked_at']<21600:raw=saved['release']
                except (OSError,ValueError,KeyError,TypeError):pass
            if raw is None:
                url=f'https://api.github.com/repos/{self.config["repository"]}/releases/latest'
                request=urllib.request.Request(url,headers={'Accept':'application/vnd.github+json','User-Agent':'Xiaohongmao/'+self.config['version'],'X-GitHub-Api-Version':'2022-11-28'})
                with urllib.request.build_opener().open(request,timeout=15) as response:
                    data=response.read(1024*1024+1)
                    if len(data)>1024*1024:raise ValueError('更新信息过大')
                    raw=json.loads(data)
                self.folder.mkdir(parents=True,exist_ok=True)
                temporary=cache.with_suffix('.tmp');temporary.write_text(json.dumps({'repository':self.config['repository'],'checked_at':time.time(),'release':raw}),encoding='utf-8');os.replace(temporary,cache)
            selected=choose_release(raw,self.config,self.distribution)
            with self.lock:
                self.selected=selected
                self.change(phase='available' if selected else 'latest',message='发现新版本，可选择下载更新' if selected else '当前已是最新正式版本',release=selected)
        except urllib.error.HTTPError as exc:
            message='暂时没有已发布的正式版本' if exc.code==404 else 'GitHub 暂时限制了检查请求，请稍后重试' if exc.code in (403,429) else f'更新服务暂不可用（HTTP {exc.code}）'
            self.change(phase='error',message=message)
        except Exception as exc:self.change(phase='error',message=str(exc) if isinstance(exc,(RuntimeError,ValueError)) else '暂时无法连接 GitHub，不影响继续使用')

    def download(self):
        with self.lock:
            if self.thread and self.thread.is_alive():return self.status()
            if self.value['phase']=='ready':return self.status()
            if not self.selected:raise ValueError('请先检查并找到新版')
            self.cancel.clear();self.change(phase='downloading',downloaded=0,total=self.selected['size'],message='正在下载更新…')
            self.thread=threading.Thread(target=self._download,args=(dict(self.selected),),daemon=True);self.thread.start()
        return self.status()

    def _download(self,item):
        temporary=None
        try:
            self.folder.mkdir(parents=True,exist_ok=True)
            destination=self.folder/(item['sha256']+Path(item['name']).suffix);temporary=destination.with_suffix('.'+uuid.uuid4().hex+'.part')
            if destination.is_file() and destination.stat().st_size==item['size'] and digest_file(destination)==item['sha256']:
                self.staged=destination;self.change(phase='ready',message='更新包已校验，可在空闲时重启更新');return
            request=urllib.request.Request(item['url'],headers={'User-Agent':'Xiaohongmao/'+self.config['version']})
            h=hashlib.sha256();received=0
            with urllib.request.build_opener(SafeRedirect()).open(request,timeout=30) as response,temporary.open('xb') as output:
                while True:
                    if self.cancel.is_set():raise InterruptedError()
                    chunk=response.read(256*1024)
                    if not chunk:break
                    received+=len(chunk)
                    if received>item['size'] or received>MAX_PACKAGE:raise ValueError('下载大小与 GitHub 发布信息不一致')
                    output.write(chunk);h.update(chunk);self.change(downloaded=received)
                output.flush();os.fsync(output.fileno())
            if received!=item['size'] or h.hexdigest()!=item['sha256']:raise ValueError('更新包校验失败，未安装；请重新下载')
            if self.cancel.is_set():raise InterruptedError()
            os.replace(temporary,destination);self.staged=destination;self.change(phase='ready',message='更新包已校验，可在空闲时重启更新')
        except InterruptedError:self.change(phase='available',message='下载已取消，当前版本可以继续使用')
        except Exception as exc:self.change(phase='error',message=str(exc) if isinstance(exc,ValueError) else '下载未完成，当前版本没有被修改，可以重试')
        finally:
            if temporary and temporary.exists():temporary.unlink()

    def prepare(self,app):
        import studio
        with studio.ADMISSION_LOCK:
            if app.SHUTTING_DOWN.is_set():raise ValueError('程序已经在退出，请稍后重新打开')
            if studio.is_busy(app):raise ValueError('任务仍在运行，请完成或暂停任务后再重启更新')
            with self.lock:
                item=self.selected
                if self.value['phase']!='ready' or not item or not self.staged:raise ValueError('请先下载并校验更新包')
                if not self.staged.is_file() or digest_file(self.staged)!=item['sha256']:raise ValueError('更新包已变化，请重新下载')
                helper=self.folder/'helpers'/uuid.uuid4().hex;helper.mkdir(parents=True)
                shutil.copytree(self.root/'python',helper/'python')
                shutil.copy2(self.root/'update_apply.py',helper/'update_apply.py')
                plan={'version':item['version'],'distribution':self.distribution,'package':str(self.staged),'sha256':item['sha256'],
                      'app_root':str(self.root),'data_home':str(app.DATA.parent),'created_at':time.time()}
                path=helper/'plan.json';path.write_text(json.dumps(plan,ensure_ascii=False),encoding='utf-8')
                # Freeze admission and enqueue graceful shutdown together. No task is killed.
                result,status=app.request_command({'command':'shutdown'})
                if status!=200:raise ValueError(result.get('error','后台无法准备退出'))
                return {'plan':str(path),'python':str(helper/'python/pythonw.exe'),'script':str(helper/'update_apply.py')}

MANAGERS={};MANAGER_LOCK=threading.Lock()
def manager(app):
    key=(str(app.ROOT),str(app.DATA))
    with MANAGER_LOCK:
        if key not in MANAGERS:MANAGERS[key]=UpdateManager(app.ROOT,app.DATA)
        return MANAGERS[key]

def handle(app,data):
    task=manager(app);action=data.get('action')
    if action=='check':return task.check(data.get('automatic') is True)
    if action=='download':return task.download()
    if action=='cancel':task.cancel.set();return task.status()
    if action=='prepare':return task.prepare(app)
    raise ValueError('不支持的更新操作')
