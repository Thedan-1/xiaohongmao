// Presentation only. Official authentication, QR, inputs and verification stay intact.
(()=>{
  if(window.__xhmLoginFocus)return;
  window.__xhmLoginFocus=true;
  let prompted=false;
  function install(){
    if(!document.documentElement)return;
    if(!document.getElementById('xhm-login-focus')){
      const style=document.createElement('style');style.id='xhm-login-focus';
      style.textContent=`
        html,body{background:#faf9fc!important;overflow:hidden!important}
        body *{visibility:hidden!important}
        .login-modal,.login-modal *,.login-container,.login-container *,
        [role=dialog],[role=dialog] *,[class*=captcha],[class*=captcha] *,
        [id*=captcha],[id*=captcha] *,[class*=verify],[class*=verify] *,
        [id*=verify],[id*=verify] *{visibility:visible!important}
        .login-modal{background:#faf9fc!important;backdrop-filter:none!important}
        .login-modal .reds-mask{background:#faf9fc!important;opacity:1!important}
        .login-container{position:fixed!important;left:50%!important;top:50%!important;
          transform:translate(-50%,-50%)!important;max-width:calc(100vw - 36px)!important;
          max-height:calc(100vh - 28px)!important;overflow:auto!important;
          border-radius:22px!important;box-shadow:0 12px 60px #3020340c!important}
      `;
      (document.head||document.documentElement).append(style);
    }
    if(!prompted){
      const me=[...document.querySelectorAll('a[href*="/user/profile/"]')].some(a=>(a.textContent||'').trim()==='我');
      const button=document.querySelector('.login-btn');
      if(me)prompted=true;
      else if(button){prompted=true;button.click()}
    }
  }
  install();document.addEventListener('DOMContentLoaded',install,{once:true});
  new MutationObserver(install).observe(document,{childList:true,subtree:true});
})();
