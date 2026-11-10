'use strict';
pages.push(['archives','ZIP-архивы','ZIP-архивы','Просмотр, упаковка и распаковка без перезаписи файлов.']);
icons.archives=icons.tools;
productNavGroups.find(row=>row[0]==='utilities')[3].unshift('archives');
pageRenderers.archives=function(){
 const selection=toolState().selection,p=model.state.data.archive_preview,result=model.state.data.archive_action;
 const busy=running()||anyScan();
 return `<section class="card"><h2>Работа с ZIP</h2><div class="toolbar"><button class="secondary small" data-archive-app="7-Zip">7-Zip</button><button class="secondary small" data-archive-app="WinRAR">WinRAR</button><small>Для RAR и 7z можно установить архиватор. WinRAR — пробная версия на 40 дней.</small></div><p>Результат сохраняется рядом с выбранным объектом. Существующие файлы не заменяются.</p><div class="toolbar"><button class="secondary" data-archive-pick="file" ${busy?'disabled':''}>Выбрать ZIP</button><button class="secondary" data-archive-pick="folder" ${busy?'disabled':''}>Выбрать папку</button></div><p data-no-translate>${esc(selection?.path||'')}</p><div class="toolbar space-top"><button class="secondary" data-archive-preview="inspect" ${busy||selection?.kind!=='file'?'disabled':''}>Содержимое ZIP</button><button class="secondary" data-archive-preview="extract" ${busy||selection?.kind!=='file'?'disabled':''}>Подготовить распаковку</button><button class="secondary" data-archive-preview="create" ${busy||selection?.kind!=='folder'?'disabled':''}>Подготовить ZIP</button></div></section>
 ${taskNote('archive_preview')}${taskNote('archive_action')}
 ${p?`<section class="card space-top"><h2 data-no-translate>${esc(p.name)}</h2>${p.entries!==null?`<p>${p.entries} объектов · ${productSize(p.bytes)}</p>`:''}${p.items?productTable(['Файл','Размер'],p.items.map(row=>[`<span data-no-translate>${esc(row.name)}</span>`,productSize(row.size)])):''}${p.action!=='inspect'?`<button class="primary space-top" data-archive-run="${esc(p.token)}" ${busy?'disabled':''}>${p.action==='create'?'Создать ZIP':'Распаковать в новую папку'}</button>`:''}</section>`:''}
 ${result?`<section class="card space-top"><h2>${esc(result.message)}</h2><p data-no-translate>${esc(result.destination||'')}</p></section>`:''}
 ${model.state.tasks.archive_action?.status==='running'?'<button class="secondary space-top" data-archive-cancel>Отменить операцию</button>':''}
 <p class="muted space-top">ZIP: до 10 000 объектов, до 2 ГиБ после распаковки, до 512 МиБ на файл. Зашифрованные ZIP, 7z и RAR пока не поддерживаются.</p>`;
};
document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-archive-app],[data-archive-pick],[data-archive-preview],[data-archive-run],[data-archive-cancel]');if(!button)return;
 try{
  if(button.dataset.archiveApp){model.softwareTab='catalog';model.appQuery=button.dataset.archiveApp;navigate('apps');render();return;}
  if(button.dataset.archivePick){await api('/api/tools/start',{kind:button.dataset.archivePick==='file'?'pick_file':'pick_folder'});}
  else if(button.dataset.archivePreview){await api('/api/archive/preview',{action:button.dataset.archivePreview,selection:toolState().selection?.token});}
  else if(button.dataset.archiveRun){if(await ask('Выполнить операцию ZIP?','Будет создан новый файл или новая папка рядом с выбранным объектом. Существующие файлы останутся.'))await api('/api/archive/run',{token:button.dataset.archiveRun,confirmed:true});}
  else await api('/api/archive/cancel',{});
  await poll();
 }catch(error){toast(error.message,true);}
});
