"""Taobao shop/contact/reply ledger. Account and shop IDs are separate from XHS."""
from datetime import datetime
import json,re
from urllib.parse import urlsplit,parse_qs

def now():return datetime.now().isoformat(timespec='milliseconds')

def shop_key(value):
    if not isinstance(value,str):raise ValueError('店铺标识无效')
    if re.fullmatch(r'[1-9][0-9]{0,19}',value):return 'shop:'+value
    u=urlsplit(value);host=(u.hostname or '').lower()
    if u.scheme!='https' or u.username or u.password:raise ValueError('请使用官方店铺链接')
    match=re.fullmatch(r'shop([1-9][0-9]{0,19})\.taobao\.com',host)
    if match:return 'shop:'+match[1]
    if host=='store.taobao.com':
        ident=parse_qs(u.query).get('shop_id',[''])[0]
        if re.fullmatch(r'[1-9][0-9]{0,19}',ident):return 'shop:'+ident
    if re.fullmatch(r'[a-z0-9][a-z0-9-]*\.tmall\.com',host) and host.split('.')[0] not in ('www','detail','login','list'):
        return 'tmall:'+host
    raise ValueError('尚未识别为具体店铺，不能用商品 ID 或店铺名称代替店铺标识')

def identity(value):
    if not isinstance(value,str) or not 1<=len(value.strip())<=200:raise ValueError('尚未核对淘宝账号')
    return value.strip()

def init(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS taobao_shops(shop_id TEXT PRIMARY KEY,name TEXT NOT NULL,url TEXT NOT NULL,evidence TEXT NOT NULL,query TEXT NOT NULL,updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS taobao_contacts(account_id TEXT NOT NULL,shop_id TEXT NOT NULL,message TEXT NOT NULL,status TEXT NOT NULL,proof TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(account_id,shop_id));
    CREATE TABLE IF NOT EXISTS taobao_replies(account_id TEXT NOT NULL,message_id TEXT NOT NULL,shop_id TEXT NOT NULL,body TEXT NOT NULL,platform_time TEXT NOT NULL,seen INTEGER NOT NULL DEFAULT 0,received_at TEXT NOT NULL,PRIMARY KEY(account_id,message_id));
    CREATE TABLE IF NOT EXISTS taobao_messages(id INTEGER PRIMARY KEY,role TEXT NOT NULL,body TEXT NOT NULL,created_at TEXT NOT NULL);
    ''')

def save_shop(con,row,query):
    key=shop_key(row['url']);name=str(row.get('name','')).strip();evidence=str(row.get('evidence','')).strip()
    if not name or not evidence:raise ValueError('店铺名称和原页面依据不能为空')
    con.execute('INSERT INTO taobao_shops VALUES(?,?,?,?,?,?) ON CONFLICT(shop_id) DO UPDATE SET name=excluded.name,url=excluded.url,evidence=excluded.evidence,query=excluded.query,updated_at=excluded.updated_at',
                (key,name[:200],row['url'],evidence[:2000],query[:100],now()))
    return key

def claim(con,account,shop,message):
    account=identity(account)
    if not isinstance(message,str) or not 1<=len(message.strip())<=1000:raise ValueError('请填写消息正文')
    if not con.execute('SELECT 1 FROM taobao_shops WHERE shop_id=?',(shop,)).fetchone():raise ValueError('店铺不在已核对的候选中')
    # Unique across this account's campaigns. Pending/uncertain submissions never retry.
    return bool(con.execute('INSERT OR IGNORE INTO taobao_contacts(account_id,shop_id,message,status,created_at,updated_at) VALUES(?,?,?,\'pending\',?,?)',(account,shop,message,now(),now())).rowcount)

def finish(con,account,shop,status,proof):
    if status not in ('sent','not_sent','needs_review','already_contacted','rejected'):raise ValueError('发送状态无效')
    if not isinstance(proof,dict):raise ValueError('发送依据格式无效')
    if status=='sent' and not (proof.get('own_new_message_visible') is True and proof.get('screenshot')):
        raise ValueError('未确认新消息和截图，不能记录为已发送')
    if not con.execute("UPDATE taobao_contacts SET status=?,proof=?,updated_at=? WHERE account_id=? AND shop_id=? AND status='pending'",(status,json.dumps(proof,ensure_ascii=False),now(),identity(account),shop)).rowcount:
        raise ValueError('这条发送记录已处理，不能覆盖')

def add_reply(con,account,shop,message_id,body,platform_time):
    account=identity(account)
    if not all(isinstance(x,str) and x.strip() for x in (message_id,body,platform_time)):raise ValueError('消息 ID、正文和平台时间不完整，未虚构新回复')
    if not con.execute('SELECT 1 FROM taobao_contacts WHERE account_id=? AND shop_id=?',(account,shop)).fetchone():raise ValueError('这家店不属于当前账号已记录的联系对象')
    return bool(con.execute('INSERT OR IGNORE INTO taobao_replies(account_id,message_id,shop_id,body,platform_time,received_at) VALUES(?,?,?,?,?,?)',(account,message_id,shop,body,platform_time,now())).rowcount)

def state(con,account=None):
    account=identity(account) if account else ''
    return {'shops':[dict(r) for r in con.execute('SELECT * FROM taobao_shops ORDER BY updated_at DESC')],
            'contacts':[dict(r) for r in con.execute('SELECT * FROM taobao_contacts WHERE account_id=? ORDER BY updated_at DESC',(account,))],
            'replies':[dict(r) for r in con.execute('SELECT r.*,s.name FROM taobao_replies r JOIN taobao_shops s ON s.shop_id=r.shop_id WHERE account_id=? ORDER BY received_at DESC',(account,))]}
