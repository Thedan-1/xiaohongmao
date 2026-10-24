"""Read-only browser collection benchmark. No sending methods are called."""
import json
import importlib
import re
import sqlite3
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser
from contextlib import closing
from pathlib import Path
from app_paths import data_dir
import adapter
importlib.reload(adapter)
from adapter import checkpoint, collect_search, prepare_chat
ROOT=Path(__file__).resolve().parent

EXTRACT_COMMENTS='''els=>els.map(el=>{
const a=el.querySelector('.author a.name');
const root=el.closest('.parent-comment')?.querySelector(':scope > .comment-item');
const p=a?new URL(a.href):null;
return {id:el.id,author:a?.innerText.trim()||'',profile_url:p?p.origin+p.pathname:'',text:el.querySelector('.content')?.innerText.trim()||'',is_note_author:!!el.querySelector('.author .tag'),parent_id:root&&root!==el?root.id:null,parent_text:root&&root!==el?root.querySelector('.content')?.innerText.trim()||'':''};
}).filter(x=>x.id&&x.text)'''

class VisibleHTML(HTMLParser):
    def __init__(self):super().__init__();self.note=False;self.comments=0
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if attrs.get('id')=='detail-title':self.note=True
        if 'comment-item' in attrs.get('class','').split():self.comments+=1

def raw_http_probe(url):
    start=time.perf_counter();result={'method':'unauthenticated HTML GET'}
    try:
        with urllib.request.urlopen(url,timeout=15) as response:
            body=response.read(2_000_000).decode('utf-8','replace');result['status']=response.status
        parser=VisibleHTML();parser.feed(body)
        result.update(note_html_present=parser.note,comment_html_count=parser.comments,bytes=len(body.encode()))
    except urllib.error.HTTPError as exc:result['status']=exc.code
    except Exception as exc:result['error']=type(exc).__name__
    result['seconds']=round(time.perf_counter()-start,3)
    return result

def collect_note(page,lead,stop):
    start=time.perf_counter();page.goto(lead['note_url'],wait_until='domcontentloaded',timeout=20000)
    checkpoint(page,stop)
    page.locator('#detail-title').wait_for(state='visible',timeout=12000)
    page.locator('.comments-container').wait_for(state='visible',timeout=15000)
    # Wait for a comment or an explicit no-comment/end state, not a fixed long sleep.
    page.wait_for_function("""()=>{const e=document.querySelector('.comments-container');return e&&(e.querySelector('.comment-item')||/共\\s*0\\s*条|暂无评论|还没有评论|THE END/.test(e.innerText))}""",timeout=12000)
    initial_seconds=round(time.perf_counter()-start,3)
    expanded=0
    for _ in range(2):
        checkpoint(page,stop)
        more=page.locator('.comments-container').get_by_text(re.compile(r'^展开\s*\d+\s*条回复$'))
        if more.count():
            before=page.locator('.comments-container .comment-item').count()
            more.first.click(timeout=5000);expanded+=1
            try:page.wait_for_function('(n)=>document.querySelectorAll(".comments-container .comment-item").length>n',arg=before,timeout=5000)
            except Exception:pass
        scroller=page.locator('.interaction-container .note-scroller')
        scroller.hover();page.mouse.wheel(0,650)
        if stop.wait(.8):raise RuntimeError('任务已暂停')
    title=page.locator('#detail-title').inner_text()
    body=page.locator('#detail-desc').inner_text() if page.locator('#detail-desc').count() else ''
    comments=page.locator('.comments-container .comment-item').evaluate_all(EXTRACT_COMMENTS)
    unique={x['id']:x for x in comments};comments=list(unique.values())[:50]
    total=page.locator('.comments-container .total').inner_text() if page.locator('.comments-container .total').count() else ''
    screenshot=data_dir(ROOT)/f'benchmark-note-{lead["id"]}.png';page.screenshot(path=str(screenshot))
    return {'lead_id':lead['id'],'title':title,'body':body,'author':lead['name'],'comments':comments,'displayed_total':total,'reply_expansions':expanded,'first_comments_seconds':initial_seconds,'seconds':round(time.perf_counter()-start,3),'scope':'最多展开2次楼中楼、滚动2次，非全量评论'}

def run(worker,payload,stop):
    worker.require_page()
    page=worker.page
    checkpoint(page,stop)
    if payload.get('mode')=='collect':
        with closing(sqlite3.connect(data_dir(ROOT)/'workbench.sqlite3')) as con:
            con.row_factory=sqlite3.Row
            notes=[dict(con.execute('SELECT * FROM leads WHERE id=?',(n,)).fetchone()) for n in (40,41,46)]
            contact=dict(con.execute('SELECT * FROM leads WHERE id=15').fetchone())
        result={'notes':[],'started_at':time.strftime('%Y-%m-%dT%H:%M:%S')}
        def save():(data_dir(ROOT)/'collection-benchmark.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        previous=data_dir(ROOT)/'collection-benchmark.json'
        old=json.loads(previous.read_text(encoding='utf-8')) if previous.exists() else {}
        result['http_probe']=old.get('http_probe') or raw_http_probe(notes[0]['note_url']);save()
        pipeline_start=time.perf_counter()
        # The browser must first leave a note overlay to expose the search field.
        page.goto('https://www.xiaohongshu.com/explore',wait_until='domcontentloaded',timeout=20000)
        start=time.perf_counter()
        rows=list(collect_search(page,'BIM建模',2,stop,filter_rules=False))
        result['search']={'seconds':round(time.perf_counter()-start,3),'count':len(rows),'keyword':'BIM建模','scrolls':2,'items':rows,'filter':'none'};save()
        for lead in notes:
            checkpoint(page,stop)
            start=time.perf_counter()
            try:result['notes'].append(collect_note(page,lead,stop))
            except Exception as exc:result['notes'].append({'lead_id':lead['id'],'seconds':round(time.perf_counter()-start,3),'error':str(exc)[:250]})
            save()
            if stop.is_set():break
        result['collection_wall_seconds']=round(time.perf_counter()-pipeline_start,3)
        if not stop.is_set():
            start=time.perf_counter()
            try:
                prepare_chat(page,contact,stop,focus=False)
                result['rpa_open_existing_contact']={'seconds':round(time.perf_counter()-start,3),'sent':False,'scope':'仅打开先前已联系对象的会话，未输入或发送'}
            except Exception as exc:result['rpa_open_existing_contact']={'seconds':round(time.perf_counter()-start,3),'error':str(exc)[:200],'sent':False}
        save()
        return
    structure=page.locator('a[href*="/user/profile/"]').evaluate_all('''anchors=>anchors.filter(a=>a.innerText.trim() && a.getBoundingClientRect().width).slice(-6).map(a=>({name:a.innerText,parents:(()=>{let p=a;const out=[];for(let i=0;i<5&&p;i++,p=p.parentElement)out.push({tag:p.tagName,cls:p.className,id:p.id,html:p.outerHTML.slice(0,9000)});return out})()}))''')
    (data_dir(ROOT)/'comment-structure.json').write_text(json.dumps(structure,ensure_ascii=False,indent=2),encoding='utf-8')
