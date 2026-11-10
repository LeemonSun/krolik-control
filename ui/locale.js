'use strict';
const supportedLocales=['ru','en','de'];
let currentLocale='ru';
let localePending=false;
const localeTextNodes=new WeakMap(),localeAttributes=new WeakMap();
function uiLocale(){return supportedLocales.includes(model.ui?.locale)?model.ui.locale:'ru';}
function translatedText(text){
 if(currentLocale==='ru')return text;
 const trimmed=text.trim(),dictionary=localeData[currentLocale]||{};
 const translated=dictionary[trimmed];
 if(typeof translated==='string')return text.replace(trimmed,translated);
 // Numbers change as jobs run. A template preserves the actual values.
 const numbers=[];
 const key=trimmed.replace(/\d+(?:[.,]\d+)?/g,n=>{numbers.push(n);return '{n}';});
 const template=dictionary[key];
 if(typeof template==='string'){
  let i=0;return text.replace(trimmed,template.replace(/\{n\}/g,()=>numbers[i++]||''));
 }
 return text;
}
function translateInterface(){
 localePending=false;currentLocale=uiLocale();
 localeObserver.disconnect();
 try{
  document.documentElement.lang=currentLocale;
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  while(walker.nextNode()){
   const node=walker.currentNode,parent=node.parentElement;
   if(!parent||parent.closest('script,style,textarea,[data-no-translate]'))continue;
   const prior=localeTextNodes.get(node),source=prior&&node.nodeValue===prior.output?prior.source:node.nodeValue;
   const output=translatedText(source);localeTextNodes.set(node,{source,output});
   if(node.nodeValue!==output)node.nodeValue=output;
  }
  for(const element of document.querySelectorAll('[title],[aria-label],[placeholder]')){
   const prior=localeAttributes.get(element)||{};
   for(const attr of ['title','aria-label','placeholder']){
    const value=element.getAttribute(attr);if(value===null)continue;
    const source=prior[attr]&&value===prior[attr].output?prior[attr].source:value;
    const output=translatedText(source);prior[attr]={source,output};
    if(value!==output)element.setAttribute(attr,output);
   }
   localeAttributes.set(element,prior);
  }
  document.title={ru:'Krolik Control — управление ПК',en:'Krolik Control — PC controls',de:'Krolik Control — PC-Verwaltung'}[currentLocale]+(model.state?.window_tag?' · '+model.state.window_tag:'');
 }finally{localeObserver.observe(document.body,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['title','aria-label','placeholder']});}
}
function scheduleTranslation(){if(!localePending){localePending=true;queueMicrotask(translateInterface);}}
const localeObserver=new MutationObserver(scheduleTranslation);
const untranslatedFindItems=findItems;
findItems=function(query,items=allItems()){
 if(uiLocale()==='ru')return untranslatedFindItems(query,items);
 const tokens=normalize(query).split(' ').filter(Boolean);
 if(!tokens.length)return items;
 return items.map(item=>{
  const title=normalize(translatedText(String(item.title||'')));
  const fields=[item.title,item.description,item.tags,groupNames[item.group]].map(value=>translatedText(String(value||'')));
  const text=normalize(fields.join(' ')),original=normalize([item.title,item.description,item.tags].join(' '));
  const matches=tokens.every(token=>text.includes(token)||original.includes(token));
  return [item,matches?10+tokens.filter(token=>title.includes(token)).length*5:0];
 }).filter(([,score])=>score>0).sort((a,b)=>b[1]-a[1]).map(([item])=>item);
};
const localePreferences=preferencesPage;
preferencesPage=function(){return `<div class="card locale-card"><div class="setting"><div class="label"><b>Язык приложения</b><small>Язык Windows и раскладки не меняются.</small></div><select class="locale-select" data-ui-locale aria-label="Язык приложения">${[['ru','Русский'],['en','English'],['de','Deutsch']].map(([id,label])=>`<option value="${id}" ${uiLocale()===id?'selected':''}>${label}</option>`).join('')}</select></div></div><div class="space-top">${localePreferences()}</div>`;};
document.addEventListener('change',e=>{
 if(!e.target.matches('[data-ui-locale]'))return;
 const locale=e.target.value;if(!supportedLocales.includes(locale))return;
 model.ui.locale=locale;render();queueSave();translateInterface();
});
// Keep the selector visible on every page, including the first launch.
const languageButton=document.createElement('select');languageButton.id='quick-locale';languageButton.setAttribute('data-ui-locale','');languageButton.setAttribute('aria-label','Язык приложения');languageButton.innerHTML='<option value="ru">RU</option><option value="en">EN</option><option value="de">DE</option>';
document.querySelector('.side-tools').append(languageButton);
const localeChrome=updateChrome;
updateChrome=function(){localeChrome();languageButton.value=uiLocale();scheduleTranslation();};
scheduleTranslation();
