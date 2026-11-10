'use strict';
const textTools={
 json(text,compact=false){
  if(text.length>1000000)throw Error('Слишком большой текст: максимум 1 млн символов.');
  const tokens=text.match(/"(?:\\.|[^"\\])*"|[{}\[\],:]|true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/g);
  let depth=0;
  for(const token of tokens||[]){
   if(token==='{'||token==='['){if(++depth>128)throw Error('JSON: слишком много уровней вложенности. Максимум 128.');}
   else if(token==='}'||token===']')depth--;
  }
  JSON.parse(text); // Validate structure without serializing rounded JavaScript numbers.
  if(compact)return tokens.join('');
  let result='',level=0;
  const line=()=> '\n'+'  '.repeat(level);
  tokens.forEach((token,index)=>{
   if(token==='{'||token==='['){result+=token;level++;if(tokens[index+1]!=='}'&&tokens[index+1]!==']')result+=line();}
   else if(token==='}'||token===']'){level--;if(tokens[index-1]!=='{'&&tokens[index-1]!=='[')result+=line();result+=token;}
   else if(token===',')result+=','+line();
   else if(token===':')result+=': ';
   else result+=token;
   if(result.length>4000000)throw Error('Результат форматирования превышает 4 млн символов.');
  });return result;
 },
 base64(text,decode=false){
  if(text.length>1000000)throw Error('Слишком большой текст: максимум 1 млн символов.');
  if(decode){
   const clean=text.replace(/\s/g,'');
   if(!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(clean))throw Error('Некорректный Base64.');
   const bytes=Uint8Array.from(atob(clean),v=>v.charCodeAt(0));return new TextDecoder('utf-8',{fatal:true}).decode(bytes);
  }
  const bytes=new TextEncoder().encode(text);let binary='';
  for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
  return btoa(binary);
 },
 url(text,decode=false){
  if(text.length>1000000)throw Error('Слишком большой текст: максимум 1 млн символов.');
  return decode?decodeURIComponent(text):encodeURIComponent(text);
 },
 password(length=24,symbols=true){
  if(!Number.isInteger(length)||length<12||length>128)throw Error('Длина пароля: от 12 до 128 символов.');
  const sets=['abcdefghijkmnopqrstuvwxyz','ABCDEFGHJKLMNPQRSTUVWXYZ','23456789'];
  if(symbols)sets.push('!@#$%&*+-=?');
  const alphabet=sets.join('');
  function random(n){const bytes=new Uint8Array(1),limit=256-256%n;do{crypto.getRandomValues(bytes);}while(bytes[0]>=limit);return bytes[0]%n;}
  const chars=sets.map(set=>set[random(set.length)]);
  while(chars.length<length)chars.push(alphabet[random(alphabet.length)]);
  for(let i=chars.length-1;i>0;i--){const j=random(i+1);[chars[i],chars[j]]=[chars[j],chars[i]];}
  return chars.join('');
 }
};
if(typeof module!=='undefined')module.exports=textTools;
if(typeof document!=='undefined'){
 pages.push(['text-tools','Текст и пароли','Текст и пароли','JSON, кодирование и пароли — на этом компьютере.']);
 icons['text-tools']=icons.tools;
 productNavGroups.find(row=>row[0]==='utilities')[3].unshift('text-tools');
 Object.assign(model,{textToolTab:'json',textToolInput:'',textToolOutput:'',textToolError:'',passwordLength:24,passwordSymbols:true});
 pageRenderers['text-tools']=function(){return `<div class="product-tabs" role="group" aria-label="Инструменты текста">${[['json','JSON'],['encoding','Base64 / URL'],['password','Пароли']].map(([id,label])=>`<button class="${model.textToolTab===id?'primary':'secondary'}" data-text-tab="${id}">${label}</button>`).join('')}</div>
 <p class="muted">Текст и пароли не отправляются в сеть и не записываются в профили.</p>
 ${model.textToolTab==='password'?`<section class="card"><div class="toolbar"><label>Длина пароля<input id="password-length" type="number" min="12" max="128" value="${model.passwordLength}"></label><label class="inline-toggle"><input id="password-symbols" type="checkbox" ${model.passwordSymbols?'checked':''}>Специальные символы</label><button class="primary" data-text-action="password">Создать пароль</button></div></section>`:
 `<label class="text-tool-label" for="text-tool-input">Исходный текст</label><textarea id="text-tool-input" class="text-tool-area" spellcheck="false" maxlength="1000000" data-no-translate>${esc(model.textToolInput)}</textarea><div class="toolbar space-top">${(model.textToolTab==='json'?[['json','Форматировать JSON'],['compact','Сжать JSON']]:[['base64','В Base64'],['unbase64','Из Base64'],['url','Кодировать URL'],['unurl','Декодировать URL']]).map(([id,label])=>`<button class="secondary" data-text-action="${id}">${label}</button>`).join('')}</div>`}
 ${model.textToolError?`<p class="note error" role="alert">${esc(model.textToolError)}</p>`:''}
 <label class="text-tool-label space-top" for="text-tool-output">Результат</label><textarea id="text-tool-output" class="text-tool-area" readonly spellcheck="false" data-no-translate>${esc(model.textToolOutput)}</textarea><div class="toolbar space-top"><button class="secondary" data-text-copy ${!model.textToolOutput?'disabled':''}>Копировать результат</button><button class="text-btn" data-text-clear>Очистить поля</button></div>`;};
 document.addEventListener('input',e=>{if(e.target.id==='text-tool-input')model.textToolInput=e.target.value;if(e.target.id==='password-length')model.passwordLength=Number(e.target.value);});
 document.addEventListener('change',e=>{if(e.target.id==='password-symbols')model.passwordSymbols=e.target.checked;});
 document.addEventListener('click',async e=>{
  const button=e.target.closest('[data-text-tab],[data-text-action],[data-text-copy],[data-text-clear]');if(!button)return;
  try{
   if(button.dataset.textTab){model.textToolTab=button.dataset.textTab;model.textToolOutput='';model.textToolError='';render();return;}
   if(button.hasAttribute('data-text-clear')){model.textToolInput='';model.textToolOutput='';model.textToolError='';render();return;}
   if(button.hasAttribute('data-text-copy')){await navigator.clipboard.writeText(model.textToolOutput);toast('Результат скопирован');return;}
   model.textToolError='';const action=button.dataset.textAction,input=model.textToolInput;
   if(action==='json'||action==='compact')model.textToolOutput=textTools.json(input,action==='compact');
   else if(action==='base64'||action==='unbase64')model.textToolOutput=textTools.base64(input,action==='unbase64');
   else if(action==='url'||action==='unurl')model.textToolOutput=textTools.url(input,action==='unurl');
   else if(action==='password')model.textToolOutput=textTools.password(model.passwordLength,model.passwordSymbols);
   render();
  }catch(error){model.textToolError=error.message;model.textToolOutput='';render();}
 });
}
