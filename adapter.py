"""Xiaohongshu visible-page adapter. No private APIs or cookie export."""
import hashlib
import json
import re
import random
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qs, unquote
from app_paths import data_dir

DATA = data_dir(Path(__file__).resolve().parent)

INCOMING_MESSAGES_JS = '''rows=>rows.flatMap(row=>{
  const content=row.querySelector('.chat-item__content');
  if(!content || content.classList.contains('chat-item__content--right') || row.querySelector('.chat-item__bubble--me') || row.querySelector('img[alt="我的头像"]'))return [];
  const bubble=row.querySelector('.chat-item__bubble');
  if(!bubble)return [];
  const text=bubble.innerText.trim();
  return [{id:row.getAttribute('data-message-id'),body:text||'[非文本消息，请打开会话查看]'}];
})'''


def platform_restriction(url,text):
    if urlsplit(url).path.rstrip('/')=='/website-login/error' and re.search(r'\b300012\b',text):
        return '小红书安全限制（300012）：平台提示 IP 存在风险，已停止请求'
    return None


def checkpoint(page, stop):
    if stop.is_set():
        raise RuntimeError('任务已暂停')
    if urlsplit(page.url).hostname != 'www.xiaohongshu.com':
        raise RuntimeError('页面已离开小红书，任务停止')
    if urlsplit(page.url).path.rstrip('/')=='/website-login/error':
        reason=platform_restriction(page.url,page.locator('body').inner_text(timeout=3000))
        if reason:
            stop.set();raise RuntimeError(reason)
    # Inspect only dialogs / login controls: ordinary notes may discuss verification.
    for text in ('请完成验证', '访问频次异常', '操作过于频繁', '安全验证'):
        matches=page.get_by_text(text,exact=True)
        for index in range(matches.count()):
            node=matches.nth(index)
            if not node.is_visible():continue
            content=node.evaluate('''e=>!!e.closest('#detail-title,#detail-desc,.comments-container,.note-item')&&!e.closest('[role="dialog"],[role="alert"],[aria-modal="true"]')''')
            if content:continue
            stop.set()
            raise RuntimeError('页面提示：'+text+'，已停止，请在专用 Edge 中处理')
    for label in ('输入手机号', '输入验证码'):
        item = page.get_by_placeholder(label, exact=True)
        if item.count() and item.first.is_visible():
            stop.set()
            raise RuntimeError('登录已失效，请在专用 Edge 中登录')


def paced(stop):
    if stop.wait(random.uniform(3,5)):
        raise RuntimeError('任务已暂停')


def collection_pause(stop):
    """Short collection pacing in integer milliseconds; cancellation stays immediate."""
    if stop.is_set():raise RuntimeError('任务已暂停')
    milliseconds=random.randint(100,900)
    if stop.wait(milliseconds/1000):raise RuntimeError('任务已暂停')
    return milliseconds


def observe(page, filename='adapter-observation.json'):
    result = {
        'url': page.url,
        'text': page.locator('body').inner_text()[:24000],
        'elements': page.locator('input,textarea,[contenteditable="true"],button,a').evaluate_all('''els => els.filter(e=>e.getBoundingClientRect().width && e.getBoundingClientRect().height).map(e=>({tag:e.tagName,text:(e.innerText||e.textContent||'').trim().slice(0,200),value:e.value,placeholder:e.getAttribute('placeholder'),href:e.getAttribute('href'),class:e.className,html:e.outerHTML.slice(0,1100)})).slice(0,200)''')
    }
    (DATA / filename).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def canonical_profile(url):
    parts = urlsplit(url)
    if parts.hostname != 'www.xiaohongshu.com' or not re.fullmatch(r'/user/profile/[a-zA-Z0-9]+',parts.path):
        raise ValueError('作者链接格式不正确')
    return urlunsplit(('https',parts.netloc,parts.path,'',''))


def classify(title, name):
    text = (title + ' ' + name).lower()
    domain = [word for word in ('bim','revit','土建','建筑建模') if word in text]
    intent = [word for word in ('接单','工作室','代建','代做','代画','承接','建模服务','外包','建模团队','交付','成交') if word in text]
    demand = [word for word in ('求助','求推荐','自动建模','效率','手动','太慢') if word in text]
    if not domain:
        return 0, '未检测到 BIM / Revit / 土建相关内容'
    score = min(100, 35 + min(len(domain),2)*10 + min(len(intent),2)*20 + min(len(demand),2)*10)
    reasons = ['相关领域：' + '、'.join(domain)]
    if intent: reasons.append('服务线索：'+'、'.join(intent))
    if demand: reasons.append('需求线索：'+'、'.join(demand))
    reasons.append('仅根据公开标题和昵称初筛，需求待核实')
    return score, '；'.join(reasons)


def collect_search(page, keyword, scrolls, stop, filter_rules=True, dedupe_authors=True, readiness=True, max_items=None, video_only=False):
    checkpoint(page,stop)
    if not readiness:observe(page,'before-search.json')
    search = page.locator('#search-input-in-feeds')
    if not search.count():
        search = page.locator('#search-input-ai')
    if not search.count():
        search = page.locator('#search-input')
    if not search.count():
        search = page.get_by_placeholder('搜索小红书', exact=True)
    if not search.count():
        # Search page may use a differently labelled input; discover by its actual placeholder.
        labels = page.locator('input,textarea').evaluate_all('els=>els.filter(e=>e.getBoundingClientRect().width && e.getBoundingClientRect().height).map(e=>e.placeholder)')
        valid = [x for x in labels if '搜索' in x and '手机号' not in x]
        if not valid and len(labels)==1:
            valid = labels
        if len(valid) != 1:
            observe(page)
            raise RuntimeError('搜索框结构变化，已保存页面供适配')
        search = page.get_by_placeholder(valid[0],exact=True)
    collection_pause(stop) if readiness else paced(stop)
    search.first.fill(keyword)
    if search.first.input_value() != keyword:
        raise RuntimeError('搜索框尚未就绪，请重试')
    collection_pause(stop) if readiness else paced(stop)
    page.keyboard.press('Enter')
    if not readiness:observe(page,'after-search-input.json')
    page.wait_for_url(lambda url: '/search_result' in urlsplit(url).path and unquote(parse_qs(urlsplit(url).query).get('keyword',[''])[0])==keyword,
                      wait_until='domcontentloaded', timeout=15000)
    try:
        page.locator('a[href*="/search_result/"],a[href*="/explore/"]').first.wait_for(state='attached',timeout=12000)
    except Exception:
        # Other releases use /explore/<id> for search cards.
        checkpoint(page,stop)
    if video_only:
        page.get_by_text('筛选',exact=True).hover(timeout=5000)
        tag=page.locator('div.tags:not([aria-hidden="true"])').filter(has_text=re.compile(r'^视频$'))
        tag.wait_for(state='visible',timeout=5000)
        if tag.count()!=1:raise RuntimeError('无法唯一确定视频筛选项，未继续')
        if 'active' not in (tag.get_attribute('class') or '').split():tag.click(timeout=5000)
        if 'active' not in (tag.get_attribute('class') or '').split():raise RuntimeError('视频筛选没有生效')
        page.mouse.move(400,100)
        page.wait_for_timeout(1200)
        checkpoint(page,stop)
    if not readiness:observe(page, 'search-observation.json')
    seen = set()
    unchanged = 0
    for index in range(scrolls):
        checkpoint(page,stop)
        cards = page.locator('a[href*="/user/profile/"]').evaluate_all('''authors => authors.filter(a=>a.getBoundingClientRect().width && a.getBoundingClientRect().height && a.innerText.trim()!=='我').flatMap(a=>{
          let box=a.parentElement;
          for(let i=0;box && i<6;i++,box=box.parentElement){
            const notes=[...box.querySelectorAll('a[href]')].filter(n=>/\\/(explore|search_result)\\/[a-zA-Z0-9]+/.test(n.getAttribute('href')));
            const people=box.querySelectorAll('a[href*="/user/profile/"]');
            if(notes.length && people.length===1){
              const titled=notes.find(n=>n.innerText.trim());
              return [{name:a.innerText.trim(), profile_url:a.href, note_url:(titled||notes[0]).href, note_title:titled?titled.innerText.trim():box.innerText.trim().split('\\n')[0]}];
            }
          }
          return [];
        })''')
        new_count = 0
        for row in cards:
            row['name'] = row['name'].splitlines()[0].strip()
            row['profile_url'] = canonical_profile(row['profile_url'])
            identity=row['profile_url'] if dedupe_authors else urlsplit(row['note_url']).path.rsplit('/',1)[-1]
            if identity in seen:
                continue
            seen.add(identity)
            new_count += 1
            row['score'],row['evidence'] = classify(row['note_title'],row['name']) if filter_rules else (0,'待 AI 语义分析；未按关键词过滤')
            if not filter_rules or row['score'] > 0:
                yield row
                if max_items is not None and len(seen)>=max_items:return
        unchanged = unchanged + 1 if new_count == 0 else 0
        if unchanged >= 2:
            break
        if index < scrolls - 1:
            collection_pause(stop) if readiness else paced(stop)
            before=page.locator('a[href*="/search_result/"],a[href*="/explore/"]').evaluate_all('es=>es.map(e=>e.href).join("|")') if readiness else None
            if readiness:page.locator('a[href*="/search_result/"]:visible,a[href*="/explore/"]:visible').last.hover(timeout=3000)
            page.mouse.wheel(0, 850)
            if readiness:
                try:page.wait_for_function('(before)=>Array.from(document.querySelectorAll(\'a[href*="/search_result/"],a[href*="/explore/"]\')).map(e=>e.href).join("|")!==before',arg=before,timeout=3000)
                except Exception:checkpoint(page,stop)
            elif stop.wait(2.5): return
    if not readiness:observe(page, 'search-observation.json')


def prepare_chat(page, lead, stop, focus=True, progress=None, on_page=None):
    report = progress or (lambda stage: None)
    if on_page:on_page(page)
    report('检查浏览器连接')
    if focus:page.bring_to_front()
    checkpoint(page,stop)
    profile = canonical_profile(lead['profile_url'])
    uid = urlsplit(profile).path.rsplit('/',1)[-1]
    chats=[p for p in page.context.pages if not p.is_closed() and urlsplit(p.url).path=='/chat' and parse_qs(urlsplit(p.url).query).get('openUid')==[uid]]
    if chats:
        chat=chats[0]
    else:
        paced(stop)
        report('打开目标主页')
        page.goto(profile,wait_until='domcontentloaded',timeout=20000)
        checkpoint(page,stop)
        report('目标主页已打开')
        button=page.get_by_title('发消息',exact=True)
        button.wait_for(state='visible',timeout=15000)
        paced(stop)
        report('打开私信窗口')
        with page.context.expect_page(timeout=10000) as popup:
            button.click()
        chat=popup.value
        chat.wait_for_load_state('domcontentloaded',timeout=15000)
    if on_page:on_page(chat)
    report('核对会话对象')
    chat.locator('.xhs-im-chat-window__header-name').wait_for(state='visible',timeout=15000)
    checkpoint(chat,stop)
    if parse_qs(urlsplit(chat.url).query).get('openUid') != [uid]:
        raise RuntimeError('聊天对象 ID 不一致，已停止')
    actual=chat.locator('.xhs-im-chat-window__header-name').inner_text().strip()
    if actual != lead['name'].splitlines()[0].strip():
        raise RuntimeError(f'聊天对象名称不一致：预期 {lead["name"]}，当前 {actual}，已停止')
    if focus: chat.bring_to_front()
    return chat


def type_message_chunks(editor, message, stop):
    """Enter small chunks with visible pauses; preserve existing drafts."""
    draft=editor.inner_text().strip()
    if draft == message.strip():return
    if draft:raise RuntimeError('输入框中已有其他草稿，已保留并停止')
    editor.click()
    offset=0
    while offset<len(message):
        if stop.is_set():raise RuntimeError('任务已暂停，输入草稿已保留')
        chunk=message[offset:offset+random.randint(2,4)]
        editor.press_sequentially(chunk,delay=150)
        offset+=len(chunk)
        if offset<len(message) and stop.wait(random.uniform(.5,1.0)):
            raise RuntimeError('任务已暂停，输入草稿已保留')
    if editor.inner_text().strip()!=message.strip():
        raise RuntimeError('输入内容不一致，已停止，未提交消息')


CONVERSATION_HISTORY_SELECTOR='.chat-item__content, .chat-item[data-message-id]:not([data-message-id^="hint-stranger-"])'

def require_sender(page,expected):
    if not expected:return
    me=page.locator('a[href*="/user/profile/"]:visible').filter(has_text=re.compile(r'^\s*我\s*$'))
    try:
        me.first.wait_for(state='visible',timeout=8000)
        if me.count()!=1:raise ValueError('ambiguous sender')
        href=me.get_attribute('href')
        current=canonical_profile('https://www.xiaohongshu.com'+href if href.startswith('/') else href)
    except Exception as exc:raise RuntimeError('无法核对当前发送账号，已停止，未提交') from exc
    if current!=canonical_profile(expected):raise RuntimeError('当前发送账号与已确认账号不同，已停止，未提交')


def send_direct_message(page, lead, message, stop, progress=None, on_page=None):
    report = progress or (lambda stage: None)
    chat=prepare_chat(page,lead,stop,progress=report,**({'on_page':on_page} if on_page else {}))
    expected=lead.get('expected_account')
    require_sender(chat,expected)
    report('检查输入框与历史消息')
    thread=chat.locator('.xhs-im-msg-list')
    thread.wait_for(state='visible',timeout=10000)
    if thread.locator(CONVERSATION_HISTORY_SELECTOR).count():return 'already_present'
    # Header visibility alone does not mean asynchronous history has loaded.
    # These bottom/stranger markers were observed in the native conversation DOM.
    try:
        chat.wait_for_load_state('networkidle',timeout=10000)
        chat.wait_for_function('''()=>{const e=document.querySelector('.xhs-im-msg-list');return !!e&&(!!e.querySelector('.chat-item__content, .chat-item[data-message-id]:not([data-message-id^="hint-stranger-"])')||
            (!!e.querySelector('.xhs-im-msg-list__bottom')&&!!e.querySelector('[data-message-id^="hint-stranger-"]')))}''',timeout=10000)
    except Exception as exc:
        raise RuntimeError('会话历史未能完整核对，无法排除以前已私信；已停止，未发送，请人工核实') from exc
    checkpoint(chat,stop)
    require_sender(chat,expected)
    if thread.locator(CONVERSATION_HISTORY_SELECTOR).count():return 'already_present'
    editor=chat.locator('.xhs-im-input-bar-editor[contenteditable="true"]')
    if editor.count()!=1 or not editor.is_visible():
        raise RuntimeError('没有可用的消息输入框，可能受到平台限制，已停止')
    draft=editor.inner_text().strip()
    if draft and draft!=message.strip():
        raise RuntimeError('会话中已有其他草稿，保留草稿并停止')
    paced(stop)
    report('分段输入消息')
    type_message_chunks(editor,message,stop)
    paced(stop)
    checkpoint(chat,stop)
    require_sender(chat,expected)
    if parse_qs(urlsplit(chat.url).query).get('openUid') != [urlsplit(lead['profile_url']).path.rsplit('/',1)[-1]]:
        raise RuntimeError('发送前收件人 ID 发生变化，已停止')
    if chat.locator('.xhs-im-chat-window__header-name').inner_text().strip()!=lead['name'].splitlines()[0].strip():
        raise RuntimeError('发送前收件人发生变化，已停止')
    if thread.locator(CONVERSATION_HISTORY_SELECTOR).count():
        if not draft and editor.inner_text().strip()==message.strip():editor.fill('')
        return 'already_present'
    # Enter is the native IM composer action; never retry an uncertain submission.
    report('提交消息并核实结果')
    checkpoint(chat,stop)
    require_sender(chat,expected)
    editor.press('Enter')
    try:
        thread.get_by_text(message,exact=True).first.wait_for(state='visible',timeout=10000)
        chat.wait_for_timeout(1200)
        observe(chat,'send-observation.json')
        (DATA/'send-dom.html').write_text(thread.inner_html(),encoding='utf-8')
        if any(x in thread.inner_text() for x in ('发送失败','发送频繁','无法发送')):
            return 'needs_review'
        if editor.count() and editor.inner_text().strip()==message.strip():
            return 'needs_review'
        report('刷新会话确认消息已保存')
        chat.reload(wait_until='domcontentloaded',timeout=15000)
        chat.locator('.xhs-im-chat-window__header-name').wait_for(state='visible',timeout=15000)
        require_sender(chat,expected)
        if parse_qs(urlsplit(chat.url).query).get('openUid') != [urlsplit(lead['profile_url']).path.rsplit('/',1)[-1]]:
            return 'needs_review'
        if chat.locator('.xhs-im-chat-window__header-name').inner_text().strip()!=lead['name'].splitlines()[0].strip():
            return 'needs_review'
        chat.locator('.xhs-im-msg-list').get_by_text(message,exact=True).first.wait_for(state='visible',timeout=15000)
        if any(x in chat.locator('.xhs-im-msg-list').inner_text() for x in ('发送失败','无法发送')):
            return 'needs_review'
        # Delivery has been verified; evidence I/O failure must not turn it into
        # an uncertain/retryable send or trigger a second submission.
        try:chat.screenshot(path=str(DATA/f'sent-{lead["id"]}.png'),timeout=5000)
        except Exception as exc:
            try:(DATA/f'dm-evidence-error-{lead["id"]}.json').write_text(json.dumps({'confirmed':True,'screenshot_error':str(exc)[:250]},ensure_ascii=False),encoding='utf-8')
            except OSError:pass
        try:observe(chat,'send-confirmed-observation.json')
        except Exception:pass
        return 'sent'
    except Exception:
        try:chat.screenshot(path=str(DATA/f'send-review-{lead["id"]}.png'),timeout=5000)
        except Exception:pass
        return 'needs_review'


def read_inbox(page, stop):
    checkpoint(page,stop)
    entry = page.get_by_role('link', name='消息',exact=True)
    if entry.count() == 1:
        entry.click()
    else:
        # This route was observed in the logged-in sidebar; search results hide that sidebar.
        page.goto('https://www.xiaohongshu.com/chat?channel_id=&channel_type=explore_feed',wait_until='domcontentloaded')
    page.wait_for_url('**/chat**',timeout=15000)
    page.wait_for_timeout(1500)
    observe(page,'inbox-observation.json')
    return []


def collect_replies(page, leads, stop):
    for lead in leads:
        if stop.is_set(): return
        paced(stop)
        chat=prepare_chat(page,lead,stop,focus=False)
        chat.locator('.xhs-im-chat-window__header-name').wait_for(state='visible',timeout=15000)
        checkpoint(chat,stop)
        if chat.locator('.xhs-im-chat-window__header-name').inner_text().strip()!=lead['name'].splitlines()[0].strip():
            raise RuntimeError('回复检查时收件人不一致，已停止')
        chat.locator('.xhs-im-msg-list').wait_for(state='visible')
        messages=chat.locator('.xhs-im-msg-list .chat-item[data-message-id]').evaluate_all(INCOMING_MESSAGES_JS)
        for item in messages:
            yield {'fingerprint':hashlib.sha256((lead['profile_url']+'|'+item['id']).encode()).hexdigest(),
                   'sender':lead['name'].splitlines()[0].strip(),'body':item['body'],'url':chat.url,'lead_id':lead['id']}
