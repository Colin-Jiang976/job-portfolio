// 求职首页与独立架构页共用三语、导航和已有材料配置。
(() => {
 const translations=window.PORTFOLIO_TEXT;
 const architecture=document.querySelector('#architecture');
 const architectureButtons=document.querySelectorAll('[data-architecture-view]');
 const explanations={all:'architectureExplainAll',page:'architectureExplainPage',catalog:'architectureExplainCatalog',download:'architectureExplainDownload'};
 let architectureView='all',language='ja';
 function renderDocuments(text){
  const list=document.querySelector('#document-downloads');if(!list)return;list.replaceChildren();
  for(const slot of ['resume','career']){
   const file=window.PORTFOLIO_DOCUMENTS?.[slot];
   if(typeof file!=='string'||!/^documents\/[a-zA-Z0-9][a-zA-Z0-9._/-]*\.(pdf|docx)$/.test(file)||file.split('/').some(part=>!part||part==='.'||part==='..'))continue;
   const link=document.createElement('a');link.className='button button-outline';link.href=file;link.download=file.split('/').at(-1);link.textContent=text[slot==='resume'?'downloadResume':'downloadCareer'];list.append(link);
  }
  document.querySelector('#document-status').textContent=text[list.childElementCount?'documentsReady':'documentsPending'];
 }
 function renderContact(text){
  const list=document.querySelector('#contact-links');if(!list)return;list.replaceChildren();const contact=window.PORTFOLIO_CONTACT||{};
  const add=(label,value,href)=>{const row=document.createElement('p'),link=document.createElement('a');link.href=href;link.textContent=label+' / '+value;row.append(link);list.append(row);};
  if(typeof contact.email==='string'&&/^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$/.test(contact.email))add(text.contactEmailLabel,contact.email,'mailto:'+contact.email);
  if(typeof contact.phone==='string'&&/^\+[0-9]{8,15}$/.test(contact.phone))add(text.contactPhoneLabel,typeof contact.phoneLabel==='string'?contact.phoneLabel:contact.phone,'tel:'+contact.phone);
 }
 function renderArchitecture(){
  if(!architecture)return;architecture.dataset.view=architectureView;
  architectureButtons.forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.architectureView===architectureView)));
  const explanation=document.querySelector('#architecture-explanation');explanation.dataset.i18n=explanations[architectureView];explanation.textContent=translations[language][explanations[architectureView]];
 }
 architectureButtons.forEach(button=>button.addEventListener('click',()=>{if(!Object.hasOwn(explanations,button.dataset.architectureView))return;architectureView=button.dataset.architectureView;renderArchitecture();}));
 function setLanguage(next){
  if(!Object.hasOwn(translations,next))return;language=next;const text=translations[language];
  document.documentElement.lang=language;document.title=document.body.dataset.page==='architecture'?text.architecturePageTitle:text.pageTitle;
  const description=document.querySelector('meta[name="description"]');if(description)description.content=document.body.dataset.page==='architecture'?text.architectureOverview:text.pageDescription;
  document.querySelectorAll('[data-i18n]').forEach(node=>{if(Object.hasOwn(text,node.dataset.i18n))node.textContent=text[node.dataset.i18n];});
  document.querySelectorAll('[data-i18n-aria-label]').forEach(node=>{if(Object.hasOwn(text,node.dataset.i18nAriaLabel))node.setAttribute('aria-label',text[node.dataset.i18nAriaLabel]);});
  document.querySelectorAll('[data-lang]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.lang===language)));
  document.querySelectorAll('[data-page-link]').forEach(link=>{const target=new URL(link.dataset.pageLink,location.href);target.searchParams.set('lang',language);link.href=target.href;});
  renderDocuments(text);renderContact(text);renderArchitecture();
  try{localStorage.setItem('cloud-nature-language',language);}catch{}
  try{const target=new URL(location.href);target.searchParams.set('lang',language);history.replaceState(null,'',target);}catch{}
 }
 document.querySelectorAll('[data-lang]').forEach(button=>button.addEventListener('click',()=>setLanguage(button.dataset.lang)));
 const menuButton=document.querySelector('.menu-toggle'),mobileNav=document.querySelector('#mobile-nav');
 if(menuButton&&mobileNav){
  const close=()=>{mobileNav.hidden=true;menuButton.setAttribute('aria-expanded','false');};
  menuButton.addEventListener('click',()=>{const open=mobileNav.hidden;mobileNav.hidden=!open;menuButton.setAttribute('aria-expanded',String(open));});
  mobileNav.querySelectorAll('a').forEach(link=>link.addEventListener('click',close));
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!mobileNav.hidden){close();menuButton.focus();}});
  window.matchMedia('(min-width: 841px)').addEventListener('change',event=>{if(event.matches)close();});
 }
 // 保留旧首页架构书签；独立页面沿用原查询参数。
 if(!architecture&&location.hash==='#architecture'){const target=new URL('architecture.html',location.href);target.search=location.search;location.replace(target.href);return;}
 try{language=localStorage.getItem('cloud-nature-language')||'ja';}catch{}
 const requested=new URLSearchParams(location.search).get('lang');
 setLanguage(Object.hasOwn(translations,requested)?requested:Object.hasOwn(translations,language)?language:'ja');
})();
