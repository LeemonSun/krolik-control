'use strict';
// Keep invalid edits out of the executable/saved plan without destroying typed text.
model.invalidNumbers={};
model.numberEdits={};
function numericValue(key,fallback){return Object.hasOwn(model.numberEdits,key)?model.numberEdits[key]:Object.hasOwn(model.invalidNumbers,key)?model.invalidNumbers[key]:fallback}
function readNumberField(input,key,choices=null,emptyAllowed=false){
 const raw=input.value,n=Number(raw),valid=raw.trim()!==''&&Number.isInteger(n)&&(choices?choices.includes(String(n)):n>=0&&n<=100);
 if(valid||emptyAllowed&&raw===''){delete model.invalidNumbers[key];input.removeAttribute('aria-invalid');input.setCustomValidity('');return raw===''?null:n}
 model.invalidNumbers[key]=raw;input.setAttribute('aria-invalid','true');input.setCustomValidity(choices?'Выберите одно из доступных значений':'Введите целое число от 0 до 100');return null;
}
function invalidNumberKeys(){
 const info=model.state?.info;
 return Object.keys(model.invalidNumbers).filter(key=>{
  const colon=key.indexOf(':'),kind=key.slice(0,colon),id=key.slice(colon+1);
  const exists=kind==='setting'?model.state.settings.some(s=>s.key===id&&s.enabled):kind==='audio'?info?.endpoints.some(a=>a.id===id&&a.controllable):info?.brightness.some(b=>b.id===id);
  if(!exists)delete model.invalidNumbers[key];return exists;
 });
}
function updateNumberSafety(){
 const keys=invalidNumberKeys(),active=keys.length>0;
 let note=$('#number-warning');if(active&&!note){note=document.createElement('div');note.id='number-warning';note.className='note warning space-top';note.setAttribute('role','status');note.innerHTML='Проверьте выделенные поля. Пустое поле не означает ноль. <button class="text-btn" data-number-reset>Сбросить неверный ввод</button>';$('#banner').append(note)}else if(!active&&note)note.remove();
 for(const input of document.querySelectorAll('[data-number-setting],[data-brightness-number],[data-audio-volume]')){
  const key=input.dataset.numberSetting?'setting:'+input.dataset.numberSetting:input.dataset.brightnessNumber?'brightness:'+input.dataset.brightnessNumber:'audio:'+input.dataset.audioVolume;
  if(keys.includes(key))input.setAttribute('aria-invalid','true');else input.removeAttribute('aria-invalid');
 }
 if(active)for(const button of document.querySelectorAll('#next,[data-apply-section],[data-apply-display],[data-retry-failed]'))button.disabled=true;
}
const safetyChrome=updateChrome;updateChrome=function(){safetyChrome();updateNumberSafety()};
const safetyRender=render;render=function(){safetyRender();updateNumberSafety()};
const safetyApi=api;api=async function(path,body){if(['/api/preview','/api/apply'].includes(path)&&invalidNumberKeys().length)throw new Error('Исправьте выделенные поля или сбросьте неверный ввод.');return safetyApi(path,body)};
const safetyHydrate=hydratePlan;hydratePlan=function(p){model.invalidNumbers={};model.numberEdits={};return safetyHydrate(p)};
const safetyPerform=perform;perform=async function(action){if(action==='clear'){model.invalidNumbers={};model.numberEdits={}}return safetyPerform(action)};
document.addEventListener('input',e=>{const t=e.target,key=t.dataset.numberSetting?'setting:'+t.dataset.numberSetting:t.dataset.brightnessNumber?'brightness:'+t.dataset.brightnessNumber:null;if(!key)return;const choices=t.dataset.numberSetting?Object.keys(model.state.settings.find(s=>s.key===t.dataset.numberSetting).choices):null;readNumberField(t,key,choices);model.numberEdits[key]=t.value;updateChrome()});
document.addEventListener('click',e=>{if(e.target.closest('[data-number-reset]')){model.invalidNumbers={};model.numberEdits={};render()}});
