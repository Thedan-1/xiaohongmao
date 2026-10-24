"""Read-only smoke check against the running local workbench."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'.runtime'))
from playwright.sync_api import sync_playwright
from adapter import INCOMING_MESSAGES_JS

info=json.loads((ROOT/'data/runtime.json').read_text(encoding='utf-8'))
with sync_playwright() as pw:
    browser=pw.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(info['url'],wait_until='networkidle')
    page.get_by_role('heading',name='先找相关的人').wait_for()
    page.locator('#lead-body tr').first.wait_for()
    count=page.locator('#lead-body tr').count()
    assert count>0
    page.locator('#filter-text').fill('BIM工作室')
    assert page.locator('#lead-body tr').count()>=1
    page.locator('#filter-text').fill('')
    page.get_by_text('筛选 / 导出',exact=True).click()
    with page.expect_download() as download:
        page.get_by_role('button',name='导出 CSV ↓').click()
    download.value.save_as(str(ROOT/'data/test-export.csv'))
    text=(ROOT/'data/test-export.csv').read_text(encoding='utf-8-sig')
    assert 'BIM工作室' in text and '客户名称' in text
    page.screenshot(path=str(ROOT/'data/workbench-preview.png'),full_page=True)
    page.locator('[data-view="messages"]').click()
    assert page.locator('#message').input_value()
    page.locator('[data-view="discover"]').click()
    page.locator('#lead-body input[type="checkbox"]:enabled').first.check()
    page.locator('#next-step').click()
    assert '已选择 1 人' in page.locator('#chosen-people').inner_text()
    page.get_by_role('button',name='预览并发送',exact=True).click()
    assert page.locator('#send-dialog').is_visible()
    assert page.locator('#send-content').inner_text()
    page.get_by_role('button',name='返回修改').click()
    page.get_by_role('button',name='使用方法',exact=True).click()
    assert page.get_by_role('heading',name='需要 API 或 AI 付费吗？').is_visible()
    page.locator('[data-view="discover"]').click()
    page.set_viewport_size({'width':600,'height':900})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    parser=browser.new_page()
    parser.set_content((ROOT/'data/send-dom.html').read_text(encoding='utf-8'))
    assert parser.locator('.chat-item[data-message-id]').evaluate_all(INCOMING_MESSAGES_JS)==[], 'Own messages or platform hints counted as replies'
    parser.set_content('''<div class="chat-item" data-message-id="test-incoming"><div class="chat-item__content"><div class="chat-item__bubble">测试入站消息</div></div></div><div class="chat-item" data-message-id="hint"><div class="chat-item__pure">系统提示</div></div>''')
    assert parser.locator('.chat-item[data-message-id]').evaluate_all(INCOMING_MESSAGES_JS)==[{'id':'test-incoming','body':'测试入站消息'}]
    assert not errors,errors
    print(json.dumps({'ui':'passed','visible_leads':count,'export':'passed','send_preview':'passed without sending','reply_parser':'passed fixture test; live incoming not verified','js_errors':errors},ensure_ascii=False))
    browser.close()
