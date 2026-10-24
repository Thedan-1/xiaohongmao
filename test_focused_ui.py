"""UI smoke test. Message preview is cancelled; settings writes are intercepted."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'.runtime'))
from playwright.sync_api import sync_playwright
from edge_path import find_edge

info=json.loads((ROOT/'data/runtime.json').read_text())
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path=find_edge(),headless=True)
    page=browser.new_page(viewport={'width':1400,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(info['url'],wait_until='networkidle')
    page.get_by_role('heading',name='输入话题，找到相关的人').wait_for()
    page.locator('#lead-body input:enabled').first.wait_for()
    candidates=page.locator('#lead-body tr').count()
    assert candidates>=3
    page.locator('#lead-body input:enabled').first.check()
    page.route('**/api/settings',lambda route:route.fulfill(status=200,content_type='application/json',body='{"ok":true}'))
    page.locator('#message').fill('这是可以自行编辑的测试消息，仅预览，不发送。')
    page.locator('#send').click()
    assert page.locator('#send-dialog').is_visible()
    assert '仅预览，不发送' in page.locator('#send-content').inner_text()
    assert '评论者' in page.locator('#send-people').inner_text() or '笔记作者' in page.locator('#send-people').inner_text()
    page.locator('#send-cancel').click()
    page.get_by_role('button',name='使用说明',exact=True).click()
    assert '评论测试' in page.locator('#help').inner_text()
    page.locator('#help').get_by_role('button',name='返回找客户').click()
    page.set_viewport_size({'width':600,'height':900})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.set_viewport_size({'width':1400,'height':1000})
    page.reload(wait_until='networkidle')
    page.screenshot(path=str(ROOT/'data/focused-workbench.png'),full_page=True)
    assert not errors,errors
    if '--start-discovery' in sys.argv:
        page.unroute('**/api/settings')
        page.locator('#topic').fill('BIM')
        page.locator('#discover').click()
        page.wait_for_function("()=>document.querySelector('#discover').textContent.includes('正在处理')",timeout=15000)
        print('Live topic discovery started through the UI; no sending action.',flush=True)
    print(json.dumps({'UI':'passed','AI_candidates':candidates,'editable_message':'preview verified, no writes or sends','mobile':'passed','errors':errors},ensure_ascii=False),flush=True)
    browser.close()
