"""Project-local identity receipts. Account identity is audit data, not a key."""
import json
from datetime import datetime
from urllib.parse import urlsplit

def now():return datetime.now().isoformat(timespec='seconds')

def identity(channel, source):
    if channel=='dm':
        value=urlsplit(source['profile_url']).path.rstrip('/').rsplit('/',1)[-1]
    else:
        value=source.get('key') or source.get('note_key') or urlsplit(source.get('url') or source['note_url']).path.rstrip('/').rsplit('/',1)[-1]
        if channel=='reply':
            if not source.get('comment_id'):raise ValueError('缺少原评论标识，无法去重')
            value+=':'+source['comment_id']
    if not value:raise ValueError('缺少稳定标识，无法核对目标')
    return value

def init(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS studio_receipts(
      project_id INTEGER NOT NULL,channel TEXT NOT NULL,target_key TEXT NOT NULL,
      account_id TEXT NOT NULL,status TEXT NOT NULL,message TEXT NOT NULL,
      result TEXT DEFAULT '',updated_at TEXT,
      PRIMARY KEY(project_id,channel,target_key));
    CREATE TABLE IF NOT EXISTS studio_setup(project_id INTEGER PRIMARY KEY,step TEXT NOT NULL DEFAULT 'direction');
    CREATE TABLE IF NOT EXISTS studio_activity(id INTEGER PRIMARY KEY,job_id INTEGER,project_id INTEGER,body TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS studio_migrations(name TEXT PRIMARY KEY);
    ''')
    if not con.execute("SELECT 1 FROM studio_migrations WHERE name='project-receipts-v1'").fetchone():
        # Only import receipts with provable project ownership, never global legacy history.
        for d in con.execute('SELECT * FROM studio_drafts ORDER BY id'):
            for item in json.loads(d['items']):
                status=item.get('status')
                if status not in ('sent','already_present','pending','needs_review','not_sent','skipped'):continue
                if status in ('pending','skipped'):status='needs_review'
                try:key=identity(d['channel'],item['source'])
                except (KeyError,ValueError):continue
                con.execute('''INSERT INTO studio_receipts VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project_id,channel,target_key) DO UPDATE SET account_id=excluded.account_id,status=excluded.status,message=excluded.message,result=excluded.result,updated_at=excluded.updated_at WHERE studio_receipts.status='not_sent' OR (studio_receipts.status NOT IN ('sent','already_present') AND excluded.status IN ('sent','already_present'))''',
                    (d['project_id'],d['channel'],key,d['account_id'],status,item['message'],item.get('result','旧草稿记录迁入'),now()))
        con.execute("INSERT INTO studio_migrations VALUES('project-receipts-v1')")

def status(con,pid,channel,source):
    row=con.execute('SELECT status FROM studio_receipts WHERE project_id=? AND channel=? AND target_key=?',(pid,channel,identity(channel,source))).fetchone()
    return row[0] if row else 'ready'


def visible_drafts(con,pid):
    """One current entry per project/channel/stable target, retaining raw audit rows."""
    receipts={(r['channel'],r['target_key']):dict(r) for r in con.execute('SELECT * FROM studio_receipts WHERE project_id=?',(pid,))}
    seen=set();result=[]
    for row in con.execute("SELECT * FROM studio_drafts WHERE project_id=? AND status!='discarded' ORDER BY id DESC",(pid,)):
        draft=dict(row);items=[]
        for source_index,item in enumerate(json.loads(draft['items'])):
            key=(draft['channel'],identity(draft['channel'],item['source']))
            if key in seen:continue
            seen.add(key)
            if draft['channel']=='dm':item['draft_index']=source_index
            receipt=receipts.get(key)
            if receipt and item.get('status')!=receipt['status']:
                item['status']=receipt['status']
                text=receipt.get('result') or ''
                try:structured=json.loads(text)
                except (ValueError,TypeError):structured=None
                item['result']=('已发送，发送记录已保存' if receipt['status']=='sent' else '已同步本项目的最新处理记录') if isinstance(structured,(dict,list)) else text
            items.append(item)
        if not items:continue
        draft['items']=items
        if all(x['status'] in ('sent','skipped','already_present') for x in items):draft['status']='complete'
        elif any(x['status']=='needs_review' for x in items):draft['status']='needs_review'
        result.append(draft)
    return result


def draftable(con,pid,channel,source):
    if status(con,pid,channel,source) not in ('ready','not_sent'):return False
    key=identity(channel,source)
    for row in con.execute("SELECT items FROM studio_drafts WHERE project_id=? AND channel=? AND status IN ('preview','sending')",(pid,channel)):
        if any(identity(channel,item['source'])==key for item in json.loads(row['items'])):return False
    return True


def matching_preview(con,pid,channel,sources,account,*,allow_expansion=False):
    keys={identity(channel,x) for x in sources}
    for row in con.execute("SELECT * FROM studio_drafts WHERE project_id=? AND channel=? AND account_id=? AND status='preview' ORDER BY id DESC",(pid,channel,account)):
        items=json.loads(row['items'])
        existing_keys={identity(channel,x['source']) for x in items}
        if items and all(x.get('status')=='ready' for x in items) and (existing_keys==keys or (allow_expansion and existing_keys<keys)):
            return dict(row)
    return None

def claim(con,pid,channel,source,account,message):
    # One conditional write is atomic even when two callers race.
    return bool(con.execute('''INSERT INTO studio_receipts(project_id,channel,target_key,account_id,status,message,updated_at)
      VALUES(?,?,?,?,'pending',?,?) ON CONFLICT(project_id,channel,target_key) DO UPDATE SET
      account_id=excluded.account_id,status='pending',message=excluded.message,updated_at=excluded.updated_at
      WHERE studio_receipts.status='not_sent' ''',(pid,channel,identity(channel,source),account,message,now())).rowcount)

def finish(con,pid,channel,source,status,result=''):
    con.execute('UPDATE studio_receipts SET status=?,result=?,updated_at=? WHERE project_id=? AND channel=? AND target_key=?',
        (status,result,now(),pid,channel,identity(channel,source)))

def progress(app,pid,text):
    if not text:return
    with app.connect() as con:
        job=con.execute("SELECT id FROM studio_jobs WHERE project_id=? AND status='running' ORDER BY id DESC LIMIT 1",(pid,)).fetchone()
        if not job:return
        last=con.execute('SELECT body FROM studio_activity WHERE job_id=? ORDER BY id DESC LIMIT 1',(job[0],)).fetchone()
        if not last or last[0]!=text:
            con.execute('INSERT INTO studio_activity(job_id,project_id,body,created_at) VALUES(?,?,?,?)',(job[0],pid,text,now()))

def setup(con,pid):
    r=con.execute('SELECT step FROM studio_setup WHERE project_id=?',(pid,)).fetchone()
    return r[0] if r else 'direction'

def set_step(con,pid,step):
    con.execute('INSERT INTO studio_setup VALUES(?,?) ON CONFLICT(project_id) DO UPDATE SET step=excluded.step',(pid,step))


def recover(con):
    con.execute("UPDATE studio_receipts SET status='needs_review',result='后台重启，需核实，不能自动重发' WHERE status='pending'")
    for d in con.execute("SELECT id,items FROM studio_drafts WHERE status='sending'").fetchall():
        items=json.loads(d['items'])
        for item in items:
            if item.get('status')=='pending':item['status']='needs_review'
        con.execute("UPDATE studio_drafts SET status='needs_review',items=? WHERE id=?",(json.dumps(items,ensure_ascii=False),d['id']))
