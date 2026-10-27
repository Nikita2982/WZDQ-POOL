'use strict';
const paths = {
  grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  layers:'<path d="m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5"/>',
  heart:'<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',
  spark:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5ZM20 2v4M18 4h4"/>',
  'arrow-up-right':'<path d="M6 18 18 6M6 6h12v12"/>',
  'arrow-right':'<path d="M4 12h16m-6-6 6 6-6 6"/>',
  'arrow-left':'<path d="M20 12H4m6-6-6 6 6 6"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  shuffle:'<path d="M3 6h3l12 12h3M3 18h3L18 6h3m-4-3 4 3-4 3m0 6 4 3-4 3"/>',
  wave:'<path d="M3 10v4m4-8v12m5-16v20m5-16v12m4-8v4"/>',
  send:'<path d="m22 2-7 20-4-9-9-4 20-7ZM22 2 11 13"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/>',
  user:'<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
  download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  book:'<path d="M12 6c-3-2-7-2-10-1v15c3-1 7-1 10 1 3-2 7-2 10-1V5c-3-1-7-1-10 1Zm0 0v15"/>',
  play:'<path d="m9 5 11 7-11 7z"/>',
  youtube:'<rect x="2" y="5" width="20" height="14" rx="4"/><path d="m10 9 5 3-5 3z"/>',
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  sliders:'<path d="M4 7h5m4 0h7M4 17h9m4 0h3"/><circle cx="11" cy="7" r="2"/><circle cx="15" cy="17" r="2"/>',
  stop:'<rect x="5" y="5" width="14" height="14" rx="2"/>',
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.wave}</svg>`;
function hydrateIcons(root=document) { root.querySelectorAll('[data-icon]').forEach(el => {el.innerHTML=icon(el.dataset.icon);}); }
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={electronic:'Electronic',house:'House',rap:'Rap'};
const genreName=genre=>({...labels,dance_pop:'Dance Pop'}[genre]||genre);
const bpmLabels={low_double:'70–76 / 140–152',mid_low:'95–103',mid:'107–117',mid_high:'123–130'};
const state={page:'home',genre:'electronic',duration:30,bpm:'low_double',sets:[],current:null,user:{first_name:'DJ'},demo:false,local:false,loading:false,poll:null,toastTimer:null,counts:{},authenticated:false,deliveryEnabled:false};
const telegram=window.Telegram?.WebApp;
const initData=telegram?.initData || '';
const $=selector=>document.querySelector(selector);
function haptic(){try{telegram?.HapticFeedback?.selectionChanged();}catch{}}
function toast(message){clearTimeout(state.toastTimer);const el=$('#toast');el.textContent=message;el.hidden=false;state.toastTimer=setTimeout(()=>{el.hidden=true;},5000);}
async function api(path,options={}){
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),20000);
  const method=(options.method||'GET').toUpperCase();
  // Explicit JSON bodies avoid empty POST transport issues in browser tunnels.
  const body=options.body??(!['GET','HEAD'].includes(method)?'{}':undefined);
  try{
    const response=await fetch('/miniapp-api'+path,{...options,method,body,signal:controller.signal,cache:'no-store',headers:{'Content-Type':'application/json','X-Pinggy-No-Screen':'1',...(initData?{Authorization:'tma '+initData}:{}),...options.headers}});
    let data;
    try{data=JSON.parse(await response.text());if(data===null||typeof data!=='object')throw new Error();}
    catch{const error=new Error('Сервис соединения вернул другую страницу. Закрой Mini App и открой заново через бота.');error.status=502;throw error;}
    if(!response.ok){const error=new Error(typeof data.detail==='string'?data.detail:'Проверь параметры и попробуй ещё раз.');error.status=response.status;throw error;}
    return data;
  }catch(error){
    if(error.name==='AbortError')throw new Error('Сервер отвечает дольше обычного. Попробуй ещё раз.');
    if(error instanceof TypeError){const connectionError=new Error('Потеряно соединение с приложением. Закрой Mini App и открой заново через бота.');connectionError.status=0;throw connectionError;}
    throw error;
  }finally{clearTimeout(timeout);}
}

function showGate(error){$('#access-gate').hidden=false;$('#gate-title').textContent=error.status===403?'Твой пропуск в WZDQ Pool':'Не удалось подключиться';$('#gate-message').textContent=error.message;$('#subscribe-link').hidden=error.status!==403;}
async function bootstrap(){
  $('#access-gate').hidden=true;$('#generate-button').disabled=true;
  try{
    const data=await api('/bootstrap');state.user=data.user;state.local=!!data.local;state.deliveryEnabled=!!data.delivery_enabled;state.demo=false;state.authenticated=true;
    data.genres.forEach(item=>{state.counts[item.id]=item.count;});
    state.sets=await api('/sets');
  }catch(error){
    if(!initData&&error.status===401){state.demo=true;state.authenticated=false;state.counts={electronic:24,house:24,rap:24};}
    else {showGate(error);return;}
  }
  $('#mode-label').textContent=state.local?'НА КОМПЬЮТЕРЕ':state.demo?'ДЕМО':'В ТВОЁМ РИТМЕ';
  for(const genre of Object.keys(labels))$('#count-'+genre).textContent=(state.demo?'Демо · ':'')+(state.counts[genre]||0)+' треков';
  $('#preview-note').hidden=!(state.local||state.demo);
  if(state.local)$('#preview-note p').textContent='Локальная версия · Реальный каталог из отдельной копии базы. Собирай и сохраняй сеты здесь. Отправка в Telegram отключена.';
  const firstName=state.user.first_name||'DJ';
  document.querySelectorAll('.profile-name').forEach(el=>{el.replaceChildren(document.createTextNode(firstName));const small=document.createElement('small');small.textContent=state.local?'LOCAL DJ WORKSPACE':'WZDQ COMMUNITY';el.append(small);});
  document.querySelectorAll('.avatar').forEach(el=>{el.textContent=firstName.slice(0,2).toUpperCase();});
  $('#generate-button').disabled=false;restoreBuilder();updateCounts();navigate(location.hash.slice(1)||'home',false);
}
function updateCounts(){
  document.querySelectorAll('.saved-count').forEach(el=>{el.textContent=state.sets.length;});
  $('#stat-tracks').textContent=Object.values(state.counts).reduce((sum,n)=>sum+n,0).toLocaleString('ru-RU');
  $('#stat-sets').textContent=state.sets.length;
  $('#stat-favorites').textContent=state.sets.filter(row=>row.favorite).length;
  $('#greeting-name').textContent=`Привет, ${state.user.first_name||'DJ'} ✳`;
  const recent=state.sets.slice(0,2);$('#recent-sets').hidden=!recent.length;
  $('#recent-sets').innerHTML=recent.length?`<div class="section-heading"><h2>Вернуться к музыке</h2><button class="text-button" data-page="sets">Все сеты ${icon('arrow-right')}</button></div><div class="recent-grid">${recent.map(row=>`<button class="recent-card" data-set-id="${escapeHtml(row.id)}"><span class="history-art ${escapeHtml(row.genre)}">${icon('wave')}</span><span><strong>${escapeHtml(genreName(row.genre))} Session</strong><small>${row.tracks.length} треков · ${Math.round(row.total_duration_sec/60)} мин · ${formatDate(row.created_at)}</small></span>${icon('arrow-up-right')}</button>`).join('')}</div>`:'';
}
function updateBuilder(){
  $('#builder-summary').textContent=`${labels[state.genre]} · ${state.duration} минут${state.genre==='rap'?' · '+bpmLabels[state.bpm]+' BPM':''}`;
  try{localStorage.setItem('wzdq-builder',JSON.stringify({genre:state.genre,duration:state.duration,bpm:state.bpm}));}catch{}
}
function restoreBuilder(){
  try{const saved=JSON.parse(localStorage.getItem('wzdq-builder')||'null');if(saved&&labels[saved.genre]&&[30,60].includes(saved.duration)&&bpmLabels[saved.bpm]){state.genre=saved.genre;state.duration=saved.duration;state.bpm=saved.bpm;}}catch{}
  chooseGenre(state.genre);setDuration(state.duration);setBpm(state.bpm);
}

function navigate(page,updateHash=true){
  if(!['home','pool','youtube','knowledge','sets','favorites','profile','result'].includes(page))page='home';
  if(page==='result'&&!state.current)page='home';
  state.page=page;document.body.dataset.page=page;
  document.querySelectorAll('.page').forEach(el=>{el.hidden=el.id!=='page-'+page;});
  document.querySelectorAll('nav [data-page]').forEach(el=>el.classList.toggle('active',el.dataset.page===page||(page==='result'&&el.dataset.page==='sets')));
  document.querySelectorAll('nav [data-page]').forEach(el=>{if(el.classList.contains('active'))el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
  if(page==='sets'||page==='favorites')renderHistory(page);
  if(page==='profile')renderProfile();
  if(page==='pool')loadPool();
  if(page==='youtube'&&typeof youtubeLoad==='function')youtubeLoad();
  if(page==='knowledge'&&typeof knowledgeLoad==='function')knowledgeLoad();
  if(page!=='knowledge'&&typeof knowledgeStop==='function')knowledgeStop();
  if(page==='result')renderResult();
  if(updateHash&&location.hash!=='#'+page)history.pushState(null,'','#'+page);
  window.scrollTo({top:0,behavior:'instant'});
  try{if(page==='home')telegram?.BackButton?.hide();else telegram?.BackButton?.show();}catch{}
}
function chooseGenre(genre){state.genre=genre;document.querySelectorAll('[data-genre]').forEach(el=>{el.classList.toggle('selected',el.dataset.genre===genre);el.setAttribute('aria-pressed',String(el.dataset.genre===genre));});$('#bpm-options').hidden=genre!=='rap';updateBuilder();haptic();}
function setDuration(duration){state.duration=duration;document.querySelectorAll('[data-duration]').forEach(el=>{el.classList.toggle('active',Number(el.dataset.duration)===duration);el.setAttribute('aria-pressed',String(Number(el.dataset.duration)===duration));});updateBuilder();haptic();}
function setBpm(bpm){state.bpm=bpm;document.querySelectorAll('[data-bpm]').forEach(el=>{el.classList.toggle('active',el.dataset.bpm===bpm);el.setAttribute('aria-pressed',String(el.dataset.bpm===bpm));});updateBuilder();haptic();}
function formatTime(seconds){return `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;}
function formatDate(value){return value?new Date(value.endsWith('Z')||/[+-]\d\d:\d\d$/.test(value)?value:value+'Z').toLocaleDateString('ru-RU',{day:'numeric',month:'short'}):'Сегодня';}
function saveCurrent(row){state.current=row;const at=state.sets.findIndex(item=>item.id===row.id);if(at<0)state.sets.unshift(row);else state.sets[at]=row;updateCounts();}
function demoSet(){
  const duration=state.duration;const count=duration===30?16:31;const pool=['After Hours','Night Circuit','Into The Groove','Velvet Room','No Sleep','Under The Lights','Slow Motion','Out Of Focus','Pressure','First Light','On The Floor','Late Checkout','Stay With Me','Daydream','The Other Side','Back Again'];
  const tracks=Array.from({length:count},(_,i)=>({id:i+1,title:pool[i%pool.length]+(i>=16?' (Dub Mix)':''),artist:['WZDQ Selection','Local Frequency','Night People','Pool Residents'][i%4],bpm:state.genre==='rap'?(state.bpm==='low_double'?72:state.bpm==='mid_low'?99:state.bpm==='mid'?112:126):122+(i%6),camelot_key:`${(Math.floor(i/3)+5)%12+1}A`,duration_sec:225+(i%4)*8}));
  return {id:'demo-'+Date.now(),genre:state.genre,duration,bpm_bucket:state.genre==='rap'?state.bpm:null,tracks,total_duration_sec:tracks.reduce((n,t)=>n+Math.floor(t.duration_sec/2),0),actual_duration_sec:tracks.reduce((n,t)=>n+t.duration_sec,0),status:'ready',sent_count:0,favorite:false,created_at:new Date().toISOString()};
}
async function generate(previous=null){
  if(state.loading)return;
  state.loading=true;$('#generate-label').textContent='Собираем…';$('#generate-button').setAttribute('aria-busy','true');$('#generate-button').disabled=true;$('#generate-button').classList.add('loading');
  const body={genre:state.genre,duration:state.duration,bpm_bucket:state.genre==='rap'?state.bpm:null,previous_set_id:previous};
  toast('Подбираем треки по BPM, тональности и энергии…');haptic();
  try{
    const row=state.demo?demoSet():await api('/sets',{method:'POST',body:JSON.stringify(body)});
    saveCurrent(row);navigate('result');$('#toast').hidden=true;
  }catch(error){toast(error.message);if(error.status===401||error.status===403)showGate(error);}
  finally{state.loading=false;$('#generate-label').textContent='Собрать сет';$('#generate-button').removeAttribute('aria-busy');$('#generate-button').disabled=false;$('#generate-button').classList.remove('loading');}
}
function resultStatus(row){
  const names={sending:'Треки отправляются в Telegram',completed:'Все треки доставлены в Telegram',partial:'Доставлена часть треков',failed:'Не удалось доставить треки',cancelled:'Отправка остановлена',interrupted:'Отправка прервалась при перезапуске'};
  if(row.status==='ready')return '';
  const count=row.sent_count||0;const total=row.tracks.length;
  return `<div class="delivery-status"><strong>${names[row.status]||'Статус отправки'}</strong><p>Доставлено ${count} из ${total} треков.${['partial','failed','interrupted'].includes(row.status)?' Проверь сообщения в чате. Можно собрать новый сет.':''}</p><div class="progress-track"><div class="progress-fill" style="width:${Math.min(100,count/total*100)}%"></div></div>${row.status==='sending'?'<button class="secondary" data-action="cancel">'+icon('stop')+'Остановить отправку</button>':''}</div>`;
}
function renderResult(){
  const row=state.current;if(!row)return;
  const total=row.tracks.length;const bpms=row.tracks.map(t=>t.bpm).filter(Number.isFinite);
  const bpmRange=bpms.length?`${Math.round(Math.min(...bpms))}–${Math.round(Math.max(...bpms))} BPM`:'';
  $('#page-result').innerHTML=`<button class="back-button" data-page="home">${icon('arrow-left')}К новому сету</button><div class="result-top"><div class="result-cover ${escapeHtml(row.genre)}">${icon('wave')}</div><div class="result-info"><p class="eyebrow">${state.demo?'DEMO SELECTION':state.local?'LOCAL SELECTION':'YOUR NEXT SET'} / ${formatDate(row.created_at)}</p><h1>${labels[row.genre]} Session</h1><div class="set-meta">${total} треков · ${Math.round(row.total_duration_sec/60)} мин сета · ${bpmRange}</div></div></div><div class="set-actions">${!state.deliveryEnabled?`<button class="primary" data-action="export">${icon('download')}Скачать треклист</button>`:`<button class="primary" data-action="deliver" ${row.status!=='ready'?'disabled':''}>${icon('send')}${row.status==='ready'?'Получить треки в чат':row.status==='sending'?'Отправляем треки…':row.status==='completed'?'Треки отправлены в чат':'Проверь статус отправки'}</button>`}<button class="secondary ${row.favorite?'saved':''}" data-action="favorite" aria-pressed="${!!row.favorite}">${icon('heart')}${row.favorite?'В избранном':'Сохранить'}</button><button class="secondary" data-action="repeat">${icon('shuffle')}Ещё вариант</button></div>${resultStatus(row)}<div class="mix-note">${state.demo?'Демонстрационные треки. ':''}Тайминг сета: 50% длительности каждого трека. Полная длина аудио — ${Math.round(row.actual_duration_sec/60)} мин.${row.total_duration_sec<row.duration*60?' Для выбранных параметров нашлось меньше совместимых треков.':''}${!state.deliveryEnabled?' Доступен экспорт треклиста. Отправка аудио пока отключена.':''}</div><div class="track-list"><div class="track-row track-head"><span>#</span><span>ТРЕК / ИСПОЛНИТЕЛЬ</span><span>BPM</span><span>KEY</span><span class="track-time">ВРЕМЯ</span></div>${row.tracks.map((track,i)=>`<div class="track-row"><span class="track-number">${String(i+1).padStart(2,'0')}</span><div class="track-name">${escapeHtml(track.title)}<small>${escapeHtml(track.artist||'Unknown artist')}</small></div><span class="track-bpm">${Math.round(track.bpm||0)}</span><span class="key-badge">${escapeHtml(track.camelot_key)}</span><span class="track-time">${formatTime(track.duration_sec||0)}</span></div>`).join('')}</div><footer class="page-footer"><span>CURATED BY YOU · MIXED WITH WZDQ</span><span>${total} TRACKS / ${row.duration} MIN SESSION</span></footer>`;
  if(row.status==='sending'&&!state.poll)schedulePoll(row.id);
}
function renderHistory(page){
  const rows=state.sets.filter(row=>page!=='favorites'||row.favorite);
  const favorite=page==='favorites';
  $('#page-'+page).innerHTML=`<div class="page-heading"><p class="eyebrow">YOUR PERSONAL COLLECTION</p><h1>${favorite?'Только любимое.':'Твои сеты.'}</h1><p>${favorite?'Звук, к которому хочется вернуться.':'Сохраняем каждую подборку. Чтобы твой следующий сет был под рукой.'}</p></div>${!rows.length?`<div class="empty-state">${icon(favorite?'heart':'layers')}<h2>${favorite?'Здесь будет твой любимый звук':'Твоя история ещё впереди'}</h2><p>${favorite?'Нажми «Сохранить» на готовом сете — он появится здесь.':'Выбери свой звук и собери первый сет. Он автоматически появится в коллекции.'}</p><button class="primary" data-page="home">Собрать первый сет ${icon('arrow-right')}</button></div>`:`<div class="history-grid">${rows.map(row=>`<button class="history-card" data-set-id="${escapeHtml(row.id)}"><div class="history-art ${escapeHtml(row.genre)}">${icon('wave')}</div><div><h3>${labels[row.genre]} Session ${row.favorite?'♡':''}</h3><p>${row.tracks.length} треков · ${Math.round(row.total_duration_sec/60)} мин</p><p>${formatDate(row.created_at)}${row.bpm_bucket?' · '+bpmLabels[row.bpm_bucket]:''}</p></div>${icon('arrow-up-right')}</button>`).join('')}</div>`}`;
}
function renderProfile(){if(typeof profileLoad==='function')profileLoad();}

async function toggleFavorite(){const row=state.current;try{const updated=state.demo?{...row,favorite:!row.favorite}:await api(`/sets/${row.id}/favorite`,{method:'PATCH',body:JSON.stringify({favorite:!row.favorite})});saveCurrent(updated);renderResult();haptic();toast(updated.favorite?'Сет добавлен в избранное':'Сет убран из избранного');}catch(error){toast(error.message);}}
function exportTracklist(){
  const row=state.current;if(!row)return;
  const text=`WZDQ POOL — ${labels[row.genre]} Session\n${row.tracks.length} tracks / ${Math.round(row.total_duration_sec/60)} min DJ timing\n\n`+row.tracks.map((t,i)=>`${String(i+1).padStart(2,'0')}. ${t.artist?t.artist+' — ':''}${t.title} | ${Math.round(t.bpm)} BPM | ${t.camelot_key} | ${formatTime(t.duration_sec)}`).join('\n');
  const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download=`WZDQ-${labels[row.genre]}-${row.duration}min.txt`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Треклист скачан');
}
async function deliver(){
  if(!state.current||state.local||state.demo)return;
  const button=$('[data-action="deliver"]');if(button)button.disabled=true;
  try{await api(`/sets/${state.current.id}/deliver`,{method:'POST'});state.current.status='sending';renderResult();schedulePoll(state.current.id);toast('Отправляем аудиотреки в чат с ботом. Можно свернуть приложение.');}catch(error){toast(error.message);renderResult();}
}
function schedulePoll(id){clearTimeout(state.poll);state.poll=setTimeout(async()=>{state.poll=null;try{const row=await api(`/sets/${id}`);const currentId=state.current?.id;const at=state.sets.findIndex(item=>item.id===id);if(at>=0)state.sets[at]=row;if(currentId===id){state.current=row;if(state.page==='result')renderResult();}if(row.status==='sending')schedulePoll(id);else toast(row.status==='completed'?'Все треки доставлены':`Отправка завершена: ${row.sent_count} из ${row.tracks.length}`);}catch(error){toast(error.message);}},2500);}
document.addEventListener('click',async event=>{
  const button=event.target.closest('button,a');if(!button)return;
  if(button.matches('a[href="#home"]')){event.preventDefault();navigate('home');return;}
  if(button.dataset.page){navigate(button.dataset.page);haptic();return;}
  if(button.dataset.genre){chooseGenre(button.dataset.genre);return;}
  if(button.dataset.duration){setDuration(Number(button.dataset.duration));return;}
  if(button.dataset.bpm){setBpm(button.dataset.bpm);return;}
  if(button.dataset.setId){state.current=state.sets.find(row=>row.id===button.dataset.setId);navigate('result');return;}
  if(button.hasAttribute('data-pool-genre')){$('#pool-genre').value=button.dataset.poolGenre;loadPool();return;}
  if(button.id==='toggle-filters'){const expanded=button.getAttribute('aria-expanded')!=='true';button.setAttribute('aria-expanded',String(expanded));$('#pool-advanced').hidden=!expanded;return;}
  if(button.dataset.action==='pool-retry'){loadPool(poolOffset);return;}
  if(button.dataset.action==='focus-builder'){$('#genre-grid').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});return;}
  if(button.id==='pool-prev'){loadPool(Math.max(0,poolOffset-40));return;}
  if(button.id==='pool-next'){loadPool(poolOffset+40);return;}
  if(button.dataset.action==='pool-build'){const genre=$('#pool-genre').value;if(labels[genre])chooseGenre(genre);navigate('home');$('#builder-title').scrollIntoView({block:'center'});return;}
  if(button.id==='generate-button'){await generate();return;}
  if(button.id==='retry-auth'){await bootstrap();return;}
  const action=button.dataset.action;
  if(action==='favorite')await toggleFavorite();
  if(action==='export')exportTracklist();
  if(action==='deliver')await deliver();
  if(action==='repeat'){const row=state.current;chooseGenre(row.genre);setDuration(row.duration);if(row.bpm_bucket)setBpm(row.bpm_bucket);button.disabled=true;try{await generate(row.id);}finally{button.disabled=false;}}
  if(action==='cancel'){button.disabled=true;try{await api(`/sets/${state.current.id}/cancel`,{method:'POST'});toast('Остановим после текущего трека');}catch(error){toast(error.message);}finally{button.disabled=false;}}
});
let poolOffset=0, poolRequest=0, poolSearchTimer=null;
for(let n=1;n<=12;n++)for(const mode of ['A','B'])$('#pool-key').add(new Option(`${n}${mode}`,`${n}${mode}`));
async function loadPool(offset=0){
  const requestId=++poolRequest;
  const params=new URLSearchParams();
  for(const [key,value] of new FormData($('#pool-filters')))if(value)params.set(key,value);
  params.set('offset',offset);params.set('limit',40);
  clearTimeout(poolSearchTimer);
  const activeFilters=['genre','bpm_min','bpm_max','key'].filter(key=>params.has(key)).length;$('#filter-count').textContent=activeFilters;$('#filter-count').hidden=!activeFilters;
  $('#pool-count').textContent='Ищем твой звук…';
  $('#pool-results').setAttribute('aria-busy','true');$('#pool-results').innerHTML='<div class="pool-skeleton" aria-hidden="true">'+Array.from({length:5},()=>'<div><i></i><span></span><b></b></div>').join('')+'</div>';
  $('#pool-prev').disabled=true;$('#pool-next').disabled=true;
  try{
    if(state.demo){$('#pool-results').innerHTML='<div class="empty-state"><h2>Каталог доступен в локальном приложении</h2><p>Открой приложение с настоящей базой треков.</p></div>';$('#pool-count').textContent='Демонстрационный режим';return;}
    const data=await api('/tracks?'+params);
    if(requestId!==poolRequest)return;
    poolOffset=offset;
    $('#pool-chips').innerHTML=[{id:'',name:'Вся музыка'},...data.genres.map(g=>({id:g.id,name:genreName(g.id)}))].map(g=>`<button type="button" class="pool-chip ${$('#pool-genre').value===g.id?'active':''}" data-pool-genre="${escapeHtml(g.id)}" aria-pressed="${$('#pool-genre').value===g.id}">${escapeHtml(g.name)}</button>`).join('');
    if($('#pool-genre').options.length===1)data.genres.forEach(g=>$('#pool-genre').add(new Option(`${genreName(g.id)} · ${g.count}`,g.id)));
    $('#pool-count').textContent=`Найдено треков: ${data.total.toLocaleString('ru-RU')}`;
    $('#pool-page').textContent=data.total?`${offset+1}–${offset+data.tracks.length} из ${data.total}`:'0 треков';
    $('#pool-prev').disabled=offset===0;$('#pool-next').disabled=offset+data.tracks.length>=data.total;
    $('#pool-results').innerHTML=data.tracks.length?`<div class="track-list"><div class="track-row track-head"><span>#</span><span>ТРЕК / ИСПОЛНИТЕЛЬ</span><span>BPM</span><span>KEY</span><span class="track-time">ВРЕМЯ</span></div>${data.tracks.map((t,i)=>`<div class="track-row"><span class="track-number">${offset+i+1}</span><div class="track-name">${escapeHtml(t.title)}<small>${escapeHtml(t.artist||'Исполнитель не указан')} · ${escapeHtml(genreName(t.genre))}</small></div><span class="track-bpm">${t.bpm?Math.round(t.bpm):'—'}</span><span class="key-badge">${escapeHtml(t.camelot_key||'—')}</span><span class="track-time">${t.duration_sec?formatTime(t.duration_sec):'—'}</span></div>`).join('')}</div>`:'<div class="empty-state"><h2>Треки не найдены</h2><p>Попробуй изменить фильтры или сбросить поиск.</p></div>';
  }catch(error){if(requestId!==poolRequest)return;$('#pool-count').textContent='Не удалось загрузить музыку';$('#pool-results').innerHTML=`<div class="empty-state"><h2>Давай ещё раз?</h2><p>${escapeHtml(error.message)}</p><button class="primary" data-action="pool-retry">Повторить загрузку</button></div>`;$('#pool-page').textContent='';}
  finally{if(requestId===poolRequest)$('#pool-results').removeAttribute('aria-busy');}
}
$('#pool-filters').addEventListener('submit',event=>{event.preventDefault();loadPool();});
$('#pool-filters').addEventListener('reset',()=>{queueMicrotask(()=>loadPool());});
$('#pool-filters').addEventListener('input',event=>{if(event.target.name==='q'&&!event.isComposing){clearTimeout(poolSearchTimer);poolSearchTimer=setTimeout(()=>loadPool(),350);}});
$('#pool-genre').addEventListener('change',()=>loadPool());
document.addEventListener('pointerdown',event=>{const button=event.target.closest('button');if(!button||button.disabled)return;try{telegram?.HapticFeedback?.impactOccurred('light');}catch{}if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;const rect=button.getBoundingClientRect();const wave=document.createElement('span');wave.className='press-wave';wave.setAttribute('aria-hidden','true');wave.style.left=(event.clientX-rect.left)+'px';wave.style.top=(event.clientY-rect.top)+'px';button.append(wave);wave.addEventListener('animationend',()=>wave.remove(),{once:true});});
window.addEventListener('popstate',()=>navigate(location.hash.slice(1),false));
window.addEventListener('online',()=>{if($('#access-gate').hidden===false)bootstrap();});
hydrateIcons();$('#year').textContent=new Date().getFullYear();
try{telegram?.ready();telegram?.expand();telegram?.setHeaderColor('#120e17');telegram?.setBackgroundColor('#120e17');telegram?.BackButton?.onClick(()=>navigate('home'));}catch{}
bootstrap();
