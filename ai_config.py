"""Per-user AI connection settings. Secrets never appear in public responses."""
import json
import math
import os
from pathlib import Path
import re
import threading
import uuid
from urllib.parse import urlsplit
from app_paths import data_home,config_file

ROOT=Path(__file__).resolve().parent
LOCK=threading.RLock()
DEFAULT_PRICING={'input':2.0,'cached_input':.04,'output':8.0}

def path(root=None):return data_home(root or ROOT)/'ai-settings.json'

def model_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/@+\-]{0,159}',value):
        raise ValueError('请填写有效的模型 ID')
    return value

def endpoint(value):
    if not isinstance(value,str):raise ValueError('请填写 HTTPS 接口地址')
    value=value.strip().rstrip('/');u=urlsplit(value)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment or any(c.isspace() for c in value):
        raise ValueError('接口地址必须为 HTTPS，不能包含账号、参数或空格')
    if u.path.endswith(('/chat/completions','/models')):raise ValueError('请填写接口根地址，不含 /chat/completions 或 /models')
    try:u.port
    except ValueError:raise ValueError('接口端口不正确') from None
    return value

def pricing(value):
    if not isinstance(value,dict):raise ValueError('请填写模型的费用估算单价')
    result={}
    for name in ['input','cached_input','output']:
        v=value.get(name)
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=100000:
            raise ValueError('费用单价必须为有效的非负数')
        if name!='cached_input' and v<=0:raise ValueError('输入和输出单价必须大于零')
        result[name]=float(v)
    if result['cached_input']>result['input']:raise ValueError('缓存输入单价不能大于普通输入单价')
    return result

def defaults():
    return {'base_url':'https://api.deepseek.com','model':'deepseek-flash','models':['deepseek-flash'],'pricing':dict(DEFAULT_PRICING)}

def load(root=None):
    result=defaults()
    f=path(root)
    if f.exists():
        try:raw=json.loads(f.read_text(encoding='utf-8'))
        except (ValueError,OSError):raise RuntimeError('AI 配置无法读取，请在设置中重新保存') from None
        if not isinstance(raw,dict):raise RuntimeError('AI 配置格式不正确')
        try:
            result.update(base_url=endpoint(raw.get('base_url',result['base_url'])),model=model_id(raw.get('model',result['model'])),pricing=pricing(raw.get('pricing',DEFAULT_PRICING)))
            models=raw.get('models',[result['model']])
            if not isinstance(models,list) or len(models)>100:raise ValueError()
            result['models']=list(dict.fromkeys([result['model']]+[model_id(x) for x in models]))
            if 'api_key' in raw:
                if not isinstance(raw['api_key'],str) or (raw['api_key'] and not re.fullmatch(r'[\x21-\x7e]{1,1024}',raw['api_key'])):raise ValueError()
                result['api_key']=raw['api_key']
        except (ValueError,TypeError):raise RuntimeError('AI 配置格式不正确，请重新填写并保存') from None
    return result

def key(config=None,root=None):
    config=load(root) if config is None else config
    if 'api_key' in config:return str(config['api_key'])
    f=config_file(root or ROOT)
    if not f.exists():return ''
    for line in f.read_text(encoding='utf-8-sig').splitlines():
        name,sep,value=line.partition('=')
        if sep and name.strip()=='DEEPSEEK_API_KEY':return value.strip().strip('"\'')
    return ''

def public(root=None):
    try:
        cfg=load(root)
        return {**{k:v for k,v in cfg.items() if k!='api_key'},'configured':bool(key(cfg,root))}
    except (RuntimeError,OSError):
        return {**defaults(),'configured':False,'configuration_error':'AI 配置无法读取，请重新填写接口、密钥、模型和单价后保存'}

def validate(data,root=None):
    try:cfg=load(root)
    except RuntimeError:
        if not all(k in data for k in ['base_url','model','pricing']) or not (data.get('api_key') or data.get('clear_key') is True):
            raise ValueError('原配置无法读取，请完整填写配置和密钥，或明确移除密钥后保存') from None
        cfg={**defaults(),'api_key':''}
    if 'base_url' in data:
        base=endpoint(data['base_url'])
        if base!=cfg['base_url']:
            if not data.get('api_key') and data.get('clear_key') is not True:raise ValueError('更换接口地址时，请重新填写对应服务的密钥')
            cfg['models']=[]
        cfg['base_url']=base
    if 'model' in data:cfg['model']=model_id(data['model'])
    if 'pricing' in data:cfg['pricing']=pricing(data['pricing'])
    if data.get('clear_key') is True:cfg['api_key']=''
    elif data.get('api_key'):
        value=data['api_key']
        if not isinstance(value,str) or not re.fullmatch(r'[\x21-\x7e]{1,1024}',value):raise ValueError('密钥不能包含空格、换行或非英文字符')
        cfg['api_key']=value
    if 'models' in data:
        if not isinstance(data['models'],list) or len(data['models'])>100:raise ValueError('模型列表不正确')
        cfg['models']=[model_id(x) for x in data['models']]
    cfg['models']=list(dict.fromkeys([cfg['model']]+cfg['models']))[:100]
    return cfg

def save(data,root=None):
    with LOCK:
        cfg=validate(data,root)
        # Move the existing legacy key into the same atomic config when preserving it.
        if 'api_key' not in cfg:cfg['api_key']=key(cfg,root)
        f=path(root);f.parent.mkdir(parents=True,exist_ok=True)
        temporary=f.with_name(f.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with temporary.open('x',encoding='utf-8') as out:
                json.dump(cfg,out,ensure_ascii=False,indent=2);out.flush();os.fsync(out.fileno())
            os.replace(temporary,f)
        except OSError:raise RuntimeError('设置未能保存，请检查本机目录是否可写；原配置未主动清空') from None
        finally:
            if temporary.exists():temporary.unlink()
    return public(root)

def handle(app,data):
    import studio,workflow_ai,deepseek_client
    with studio.ADMISSION_LOCK:
        if studio.is_busy(app):raise ValueError('任务运行中，请暂停或完成后再修改 AI 设置')
        action=data.get('action','save')
        if action=='budget':
            if isinstance(data.get('limit'),(int,float)) and data['limit']>1000000:raise ValueError('费用上限不能超过 1000000 元')
            return {'budget':workflow_ai.authorize_budget(data.get('limit'),'用户在设置中调整本机费用上限')}
        if action=='models':
            cfg=validate(data,deepseek_client.ROOT)
            response=deepseek_client.request('/models',configuration=cfg)
            rows=response.get('data') if isinstance(response,dict) else None
            if not isinstance(rows,list):raise RuntimeError('服务未返回有效的模型列表，请手动填写模型 ID')
            ids=[]
            for row in rows:
                try:ids.append(model_id(row['id']))
                except (KeyError,TypeError,ValueError):continue
            return {'models':list(dict.fromkeys(ids))[:100]}
        if action!='save':raise ValueError('不支持的设置操作')
        return save(data,deepseek_client.ROOT)
