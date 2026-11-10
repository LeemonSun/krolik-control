'use strict';
const identityAttributes=['data-install-record','data-session','data-mixer-volume','data-mixer-mute','data-tool','data-verification','data-startup-task','data-setting-row','data-item','data-layout-x','data-layout-y','data-startup','data-upgrade','data-audio-range','data-brightness-number','data-setting','data-number-setting','data-range-setting','data-audio-volume','data-audio-mute','data-brightness','data-driver-target','data-app','data-update','data-care-tab','data-care-run','data-care-tone','data-audio-tool','data-care-fix','data-care-play','data-care-undo','data-care-export','data-program-id','data-report-id'];
function elementKey(e){if(!e)return null;if(e.id)return '#'+CSS.escape(e.id);for(const a of identityAttributes)if(e.hasAttribute(a)){let key='['+a+'="'+CSS.escape(e.getAttribute(a))+'"]';if(e.dataset.endpoint)key+='[data-endpoint="'+CSS.escape(e.dataset.endpoint)+'"]';if(e.dataset.careReport)key+='[data-care-report="'+CSS.escape(e.dataset.careReport)+'"]';return key}return null}
function detailKey(e,i){return e.id||e.querySelector('summary')?.textContent+'|'+(e.closest('.device-row')?.querySelector('[data-driver-target]')?.dataset.driverTarget||i)}
function nodeKey(node){return node.nodeType===1?elementKey(node):null}
function compatibleNode(a,b){if(a.nodeType!==b.nodeType||a.nodeName!==b.nodeName)return false;const ka=nodeKey(a),kb=nodeKey(b);if(ka||kb)return ka===kb;if(a.nodeType===1)return (a.classList[0]||'')===(b.classList[0]||'');return true}
function patchElement(current,next){
 if(current.nodeType!==1){if(current.nodeValue!==next.nodeValue)current.nodeValue=next.nodeValue;return}
 const isDetails=current.tagName==='DETAILS',isInput=current.tagName==='INPUT';
 for(const attr of [...current.attributes])if(!next.hasAttribute(attr.name)&&!(isDetails&&attr.name==='open')&&!(current.hasAttribute('data-setting-row')&&attr.name==='hidden'))current.removeAttribute(attr.name);
 for(const attr of next.attributes)if(current.getAttribute(attr.name)!==attr.value)current.setAttribute(attr.name,attr.value);
 patchChildren(current,next);
 if(isInput){if(current.type!=='file'&&current.value!==next.value)current.value=next.value;if(current.checked!==next.checked)current.checked=next.checked}
 if(current.tagName==='TEXTAREA'&&current.value!==next.value)current.value=next.value;
 if(current.tagName==='SELECT'&&!current.multiple&&current.value!==next.value)current.value=next.value;
}
function patchChildren(current,next){
 const candidates=[...current.childNodes],used=new Set();let cursor=current.firstChild;
 for(const desired of [...next.childNodes]){
  let existing=cursor&&!used.has(cursor)&&compatibleNode(cursor,desired)?cursor:candidates.find(n=>!used.has(n)&&compatibleNode(n,desired));
  if(!existing){existing=desired.cloneNode(true);current.insertBefore(existing,cursor)}
  else{if(existing!==cursor)current.insertBefore(existing,cursor);patchElement(existing,desired)}
  used.add(existing);cursor=existing.nextSibling;
 }
 for(const node of candidates)if(!used.has(node)&&node.parentNode===current)current.removeChild(node);
}
function mountContent(html){
 const root=document.querySelector('#content');if(root._html===html)return;
 const active=document.activeElement,focus=root.contains(active)?elementKey(active):null,y=scrollY;
 let caret=null;try{caret=[active.selectionStart,active.selectionEnd,active.selectionDirection]}catch{}
 const selection=getSelection(),range=selection&&!selection.isCollapsed&&root.contains(selection.anchorNode)&&root.contains(selection.focusNode)?{anchor:selection.anchorNode,a:selection.anchorOffset,focus:selection.focusNode,f:selection.focusOffset}:null;
 const template=document.createElement('template');template.innerHTML=html;patchChildren(root,template.content);root._html=html;
 if(focus){const next=root.querySelector(focus);if(next&&!next.disabled){if(document.activeElement!==next)next.focus({preventScroll:true});if(caret&&caret[0]!==null)try{next.setSelectionRange(...caret)}catch{}}}
 if(range&&range.anchor.isConnected&&range.focus.isConnected){const max=n=>n.nodeType===3?n.length:n.childNodes.length;try{selection.setBaseAndExtent(range.anchor,Math.min(range.a,max(range.anchor)),range.focus,Math.min(range.f,max(range.focus)))}catch{}}
 if(scrollY!==y)window.scrollTo({top:y,behavior:'instant'});
}
