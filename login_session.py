"""Move an explicitly completed official login into the local execution browser.

Credentials stay in the two local browser stores. No cookie file, event payload,
project record, or AI request is created by this module.
"""
import json
import math
import re
import time

DOMAINS={'xiaohongshu.com','www.xiaohongshu.com'}

def validate_profile(value):
    if not isinstance(value,str) or not re.fullmatch(r'https://www\.xiaohongshu\.com/user/profile/[A-Za-z0-9]+',value):
        raise ValueError('尚未读到登录账号身份，请完成官方登录后重试')
    return value

def validate_cookies(value):
    if not isinstance(value,list) or not 0<len(value)<=100:
        raise ValueError('登录状态无效，请在客户端完成官方登录后重试')
    if len(json.dumps(value,ensure_ascii=False).encode('utf-8'))>24576:
        raise ValueError('登录状态过大，未连接工作台')
    result=[];seen=set()
    for item in value:
        if not isinstance(item,dict):raise ValueError('登录状态格式无效')
        domain=item.get('domain','')
        name=item.get('name','');body=item.get('value','');path=item.get('path','/')
        if not isinstance(domain,str) or domain.lower() not in ('xiaohongshu.com','.xiaohongshu.com','www.xiaohongshu.com','.www.xiaohongshu.com'):
            raise ValueError('只能连接小红书官方登录状态')
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_!#$%&\x27*+.^`|~-]{1,128}',name):
            raise ValueError('登录状态格式无效')
        if not isinstance(body,str) or len(body)>4096 or any(ord(c)<32 or ord(c)==127 for c in body):
            raise ValueError('登录状态格式无效')
        if not isinstance(path,str) or not path.startswith('/') or len(path)>512 or any(ord(c)<32 for c in path):
            raise ValueError('登录状态路径无效')
        key=(domain.lower(),path,name)
        if key in seen:raise ValueError('登录状态包含重复项')
        seen.add(key)
        cookie={'name':name,'value':body,'domain':domain.lower(),'path':path,
                'secure':bool(item.get('secure',False)),'httpOnly':bool(item.get('httpOnly',False))}
        same=item.get('sameSite','Lax')
        if same not in ('Strict','Lax','None'):raise ValueError('登录状态格式无效')
        cookie['sameSite']=same
        expiry=item.get('expires',-1)
        if isinstance(expiry,bool) or not isinstance(expiry,(float,int)) or not math.isfinite(expiry):
            raise ValueError('登录状态有效期无效')
        if expiry!=-1:
            if expiry<=time.time():continue
            cookie['expires']=expiry
        result.append(cookie)
    if not any(c['name']=='web_session' and c['value'] for c in result):
        raise ValueError('尚未完成小红书登录，请先扫码或完成官方验证')
    return result

def import_session(app,worker,payload):
    transfer=payload['transfer_id'];previous=None;checked={};stage='validate'
    start=time.perf_counter();timings={}
    def progress(name,message):
        nonlocal stage
        timings[stage]=round(time.perf_counter()-start,3)
        stage=name
        app.update(login='connecting',login_transfer_status='connecting',login_transfer_stage=name,
                   login_transfer_timings=dict(timings),message=message)
    app.update(login_transfer_id=transfer,login_transfer_status='connecting',account=None,
               login='connecting',login_verified_profile=None,login_transfer_error=None,
               message='正在检测登录：准备连接后台…')
    try:
        cookies=validate_cookies(payload['cookies']);expected=validate_profile(payload.get('expected_profile'))
        progress('driver_start','正在检测登录：初始化后台浏览器…')
        worker.ensure_driver()
        with worker.browser_operation(75):
            progress('browser_start','正在检测登录：启动后台浏览器…')
            # Import before the first navigation; do not first load a logged-out feed.
            worker.launch(visible=False,navigate=False)
            previous=worker.context.cookies()
            progress('session_import','正在检测登录：连接官方登录状态…')
            worker.context.clear_cookies()
            worker.context.add_cookies(cookies)
            progress('page_load','正在检测登录：等待官方页面响应…')
            worker.page.goto('https://www.xiaohongshu.com/explore',wait_until='domcontentloaded',timeout=25000)
            try:
                worker.page.locator('a[href*="/user/profile/"]:visible').filter(has_text=re.compile(r'^\s*我\s*$')).first.wait_for(state='visible',timeout=12000)
            except Exception:
                pass
            progress('identity_check','正在检测登录：核对实际登录账号…')
            checked=worker.check(publish=False)
            if checked.get('login')!='ready':
                raise RuntimeError('identity not ready')
            import adapter
            href=worker.page.locator('a[href*="/user/profile/"]:visible').filter(has_text=re.compile(r'^\s*我\s*$')).first.get_attribute('href')
            actual=adapter.canonical_profile('https://www.xiaohongshu.com'+href if href.startswith('/') else href)
            if actual!=expected:
                stage='identity_mismatch'
                raise RuntimeError('identity mismatch')
            progress('profile_read','正在检测登录：读取账号资料…')
            info={'profile_url':actual,'name':'小红书账号'}
            try:
                import studio
                info=studio.read_account_profile(app,worker)
            except Exception:
                pass  # Optional avatar metadata cannot invalidate verified identity.
        timings[stage]=round(time.perf_counter()-start,3)
        # Publish success once, only after the actual identity and browser guard pass.
        app.update(login='ready',account=info,login_verified_profile=actual,
                   login_transfer_status='complete',login_transfer_stage='complete',
                   login_transfer_seconds=round(time.perf_counter()-start,3),login_transfer_timings=timings,
                   message='登录核验成功，可以开始使用工作台')
        app.event('客户端登录已核验并连接；未保存或记录会话凭据')
    except Exception as exc:
        restricted=checked.get('login')=='restricted' or app.STATE.get('login')=='restricted'
        restored=True
        if previous is not None:
            try:
                worker.context.clear_cookies();worker.context.add_cookies(previous)
            except Exception:restored=False
        reasons={'driver_start':'后台浏览器初始化失败','browser_start':'后台浏览器启动失败',
                 'session_import':'登录状态连接失败','page_load':'官方页面加载未完成',
                 'identity_check':'后台页面尚未确认登录','identity_mismatch':'后台账号与登录账号不一致',
                 'validate':'登录资料校验失败','profile_read':'账号资料读取中断'}
        message=reasons.get(stage,'登录连接失败')+'；尚未登录工作台，请重新检测。'
        if not restored:message+='旧登录状态未能恢复，请重新登录。'
        if restricted:message=checked.get('message') or '小红书提示安全限制，请在官方页面处理'
        if checked.get('login')=='verification':message='官方页面要求验证，请完成官方验证后重新检测。'
        app.update(login_transfer_status='failed',login='restricted' if restricted else 'unknown',account=None,
                   login_verified_profile=None,login_transfer_stage=stage,
                   login_transfer_error=type(exc).__name__,login_transfer_seconds=round(time.perf_counter()-start,3),
                   login_transfer_timings=timings,message=message)
        # Only a stage and exception class are recorded. Exceptions may contain credentials.
        app.event(message+'（阶段：'+stage+'）','error')
    finally:
        payload.pop('cookies',None)
