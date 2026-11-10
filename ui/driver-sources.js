'use strict';
model.driverSourceMode='vendor';
model.driverVendorQuery='';
model.driverShowAll=false;
const driverBuildNav=buildNav;
buildNav=function(){
 driverBuildNav();
 const nav=document.querySelector('#nav');
 if(!nav.querySelector('.nav-settings'))nav.insertAdjacentHTML('beforeend',`<div class="nav-settings">${navButton('preferences')}</div>`);
};
const sourceDrivers=drivers;
drivers=function(){
 const tabs=`<div class="product-tabs driver-tabs" role="group" aria-label="Источник драйверов"><button class="${model.driverSourceMode==='vendor'?'primary':'secondary'}" data-driver-source-mode="vendor">От производителя</button><button class="${model.driverSourceMode==='windows'?'primary':'secondary'}" data-driver-source-mode="windows">Через Windows</button></div>`;
 if(model.driverSourceMode==='windows')return tabs+sourceDrivers();
 const sources=model.state.data.driver_sources||[],query=model.driverVendorQuery.trim().toLowerCase();
 const filtered=sources.filter(s=>[s.name,s.scope,typeof translatedText==='function'?translatedText(s.scope):''].join(' ').toLowerCase().includes(query));
 const items=filtered.filter(s=>query||model.driverShowAll||s.recommended||['amd','intel','nvidia'].includes(s.id));
 const task=model.state.tasks.driver_download,busy=task?.status==='running',ready=model.state.data.driver_download;
 const locked=running()||anyScan()||model.state.data.care?.running;
 return tabs+`<section class="driver-intro"><div><h2>Официальные драйверы</h2><p>Официальные сайты и установщики производителей. Для ноутбука сначала проверьте поддержку его марки.</p></div><span class="source-badge">Официальные источники</span></section>
 <div class="note">Для неизвестного устройства откройте список оборудования: там доступны модель и Hardware ID. Универсальный драйвер по одному названию не подбирается.</div>
 <div class="toolbar"><input id="driver-vendor-query" type="search" value="${esc(model.driverVendorQuery)}" placeholder="Производитель: AMD, Intel, ASUS…" aria-label="Поиск производителя"><button class="secondary" data-driver-source-mode="windows">Список устройств</button></div>
 ${taskNote('driver_download')}${taskNote('driver_vendor_action')}
 ${busy?`<div class="note"><span class="spinner"></span> Скачиваем и проверяем установщик… <button class="text-btn" data-driver-download-cancel>Отменить загрузку</button></div>`:''}
 ${ready?.id?`<section class="driver-ready"><div><b>${esc(ready.publisher)}</b><p>Подпись проверена · ${productSize(ready.size)}</p><details><summary>Сведения о файле</summary><small class="driver-file-hash">SHA-256: ${esc(ready.sha256)}</small><p>${esc(ready.url)}</p></details></div><button class="primary" data-driver-vendor-launch="${esc(ready.id)}" ${locked?'disabled':''}>Открыть установщик</button></section>`:''}
 <div class="driver-source-grid">${items.map(s=>`<article class="driver-source-card"><div class="driver-source-heading"><span class="vendor-monogram" aria-hidden="true">${esc(s.name.slice(0,2).toUpperCase())}</span><div><h3>${esc(s.name)}</h3><small>${esc(s.scope)}</small></div>${s.recommended?'<span class="badge">Есть на этом ПК</span>':''}</div><small class="official-domain">${esc(new URL(s.url).hostname)}</small><div class="driver-source-actions">${s.can_download?`<button class="primary small" data-driver-vendor-download="${esc(s.id)}" ${locked?'disabled':''}>Скачать установщик</button>`:''}<button class="secondary small" data-driver-source="${esc(s.id)}">Официальный сайт ↗</button></div></article>`).join('')||empty('Производитель не найден','Измените название или найдите марку вашего ПК.')}</div>
 ${!query?`<button class="secondary space-top" data-driver-show-all>${model.driverShowAll?'Свернуть список':'Показать всех производителей'}</button>`:''}
 <p class="driver-footnote">Установщики AMD и Intel сами определяют поддерживаемое оборудование. Для остальных марок открывается раздел поддержки. Скачивание не запускает установку.</p>`;
};
document.addEventListener('input',e=>{if(e.target.id==='driver-vendor-query'){model.driverVendorQuery=e.target.value;render();}});
document.addEventListener('click',async e=>{
 const button=e.target.closest('[data-driver-source-mode],[data-driver-source],[data-driver-vendor-download],[data-driver-vendor-launch],[data-driver-download-cancel],[data-driver-show-all]');
 if(!button)return;
 try{
  if(button.hasAttribute('data-driver-show-all')){model.driverShowAll=!model.driverShowAll;render();return;}
  if(button.dataset.driverSourceMode){model.driverSourceMode=button.dataset.driverSourceMode;render();if(model.driverSourceMode==='windows'&&!model.state.tasks.drivers)await perform('drivers');return;}
  if(button.dataset.driverSource){await api('/api/driver-source/open',{vendor:button.dataset.driverSource});return;}
  if(button.hasAttribute('data-driver-download-cancel')){await api('/api/driver-source/cancel',{});return;}
  if(button.dataset.driverVendorDownload){
   const vendor=button.dataset.driverVendorDownload,name=model.state.data.driver_sources.find(s=>s.id===vendor)?.name||vendor;
   if(await ask('Скачать установщик '+name+'?','Файл будет загружен с сайта производителя. Перед запуском проверим цифровую подпись и издателя. Установка сама не начнётся.')){await api('/api/driver-source/download',{vendor,confirmed:true});await poll();}
  }
  if(button.dataset.driverVendorLaunch&&await ask('Открыть установщик производителя?','Откроется отдельное окно AMD или Intel. Установщик может запросить права администратора. Вы сами выбираете, какие обновления ставить.')){await api('/api/driver-source/launch',{id:button.dataset.driverVendorLaunch,confirmed:true});await poll();}
 }catch(error){toast(error.message,true);}
});
