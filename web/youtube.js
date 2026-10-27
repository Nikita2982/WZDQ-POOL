'use strict';
const yt = {jobs:[],current:null,timer:null,busy:false,seenJob:null,seenTracks:new Set()};
const ytLabels = {running:'Ищем треки',completed:'Разбор завершён',failed:'Не удалось завершить',cancelled:'Разбор отменён',interrupted:'Разбор прерван'};
function youtubeVideoId(value){
  try{
    const url=new URL(value.trim());
    if(!['https:','http:'].includes(url.protocol)||url.username||url.password||url.port)return null;
    const parts=url.pathname.replace(/^\/|\/$/g,'').split('/');
    let id=null;
    if(url.hostname==='youtu.be'&&parts.length===1)id=parts[0];
    else if(['youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'].includes(url.hostname)){
      if(url.pathname==='/watch')id=url.searchParams.get('v');
      else if(parts.length===2&&['live','shorts','embed'].includes(parts[0]))id=parts[1];
    }
    return /^[A-Za-z0-9_-]{11}$/.test(id||'')?id:null;
  }catch{return null;}
}
function youtubePreview(){
  const preview=$('#youtube-preview'),id=youtubeVideoId($('#youtube-url').value);
  if(preview.dataset.videoId===(id||''))return;
  preview.dataset.videoId=id||'';
  preview.replaceChildren();preview.hidden=!id;
  if(!id)return;
  const image=document.createElement('img'),caption=document.createElement('figcaption');
  image.alt='Обложка DJ-сета на YouTube';image.referrerPolicy='no-referrer';
  caption.textContent='Загружаем обложку…';
  image.onload=()=>{if(preview.dataset.videoId!==id)return;if(image.naturalWidth<=120){image.hidden=true;caption.textContent='Обложка недоступна. Можно запустить анализ ссылки.';}else caption.textContent='Обложка видео · YouTube';};
  image.onerror=()=>{if(preview.dataset.videoId!==id)return;image.hidden=true;caption.textContent='Не удалось загрузить обложку. Можно запустить анализ ссылки.';};
  preview.append(image,caption);
  image.src='https://i.ytimg.com/vi/'+id+'/hqdefault.jpg';
}
$('#youtube-url').addEventListener('input',youtubePreview);
$('#youtube-url').addEventListener('change',youtubePreview);
youtubePreview();
function youtubeAudioStatus(audio){
  if(!audio)return '';
  const labels={queued:'В очереди на поиск',searching:'Ищем аудиофайл…',downloading:'Скачиваем аудио…',ready:audio.quality||'MP3 готов',missing:'Аудиофайл не найден',failed:audio.message||'Не удалось получить файл',stopped:'Поиск аудио остановлен',expired:'Срок хранения файла истёк'};
  return `<span class="yt-audio-state audio-${escapeHtml(audio.status)}">${['searching','downloading'].includes(audio.status)?'<i></i>':''}${escapeHtml(labels[audio.status]||'')}</span>`;
}
function youtubeRender(){
  const job=yt.current, running=job?.status==='running';
  $('#youtube-start').disabled=yt.busy||running||state.demo;
  if(!job){$('#youtube-current').innerHTML=`<div class="yt-placeholder">${icon('wave')}<p>${state.demo?'Открой приложение из чата бота, чтобы распознать сет.':'Добавь ссылку — найденные треки появятся здесь по мере анализа.'}</p></div>`;}
  else{
    const match=job.progress.match(/Проверено (\d+)\/(\d+)/), percent=match&&Number(match[2])?Math.min(100,Math.round(100*Number(match[1])/Number(match[2]))):null;
    const tracks=job.tracks||[];
    if(yt.seenJob!==job.id){yt.seenJob=job.id;yt.seenTracks=new Set();}
    let discoveryIndex=0;
    const renderedTracks=tracks.map((track,i)=>{
      const key=JSON.stringify([track.artist.trim().toLowerCase(),track.title.trim().toLowerCase()]);
      const fresh=!yt.seenTracks.has(key);yt.seenTracks.add(key);
      return `<li class="${fresh?'yt-new-track':''}" style="--discovery-delay:${fresh?Math.min(discoveryIndex++*.12,1.2):0}s"><span class="yt-track-number">${String(i+1).padStart(2,'0')}</span><span><strong>${escapeHtml(track.title)}</strong><small>${escapeHtml(track.artist)}</small>${youtubeAudioStatus(track.audio)}</span>${track.timestamp?`<time>${escapeHtml(track.timestamp)}</time>`:''}${track.audio?.status==='ready'?`<button class="secondary yt-audio-download" data-yt-audio="${escapeHtml(track.audio.id)}" data-yt-job-id="${job.id}" aria-label="Скачать ${escapeHtml(track.artist)} — ${escapeHtml(track.title)}">${icon('download')}<span>Скачать</span></button>`:''}</li>`;
    }).join('');
    const readyAudio=tracks.filter(track=>track.audio?.status==='ready').length;
    const audioSummary=tracks.some(track=>track.audio)?`<div class="yt-audio-summary">${icon('download')}<span>Готово к скачиванию: <strong>${readyAudio} из ${tracks.length}</strong><small>Файлы хранятся 24 часа. Скачай нужные на устройство.</small></span></div>`:'';
    const sourceNote=(job.report||'').split('\n').find(line=>line.includes('аудио не проверялось')||line.includes('Распознавание аудио не завершено'))||'';
    $('#youtube-current').innerHTML=`<article class="yt-result"><div class="yt-result-head"><span class="yt-status ${running?'is-running':''}">${running?icon('wave'):icon('check')}${escapeHtml(ytLabels[job.status]||job.status)}</span><strong>${tracks.length} треков</strong></div><h2>${escapeHtml(job.title)}</h2><p class="yt-progress-message">${escapeHtml(job.progress.split('\n\n')[0].replace(/Найдено треков: (\d+)/,'Найдено в аудио: $1'))}</p>${sourceNote?`<p class="yt-hint">${escapeHtml(sourceNote)}</p>`:''}${running?`<div class="yt-scanner"><div class="yt-scanner-orbit"></div><div class="yt-scanner-wave">${[0,1,2,3,4,5,6].map(i=>`<i style="--bar:${i}"></i>`).join('')}</div><div><strong>Поиск треков продолжается</strong><span>Новые находки появятся в списке ниже</span></div></div><div class="yt-progress ${percent===null?'is-indeterminate':''}" ${percent!==null?`role="progressbar" aria-valuenow="${percent}" aria-valuemin="0" aria-valuemax="100"`:''}><span style="width:${percent??30}%"></span></div><p class="yt-hint">${percent!==null?percent+'% фрагментов проверено · ':''}Можно перейти в другой раздел. Анализ продолжится, пока приложение работает на компьютере.</p><button class="secondary" data-yt-cancel="${job.id}">${icon('stop')}Остановить</button>`:''}
    ${!running&&tracks.some(track=>!track.audio||['missing','failed','stopped','expired'].includes(track.audio.status))?`<button class="secondary" data-yt-find-audio="${job.id}">${icon('search')}Найти и скачать аудио</button>`:''}
    ${audioSummary}${tracks.length?`<div class="yt-found-heading"><h3>Найденные треки</h3><span>${running?'<i class="live-dot"></i> ':''}${tracks.length}</span></div><ol class="yt-tracks">${renderedTracks}</ol>`:''}
    ${job.report?`<div class="set-actions"><button class="secondary" data-yt-download>${icon('download')}Скачать TXT</button>${!state.local?`<button class="primary" data-yt-send="${job.id}">${icon('send')}Треклист в чат</button>`:''}</div><p class="yt-hint">Список может быть неполным. Источники и примечания доступны в отчёте.</p><details class="yt-report"><summary>Полный отчёт и источники</summary><pre>${escapeHtml(job.report)}</pre></details>`:''}</article>`;
  }
  $('#youtube-history').innerHTML=yt.jobs.length?`<div class="section-heading"><h2>Твои разборы</h2></div><div class="yt-history">${yt.jobs.map(row=>`<button class="yt-history-item ${row.id===job?.id?'selected':''}" data-yt-job="${row.id}">${icon('youtube')}<span><strong>${escapeHtml(row.title)}</strong><small>${escapeHtml(ytLabels[row.status]||row.status)} · ${(row.tracks||[]).length} треков</small></span>${icon('arrow-right')}</button>`).join('')}</div>`:'';
}
function youtubeSchedule(){clearTimeout(yt.timer);if(yt.current?.status==='running')yt.timer=setTimeout(youtubePoll,2500);}
async function youtubePoll(){
  const id=yt.current?.id;if(!id)return;
  try{const job=await api('/youtube/jobs/'+id);if(yt.current?.id!==id)return;yt.current=job;yt.jobs=yt.jobs.map(row=>row.id===id?job:row);youtubeRender();}
  catch(error){$('#youtube-current .yt-hint')?.replaceChildren(document.createTextNode('Соединение прервалось. Повторяем подключение…'));}
  youtubeSchedule();
}
async function youtubeLoad(){
  if(state.demo){youtubeRender();return;}
  try{yt.jobs=await api('/youtube/jobs');const active=yt.jobs.find(row=>row.status==='running');yt.current=active||yt.jobs.find(row=>row.id===yt.current?.id)||yt.jobs[0]||null;youtubeRender();youtubeSchedule();}
  catch(error){$('#youtube-current').innerHTML=`<div class="yt-placeholder"><p>${escapeHtml(error.message)}</p><button class="secondary" data-yt-retry>Повторить подключение</button></div>`;}
}
$('#youtube-form').addEventListener('submit',async event=>{
  event.preventDefault();if(yt.busy||yt.current?.status==='running'||state.demo)return;
  yt.busy=true;youtubeRender();haptic();
  try{const job=await api('/youtube/jobs',{method:'POST',body:JSON.stringify({url:$('#youtube-url').value.trim()})});yt.current=job;yt.jobs.unshift(job);youtubeRender();youtubeSchedule();}
  catch(error){toast(error.message);}
  finally{yt.busy=false;youtubeRender();}
});
$('#page-youtube').addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.hasAttribute('data-yt-retry'))return youtubeLoad();
  if(button.dataset.ytFindAudio){
    button.disabled=true;
    try{const job=await api('/youtube/jobs/'+button.dataset.ytFindAudio+'/audio',{method:'POST'});yt.current=job;yt.jobs=yt.jobs.map(row=>row.id===job.id?job:row);youtubeRender();youtubeSchedule();}
    catch(error){toast(error.message);button.disabled=false;}
    return;
  }
  if(button.dataset.ytAudio){
    button.disabled=true;
    try{
      const file=await api('/youtube/jobs/'+button.dataset.ytJobId+'/audio/'+button.dataset.ytAudio+'/download',{method:'POST'});
      const url=new URL(file.url,location.origin).href;
      if(telegram?.downloadFile&&telegram?.isVersionAtLeast?.('8.0')!==false&&url.startsWith('https:')){
        telegram.downloadFile({url,file_name:file.filename},accepted=>{if(accepted)toast('Скачивание началось');});
      }else if(telegram?.openLink){telegram.openLink(url);}
      else{const link=document.createElement('a');link.href=url;link.download=file.filename;link.click();}
    }catch(error){toast(error.message);}
    finally{button.disabled=false;}
    return;
  }
  if(button.dataset.ytJob){yt.current=yt.jobs.find(row=>row.id===button.dataset.ytJob);youtubeRender();youtubeSchedule();return;}
  if(button.hasAttribute('data-yt-download')){const blob=new Blob([yt.current.report],{type:'text/plain;charset=utf-8'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='youtube-tracklist.txt';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;}
  button.disabled=true;
  try{
    if(button.dataset.ytCancel){await api('/youtube/jobs/'+button.dataset.ytCancel+'/cancel',{method:'POST'});await youtubePoll();}
    if(button.dataset.ytSend){await api('/youtube/jobs/'+button.dataset.ytSend+'/send',{method:'POST'});toast('Треклист отправлен в чат бота');}
  }catch(error){toast(error.message);}
  finally{button.disabled=false;}
});
if(state.page==='youtube')youtubeLoad();
