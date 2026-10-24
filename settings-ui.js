// Settings are a full page; edits survive background refreshes until saved/closed.
const uiPreferences=(()=>{try{return {shortcut:'enter',reduceMotion:false,...JSON.parse(localStorage.getItem('xhm-ui-preferences')||'{}')}}catch{return {shortcut:'enter',reduceMotion:false}}})();
let settingsOpen=false,aiDirty=false,budgetDirty=false,settingsSaving=false,modelsLoading=false,modelFetchVersion=0,aiFormSignature='';
const settingsTitles={general:'常规',account:'账号与登录',ai:'模型与 API',usage:'用量与预算',archive:'已归档聊天',about:'关于'};
document.documentElement.classList.toggle('reduce-motion',Boolean(uiPreferences.reduceMotion));
function toggleProfileMenu(){const p=$('profile-menu');p.hidden=!p.hidden;$('settings').setAttribute('aria-expanded',String(!p.hidden))}
function closeSettings(){settingsOpen=false;$('settings-page').hidden=true;document.querySelector('.app').hidden=false;$('ai-api-key').value='';$('ai-api-key').type='password';$('show-api-key').textContent='显示';modelFetchVersion++;aiDirty=false;budgetDirty=false;aiFormSignature=''}
function openSettings(name='general'){
 settingsTab=settingsTitles[name]?name:'general';settingsOpen=true;settingsKey='';aiDirty=false;budgetDirty=false;aiFormSignature='';
 $('profile-menu').hidden=true;$('model-menu').hidden=true;$('settings').setAttribute('aria-expanded','false');
 $('settings-page').hidden=false;document.querySelector('.app').hidden=true;$('settings-search').value='';
 document.querySelectorAll('[data-settings-tab]').forEach(b=>b.hidden=false);renderSettings(true);$('settings-title').focus();
}
function renderSettings(force=false){
 if(!model)return;
 const info=model.state.account;
 if(!settingsOpen)return;
 const ai=model.ai||{},budget=ai.budget||{};
 $('settings-title').textContent=settingsTitles[settingsTab];
 document.querySelectorAll('[data-settings-tab]').forEach(b=>{const active=b.dataset.settingsTab===settingsTab;b.classList.toggle('active',active);b.setAttribute('aria-current',active?'page':'false')});
 Object.keys(settingsTitles).forEach(name=>$('settings-'+name).hidden=settingsTab!==name);
 if(settingsTab==='about'&&typeof updateState!=='undefined'&&updateState)renderUpdateStatus(updateState);
 $('settings-profile').innerHTML=avatar(info)+'<div><b>'+esc(info?.name||'未连接小红书账号')+'</b><p>'+esc(model.state.login==='ready'?'已登录':model.state.login==='connecting'?'正在检测登录…':'尚未完成登录')+(info?.public_id?' · '+esc(info.public_id):'')+'</p></div>';
 $('settings-login').disabled=$('settings-refresh-account').disabled=busy();
 const signature=JSON.stringify([ai.base_url,ai.model,ai.configured,ai.pricing,ai.models]);
 if(!aiDirty&&!settingsSaving&&signature!==aiFormSignature){
  aiFormSignature=signature;$('ai-base-url').value=ai.base_url||'https://api.deepseek.com';$('ai-model-id').value=ai.model||'deepseek-flash';$('ai-api-key').value='';$('clear-api-key').checked=false;
  const prices=ai.pricing||{input:2,cached_input:.04,output:8};$('ai-input-price').value=prices.input;$('ai-cached-price').value=prices.cached_input;$('ai-output-price').value=prices.output;
  $('available-models').innerHTML=(ai.models||[ai.model].filter(Boolean)).map(id=>'<option value="'+esc(id)+'"></option>').join('');
 }
 $('settings-key').textContent=ai.configuration_error|| (ai.configured?'已保存，留空保留':'尚未配置');$('ai-api-key').placeholder=ai.configured?'留空则保留当前密钥':'填写你的 API Key';
 $('send-shortcut').value=uiPreferences.shortcut;$('reduce-motion').checked=Boolean(uiPreferences.reduceMotion);
 for(const id of ['ai-base-url','ai-api-key','ai-model-id','ai-input-price','ai-cached-price','ai-output-price','clear-api-key'])$(id).disabled=busy()||settingsSaving;
 $('save-ai-settings').disabled=busy()||settingsSaving;$('fetch-models').disabled=busy()||settingsSaving||modelsLoading;
 $('usage-spent').textContent='¥'+Number(budget.reserved_or_peak_cost||0).toFixed(2);$('usage-remaining').textContent='¥'+Number(budget.remaining||0).toFixed(2);
 if(!budgetDirty)$('ai-budget-limit').value=budget.limit??5;
 $('save-budget').disabled=busy()||settingsSaving;$('ai-budget-limit').disabled=busy()||settingsSaving;
 const rows=model.archived||[];$('archive-count').textContent=rows.length||'';
 $('archived-list').innerHTML=rows.length?rows.map(p=>'<div class="archived-row"><div><b>'+esc(p.title)+'</b><p class="muted">'+esc(p.archived_at.replace('T',' '))+'</p></div><div class="archive-actions"><button data-restore="'+p.id+'" '+(busy()?'disabled':'')+'>恢复</button><button class="danger-text" data-delete-project="'+p.id+'" '+(busy()?'disabled':'')+'>删除</button></div></div>').join(''):'<div class="settings-empty">没有已归档的聊天</div>';
}
function renderModelPicker(){
 const ai=model.ai||{},current=ai.model||'deepseek-flash';$('current-model').textContent=current;$('model-picker').disabled=busy();
 const ids=[...new Set([current,...(ai.models||[])])];
 $('model-menu').innerHTML='<div class="model-menu-label">模型</div>'+ids.map(id=>'<button data-choose-model="'+esc(id)+'"><span>'+esc(id)+'</span><span>'+(id===current?'✓':'')+'</span></button>').join('')+'<div class="menu-divider"></div><button data-open-settings="ai">模型与 API 设置 <span>↗</span></button>';
}
function aiForm(){return {base_url:$('ai-base-url').value.trim(),model:$('ai-model-id').value.trim(),api_key:$('ai-api-key').value.trim(),clear_key:$('clear-api-key').checked,pricing:{input:Number($('ai-input-price').value),cached_input:Number($('ai-cached-price').value),output:Number($('ai-output-price').value)}}}
$('settings-back').onclick=closeSettings;
document.querySelectorAll('[data-settings-tab]').forEach(b=>b.onclick=()=>{settingsTab=b.dataset.settingsTab;renderSettings(true);$('settings-title').scrollIntoView({block:'start'})});
$('settings-search').oninput=e=>{const q=e.target.value.trim().toLowerCase(),keywords={ai:'密钥 模型 api 连接 deepseek',usage:'费用 预算 上限 用量 消费',account:'小红书 登录 账号',general:'常规 快捷键 动画 动效',archive:'归档 删除 恢复 聊天',about:'版本 帮助 更新'};document.querySelectorAll('[data-settings-tab]').forEach(b=>b.hidden=!(keywords[b.dataset.settingsTab]||'').toLowerCase().includes(q))};
$('settings-login').onclick=openPlatformLogin;$('settings-refresh-account').onclick=()=>command('account');
for(const id of ['send-shortcut','reduce-motion'])$(id).onchange=()=>{uiPreferences.shortcut=$('send-shortcut').value;uiPreferences.reduceMotion=$('reduce-motion').checked;localStorage.setItem('xhm-ui-preferences',JSON.stringify(uiPreferences));document.documentElement.classList.toggle('reduce-motion',uiPreferences.reduceMotion)};
$('ai-settings-form').oninput=()=>{aiDirty=true;$('ai-save-status').textContent='有未保存的修改'};
$('ai-budget-limit').oninput=()=>{budgetDirty=true;$('budget-save-status').textContent='有未保存的修改'};
$('show-api-key').onclick=()=>{const input=$('ai-api-key');input.type=input.type==='password'?'text':'password';$('show-api-key').textContent=input.type==='password'?'显示':'隐藏'};
$('ai-settings-form').onsubmit=async e=>{
 e.preventDefault();if(settingsSaving||busy())return;settingsSaving=true;renderSettings();$('ai-save-status').textContent='正在保存…';
 try{const saved=await api('ai-settings',{action:'save',...aiForm(),models:[...$('available-models').options].map(x=>x.value)});model.ai={...model.ai,...saved};aiDirty=false;aiFormSignature='';$('ai-api-key').value='';$('ai-save-status').textContent='已保存';renderModelPicker();await refresh()}
 catch(error){$('ai-save-status').textContent=error.message}finally{settingsSaving=false;renderSettings(true)}
};
$('save-budget').onclick=async()=>{if(settingsSaving||busy())return;settingsSaving=true;renderSettings();$('budget-save-status').textContent='正在保存…';try{const result=await api('ai-settings',{action:'budget',limit:Number($('ai-budget-limit').value)});model.ai.budget=result.budget;budgetDirty=false;$('budget-save-status').textContent='已保存';await refresh()}catch(error){$('budget-save-status').textContent=error.message}finally{settingsSaving=false;renderSettings(true)}};
$('fetch-models').onclick=async()=>{
 if(modelsLoading||settingsSaving||busy())return;const version=++modelFetchVersion,form=aiForm();modelsLoading=true;renderSettings();$('models-status').textContent='正在读取模型列表…';
 try{const result=await api('ai-settings',{action:'models',...form});if(version!==modelFetchVersion||!settingsOpen||form.base_url!==$('ai-base-url').value.trim()||form.api_key!==$('ai-api-key').value.trim())return;
 $('available-models').innerHTML=(result.models||[]).map(id=>'<option value="'+esc(id)+'"></option>').join('');aiDirty=true;$('models-status').textContent=result.models?.length?'已读取 '+result.models.length+' 个模型，点击模型输入框选择':'服务未返回模型列表，可手动填写模型 ID';
 }catch(error){if(version===modelFetchVersion)$('models-status').textContent=error.message+'；也可手动填写模型 ID'}finally{modelsLoading=false;renderSettings()}
};
$('model-picker').onclick=()=>{const menu=$('model-menu');menu.hidden=!menu.hidden;$('model-picker').setAttribute('aria-expanded',String(!menu.hidden))};
$('model-menu').onclick=e=>{const button=e.target.closest('[data-choose-model]');if(!button)return;const id=button.dataset.chooseModel;$('model-menu').hidden=true;if(id===model.ai.model)return;openSettings('ai');$('ai-model-id').value=id;aiDirty=true;$('ai-save-status').textContent='核对模型单价后保存，即可切换'};
document.addEventListener('click',e=>{
 const settings=e.target.closest('[data-open-settings]');if(settings){openSettings(settings.dataset.openSettings);return}
 if(!e.target.closest('.side-bottom')){$('profile-menu').hidden=true;$('settings').setAttribute('aria-expanded','false')}
 if(!e.target.closest('.model-picker-wrap')){$('model-menu').hidden=true;$('model-picker').setAttribute('aria-expanded','false')}
});
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key===','){e.preventDefault();openSettings()}if(e.key==='Escape'){if(settingsOpen)closeSettings();$('profile-menu').hidden=true;$('model-menu').hidden=true}});
