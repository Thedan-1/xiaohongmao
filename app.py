from __future__ import annotations

import csv
import io
import json
import math
import os
import queue
import random
import secrets
import socket
import sqlite3
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from edge_path import find_edge
from app_paths import data_dir

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / '.runtime'))
DATA = data_dir(ROOT)
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / 'workbench.sqlite3'
TOKEN = secrets.token_urlsafe(32)
COMMANDS = queue.Queue()
STOP = threading.Event()
SHUTTING_DOWN = threading.Event()
SERVER = None
LOCK = threading.Lock()
STATE = {'browser': 'closed', 'task': 'idle', 'message': '正在启动专用 Edge', 'url': '', 'login': 'unknown', 'current_keyword': '', 'updated_at': ''}
SEND_DEADLINE_SECONDS = 90


def now():
    return datetime.now().isoformat(timespec='seconds')


@contextmanager
def connect():
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def init_db():
    with connect() as con:
        con.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS leads (
          id INTEGER PRIMARY KEY, profile_url TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL, note_url TEXT, note_title TEXT, keyword TEXT,
          evidence TEXT, score INTEGER DEFAULT 0, status TEXT DEFAULT 'new',
          created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, time TEXT, level TEXT, message TEXT);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY, lead_id INTEGER NOT NULL,
          channel TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL,
          created_at TEXT, updated_at TEXT, UNIQUE(lead_id, channel));
        CREATE TABLE IF NOT EXISTS replies (id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE,
          sender TEXT, body TEXT, conversation_url TEXT, created_at TEXT, handled INTEGER DEFAULT 0);
        ''')
        import discovery
        discovery.init(con)
        import topic_state
        topic_state.init(con)
        import comment_flow
        comment_flow.init(con)
        import studio
        studio.init(con)


def write_diagnostic(text, stream_name='stdout'):
    """A closed desktop host pipe must never terminate a command worker."""
    try:
        stream = getattr(sys, stream_name, None)
        if stream is None:
            raise OSError('Diagnostic stream unavailable')
        stream.write(text.rstrip('\n') + '\n')
        stream.flush()
        return
    except (OSError, ValueError, AttributeError):
        pass
    try:
        with (DATA / 'backend-diagnostics.log').open('a', encoding='utf-8') as log:
            log.write(text.rstrip('\n') + '\n')
    except (OSError, ValueError):
        # Disk/full permissions failures cannot turn an observed event into
        # another failed command or prevent the shutdown queue from draining.
        pass


def event(message, level='info'):
    try:
        with connect() as con:
            con.execute('INSERT INTO events(time,level,message) VALUES(?,?,?)', (now(), level, message))
    except (sqlite3.Error, OSError) as exc:
        write_diagnostic(f'{now()} [logging] Event storage unavailable: {exc}', 'stderr')
    write_diagnostic(f'{now()} [{level}] {message}')


def update(**kwargs):
    with LOCK:
        STATE.update(kwargs, updated_at=now())


def settings():
    defaults = {'topic':'BIM','keywords': 'BIM建模接单\nRevit建模\nBIM工作室\n土建建模',
                'message': '你好，看到你分享的 BIM 建模内容。我们在做一款把土建平面图自动生成 3D 模型的工具，想邀请你体验，看看能否减少手动建模的工作量。有兴趣的话我可以发你体验地址。',
                'purpose':'','target_count':40,'scrolls': 3, 'interval_min':1, 'interval_max':3}
    with connect() as con:
        for row in con.execute('SELECT key,value FROM settings'):
            defaults[row['key']] = json.loads(row['value'])
    return defaults


class BrowserWorker:
    def __init__(self):
        self.context = None
        self.page = None
        self.pw = None
        self.visible = None

    @contextmanager
    def browser_operation(self, seconds=90):
        from browser_guard import BrowserGuard, BrowserOperationTimeout
        update(operation_deadline=time.time()+seconds)
        try:
            with BrowserGuard(self.pw, STOP, seconds,
                              lambda reason: update(message=reason, browser='closed', login='unknown')):
                yield
        except BrowserOperationTimeout:
            self.context = self.page = self.pw = None
            raise
        finally:
            update(operation_deadline=None)

    def ensure_driver(self):
        # Guards need an existing driver process, including on the first login.
        if not self.pw:
            from playwright.sync_api import sync_playwright
            self.pw=sync_playwright().start()
        return self.pw

    def launch(self,visible=True,navigate=True):
        if self.context:
            try:
                self.page.title()
                if self.visible == visible:
                    if visible:self.page.bring_to_front()
                    return
            except Exception:
                pass
            try:self.context.close()
            except Exception:pass
            self.context = self.page = None
        self.ensure_driver()
        update(browser='starting', message='正在打开专用 Edge 窗口' if visible else '正在连接后台浏览器，不占用鼠标和前台窗口')
        self.context = self.pw.chromium.launch_persistent_context(
            user_data_dir=str(DATA / 'edge-profile'), executable_path=find_edge(), headless=not visible,
            viewport=None if visible else {'width':1440,'height':1000}, no_viewport=visible, accept_downloads=False,
            args=['--start-maximized'] if visible else ['--autoplay-policy=user-gesture-required'])
        self.visible=visible
        if not visible:
            # Text analysis does not need video playback; avoid loading large media streams.
            self.context.route('**/*',lambda route:route.abort() if route.request.resource_type=='media' else route.continue_())
        self.context.set_default_timeout(6000)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        if navigate:self.page.goto('https://www.xiaohongshu.com/explore', wait_until='domcontentloaded', timeout=45000)
        update(browser='open',background=not visible, message='专用 Edge 已打开，请在该窗口登录小红书' if visible else '后台浏览器已连接，可继续正常使用自己的浏览器', url=self.page.url)
        event('专用浏览器已打开；登录资料保存在本机；'+('前台登录模式' if visible else '后台运行模式'))

    def background(self):
        # Even a reused page.title() can stall on a dead driver connection.
        self.ensure_driver()
        with self.browser_operation(45):
            self.launch(visible=False)
            # The native search layout can omit the sidebar identity entry.
            if urlsplit(self.page.url).path.startswith('/search_result'):
                self.page.goto('https://www.xiaohongshu.com/explore',wait_until='domcontentloaded',timeout=20000)
            self.check()
        if STATE['login']=='restricted':raise RuntimeError(STATE['message'])
        if STATE['login']!='ready':raise RuntimeError('后台登录未就绪，请点“登录小红书”在官方窗口处理后继续')

    def require_page(self):
        if not self.page or self.page.is_closed():
            update(browser='closed',login='unknown')
            raise RuntimeError('专用 Edge 已关闭，请点击“打开专用 Edge”')

    def recover_source_page(self):
        """Recover a crashed source tab only before any message submission."""
        try:
            self.page.bring_to_front()
        except Exception as exc:
            if 'Target crashed' not in str(exc):raise
            update(message='原页面已崩溃，正在重新打开小红书入口；尚未提交消息')
            self.page=self.context.new_page()
            self.page.goto('https://www.xiaohongshu.com/explore',wait_until='domcontentloaded',timeout=20000)
            event('已替换崩溃的入口页面；发送前仍检查收件人与会话历史')

    def snapshot(self):
        self.require_page()
        content = self.page.locator('body').inner_text(timeout=10000)
        elements = self.page.locator('input,textarea,[contenteditable="true"],button,a').evaluate_all('''els => els.filter(e => e.getBoundingClientRect().width && e.getBoundingClientRect().height).map(e => ({tag:e.tagName, text:(e.innerText||e.textContent||'').trim().slice(0,150), placeholder:e.getAttribute('placeholder'), role:e.getAttribute('role'), href:e.getAttribute('href'), type:e.getAttribute('type')})).slice(0,180)''')
        result = {'url': self.page.url, 'title': self.page.title(), 'text': content[:24000], 'elements': elements, 'time': now()}
        (DATA / 'page-observation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        self.page.screenshot(path=str(DATA / 'page.png'))
        update(url=self.page.url)
        return result

    def check(self,publish=True):
        snap = self.snapshot()
        text = snap['text']
        from adapter import platform_restriction
        restriction=platform_restriction(snap['url'],text)
        blocked = any(x in text for x in ['请完成验证', '访问频次异常', '操作过于频繁', '安全验证'])
        login_form = any(e.get('placeholder') and any(t in e['placeholder'] for t in ['手机号','验证码']) for e in snap['elements'])
        profile = any(e.get('href') and '/user/profile/' in e['href'] and e['text'].strip() == '我' for e in snap['elements'])
        if restriction:
            result=dict(login='restricted',message=restriction)
            STOP.set()
        elif blocked:
            result=dict(login='verification', message='页面要求验证，任务已暂停，请在 Edge 中处理')
            STOP.set()
        elif login_form:
            result=dict(login='required', message='请在专用 Edge 中完成登录，然后点击“检查登录”')
        elif profile:
            result=dict(login='ready', message='已检测到个人主页入口，可以开始搜索')
        else:
            result=dict(login='unknown', message='暂不能确认登录，请查看专用 Edge 并点击“检查登录”')
        if publish:
            update(**result)
            event(result['message'])
        return result

    def search(self, payload):
        import importlib, adapter
        importlib.reload(adapter)
        from adapter import collect_search
        self.require_page()
        cfg = settings()
        keywords = [x.strip() for x in str(payload.get('keywords', cfg['keywords'])).splitlines() if x.strip()]
        if not keywords:
            raise ValueError('请先填写搜索关键词')
        scrolls = max(1, min(20, int(payload.get('scrolls', cfg['scrolls']))))
        for keyword in keywords[:40]:
            if STOP.is_set():
                break
            update(current_keyword=keyword, message=f'正在搜索：{keyword}')
            event(f'搜索开始：{keyword}')
            for lead in collect_search(self.page, keyword, scrolls, STOP):
                with connect() as con:
                    con.execute('''INSERT OR IGNORE INTO leads(profile_url,name,note_url,note_title,keyword,evidence,score,created_at,updated_at)
                      VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(profile_url) DO UPDATE SET
                      name=excluded.name,note_url=CASE WHEN excluded.score>=leads.score THEN excluded.note_url ELSE leads.note_url END,
                      note_title=CASE WHEN excluded.score>=leads.score THEN excluded.note_title ELSE leads.note_title END,
                      evidence=CASE WHEN excluded.score>=leads.score THEN excluded.evidence ELSE leads.evidence END,
                      keyword=CASE WHEN excluded.score>=leads.score THEN excluded.keyword ELSE leads.keyword END,
                      score=MAX(leads.score,excluded.score),updated_at=excluded.updated_at''', (lead['profile_url'],lead['name'],lead['note_url'],lead['note_title'],keyword,lead['evidence'],lead['score'],now(),now()))
            event(f'关键词完成：{keyword}')
            if len(keywords) > 1 and STOP.wait(3):
                break
        update(current_keyword='', message='搜索已暂停，已保存找到的线索' if STOP.is_set() else '本轮搜索完成，线索已去重保存')

    def open_lead(self, payload):
        self.require_page()
        with connect() as con:
            row = con.execute('SELECT * FROM leads WHERE id=?', (int(payload['id']),)).fetchone()
        if not row:
            raise ValueError('线索不存在')
        self.page.goto(row['profile_url'] if payload.get('profile') else (row['note_url'] or row['profile_url']), wait_until='domcontentloaded')
        self.page.bring_to_front()
        update(url=self.page.url, message=f'已打开 {row["name"]} 的来源内容')

    def send(self, payload):
        import importlib, adapter
        importlib.reload(adapter)
        from adapter import send_direct_message
        self.require_page()
        cfg = settings()
        message = str(payload.get('message', cfg['message'])).strip()
        if not message or len(message) > 1000:
            raise ValueError('请保存 1～1000 字的招呼话术')
        ids = payload.get('ids', [])[:50]
        sent_count = 0
        for index, lead_id in enumerate(ids):
            if STOP.is_set():
                break
            with connect() as con:
                lead = con.execute('SELECT * FROM leads WHERE id=?',(int(lead_id),)).fetchone()
                if not lead or lead['status'] in ('ignored','replied','do_not_contact'):
                    continue
                previous = con.execute('SELECT status FROM contacts WHERE lead_id=? AND channel=?', (lead_id,'dm')).fetchone()
                if previous and previous['status'] != 'not_sent':
                    event(f'跳过已处理或待核实的联系人：{lead["name"]}')
                    continue
                if previous:
                    con.execute('UPDATE contacts SET message=?,status=?,updated_at=? WHERE lead_id=? AND channel=?',(message,'pending',now(),lead_id,'dm'))
                else:
                    con.execute('INSERT INTO contacts(lead_id,channel,message,status,created_at,updated_at) VALUES(?,?,?,?,?,?)', (lead_id,'dm',message,'pending',now(),now()))
            label = f'{index+1}/{len(ids)} · {lead["name"]}'
            update(message=f'{label}：准备打开会话')
            try:
                with self.browser_operation(SEND_DEADLINE_SECONDS):
                    self.recover_source_page()
                    result = send_direct_message(self.page, dict(lead), message, STOP,
                                                 progress=lambda stage: update(message=f'{label}：{stage}'))
            except Exception:
                with connect() as con:
                    con.execute('UPDATE contacts SET status=?,updated_at=? WHERE lead_id=? AND channel=?',('needs_review',now(),lead_id,'dm'))
                raise
            with connect() as con:
                con.execute('UPDATE contacts SET status=?,updated_at=? WHERE lead_id=? AND channel=?',(result,now(),lead_id,'dm'))
                if result == 'sent':
                    con.execute('UPDATE leads SET status=?,updated_at=? WHERE id=?',('contacted',now(),lead_id))
            event(f'{lead["name"]}：' + ('已确认发送' if result == 'sent' else '发送未确认，请人工检查'))
            if result != 'sent':
                break
            sent_count += 1
            if index < len(ids)-1:
                delay=random.uniform(1,3)
                update(message=f'{label}：已发送。随机等待 {delay:.1f} 秒后处理下一位')
                if STOP.wait(delay):break
        update(message=f'发送已暂停，本轮已确认发送 {sent_count} 位' if STOP.is_set() else f'本轮结束，已确认发送 {sent_count} 位；发送结果见候选名单')

    def prepare(self, payload):
        import importlib, adapter
        importlib.reload(adapter)
        self.require_page()
        with connect() as con:
            lead=con.execute('SELECT * FROM leads WHERE id=?',(int(payload['id']),)).fetchone()
        if not lead:
            raise ValueError('线索不存在')
        if lead['status'] in ('ignored','do_not_contact'):
            raise ValueError('此线索已标记为不联系')
        with self.browser_operation(SEND_DEADLINE_SECONDS):
            self.recover_source_page()
            chat=adapter.prepare_chat(self.page,dict(lead),STOP,
                                      progress=lambda stage:update(message=f'{lead["name"]}：{stage}'))
            adapter.observe(chat,'prepared-chat.json')
        update(message=f'已核对并打开 {lead["name"]} 的会话，未发送消息')
        event(STATE['message'])

    def inbox(self, payload):
        import importlib, adapter
        importlib.reload(adapter)
        from adapter import collect_replies
        self.require_page()
        with connect() as con:
            leads=[dict(r) for r in con.execute("SELECT leads.* FROM leads JOIN contacts ON leads.id=contacts.lead_id WHERE contacts.status='sent' AND leads.status!='do_not_contact'")]
        if not leads:
            update(message='还没有已发送的联系人，暂无需要检查的回复')
            return
        added=0
        for item in collect_replies(self.page, leads, STOP):
            with connect() as con:
                cur=con.execute('INSERT OR IGNORE INTO replies(fingerprint,sender,body,conversation_url,created_at) VALUES(?,?,?,?,?)', (item['fingerprint'],item['sender'],item['body'],item['url'],now()))
                if cur.rowcount:
                    added+=1
                    status='do_not_contact' if any(x in item['body'] for x in ('不需要','不要发','别发','不感兴趣','别联系','退订')) else 'replied'
                    con.execute('UPDATE leads SET status=?,updated_at=? WHERE id=?',(status,now(),item['lead_id']))
        update(message=f'回复检查完成：发现 {added} 条新消息' if not STOP.is_set() else '回复检查已暂停')
        event(STATE['message'])

    def monitor(self, payload):
        while not STOP.is_set():
            self.inbox(payload)
            update(message='正在监测回复，每 60 秒检查一次；可随时暂停')
            if STOP.wait(60): break
        update(message='回复监测已暂停')

    def run(self):
        while True:
            command, payload = COMMANDS.get()
            update(task=command)
            try:
                if command == 'studio':
                    import studio
                    studio.run(sys.modules[__name__],self,payload)
                elif command == 'account':
                    import studio
                    studio.account(sys.modules[__name__],self,payload)
                elif command == 'login_session':
                    import login_session
                    login_session.import_session(sys.modules[__name__],self,payload)
                elif command == 'launch':
                    self.launch()
                    self.check()
                elif command == 'check': self.check()
                elif command == 'snapshot': self.snapshot()
                elif command == 'benchmark':
                    import importlib, benchmark_collect
                    importlib.reload(benchmark_collect)
                    benchmark_collect.run(self,payload,STOP)
                elif command == 'search': self.search(payload)
                elif command == 'discover':
                    import discovery
                    self.background()
                    discovery.run(self,payload,STOP,connect,update,event)
                elif command in ('comment_inspect','comment_find','comment_send'):
                    import importlib,comment_flow
                    importlib.reload(comment_flow)
                    getattr(comment_flow,command.removeprefix('comment_'))(self,payload,STOP,connect,update,event)
                elif command == 'open':
                    self.launch(visible=True);self.open_lead(payload)
                elif command == 'send':
                    self.background();self.send(payload)
                elif command == 'inbox':
                    self.background();self.inbox(payload)
                elif command == 'prepare':
                    self.launch(visible=True);self.prepare(payload)
                elif command == 'monitor':
                    self.background();self.monitor(payload)
                elif command == 'close':
                    if self.context: self.context.close()
                    self.context = None
                    update(browser='closed',login='unknown',message='专用 Edge 已关闭，登录资料已保存')
                elif command == 'shutdown':
                    try:
                        if self.context: self.context.close()
                    finally:
                        try:
                            if self.pw: self.pw.stop()
                        finally:
                            update(browser='closed',login='unknown',message='程序已退出，数据已保存')
                            if SERVER:
                                threading.Thread(target=SERVER.shutdown,daemon=True).start()
            except Exception as exc:
                from browser_guard import BrowserOperationTimeout
                message = str(exc)[:650] if isinstance(exc,BrowserOperationTimeout) else ('任务已暂停，已保存现有进度' if STOP.is_set() else str(exc)[:650])
                update(message=message)
                event(message, 'info' if STOP.is_set() else 'error')
                if not STOP.is_set(): write_diagnostic(traceback.format_exc(), 'stderr')
                try:
                    if self.page and not self.page.is_closed():
                        self.page.screenshot(path=str(DATA / 'last-error.png'))
                except Exception:
                    pass
            finally:
                update(task='idle')
                COMMANDS.task_done()


def request_command(data):
    # Share studio admission through queue publication, including shutdown/pause.
    import studio
    with studio.ADMISSION_LOCK:
        cmd=data['command']
        if os.environ.get('XIAOHONGMAO_DESKTOP_SMOKE')=='1' and cmd not in ('shutdown','pause'):
            return {'error':'客户端离线测试中，未启动平台操作'},409
        if cmd=='shutdown':
            if not SHUTTING_DOWN.is_set():
                SHUTTING_DOWN.set();STOP.set();COMMANDS.put(('shutdown',{}))
                update(message='正在停止任务并退出，数据会保留')
            return {'ok':True},200
        if SHUTTING_DOWN.is_set():return {'error':'程序正在退出，请稍后重新打开'},409
        if cmd=='pause':
            STOP.set();update(message='已请求暂停，将在当前页面操作结束后停止')
            return {'ok':True},200
        if cmd not in ('account','launch','check','snapshot','search','discover','open','send','inbox','close','prepare','monitor','benchmark','comment_inspect','comment_find','comment_send','login_session'):
            raise ValueError('不支持的指令')
        if studio.is_busy(sys.modules[__name__]):return {'error':'当前操作尚未结束，请稍后再试'},409
        if cmd=='login_session':
            import login_session,re
            if not re.fullmatch(r'[a-fA-F0-9-]{32,36}',str(data.get('transfer_id',''))):raise ValueError('登录连接标识无效')
            data['cookies']=login_session.validate_cookies(data.get('cookies'))
            data['expected_profile']=login_session.validate_profile(data.get('expected_profile'))
            update(login_transfer_id=data['transfer_id'],login_transfer_status='queued',
                   login='connecting',account=None,login_verified_profile=None,
                   message='正在检测登录：等待后台连接…')
        STOP.clear();COMMANDS.put((cmd,data))
        return {'ok':True},200


def request_topic(data):
    import studio,topic_state
    with studio.ADMISSION_LOCK:
        if SHUTTING_DOWN.is_set():return {'error':'程序正在退出，不能切换话题'},409
        if studio.is_busy(sys.modules[__name__]):return {'error':'请先暂停当前任务，再切换话题'},409
        cfg=settings()
        with connect() as con:result=topic_state.switch(con,cfg,str(data['topic']))
        update(message='已切换话题；搜索、联系目的与消息草稿分别保存')
        return result,200


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def reply(self, body, status=200, content_type='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body,ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

    def storage_failure(self,exc):
        return self.reply({'error':'本地数据暂时无法读写，请检查磁盘空间和数据库状态。此次请求没有自动重试；内容可能未保存，发送结果不明时请先核实，勿重复发送。','detail':str(exc)[:1200]},503)

    def do_GET(self):
        try:return self.get_response()
        except sqlite3.Error as exc:return self.storage_failure(exc)

    def get_response(self):
        if not self.valid_host(): return self.reply({'error':'Invalid host'},403)
        path = urlsplit(self.path).path
        if path in ('/','/legacy'):
            html = (ROOT / ('ui.html' if path=='/' else 'legacy-ui.html')).read_text(encoding='utf-8').replace('__TOKEN__',TOKEN)
            return self.reply(html.encode('utf-8'), content_type='text/html; charset=utf-8')
        if self.headers.get('X-App-Token') != TOKEN:
            return self.reply({'error':'Unauthorized'},403)
        if path == '/api/update':
            import updater
            return self.reply(updater.manager(sys.modules[__name__]).status())
        if path == '/api/studio':
            import studio
            query=parse_qs(urlsplit(self.path).query)
            try:
                with connect() as con:result=studio.state(con,query.get('project',[None])[0])
                import workflow_ai,deepseek_client,ai_config
                result.update(state=dict(STATE),ai={**ai_config.public(deepseek_client.ROOT),'budget':workflow_ai.budget()})
                return self.reply(result)
            except (ValueError,TypeError):return self.reply({'error':'项目不存在'},404)
        if path == '/api/studio-dm-proof':
            try:
                query=parse_qs(urlsplit(self.path).query);pid=int(query.get('project',['0'])[0]);did=int(query.get('draft',['0'])[0]);index=int(query.get('item',['-1'])[0])
            except ValueError:return self.reply({'error':'参数错误'},400)
            with connect() as con:
                row=con.execute("SELECT d.items FROM studio_drafts d JOIN studio_projects p ON p.id=d.project_id WHERE d.project_id=? AND d.id=? AND d.channel='dm' AND p.archived_at IS NULL",(pid,did)).fetchone()
                items=json.loads(row[0]) if row else []
                if not 0<=index<len(items) or items[index].get('status') not in ('sent','needs_review'):return self.reply({'error':'没有对应的私信截图'},404)
                prefix='sent' if items[index]['status']=='sent' else 'send-review'
            proof=DATA/f'{prefix}-project-{pid}-draft-{did}-{index}.png'
            return self.reply(proof.read_bytes(),content_type='image/png') if proof.is_file() else self.reply({'error':'截图未保存'},404)
        if path == '/api/studio-frame':
            try:
                query=parse_qs(urlsplit(self.path).query)
                pid=int(query.get('project',['0'])[0]);frame_id=int(query.get('frame',['0'])[0])
            except ValueError:return self.reply({'error':'参数错误'},400)
            with connect() as con:
                if not con.execute('SELECT 1 FROM studio_projects WHERE id=? AND archived_at IS NULL',(pid,)).fetchone():return self.reply({'error':'项目不存在或已归档'},404)
                if frame_id:
                    row=con.execute('SELECT image FROM studio_frames WHERE project_id=? AND id=?',(pid,frame_id)).fetchone()
                    return self.reply(bytes(row[0]),content_type='image/jpeg') if row else self.reply({'error':'该步骤未保存画面或已超过保留数量'},404)
            file=DATA/f'studio-frame-{pid}.jpg'
            return self.reply(file.read_bytes(),content_type='image/jpeg') if file.exists() else self.reply({'error':'暂无执行画面'},404)
        if path == '/api/state':
            import topic_state
            import discovery
            cfg=settings()
            with connect() as con:
                leads = topic_state.leads(con,cfg['topic'],cfg.get('purpose',''))
                events = [dict(x) for x in con.execute('SELECT * FROM events ORDER BY id DESC LIMIT 80')]
                replies = [dict(x) for x in con.execute('SELECT * FROM replies ORDER BY id DESC LIMIT 300')]
                contacts = [dict(x) for x in con.execute('SELECT * FROM contacts ORDER BY id DESC LIMIT 1000')]
                count = con.execute('SELECT COUNT(*) FROM leads').fetchone()[0]
                run = con.execute('SELECT * FROM discovery_runs WHERE topic=? ORDER BY id DESC LIMIT 1',(cfg['topic'],)).fetchone()
                topics=[x[0] for x in con.execute('SELECT topic FROM topic_settings ORDER BY rowid DESC')]
                reply_accounts=[dict(x) for x in con.execute('SELECT id,name,profile_url FROM leads WHERE id IN (SELECT lead_id FROM contacts)')]
                search_preview=discovery.preview(con,cfg['topic'])
                import comment_flow
                comments=comment_flow.state(con)
            import workflow_ai
            try:
                from deepseek_client import credential
                configured=bool(credential())
            except (OSError,RuntimeError):configured=False
            return self.reply({'state': dict(STATE), 'leads': leads,'reply_accounts':reply_accounts,'events': events, 'replies': replies,'contacts':contacts, 'settings': cfg,'topics':topics,'total': count,'discovery':dict(run) if run else None,'search_preview':search_preview,'comments':comments,'ai':{'configured':configured,'budget':workflow_ai.budget()}})
        if path == '/api/observation':
            p = DATA / 'page-observation.json'
            return self.reply(json.loads(p.read_text(encoding='utf-8')) if p.exists() else {})
        if path == '/api/export':
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(['客户名称','主页','来源笔记','标题','关键词','匹配证据','匹配分','状态','发现时间'])
            with connect() as con:
                for r in con.execute('SELECT name,profile_url,note_url,note_title,keyword,evidence,score,status,created_at FROM leads ORDER BY id'):
                    writer.writerow([("'" + str(v)) if str(v).startswith(('=','+','-','@','\t','\r')) else v for v in r])
            return self.reply(('\ufeff'+buf.getvalue()).encode('utf-8'),content_type='text/csv; charset=utf-8')
        return self.reply({'error':'Not found'},404)

    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-App-Token') != TOKEN:
            return self.reply({'error':'Unauthorized'},403)
        if self.headers.get('Origin') not in (None, f'http://127.0.0.1:{self.server.server_port}'):
            return self.reply({'error':'Invalid origin'},403)
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 32768: raise ValueError('请求大小不正确')
            def finite_number(value):
                result=float(value)
                if not math.isfinite(result):raise ValueError('请求中不能包含非有限数字')
                return result
            data = json.loads(self.rfile.read(length),parse_float=finite_number,parse_constant=finite_number)
            if not isinstance(data,dict):raise ValueError('请求内容必须是 JSON 对象')
            path = urlsplit(self.path).path
            if path == '/api/update':
                import updater
                try:return self.reply(updater.handle(sys.modules[__name__],data))
                except RuntimeError as exc:return self.reply({'error':str(exc)},400)
            if path == '/api/studio':
                import studio
                return self.reply(studio.request(sys.modules[__name__],data))
            if path == '/api/ai-settings':
                import ai_config
                try:return self.reply(ai_config.handle(sys.modules[__name__],data))
                except RuntimeError as exc:return self.reply({'error':str(exc)},400)
            if path == '/api/topic':
                body,status=request_topic(data)
                return self.reply(body,status)
            if path == '/api/settings':
                allowed = {'topic','keywords','message','purpose','target_count','scrolls'}
                current=settings()
                if 'topic' in data and data['topic']!=current['topic']:raise ValueError('请先通过切换话题保存独立草稿')
                with connect() as con:
                    for k,v in data.items():
                        if k in allowed:
                            if k in ('topic','keywords','message','purpose'):
                                v = str(v)[:120 if k=='topic' else 5000]
                            else:
                                v = max(1, min(300, int(v)))
                            con.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',(k,json.dumps(v,ensure_ascii=False)))
                            current[k]=v
                    import topic_state
                    topic_state.save(con,current)
                return self.reply({'ok': True})
            if path == '/api/lead':
                if data['status'] not in ('new','qualified','ignored','do_not_contact','replied'):
                    raise ValueError('不支持的状态')
                with connect() as con:
                    con.execute('UPDATE leads SET status=?,updated_at=? WHERE id=?',(data['status'],now(),int(data['id'])))
                return self.reply({'ok': True})
            if path == '/api/reply':
                with connect() as con:
                    con.execute('UPDATE replies SET handled=1 WHERE id=?',(int(data['id']),))
                return self.reply({'ok':True})
            if path == '/api/command':
                body,status=request_command(data)
                return self.reply(body,status)
            return self.reply({'error':'Not found'},404)
        except sqlite3.Error as exc:
            return self.storage_failure(exc)
        except (ValueError,KeyError,TypeError) as exc:
            return self.reply({'error':str(exc)},400)


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


@contextmanager
def instance_owner():
    """Own the data directory before migrations or crash recovery touch it."""
    with (DATA/'workbench.lock').open('a+b') as lock_file:
        lock_file.seek(0)
        if not lock_file.read(1):lock_file.write(b'0');lock_file.flush()
        lock_file.seek(0);acquired=False
        try:
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(lock_file.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(lock_file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                acquired=True
            except OSError:raise RuntimeError('工作台已在运行，请使用现有窗口；未启动第二个后台进程') from None
            yield
        finally:
            if acquired:
                lock_file.seek(0)
                if os.name=='nt':msvcrt.locking(lock_file.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(lock_file.fileno(),fcntl.LOCK_UN)

def main():
    with instance_owner():return _serve()

def _serve():
    global SERVER
    init_db()
    with connect() as con:
        con.execute("UPDATE studio_jobs SET status='failed',error=? WHERE status IN ('running','queued')",(json.dumps({'title':'后台程序已重启','detail':'任务中断，未自动重试','advice':'可恢复采集；发送中的条目请先核实。'},ensure_ascii=False),))
        import project_store
        project_store.recover(con)
    server = None
    for port in range(8765,8786):
        try:
            server = LocalServer(('127.0.0.1',port),Handler)
            break
        except OSError: continue
    if not server: raise RuntimeError('本地工作台端口不可用')
    SERVER=server
    info = {'url':f'http://127.0.0.1:{server.server_port}','pid':os.getpid(),'token':TOKEN}
    (DATA / 'runtime.json').write_text(json.dumps(info),encoding='utf-8')
    worker = BrowserWorker()
    threading.Thread(target=worker.run,daemon=True).start()
    if '--no-browser' not in sys.argv:
        COMMANDS.put(('launch',{}))
    event(f'工作台已启动：{info["url"]}')
    server.serve_forever()
    server.server_close()


if __name__ == '__main__': main()
