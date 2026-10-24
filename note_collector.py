"""Collect a bounded sample of visible note text and threaded comments."""
import re
import time
from urllib.parse import urlsplit
from adapter import checkpoint,canonical_profile,collection_pause

COMMENTS='''els=>els.map(el=>{
const a=el.querySelector('.author a.name');
const root=el.closest('.parent-comment')?.querySelector(':scope > .comment-item');
const p=a?new URL(a.href):null;
return {id:el.id,author:a?.innerText.trim()||'',profile_url:p?p.origin+p.pathname:'',text:el.querySelector('.content')?.innerText.trim()||'',is_note_author:!!el.querySelector('.author .tag'),parent_id:root&&root!==el?root.id:null,parent_text:root&&root!==el?root.querySelector('.content')?.innerText.trim()||'':''};
}).filter(x=>x.id&&x.text)'''

COMMENT_STATE=r'''()=>{const e=document.querySelector('.comments-container');
const count=e?e.querySelectorAll('.comment-item').length:0;
const total=e?.querySelector('.total')?.innerText.match(/共\s*(\d+)\s*条/);
const empty=document.querySelector('.interaction-container .no-comments-text');
return {count,end:(!count&&!!empty&&empty.getBoundingClientRect().width>0)||!!e&&(/共\s*0\s*条|暂无评论|还没有评论|这是一片荒地|THE END|没有更多评论/.test(e.innerText)||(total&&count>=Number(total[1])))};}'''


def collect_ready(page,note,stop,limit=20):
    """Read the default comment order, stopping on quantity/end/readiness events."""
    url=urlsplit(note['note_url'])
    if url.hostname!='www.xiaohongshu.com' or not re.fullmatch(r'/(explore|search_result)/[a-zA-Z0-9]+',url.path):raise ValueError('笔记链接无效')
    start=time.perf_counter();timings={};scrolls=0;notice='页面默认展示顺序，非全量；未确认是热度排序'
    def stamp(name,t):timings[name]=round(time.perf_counter()-t,3)
    t=time.perf_counter()
    collection_pause(stop)
    page.goto(note['note_url'],wait_until='domcontentloaded',timeout=20000)
    checkpoint(page,stop)
    author=page.locator('.interaction-container .author-container a.name').first
    author.wait_for(state='visible',timeout=8000)
    if url.path.rsplit('/',1)[-1]!=urlsplit(page.url).path.rsplit('/',1)[-1]:raise ValueError('笔记位置不一致')
    title=page.locator('#detail-title').inner_text() if page.locator('#detail-title').count() else note.get('note_title','')
    body=page.locator('#detail-desc').inner_text() if page.locator('#detail-desc').count() else ''
    href=author.get_attribute('href');profile=canonical_profile('https://www.xiaohongshu.com'+href if href.startswith('/') else href)
    name=author.inner_text().strip();stamp('open_and_body',t)
    t=time.perf_counter()
    try:
        page.wait_for_function('()=>{const s=('+COMMENT_STATE+')();return s.count>0||s.end}',timeout=6000)
        unchanged=0
        for _ in range(6):
            checkpoint(page,stop)
            state=page.evaluate(COMMENT_STATE)
            if state['count']>=limit or state['end']:break
            collection_pause(stop)
            page.locator('.interaction-container .note-scroller').hover()
            page.mouse.wheel(0,850);scrolls+=1
            try:page.wait_for_function('(n)=>{const s=('+COMMENT_STATE+')();return s.count>n||s.end}',arg=state['count'],timeout=2000)
            except Exception:checkpoint(page,stop)
            after=page.evaluate(COMMENT_STATE)
            unchanged=unchanged+1 if after['count']<=state['count'] else 0
            if unchanged>=2:
                notice+='；滚动后未增加，可能还有未加载内容';break
    except Exception:
        checkpoint(page,stop);notice+='；加载等待超时，只保存当前可读评论'
    comments=page.locator('.comments-container .comment-item').evaluate_all(COMMENTS)
    for comment in comments:comment['profile_url']=canonical_profile(comment['profile_url'])
    comments=list({c['id']:c for c in comments}.values())[:limit]
    stamp('comments',t)
    media=page.evaluate('''()=>{const v=document.querySelector('video');const imgs=document.querySelectorAll('.note-slider img, .swiper-slide img');return {media_type:v?'video':imgs.length?'image':'unknown',cover:v?.poster||imgs[0]?.src||'',commentable:!!document.querySelector('#content-textarea')}}''')
    return dict(**media,title=title,body=body,author=name,profile_url=profile,note_url=note['note_url'],comments=comments,
                notice=notice,seconds=round(time.perf_counter()-start,3),timings=timings,scrolls=scrolls)

def collect(page,note,stop):
    url=urlsplit(note['note_url'])
    if url.hostname!='www.xiaohongshu.com' or not re.fullmatch(r'/(explore|search_result)/[a-zA-Z0-9]+',url.path):raise ValueError('笔记链接无效')
    start=time.perf_counter()
    page.goto(note['note_url'],wait_until='domcontentloaded',timeout=20000)
    checkpoint(page,stop)
    page.locator('#detail-title').wait_for(state='visible',timeout=12000)
    if url.path.rsplit('/',1)[-1] not in urlsplit(page.url).path:raise ValueError('笔记跳转到了其他页面，停止读取')
    title=page.locator('#detail-title').inner_text()
    body=page.locator('#detail-desc').inner_text() if page.locator('#detail-desc').count() else ''
    author=page.locator('.interaction-container .author-container a.name').first
    profile=canonical_profile('https://www.xiaohongshu.com'+author.get_attribute('href')) if author.get_attribute('href').startswith('/') else canonical_profile(author.get_attribute('href'))
    name=author.inner_text().strip()
    comments=[];notice='正文及当前加载的评论；非全量'
    try:
        page.wait_for_function("""()=>{const e=document.querySelector('.comments-container');return e&&(e.querySelector('.comment-item')||/共\\s*0\\s*条|暂无评论|还没有评论|THE END/.test(e.innerText))}""",timeout=10000)
        for _ in range(2):
            checkpoint(page,stop)
            more=page.locator('.comments-container').get_by_text(re.compile(r'^展开\s*\d+\s*条回复$'))
            if more.count():
                before=page.locator('.comments-container .comment-item').count()
                more.first.click(timeout=5000)
                try:page.wait_for_function('(n)=>document.querySelectorAll(".comments-container .comment-item").length>n',arg=before,timeout=4000)
                except Exception:checkpoint(page,stop)
            page.locator('.interaction-container .note-scroller').hover();page.mouse.wheel(0,650)
            if stop.wait(.8):raise RuntimeError('任务已暂停')
        comments=page.locator('.comments-container .comment-item').evaluate_all(COMMENTS)
    except Exception:
        checkpoint(page,stop)
        notice='评论未完整加载，本轮只分析已读取部分'
        comments=page.locator('.comments-container .comment-item').evaluate_all(COMMENTS)
    for comment in comments:comment['profile_url']=canonical_profile(comment['profile_url'])
    unique=list({c['id']:c for c in comments}.values())[:20]
    total=page.locator('.comments-container .total').inner_text() if page.locator('.comments-container .total').count() else ''
    return {'title':title,'body':body,'author':name,'profile_url':profile,'note_url':note['note_url'],'comments':unique,'displayed_total':total,'notice':notice,'seconds':round(time.perf_counter()-start,3)}
