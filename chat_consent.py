"""Recognize a human's direct approval and bind it to immutable existing drafts.

Only the latest trusted human chat message is considered. Public notes, quoted
instructions, model output, questions and future blanket permissions grant none.
"""
import hashlib
import json
import re

def decision(text):
    if not isinstance(text,str):return None
    text=text.strip()
    if not text or len(text)>160:return None
    # A question, quotation, hypothetical, refusal or changed-content request is
    # not approval of the exact draft currently on screen.
    if re.search(r'[?？“”「」『』"\n]|能不能|可不可以|能否|是否|可否|怎么|如何|为什么|什么|意思|为何|会不会|要不要|是不是|按钮|功能|权限|在哪|有没有|如果|假如|假设|比如|例如|只是|说说|示例|他说|她说|用户说|以后|后续|今后|所有项目|永久|默认|不要|别发|别发送|不发|不发送|不同意|不允许|没允许|没有允许|未确认|先不|暂不|取消|撤销|稍后|等一下|等等|吗|嘛|呢|修改|改成|换成|换个|新的文案|不是',text):return None
    normalized=re.sub(r'[\s，,。.!！、:：;；]','',text)
    if not re.search(r'发送|发出|发出去|发吧|发这|发刚才|开始发|现在发|直接发|都发|全发|发评论|发私信|可以发|允许发|同意发|发(?:这些|这批|刚才预览的)(?:评论|私信)',normalized):return None
    # Explicit performative or imperative. Merely discussing a permission never
    # qualifies, even when the model proposes a send action.
    if not re.match(r'^(?:好|可以|行|对|那|就|现在|直接|请|帮我|替我|给|我|确认|同意|允许|授权|开始|按|把|发送|发)',normalized):return None
    words=['确认','同意','允许','授权','开始','发送','发出去','发出','发','按','现在','直接','当前','刚才','最新','预览','草稿','这批','这些','这个','这份','这样','本次','已经','准备好','全部','所有人','所有','内容','普通评论','回复评论','评论','私信','追评','完全','照原样','照','好的','可以','没问题','没错','帮我','替我','给我','给','我','想','要','请','把','就','都','全','对','那','好','行','吧','的','条','个','份','批','第','号','一次']
    words+=['了','你']
    remaining=re.sub('|'.join(map(re.escape,sorted(words,key=len,reverse=True)))+r'|[0-9#]','',normalized)
    if remaining:return None
    channels=[]
    if '私信' in text:channels.append('dm')
    if '追评' in text or '回复评论' in text:channels.append('reply')
    elif '评论' in text:channels.append('note')
    if len(channels)>1:return {'ambiguous':True}
    count=re.search(r'(\d{1,3})\s*(?:条|个)',text)
    did=re.search(r'草稿\s*[#号]?\s*(\d+)',text)
    return {'channel':channels[0] if channels else None,'count':int(count[1]) if count else None,
            'draft_id':int(did[1]) if did else None,'latest':bool(re.search(r'刚才|最新|这批|当前',text))}

def fingerprint(draft):
    items=draft['items']
    if isinstance(items,str):items=json.loads(items)
    value={'project_id':draft['project_id'],'id':draft['id'],'account_id':draft['account_id'],'channel':draft['channel'],'items':items}
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()

def init(con):
    con.execute('''CREATE TABLE IF NOT EXISTS studio_authorizations(
      id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL,draft_id INTEGER NOT NULL,
      message_id INTEGER NOT NULL,draft_hash TEXT NOT NULL,status TEXT NOT NULL,
      created_at TEXT NOT NULL,UNIQUE(project_id,draft_id,message_id))''')

def authorize(con,pid,message_id,text,now):
    row=con.execute("SELECT body FROM studio_messages WHERE id=? AND project_id=? AND role='user'",(message_id,pid)).fetchone()
    if not row or row['body']!=text:return None,'没有找到当前项目的明确用户确认，尚未发送。'
    latest=con.execute("SELECT MAX(id) FROM studio_messages WHERE project_id=? AND role='user'",(pid,)).fetchone()[0]
    if latest!=message_id:return None,'这条确认之后已有新的用户要求，请按当前预览重新确认。没有发送。'
    if con.execute('SELECT 1 FROM studio_authorizations WHERE project_id=? AND message_id=?',(pid,message_id)).fetchone():
        return None,'这次确认已经处理，不会重复发送。'
    parsed=decision(text)
    if not parsed:return None,None
    if parsed.get('ambiguous'):return None,'请说明先发送哪一批预览：评论还是私信。没有发送。'
    drafts=[dict(d) for d in con.execute("SELECT * FROM studio_drafts WHERE project_id=? AND status='preview' ORDER BY id DESC",(pid,))]
    if parsed['channel']:drafts=[d for d in drafts if d['channel']==parsed['channel']]
    if parsed['draft_id']:drafts=[d for d in drafts if d['id']==parsed['draft_id']]
    if parsed['count'] is not None:drafts=[d for d in drafts if len(json.loads(d['items']))==parsed['count']]
    if parsed['latest'] and drafts:drafts=drafts[:1]
    if not drafts:return None,'当前没有符合这次确认的待发送预览。请先准备内容和对象，再说“确认发送这批”。没有发送。'
    if len(drafts)!=1:return None,'当前有多份待发送预览，请说明是哪批，例如“确认发送刚才预览的私信”。没有发送。'
    d=drafts[0];digest=fingerprint(d)
    prior=con.execute('SELECT id,status,draft_hash FROM studio_authorizations WHERE project_id=? AND draft_id=? AND message_id=?',(pid,d['id'],message_id)).fetchone()
    if prior:return None,'这次确认已经处理，不会重复发送。'
    aid=con.execute("INSERT INTO studio_authorizations(project_id,draft_id,message_id,draft_hash,status,created_at) VALUES(?,?,?,?,'authorized',?)",(pid,d['id'],message_id,digest,now)).lastrowid
    return {'authorization_id':aid,'draft_id':d['id'],'count':len(json.loads(d['items'])),'channel':d['channel']},None
