"""Dedicated Taobao browser; separate profile and visible-page diagnostics only."""
from pathlib import Path
import argparse,json,re,sys,time
from urllib.parse import urlencode,urlsplit
from app_paths import data_dir
from edge_path import find_edge

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'.runtime'))

class TaobaoVerificationRequired(RuntimeError):
    pass

def verification_notice(text):
    if not isinstance(text,str):return None
    if not (('滑块' in text and '验证' in text and '正常访问' in text) or ('验证失败' in text and '重试' in text)):
        return None
    match=re.search(r'error\s*[:：]\s*([A-Za-z0-9_-]{1,40})',text,re.I)
    code='（'+match[1]+'）' if match else ''
    return '淘宝要求安全验证'+code+'，流程已暂停。请在官方页面处理；尚未发送，不自动刷新或重试。'

def official_url(value):
    u=urlsplit(value);host=(u.hostname or '').lower()
    return u.scheme=='https' and not u.username and not u.password and (host=='taobao.com' or host.endswith('.taobao.com') or host=='tmall.com' or host.endswith('.tmall.com'))

class TaobaoBrowser:
    def __init__(self,home=None):
        self.home=Path(home) if home else data_dir(ROOT)
        self.context=self.page=self.driver=None

    def open(self):
        from playwright.sync_api import sync_playwright
        self.home.mkdir(parents=True,exist_ok=True)
        self.driver=sync_playwright().start()
        self.context=self.driver.chromium.launch_persistent_context(user_data_dir=str(self.home/'taobao-profile'),executable_path=find_edge(),headless=False,no_viewport=True,accept_downloads=False)
        self.context.set_default_timeout(6000)
        self.page=self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.goto('https://www.taobao.com/',wait_until='domcontentloaded',timeout=30000)

    def search(self,query):
        if not isinstance(query,str) or not 1<=len(query.strip())<=100:raise ValueError('请输入店铺搜索词')
        self.check_verification(self.page)
        self.page.goto('https://s.taobao.com/search?'+urlencode({'q':query.strip()}),wait_until='domcontentloaded',timeout=30000)
        self.check_verification(self.page)

    def check_verification(self,page):
        if not official_url(page.url):raise RuntimeError('当前页面不在淘宝或天猫官方域名，已停止')
        for frame in page.frames:
            try:
                if frame!=page.main_frame and not frame.frame_element().is_visible():continue
                text=frame.locator('body').inner_text(timeout=750)
            except Exception:continue
            notice=verification_notice(text)
            if notice:raise TaobaoVerificationRequired(notice)

    def snapshot(self):
        page=self.context.pages[-1]
        if not official_url(page.url):raise RuntimeError('浏览器当前页面不在淘宝或天猫官方域名，未读取')
        self.check_verification(page)
        value=page.evaluate('''()=>({title:document.title,text:document.body?.innerText.slice(0,14000)||'',
        links:[...document.querySelectorAll('a[href]')].filter(a=>a.getBoundingClientRect().width&&a.getBoundingClientRect().height).map(a=>({text:a.innerText.trim().slice(0,100),href:a.href})).slice(0,150),
        controls:[...document.querySelectorAll('input,textarea,button,[contenteditable=true]')].filter(e=>e.getBoundingClientRect().width&&e.getBoundingClientRect().height).map(e=>({tag:e.tagName,placeholder:e.getAttribute('placeholder'),text:e.tagName==='BUTTON'?e.innerText.slice(0,80):'',editable:e.getAttribute('contenteditable')})).slice(0,60)})''')
        value.update(url=page.url,time=time.strftime('%Y-%m-%dT%H:%M:%S'))
        return value

    def close(self):
        if self.context:self.context.close()
        if self.driver:self.driver.stop()

def probe(query,seconds):
    browser=TaobaoBrowser();out=browser.home/'taobao-probe.json'
    try:
        browser.open();browser.search(query)
        print(json.dumps({'opened':True,'query':query,'profile_separate_from_xiaohongshu':True,'read_only':True},ensure_ascii=False),flush=True)
        deadline=time.monotonic()+seconds;prior=None
        while time.monotonic()<deadline:
            try:
                value=browser.snapshot();temporary=out.with_suffix('.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(out)
                summary={'title':value['title'],'host':urlsplit(value['url']).hostname,'visible_links':len(value['links']),'login_visible':any(x in value['text'] for x in ('扫码登录','密码登录','短信登录'))}
                if summary!=prior:print(json.dumps(summary,ensure_ascii=False),flush=True);prior=summary
                browser.page.wait_for_timeout(2000)
            except TaobaoVerificationRequired as exc:
                out.write_text(json.dumps({'status':'verification_required','message':str(exc),'sent':0},ensure_ascii=False),encoding='utf-8')
                print(json.dumps({'status':'verification_required','message':str(exc),'sent':0},ensure_ascii=False),flush=True)
                break
            except Exception:
                if not browser.context.pages:break
                browser.page=browser.context.pages[-1];browser.page.wait_for_timeout(1000)
    finally:browser.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--probe',action='store_true');p.add_argument('--query',default='BIM代做');p.add_argument('--seconds',type=int,default=600);args=p.parse_args()
    if args.probe:probe(args.query,args.seconds)
