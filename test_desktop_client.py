"""Exercise the real WinForms/WebView2 client with isolated data and no outbound jobs."""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT=Path(__file__).resolve().parent
STAGE=Path(os.environ.get('XIAOHONGMAO_TEST_INSTALL',str(ROOT/'release/小红帽-Windows-x64-v0.6')))
CLIENT_ARGS=['--smoke-test']+(['--preview'] if os.environ.get('XIAOHONGMAO_TEST_PREVIEW')=='1' else [])

def api(home,path,body=None):
    info=json.loads((home/'data/runtime.json').read_text(encoding='utf-8'))
    q=urllib.request.Request(info['url']+path,data=body,headers={'X-App-Token':info['token'],'Content-Type':'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(q,timeout=5) as r:return json.load(r)

def case(name,reuse=False):
    home=ROOT/'data/desktop-qa'/f'{name}-{time.time_ns()}'
    home.mkdir(parents=True)
    env=os.environ.copy();env.update(XIAOHONGMAO_DATA_HOME=str(home),XIAOHONGMAO_DESKTOP_SMOKE='1',PATH=os.path.join(os.environ['SystemRoot'],'System32'))
    env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    backend=None;client=None
    # Existing user configuration must survive upgrades and startup unchanged.
    sentinel='DEEPSEEK_API_KEY=offline-test-no-paid-calls\n'
    (home/'deepseek.local.txt').write_text(sentinel,encoding='utf-8')
    try:
        if reuse:
            backend=subprocess.Popen([str(STAGE/'python/pythonw.exe'),'-X','utf8',str(STAGE/'app.py'),'--no-browser'],cwd=STAGE,env=env,creationflags=subprocess.CREATE_NO_WINDOW,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            for _ in range(80):
                try:api(home,'/api/state');break
                except Exception:time.sleep(.1)
            else:raise AssertionError('fixture backend not ready')
        client=subprocess.Popen([str(STAGE/'小红帽.exe'),*CLIENT_ARGS],cwd=STAGE,env=env)
        for _ in range(80):
            if (home/'client.json').exists():break
            if client.poll() is not None:raise AssertionError('client exited before startup')
            time.sleep(.05)
        second=subprocess.run([str(STAGE/'小红帽.exe'),*CLIENT_ARGS],cwd=STAGE,env=env,timeout=10)
        assert second.returncode==0,'duplicate launch must reuse existing window'
        assert client.wait(timeout=135)==0,(home/'desktop-test.json').read_text(encoding='utf-8')
        result=json.loads((home/'desktop-test.json').read_text(encoding='utf-8'));assert result['ok'],result
        assert (home/'deepseek.local.txt').read_text(encoding='utf-8')==sentinel,'key overwritten'
        if reuse:
            assert backend.poll() is None,'reused backend terminated'
            assert api(home,'/api/state')['state']['task']=='idle'
        else:
            try:api(home,'/api/state')
            except Exception:pass
            else:raise AssertionError('owned backend left running')
        print(name,json.dumps(result,ensure_ascii=False),flush=True)
        return {'name':name,'home':str(home),'result':result,'duplicate_launch':'pass','existing_key_preserved':True}
    finally:
        try:api(home,'/api/command',b'{"command":"shutdown"}')
        except Exception:pass
        if backend:backend.wait(timeout=20)
        if client and client.poll() is None:client.terminate();client.wait(timeout=10)

if __name__=='__main__':
    results=[case('首次启动 中文 空格'),case('复用已有后台',reuse=True)]
    report=ROOT/'data/desktop-qa/native-client-results.json'
    report.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Native client tests passed:',report)
