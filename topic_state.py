"""Per-topic drafts and evidence; contact history stays global by account."""
import json

FIELDS=('purpose','message','target_count')
DEFAULTS={'purpose':'','message':'','target_count':40}

def init(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS topic_settings(topic TEXT PRIMARY KEY,config TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS topic_leads(topic TEXT,lead_id INTEGER,evidence TEXT NOT NULL,PRIMARY KEY(topic,lead_id));
    CREATE TABLE IF NOT EXISTS discovery_plans(topic TEXT,purpose TEXT,plan TEXT,PRIMARY KEY(topic,purpose));
    CREATE TABLE IF NOT EXISTS topic_analysis(topic TEXT PRIMARY KEY,purpose TEXT);
    ''')
    for row in con.execute("SELECT * FROM leads WHERE ai_topic!=''").fetchall():
        remember(con,row['ai_topic'],dict(row),replace=False)

def remember(con,topic,lead,replace=True):
    fields=('name','note_url','note_title','keyword','evidence','source_kind','source_text','source_comment_id','ai_fit','ai_intent','ai_uncertainty','ai_topic')
    value={k:lead[k] for k in fields};value['ai_topic']=topic
    value['analysis_goal']=lead.get('analysis_goal','')
    verb='REPLACE' if replace else 'IGNORE'
    con.execute(f'INSERT OR {verb} INTO topic_leads VALUES(?,?,?)',(topic,lead['id'],json.dumps(value,ensure_ascii=False)))

def save(con,config):
    con.execute('INSERT OR REPLACE INTO topic_settings VALUES(?,?)',(config['topic'],json.dumps({k:config.get(k,DEFAULTS[k]) for k in FIELDS},ensure_ascii=False)))

def switch(con,current,topic):
    topic=topic.strip()
    if not 1<=len(topic)<=120:raise ValueError('请输入1～120字的话题')
    save(con,current)
    row=con.execute('SELECT config FROM topic_settings WHERE topic=?',(topic,)).fetchone()
    result={'topic':topic,**(json.loads(row[0]) if row else DEFAULTS)}
    for key,value in result.items():con.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value,ensure_ascii=False)))
    return result

def leads(con,topic,purpose=None):
    rows=[]
    for row in con.execute('SELECT l.*,t.evidence AS topic_evidence FROM topic_leads t JOIN leads l ON l.id=t.lead_id WHERE t.topic=? ORDER BY l.id DESC LIMIT 2000',(topic,)):
        item=dict(row);item.update(json.loads(item.pop('topic_evidence')))
        if purpose is None or item.get('analysis_goal','')==purpose:rows.append(item)
    return rows
