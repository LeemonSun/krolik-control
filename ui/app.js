'use strict';
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icons={
 overview:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
 drivers:'<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 1v5m6-5v5M9 18v5m6-5v5M1 9h5m-5 6h5m12-6h5m-5 6h5"/><rect x="9" y="9" width="6" height="6"/>',
 monitor:'<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8m-4-4v4"/>',
 input:'<rect x="2" y="6" width="20" height="13" rx="2"/><path d="M5 10h1m3 0h1m3 0h1m3 0h1M5 14h1m3 0h1m3 0h1m3 0h1M8 17h8"/>',
 language:'<path d="M3 5h12M9 3v2M5 5c0 6 5 10 9 11M13 5c0 6-5 10-10 12m11 4 4-11 4 11m-7-3h6"/>',
 power:'<path d="M12 2v9m-6-6a9 9 0 1 0 12 0"/>',
 network:'<path d="M2 8a16 16 0 0 1 20 0M5 12a11 11 0 0 1 14 0m-11 4a6 6 0 0 1 8 0"/><circle cx="12" cy="20" r="1"/>',
 sound:'<path d="m3 9 5 0 5-5v16l-5-5H3zM17 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>',
 appearance:'<circle cx="12" cy="12" r="9"/><path d="M12 3v18"/><path d="M12 3a9 9 0 0 1 0 18" fill="currentColor"/>',
 explorer:'<path d="M3 6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
 gaming:'<path d="M6 8h12c4 0 6 12 2 12l-4-4H8l-4 4C0 20 2 8 6 8zM6 11v5m-2-2h5m7-2h.1m3 3h.1M9 8l2-4h4"/>',
 privacy:'<path d="m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6zM8 12l3 3 5-6"/>',
 apps:'<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><path d="M14 18h8m-4-4v8"/>',
 system:'<path d="m12 3 2 3 4-1 1 4 3 3-3 3-1 4-4-1-2 3-2-3-4 1-1-4-3-3 3-3 1-4 4 1z"/><circle cx="12" cy="12" r="3"/>',
 summary:'<path d="M9 5H5v16h14V5h-4M9 3h6v5H9zM8 12l2 2 5-4m-7 8h8"/>',
};
const icon=(name)=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]||icons.system}</svg>`;
const pages=[
 ['overview','Обзор','Обзор','Настройки, программы и проверка устройств.'],
 ['drivers','Драйверы','Драйверы устройств','Загрузка от производителей, список устройств и поиск через Windows.'],
 ['monitor','Мониторы','Мониторы','Выберите разрешение и частоту обновления подключённого экрана.'],
 ['input','Мышь и клавиатура','Мышь и клавиатура','Скорость мыши, прокрутка и повтор клавиш.'],
 ['language','Язык и раскладки','Язык и раскладки','Языки ввода, основной язык и сочетание переключения.'],
 ['power','Питание','Питание и сон','Доступные схемы, таймеры экрана и сна.'],
 ['network','Сеть','Сеть','Подключённые адаптеры и выбор DNS.'],
 ['sound','Звук','Звук','Громкость и отключение звука подключённых устройств.'],
 ['appearance','Windows и Проводник','Windows и Проводник','Оформление, панель задач и отображение файлов.'],
 ['gaming','Игры','Игровые параметры','Штатный игровой режим и фоновая запись.'],
 ['privacy','Конфиденциальность','Конфиденциальность','Рекламные предложения и персонализация Windows.'],
 ['apps','Установка программ','Установка программ','Выберите программы для установки.'],
 ['system','Система и обновления','Система и обновления','Поиск и установка обновлений Windows, проверка лицензии.'],
 ['summary','Проверка и применение','Проверка и применение','Применятся только перечисленные здесь изменения.'],
];
const model={state:null,page:'overview',settings:{},displays:{},brightness:{},audio:{},apps:new Set(),updates:new Set(),adapter:null,restore:false,monitor:null,driverQuery:'',driverFilter:'all',signature:'',applied:null,activeRun:false,instantApp:null,instantPlan:null,driverTargets:new Set(),driverCategory:'all',pendingDriver:null};
const pageRenderers={};
let token=location.hash.slice(1)||sessionStorage.getItem('winpilot-token')||'';if(token)sessionStorage.setItem('winpilot-token',token);history.replaceState(null,'',location.pathname);
let toastTimer,stateEtag=null;
function toast(text,error=false){const t=$('#toast');if(!t||model.appClosing)return;t.textContent=text;t.className=error?'error':'';t.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.hidden=true,7000)}
async function api(path,body){
 const opts={headers:{'X-WinPilot-Token':token}};
 if(path==='/api/state'&&stateEtag)opts.headers['If-None-Match']=stateEtag;
 if(body!==undefined){opts.method='POST';opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(body)}
 const res=await fetch(path,opts);if(res.status===304)return null;if(path==='/api/state'&&res.ok)stateEtag=res.headers.get('ETag');let data;try{data=await res.json()}catch{throw new Error('Сервер вернул некорректный ответ')}
 if(!res.ok)throw new Error(data.error||'Ошибка запроса');return data;
}
const running=()=>Boolean(model.state?.engine.running);
const taskRunning=name=>model.state?.tasks[name]?.status==='running';
let anyScan=()=>Object.values(model.state?.tasks||{}).some(t=>t.status==='running');
const blockingScan=()=>Boolean(model.state?.data.care?.running)||Object.entries(model.state?.tasks||{}).some(([name,t])=>t.status==='running'&&!['inventory_details','drivers','activation'].includes(name));
function plan(){return {version:1,settings:{...model.settings},displays:Object.values(model.displays),brightness:Object.values(model.brightness),audio:Object.values(model.audio),apps:[...model.apps],updates:[...model.updates],adapter:model.adapter,restore_point:model.restore}}
function count(){const p=plan();return Object.keys(p.settings).length+p.displays.length+p.brightness.length+p.audio.length+p.apps.length+p.updates.length+(p.restore_point?1:0)}
function groupCount(group){if(group==='summary')return count();if(group==='monitor')return Object.keys(model.displays).length+Object.keys(model.brightness).length;if(group==='sound')return Object.keys(model.audio).length;if(group==='apps')return model.apps.size;if(group==='drivers')return [...model.updates].filter(id=>(model.state?.data.driver_updates||[]).some(u=>u.id===id)).length;if(group==='system')return [...model.updates].filter(id=>(model.state?.data.software_updates||[]).some(u=>u.id===id)).length;return (model.state?.settings||[]).filter(s=>(s.group===group||(group==='appearance'&&s.group==='explorer'))&&model.settings[s.key]!==undefined).length}
function updateChrome(){
 const idx=pages.findIndex(p=>p[0]===model.page),p=pages[idx],st=model.state,info=st?.info;
 if(!$('#nav').children.length)$('#nav').innerHTML=pages.map(([id,title])=>`<button data-page="${id}">${icon(id)}<span class="nav-label">${title}</span><span class="nav-count" aria-hidden="true" hidden></span></button>`).join('');
 $('#nav').querySelectorAll('button').forEach(button=>{const id=button.dataset.page,n=groupCount(id),badge=button.querySelector('.nav-count');button.classList.toggle('active',id===model.page);button.disabled=false;badge.hidden=!n;badge.textContent=n||''});
 $('#crumb').textContent=p[1];$('#page-title').textContent=p[2];$('#page-description').textContent=p[3];$('#step-mark').innerHTML=`${String(idx+1).padStart(2,'0')} <span>/ ${pages.length}</span>`;
 $('#count').textContent=`${count()} изменений`;$('#foot-note').textContent=running()?'Выполняется выбранная очередь':'Пока ничего не применяется';
 $('#back').disabled=idx===0||running();$('#next').disabled=!info||running()||blockingScan()||(model.page==='summary'&&!count());
 $('#next').innerHTML=model.page==='summary'?'Применить':idx===pages.length-2?'Проверить выбор <span>→</span>':'Продолжить <span>→</span>';
 $('#refresh').disabled=running()||anyScan();$('#close').disabled=running()||anyScan();
 $('#scan-status').textContent=taskRunning('inventory')?'Сканируем ПК…':!info?'ПК не просканирован':anyScan()?'Фоновая проверка…':'Компьютер определён';
 $('#scan-status').classList.toggle('busy',anyScan());
 $('#mode-pill').textContent=st?.demo?'ДЕМО · ПРИМЕР ДАННЫХ':info?.admin?'WINDOWS · АДМИНИСТРАТОР':'WINDOWS · ПОЛЬЗОВАТЕЛЬ';$('#mode-pill').className='pill '+(st?.demo?'demo':'live');
 $('#pc-name').textContent=info?.hostname||'Определяем компьютер';
 const notes=[];
 if(st?.demo)notes.push('<div class="note warning">ДЕМО: устройства и разрешения вымышленные. Это не данные вашего ПК.</div>');
 if(st?.tasks.inventory?.status==='error')notes.push(`<div class="note error">Не удалось полностью просканировать ПК: ${esc(st.tasks.inventory.error)}<br>Нажмите ↻, чтобы повторить.</div>`);
 if(info&&!info.admin&&!info.privileged_helper&&!st.demo&&['drivers','network','system','summary'].includes(model.page))notes.push('<div class="note">Для установки драйверов, обновлений и изменения DNS запустите <b>Start-Admin.cmd</b>. Текущий выбор можно сохранить в профиль.</div>');
 $('#banner').innerHTML=notes.join('');
}
function navigate(page){model.page=page;render();window.scrollTo(0,0)}
function settingCard(group){
 const settings=(model.state?.settings||[]).filter(s=>s.group===group);
 if(!settings.length)return '';
 return `<div class="card">${settings.map(s=>{
 const current=model.state.info?.settings[s.key],selected=model.settings[s.key]??'';
 const label=s.choices[current]|| (current?String(current):'Не определено');
 return `<div class="setting ${!s.enabled?'disabled':''}" data-setting-row="${s.key}"><div class="label"><b>${esc(s.title)}${s.admin?'<span class="admin">Администратор</span>':''}</b><small>${esc(s.description)}${!s.enabled?' · '+esc(s.reason):''}</small><span class="current">Сейчас: ${esc(label)}</span></div><select aria-label="${esc(s.title)}" data-setting="${s.key}" ${!s.enabled?'disabled':''}><option value="">${esc(label)} · сейчас</option>${Object.entries(s.choices).map(([v,n])=>`<option value="${esc(v)}" ${selected===v?'selected':''}>${esc(n)}</option>`).join('')}</select></div>`;
 }).join('')}</div>`;
}
function section(title,extra=''){return `<div class="section-head"><h2>${esc(title)}</h2>${extra}</div>`}
function link(id,title,sub='Откроется отдельное окно Windows'){return `<button class="link-card" data-open="${id}">${esc(title)} ↗<span>${esc(sub)}</span></button>`}
function empty(title,description=''){return `<div class="empty">${icon('system')}<h3>${esc(title)}</h3><p>${esc(description)}</p></div>`}
function taskNote(name){const t=model.state?.tasks[name];if(!t)return '';if(t.status==='running')return '<div class="scan-note"><span class="spinner"></span>Проверяем…</div>';if(t.status==='error')return `<div class="note error"><p>${esc(t.error)}</p>${['audio_test','audio_meter','voice_playback'].includes(name)?'':`<button class="secondary small" data-retry-task="${esc(name)}">Повторить</button>`}${t.details?`<details class="technical-details"><summary>Технические сведения</summary><p class="mono">${esc(t.details)}</p></details>`:''}</div>`;return ''}
function overview(){const info=model.state.info;if(!info)return `<div class="note"><span class="spinner"></span>Ищем подключённые устройства…</div><div class="grid three">${Array(6).fill('<div class="card skeleton-card"><div class="skeleton"></div><div class="skeleton short"></div></div>').join('')}</div>`;
 const hardware=[['drivers','Процессор',info.cpu.join(', ')],['monitor','Видеокарта',info.gpu.join(', ')],['overview','Оперативная память',info.ram+' ГБ'],['system','Операционная система',info.os+' · '+info.build],['monitor','Мониторы',info.displays.length+' подключено'],['network','Сетевые адаптеры',info.network.length+' обнаружено']];
 return `<div class="hero"><div class="hero-icon">${icon('privacy')}</div><div><h2>Компьютер</h2><p>Выберите раздел, чтобы посмотреть доступные настройки.</p></div><span class="badge">ПК ОПРЕДЕЛЁН</span></div><div class="grid three">${hardware.map(([i,n,v])=>`<div class="card hardware-card"><span class="hw-icon">${icon(i)}</span><small>${n}</small><strong>${esc(v)}</strong></div>`).join('')}</div>${info.board?`<p class="muted">Плата: ${esc(info.board.Manufacturer)} ${esc(info.board.Product)} · BIOS: ${esc(info.bios?.SMBIOSBIOSVersion||'—')} · Накопители: ${esc((info.disks||[]).map(d=>d.name+' '+d.size+' ГБ').join(', '))}</p>`:''}${section('Быстрый переход','<small>Начните с любого раздела</small>')}<div class="grid">${[['drivers','Проверить драйверы','Все устройства и отсутствующие драйверы'],['monitor','Настроить монитор','Разрешение, герцовка и ориентация'],['apps','Установить браузер','Firefox, Chrome и другие программы'],['language','Выбрать раскладки','Русский, английский и переключение']].map(([id,t,d])=>`<button data-page="${id}" class="card quick"><span>${icon(id)}</span><div><b>${t}</b><small>${d}</small></div><em>→</em></button>`).join('')}</div>${section('Профиль настроек')}<div class="card profile-card"><div><h3>Сохранить выбор и продолжить позже</h3><p>При загрузке доступность устройств и значений проверяется заново.</p></div><div class="toolbar"><button class="secondary small" data-action="export">Сохранить в файл</button><button class="secondary small" data-action="import">Загрузить из файла</button><button class="secondary small" data-action="diagnostics">Диагностика</button></div></div>`;
}
function updateList(name){const list=model.state.data[name]||[];if(!list.length)return '';
 return `<div class="stack">${list.map(u=>`<label class="check-card"><input type="checkbox" data-update="${esc(u.id)}" ${model.updates.has(u.id)?'checked':''}><div><b>${esc(u.name)}</b><small>${u.driver?'Драйвер Microsoft Update':'Обновление Windows'} · ревизия ${u.revision}</small></div><span class="app-size">до ${u.size} МБ</span></label>`).join('')}</div>`;
}
function drivers(){
 const data=model.state.data.drivers||[],updates=model.state.data.driver_updates||[],categories=[...new Set(data.map(d=>d.category||'Unknown'))];
 const available=updates.filter(u=>model.driverTargets.size?u.device_ids?.some(id=>model.driverTargets.has(id)):model.driverCategory==='all'||u.category?.toLowerCase()===model.driverCategory.toLowerCase());
 return `<div class="device-toolbar"><div><span class="badge">${data.length} устройств</span> <span class="muted">${data.filter(d=>d.problem).length} требуют внимания</span></div><div class="toolbar"><button class="secondary small" data-action="drivers" ${taskRunning('drivers')?'disabled':''}>↻ Пересканировать</button><button class="secondary small" data-action="driver-search" ${taskRunning('driver_updates')||taskRunning('software_updates')?'disabled':''}>Найти обновления драйверов</button></div></div>${taskNote('drivers')}${taskNote('driver_updates')}
 <div class="filter-chips"><button data-driver-category="all" class="${model.driverCategory==='all'?'active':''}">Все</button>${categories.map(c=>`<button data-driver-category="${esc(c)}" class="${model.driverCategory===c?'active':''}">${esc(driverCategory(c))}</button>`).join('')}</div>
 <div class="toolbar"><input type="search" id="driver-query" placeholder="Название устройства или производитель" aria-label="Поиск устройств" value="${esc(model.driverQuery)}"><select id="driver-filter" aria-label="Фильтр драйверов"><option value="all" ${model.driverFilter==='all'?'selected':''}>Все устройства</option><option value="problem" ${model.driverFilter==='problem'?'selected':''}>С проблемами</option></select></div>
 <div id="driver-table">${data.length?driverTable():model.state.tasks.drivers?.status==='error'?empty('Список устройств недоступен','Повторите сканирование кнопкой выше.'):model.state.tasks.drivers?.status==='done'?empty('Устройства не найдены','Можно повторить сканирование.'):empty('Определяем устройства…','Список загружается автоматически.')}</div>
 <div class="section-apply"><span id="driver-selected">Выбрано устройств: ${model.driverTargets.size}</span><button class="primary" data-driver-update ${!model.driverTargets.size||taskRunning('driver_updates')?'disabled':''}>Обновить выбранные</button></div>
 ${updates.length?section('Доступно для установки')+`<div class="stack">${available.map(updateCard).join('')||'<p class="muted">Для выбранных устройств подходящих обновлений нет.</p>'}</div><button class="secondary space-top" data-install-updates ${!available.some(u=>model.updates.has(u.id))?'disabled':''}>Установить отмеченные обновления</button>`:''}
 <p class="muted">Перед обновлением сохраняется копия сторонних драйверов. Если копию создать не удалось, обновления не начинаются. Источник — Windows Update. Устанавливаются только пакеты, которые Windows признала совместимыми с этим ПК. Для части оборудования производитель может не публиковать пакеты здесь.</p>`;
}
function driverCategory(c){return ({Display:'Видеокарты',Processor:'Процессор',Net:'Сеть',MEDIA:'Звук',AudioEndpoint:'Аудиоустройства',System:'Система',USB:'USB',HIDClass:'Устройства ввода',Keyboard:'Клавиатуры',Mouse:'Мыши',Monitor:'Мониторы',Bluetooth:'Bluetooth',Printer:'Принтеры',DiskDrive:'Накопители',Unknown:'Неизвестные'})[c]||c}
function updateCard(u){return `<label class="check-card"><input type="checkbox" data-update="${esc(u.id)}" ${model.updates.has(u.id)?'checked':''}><div><b>${esc(u.name)}</b><small>${esc(u.provider||'Windows Update')}${u.device_ids?.length?' · для '+u.device_ids.length+' устройств':''}</small></div><span class="app-size">${u.size} МБ</span></label>`}

function groupedDrivers(){const groups=new Map(),rows=[];for(const d of model.state.data.drivers||[]){const key=d.category==='Processor'?d.name:null;if(key&&groups.has(key)){groups.get(key).members.push(d.id)}else{const row={...d,members:[d.id]};rows.push(row);if(key)groups.set(key,row)}}return rows}
function driverMembers(id){return groupedDrivers().find(d=>d.id===id)?.members||[id]}
function driverTable(){const rows=groupedDrivers().filter(d=>(model.driverCategory==='all'||(d.category||'Unknown')===model.driverCategory)&&(model.driverFilter!=='problem'||d.problem!==0)&&[d.name,d.provider,d.category,d.id,d.inf].join(' ').toLowerCase().includes(model.driverQuery.toLowerCase()));
 if(!rows.length)return empty('Устройства не найдены','Измените запрос или фильтр.');
 const shown=(!model.driverMore&&!model.driverQuery&&model.driverFilter==='all'&&model.driverCategory==='all')?rows.slice(0,12):rows;
 return `<div class="device-list">${shown.map(d=>`<div class="device-row"><input type="checkbox" data-driver-target="${esc(d.id)}" aria-label="Выбрать ${esc(d.name||'устройство')}" ${d.members.every(id=>model.driverTargets.has(id))?'checked':''}><span class="device-icon">${icon(d.category==='Display'?'monitor':d.category==='Net'?'network':d.category==='MEDIA'?'sound':'drivers')}</span><div class="device-name"><b>${esc(d.name||'Без названия')}${d.members.length>1?' · '+d.members.length+' устройств':''}</b><small>${esc(d.provider||driverCategory(d.category||'Unknown'))} · ${esc(d.version||'Версия не определена')}</small><details><summary>Сведения об устройстве</summary><p>${esc(d.id)}<br>${esc(d.inf||'INF не найден')} · ${esc(d.date||'Дата не определена')}</p></details></div><span class="device-state ${d.problem?'bad':'ok'}">${d.problem?d.problem===28?'Нет драйвера':'Ошибка '+d.problem:'Работает'}</span><button class="secondary small" data-driver-one="${esc(d.id)}" ${taskRunning('driver_updates')?'disabled':''}>Обновить</button></div>`).join('')}</div>${shown.length<rows.length?`<button class="secondary space-top" data-driver-more>Остальные устройства · ${rows.length-shown.length}</button>`:''}`;
}

function monitor(){const info=model.state.info,list=info.displays;
 if(!list.length)return empty('Мониторы не обнаружены','Проверьте подключение и нажмите ↻.');
 if(!list.some(d=>d.id===model.monitor))model.monitor=list[0].id;
 const d=list.find(x=>x.id===model.monitor),chosen=model.displays[d.id],currentMode=chosen?.mode||d.current,[resolution,hz]=currentMode.split('@');
 const modes=d.modes,resolutions=[...new Set(modes.map(m=>m.width+'x'+m.height))],rates=modes.filter(m=>m.width+'x'+m.height===resolution);
 return `<div class="monitor-select">${list.map((m,i)=>`<button class="monitor-tab ${m.id===d.id?'active':''}" data-monitor="${esc(m.id)}">${icon('monitor')}<span>${i+1}. ${esc(m.name)}<small>${m.primary?'Основной экран':'Дополнительный экран'}</small></span></button>`).join('')}</div>
 <div class="display-layout"><div class="display-art" aria-hidden="true"><div class="display-ambient"></div><div class="display-bezel"><div class="display-wallpaper"><span>${list.indexOf(d)+1}</span><small>${esc(d.name)}</small><i></i><i></i><i></i></div></div><div class="display-neck"></div><div class="display-foot"></div><span class="display-spec">${esc(d.current.replace('x',' × ').replace('@',' · '))} Гц</span></div><div class="card display-controls"><div class="device-heading"><span class="device-icon">${icon('monitor')}</span><div><h2>${esc(d.name)}</h2><p>${esc(d.gpu)}</p></div></div>
 <div class="setting"><div class="label"><b>Разрешение</b></div><select id="display-resolution" aria-label="Разрешение">${resolutions.map(r=>`<option value="${r}" ${r===resolution?'selected':''}>${r.replace('x',' × ')}</option>`).join('')}</select></div>
 <div class="setting"><div class="label"><b>Частота обновления</b><small>${rates.length} доступных ${rates.length===1?'режим':'режима'}</small></div><select id="display-rate" aria-label="Частота обновления">${rates.map(m=>`<option value="${m.hz}" ${String(m.hz)===hz?'selected':''}>${m.hz} Гц${String(m.hz)===d.current.split('@')[1]&&resolution===d.current.split('@')[0]?' · сейчас':''}</option>`).join('')}</select></div>
 <div class="setting"><div class="label"><b>Ориентация</b></div><select id="display-orientation" aria-label="Ориентация">${['Альбомная','Книжная','Альбомная перевёрнутая','Книжная перевёрнутая'].map((v,i)=>`<option value="${i}" ${(chosen?.orientation??d.orientation)===i?'selected':''}>${v}</option>`).join('')}</select></div>
 <div class="section-apply"><span>${chosen?'Есть изменения':'Текущий режим'}</span>${chosen?`<button class="text-btn" data-display-reset="${esc(d.id)}">Сбросить</button>`:''}<button class="primary" data-apply-section ${!chosen?'disabled':''}>Применить</button></div></div></div>
 ${info.brightness.length?section('Яркость')+`<div class="card">${info.brightness.map((b,i)=>`<div class="setting"><div class="label"><b>Встроенный экран ${i+1}</b><small>Сейчас ${b.value}%</small></div><input type="range" min="0" max="100" aria-label="Яркость экрана ${i+1}" data-brightness="${esc(b.id)}" value="${model.brightness[b.id]?.value??b.value}"><output>${model.brightness[b.id]?.value??b.value}%</output></div>`).join('')}</div>`:''}
 <div class="quiet-tip">${icon('privacy')}<p>После переключения будет 20 секунд на подтверждение. Без ответа вернётся прежний режим.</p></div>
 <details class="support-details"><summary>Доступность параметров</summary><p>Показаны режимы, предоставленные видеодрайвером. Дробная частота отображается округлённо. Дополнительные настройки HDR, масштаба, цветовых профилей и яркости внешних экранов пока недоступны.</p></details>`;
}

function network(){const info=model.state.info;return `<div class="grid">${info.network.map(n=>`<div class="card"><h3>${esc(n.name)}</h3><p>${esc(n.description)}</p><p class="space-top"><span class="badge">${esc(n.status)}</span></p><p class="mono space-top">IPv4 DNS: ${esc(n.dns.join(', ')||'Не определён')}</p></div>`).join('')}</div>${section('Настройка DNS')}<div class="card"><div class="setting"><div class="label"><b>Сетевой адаптер</b><small>Выберите конкретное подключение.</small></div><select id="network-adapter" aria-label="Сетевой адаптер"><option value="">Выберите адаптер</option>${info.network.map(n=>`<option value="${n.id}" ${model.adapter===n.id?'selected':''}>${esc(n.name)}</option>`).join('')}</select></div></div><div class="space-top">${settingCard('network')}</div>`}
function sound(){const info=model.state.info,endpoints=info.endpoints||[];
 return `${info.audio_error?`<div class="note warning">Не удалось прочитать аудиоустройства. Повторите проверку.</div>`:''}${endpoints.length?`<div class="stack">${endpoints.map(a=>{const chosen=model.audio[a.id];return `<div class="card"><h3>${esc(a.name)} ${a.default?'<span class="badge">По умолчанию</span>':''}</h3><p>${a.flow===0?'Устройство вывода':'Микрофон'} · сейчас ${a.volume??'—'}%${a.mute?' · звук отключён':''}</p>${a.controllable?`<div class="setting space-top"><div class="label"><b>Громкость</b><small>0–100%. Пустое поле — не менять.</small></div><input class="volume-input" type="number" min="0" max="100" step="1" placeholder="Не менять" aria-label="Громкость ${esc(a.name)}" data-audio-volume="${esc(a.id)}" value="${esc(numericValue('audio:'+a.id,chosen?.volume??''))}"></div><div class="setting"><div class="label"><b>Отключение звука</b><small>Изменение нужно подтвердить.</small></div><select aria-label="Отключение звука ${esc(a.name)}" data-audio-mute="${esc(a.id)}"><option value="">Не менять</option><option value="false" ${chosen?.mute===false?'selected':''}>Звук включён</option><option value="true" ${chosen?.mute===true?'selected':''}>Звук отключён</option></select></div>`:'<p class="muted">Громкость этого устройства нельзя изменить здесь.</p>'}</div>`}).join('')}</div>`:empty('Активные динамики и микрофоны не обнаружены')}`;
}
function applicationStatus(row){
 if(!row)return taskRunning('programs')?'Проверяем наличие…':'Проверка ещё не выполнена';
 if(row.installed)return 'Установлена'+(row.version?' · '+row.version:'');
 return 'Доступна к установке';
}
function apps(){
 const rows=model.state.data.programs||[],all=model.state.apps,ready=model.state.info.winget,supported=Number(model.state.info.build)>=17763;
 const groups=[...new Set(all.map(a=>a.group))],query=(model.appQuery||'').toLocaleLowerCase(),filtered=all.filter(a=>(!model.appGroup||model.appGroup==='all'||a.group===model.appGroup)&&[a.name,a.group,a.id].join(' ').toLocaleLowerCase().includes(query));
 const setupError=[...(model.state.engine.items||[])].reverse().find(i=>i.kind==='package_manager'&&i.status==='error');
 const setup=!supported?'<div class="note warning">Для установки программ нужна Windows 10 1809 или новее.</div>':!ready?`<div class="setup-note"><span>${setupError?esc(setupError.message):'Первую установку подготовим автоматически. Нужен интернет.'}</span><button class="secondary small" data-prepare-apps ${running()||blockingScan()?'disabled':''}>${setupError?'Повторить подготовку':'Подготовить сейчас'}</button></div>`:'';
 const card=a=>{const row=rows.find(r=>r.id===a.id),upgrade=row?.installed&&row.update_available;return `<article class="card program-card" data-program-id="${esc(a.id)}"><div class="program-top"><span class="program-logo logo-${a.group==='Браузер'?'browser':a.group==='Игры'?'games':'tools'}">${esc(a.name.slice(0,1))}</span><div><h3>${esc(a.name)}</h3><p>${esc(a.group)}</p></div></div><div class="program-status ${row?.installed?'installed':''}">${esc(applicationStatus(row))}</div>${upgrade?`<p class="update-offer">Доступна версия ${esc(row.available_version)}</p>`:row?.update_check==='unavailable'?'<p class="muted">Обновления проверить не удалось</p>':''}<div class="program-actions"><label><input type="checkbox" aria-label="В очередь: ${esc(a.name)}" data-app="${a.id}" ${model.apps.has(a.id)?'checked':''} ${!supported?'disabled':''}>${row?.installed?'В набор':'В очередь'}</label>${!row?.installed?`<button class="secondary small" data-install="${a.id}" ${!supported||blockingScan()?'disabled':''}>Установить сейчас</button>`:upgrade?`<label><input type="checkbox" aria-label="Обновить: ${esc(a.name)}" data-upgrade="${a.id}" ${model.upgrades.has(a.id)?'checked':''}>Обновить</label><button class="secondary small" data-upgrade-now="${a.id}">Обновить сейчас</button>`:''}</div></article>`};
 return `${setup}${running()?'<div class="note">Сейчас выполняется очередь. <button class="text-btn" data-page="summary">Посмотреть ход выполнения →</button></div>':''}<div class="program-toolbar"><input id="app-query" type="search" aria-label="Поиск программ" placeholder="Найти программу" value="${esc(model.appQuery||'')}"><button class="secondary small" data-action="program-updates" ${taskRunning('programs')||!ready?'disabled':''}>Проверить обновления</button><button class="secondary small" data-export-programs ${!rows.some(r=>r.installed)?'disabled':''}>Сохранить набор</button></div>${taskNote('programs')}<div class="filter-chips"><button data-app-group="all" class="${!model.appGroup||model.appGroup==='all'?'active':''}">Все</button>${groups.map(g=>`<button data-app-group="${esc(g)}" class="${model.appGroup===g?'active':''}">${g==='Браузер'?'Браузеры':esc(g)}</button>`).join('')}</div><div id="program-list">${programResults(filtered,groups,card)}</div><div class="section-apply"><span>В очереди: ${groupCount('apps')}</span><button class="primary" data-apply-section ${!groupCount('apps')?'disabled':''}>Установить выбранное</button></div><details class="support-details"><summary>Как проходит установка</summary><p>Выбранные программы загружаются из каталога Microsoft WinGet. При необходимости Krolik Control сам установит официальный компонент Microsoft. Windows может запросить подтверждение прав. Условия выбранных пакетов принимаются после подтверждения списка. Для нового основного браузера Windows может потребовать отдельный выбор.</p><p>Сохранение набора включает отмеченные установленные программы. Если такие не отмечены — все установленные из этого каталога.</p></details>`;
}
function programResults(filtered,groups,card){return groups.filter(g=>filtered.some(a=>a.group===g)).map(g=>section(g==='Браузер'?'Браузеры':g)+`<div class="program-grid">${filtered.filter(a=>a.group===g).map(card).join('')}</div>`).join('')||empty('Программы не найдены')}
function system(){const activation=model.state.data.activation||[];
 return `${section('Обновления Windows')}<div class="toolbar"><button class="primary" data-action="software-search" ${taskRunning('driver_updates')||taskRunning('software_updates')?'disabled':''}>Найти обновления</button></div>${taskNote('software_updates')}${updateList('software_updates')||empty('Доступные обновления появятся здесь','Поиск запускается кнопкой выше.')} ${section('Лицензия Windows')}<div class="card"><div class="profile-card"><div><h3>Состояние активации</h3><p>Проверка установленной лицензии</p></div><button class="secondary" data-action="activation" ${taskRunning('activation')?'disabled':''}>Проверить</button></div>${activation.map(a=>`<div class="list-row">${esc(a.Name)}<span class="badge">${['Не лицензирована','Активирована','Льготный период','Льготный период','Льготный период','Уведомление','Льготный период'][a.LicenseStatus]||'Неизвестно'}</span></div>`).join('')}</div>${taskNote('activation')}`;
}

function selectedRows(){const p=plan(),state=model.state,all=[];
 for(const [key,value] of Object.entries(p.settings)){const s=state.settings.find(s=>s.key===key);all.push([s?.title||key,s?.choices[value]||value])}
 for(const d of p.displays)all.push(['Монитор '+d.id,d.mode+' · ориентация '+d.orientation]);
 for(const b of p.brightness)all.push(['Яркость',b.value+'%']);
 for(const a of p.audio)all.push(['Звук',`${state.info.endpoints?.find(e=>e.id===a.id)?.name||a.id}: ${a.volume!==undefined?a.volume+'% ':''}${a.mute!==undefined?(a.mute?'выключен':'включён'):''}`]);
 for(const id of p.apps)all.push(['Программа',state.apps.find(a=>a.id===id)?.name||id]);
 for(const id of p.updates)all.push(['Обновление',[...(state.data.driver_updates||[]),...(state.data.software_updates||[])].find(u=>u.id===id)?.name||'Запись недоступна — повторите поиск']);
 return all;
}
function summary(){const state=model.state,engine=state.engine,items=engine.items||[],done=items.filter(i=>!['queued','running'].includes(i.status)).length,errors=items.filter(i=>i.status==='error').length;
 return `${engine.running||engine.finished?`<div class="card"><div class="profile-card"><h2>${engine.running?'Применяем выбранные настройки':errors?'Завершено с ошибками':'Очередь завершена'}</h2><span class="badge">${done} / ${items.length}</span></div><div class="progress"><div id="job-progress"></div></div>${engine.running?'<button class="secondary small" data-action="cancel">Остановить после текущего пункта</button>':''}${engine.reboot?'<div class="note warning space-top">Для установленных обновлений нужна перезагрузка. Перезагрузите ПК вручную после сохранения работы.</div>':''}${items.map((i,index)=>`<div class="list-row ${esc(i.status)}"><span class="index">${{queued:'·',running:'…',success:'✓',unverified:'?',deferred:'◷',error:'!',skipped:'−'}[i.status]}</span><div>${esc(i.title)}${i.message?i.status==='error'?`<p class="result">${esc(i.message)}</p><details><summary>Сведения об ошибке</summary>${i.details?`<p class="mono">${esc(i.details)}</p>`:''}<button class="secondary small" data-copy-error="${index}">Копировать ошибку</button></details>`:`<span class="result">${esc(i.message)}</span>`:''}</div></div>`).join('')}${errors&&!engine.running&&!engine.persistence_error&&items.some(i=>i.kind)?`<button class="secondary small space-top" data-retry-failed ${blockingScan()?'disabled':''}>Повторить ошибки</button>`:''}${engine.log?`<details class="muted"><summary>Сведения о выполнении</summary><p class="mono">${esc(engine.log)}</p></details>`:''}${engine.can_undo?'<button class="secondary small space-top" data-action="undo">Вернуть сохранённые настройки</button><p class="muted">Откат возвращает сохранённые настройки реестра, ввода, языков, питания, DNS, звука и яркости. Программы, обновления и подтверждённые режимы экранов не удаляются.</p>':''}</div>`:''}${section('Ваш выбор',`<button class="text-btn" data-action="clear" ${running()?'disabled':''}>Сбросить выбор</button>`)}${selectedRows().length?`<div class="card">${selectedRows().map(([title,value],i)=>`<div class="list-row"><span class="index">${i+1}</span><div>${esc(title)}</div><small>${esc(value)}</small></div>`).join('')}</div>`:empty('Новых изменений не выбрано','Откройте категории слева и выберите нужные параметры.')}<label class="inline-toggle"><input id="restore-point" type="checkbox" ${model.restore?'checked':''} ${(!state.info.admin&&!state.info.privileged_helper&&!state.demo)||running()?'disabled':''}>Создать точку восстановления перед изменениями (нужны права администратора)</label><div class="note">Сначала настройки и программы, затем обновления и мониторы. Ошибки будут показаны отдельно. Интернет-поиск и установка могут занять несколько минут. Перезагрузка автоматически не выполняется.</div><div class="toolbar"><button class="secondary small" data-action="export">Сохранить профиль</button><button class="secondary small" data-action="import" ${running()?'disabled':''}>Загрузить профиль</button></div>`;
}
function render(){if(!model.state)return;updateChrome();
 let html='';if(!model.state.info&&model.page!=='overview')html=empty('Дождитесь определения ПК','Здесь появятся параметры, доступные на вашем компьютере.');else switch(model.page){
 case 'overview':html=overview();break;case 'drivers':html=drivers();break;case 'monitor':html=monitor();break;case 'network':html=network();break;case 'sound':html=sound();break;case 'apps':html=apps();break;case 'system':html=system();break;case 'summary':html=summary();break;
 case 'appearance':html=settingCard('appearance')+section('Проводник')+settingCard('explorer');break;
 default:html=settingCard(model.page);}
 mountContent(html);
 if($('#job-progress'))$('#job-progress').style.width=`${model.state.engine.items.length?model.state.engine.items.filter(i=>!['queued','running'].includes(i.status)).length/model.state.engine.items.length*100:0}%`;
}
async function perform(action){
 const requests={drivers:'/api/drivers','driver-search':'/api/drivers/search','software-search':'/api/updates/search',activation:'/api/activation'};
 try{
 if(requests[action]){await api(requests[action],{});await poll();return}
 if(action==='export'){const blob=new Blob([JSON.stringify(plan(),null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='KrolikControl-profile.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return}
 if(action==='diagnostics'){const blob=new Blob([JSON.stringify({version:1,info:model.state.info,tasks:model.state.tasks,engine:model.state.engine},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='KrolikControl-diagnostics.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return}
 if(action==='import'){$('#import-file').click();return}
 if(action==='clear'){model.settings={};model.displays={};model.brightness={};model.audio={};model.apps.clear();model.updates.clear();model.restore=false;render();return}
 if(action==='cancel'){await api('/api/cancel',{});toast('Очередь остановится после текущей операции');return}
 if(action==='undo'){if(!await ask('Вернуть сохранённые настройки?','Программы, обновления и подтверждённые режимы экранов останутся. Настройки вернутся из сохранённой резервной копии.'))return;await api('/api/undo',{});model.applied=null;await poll();return}
 }catch(e){toast(e.message,true)}
}
document.addEventListener('click',async e=>{
 const page=e.target.closest('[data-page]');if(page){navigate(page.dataset.page);return}
 const open=e.target.closest('[data-open]');if(open){try{const r=await api('/api/open',{id:open.dataset.open});if(r.message)toast(r.message)}catch(err){toast(err.message,true)}return}
 const action=e.target.closest('[data-action]');if(action){perform(action.dataset.action);return}
 const monitor=e.target.closest('[data-monitor]');if(monitor){model.monitor=monitor.dataset.monitor;render();return}
 const download=e.target.closest('[data-download]');if(download){if(!await ask('Открыть официальный сайт?','Будет открыта страница загрузки выбранного браузера.'))return;try{const r=await api('/api/open',{id:download.dataset.download});if(r.message)toast(r.message)}catch(err){toast(err.message,true)}return}
 const install=e.target.closest('[data-install]'); if(install){const id=install.dataset.install,a=model.state.apps.find(x=>x.id===id);try{await previewInstant({version:1,apps:[id]},`Установить ${a.name}? Остальные изменения останутся в очереди.`)}catch(err){toast(err.message,true)}return}
});
document.addEventListener('change',e=>{const t=e.target;if(t.dataset.setting){if(t.value)model.settings[t.dataset.setting]=t.value;else delete model.settings[t.dataset.setting];updateChrome();return}
 if(t.dataset.audioVolume||t.dataset.audioMute){const id=t.dataset.audioVolume||t.dataset.audioMute,a=model.audio[id]||{id};if(t.dataset.audioVolume){if(t.value==='')delete a.volume;else a.volume=Number(t.value)}else{if(t.value==='')delete a.mute;else a.mute=t.value==='true'}if(Object.keys(a).length>1)model.audio[id]=a;else delete model.audio[id];updateChrome();return}
 if(t.dataset.app){t.checked?model.apps.add(t.dataset.app):model.apps.delete(t.dataset.app);updateChrome();return}
 if(t.dataset.update){t.checked?model.updates.add(t.dataset.update):model.updates.delete(t.dataset.update);updateChrome();const install=$('[data-install-updates]');if(install)install.disabled=!model.state.data.driver_updates?.some(u=>model.updates.has(u.id));return}
 if(t.dataset.brightness){if(t.value!=='')model.brightness[t.dataset.brightness]={id:t.dataset.brightness,value:Number(t.value)};else delete model.brightness[t.dataset.brightness];updateChrome();return}
 if(t.id==='network-adapter'){model.adapter=t.value?Number(t.value):null;return}
 if(t.id==='restore-point'){model.restore=t.checked;updateChrome();return}
 if(t.id==='driver-filter'){model.driverFilter=t.value;$('#driver-table').innerHTML=driverTable();return}
 if(t.id.startsWith('display-')){const d=model.state.info.displays.find(d=>d.id===model.monitor);let v=model.displays[d.id];if(t.id!=='display-enable'&&!v)v=model.displays[d.id]={id:d.id,mode:d.current,orientation:d.orientation};
 if(t.id==='display-enable'){if(t.value)v=model.displays[d.id]={id:d.id,mode:d.current,orientation:d.orientation};else delete model.displays[d.id]}
 if(v&&t.id==='display-resolution'){const hz=v.mode.split('@')[1],modes=d.modes.filter(m=>m.width+'x'+m.height===t.value);v.mode=(modes.find(m=>String(m.hz)===hz)||modes[0]).id}
 if(v&&t.id==='display-rate')v.mode=v.mode.split('@')[0]+'@'+t.value;
 if(v&&t.id==='display-orientation')v.orientation=Number(t.value);
 if(v&&v.mode===d.current&&v.orientation===d.orientation)delete model.displays[d.id];
 render();}
});
document.addEventListener('input',e=>{const t=e.target;if(t.id==='driver-query'){model.driverQuery=t.value;$('#driver-table').innerHTML=driverTable()}if(t.dataset.audioVolume){const id=t.dataset.audioVolume,a=model.audio[id]||{id};if(t.value==='')delete a.volume;else a.volume=Number(t.value);if(Object.keys(a).length>1)model.audio[id]=a;else delete model.audio[id];updateChrome()}});
$('#back').onclick=()=>navigate(pages[pages.findIndex(p=>p[0]===model.page)-1]?.[0]||'overview');
$('#next').onclick=async()=>{if(model.page!=='summary'){navigate(pages[pages.findIndex(p=>p[0]===model.page)+1][0]);return}try{await previewInstant(plan())}catch(e){toast(e.message,true)}};
$('#refresh').onclick=async()=>{try{await api('/api/scan',{});await poll()}catch(e){toast(e.message,true)}};
$('#close').onclick=async()=>{try{await api('/api/close',{});model.appClosing=true;document.body.innerHTML='<main><h1>Krolik Control закрыт.</h1><p>Это окно можно закрыть.</p></main>';window.close()}catch(e){toast(e.message,true)}};
$('#apply-no').onclick=()=>$('#apply-dialog').close();
$('#apply-yes').onclick=async()=>{const b=$('#apply-yes');b.disabled=true;try{const p=model.instantPlan||(model.instantApp?{version:1,apps:[model.instantApp]}:plan());const started=await api('/api/apply',p);model.applied=p;model.appliedRun=started.run;model.activeRun=true;$('#apply-dialog').close();navigate('summary');await poll()}catch(e){toast(e.message,true)}finally{b.disabled=false}};
async function confirmDisplay(keep){try{const pending=model.state?.display_pending;if(pending)await api('/api/display/confirm',{id:pending.id,keep});$('#display-dialog').close();await poll()}catch(e){toast(e.message,true)}}
$('#display-keep').onclick=()=>confirmDisplay(true);$('#display-revert').onclick=()=>confirmDisplay(false);$('#display-dialog').addEventListener('cancel',e=>{e.preventDefault();confirmDisplay(false)});
$('#import-file').onchange=async e=>{const file=e.target.files[0];e.target.value='';if(!file)return;try{if(file.size>131072)throw new Error('Профиль слишком большой');const p=JSON.parse(await file.text());await api('/api/profile/validate',p);model.settings=p.settings||{};model.displays=Object.fromEntries((p.displays||[]).map(d=>[d.id,d]));model.brightness=Object.fromEntries((p.brightness||[]).map(d=>[d.id,d]));model.audio=Object.fromEntries((p.audio||[]).map(d=>[d.id,d]));model.apps=new Set(p.apps||[]);model.updates=new Set(p.updates||[]);model.adapter=p.adapter??null;model.restore=Boolean(p.restore_point);render();toast('Профиль загружен и проверен')}catch(err){toast('Профиль не загружен: '+err.message,true)}};
function sameAudioChoice(a,b){return Boolean(a&&b&&Object.keys(a).length===Object.keys(b).length&&Object.keys(a).every(k=>a[k]===b[k]))}
function reconcile(){const p=model.applied;if(!p)return;const ops=model.state.engine.items.filter(i=>i.status==='success');for(const op of ops){if(op.kind==='setting'&&model.settings[op.key]===op.value)delete model.settings[op.key];if(op.kind==='app')model.apps.delete(op.key);if(op.kind==='update')model.updates.delete(op.key);if(op.kind==='display'&&model.displays[op.key]?.mode===op.value&&model.displays[op.key]?.orientation===op.orientation)delete model.displays[op.key];if(op.kind==='brightness'&&model.brightness[op.key]?.value===op.value)delete model.brightness[op.key];if(op.kind==='audio'&&sameAudioChoice(model.audio[op.key],op.value))delete model.audio[op.key];if(op.kind==='restore_point')model.restore=false}model.applied=null}
let polling=false,connected=true;
async function poll(){if(model.appClosing||polling)return;polling=true;try{const state=await api('/api/state');if(!state||model.appClosing)return;connected=true;model.state=state;
 if(typeof reconcileVerification==='function')reconcileVerification(state);
 if(!state.engine.running&&state.engine.finished&&model.applied&&state.engine.log===model.appliedRun){reconcile();toast(state.engine.items.some(i=>i.status==='error')?'Очередь завершена. Проверьте ошибки в результатах.':state.demo?'Демонстрация завершена. Система не изменена.':state.engine.items.some(i=>['unverified','deferred'].includes(i.status))?'Команды выполнены. Часть результатов ожидает проверки.':'Выбранные операции завершены.',state.engine.items.some(i=>i.status==='error'));}
 model.activeRun=state.engine.running;
 if(model.pendingDriver&&state.tasks.driver_updates?.status==='done'){const targets=model.pendingDriver;model.pendingDriver=null;setTimeout(()=>offerDriverUpdates(targets),0)}else if(model.pendingDriver&&state.tasks.driver_updates?.status==='error')model.pendingDriver=null;
 const pending=state.display_pending,dialog=$('#display-dialog');if(pending){$('#countdown').textContent=pending.seconds;if(!dialog.open)dialog.showModal()}else if(dialog.open)dialog.close();
 const signature=JSON.stringify({...state,display_pending:Boolean(pending)});
 if(signature!==model.signature){model.signature=signature;render()}
 }catch(e){if(model.appClosing)return;stateEtag=null;if(connected){toast('Соединение с Krolik Control потеряно: '+e.message,true);connected=false}$('#scan-status').textContent='Нет соединения';$('#next').disabled=true}finally{polling=false}}
document.addEventListener('DOMContentLoaded',()=>{poll();setInterval(poll,700)},{once:true});

// A streaming connection is tied to the window even when pagehide is not delivered.
(async function keepWindowConnection(){while(!model.appClosing){try{const r=await fetch('/api/lifetime',{headers:{'X-WinPilot-Token':token}});if(!r.ok)break;const reader=r.body.getReader();while(!(await reader.read()).done){}}catch{}if(!model.appClosing)await new Promise(resolve=>setTimeout(resolve,600))}})();
