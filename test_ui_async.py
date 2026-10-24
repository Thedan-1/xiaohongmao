"""Real compiled UI in headless Edge; only isolated data and stubbed API promises."""
import unittest
from pathlib import Path
import app,studio,test_studio
from playwright.sync_api import sync_playwright
from edge_path import find_edge

class UiAsyncTests(unittest.TestCase):
    def test_automatic_account_refresh_leaves_visible_login_window_open(self):
        result=self.page.evaluate("""async()=>{
          fixtures[1].state={...fixtures[1].state,account:null,background:false,login:'unknown'};
          let accountCalls=0;api=async(path,data)=>{if(data?.command==='account')accountCalls++;return fixtureApi(path,data)};
          autoAccount=false;await refresh();return accountCalls;
        }""")
        self.assertEqual(result,0)
        self.assertEqual(self.errors,[])
    def test_dm_proof_opens_actual_saved_screenshot_without_a_send(self):
        self.page.evaluate("""()=>{
          model.drafts=[{id:8,channel:'dm',status:'complete',created_at:'now',items:[{source:{author:'A',id:1},message:'hello',status:'sent',result:'saved',dm_proof:{draft_id:8,index:3,time:'2026-10-22T12:00:00'}}]}];
          fetch=async url=>{window.proofUrl=url;return new Response(new Blob(['fixture'],{type:'image/png'}))};
          setPanel(true,'drafts');
        }""")
        self.page.locator('[data-dm-proof]').click()
        self.page.wait_for_function('!!window.proofUrl')
        self.assertIn('/api/studio-dm-proof?project=1&draft=8&item=3',self.page.evaluate('proofUrl'))
        self.assertEqual(self.errors,[])

    def test_chat_preview_syncs_four_targets_and_template_to_form(self):
        self.page.evaluate("""async()=>{
          const f=fixtures[1];f.notes=Array.from({length:20},(_,i)=>({key:String(i),title:'BIM',author:'A',body:'BIM',type:'image',contact_status:'ready'}));
          f.drafts=[{id:7,channel:'note',status:'preview',items:f.notes.slice(0,4).map(source=>({source,message:'想学习BIM从哪里开始 求佬教教',status:'ready'}))}];
          await refresh();
        }""")
        self.assertEqual(self.page.evaluate('noteSelection.size'),4)
        self.assertIn('当前选择 4 个',self.page.locator('#draft-scope').inner_text())
        self.assertEqual(self.page.locator('#draft-template').input_value(),'想学习BIM从哪里开始 求佬教教')
        self.assertTrue(self.page.locator('#build-draft').is_enabled())
        self.assertEqual(self.errors,[])

    def test_empty_form_disables_preview_and_explicit_all_selects_twenty(self):
        self.page.evaluate("""()=>{
          model.notes=Array.from({length:20},(_,i)=>({key:String(i),title:'BIM',author:'A',body:'BIM',type:'image',contact_status:'ready'}));
          model.drafts=[];noteSelection.clear();draftConfig.channel='note';setPanel(true,'drafts');
        }""")
        self.assertTrue(self.page.locator('#build-draft').is_disabled())
        self.page.locator('[data-draft-all]').click()
        self.assertEqual(self.page.evaluate('noteSelection.size'),20)
        self.assertTrue(self.page.locator('#build-draft').is_enabled())
        self.assertIn('当前选择 20 个',self.page.locator('#draft-scope').inner_text())
        self.assertEqual(self.errors,[])

    def test_one_answer_header_and_completed_steps_collapsed(self):
        self.page.evaluate("""()=>{
            model.messages=[{id:1,role:'user',body:'search',created_at:'2026-10-22T12:00:00'},
             {id:2,role:'assistant',body:'intermediate draft ready',created_at:'2026-10-22T12:01:00'},
             {id:3,role:'assistant',body:'final summary',created_at:'2026-10-22T12:02:00'}];
            model.jobs=[{id:1,kind:'search',status:'complete',after_message_id:1,created_at:'2026-10-22T12:00:00',activity:[],frames:[]}];
            lastMessages='';renderMessages();
        }""")
        self.assertEqual(self.page.locator('.assistant-head').count(),1)
        self.assertEqual(self.page.locator('.turn-record:not([open])').count(),1)
        self.assertEqual(self.page.locator('.message.assistant>.bubble').inner_text(),'final summary')
        self.assertFalse(self.page.locator('.interim-reply').is_visible())
        self.page.locator('.turn-record>summary').click()
        self.assertTrue(self.page.locator('.interim-reply').is_visible())
        self.assertEqual(self.errors,[])

    def test_running_record_expands_then_collapses_on_completion(self):
        self.page.evaluate("""()=>{
          model.messages=[{id:1,role:'user',body:'search',created_at:'2026-10-22T12:00:00'}];
          model.jobs=[{id:2,kind:'search',status:'running',after_message_id:1,created_at:'2026-10-22T12:00:00',activity:[{body:'reading',created_at:'2026-10-22T12:00:01'}],frames:[]}];
          lastMessages='';renderMessages();
        }""")
        self.assertTrue(self.page.locator('.turn-record').get_attribute('open') is not None)
        self.page.evaluate("model.jobs[0].status='complete';renderMessages()")
        self.assertIsNone(self.page.locator('.turn-record').get_attribute('open'))

    def test_click_historical_step_uses_its_frame_and_live_updates_do_not_replace_it(self):
        result=self.page.evaluate("""async()=>{
          let requests=[];fetch=async url=>{requests.push(url);return new Response(new Blob(['fixture'],{type:'image/jpeg'}))};
          model.messages=[{id:1,role:'user',body:'search',created_at:'2026-10-22T12:00:00'}];
          model.jobs=[{id:2,kind:'search',status:'complete',after_message_id:1,created_at:'2026-10-22T12:00:00',activity:[],frames:[{id:42,project_id:1,job_id:2,label:'old search',time:'2026-10-22T12:00:01'}]}];
          lastMessages='';renderMessages();document.querySelector('[data-job="2"]>summary').click();
          await new Promise(r=>setTimeout(r,30));
          model.frame={project_id:1,job_id:3,time:'new',revision:'new'};await updateFrame();
          return {requests,historical:historicalFrame?.id,meta:document.querySelector('#frame-meta')?.textContent};
        }""")
        self.assertTrue(all('&frame=42' in url for url in result['requests']))
        self.assertEqual(result['historical'],42)
        self.assertIn('历史画面',result['meta'])
        self.assertEqual(self.errors,[])

    def setUp(self):
        test_studio.StudioTests.setUp(self)
        second=studio.request(app,{'action':'create','title':'第二项目'})['project_id']
        self.assertEqual(second,2)
        fixtures={}
        with app.connect() as con:
            for pid in (1,2):
                value=studio.state(con,pid)
                value.update(state={**app.STATE,'login':'ready'},ai={'budget':{'remaining':20}})
                fixtures[str(pid)]=value
        self.pw=sync_playwright().start()
        self.browser=self.pw.chromium.launch(executable_path=find_edge(),headless=True)
        self.page=self.browser.new_page();self.errors=[]
        self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        html=Path('ui.html').read_text(encoding='utf-8')
        self.assertIn('refresh();setInterval(refresh,1800);',html)
        html=html.replace('refresh();setInterval(refresh,1800);','')
        self.page.route('**/*',lambda r:r.fulfill(content_type='text/html',body=html))
        self.page.goto('http://127.0.0.1:8765/?project=1')
        self.page.evaluate("""async fixtures=>{
            window.fixtures=fixtures;
            window.fixtureApi=async(path,data)=>structuredClone(fixtures[Number(new URL('http://fixture/'+path).searchParams.get('project')||pid)||1]);
            api=fixtureApi;await refresh();
        }""",fixtures)
    def tearDown(self):
        self.browser.close();self.pw.stop()
        test_studio.StudioTests.tearDown(self)

    def test_late_refresh_cannot_undo_project_switch(self):
        self.page.evaluate("""async()=>{
            let release,calls=0;
            api=async(path,data)=>{if(calls++===0)return await new Promise(r=>release=r);return fixtureApi(path,data)};
            const pending=refresh();await changeProject(2);
            release(structuredClone(fixtures[1]));await pending;
        }""")
        try:self.page.wait_for_function('pid===2&&model.project.id===2',timeout=1500)
        except Exception:self.fail('A late response overwrote selected project: '+str(self.page.evaluate('({pid,shown:model.project.id})')))
        self.assertEqual(self.errors,[])

    def test_switch_away_and_back_discards_old_same_project_response(self):
        self.page.evaluate("""async()=>{
            let release,calls=0;
            api=async(path,data)=>{if(calls++===0)return await new Promise(r=>release=r);const next=await fixtureApi(path,data);next.project.title='最新版本';return next};
            const pending=refresh();await changeProject(2);await changeProject(1);
            const old=structuredClone(fixtures[1]);old.project.title='过期版本';release(old);await pending;
        }""")
        try:self.page.wait_for_function("pid===1&&model.project.title==='最新版本'",timeout=1500)
        except Exception:self.fail('A→B→A accepted an obsolete response')

    def test_rejected_chat_keeps_unsent_text_without_automatic_retry(self):
        result=self.page.evaluate("""async()=>{
            let calls=0;api=async()=>{calls++;throw Error('本地存储不可用')};
            $('prompt').value='英雄联盟剪辑的新要求';await sendChat();
            return {text:$('prompt').value,calls};
        }""")
        self.assertEqual(result,{'text':'英雄联盟剪辑的新要求','calls':1})

    def test_pending_chat_double_click_submits_once_and_preserves_new_edit(self):
        result=self.page.evaluate("""async()=>{
            let release,calls=0;api=async(path,data)=>{if(data){calls++;return await new Promise(r=>release=r)}return fixtureApi(path,data)};
            $('prompt').value='第一句';const first=sendChat();const second=sendChat();
            $('prompt').value='正在编辑的第二句';release({ok:true});await Promise.all([first,second]);
            return {text:$('prompt').value,calls};
        }""")
        self.assertEqual(result,{'text':'正在编辑的第二句','calls':1})

    def test_chat_completion_does_not_clear_other_project_identical_text(self):
        result=self.page.evaluate("""async()=>{
            let release;api=async(path,data)=>data?await new Promise(r=>release=r):await fixtureApi(path,data);
            $('prompt').value='相同内容';const pending=sendChat();await changeProject(2);
            $('prompt').value='相同内容';release({ok:true});await pending;
            return {text:$('prompt').value,pid,shown:model.project.id};
        }""")
        self.assertEqual(result,{'text':'相同内容','pid':2,'shown':2})

    def test_loading_project_does_not_admit_chat_using_previous_model(self):
        result=self.page.evaluate("""async()=>{
            let release,posts=0;api=async(path,data)=>{if(data){posts++;return {ok:true}}return await new Promise(r=>release=r)};
            const changing=changeProject(2);$('prompt').value='等新项目准备好';await sendChat();
            const result={posts,text:$('prompt').value};release(structuredClone(fixtures[2]));await changing;return result;
        }""")
        self.assertEqual(result,{'posts':0,'text':'等新项目准备好'})

    def test_stale_refresh_error_cannot_replace_current_project_status(self):
        self.page.evaluate("""async()=>{
            let reject,calls=0;api=async(path,data)=>{if(calls++===0)return await new Promise((r,j)=>reject=j);return fixtureApi(path,data)};
            const pending=refresh();await changeProject(2);reject(Error('旧项目连接错误'));await pending;
        }""")
        self.page.wait_for_function('pid===2&&model.project.id===2')
        self.assertNotIn('旧项目连接错误',self.page.locator('#activity').inner_text())

    def test_new_job_frame_same_second_is_not_skipped(self):
        result=self.page.evaluate("""async()=>{
            let calls=0;fetch=async()=>{calls++;return new Response(new Blob(['fixture '+calls],{type:'image/jpeg'}))};
            model.frame={project_id:1,job_id:10,time:'2026-10-22T07:45:00',label:'first'};
            await updateFrame();const first=frameUrl;
            model.frame={project_id:1,job_id:11,time:'2026-10-22T07:45:00',label:'second'};
            await updateFrame();return {calls,changed:frameUrl!==first};
        }""")
        self.assertEqual(result,{'calls':2,'changed':True})

    def test_same_job_new_frame_revision_is_not_skipped(self):
        result=self.page.evaluate("""async()=>{
            let calls=0;fetch=async()=>{calls++;return new Response(new Blob(['fixture '+calls],{type:'image/jpeg'}))};
            model.frame={project_id:1,job_id:10,time:'2026-10-22T07:45:00',revision:'one',label:'first'};
            await updateFrame();model.frame={...model.frame,revision:'two',label:'second'};
            await updateFrame();return calls;
        }""")
        self.assertEqual(result,2)

    def test_late_image_after_switch_away_and_back_is_discarded(self):
        result=self.page.evaluate("""async()=>{
            let release;fetch=async()=>await new Promise(r=>release=r);
            const frame={project_id:1,job_id:10,time:'2026-10-22T07:45:00',label:'old'};model.frame=frame;
            const pending=updateFrame();await changeProject(2);await changeProject(1);model.frame=frame;
            release(new Response(new Blob(['old fixture'],{type:'image/jpeg'})));await pending;return frameUrl;
        }""")
        self.assertEqual(result,'')

    def test_capture_generates_new_revision_even_with_same_display_time(self):
        import json
        from unittest.mock import Mock,patch
        folder=Path(app.DB).parent/'frames';folder.mkdir()
        worker=Mock();worker.page.is_closed.return_value=False;worker.page.url='http://fixture/note'
        from contextlib import nullcontext
        worker.browser_operation.side_effect=lambda *a:nullcontext()
        worker.page.screenshot.return_value=b'isolated fixture';worker.studio_job_id=10
        with patch.object(app,'DATA',folder),patch.object(studio,'now',return_value='same second'):
            studio.capture(worker,app,1,'first',True)
            first=json.loads((folder/'studio-frame-1.json').read_text(encoding='utf-8'))
            studio.capture(worker,app,1,'second',True)
            second=json.loads((folder/'studio-frame-1.json').read_text(encoding='utf-8'))
        self.assertEqual(first['time'],second['time']);self.assertNotEqual(first['revision'],second['revision'])

if __name__=='__main__':unittest.main()
