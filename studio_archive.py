"""Archive first; permanently delete only explicitly confirmed archived projects."""
from datetime import datetime

def now():return datetime.now().isoformat(timespec='seconds')

def init(con):
    if 'archived_at' not in {r[1] for r in con.execute('PRAGMA table_info(studio_projects)')}:
        con.execute('ALTER TABLE studio_projects ADD COLUMN archived_at TEXT')
    con.executescript('''
    CREATE TABLE IF NOT EXISTS studio_project_sequence(id INTEGER PRIMARY KEY CHECK(id=1),last_id INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS studio_owned_runs(project_id INTEGER NOT NULL,run_id INTEGER PRIMARY KEY);
    INSERT OR IGNORE INTO studio_project_sequence SELECT 1,COALESCE(MAX(id),0) FROM studio_projects;
    UPDATE studio_project_sequence SET last_id=MAX(last_id,(SELECT COALESCE(MAX(id),0) FROM studio_projects));
    ''')

def create(con,title):
    # Never recycle a deleted project ID: old links must not point to a new project.
    con.execute('UPDATE studio_project_sequence SET last_id=MAX(last_id,(SELECT COALESCE(MAX(id),0) FROM studio_projects))+1 WHERE id=1')
    pid=con.execute('SELECT last_id FROM studio_project_sequence WHERE id=1').fetchone()[0]
    con.execute('INSERT INTO studio_projects(id,title,created_at,updated_at) VALUES(?,?,?,?)',(pid,title,now(),now()))
    return pid

def change(app,pid,action,confirmed=False):
    files=[]
    with app.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        p=con.execute('SELECT * FROM studio_projects WHERE id=?',(pid,)).fetchone()
        if not p:raise ValueError('项目不存在')
        if app.STATE.get('task')!='idle' or not app.COMMANDS.empty() or app.COMMANDS.unfinished_tasks or con.execute("SELECT 1 FROM studio_jobs WHERE status IN ('queued','running') LIMIT 1").fetchone():
            raise ValueError('任务仍在运行，请先暂停并等待结束，再管理归档')
        if action=='archive':
            con.execute('UPDATE studio_projects SET archived_at=COALESCE(archived_at,?) WHERE id=?',(now(),pid))
        elif action=='restore':
            con.execute('UPDATE studio_projects SET archived_at=NULL,updated_at=? WHERE id=?',(now(),pid))
        elif action=='delete':
            if not p['archived_at']:raise ValueError('请先归档，再到个人设置中删除')
            if confirmed is not True:raise ValueError('请确认永久删除，此操作无法在工作台撤销')
            run_ids={r[0] for r in con.execute('SELECT run_id FROM studio_runs WHERE project_id=? UNION SELECT run_id FROM studio_owned_runs WHERE project_id=?',(pid,pid))}
            for rid in run_ids:
                # Defensive ownership check for historical/imported data.
                if con.execute('SELECT 1 FROM studio_runs WHERE run_id=? AND project_id!=?',(rid,pid)).fetchone():continue
                for row in con.execute('SELECT id FROM comment_targets WHERE run_id=?',(rid,)):
                    files.extend([f'comment-preview-{row[0]}.png',f'comment-sent-{row[0]}.png',f'comment-receipt-{row[0]}.json'])
                for table in ('comment_targets','comment_leads','comment_captures'):
                    con.execute(f'DELETE FROM {table} WHERE run_id=?',(rid,))
                con.execute('DELETE FROM comment_runs WHERE id=?',(rid,))
            for table in ('studio_messages','studio_runs','studio_owned_runs','studio_jobs','studio_drafts','studio_receipts','studio_setup','studio_activity','studio_frames','studio_authorizations'):
                con.execute(f'DELETE FROM {table} WHERE project_id=?',(pid,))
            con.execute('DELETE FROM studio_projects WHERE id=?',(pid,))
            files.extend([f'studio-frame-{pid}.jpg',f'studio-frame-{pid}.json',f'studio-frame-{pid}.tmp',f'studio-frame-{pid}.tmp.json'])
        else:raise ValueError('不支持的归档操作')
        next_project=con.execute('SELECT id FROM studio_projects WHERE archived_at IS NULL ORDER BY updated_at DESC,id DESC LIMIT 1').fetchone()
    failed=[]
    root=app.DATA.resolve()
    if action=='delete':
        for pattern in (f'sent-project-{pid}-draft-*.png',f'send-review-project-{pid}-draft-*.png'):
            files.extend(file.name for file in root.glob(pattern) if file.is_file())
    for name in files:
        file=root/name
        if file.resolve().parent!=root:failed.append(name);continue
        try:file.unlink(missing_ok=True)
        except OSError:failed.append(name)
    return {'ok':True,'project_id':pid if action=='restore' else (next_project[0] if next_project else 0),
            'warning':'项目记录已删除，但部分截图文件未能清理：'+', '.join(failed) if failed else ''}
