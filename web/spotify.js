'use strict';
const spotify={url:'',canonicalUrl:null,mediaType:null,metadata:null,download:null,currentTracks:[],available:false,loading:false,polling:false,pollTimer:null,expiresAt:0,requestId:0,deliveryByTrack:{},activeDeliveryTrackId:null};
function normalizeSpotifyUrl(value){
  try{
    const url=new URL(value.trim());
    if(url.protocol!=='https:'||url.username||url.password||url.port||!['open.spotify.com','www.open.spotify.com'].includes(url.hostname.toLowerCase()))return null;
    const parts=url.pathname.split('/').filter(part=>part&&!part.startsWith('intl-'));
    for(let i=0;i<parts.length-1;i++)if(['track','album','playlist'].includes(parts[i])&&/^[A-Za-z0-9]{22}$/.test(parts[i+1]))return {url:`https://open.spotify.com/${parts[i]}/${parts[i+1]}`,type:parts[i]};
    return null;
  }catch{return null;}
}
function spotifyValidate(){
  const input=$('#spotify-url'),message=$('#spotify-validation'),button=$('#spotify-submit');
  const value=input.value.trim(),parsed=normalizeSpotifyUrl(value);spotify.url=value;spotify.canonicalUrl=parsed?.url||null;spotify.mediaType=parsed?.type||null;
  input.setAttribute('aria-invalid',String(Boolean(value&&!parsed)));
  input.disabled=spotify.loading;$('#spotify-paste').disabled=spotify.loading;
  if(value&&!parsed)message.textContent='Нужна ссылка Spotify на трек, альбом или плейлист.';
  else if(!spotify.available)message.textContent='Подключение ожидает API-ключ от сервиса загрузки.';
  else message.textContent=parsed?`Тип ссылки: ${{track:'трек',album:'альбом',playlist:'плейлист'}[parsed.type]||'неизвестно'}.`:'Подойдут ссылки на трек, альбом или плейлист Spotify.';
  button.disabled=!parsed||!spotify.available||spotify.loading;
  button.innerHTML=`<span data-icon="${spotify.loading?'wave':'arrow-right'}"></span>${spotify.loading?'Получаем данные…':'Найти и скачать'} `;hydrateIcons(button);
}
function spotifyFailMessage(payload){
  if(payload?.success===false){const detail=payload.detail?.message||payload.detail||payload.message;return typeof detail==='string'?detail:'Сервис не нашёл эту ссылку.';}
  return '';
}
function setSpotifySteps(stage){
  const order={link:1,search:2,ready:3,error:2}[stage]||1;
  document.querySelectorAll('[data-spotify-step]').forEach((el,index)=>{el.classList.toggle('active',index<order);el.classList.toggle('complete',index+1<order);el.classList.toggle('failed',stage==='error'&&index===1);});
}
function spotifyArtwork(url){return url?`<img src="${escapeHtml(url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`:`<span data-icon="wave"></span>`;}
function spotifyCard(track,index,progressText=''){
  const name=track.name||track.title||'Без названия',performers=track.performers||track.performer||track.artists||'Исполнитель не указан';
  const progress=Number(track.progress),ready=Boolean(track.audio_url),failed=progress===101;
  const delivery=spotify.deliveryByTrack[String(track.id)]||'',otherBusy=spotify.activeDeliveryTrackId&&spotify.activeDeliveryTrackId!==String(track.id);
  const pct=Number.isFinite(progress)?Math.max(0,Math.min(100,progress)):0;
  const duration=Number(track.duration);const durationLabel=duration?formatTime(duration):'';
  const action=ready?(delivery==='sent'?'<span class="spotify-track-sent"><span data-icon="check"></span>В диалоге</span>':`<button class="spotify-send-button" type="button" data-spotify-deliver="${escapeHtml(String(track.id||''))}" data-track-title="${escapeHtml(name)}" data-track-artist="${escapeHtml(performers)}" ${delivery==='sending'||otherBusy?'disabled':''}><span data-icon="${delivery==='sending'?'wave':'send'}"></span>${delivery==='sending'?'Отправляю…':otherBusy?'Подожди':'Скачать в бот'}</button>`):failed?'<span class="spotify-track-failed">Не удалось</span>':`<span class="spotify-track-progress">${progressText|| (progress?`${pct}%`:'В очереди')}</span>`;
  return `<article class="spotify-track-card"><div class="spotify-track-art">${spotifyArtwork(track.coverart||track.cover)}</div><div class="spotify-track-copy"><strong>${escapeHtml(name)}</strong><span>${escapeHtml(performers)}${durationLabel?' · '+durationLabel:''}</span>${!ready&&!failed?`<div class="spotify-item-progress"><i style="width:${pct}%"></i></div>`:''}</div><div class="spotify-track-action">${action}</div></article>`;
}
function renderSpotify(){
  const result=$('#spotify-result');
  if(!spotify.metadata){
    result.innerHTML=`<div class="spotify-empty"><span class="spotify-empty-icon" data-icon="wave"></span><div><strong>${spotify.available?'Треки появятся здесь':'Ожидаем подключение API'}</strong><p>${spotify.available?'Вставь ссылку Spotify, чтобы проверить доступность аудио.':'Как только сервис выдаст API-ключ, загрузчик включится здесь.'}</p></div></div>`;hydrateIcons(result);return;
  }
  const metadata=spotify.metadata.metadata||{},download=spotify.download||{},isSingle=spotify.mediaType==='track';
  const items=Array.isArray(download.items)?download.items:[];
  const metadataTracks=Array.isArray(spotify.metadata.tracks)?spotify.metadata.tracks:[];
  const tracks=isSingle?[{...metadata,...download,coverart:metadata.coverart||metadata.cover,performers:metadata.performers||metadata.performer}]:metadataTracks.map(track=>({...track,...(items.find(item=>item.id===track.id)||{})}));
  spotify.currentTracks=tracks;
  const globalProgress=Number(download.progress),status=download.status||'pending';
  const allDone=isSingle?(Boolean(download.audio_url)||status==='failed'||globalProgress===101):items.length>0&&items.every(item=>item.audio_url||Number(item.progress)===101);
  const done=status==='available'||download.downloaded===true||allDone;
  const failed=status==='failed'||globalProgress===101;
  const heading=metadata.name||'Spotify подборка';
  const statusText=failed?'Не удалось подготовить аудио':done?'Файлы готовы к скачиванию':`Подготавливаем аудио${Number.isFinite(globalProgress)?` · ${Math.min(globalProgress,100)}%`:''}`;
  const total=Number(metadata.count)||tracks.length;
  const summary=`<div class="spotify-result-heading"><div class="spotify-collection-art">${spotifyArtwork(metadata.coverart||metadata.cover)}</div><div><span class="spotify-step">${escapeHtml(String(spotify.mediaType||'spotify').toUpperCase())}${total>1?' · '+total+' ТРЕКОВ':''}</span><h2>${escapeHtml(heading)}</h2><p>${escapeHtml(metadata.performers||metadata.performer||metadata.artists||metadata.description||'')}</p><strong class="spotify-job-status ${done?'is-ready':''} ${failed?'is-failed':''}" role="status">${escapeHtml(statusText)}</strong></div></div>`;
  const progressBar=!done&&!failed?`<div class="spotify-job-progress"><i style="width:${Math.max(3,Math.min(globalProgress||0,100))}%"></i></div>`:'';
  const cards=tracks.length?tracks.map((track,index)=>spotifyCard(track,index)).join(''):`<div class="spotify-empty"><span class="spotify-empty-icon" data-icon="info"></span><div><strong>В списке пока нет треков</strong><p>Обнови статус загрузки через несколько секунд.</p></div></div>`;
  const readyToSend=tracks.filter(track=>track.audio_url&&spotify.deliveryByTrack[String(track.id)]!=='sent');
  const pendingItems=items.filter(item=>!item.audio_url&&Number(item.progress)!==101).length;
  const collectionButton=!isSingle&&readyToSend.length>0&&readyToSend.length<=100
    ?`<button class="primary spotify-collection-send" id="spotify-deliver-collection" type="button" ${spotify.activeDeliveryTrackId?'disabled':''}><span data-icon="send"></span>${pendingItems?`Отправить готовые в бот · ${readyToSend.length} из ${total}`:`Скачать ${spotify.mediaType==='playlist'?'плейлист':'альбом'} в бот · ${readyToSend.length}`}</button>`
    :!isSingle&&readyToSend.length>100?'<p class="spotify-collection-limit">Весь список больше 100 треков. Отправь готовые треки по одному.</p>':'';
  const refresh=!done&&!failed?'<button class="secondary spotify-refresh" id="spotify-refresh" type="button">Обновить статус</button>':'';
  result.innerHTML=`${summary}${progressBar}${collectionButton}<div class="spotify-track-list">${cards}</div>${refresh}`;hydrateIcons(result);
  setSpotifySteps(failed?'error':done?'ready':'search');
}
function stopSpotifyPolling(){clearTimeout(spotify.pollTimer);spotify.pollTimer=null;}
async function pollSpotifyDelivery(jobId,trackIds,deadline){
  try{
    const result=await api(`/spotify/deliver/${encodeURIComponent(jobId)}`);
    if(['completed','partial'].includes(result.status)){
      const sent=new Set(result.sent_track_ids||[]);
      trackIds.forEach(trackId=>{if(sent.has(trackId))spotify.deliveryByTrack[trackId]='sent';else delete spotify.deliveryByTrack[trackId];});
      spotify.activeDeliveryTrackId=null;renderSpotify();
      if(result.status==='partial')toast(result.message||'Часть треков не удалось отправить.');
      return;
    }
    if(['failed','interrupted'].includes(result.status)){
      trackIds.forEach(trackId=>delete spotify.deliveryByTrack[trackId]);spotify.activeDeliveryTrackId=null;renderSpotify();toast(result.message||'Не получилось отправить треки.');return;
    }
  }catch(error){
    if(error.status===401||error.status===403||error.status===404){
      trackIds.forEach(trackId=>delete spotify.deliveryByTrack[trackId]);spotify.activeDeliveryTrackId=null;renderSpotify();toast(error.message||'Отправка прервалась. Попробуй снова.');return;
    }
  }
  if(Date.now()>=deadline){trackIds.forEach(trackId=>delete spotify.deliveryByTrack[trackId]);spotify.activeDeliveryTrackId=null;renderSpotify();toast('Статус отправки не получен. Проверь диалог с ботом.');return;}
  spotify.pollTimer=setTimeout(()=>pollSpotifyDelivery(jobId,trackIds,deadline),1600);
}
async function startSpotifyDelivery(tracks,activeKey){
  if(!tracks.length||spotify.activeDeliveryTrackId)return;
  const trackIds=tracks.map(track=>String(track.track_id));
  spotify.activeDeliveryTrackId=activeKey;trackIds.forEach(trackId=>spotify.deliveryByTrack[trackId]='sending');renderSpotify();
  try{
    const result=await api('/spotify/deliver',{method:'POST',body:JSON.stringify({tracks})});
    spotify.pollTimer=setTimeout(()=>pollSpotifyDelivery(result.job_id,trackIds,Date.now()+20*60*1000),800);
  }catch(error){
    trackIds.forEach(trackId=>delete spotify.deliveryByTrack[trackId]);spotify.activeDeliveryTrackId=null;renderSpotify();toast(error.message);
  }
}
function deliverSpotifyTrack(button){
  const trackId=String(button.dataset.spotifyDeliver||''),track=spotify.currentTracks.find(item=>String(item.id)===trackId);
  if(!track)return;
  startSpotifyDelivery([{track_id:trackId,title:track.name||track.title||'Spotify track',performer:track.performers||track.performer||track.artists||''}],trackId);
}
function deliverSpotifyCollection(){
  const tracks=spotify.currentTracks.filter(track=>track.audio_url&&spotify.deliveryByTrack[String(track.id)]!=='sent');
  const payload=tracks.map(track=>({track_id:String(track.id),title:track.name||track.title||'Spotify track',performer:track.performers||track.performer||track.artists||''}));
  startSpotifyDelivery(payload,'collection');
}
function downloadFinished(payload){
  if(payload.status==='available'||payload.status==='failed'||payload.downloaded===true||Number(payload.progress)===101)return true;
  if(spotify.mediaType==='track')return Boolean(payload.audio_url);
  const items=Array.isArray(payload.items)?payload.items:[];
  return items.length>0&&items.every(item=>item.audio_url||Number(item.progress)===101);
}
async function refreshSpotifyStatus(schedule=true){
  if(!spotify.canonicalUrl||!spotify.download||spotify.polling)return;
  spotify.polling=true;
  const requestId=spotify.requestId;
  try{
    const payload=await api('/spotify/download',{method:'POST',body:JSON.stringify({url:spotify.canonicalUrl}),timeoutMs:45000});
    if(requestId!==spotify.requestId)return;
    const failure=spotifyFailMessage(payload);if(failure)throw new Error(failure);
    spotify.download=payload;renderSpotify();
    if(downloadFinished(payload)){stopSpotifyPolling();return;}
    if(schedule&&Date.now()<spotify.expiresAt)spotify.pollTimer=setTimeout(()=>refreshSpotifyStatus(true),3000);
    else if(Date.now()>=spotify.expiresAt)toast('Загрузка ещё выполняется. Нажми «Обновить статус», чтобы продолжить.');
  }catch(error){
    if(requestId!==spotify.requestId)return;
    spotify.download={...spotify.download,status:'failed',error:error.message};renderSpotify();stopSpotifyPolling();toast(error.message);
  }finally{spotify.polling=false;}
}
async function spotifyStart(){
  if(spotify.loading||!spotify.available)return;
  const parsed=normalizeSpotifyUrl($('#spotify-url').value);if(!parsed){spotifyValidate();return;}
  stopSpotifyPolling();spotify.requestId++;spotify.loading=true;spotify.metadata=null;spotify.download=null;spotify.canonicalUrl=parsed.url;spotify.mediaType=parsed.type;spotify.expiresAt=Date.now()+15*60*1000;setSpotifySteps('search');spotifyValidate();
  $('#spotify-result').innerHTML='<div class="spotify-loading"><span class="spinner"></span><strong>Проверяем ссылку и наличие аудио…</strong></div>';
  try{
    const payload=await api('/spotify/item',{method:'POST',body:JSON.stringify({url:parsed.url}),timeoutMs:45000});
    const failure=spotifyFailMessage(payload);if(failure)throw new Error(failure);
    const data=payload.data;
    if(!data||!data.metadata)throw new Error('Сервис не вернул метаданные для этой ссылки.');
    spotify.metadata=data;renderSpotify();
    spotify.download={status:'pending',progress:0,items:[]};renderSpotify();
    await refreshSpotifyStatus(true);
  }catch(error){
    spotify.download={status:'failed',progress:101,error:error.message};
    $('#spotify-result').innerHTML=`<div class="spotify-error"><strong>Не удалось начать загрузку</strong><p>${escapeHtml(error.message)}</p><button class="secondary" id="spotify-retry" type="button">Попробовать ещё раз</button></div>`;setSpotifySteps('error');
  }finally{spotify.loading=false;spotifyValidate();}
}
$('#spotify-url').addEventListener('input',spotifyValidate);
$('#spotify-url').addEventListener('change',spotifyValidate);
$('#spotify-paste').addEventListener('click',async()=>{
  try{const value=await navigator.clipboard.readText();if(!value){toast('В буфере обмена нет ссылки.');return;}$('#spotify-url').value=value.trim();spotifyValidate();$('#spotify-url').focus();}
  catch{toast('Разреши доступ к буферу обмена или вставь ссылку вручную.');}
});
$('#spotify-form').addEventListener('submit',event=>{event.preventDefault();spotifyStart();});
$('#spotify-result').addEventListener('click',event=>{
  const sendButton=event.target.closest('[data-spotify-deliver]');if(sendButton){deliverSpotifyTrack(sendButton);return;}
  if(event.target.closest('#spotify-deliver-collection')){deliverSpotifyCollection();return;}
  if(event.target.closest('#spotify-refresh')){stopSpotifyPolling();refreshSpotifyStatus(false);}
  if(event.target.closest('#spotify-retry'))spotifyStart();
});
async function spotifyLoad(){
  try{const result=await api('/spotify/status');spotify.available=Boolean(result.available);}
  catch{spotify.available=false;}
  spotifyValidate();if(!spotify.metadata)renderSpotify();
  if(spotify.download&&!downloadFinished(spotify.download)&&!spotify.pollTimer){spotify.expiresAt=Date.now()+15*60*1000;refreshSpotifyStatus(true);}
}
