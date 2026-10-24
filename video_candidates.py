"""Read-only native video search collection for manual workbench selection."""
import importlib
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
import adapter
import comment_flow
import studio
import studio_archive
import project_store
from app_paths import data_dir

def run(worker,stop,db,update):
    importlib.reload(adapter)
    started=time.monotonic()
    topic='英雄联盟 S16'
    queries=['英雄联盟 S16','S16 瑞士轮','LOL S16','S16 全球总决赛','英雄联盟S16赛事','S16 英雄联盟比赛']
    report={'read':0,'comments_read':0,'accepted':0,'preview_only':True,'candidate_mode':'video_search_cards','queries':queries,'decisions':[],'scope':'视频搜索卡片；正文和评论未读取；未发送'}
    with db() as con:
        existing=con.execute("SELECT id FROM studio_projects WHERE title='英雄联盟 S16 · 手动挑选' AND archived_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
        pid=existing[0] if existing else studio_archive.create(con,'英雄联盟 S16 · 手动挑选')
        con.execute('UPDATE studio_projects SET plan=? WHERE id=?',(studio.dump({'topic':topic,'queries':queries,'count':100,'goal':'只找视频候选，用户手动选择发送'}),pid))
        project_store.set_step(con,pid,'done')
        studio.message(con,pid,'user','找到100个英雄联盟S16视频，我手动选择发送。')
        jid=con.execute("INSERT INTO studio_jobs(project_id,kind,status,payload,created_at,updated_at) VALUES(?,'search','running',?,?,?)",(pid,'{}',studio.now(),studio.now())).lastrowid
        rid=con.execute("INSERT INTO comment_runs(topic,criteria,target,status,report,started_at) VALUES(?,?,100,'finding',?,?)",(topic,'只采集候选，不发送',studio.dump(report),studio.now())).lastrowid
        con.execute('INSERT INTO studio_runs(project_id,run_id) VALUES(?,?)',(pid,rid))
    worker.studio_job_id=jid
    app=sys.modules[worker.__class__.__module__]
    found={};seen=set()
    def progress(text):
        update(message=text)
        with db() as con:
            con.execute('INSERT INTO studio_activity(job_id,project_id,body,created_at) VALUES(?,?,?,?)',(jid,pid,text,studio.now()))
    def persist(raw,note,reason):
        key=urlsplit(note['note_url']).path.rsplit('/',1)[-1]
        if key in found or len(found)>=100:return
        found[key]=note
        report['accepted']=len(found)
        report['decisions'].append({'id':key,'relevant':True,'reason':reason})
        with db() as con:
            con.execute('INSERT INTO comment_captures(run_id,note_key,raw,capture,captured_at) VALUES(?,?,?,?,?)',(rid,key,studio.dump(raw),studio.dump(note),studio.now()))
            con.execute('UPDATE comment_runs SET report=? WHERE id=?',(studio.dump(report),rid))
    try:
        worker.background()
        # Reuse captured video data as candidate material; no receipts cross projects.
        with db() as con:
            rows=con.execute('SELECT c.raw,c.capture,c.note_key,r.report FROM comment_captures c JOIN studio_runs s ON s.run_id=c.run_id JOIN comment_runs r ON r.id=c.run_id WHERE s.project_id=15').fetchall()
        for row in rows:
            n=json.loads(row['capture'])
            relevance={d['id']:d.get('relevant') for d in json.loads(row['report']).get('decisions',[])}
            if n.get('media_type')=='video' and relevance.get(row['note_key']) is not False:persist(json.loads(row['raw']),n,'已有同话题视频快照，仅作为新项目候选')
        for query in queries:
            if len(found)>=100:break
            progress(f'已保存 {len(found)}/100 个视频候选；搜索：{query}。不发送。')
            with worker.browser_operation(240):
                worker.page.goto('https://www.xiaohongshu.com/explore',wait_until='domcontentloaded',timeout=20000)
                rows=list(adapter.collect_search(worker.page,query,24,stop,filter_rules=False,dedupe_authors=False,readiness=True,max_items=130,video_only=True))
                studio.capture(worker,app,pid,'视频筛选：'+query,force=True)
            fresh=[]
            for r in rows:
                key=urlsplit(r['note_url']).path.rsplit('/',1)[-1]
                if key in seen or key in found:continue
                seen.add(key);fresh.append((key,r))
            for offset in range(0,len(fresh),30):
                if stop.is_set():raise RuntimeError('已暂停；候选已保存')
                if len(found)>=100:break
                batch=fresh[offset:offset+30]
                progress(f'已保存 {len(found)}/100 个；AI 批量筛选视频标题，不读取评论、不发送。')
                decisions=comment_flow.screen_notes(topic,[{'id':k,'text':r['note_title']} for k,r in batch])
                accepted={d['id']:d for d in decisions if d['relevant'] and d.get('screen_status')=='verified'}
                for key,r in batch:
                    if key not in accepted:continue
                    n={'title':r['note_title'],'author':r['name'],'profile_url':r['profile_url'],'note_url':r['note_url'],'body':'仅采集搜索卡片，正文与评论尚未读取。','comments':[],'media_type':'video','commentable':None,'capture_scope':'search_card'}
                    persist(r,n,accepted[key]['reason'])
        text=f'已保存 {len(found)} 个唯一视频候选，尚未发送。请在右侧“笔记”勾选对象，再准备消息预览。新增候选只读取了搜索卡片；评论权限会在操作前核验。'
        progress(text)
        with db() as con:
            studio.message(con,pid,'assistant',text)
            con.execute("UPDATE studio_jobs SET status='complete',updated_at=? WHERE id=?",(studio.now(),jid))
            con.execute("UPDATE comment_runs SET status='ready',finished_at=? WHERE id=?",(studio.now(),rid))
    except Exception as exc:
        progress(f'已保留 {len(found)} 个视频候选；采集停止：{str(exc)[:180]}')
        with db() as con:
            con.execute("UPDATE studio_jobs SET status='failed',error=?,updated_at=? WHERE id=?",(studio.dump({'title':'视频采集停止','advice':str(exc)[:250]}),studio.now(),jid))
            con.execute("UPDATE comment_runs SET status='failed' WHERE id=?",(rid,))
        raise
    finally:
        (data_dir()/'s16-manual-candidates.json').write_text(studio.dump({'project_id':pid,'count':len(found),'unique_ids':list(found),'real_sends':0,'seconds':round(time.monotonic()-started,2)}),encoding='utf-8')
        worker.studio_job_id=None
