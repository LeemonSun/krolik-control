'use strict';
pages.splice(pages.findIndex(p=>p[0]==='pc')+1,0,['firmware','BIOS и память','BIOS и память','Прошивка, оперативная память и доступные настройки платы.']);
icons.firmware='<rect x="5" y="5" width="14" height="14" rx="3"/><path d="M9 1v4m6-4v4M9 19v4m6-4v4M1 9h4m-4 6h4m14-6h4m-4 6h4M9 9h6v6H9z"/>';
groupNames.firmware='BIOS и память';
Object.assign(model,{firmwareBusy:false,firmwareLastAction:'',firmwareRequested:false,firmwareChoices:{}});
const firmwareNav=buildNav;
buildNav=function(){firmwareNav();if(!$('#nav [data-page="firmware"]'))$('#nav [data-page="pc"]')?.insertAdjacentHTML('afterend',navButton('firmware'))};
const firmwareRender=render;
render=function(){document.body.classList.toggle('firmware-readonly',model.page==='firmware'&&!count());firmwareRender()};
const fwBool=(v,yes='Включено',no='Выключено')=>v===true?yes:v===false?no:'Не предоставлено';
function fwDisabled(){return model.firmwareBusy||running()||anyScan()||model.state?.data.care?.running}
function fwTaskNote(name){const t=model.state.tasks[name];if(!t)return '';if(t.status==='running')return `<div class="scan-note"><span class="spinner"></span>${name==='firmware_action'?'Передаём подтверждённое действие…':'Читаем сведения BIOS…'}</div>`;if(t.status==='error')return `<div class="note error"><p>${esc(t.error)}</p><button class="secondary small" data-fw-scan>Обновить и проверить</button></div>`;return ''}
function fwGuide(data){
 const maker=(data.board?.[0]?.vendor||'').toLowerCase();
 if(/asus|asustek/.test(maker))return {brand:'ASUS',path:'Advanced Mode (F7) → Ai Tweaker / Extreme Tweaker → Ai Overclock Tuner',profile:'EXPO / XMP / DOCP'};
 if(/msi|micro-star/.test(maker))return {brand:'MSI',path:'EZ Mode → A-XMP / EXPO, либо Advanced Mode (F7) → OC',profile:'EXPO / A-XMP / XMP'};
 return {brand:'Ваша плата',path:'Раздел памяти или разгона в UEFI; расположение уточняется в руководстве вашей модели',profile:'XMP / EXPO, если профиль предусмотрен комплектом памяти и платой'};
}
function fwComparison(data){
 const b=data.saved?.baseline;if(!b)return '<p class="fw-muted">Сохраните текущие параметры перед изменением. После возвращения в Windows здесь будет сравнение.</p>';
 if(JSON.stringify(b.machine)!==JSON.stringify({board:data.board,system:data.system}))return '<p class="fw-muted">Снимок относится к другой плате или модели ПК. Сохраните новый снимок для сравнения.</p>';
 const previous=b.memory||[],same=previous.length===data.memory.length&&previous.every((m,i)=>{const n=data.memory[i];return n&&m.slot===n.slot&&m.part===n.part&&m.bytes===n.bytes});
 if(!same)return '<p class="fw-muted">Состав или порядок модулей изменился. Сравнение частот требует нового снимка.</p>';
 const rebooted=b.boot&&data.boot&&b.boot!==data.boot;
 return `<p class="fw-muted">Снимок: ${esc(new Date(b.time*1000).toLocaleString('ru-RU'))} · ${rebooted?'после новой загрузки Windows':'перезагрузка после снимка ещё не обнаружена'}</p><div class="fw-comparison">${previous.map((m,i)=>`<div><b>${esc(m.slot)}</b><span>${pcValue(m.configured,'MT/s')} <span aria-hidden="true">→</span> ${pcValue(data.memory[i].configured,'MT/s')}</span></div>`).join('')}</div><small class="fw-muted">Это сравнение сведений SMBIOS. Оно не доказывает стабильность разгона или включение конкретного профиля.</small>`;
}
function fwChange(data){
 const j=data.saved?.change;if(!j)return '';
 const status={prepared:'Запись могла начаться · нужна проверка после перезагрузки',accepted:'BIOS принял изменение · нужна перезагрузка',uncertain:'Результат записи не подтверждён · нужна проверка',verified:'После новой загрузки BIOS сообщает выбранное значение',mismatch:'После новой загрузки значение отличается от выбранного',unavailable:'После новой загрузки параметр недоступен для проверки'}[j.state]||'Сохранённое изменение';
 const row=data.settings.find(s=>s.name===j.name),canReturn=['verified','mismatch'].includes(j.state)&&row?.writable&&row.choices.includes(j.before)&&row.current!==j.before;
 return `<section class="fw-card fw-change" id="fw-change"><div class="fw-section-title"><h2>Последнее изменение</h2><span class="fw-label">${esc(status)}</span></div><p><b>${esc(j.title||j.name)}</b> · ${esc(j.before)} → ${esc(j.after)}</p>${j.observed?`<p class="fw-muted">Сейчас BIOS сообщает: ${esc(j.observed)}</p>`:''}<div class="fw-actions">${['prepared','accepted','uncertain'].includes(j.state)?`<button class="primary" data-fw-restart="windows" ${fwDisabled()?'disabled':''}>Перезагрузить и проверить</button>`:''}${canReturn?`<button class="secondary" data-fw-return ${fwDisabled()?'disabled':''}>Вернуть прежнее значение…</button>`:''}<span class="fw-muted">${model.state.demo?'Демонстрация · настройки не записывались':'Принятие прошивкой и фактическая работа после загрузки проверяются отдельно.'}</span></div></section>`;
}
function firmwareView(){
 const data=model.state.data.firmware,task=model.state.tasks.firmware;
 if(!data)return `<div class="fw-dashboard"><section class="fw-card fw-empty">${icon('firmware')}<h2>${task?.status==='running'?'Читаем прошивку и память…':'Определить возможности BIOS'}</h2><p>Модель платы, модули памяти и настройки, доступные из Windows.</p><button class="primary" data-fw-scan ${fwDisabled()?'disabled':''}>${task?.status==='running'?'Сканирование…':'Проверить возможности'}</button>${fwTaskNote('firmware')}</section></div>`;
 const board=data.board?.[0],bios=data.bios?.[0],guide=fwGuide(data),mem=data.memory||[],speeds=[...new Set(mem.map(m=>m.configured).filter(pcNumber))],canWrite=data.settings.some(s=>s.writable),memorySettings=data.settings.filter(s=>s.kind==='memory'),total=mem.reduce((n,m)=>n+(m.bytes||0),0)/1024**3;
 const disabled=fwDisabled(),pending=['accepted','prepared','uncertain'].includes(data.saved?.change?.state),lock=disabled||pending||!!data.warning||!model.state.info?.admin&&!model.state.demo;
 const protectedText=data.encryption===true?'Защита включена':data.encryption===false?'Защита не активна':'Состояние не прочитано';
 return `<div class="fw-dashboard"><div class="fw-toolbar"><span>${model.state.demo?'Демонстрационные данные':'Прочитано '+new Date(data.scanned_at*1000).toLocaleTimeString('ru-RU')}</span><button class="secondary small" data-fw-scan ${disabled?'disabled':''}>↻ Обновить сведения</button></div>${fwTaskNote('firmware')}${fwTaskNote('firmware_action')}
 ${data.warning?`<div class="note error">${esc(data.warning)}</div>`:''}
 <section class="fw-hero"><div class="fw-chip" aria-hidden="true">${icon('firmware')}<span>UEFI</span></div><div><span class="fw-kicker">ПЛАТА И ПРОШИВКА</span><h2>${esc([board?.vendor,board?.model].filter(Boolean).join(' ')||'Модель платы не предоставлена')}</h2><p>${esc([bios?.vendor,bios?.version,bios?.date].filter(Boolean).join(' · ')||'Версия BIOS не предоставлена')}</p><span class="fw-label">${data.mode==='uefi'?'Windows загружена через UEFI':data.mode==='legacy'?'Windows загружена через Legacy BIOS':'Способ загрузки не определён'}</span></div><button class="secondary" data-fw-restart="uefi" ${disabled||data.mode!=='uefi'?'disabled':''}>Перейти в UEFI…</button></section>
 <div class="fw-status-grid"><article><span>Secure Boot</span><b>${fwBool(data.secure_boot)}</b><small>Проверка доверенной загрузки</small></article><article><span>TPM</span><b>${data.tpm?.present===true?fwBool(data.tpm.ready,'Готов','Требует проверки'):data.tpm?.present===false?'Не обнаружен':'Не предоставлено'}</b><small>Состояние модуля защиты</small></article><article><span>Виртуализация CPU</span><b>${data.cpu.length?fwBool(data.cpu[0].virtualization):'Не предоставлено'}</b><small>По сведениям Windows</small></article><article><span>Шифрование диска Windows</span><b>${protectedText}</b><small>Ключи восстановления не считываются</small></article></div>
 ${fwChange(data)}
 <section class="fw-card"><div class="fw-section-title"><div><span class="fw-kicker">ОПЕРАТИВНАЯ ПАМЯТЬ</span><h2>${pcValue(total||null,'ГБ')} <span class="fw-muted">· ${speeds.length?speeds.map(s=>pcValue(s,'MT/s')).join(' / '):'Скорость не предоставлена'}</span></h2></div><button class="secondary small" data-fw-baseline ${disabled||!mem.length?'disabled':''}>Запомнить перед изменением</button></div>
 <div class="fw-memory">${mem.map((m,i)=>`<article class="fw-dimm" id="fw-dimm-${i}"><div class="fw-dimm-art" aria-hidden="true">${pcArt('ram')}</div><div><span class="fw-label">${esc(m.slot)}</span><b>${esc([m.vendor,m.part].filter(Boolean).join(' ')||'Модель модуля не предоставлена')}</b><small>${pcValue(m.bytes?m.bytes/1024**3:null,'ГБ')} · ${({24:'DDR3',26:'DDR4',34:'DDR5'})[m.type]||'Тип не предоставлен'} · ${pcValue(m.configured,'MT/s')}${m.voltage?' · '+pcValue(m.voltage/1000,'В',3):''}</small></div></article>`).join('')||'<p class="fw-muted">Windows не предоставила сведения о модулях.</p>'}</div>
 <p class="fw-muted fw-small">Скорость и напряжение сообщены SMBIOS. Поддержку EXPO/XMP и доступные частоты нельзя определить по одной текущей скорости.</p><details class="fw-details" id="fw-before-after"><summary>Сравнение до и после</summary>${fwComparison(data)}</details></section>
 <section class="fw-card"><div class="fw-section-title"><div><span class="fw-kicker">УПРАВЛЕНИЕ ИЗ ПРИЛОЖЕНИЯ</span><h2>${canWrite?'Доступны настройки производителя':'Проверка возможностей завершена'}</h2></div><span class="fw-label">${({none:'OEM-интерфейс не обнаружен',lenovo:'Lenovo WMI',hp:'HP CMI',dell:'Dell BIOS WMI'})[data.provider]}</span></div>
 <p class="fw-muted">${canWrite?'Выберите значение и подтвердите отдельное действие. BIOS-настройки не включаются в общую очередь Windows.':'Эта прошивка не предоставила доступных для записи пунктов. Список зависит от модели, прав доступа и защиты BIOS.'}</p>
 ${data.provider!=='none'&&data.password!==false?'<p class="note warning">Защита BIOS включена или её состояние не прочитано. Запись заблокирована; пароли в приложении не вводятся.</p>':''}
 ${!model.state.info?.admin&&!model.state.demo?'<p class="note">Для изменения доступных параметров запустите приложение от имени администратора.</p>':''}
 <div class="fw-setting-list">${data.settings.map((s,i)=>`<div class="fw-setting" id="fw-setting-${i}"><div><b>${esc(s.title)}</b><small>${esc(s.name)} · сейчас: ${esc(s.current)}</small>${!s.writable?'<small>Доступно только чтение</small>':''}</div><select aria-label="${esc(s.title)}" data-fw-select="${i}" ${lock||!s.writable?'disabled':''}><option value="" ${!model.firmwareChoices[s.name]?'selected':''}>${esc(s.current)} · сейчас</option>${s.choices.filter(c=>c!==s.current).map(c=>`<option value="${esc(c)}" ${model.firmwareChoices[s.name]===c?'selected':''}>${esc(c)}</option>`).join('')}</select><button class="secondary small" data-fw-set="${i}" ${lock||!s.writable?'disabled':''}>Выбрать…</button></div>`).join('')}</div>
 ${!memorySettings.some(s=>s.writable)?'<div class="fw-capability-note"><b>Профиль RAM через Windows не предоставлен</b><span>Кнопка EXPO/XMP появится, если поддерживаемый OEM-интерфейс вернёт такой параметр и допустимые значения. Сейчас настройка выполняется в UEFI по маршруту ниже.</span></div>':''}</section>
 <section class="fw-card"><div class="fw-section-title"><div><span class="fw-kicker">НАСТРОЙКА ПРОФИЛЯ RAM</span><h2>${esc(guide.brand)} · путь в прошивке</h2></div></div><ol class="fw-steps"><li><b>Сохраните снимок и подготовьте восстановление</b><p>Запомните текущие параметры кнопкой выше. Если диск защищён, убедитесь, что ключ восстановления доступен на другом устройстве.</p></li><li><b>${esc(guide.path)}</b><p>Найдите существующий профиль ${esc(guide.profile)}. Сверьте его с комплектом RAM и списком совместимости вашей платы; универсальной подходящей частоты нет.</p></li><li><b>Сохраните выбранное и проверьте после загрузки</b><p>Подтвердите только нужные изменения в UEFI. Первый запуск может занять больше времени из-за обучения памяти. Вернувшись, обновите этот раздел и сравните параметры.</p></li></ol><p class="fw-muted fw-small">Это ориентир для семейства плат. Модель и версия BIOS могут менять расположение пунктов. Приложение не определяет XMP/EXPO через чтение SPD.</p><div class="fw-actions"><button class="primary" data-fw-restart="uefi" ${disabled||data.mode!=='uefi'?'disabled':''}>Перезагрузить в UEFI…</button><button class="secondary" data-fw-test>Проверки производительности</button></div></section>
 <details class="fw-card fw-details" id="fw-limitations"><summary>Что стоит знать перед изменением</summary><p>Профиль памяти может вызвать нестабильность или неудачный запуск. Сначала изучите способ возврата настроек в руководстве именно вашей платы. Снимок в приложении сохраняет показания, а не полную резервную копию BIOS.</p><p>Короткий бенчмарк помогает сравнить производительность, но не заменяет длительный тест памяти. Если ПК перестал загружаться, приложение не сможет откатить прошивку.</p><p>Secure Boot, TPM, режим контроллера диска, порядок загрузки, напряжения и прошивка BIOS здесь не меняются. Поддержка определяется по возможностям Windows 10/11 x64; будущие версии Windows потребуют отдельных испытаний.</p></details></div>`;
}
pageRenderers.firmware=firmwareView;
async function fwScan(baseline=false){if(model.firmwareBusy)return;model.firmwareBusy=true;try{await api(baseline?'/api/firmware/baseline':'/api/firmware/scan',{});model.firmwareRequested=true;await poll()}finally{model.firmwareBusy=false;if(model.page==='firmware')render()}}
const firmwareVisit=visitPage;
visitPage=function(page,options){firmwareVisit(page,options);if(page==='firmware'&&!model.state?.data.firmware&&!taskRunning('firmware')&&!model.firmwareRequested)fwScan().catch(e=>toast(e.message,true))};
const firmwarePoll=poll;
poll=async function(){await firmwarePoll();if(model.hydrated&&model.page==='firmware'&&!model.state?.data.firmware&&!model.firmwareRequested&&!fwDisabled())fwScan().catch(e=>toast(e.message,true));const t=model.state?.tasks.firmware_action,marker=t&&t.status!=='running'?`${t.finished||t.started}:${t.status}`:'';if(marker&&marker!==model.firmwareLastAction&&!taskRunning('firmware')){try{await api('/api/firmware/scan',{});model.firmwareLastAction=marker}catch(e){toast(e.message,true)}}};
async function fwConfirm(body){
 if(fwDisabled())return;
 model.firmwareBusy=true;
 try{
  await flushWorkspace();
  const p=await api('/api/firmware/preview',body),restart=p.action==='restart';
  const title=restart?(p.target==='uefi'?'Перезагрузить ПК в UEFI?':'Перезагрузить ПК для проверки?'):'Передать настройку в BIOS?';
  const message=restart?'Сохраните документы и закройте программы. Windows получит запрос на перезагрузку без принудительного закрытия приложений.':`${p.title}: ${p.before} → ${p.value}. После принятия прошивкой потребуется перезагрузка.${p.provider==='lenovo'?' На Lenovo будут сохранены и другие уже подготовленные изменения BIOS; закройте остальные утилиты настройки.':''}`;
  const details=`${!restart?'<p>Прежнее значение будет записано в журнал. Автоматический откат при неудачном старте не гарантируется.</p>':''}${p.recovery_required?'<label class="inline-toggle"><input type="checkbox" id="fw-recovery-ack"> У меня есть доступ к ключу восстановления шифрования на другом устройстве</label>':''}${p.kind==='memory'?'<label class="inline-toggle"><input type="checkbox" id="fw-memory-ack"> Я сверил профиль с памятью и платой и знаю способ вернуть настройки, если ПК не запустится</label>':''}${p.demo?'<p class="fw-label">Демонстрация: BIOS и перезагрузка не изменяются.</p>':''}`;
  const promise=ask(title,message,details),yes=$('#confirm-yes');
  const check=()=>{yes.disabled=Boolean($('#fw-recovery-ack')&&!$('#fw-recovery-ack').checked||$('#fw-memory-ack')&&!$('#fw-memory-ack').checked)};
  $('#confirm-details').addEventListener('change',check);check();
  let ok;try{ok=await promise}finally{$('#confirm-details').removeEventListener('change',check);yes.disabled=false}
  if(!ok)return;
  await api('/api/firmware/apply',{token:p.token,confirmed:true,recovery_saved:$('#fw-recovery-ack')?.checked===true,memory_ack:$('#fw-memory-ack')?.checked===true});await poll();toast(restart?'Запрос принят. Сохраните работу перед перезагрузкой.':'Передаём выбранное значение в BIOS…');
 }finally{model.firmwareBusy=false;if(model.page==='firmware')render()}
}
document.addEventListener('click',async e=>{try{
 if(e.target.closest('[data-fw-scan]')){await fwScan();return}
 if(e.target.closest('[data-fw-baseline]')){if(model.state.data.firmware?.saved.baseline&&!await ask('Заменить снимок памяти?','Текущие показания станут новой точкой сравнения. Предыдущий снимок будет заменён.'))return;await fwScan(true);return}
 const restart=e.target.closest('[data-fw-restart]');if(restart){await fwConfirm({action:'restart',target:restart.dataset.fwRestart});return}
 const set=e.target.closest('[data-fw-set]');if(set){const i=Number(set.dataset.fwSet),s=model.state.data.firmware.settings[i],value=$(`[data-fw-select="${i}"]`)?.value;if(!value){toast('Сначала выберите новое значение');return}await fwConfirm({action:'setting',name:s.name,value});return}
 if(e.target.closest('[data-fw-return]')){const j=model.state.data.firmware.saved.change;await fwConfirm({action:'setting',name:j.name,value:j.before});return}
 if(e.target.closest('[data-fw-test]')){model.careTab='performance';navigate('care')}
}catch(err){toast(err.message,true)}});

document.addEventListener('change',e=>{const t=e.target;if(t.matches('[data-fw-select]')){const s=model.state.data.firmware?.settings[Number(t.dataset.fwSelect)];if(s){if(t.value)model.firmwareChoices[s.name]=t.value;else delete model.firmwareChoices[s.name]}}});
