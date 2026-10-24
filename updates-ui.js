// Update prompts never stop a task or install without the user's choice.
let updateState=null,updateTimer=null,updateApplying=false,updateNotified='';
const updateBanner=document.createElement('div');updateBanner.className='update-banner';updateBanner.hidden=true;document.body.append(updateBanner);
function renderUpdateStatus(value){
 updateState=value;const phase=value.phase,release=value.release;
 $('update-heading').textContent=phase==='available'||phase==='ready'?'发现新版 '+release?.version:'软件更新';
 $('update-message').textContent=value.message||'尚未检查更新';
 $('check-updates').disabled=['checking','downloading'].includes(phase)||updateApplying;
 $('update-detail').hidden=!release;$('download-update').hidden=!release||!['available','error'].includes(phase);
 $('apply-update').hidden=phase!=='ready';$('apply-update').disabled=busy()||updateApplying;
 $('apply-update').textContent=value.distribution==='preview'?'重启并更新预览版':'重启并安装更新';
 $('cancel-update').hidden=phase!=='downloading';
 $('update-version').textContent=release?'当前 '+value.current_version+' → 新版 '+release.version:'';
 $('update-notes').textContent=release?.notes||'';
 $('update-progress').textContent=phase==='downloading'?'已下载 '+Math.floor(Number(value.downloaded||0)/Math.max(1,value.total)*100)+'%':phase==='ready'&&busy()?'任务进行中，完成或暂停后可重启更新':'';
 $('update-release-link').href=release?.release_url||'https://github.com/Thedan-1/xiaohongmao/releases';
 if(release&&['available','ready'].includes(phase)&&updateNotified!==release.version){
  let dismissed='';try{dismissed=sessionStorage.getItem('xhm-update-dismissed')}catch{}
  if(dismissed!==release.version){updateBanner.hidden=false;updateBanner.innerHTML='<span>小红帽 '+esc(release.version)+' 已发布</span><button data-view-update>查看更新</button><button data-dismiss-update aria-label="稍后">×</button>';updateNotified=release.version}
 }
 if(['checking','downloading'].includes(phase))scheduleUpdatePoll();
}
function scheduleUpdatePoll(){clearTimeout(updateTimer);updateTimer=setTimeout(refreshUpdateStatus,1000)}
async function refreshUpdateStatus(){try{renderUpdateStatus(await api('update'))}catch(e){if(settingsOpen&&settingsTab==='about')$('update-message').textContent='更新检查暂不可用'} }
async function updateAction(action,extra={}){try{renderUpdateStatus(await api('update',{action,...extra}))}catch(e){$('update-message').textContent=e.message;toast(e.message)}}
$('check-updates').onclick=()=>updateAction('check');$('download-update').onclick=()=>updateAction('download');$('cancel-update').onclick=()=>updateAction('cancel');
$('apply-update').onclick=()=>{
 if(busy()){toast('任务仍在运行，请完成或暂停后再更新');return}
 if(!window.XIAOHONGMAO_NATIVE||!window.chrome?.webview){toast('请在小红帽客户端内重启更新');return}
 updateApplying=true;$('apply-update').disabled=true;$('update-message').textContent='正在准备退出，完成后开始更新…';
 chrome.webview.postMessage({type:'install-update'});
};
window.updateApplyFailed=message=>{updateApplying=false;$('update-message').textContent=message;toast(message);if(updateState)renderUpdateStatus({...updateState,message})};
updateBanner.onclick=e=>{if(e.target.closest('[data-view-update]')){openSettings('about');refreshUpdateStatus()}if(e.target.closest('[data-dismiss-update]')){updateBanner.hidden=true;try{sessionStorage.setItem('xhm-update-dismissed',updateState.release.version)}catch{}}};
document.querySelector('[data-settings-tab="about"]').addEventListener('click',refreshUpdateStatus);
document.querySelectorAll('[data-open-settings="about"]').forEach(button=>button.addEventListener('click',refreshUpdateStatus));
if(window.XIAOHONGMAO_NATIVE&&!window.XIAOHONGMAO_SMOKE){
 setTimeout(()=>updateAction('check',{automatic:true}),3500);
 setInterval(()=>updateAction('check',{automatic:true}),21660000);
}
