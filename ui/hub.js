'use strict';
// Product shell around the Windows controls. The core operations remain in app.js.
Object.assign(icons,{
 catalog:'<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M8 3v18m0-12h13m-13 6h13"/>',
 favorites:'<path d="m12 2 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1z"/>',
 profiles:'<path d="M4 5h16v16H4zM8 2v6m8-6v6M8 12h8m-8 4h5"/>',
 history:'<path d="M3 11a9 9 0 1 1 3 8M3 4v7h7m2-4v6l4 2"/>',
});
pages.splice(1,0,['catalog','Каталог настроек','Каталог настроек','Настройки и устройства, которыми можно управлять внутри Krolik Control.'],['favorites','Избранное','Избранное','Сохраните часто нужные параметры звёздочкой.']);
pages.splice(pages.length-1,0,['profiles','Профили','Профили настроек','Ваши настройки для работы и игр.'],['history','История','История изменений','Результаты применений, прерванные операции и сохранённая резервная копия.']);
const pageTitles={overview:'Обзор',drivers:'Драйверы устройств',monitor:'Мониторы и изображение',input:'Мышь и клавиатура',language:'Язык и раскладки',power:'Питание и сон',network:'Сеть и подключения',sound:'Звук и микрофон',appearance:'Windows и Проводник',gaming:'Игровые параметры',privacy:'Конфиденциальность',apps:'Установка программ',system:'Система и обслуживание',summary:'Проверьте изменения'};
for(const p of pages)if(pageTitles[p[0]])p[2]=pageTitles[p[0]];
const groupNames={monitor:'Мониторы',drivers:'Драйверы',hardware:'Оборудование',input:'Мышь и клавиатура',language:'Язык и время',power:'Питание',network:'Сеть',sound:'Звук',appearance:'Оформление',explorer:'Проводник',gaming:'Игры',privacy:'Конфиденциальность',apps:'Программы',system:'Система',accounts:'Учётные записи',accessibility:'Специальные возможности'};
const groupPage=g=>['hardware','accounts','accessibility'].includes(g)?'catalog':g==='explorer'?'appearance':g;
Object.assign(model,{favorites:new Set(),recent:[],profiles:[],uiTheme:'light',uiMode:'basic',hydrated:false,workspaceRevision:0,savedSignature:'',catalogQuery:'',catalogGroup:'all',catalogKind:'all',saveTimer:null,saveChain:Promise.resolve(),searchIndex:0});
const coreRender=render,coreChrome=updateChrome,corePerform=perform,coreApi=api,coreNavigate=navigate;
let confirmResolve=null;
function ask(title,text,details=''){
 if(confirmResolve)return Promise.resolve(false);
 $('#confirm-title').textContent=title;$('#confirm-text').textContent=text;$('#confirm-details').innerHTML=details;
 $('#confirm-dialog').showModal();return new Promise(resolve=>confirmResolve=resolve);
}
function finishAsk(value){$('#confirm-dialog').close();if(confirmResolve){confirmResolve(value);confirmResolve=null}}
$('#confirm-no').onclick=()=>finishAsk(false);$('#confirm-yes').onclick=()=>finishAsk(true);$('#confirm-dialog').addEventListener('cancel',e=>{e.preventDefault();finishAsk(false)});
function workspaceValue(){return {draft:plan(),favorites:[...model.favorites],recent:model.recent,profiles:model.profiles,theme:model.uiTheme,mode:model.uiMode}}
function hydratePlan(p){p=JSON.parse(JSON.stringify(p));model.settings={...(p.settings||{})};model.displays=Object.fromEntries((p.displays||[]).map(v=>[v.id,v]));model.brightness=Object.fromEntries((p.brightness||[]).map(v=>[v.id,v]));model.audio=Object.fromEntries((p.audio||[]).map(v=>[v.id,v]));model.apps=new Set(p.apps||[]);model.updates=new Set(p.updates||[]);model.adapter=p.adapter??null;model.restore=Boolean(p.restore_point)}
function hydrateWorkspace(){
 if(!model.state)return;
 const w=model.state.workspace;
 if(!model.hydrated){
  if(w){hydratePlan(w.draft);model.favorites=new Set(w.favorites);model.recent=w.recent||[];model.profiles=w.profiles;model.uiTheme=w.theme;model.uiMode=w.mode;model.workspaceRevision=model.state.workspace_revision||0}
  model.hydrated=true;model.savedSignature=JSON.stringify(workspaceValue());
  if(count())setTimeout(()=>toast('Восстановлен незавершённый выбор. Перед применением проверьте устройства и значения.'),150);
 }
 if(model.state.workspace_revision>model.workspaceRevision){model.workspaceRevision=model.state.workspace_revision;model.savedSignature=JSON.stringify(model.state.workspace)}
 document.documentElement.dataset.theme=model.uiTheme;$('#ui-mode').value=model.uiMode;
}
function queueSave(){
 if(!model.hydrated||running())return;
 if(JSON.stringify(workspaceValue())===model.savedSignature)return;
 clearTimeout(model.saveTimer);$('#save-status').textContent='Сохраняем…';
 model.saveTimer=setTimeout(()=>flushWorkspace().catch(e=>toast('Выбор не сохранён: '+e.message,true)),450);
}
function flushWorkspace(){
 clearTimeout(model.saveTimer);
 model.saveChain=model.saveChain.catch(()=>{}).then(async()=>{
  if(!model.hydrated||running())return;
  const value=workspaceValue(),signature=JSON.stringify(value);
  if(signature===model.savedSignature)return;
  try{const saved=await coreApi('/api/workspace',{workspace:value,revision:model.workspaceRevision});model.workspaceRevision=saved.revision;model.savedSignature=signature;$('#save-status').textContent='Сохранено'}
  catch(e){$('#save-status').textContent='Не сохранено';throw e}
 });return model.saveChain;
}
api=async function(path,body){if(['/api/apply','/api/close','/api/undo','/api/elevate'].includes(path))await flushWorkspace();return coreApi(path,body)};
function navButton(id){const p=pages.find(p=>p[0]===id);return `<button data-page="${id}" title="${esc(p[1])}">${icon(id)}<span class="nav-label">${esc(p[1])}</span><span class="nav-count" aria-hidden="true" hidden></span></button>`}
function buildNav(){
 const nav=$('#nav');if(nav.dataset.hub)return;
 nav.dataset.hub='on';nav.innerHTML=`<div class="nav-block">${['overview','catalog','favorites'].map(navButton).join('')}</div><div class="nav-section-label">КОМПЬЮТЕР</div><div class="nav-block">${['drivers','monitor','sound','apps'].map(navButton).join('')}</div><details class="nav-details" id="windows-nav"><summary>${icon('system')}<span>Настройки Windows</span><b>⌄</b></summary><div>${['input','language','power','network','appearance','gaming','privacy','system'].map(navButton).join('')}</div></details><div class="nav-section-label">ИНСТРУМЕНТЫ</div><div class="nav-block">${['profiles','history','summary'].map(navButton).join('')}</div>`;
}
updateChrome=function(){
 hydrateWorkspace();buildNav();coreChrome();
 const idx=pages.findIndex(p=>p[0]===model.page);
 $('#eyebrow').textContent=['overview','catalog','favorites'].includes(model.page)?'КОМПЬЮТЕР':model.page==='summary'?'ОЧЕРЕДЬ ИЗМЕНЕНИЙ':'НАСТРОЙКИ КОМПЬЮТЕРА';
 $('#step-mark').innerHTML=`<span class="saved-indicator">${model.state?.info?'● Компьютер определён':'◌ Определяем оборудование'}</span>`;
 $('#close').disabled=running();
 $('#back').textContent='Сбросить выбор';$('#back').disabled=!count()||running();
 $('#next').disabled=!model.state?.info||running()||blockingScan()||!count();$('#next').innerHTML=model.page==='summary'?'Применить изменения':`Проверить выбор <span>${count()}</span>`;
 $('#foot-note').textContent=running()?'Изменения применяются по очереди':count()?'Выбор сохраняется автоматически':'Изменения не выбраны';

 $('#banner').querySelectorAll('.note').forEach(note=>{if(note.textContent.includes('Start-Admin.cmd'))note.innerHTML='Для драйверов, обновлений и DNS нужны права администратора. <button class="secondary small" data-action="elevate">Перезапустить с правами ↗</button>'});
 if(model.state.info?.pending_groups?.includes(model.page)){const t=model.state.tasks.inventory_details;$('#banner').insertAdjacentHTML('beforeend',`<div class="note ${t?.status==='error'?'error':''}">${t?.status==='error'?'Не удалось определить параметры: '+esc(t.error)+'. Нажмите ↻, чтобы повторить.':'Определяем доступные значения этого раздела…'}</div>`)}
 if(model.state.workspace_warning&&!$('#banner').querySelector('.workspace-warning'))$('#banner').insertAdjacentHTML('beforeend',`<div class="note warning workspace-warning">${esc(model.state.workspace_warning)}</div>`);
 queueSave();
};
navigate=function(page){if(!pages.some(p=>p[0]===page))return;$('#search-results').hidden=true;$('#global-search').setAttribute('aria-expanded','false');coreNavigate(page);if(page==='drivers'&&!model.state.tasks.drivers)perform('drivers');if(['monitor','sound'].includes(page)&&Date.now()-(model.lastDeviceScan||0)>5000){model.lastDeviceScan=Date.now();api('/api/devices/scan',{}).then(poll).catch(e=>toast(e.message,true))}};
function star(id){const active=model.favorites.has(id);return `<button class="star ${active?'selected':''}" data-star="${esc(id)}" aria-label="${active?'Убрать из избранного':'Добавить в избранное'}: ${esc(itemById(id)?.title||id)}" aria-pressed="${active}" title="Избранное">${icon('favorites')}</button>`}
function allItems(){return (model.state?.catalog||[]).filter(a=>a.kind!=='windows')}
function itemById(id){return allItems().find(a=>a.id===id)}
function normalize(s){return String(s||'').toLowerCase().replace(/ё/g,'е').replace(/[^\p{L}\p{N}]+/gu,' ').trim()}
function wrongLayout(s){const latin="qwertyuiop[]asdfghjkl;'zxcvbnm,.",ru='йцукенгшщзхъфывапролджэячсмитьбю';return s.toLowerCase().split('').map(c=>latin.includes(c)?ru[latin.indexOf(c)]:c).join('')}
function findItems(query,items=allItems()){
 const q=normalize(query),alternate=normalize(wrongLayout(query)),tokens=q.split(' ').filter(Boolean),alt=alternate.split(' ').filter(Boolean);
 if(!q)return items;
 return items.map(a=>{const title=normalize(a.title),text=normalize([a.title,a.description,a.tags,groupNames[a.group]].join(' '));let score=0;if(tokens.every(t=>text.includes(t)))score=10+tokens.filter(t=>title.includes(t)).length*5;if(alt.length&&alt.every(t=>text.includes(t)))score=Math.max(score,8);if(title===q)score+=30;if(title.startsWith(q))score+=12;return [a,score]}).filter(([,s])=>s>0).sort((a,b)=>b[1]-a[1]).map(([a])=>a);
}
function itemKind(a){return a.kind==='setting'?'В Krolik Control':a.kind==='app'?'Установка':'Устройства'}
function itemCard(a){return `<article class="directory-card ${a.available?'':'unavailable'}"><div class="directory-icon">${icon(groupPage(a.group))}</div><div class="directory-body"><div class="directory-top"><span class="micro-label">${esc(groupNames[a.group]||a.group)}</span>${star(a.id)}</div><h3>${esc(a.title)}</h3><p>${esc(a.description)}</p><div class="directory-bottom"><span class="kind-tag ${a.kind}">${itemKind(a)}</span><button class="directory-open" data-item="${esc(a.id)}" ${!a.available?'disabled':''}>${a.available?(a.kind==='windows'?'Открыть':'Настроить'):'Недоступно'} <span>→</span></button></div>${!a.available?`<small class="availability">${esc(a.reason||'Недоступно на этом ПК')}</small>`:''}</div></article>`}
function catalog(favorites=false){
 let items=allItems().filter(a=>!favorites||model.favorites.has(a.id));
 if(model.uiMode==='basic'&&!favorites)items=items.filter(a=>!a.advanced);
 if(model.catalogGroup!=='all')items=items.filter(a=>a.group===model.catalogGroup);
 if(model.catalogKind!=='all')items=items.filter(a=>a.kind===model.catalogKind);
 items=findItems(model.catalogQuery,items);
 const groups=[...new Set(allItems().filter(a=>!favorites||model.favorites.has(a.id)).map(a=>a.group))];
 return `<div class="catalog-controls"><div class="catalog-search"><span>⌕</span><input id="catalog-query" type="search" value="${esc(model.catalogQuery)}" placeholder="Герцовка, мышь, раскладка, браузер…" aria-label="Поиск в каталоге"></div><select id="catalog-kind" aria-label="Тип настройки"><option value="all">Все действия</option><option value="setting" ${model.catalogKind==='setting'?'selected':''}>Внутри Krolik Control</option><option value="device" ${model.catalogKind==='device'?'selected':''}>Устройства</option><option value="app" ${model.catalogKind==='app'?'selected':''}>Установка программ</option></select></div><div class="filter-chips"><button data-filter="all" class="${model.catalogGroup==='all'?'active':''}">Всё</button>${groups.map(g=>`<button data-filter="${g}" class="${model.catalogGroup===g?'active':''}">${esc(groupNames[g]||g)}</button>`).join('')}</div><div class="catalog-meta"><span id="catalog-found">Найдено: ${items.length}</span><span>Звёздочка сохранит действие в избранном</span></div><div id="catalog-items" class="directory-grid">${items.map(itemCard).join('')||empty(favorites?'В избранном пока пусто':'Ничего не найдено',favorites?'Добавьте нужные действия звёздочкой из каталога или категорий.':'Попробуйте другое слово или включите «Все настройки».')}</div>`;
}
function refreshCatalogResults(){let items=allItems().filter(a=>model.page!=='favorites'||model.favorites.has(a.id));if(model.uiMode==='basic'&&model.page!=='favorites')items=items.filter(a=>!a.advanced);if(model.catalogGroup!=='all')items=items.filter(a=>a.group===model.catalogGroup);if(model.catalogKind!=='all')items=items.filter(a=>a.kind===model.catalogKind);items=findItems(model.catalogQuery,items);$('#catalog-found').textContent='Найдено: '+items.length;$('#catalog-items').innerHTML=items.map(itemCard).join('')||empty('Ничего не найдено','Измените запрос или фильтры.')}
function overviewHub(){const info=model.state.info;if(!info)return overview();
 const cards=[['monitor','Мониторы','Разрешение и частота'],['drivers','Драйверы','Найти и обновить'],['apps','Программы','Браузеры, игры и инструменты'],['sound','Звук','Динамики и микрофон']];
 const categories=[['input','Мышь и клавиатура','Скорость, кнопки, прокрутка'],['language','Раскладки','Языки ввода и переключение'],['power','Питание','Схема, экран и сон'],['appearance','Windows и файлы','Тема, панель задач, Проводник'],['network','Сеть','Адаптеры и DNS'],['gaming','Игры','Игровой режим и запись'],['privacy','Конфиденциальность','Предложения и персонализация'],['system','Обновления','Windows Update и лицензия']];
 return `<div class="welcome-card"><div><span class="online-chip"><i></i>${esc(info.hostname)}</span><h2>Компьютер</h2><p>${esc(info.os)}</p></div><div class="welcome-art" aria-hidden="true"><img src="/brand.png" alt=""><i></i><i></i><i></i></div></div><div class="machine-specs"><div>${icon('drivers')}<span>Процессор<b>${esc(info.cpu.join(', '))}</b></span></div><div>${icon('monitor')}<span>Видеокарта<b>${esc(info.gpu.join(', '))}</b></span></div><div>${icon('overview')}<span>Память<b>${esc(info.ram)} ГБ</b></span></div></div>${section('Быстрый доступ')}<div class="quick-grid">${cards.map(([id,t,d])=>`<button class="quick-tile" data-page="${id}"><span>${icon(id)}</span><b>${t}</b><small>${d}</small><em>→</em></button>`).join('')}</div>${section('Настройки')}<div class="category-grid">${categories.map(([id,t,d])=>`<button class="category-card" data-page="${id}"><span>${icon(id)}</span><div><b>${t}</b><small>${d}</small></div><em>→</em></button>`).join('')}</div>`;
}
function profilesPage(){return `<div class="section-intro"><div><h2>Профили настроек</h2><p>Сохранённые настройки для работы и игр.</p></div></div><div class="preset-grid">${model.state.presets.map((p,i)=>`<div class="preset-card"><span class="preset-icon">${icon(['appearance','gaming','language'][i])}</span><span class="micro-label">${p.settings?Object.keys(p.settings).length:0} НАСТРОЙКИ · ${p.apps?.length||0} ПРОГРАММЫ</span><h3>${esc(p.title)}</h3><p>${esc(p.description)}</p><button class="secondary" data-preset="${p.id}">Посмотреть состав →</button></div>`).join('')}</div>${section('Личные профили',`<button class="primary small" data-action="save-profile" ${!count()?'disabled':''}>+ Сохранить текущий выбор</button>`)}${model.profiles.length?`<div class="stack">${model.profiles.map((p,i)=>`<div class="profile-row"><span class="profile-icon">${icon('profiles')}</span><div><b data-no-translate>${esc(p.name)}</b><small>${Object.keys(p.plan.settings||{}).length} системных параметров · ${(p.plan.apps||[]).length} программ</small></div><button class="secondary small" data-load-profile="${i}">Добавить в очередь</button><button class="delete-btn" data-delete-profile="${i}" aria-label="Удалить профиль ${esc(p.name)}">×</button></div>`).join('')}</div>`:empty('Сохраните свой первый профиль','Выберите нужные параметры и сохраните их одним набором.')}<div class="profile-import"><div><h3>Перенос между компьютерами</h3><p>Экспортируйте текущий выбор или загрузите файл профиля. Устройства и режимы будут проверены на этом ПК.</p></div><div class="toolbar"><button class="secondary small" data-action="export">Сохранить в файл</button><button class="secondary small" data-action="import">Загрузить из файла</button></div></div>`}
function historyPage(){const history=model.state.history||[];return `${model.state.engine.can_undo?`<div class="recovery-card"><span>${icon('history')}</span><div><h3>Сохранена резервная копия настроек</h3><p>Доступна и после перезапуска программы. Установленные программы и обновления останутся.</p></div><button class="secondary" data-action="undo">Вернуть настройки</button></div>`:''}${history.length?history.map(h=>`<details class="history-card"><summary><span class="history-symbol ${h.errors||h.interrupted||h.pending||h.closed?'attention':''}">${h.interrupted?'!':h.errors?'!':h.pending||h.closed?'?':'✓'}</span><div><b>${h.kind==='undo'?'Возврат настроек':h.kind==='action'?esc(h.title):'Применение изменений'}</b><small>${esc(new Date(h.time).toLocaleString('ru-RU'))}</small></div><span class="history-counts">${h.success} подтверждено${h.pending?' · '+h.pending+' ожидают проверки':''}${h.closed?' · '+h.closed+' без подтверждения':''}${h.errors?' · '+h.errors+' с ошибкой':''}${h.interrupted?' · прервано':''}</span><em>⌄</em></summary><div class="history-details">${h.interrupted?'<div class="note warning">Программа закрылась до завершения очереди. Проверьте результат текущей операции перед повторным применением.</div>':''}${h.items.map(i=>`<div class="list-row ${esc(i.status)}"><span class="index">${i.status==='success'?'✓':i.status==='error'?'!':['unverified','deferred'].includes(i.status)?'?':'·'}</span><div>${esc(i.title)}<span class="result">${esc(i.message||({'queued':'Не запускалось','running':'Завершение не подтверждено'})[i.status]||'')}</span></div></div>`).join('')}</div></details>`).join(''):empty('История пока пуста','После применения здесь появятся результаты каждого действия.')}<div class="profile-import"><div><h3>Нужно разобраться с ошибкой?</h3><p>Сохраните диагностику с оборудованием, задачами и результатами.</p></div><button class="secondary small" data-action="diagnostics">Сохранить диагностику</button></div>`}
function beforeValue(op){const info=model.state.info;if(op.kind==='setting'){const s=model.state.settings.find(s=>s.key===op.key),v=info.settings[op.key];return s?.choices[v]||v||'Не определено'}if(op.kind==='display')return info.displays.find(d=>d.id===op.key)?.current||'Не определено';if(op.kind==='audio'){const a=info.endpoints?.find(a=>a.id===op.key);return a?`${a.volume}% · ${a.mute?'выключен':'включён'}`:'Не определено'}if(op.kind==='brightness')return (info.brightness.find(a=>a.id===op.key)?.value??'—')+'%';return op.kind==='app'?'Состояние проверит установщик':'Требуется проверка'}
function comparisonRows(){const p=plan(),rows=[];for(const [key,value] of Object.entries(p.settings)){const s=model.state.settings.find(s=>s.key===key);rows.push({title:s?.title||key,before:beforeValue({kind:'setting',key}),after:s?.choices[value]||value,remove:'setting:'+key})}for(const d of p.displays)rows.push({title:model.state.info.displays.find(a=>a.id===d.id)?.name||'Монитор',before:beforeValue({kind:'display',key:d.id}),after:d.mode+' · '+['альбомная','книжная','перевёрнутая','книжная перевёрнутая'][d.orientation],remove:'display:'+d.id});for(const b of p.brightness)rows.push({title:'Яркость',before:beforeValue({kind:'brightness',key:b.id}),after:b.value+'%',remove:'brightness:'+b.id});for(const a of p.audio)rows.push({title:model.state.info.endpoints?.find(e=>e.id===a.id)?.name||'Звук',before:beforeValue({kind:'audio',key:a.id}),after:[a.volume!==undefined?a.volume+'%':'',a.mute!==undefined?(a.mute?'звук выключен':'звук включён'):''].filter(Boolean).join(' · '),remove:'audio:'+a.id});for(const a of p.apps)rows.push({title:model.state.apps.find(v=>v.id===a)?.name||a,before:'Проверка установленной версии',after:'Установить, если отсутствует',remove:'app:'+a});for(const id of p.updates)rows.push({title:[...(model.state.data.driver_updates||[]),...(model.state.data.software_updates||[])].find(u=>u.id===id)?.name||'Обновление: нужен повторный поиск',before:'Не установлено',after:'Загрузить и установить',remove:'update:'+id});return rows}
const coreSummary=summary;
summary=function(){let html=coreSummary();const rows=comparisonRows();const marker=html.indexOf('<div class="section-head"><h2>Ваш выбор</h2>');if(marker<0)return html;const tail=html.indexOf('<label class="inline-toggle">',marker);if(tail<0)return html;const compare=rows.length?`<div class="comparison"><div class="comparison-head"><span>Настройка</span><span>Сейчас</span><span>Станет</span><span></span></div>${rows.map(r=>`<div class="comparison-row"><b>${esc(r.title)}</b><span>${esc(r.before)}</span><strong>${esc(r.after)}</strong><button data-remove="${esc(r.remove)}" class="delete-btn" aria-label="Убрать ${esc(r.title)}" ${running()?'disabled':''}>×</button></div>`).join('')}</div>`:empty('Изменения не выбраны','Выберите нужные параметры или воспользуйтесь готовым профилем.');return html.slice(0,marker)+section('Изменения перед применением',`<span class="badge">${rows.length} пунктов</span>`)+compare+html.slice(tail)};
render=function(){hydrateWorkspace();buildNav();if(!model.state)return;let custom=null;if(model.state.info){if(model.page==='overview')custom=overviewHub();if(model.page==='catalog')custom=catalog();if(model.page==='favorites')custom=catalog(true);if(model.page==='profiles')custom=profilesPage();if(model.page==='history')custom=historyPage()}
 if(custom!==null){updateChrome();mountContent(custom)}else coreRender();
 // Stars and advanced visibility are attached to stable, meaningful setting rows.
 $('#content').querySelectorAll('[data-setting-row]').forEach(row=>{const key=row.dataset.settingRow,s=model.state.settings.find(s=>s.key===key);row.hidden=Boolean(s?.advanced&&model.uiMode==='basic');const label=row.querySelector('.label');if(label&&!label.querySelector('.star'))label.insertAdjacentHTML('beforeend',star('setting:'+key))});
 if(!['overview','catalog','favorites','profiles','history','summary','drivers','apps','monitor'].includes(model.page)&&model.state.info&&!$('#content [data-apply-section]'))$('#content').insertAdjacentHTML('beforeend',`<div class="section-apply"><span>Выбрано в разделе: ${groupCount(model.page)}</span><button class="primary" data-apply-section ${!groupCount(model.page)||blockingScan()?'disabled':''}>Применить в разделе</button></div>`);
};
async function openItem(id){const a=itemById(id);if(!a||!a.available)return;model.recent=[id,...model.recent.filter(v=>v!==id)].slice(0,8);queueSave();$('#global-search').blur();$('#search-results').hidden=true;
 if(a.kind==='device'){navigate(groupPage(a.group));return}
 if(a.kind==='windows'){try{const r=await api('/api/open',{id:a.link});if(r.message)toast(r.message)}catch(e){toast(e.message,true)}return}
 if(a.kind==='app'){navigate('apps');model.softwareTab='catalog';model.appGroup='all';model.appQuery='';render();queueSave();const element=$('#content').querySelector(`[data-app="${CSS.escape(id.slice(4))}"]`);element?.closest('.card,.check-card')?.scrollIntoView({block:'center',behavior:'smooth'});return}
 if(a.advanced)model.uiMode='all';navigate(groupPage(a.group));const row=$('#content').querySelector(`[data-setting-row="${CSS.escape(id.slice(8))}"]`);if(row){row.classList.add('highlight-setting');row.scrollIntoView({block:'center',behavior:'smooth'});setTimeout(()=>row.classList.remove('highlight-setting'),2200)}queueSave();
}
function showSearch(){const input=$('#global-search'),query=input.value,box=$('#search-results');const results=query?findItems(query).slice(0,8):model.recent.map(itemById).filter(Boolean).slice(0,6);model.searchIndex=0;box.innerHTML=`<div class="search-caption">${query?'РЕЗУЛЬТАТЫ ПОИСКА':'НЕДАВНО ОТКРЫВАЛИ'}</div>${results.length?results.map((a,i)=>`<button data-item="${esc(a.id)}" class="search-result ${i===0?'focused':''}"><span>${icon(groupPage(a.group))}</span><div><b>${esc(a.title)}</b><small>${esc(groupNames[a.group])} · ${itemKind(a)}</small></div><em>↵</em></button>`).join(''):`<div class="search-empty">${query?'Ничего не найдено. Попробуйте другое слово.':'Введите название настройки — например, «герцовка».'}</div>`}<button class="search-all" data-page="catalog">Открыть полный каталог →</button>`;box.hidden=false;input.setAttribute('aria-expanded','true')}
$('#global-search').oninput=showSearch;$('#global-search').onfocus=showSearch;
$('#global-search').onkeydown=e=>{const buttons=[...$('#search-results').querySelectorAll('.search-result')];if(e.key==='Escape'){$('#search-results').hidden=true;$('#global-search').blur()}if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();model.searchIndex=(model.searchIndex+(e.key==='ArrowDown'?1:-1)+buttons.length)%Math.max(1,buttons.length);buttons.forEach((b,i)=>b.classList.toggle('focused',i===model.searchIndex));buttons[model.searchIndex]?.scrollIntoView({block:'nearest'})}if(e.key==='Enter'&&buttons.length){e.preventDefault();openItem(buttons[model.searchIndex].dataset.item)}};
document.addEventListener('keydown',e=>{if(!document.querySelector('dialog[open]')&&(e.ctrlKey||e.metaKey)&&(e.code==='KeyK'||e.key.toLowerCase()==='k')){e.preventDefault();$('#global-search').focus()}if(e.key==='Escape')$('#search-results').hidden=true});
document.addEventListener('click',e=>{if(!e.target.closest('.global-search')){$('#search-results').hidden=true;$('#global-search').setAttribute('aria-expanded','false')}});
$('#theme-toggle').onclick=()=>{model.uiTheme=model.uiTheme==='dark'?'light':'dark';document.documentElement.dataset.theme=model.uiTheme;queueSave()};
$('#ui-mode').onchange=()=>{model.uiMode=$('#ui-mode').value;render();queueSave()};
const coreNext=$('#next').onclick;$('#next').onclick=()=>model.page==='summary'?coreNext():navigate('summary');
$('#back').onclick=async()=>{if(await ask('Сбросить выбранные изменения?','Сохранённые профили и избранное останутся.'))perform('clear')};
perform=async function(action){if(action==='elevate'){try{const response=await api('/api/elevate',{});if(response.restarting){model.appClosing=true;$('#banner').innerHTML='<div class="note success">Открывается Krolik Control с правами администратора. Выбор сохранён. Это окно можно закрыть.</div>';window.close()}else toast(response.message)}catch(e){toast(e.message,true)}return}if(action==='save-profile'){if(!count()){toast('Сначала выберите настройки');return}$('#profile-name').value='';$('#profile-dialog').showModal();$('#profile-name').focus();return}return corePerform(action)};
$('#profile-cancel').onclick=()=>$('#profile-dialog').close();
$('#profile-save').onclick=async()=>{const name=$('#profile-name').value.trim();if(!name||name.length>60){toast('Введите название до 60 символов',true);return}if(model.profiles.some(p=>p.name.toLowerCase()===name.toLowerCase())){toast('Профиль с таким названием уже есть',true);return}if(model.profiles.length>=20){toast('Можно сохранить до 20 профилей',true);return}const p=JSON.parse(JSON.stringify(plan()));if(!$('#profile-devices').checked){p.displays=[];p.audio=[];p.audio_defaults=[];p.brightness=[];p.startup=[];p.layout=[];delete p.settings.dns;delete p.settings.power_plan;p.adapter=null}p.updates=[];p.upgrades=[];model.profiles.push({name,plan:p});try{await flushWorkspace();$('#profile-dialog').close();render();toast('Профиль сохранён')}catch(e){model.profiles.pop();toast(e.message,true)}};
function compatiblePlan(p){const result={settings:{},apps:[],displays:[],brightness:[],audio:[],updates:[],adapter:p.adapter??null,restore_point:Boolean(p.restore_point&&(model.state.info.admin||model.state.demo))};let skipped=0;for(const [key,value] of Object.entries(p.settings||{})){const s=model.state.settings.find(s=>s.key===key);if(s?.enabled&&Object.hasOwn(s.choices,value))result.settings[key]=value;else skipped++}if(result.settings.dns&&!model.state.info.network.some(n=>n.id===result.adapter)){delete result.settings.dns;skipped++}for(const id of p.apps||[])if(Number(model.state.info.build)>=17763&&model.state.apps.some(a=>a.id===id))result.apps.push(id);else skipped++;for(const d of p.displays||[]){const known=model.state.info.displays.find(x=>x.id===d.id);if(known?.modes.some(m=>m.id===d.mode))result.displays.push(d);else skipped++}for(const a of p.audio||[])if(model.state.info.endpoints?.some(e=>e.id===a.id&&e.controllable))result.audio.push(a);else skipped++;for(const b of p.brightness||[])if(model.state.info.brightness.some(e=>e.id===b.id))result.brightness.push(b);else skipped++;result.upgrades=[];result.startup=[];result.layout=[];result.languages=[];for(const id of p.upgrades||[])if(model.state.data.programs?.some(r=>r.id===id&&r.installed&&r.update_available))result.upgrades.push(id);else skipped++;for(const r of p.startup||[])if(model.state.data.startup?.some(a=>a.id===r.id&&a.controllable))result.startup.push(r);else skipped++;if(p.languages?.length){if(p.languages.every(t=>model.state.info.language_options?.some(r=>r.id===t)||model.state.info.languages.includes(t)))result.languages=p.languages;else skipped++}if(p.layout?.length){if(p.layout.length===model.state.info.displays.length&&p.layout.every(r=>model.state.info.displays.some(d=>d.id===r.id)))result.layout=p.layout;else skipped++}skipped+=(p.updates||[]).length;return {plan:result,skipped}}
async function loadProfile(p,name){await api('/api/profile/validate',p);const {plan:v,skipped}=compatiblePlan(p),details=`<div class="profile-preview">${Object.entries(v.settings).map(([k,value])=>{const s=model.state.settings.find(s=>s.key===k);return `<div><b>${esc(s.title)}</b><span>${esc(s.choices[value])}</span></div>`}).join('')}${v.apps.map(id=>`<div><b>Установка</b><span>${esc(model.state.apps.find(a=>a.id===id)?.name||id)}</span></div>`).join('')}</div>`;if(!await ask('Добавить «'+name+'» в очередь?',`${Object.keys(v.settings).length} системных параметров, ${v.apps.length} программ, ${v.displays.length+v.audio.length+v.brightness.length+(v.layout?.length?1:0)} устройств, ${v.upgrades?.length||0} обновлений программ, ${v.startup?.length||0} записей автозагрузки${v.languages?.length?', языки: '+v.languages.join(', '):''}.${skipped?' Недоступных или требующих повторного поиска пунктов: '+skipped+'.':''} Система изменится только после общего применения.`,details))return;Object.assign(model.settings,v.settings);for(const field of ['displays','audio','brightness'])for(const d of v[field])model[field][d.id]={...d};for(const id of v.apps)model.apps.add(id);for(const id of v.upgrades||[])model.upgrades.add(id);for(const r of v.startup||[])model.startupChoices[r.id]=r;if(v.layout?.length)model.layout=v.layout;if(v.languages?.length){model.languageChoices=v.languages;delete model.settings.layouts}if(v.settings.layouts)model.languageChoices=[];if(v.settings.dns)model.adapter=v.adapter;model.restore=model.restore||v.restore_point;render();await flushWorkspace();toast('Профиль добавлен в очередь')}
// Override import to retain hardware validation and preview, without silently applying anything.
$('#import-file').onchange=async e=>{const file=e.target.files[0];e.target.value='';if(!file)return;try{if(file.size>131072)throw new Error('Профиль слишком большой');const p=JSON.parse(await file.text());await loadProfile(p,file.name)}catch(err){toast('Профиль не загружен: '+err.message,true)}};
document.addEventListener('input',e=>{if(e.target.id==='catalog-query'){model.catalogQuery=e.target.value;refreshCatalogResults()}});
document.addEventListener('change',e=>{if(e.target.id==='catalog-kind'){model.catalogKind=e.target.value;refreshCatalogResults()}queueSave()});
document.addEventListener('click',async e=>{const target=e.target;try{
 const starButton=target.closest('[data-star]');if(starButton){const id=starButton.dataset.star;model.favorites.has(id)?model.favorites.delete(id):model.favorites.add(id);render();queueSave();return}
 const item=target.closest('[data-item]');if(item){await openItem(item.dataset.item);return}
 const filter=target.closest('[data-filter]');if(filter){model.catalogGroup=filter.dataset.filter;render();return}
 const preset=target.closest('[data-preset]');if(preset){const p=model.state.presets.find(p=>p.id===preset.dataset.preset);await loadProfile({version:1,settings:p.settings,apps:p.apps},p.title);return}
 const profile=target.closest('[data-load-profile]');if(profile){const p=model.profiles[Number(profile.dataset.loadProfile)];await loadProfile(p.plan,p.name);return}
 const del=target.closest('[data-delete-profile]');if(del){const index=Number(del.dataset.deleteProfile);if(await ask('Удалить профиль?','Профиль «'+model.profiles[index].name+'» будет удалён. Применённые настройки останутся.')){model.profiles.splice(index,1);await flushWorkspace();render()}return}
 const remove=target.closest('[data-remove]');if(remove){const [kind,...rest]=remove.dataset.remove.split(':'),key=rest.join(':');if(kind==='setting')delete model.settings[key];if(kind==='display')delete model.displays[key];if(kind==='brightness')delete model.brightness[key];if(kind==='audio')delete model.audio[key];if(kind==='app')model.apps.delete(key);if(kind==='update')model.updates.delete(key);render();queueSave()}
 }catch(err){toast(err.message,true)}});



function sectionPlan(){
 const p={version:1,settings:{},displays:[],brightness:[],audio:[],apps:[],updates:[],adapter:model.adapter};
 for(const s of model.state.settings)if((s.group===model.page||(model.page==='appearance'&&s.group==='explorer'))&&model.settings[s.key]!==undefined)p.settings[s.key]=model.settings[s.key];
 if(model.page==='monitor'){p.displays=Object.values(model.displays);p.brightness=Object.values(model.brightness)}
 if(model.page==='sound')p.audio=Object.values(model.audio);
 if(model.page==='system')p.updates=[...model.updates].filter(id=>model.state.data.software_updates?.some(u=>u.id===id));
 return p;
}
async function previewInstant(p,text){
 if(model.appClosing||model.windowClosing||model.previewPending||modalOpen()||running())return;
 model.previewPending=true;const snapshot=structuredClone(p),navigation=model.navigationRevision||0;
 try{
  const response=await api('/api/preview',snapshot);
  if(model.appClosing||model.windowClosing||(model.navigationRevision||0)!==navigation||modalOpen()||running())return;
  if(!response.operations.length){toast('Выберите изменения');return}
  model.instantApp=null;model.instantPlan=snapshot;
  $('#apply-description').textContent=text||'Будут выполнены следующие действия:';
  $('#apply-list').innerHTML=response.operations.map(o=>`<li>${typeof previewOperationHTML==='function'?previewOperationHTML(o):esc(o.title)}</li>`).join('');$('#apply-list').hidden=false;
  updateConditions(snapshot);$('#apply-dialog').showModal();updateNavigation();
 }finally{model.previewPending=false}
};
async function offerDriverUpdates(targets){
 const list=(model.state.data.driver_updates||[]).filter(u=>u.device_ids?.some(id=>targets.includes(id)));
 if(!list.length){toast('Windows Update не предложил подходящих драйверов для выбранных устройств.');return}
 await previewInstant({version:1,updates:list.map(u=>u.id)},`Установить ${list.length} обновлений для выбранных устройств? ${list.map(u=>u.name).join('; ')}. Драйверы будут загружены и установлены здесь; может потребоваться перезагрузка.`);
}
async function updateDrivers(targets){
 if(!targets.length)return;
 if(!model.state.demo&&!model.state.info.admin){toast('Для установки нужны права администратора. Нажмите «Перезапустить с правами» вверху раздела.',true);return}
 if(taskRunning('software_updates')||taskRunning('driver_updates')){toast('Поиск обновлений уже идёт');return}
 if(model.state.tasks.driver_updates?.status==='done'&&Date.now()/1000-(model.state.tasks.driver_updates.finished||0)<600){await offerDriverUpdates(targets);return}
 model.pendingDriver=targets;
 try{await api('/api/drivers/search',{});await poll()}catch(e){model.pendingDriver=null;throw e}
}
document.addEventListener('change',e=>{
 const t=e.target;
 if(t.dataset.driverTarget){for(const id of driverMembers(t.dataset.driverTarget)){t.checked?model.driverTargets.add(id):model.driverTargets.delete(id)}$('#driver-selected').textContent='Выбрано устройств: '+model.driverTargets.size;const b=$('[data-driver-update]');if(b)b.disabled=!model.driverTargets.size||taskRunning('driver_updates');return}
 if(t.dataset.setting||t.dataset.audioVolume||t.dataset.audioMute||t.dataset.brightness){const b=$('[data-apply-section]');if(b)b.disabled=!groupCount(model.page)||blockingScan();const label=b?.parentElement.querySelector('span');if(label&&model.page!=='monitor')label.textContent='Выбрано в разделе: '+groupCount(model.page)}
 if(t.dataset.brightness){const out=t.parentElement.querySelector('output');if(out)out.textContent=t.value+'%'}
});
document.addEventListener('input',e=>{
 if(e.target.id==='app-query'){model.appQuery=e.target.value;const input=e.target,start=input.selectionStart;mountContent(apps());$('#app-query').focus();$('#app-query').setSelectionRange(start,start)}
 if(e.target.dataset.audioVolume){const b=$('[data-apply-section]');if(b)b.disabled=!groupCount(model.page)||blockingScan()}
 if(e.target.dataset.brightness){const t=e.target,out=t.parentElement.querySelector('output');if(out)out.textContent=t.value+'%'}
});
document.addEventListener('click',async e=>{
 const t=e.target;
 try{
  const category=t.closest('[data-driver-category]');if(category){model.driverCategory=category.dataset.driverCategory;render();return}
  if(t.closest('[data-driver-more]')){model.driverMore=true;$('#driver-table').innerHTML=driverTable();return}
  const app=t.closest('[data-app-group]');if(app){model.appGroup=app.dataset.appGroup;render();return}
  const reset=t.closest('[data-display-reset]');if(reset){delete model.displays[reset.dataset.displayReset];render();queueSave();return}
  if(t.closest('[data-apply-section]')){await previewInstant(sectionPlan());return}
  const one=t.closest('[data-driver-one]');if(one){await updateDrivers(driverMembers(one.dataset.driverOne));return}
  if(t.closest('[data-driver-update]')){await updateDrivers([...model.driverTargets]);return}
  if(t.closest('[data-install-updates]')){const ids=[...$('#content').querySelectorAll('input[data-update]:checked')].map(i=>i.dataset.update);await previewInstant({version:1,updates:ids});return}
 }catch(err){toast(err.message,true)}
});
