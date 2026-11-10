'use strict';
// Profiles share the existing validated plan and execution engine.
model.audioDefaults=[];
const modesPlan=plan;
plan=function(){const p=modesPlan();if(model.audioDefaults.length){p.audio_defaults=structuredClone(model.audioDefaults);p.audio_routing_ack=true;}return p;};
const modesHydrate=hydratePlan;
hydratePlan=function(p){modesHydrate(p);model.audioDefaults=structuredClone(p.audio_defaults||[]);};
const modesCount=count;
count=function(){return modesCount()+model.audioDefaults.length;};
const modesReconcile=reconcile;
reconcile=function(){if(model.applied)for(const op of model.state.engine.items||[])if(op.status==='success'&&op.kind==='audio_default')model.audioDefaults=model.audioDefaults.filter(r=>JSON.stringify(r)!==JSON.stringify(op.value));modesReconcile();};
const modesCompatible=compatiblePlan;
compatiblePlan=function(p){const result=modesCompatible(p);result.plan.audio_defaults=[];for(const r of p.audio_defaults||[]){if(model.state.info.endpoints.some(e=>e.id===r.id&&e.flow===r.flow))result.plan.audio_defaults.push(r);else result.skipped++;}if(result.plan.audio_defaults.length)result.plan.audio_routing_ack=true;return result;};
const modesPerform=perform;
perform=async function(action){if(action==='diagnostics')return openSupportReport();if(action==='clear'&&!running())model.audioDefaults=[];return modesPerform(action);};
const modesComparison=comparisonRows;
comparisonRows=function(){const rows=modesComparison();for(const r of model.audioDefaults){const endpoints=model.state.info.endpoints,before=endpoints.find(e=>e.flow===r.flow&&(e.default_roles||[...(e.default?[1]:[])]).includes(r.role)),after=endpoints.find(e=>e.id===r.id);rows.push({title:(r.flow===0?'Выход звука':'Микрофон')+' · '+({0:'Системные звуки',1:'Музыка и приложения',2:'Связь'})[r.role],before:before?.name||'—',after:after?.name||'—',remove:'audio_default:'+r.flow+':'+r.role});}return rows;};
document.addEventListener('click',e=>{const remove=e.target.closest('[data-remove]');if(remove?.dataset.remove.startsWith('audio_default:')){const [_,flow,role]=remove.dataset.remove.split(':');model.audioDefaults=model.audioDefaults.filter(r=>r.flow!==Number(flow)||r.role!==Number(role));render();queueSave();}});
const modesChrome=updateChrome;
updateChrome=function(){modesChrome();const n=count(),mod=n%100,word=mod>=11&&mod<=14?'изменений':n%10===1?'изменение':n%10>=2&&n%10<=4?'изменения':'изменений';$('#count').textContent=n+' '+word;};
const modesLoad=loadProfile;
loadProfile=async function(p,name){if(p.audio_defaults?.length){await api('/api/profile/validate',p);const missing=p.audio_defaults.some(r=>!model.state.info.endpoints.some(e=>e.id===r.id&&e.flow===r.flow));if(missing)throw Error('Аудиоустройство профиля отключено');await previewInstant(p,'Проверьте настройки профиля перед применением.');return;}return modesLoad(p,name);};

function modeSummary(p){
 const result=[];if(p.displays?.length)result.push('Экран');if(p.audio?.length||p.audio_defaults?.length)result.push('Звук');if(Object.keys(p.settings||{}).some(k=>k.includes('power')||k.includes('sleep')||k.includes('screen_')))result.push('Питание');
 if(p.apps?.length||p.updates?.length||p.upgrades?.length)result.push('Программы');if(!result.length)result.push('Настройки');return result;
}
function modeMatches(p){
 const info=model.state.info;let n=0;
 if(p.apps?.length||p.updates?.length||p.upgrades?.length||p.startup?.length||p.layout?.length||p.languages?.length||p.restore_point||p.prepare_apps)return false;
 for(const [k,v] of Object.entries(p.settings||{})){n++;if(info.settings?.[k]!==v)return false;}
 for(const r of p.displays||[]){n++;const actual=info.displays.find(d=>d.id===r.id);if(!actual||actual.current!==r.mode||actual.orientation!==r.orientation)return false;}
 for(const r of p.audio||[]){n++;const a=info.endpoints.find(e=>e.id===r.id);if(!a||('volume'in r&&a.volume!==r.volume)||('mute'in r&&a.mute!==r.mute))return false;}
 for(const r of p.brightness||[]){n++;if(!info.brightness?.some(b=>b.id===r.id&&(b.value??b.current)===r.value))return false;}
 for(const r of p.audio_defaults||[]){n++;if(!info.endpoints.some(e=>e.id===r.id&&e.flow===r.flow&&(e.default_roles||[...(e.default?[1]:[])]).includes(r.role)))return false;}
 return n>0;
}
function modeEditable(p){
 if(p.apps?.length||p.updates?.length||p.upgrades?.length||p.startup?.length||p.layout?.length||p.languages?.length||p.brightness?.length||p.restore_point||p.prepare_apps||Object.keys(p.settings||{}).some(k=>k!=='power_plan'))return false;
 if((p.audio||[]).some(a=>!Number.isInteger(a.volume)||typeof a.mute!=='boolean'))return false;
 const groups=new Map();for(const r of p.audio_defaults||[]){const group=groups.get(r.flow)||[];group.push(r);groups.set(r.flow,group);}
 let roles=null;for(const group of groups.values()){if(new Set(group.map(r=>r.id)).size!==1)return false;const key=group.map(r=>r.role).sort().join(',');if(!['0,1','0,1,2'].includes(key)||roles&&roles!==key)return false;roles=key;}
 return true;
}
function modeCard(p,i){const active=modeMatches(p.plan),ico=/игр|game/i.test(p.name)?'gaming':/тв|tv|кино/i.test(p.name)?'monitor':'profiles';return `<article class="mode-card ${active?'mode-current':''}"><div class="mode-card-top"><span class="mode-icon">${icon(ico)}</span>${active?'<span class="mode-status">Сейчас</span>':''}</div><h3 data-no-translate>${esc(p.name)}</h3><div class="mode-tags">${modeSummary(p.plan).map(s=>`<span>${esc(s)}</span>`).join('')}</div><button class="${active?'secondary':'primary'}" data-mode-apply="${i}" ${active||running()?'disabled':''}>${active?'Уже включён':'Применить профиль'}</button><div class="mode-card-actions">${modeEditable(p.plan)?`<button class="text-btn" data-mode-edit="${i}">Редактировать</button>`:''}<button class="text-btn" data-mode-delete="${i}">Удалить</button></div></article>`;}
overviewHub=function(){
 const info=model.state.info;if(!info)return overview();const current=model.profiles.find(p=>modeMatches(p.plan));
 const output=info.endpoints.find(e=>e.flow===0&&e.default),mic=info.endpoints.find(e=>e.flow===1&&e.default),display=info.displays.find(d=>d.primary)||info.displays[0];
 return `<section class="mode-hero"><div class="mode-hero-copy"><span class="mode-kicker">ВАШ КОМПЬЮТЕР</span><h2>${current?esc(current.name):'Всё под рукой'}</h2><p>Сохраняйте настройки для работы и игр.</p><div class="toolbar"><button class="primary" data-mode-create>Создать профиль</button><button class="secondary" data-page="profiles">Мои профили</button></div></div><div class="mode-art" aria-hidden="true"><div class="mode-art-orbit"></div><img src="/krolik-mark.svg" alt=""></div></section>
 <section class="mode-section"><div class="section-intro"><h2>Быстрое переключение</h2><button class="text-btn" data-page="profiles">Все профили →</button></div>${model.profiles.length?`<div class="mode-grid">${model.profiles.slice(0,3).map(modeCard).join('')}</div>`:`<div class="mode-empty"><span class="mode-icon">${icon('profiles')}</span><div><h3>Сохраните привычные настройки</h3><p>Создайте профиль для работы, игры или телевизора.</p></div><button class="secondary" data-mode-create>Начать</button></div>`}</section>
 <section class="mode-section"><h2>Сейчас подключено</h2><div class="mode-device-grid">${[['monitor','Экран',display?.name,display?.current],['sound','Выход звука',output?.name,output?String(output.volume??'—')+'%':''],['sound','Микрофон',mic?.name,mic?String(mic.volume??'—')+'%':'']].map(([page,title,name,detail])=>`<button class="mode-device" data-page="${page}"><span class="mode-icon">${icon(page)}</span><span><small>${title}</small><b data-no-translate>${esc(name||'Не подключён')}</b><em data-no-translate>${esc(detail)}</em></span><span aria-hidden="true">↗</span></button>`).join('')}</div></section>
 <section class="mode-section"><h2>Полезное рядом</h2><div class="mode-shortcuts">${[['apps','Установить программы','Браузер, архиватор и другое'],['drivers','Драйверы','Официальные источники'],['care','Проверить ПК','Звук, интернет и восстановление'],['favorites','Избранное','Ваши частые действия']].map(([page,title,desc])=>`<button class="mode-shortcut" data-page="${page}">${icon(page)}<b>${title}</b><small>${desc}</small><span aria-hidden="true">→</span></button>`).join('')}</div></section>
 <div class="mode-computer"><span data-no-translate>${esc(info.computer||'PC')}</span><span data-no-translate>${esc(info.windows||info.os||'Windows')}</span><button class="text-btn" data-page="pc">О компьютере →</button><button class="text-btn" data-page="history">История изменений →</button></div>`;
};
const modesOldProfiles=profilesPage;
profilesPage=function(){return `<div class="section-intro"><div><h2>Ваши режимы работы</h2><p>Сохраните экран, громкость и питание в одном профиле.</p></div><button class="primary" data-mode-create>Создать профиль</button></div>${model.profiles.length?`<div class="mode-grid">${model.profiles.map(modeCard).join('')}</div>`:''}<details class="mode-advanced"><summary>Сохранённые наборы и перенос</summary>${modesOldProfiles()}</details>`;};

buildNav=function(){
 const groups=[['overview','Главная','overview'],['profiles','Профили','profiles'],['monitor','Экран и звук','monitor'],['apps','Программы','apps'],['tools','Инструменты','tools']];
 const secondary=[['sound','Звук'],['drivers','Драйверы'],['input','Мышь и клавиатура'],['power','Питание'],['startup','Автозагрузка'],['care','Проверка ПК'],['pc','Мой ПК'],['favorites','Избранное'],['history','История'],['catalog','Все настройки'],['storage','Место на дисках'],['firmware','BIOS и память'],['archives','ZIP-архивы'],['text-tools','Текст и пароли'],['peripheral-test','Проверка устройств'],['diagnostics','Диагностика сети']];
 const nav=$('#nav');if(nav.dataset.modesPage!==model.page||!nav.querySelector('.mode-nav')){nav.innerHTML=`<div class="mode-nav">${groups.map(([id,title,ico])=>`<button data-page="${id}">${icon(ico)}<span class="nav-label">${title}</span><span class="nav-count" hidden></span></button>`).join('')}</div><details class="mode-more" ${secondary.some(([id])=>id===model.page)?'open':''}><summary>Другие разделы</summary>${secondary.map(([id,title])=>`<button data-page="${id}">${icon(id)}<span class="nav-label">${title}</span><span class="nav-count" hidden></span></button>`).join('')}</details>`;nav.dataset.modesPage=model.page;}
 if(!nav.querySelector('[data-page="preferences"]'))nav.insertAdjacentHTML('beforeend',`<div class="nav-block">${navButton('preferences')}</div>`);
 nav.querySelectorAll('[data-page]').forEach(b=>{const id=b.dataset.page;b.classList.toggle('active',id===model.page||id==='monitor'&&['sound','power'].includes(model.page)||id==='tools'&&['archives','text-tools','storage'].includes(model.page));});
};
// All pages remain searchable and accessible in the existing catalog.
const modesMonitor=monitor;
monitor=function(){return `<div class="mode-switch"><button class="primary" data-page="monitor">Экран</button><button class="secondary" data-page="sound">Звук и микрофон</button><button class="secondary" data-page="power">Питание</button></div>`+modesMonitor();};
const modesSound=sound;
sound=function(){return `<div class="mode-switch"><button class="secondary" data-page="monitor">Экран</button><button class="primary" data-page="sound">Звук и микрофон</button><button class="secondary" data-page="power">Питание</button></div>`+modesSound();};
const modesDrivers=drivers;
drivers=function(){return (model.driverSourceMode==='vendor'?taskNote('drivers'):'')+modesDrivers();};
const modesTools=pageRenderers.tools;
pageRenderers.tools=function(){return `<div class="mode-shortcuts mode-tool-links">${[['archives','ZIP-архивы','Создать или распаковать ZIP'],['text-tools','Текст и пароли','JSON, Base64 и пароли'],['storage','Место на дисках','Найти крупные файлы'],['diagnostics','Диагностика сети','Проверить соединение']].map(([id,title,description])=>`<button class="mode-shortcut" data-page="${id}">${icon(id)}<b>${title}</b><small>${description}</small></button>`).join('')}</div>`+modesTools();};

function previewOperationHTML(op){
 const info=model.state.info;let title='',before='',after='';
 if(op.kind==='display'){const d=info.displays.find(d=>d.id===op.key);title=d?.name||'Экран';before=d?.current;after=op.value;}
 if(op.kind==='setting'){const s=model.state.settings.find(s=>s.key===op.key);title=s?.title||op.title;const choices=op.key==='power_plan'?Object.fromEntries(info.power_plans.map(p=>[p.id,p.name])):s?.choices;before=choices?.[info.settings[op.key]];after=choices?.[op.value];}
 if(op.kind==='audio_default'){title=op.value.flow===0?'Выход звука':'Микрофон';before=info.endpoints.find(e=>e.flow===op.value.flow&&(e.default_roles||[...(e.default?[1]:[])]).includes(op.value.role))?.name;after=info.endpoints.find(e=>e.id===op.key)?.name;title+=' · '+({0:'Системные звуки',1:'Музыка и приложения',2:'Связь'})[op.value.role];}
 if(op.kind==='audio'){const a=info.endpoints.find(e=>e.id===op.key);title=a?.name||'Громкость';before=a?.volume+'%';after=('volume'in op.value?op.value.volume:a?.volume)+'%';if(op.value.mute)after+=' 🔇';}
 if(before===undefined||!title)return esc(op.title);
 const raw=op.kind==='display'||op.kind==='audio'||op.kind==='audio_default'?'data-no-translate':'';
 return `<div class="mode-operation"><b ${op.kind==='display'||op.kind==='audio'?'data-no-translate':''}>${esc(title)}</b><div><span ${raw}>${esc(String(before))}</span><span class="mode-change-arrow" aria-hidden="true">→</span><strong ${raw}>${esc(String(after))}</strong></div></div>`;
}
const modesConditions=updateConditions;
updateConditions=function(p){modesConditions(p);const c=$('#apply-conditions');if(p.audio_defaults?.length){c.hidden=false;c.textContent+=(c.textContent?' ':'')+'Переключение пока проходит проверку на разных ПК. Некоторые приложения используют собственный выбор звука.';}if(model.state.info?.privileged_helper&&(p.updates?.length||p.restore_point||Object.keys(p.settings||{}).some(k=>model.state.settings.find(s=>s.key===k)?.admin))){c.hidden=false;c.textContent+=(c.textContent?' ':'')+'Windows попросит разрешение только для выбранного действия. Основное окно продолжит работать без прав администратора.';}};

document.body.insertAdjacentHTML('beforeend',`<dialog id="mode-builder"><form id="mode-form"><div class="mode-dialog-head"><span class="mode-kicker">НОВЫЙ ПРОФИЛЬ</span><h2>Новый профиль</h2><p>Выберите настройки для профиля.</p></div><label class="mode-field">Название<input id="mode-name" maxlength="60" required autocomplete="off" placeholder="Например, работа"></label><div class="mode-name-choices">${['Работа','Игра','ТВ'].map(s=>`<button type="button" class="secondary small" data-mode-name="${s}">${s}</button>`).join('')}</div><div id="mode-fields"></div><p id="mode-error" class="note error" role="alert" hidden></p><div class="dialog-actions"><button type="button" class="secondary" data-mode-cancel>Отмена</button><button type="submit" class="primary">Сохранить профиль</button></div></form></dialog>`);
function modeOptions(rows,id,value,name='name'){return rows.map(r=>`<option value="${esc(r[id])}" ${r[id]===value?'selected':''} data-no-translate>${esc(r[name])}</option>`).join('');}
async function openModeBuilder(edit=null){
 if(running()||modalOpen())return;
 const info=model.state.info;if(!info){toast('Сначала дождитесь списка устройств',true);return;}
 model.modeEdit=edit;model.modeSnapshot=structuredClone(info);$('#mode-name').value='';$('#mode-error').hidden=true;
 const outputs=info.endpoints.filter(e=>e.flow===0),mics=info.endpoints.filter(e=>e.flow===1),oldAudio=edit===null?[]:model.profiles[edit]?.plan.audio||[];const volumeRows=info.endpoints.filter(e=>e.controllable&&(!oldAudio.length||oldAudio.some(a=>a.id===e.id)));
 $('#mode-fields').innerHTML=`<fieldset class="mode-fieldset"><legend><label><input type="checkbox" id="mode-screen" ${info.displays.length?'checked':'disabled'}> Экран</label></legend>${info.displays.map((d,i)=>`<label class="mode-field"><span data-no-translate>${esc(d.name)}</span><select data-mode-display="${i}"><option value="">Не менять</option>${modeOptions(d.modes,'id',d.current,'id')}</select></label>`).join('')||'<p>Экран не подключён</p>'}</fieldset><fieldset class="mode-fieldset"><legend><label><input type="checkbox" id="mode-audio" ${info.endpoints.some(e=>e.controllable)?'checked':'disabled'}> Громкость</label></legend>${volumeRows.map(e=>`<div class="mode-volume"><span data-no-translate>${esc(e.name)}</span><input type="number" min="0" max="100" step="1" required data-mode-volume="${esc(e.id)}" aria-label="${esc(e.name)}" value="${Number.isInteger(e.volume)?e.volume:50}"><span>%</span><label class="mode-mute"><input type="checkbox" data-mode-muted="${esc(e.id)}" ${e.mute?'checked':''}>Без звука</label></div>`).join('')}</fieldset><fieldset class="mode-fieldset"><legend>Питание</legend><label class="mode-field">Схема питания<select id="mode-power"><option value="">Не менять</option>${modeOptions(info.power_plans||[],'id',info.settings?.power_plan)}</select></label></fieldset><details class="mode-fieldset"><summary>Выбор наушников и микрофона</summary><p>Переключение пока проходит проверку на разных ПК. Некоторые приложения используют собственный выбор звука.</p><label class="mode-field">Выход звука<select id="mode-output"><option value="">Не менять</option>${modeOptions(outputs,'id',outputs.find(e=>e.default)?.id)}</select></label><label class="mode-field">Микрофон<select id="mode-input"><option value="">Не менять</option>${modeOptions(mics,'id',mics.find(e=>e.default)?.id)}</select></label><label class="inline-toggle"><input id="mode-routing" type="checkbox">Включить пробное переключение звука</label><label class="inline-toggle"><input id="mode-communications" type="checkbox">Также использовать для звонков</label></details>`;
 if(edit!==null){
  const saved=model.profiles[edit];if(!saved||!modeEditable(saved.plan))return;await api('/api/preview',saved.plan);
  const p=saved.plan;$('#mode-name').value=saved.name;$('#mode-screen').checked=Boolean(p.displays?.length);$('#mode-audio').checked=Boolean(p.audio?.length);
  $('#mode-fields').querySelectorAll('[data-mode-display]').forEach(s=>{const d=info.displays[Number(s.dataset.modeDisplay)];s.value=p.displays?.find(r=>r.id===d.id)?.mode||'';});
  $('#mode-fields').querySelectorAll('[data-mode-volume]').forEach(s=>{const a=p.audio?.find(r=>r.id===s.dataset.modeVolume);if(a)s.value=a.volume;});$('#mode-fields').querySelectorAll('[data-mode-muted]').forEach(s=>{s.checked=Boolean(p.audio?.find(r=>r.id===s.dataset.modeMuted)?.mute);});
  $('#mode-power').value=p.settings?.power_plan||'';$('#mode-routing').checked=Boolean(p.audio_defaults?.length);$('#mode-communications').checked=p.audio_defaults?.some(r=>r.role===2)||false;
  for(const [id,flow] of [['mode-output',0],['mode-input',1]])$('#'+id).value=p.audio_defaults?.find(r=>r.flow===flow)?.id||'';
 }
 syncModeFields();$('#mode-builder button[type=submit]').textContent=edit===null?'Сохранить профиль':'Сохранить изменения';$('#mode-builder').showModal();$('#mode-name').focus();
}
function syncModeFields(){for(const [id,selector] of [['mode-screen','[data-mode-display]'],['mode-audio','[data-mode-volume],[data-mode-muted]']])$('#mode-fields').querySelectorAll(selector).forEach(e=>e.disabled=!$('#'+id).checked);$('#mode-communications').disabled=!$('#mode-routing').checked;}
document.addEventListener('change',e=>{if(['mode-screen','mode-audio','mode-routing'].includes(e.target.id))syncModeFields();});
$('#mode-form').onsubmit=async e=>{
 e.preventDefault();if(model.modeSaving)return;model.modeSaving=true;const submit=e.submitter||$('#mode-builder button[type=submit]');submit.disabled=true;$('[data-mode-cancel]').disabled=true;try{
  const name=$('#mode-name').value.trim();if(!name||name.length>60)throw Error('Введите название до 60 символов');if(model.profiles.length>=20&&model.modeEdit===null)throw Error('Можно сохранить до 20 профилей');if(model.profiles.some((p,i)=>i!==model.modeEdit&&p.name.toLocaleLowerCase()===name.toLocaleLowerCase()))throw Error('Профиль с таким названием уже есть');
  const info=model.modeSnapshot,p={version:1,settings:{},displays:[],audio:[]};
  if($('#mode-screen').checked)$('#mode-fields').querySelectorAll('[data-mode-display]').forEach(s=>{const d=info.displays[Number(s.dataset.modeDisplay)];if(s.value)p.displays.push({id:d.id,mode:s.value,orientation:d.orientation||0});});
  if($('#mode-audio').checked)$('#mode-fields').querySelectorAll('[data-mode-volume]').forEach(s=>{const raw=s.value.trim(),volume=Number(raw);if(!raw||!Number.isInteger(volume)||volume<0||volume>100)throw Error('Введите целое число от 0 до 100');const a=info.endpoints.find(r=>r.id===s.dataset.modeVolume);const mute=[...$('#mode-fields').querySelectorAll('[data-mode-muted]')].find(m=>m.dataset.modeMuted===a.id).checked;p.audio.push({id:a.id,volume,mute});});
  if($('#mode-power').value)p.settings.power_plan=$('#mode-power').value;
  if($('#mode-routing').checked){p.audio_defaults=[];p.audio_routing_ack=true;for(const [id,flow] of [['mode-output',0],['mode-input',1]])if($('#'+id).value)for(const role of ($('#mode-communications').checked?[0,1,2]:[0,1]))p.audio_defaults.push({id:$('#'+id).value,flow,role});}
  if(!p.displays.length&&!p.audio.length&&!Object.keys(p.settings).length&&!p.audio_defaults?.length)throw Error('Выберите хотя бы одну настройку');
  await api('/api/profile/validate',p);const record={name,plan:p},index=model.modeEdit,previous=index===null?null:model.profiles[index];if(index===null)model.profiles.push(record);else model.profiles[index]=record;try{await flushWorkspace();}catch(error){if(index===null)model.profiles.splice(model.profiles.indexOf(record),1);else model.profiles[index]=previous;throw error;}
  $('#mode-builder').close();render();toast('Профиль сохранён');
 }catch(error){$('#mode-error').textContent=error.message;$('#mode-error').hidden=false;}finally{submit.disabled=false;$('[data-mode-cancel]').disabled=false;model.modeSaving=false;}
};
document.addEventListener('click',async e=>{
 const t=e.target.closest('[data-mode-create],[data-mode-name],[data-mode-cancel],[data-mode-apply],[data-mode-edit],[data-mode-delete]');if(!t)return;
 try{if(t.hasAttribute('data-mode-delete')){const record=model.profiles[Number(t.dataset.modeDelete)];if(!record)return;if(!await ask('Удалить профиль?',record.name))return;const index=model.profiles.indexOf(record);if(index<0)throw Error('Профиль не найден');model.profiles.splice(index,1);try{await flushWorkspace();}catch(error){model.profiles.splice(index,0,record);throw error;}render();return;}if(t.hasAttribute('data-mode-edit'))return await openModeBuilder(Number(t.dataset.modeEdit));if(t.hasAttribute('data-mode-create'))return await openModeBuilder();if(t.dataset.modeName){$('#mode-name').value=translatedText(t.dataset.modeName);return;}if(t.hasAttribute('data-mode-cancel')){$('#mode-builder').close();return;}
  const p=model.profiles[Number(t.dataset.modeApply)];if(p)await previewInstant(p.plan,'Проверьте настройки профиля перед применением.');
 }catch(error){toast(error.message,true);}
});
const modesRender=render;let modesLastPage=null;
render=function(){modesRender();document.body.classList.toggle('mode-home',model.page==='overview');if(model.page!==modesLastPage){$('#content').classList.remove('mode-enter');void $('#content').offsetWidth;$('#content').classList.add('mode-enter');modesLastPage=model.page;}
 if(model.state?.data.desktop?.available&&!$('[data-mode-background]'))$('#close').insertAdjacentHTML('beforebegin','<button class="text-btn" data-mode-background>В трей</button>');
 const action=model.state?.data.desktop_action;if(action&&action.sequence!==model.desktopSequence&&!modalOpen()&&!running()){
  model.desktopSequence=action.sequence;const p=model.profiles.find(p=>p.name===action.profile);if(p)setTimeout(()=>previewInstant(p.plan,'Проверьте настройки профиля перед применением.').catch(e=>toast(e.message,true)),0);
 }
};
const modesPreferences=preferencesPage;
preferencesPage=function(){const desktop=model.state.data.desktop;return `<section class="card"><h2>Быстрый доступ</h2><label class="inline-toggle"><input type="checkbox" id="mode-quick-keys" ${model.ui.quick_keys?'checked':''} ${!desktop?.available?'disabled':''}>Горячие клавиши профилей</label><p>Ctrl+Alt+1…9 открывают первые девять профилей. Перед применением вы увидите список изменений.</p>${!desktop?.available?'<p class="muted">Доступно при обычном запуске в Windows.</p>':''}${desktop?.conflicts?.length?`<p class="note warning">${esc(desktop.conflicts.join(', '))}</p>`:''}</section>`+modesPreferences();};
document.addEventListener('change',e=>{if(e.target.id==='mode-quick-keys'){model.ui.quick_keys=e.target.checked;queueSave();}});
document.addEventListener('click',async e=>{if(e.target.closest('[data-mode-background]'))try{await api('/api/desktop/hide',{});}catch(error){toast(error.message,true);}});

document.body.insertAdjacentHTML('beforeend',`<dialog id="support-dialog"><h2>Отчёт для поддержки</h2><p>Имена, серийные номера, адреса, пути и личные профили исключены.</p><textarea id="support-report" class="text-tool-area" readonly data-no-translate aria-label="Содержимое отчёта"></textarea><div class="dialog-actions"><button class="secondary" data-support-close>Закрыть</button><button class="primary" data-support-save>Сохранить отчёт</button></div></dialog><dialog id="license-dialog"><h2>Сторонние компоненты</h2><select id="license-component" aria-label="Выбрать компонент"></select><pre id="license-text" data-no-translate></pre><div class="dialog-actions"><button class="secondary" data-license-close>Закрыть</button></div></dialog>`);
async function openSupportReport(){if(modalOpen())return;try{model.supportReport=await api('/api/support/report',{});$('#support-report').value=JSON.stringify(model.supportReport,null,2);$('#support-dialog').showModal();}catch(error){toast(error.message,true);}}
const modesPrivacyPreferences=preferencesPage;
preferencesPage=function(){return modesPrivacyPreferences()+`<section class="card space-top"><h2>Данные и приватность</h2><p>У Krolik Control нет аккаунта и собственной аналитики. Настройки и профили сохраняются на этом ПК.</p><p>Сетевые проверки и загрузки обращаются к выбранным сервисам и производителям.</p><p>Отчёт можно просмотреть перед сохранением.</p><button class="secondary" data-license-open>Лицензии компонентов</button></section>`;};
document.addEventListener('click',async e=>{try{
 if(e.target.closest('[data-support-close]'))$('#support-dialog').close();
 if(e.target.closest('[data-support-save]')&&model.supportReport)downloadJSON('KrolikControl-support.json',model.supportReport);
 if(e.target.closest('[data-license-close]'))$('#license-dialog').close();
 if(e.target.closest('[data-license-open]')){const response=await fetch('/third-party-notices.json');if(!response.ok)throw Error('Не удалось прочитать лицензии');model.notices=await response.json();$('#license-component').innerHTML=Object.keys(model.notices).map(name=>`<option>${esc(name)}</option>`).join('');$('#license-text').textContent=model.notices[$('#license-component').value];$('#license-dialog').showModal();}
}catch(error){toast(error.message,true);}});
$('#license-component').onchange=()=>$('#license-text').textContent=model.notices[$('#license-component').value];

$('#mode-builder').addEventListener('cancel',e=>{if(model.modeSaving)e.preventDefault();});
