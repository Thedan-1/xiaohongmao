"""Topic -> AI search plan -> visible notes/comments -> reviewed candidates. Never sends."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlsplit
import workflow_ai as ai
import topic_state
from adapter import collect_search,canonical_profile,checkpoint
from note_collector import collect

def now():return datetime.now().isoformat(timespec='seconds')

def init(con):
    columns={r[1] for r in con.execute('PRAGMA table_info(leads)')}
    for name,default in [('source_kind','legacy'),('source_text',''),('source_comment_id',''),('ai_fit',''),('ai_intent',''),('ai_uncertainty',''),('ai_topic','')]:
        if name not in columns:con.execute(f"ALTER TABLE leads ADD COLUMN {name} TEXT DEFAULT '{default}'")
    con.executescript('''
      CREATE TABLE IF NOT EXISTS discovery_topics(topic TEXT PRIMARY KEY,plan TEXT,search_round INTEGER DEFAULT 0);
      CREATE TABLE IF NOT EXISTS discovery_notes(topic TEXT,note_key TEXT,raw TEXT,status TEXT DEFAULT 'queued',reason TEXT DEFAULT '',capture TEXT,updated_at TEXT,PRIMARY KEY(topic,note_key));
      CREATE TABLE IF NOT EXISTS discovery_runs(id INTEGER PRIMARY KEY,topic TEXT,status TEXT,queries TEXT,found INTEGER DEFAULT 0,excluded INTEGER DEFAULT 0,read_count INTEGER DEFAULT 0,candidates INTEGER DEFAULT 0,error TEXT DEFAULT '',started_at TEXT,finished_at TEXT);
      CREATE TABLE IF NOT EXISTS discovery_assessments(topic TEXT,source_key TEXT,result TEXT,source_json TEXT,PRIMARY KEY(topic,source_key));
    ''')

def save_candidate(con,topic,source,result,purpose=''):
    if result['fit'] not in ('high','potential') or not result.get('evidence_verified'):return None
    if source['author'].strip() in ('用户已注销','已注销'):return None
    profile=canonical_profile(source['profile_url'])
    old=con.execute('SELECT * FROM leads WHERE profile_url=?',(profile,)).fetchone()
    previous=con.execute('SELECT evidence FROM topic_leads WHERE topic=? AND lead_id=?',(topic,old['id'])).fetchone() if old else None
    same_goal=previous and json.loads(previous[0]).get('analysis_goal','')==purpose
    if same_goal and old['ai_topic']==topic and old['ai_fit']=='high' and result['fit']=='potential':return old['id']
    if same_goal and old['ai_topic']==topic and old['ai_fit']==result['fit'] and old['source_kind']=='note_author' and source['kind']=='commenter':return old['id']
    values=(source['author'],source['note_url'],source['note_title'],topic,result['evidence'],now(),source['kind'],source['text'],source.get('comment_id',''),result['fit'],result['intent'],result['uncertainty'],topic)
    if old:
        con.execute('UPDATE leads SET name=?,note_url=?,note_title=?,keyword=?,evidence=?,updated_at=?,source_kind=?,source_text=?,source_comment_id=?,ai_fit=?,ai_intent=?,ai_uncertainty=?,ai_topic=? WHERE id=?',values+(old['id'],))
        topic_state.remember(con,topic,{**dict(con.execute('SELECT * FROM leads WHERE id=?',(old['id'],)).fetchone()),'analysis_goal':purpose})
        return old['id']
    cur=con.execute('''INSERT INTO leads(name,note_url,note_title,keyword,evidence,updated_at,source_kind,source_text,source_comment_id,ai_fit,ai_intent,ai_uncertainty,ai_topic,profile_url,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',values+(profile,now()))
    lead_id=cur.lastrowid
    topic_state.remember(con,topic,{**dict(con.execute('SELECT * FROM leads WHERE id=?',(lead_id,)).fetchone()),'analysis_goal':purpose})
    return lead_id

def items_for_note(note,note_key):
    items=[];sources={}
    key='note-'+note_key
    text=note['title']+'\n'+note['body'][:1600]
    items.append({'id':key,'source_type':'note_with_body','author':note['author'],'text':text})
    sources[key]={'kind':'note_author','author':note['author'],'profile_url':note['profile_url'],'note_url':note['note_url'],'note_title':note['title'],'text':text}
    for comment in note['comments']:
        key=comment['id']
        items.append({'id':key,'source_type':'comment','author':comment['author'],'text':comment['text'][:600],
                      'is_note_author':comment['is_note_author'],'note_title':note['title'],'note_context':note['body'][:180],'parent_text':comment['parent_text'][:240]})
        sources[key]={'kind':'commenter','author':comment['author'],'profile_url':comment['profile_url'],'note_url':note['note_url'],'note_title':note['title'],'text':comment['text'],'comment_id':key}
    return items,sources

def batches(items):
    batch=[]
    for item in items:
        if batch and (len(batch)>=20 or len(json.dumps(batch+[item],ensure_ascii=False).encode('utf-8'))>24000):
            yield batch;batch=[]
        batch.append(item)
    if batch:yield batch


def preview(con,topic):
    """Search observations, never eligible recipients or verified comment targets."""
    counts={r['status']:r['n'] for r in con.execute('SELECT status,COUNT(*) n FROM discovery_notes WHERE topic=? GROUP BY status',(topic,))}
    rows=con.execute("SELECT note_key,raw,status,reason FROM discovery_notes WHERE topic=? AND status!='excluded' ORDER BY rowid DESC LIMIT 8",(topic,)).fetchall()
    return {'total':sum(counts.values()),'analyzed':counts.get('analyzed',0),'excluded':counts.get('excluded',0),
            'notes':[{'id':r['note_key'],'title':json.loads(r['raw']).get('note_title',''),'author':json.loads(r['raw']).get('name',''),'status':r['status']} for r in rows]}

def run_round(worker,payload,stop,db,update,event):
    topic=str(payload.get('topic','')).strip()
    purpose=str(payload.get('purpose',''))[:1000]
    if not 1<=len(topic)<=120:raise ValueError('请输入1～120字的话题')
    worker.require_page()
    with worker.browser_operation(60):
        worker.recover_source_page();checkpoint(worker.page,stop)
    with db() as con:
        run_id=con.execute("INSERT INTO discovery_runs(topic,status,started_at) VALUES(?,'running',?)",(topic,now())).lastrowid
    candidates=set();read_count=0;excluded=0
    def progress(message,**values):
        update(message=message)
        if values:
            with db() as con:
                con.execute('UPDATE discovery_runs SET '+','.join(k+'=?' for k in values)+' WHERE id=?',tuple(values.values())+(run_id,))
    def stopped():
        if stop.is_set():raise RuntimeError('已暂停，已保存当前进度')
    try:
        progress('AI 正在把话题变成搜索词…')
        with db() as con:cached=con.execute('SELECT plan FROM discovery_plans WHERE topic=? AND purpose=?',(topic,purpose)).fetchone()
        plan=json.loads(cached['plan']) if cached else ai.plan(topic,purpose)
        if len(topic)<=32:plan['queries']=list(dict.fromkeys([topic]+plan['queries']))[:3]
        stopped()
        with db() as con:
            con.execute('INSERT OR IGNORE INTO discovery_topics(topic,plan) VALUES(?,?)',(topic,json.dumps(plan,ensure_ascii=False)))
            con.execute('INSERT OR IGNORE INTO discovery_plans VALUES(?,?,?)',(topic,purpose,json.dumps(plan,ensure_ascii=False)))
            pending=con.execute("SELECT COUNT(*) FROM discovery_notes WHERE topic=? AND status IN ('queued','relevant')",(topic,)).fetchone()[0]
            round_no=con.execute('SELECT search_round FROM discovery_topics WHERE topic=?',(topic,)).fetchone()[0]
        progress('搜索词已准备好',queries=json.dumps(plan['queries'],ensure_ascii=False))
        if pending<3 or payload.get('force_search'):
            worker.page.goto('https://www.xiaohongshu.com/explore',wait_until='domcontentloaded',timeout=20000)
            # Rotate search phrases across rounds; show/analyze the first batch promptly.
            for query in [plan['queries'][round_no % len(plan['queries'])]]:
                stopped();progress('正在搜索：'+query)
                with worker.browser_operation(180):
                    for row in collect_search(worker.page,query,min(2+(round_no//len(plan['queries']))*2,20),stop,filter_rules=False,dedupe_authors=False):
                        row['query']=query
                        key=urlsplit(row['note_url']).path.rsplit('/',1)[-1]
                        with db() as con:
                            con.execute('INSERT INTO discovery_notes(topic,note_key,raw,updated_at) VALUES(?,?,?,?) ON CONFLICT(topic,note_key) DO UPDATE SET raw=excluded.raw,updated_at=excluded.updated_at',(topic,key,json.dumps(row,ensure_ascii=False),now()))
                with db() as con:count=con.execute('SELECT COUNT(*) FROM discovery_notes WHERE topic=?',(topic,)).fetchone()[0]
                progress('已收集笔记，准备读取正文与评论',found=count)
            with db() as con:con.execute('UPDATE discovery_topics SET search_round=search_round+1 WHERE topic=?',(topic,))
        with db() as con:count=con.execute('SELECT COUNT(*) FROM discovery_notes WHERE topic=?',(topic,)).fetchone()[0]
        progress('AI 正在排除与话题无关的笔记…',found=count)
        with db() as con:
            queued=con.execute("SELECT * FROM discovery_notes WHERE topic=? AND status='queued' ORDER BY CASE WHEN json_extract(raw,'$.query')=? THEN 0 ELSE 1 END,rowid LIMIT 24",(topic,topic)).fetchall()
        if queued:
            items=[{'id':r['note_key'],'text':json.loads(r['raw'])['note_title']} for r in queued]
            relevance=ai.relevance(topic,items);stopped()
            with db() as con:
                for result in relevance:
                    status='relevant' if result['relevant'] else 'excluded'
                    excluded+=not result['relevant']
                    con.execute('UPDATE discovery_notes SET status=?,reason=? WHERE topic=? AND note_key=?',(status,str(result.get('reason',''))[:200],topic,str(result['id'])))
            progress('主题相关性已判断',excluded=excluded)
        with db() as con:notes=con.execute("SELECT * FROM discovery_notes WHERE topic=? AND status='relevant' ORDER BY CASE WHEN json_extract(raw,'$.query')=? THEN 0 ELSE 1 END,rowid LIMIT 3",(topic,topic)).fetchall()
        def analyze(note,note_key):
            items,sources=items_for_note(note,note_key)
            results=[]
            for batch in batches(items):
                stopped()
                results.extend(ai.intent(topic,batch,purpose))
            return results,sources
        def save_analysis(pending):
            nonlocal read_count
            note_key,future=pending
            progress('AI 正在核实相关性和联系目的…')
            results,sources=future.result()
            stopped()
            with db() as con:
                for result in results:
                    source=sources[str(result['id'])]
                    con.execute('INSERT OR REPLACE INTO discovery_assessments VALUES(?,?,?,?)',(topic,str(result['id']),json.dumps(result,ensure_ascii=False),json.dumps(source,ensure_ascii=False)))
                    candidate=save_candidate(con,topic,source,result,purpose)
                    if candidate:candidates.add(candidate)
                con.execute("UPDATE discovery_notes SET status='analyzed' WHERE topic=? AND note_key=?",(topic,note_key))
            read_count+=1
            progress('已保存候选人和原文依据',read_count=read_count,candidates=len(candidates))
        # Only AI runs off-thread. Playwright stays on its owning thread; at most
        # one AI request is active while the next note loads. No extra paid calls.
        with ThreadPoolExecutor(max_workers=1,thread_name_prefix='discovery-ai') as pool:
            pending_analysis=None
            for row in notes:
                stopped();progress(f'正在读取正文和评论（{read_count+1}/{len(notes)}）')
                try:
                    with worker.browser_operation(60):
                        if row['capture']:
                            note=json.loads(row['capture'])
                        else:
                            # Reclaim each previous note's video/DOM resources before loading the next.
                            previous_page=worker.page
                            worker.page=worker.context.new_page()
                            previous_page.close()
                            note=collect(worker.page,json.loads(row['raw']),stop)
                    with db() as con:con.execute('UPDATE discovery_notes SET capture=? WHERE topic=? AND note_key=?',(json.dumps(note,ensure_ascii=False),topic,row['note_key']))
                except Exception as exc:
                    if 'Target crashed' in str(exc):
                        with worker.browser_operation(60):worker.recover_source_page()
                        event('这篇笔记的浏览器页面崩溃，已跳过并恢复后台入口','info')
                    else:checkpoint(worker.page,stop)
                    with db() as con:con.execute("UPDATE discovery_notes SET status='failed',reason=? WHERE topic=? AND note_key=?",(str(exc)[:200],topic,row['note_key']))
                    event('有一篇笔记未能读取，已保留记录供检查','info');continue
                if pending_analysis:
                    save_analysis(pending_analysis)
                stopped()
                pending_analysis=(row['note_key'],pool.submit(analyze,note,row['note_key']))
            if pending_analysis:
                save_analysis(pending_analysis)
        stopped()
        message=f'本轮读了 {read_count} 篇笔记，发现 {len(candidates)} 位候选人。可继续找，或勾选后写消息。'
        progress(message,status='complete',finished_at=now());event(message)
    except Exception as exc:
        progress('已暂停，当前结果已保存' if stop.is_set() else '本轮未完成：'+str(exc)[:200],status='paused' if stop.is_set() else 'failed',error=str(exc)[:250],finished_at=now())
        raise


def run(worker,payload,stop,db,update,event):
    if 'target_count' not in payload:return run_round(worker,payload,stop,db,update,event)
    target=max(1,min(200,int(payload['target_count'])))
    topic=str(payload['topic']).strip()
    purpose=str(payload.get('purpose',''))[:1000]
    with db() as con:
        last=con.execute('SELECT purpose FROM topic_analysis WHERE topic=?',(topic,)).fetchone()
        if last and last[0]!=purpose:
            con.execute("UPDATE discovery_notes SET status='relevant' WHERE topic=? AND status='analyzed'",(topic,))
        con.execute('INSERT OR REPLACE INTO topic_analysis VALUES(?,?)',(topic,purpose))
    def available():
        with db() as con:
            contacts={r[0] for r in con.execute("SELECT lead_id FROM contacts WHERE status!='not_sent'")}
            return sum(r['ai_fit'] in ('high','potential') and r['status'] not in ('ignored','do_not_contact','replied','contacted') and r['id'] not in contacts for r in topic_state.leads(con,topic,purpose))
    previous=available();stagnant=0
    for index in range(50):
        if previous>=target or stop.is_set():break
        def report(**values):
            if 'message' in values:values['message']=f'目标 {target} 位 · 第 {index+1} 轮：'+values['message']
            update(**values)
        run_round(worker,payload,stop,db,report,event)
        payload={**payload,'force_search':False}
        count=available()
        stagnant=stagnant+1 if count==previous else 0
        previous=count
        if stagnant>=5:break
    if not stop.is_set():
        message=f'本次找到 {previous} 位尚未联系的候选人，目标 {target} 位。'+('可以预览并发送。' if previous>=target else '当前可见结果不足，已保存进度；可换搜索方向继续找。')
        update(message=message);event(message)
