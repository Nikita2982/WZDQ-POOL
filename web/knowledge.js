'use strict';
const knowledgeState={videos:[],category:'',query:'',loaded:false,loading:false,canUpload:false,maxUploadBytes:500*1024*1024,upload:null};
function knowledgeStop(){const player=$('#knowledge-player');player.querySelector('video')?.pause();player.replaceChildren();player.hidden=true;}
function knowledgeRender(){
  const all=knowledgeState.videos;
  $('#knowledge-controls').hidden=!all.length;
  const query=knowledgeState.query.toLocaleLowerCase('ru-RU');
  const videos=all.filter(video=>(!knowledgeState.category||video.category===knowledgeState.category)&&(!query||`${video.title} ${video.description} ${video.category}`.toLocaleLowerCase('ru-RU').includes(query)));
  $('#knowledge-count').textContent=all.length?`${videos.length} / ${all.length} видео`:'0 видео';
  const categories=[...new Set(all.map(video=>video.category))];
  $('#knowledge-categories').innerHTML=[{id:'',title:'Все видео'},...categories.map(category=>({id:category,title:category}))].map(category=>`<button class="pool-chip ${knowledgeState.category===category.id?'active':''}" data-knowledge-category="${escapeHtml(category.id)}" aria-pressed="${knowledgeState.category===category.id}">${escapeHtml(category.title)}</button>`).join('');
  if(!all.length){$('#knowledge-content').innerHTML=`<div class="knowledge-empty"><span class="knowledge-empty-icon">${icon('book')}</span><p class="eyebrow">УЧИТЬСЯ — ТОЖЕ ИСКУССТВО</p><h2>Твой следующий навык<br>начнётся здесь.</h2><p>Здесь будут обучающие видео для диджеев.<br>Первые уроки скоро появятся.</p><span class="knowledge-soon"><i class="live-dot"></i> Готовим библиотеку</span></div>`;return;}
  if(!videos.length){$('#knowledge-content').innerHTML='<div class="empty-state"><h2>Видео не найдены</h2><p>Попробуй другой запрос или категорию.</p></div>';return;}
  $('#knowledge-content').innerHTML=`<div class="knowledge-grid">${videos.map(video=>{
    const videoId=youtubeVideoId(video.url),thumbnail=video.thumbnail_url||(videoId?'https://i.ytimg.com/vi/'+videoId+'/hqdefault.jpg':'');
    return `<button class="knowledge-card" data-knowledge-id="${escapeHtml(video.id)}"><span class="knowledge-cover">${thumbnail?`<img src="${escapeHtml(thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer">`:icon('book')}<span class="knowledge-play">${icon('play')}</span></span><span class="knowledge-card-body"><small>${escapeHtml(video.category)}</small><strong>${escapeHtml(video.title)}</strong>${video.description?`<span>${escapeHtml(video.description)}</span>`:''}<span class="knowledge-watch">Смотреть видео ${icon('arrow-up-right')}</span></span></button>`;
  }).join('')}</div>`;
  $('#knowledge-content').querySelectorAll('img').forEach(image=>{image.addEventListener('error',()=>image.remove(),{once:true});});
}
async function knowledgeLoad(){
  if(knowledgeState.loaded)knowledgeRender();
  if(knowledgeState.loading)return;
  if(state.demo){$('#knowledge-content').innerHTML='<div class="knowledge-empty"><h2>Знания для участников пула</h2><p>Открой приложение через Telegram, чтобы перейти к библиотеке.</p></div>';$('#knowledge-count').textContent='Доступ через Telegram';return;}
  knowledgeState.loading=true;
  try{const data=await api('/knowledge');knowledgeState.videos=data.videos;knowledgeState.canUpload=!!data.can_upload;knowledgeState.maxUploadBytes=data.max_upload_bytes||500*1024*1024;knowledgeState.loaded=true;$('#knowledge-manage').hidden=!knowledgeState.canUpload;knowledgeRender();}
  catch(error){$('#knowledge-count').textContent='';$('#knowledge-content').innerHTML=`<div class="knowledge-empty"><h2>Не удалось открыть библиотеку</h2><p>${escapeHtml(error.message)}</p><button class="secondary" data-knowledge-retry>Повторить</button></div>`;}
  finally{knowledgeState.loading=false;}
}
function knowledgeOpen(video){
  knowledgeStop();
  const player=$('#knowledge-player');
  const heading=document.createElement('div');heading.className='knowledge-player-heading';
  const title=document.createElement('h2');title.textContent=video.title;
  const close=document.createElement('button');close.className='secondary';close.textContent='Закрыть';close.addEventListener('click',knowledgeStop);
  heading.append(title,close);player.append(heading);
  const id=youtubeVideoId(video.url);
  if(id){const frame=document.createElement('iframe');frame.src='https://www.youtube-nocookie.com/embed/'+id;frame.title=video.title;frame.allow='encrypted-media; picture-in-picture; fullscreen';frame.allowFullscreen=true;frame.referrerPolicy='strict-origin-when-cross-origin';player.append(frame);}
  else if(video.uploaded||/\.(mp4|webm|m4v)$/i.test(new URL(video.url,location.origin).pathname)){
    const media=document.createElement('video');media.controls=true;media.playsInline=true;media.preload='metadata';media.src=video.url;if(video.thumbnail_url)media.poster=video.thumbnail_url;player.append(media);
  }
  const link=document.createElement('button');link.hidden=!!video.uploaded;link.className='text-button';link.textContent='Открыть видео в источнике ↗';link.addEventListener('click',()=>{
    const url=new URL(video.url,location.origin);if(url.protocol!=='https:')return;
    if(telegram){if(['t.me','telegram.me'].includes(url.hostname))telegram.openTelegramLink(video.url);else telegram.openLink(video.url);}else window.open(video.url,'_blank','noopener,noreferrer');
  });player.append(link);player.hidden=false;player.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
}
$('#knowledge-search').addEventListener('input',event=>{knowledgeState.query=event.target.value.trim();knowledgeRender();});
$('#page-knowledge').addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.hasAttribute('data-knowledge-retry'))knowledgeLoad();
  if(button.hasAttribute('data-knowledge-category')){knowledgeState.category=button.dataset.knowledgeCategory;knowledgeRender();}
  if(button.dataset.knowledgeId){const video=knowledgeState.videos.find(row=>row.id===button.dataset.knowledgeId);if(video)knowledgeOpen(video);}
});
if(state.page==='knowledge')knowledgeLoad();

function knowledgeUploadReset(){
  $('#knowledge-upload-submit').disabled=false;
  $('#knowledge-upload-title').disabled=false;
  $('#knowledge-upload-file').disabled=false;
  knowledgeState.upload=null;
}
$('#knowledge-add-toggle').addEventListener('click',()=>{
  if(!knowledgeState.canUpload)return;
  const form=$('#knowledge-upload-form');form.hidden=!form.hidden;
  $('#knowledge-add-toggle').setAttribute('aria-expanded',String(!form.hidden));
  if(!form.hidden)$('#knowledge-upload-title').focus();
});
$('#knowledge-upload-file').addEventListener('change',event=>{
  const file=event.target.files[0];
  if(file&&!$('#knowledge-upload-title').value.trim())$('#knowledge-upload-title').value=file.name.replace(/\.[^.]+$/,'').slice(0,300);
});
$('#knowledge-upload-cancel').addEventListener('click',()=>{
  if(knowledgeState.upload){knowledgeState.upload.abort();return;}
  $('#knowledge-upload-form').hidden=true;$('#knowledge-add-toggle').setAttribute('aria-expanded','false');
});
$('#knowledge-upload-form').addEventListener('submit',event=>{
  event.preventDefault();
  if(!knowledgeState.canUpload||knowledgeState.upload)return;
  const title=$('#knowledge-upload-title').value.trim(),file=$('#knowledge-upload-file').files[0];
  if(!title||!file){toast('Выбери видео и укажи название');return;}
  if(!file.size){toast('Выбран пустой файл');return;}
  if(file.size>knowledgeState.maxUploadBytes){toast('Видео слишком большое. Максимум — 500 МБ');return;}
  const request=new XMLHttpRequest();knowledgeState.upload=request;
  request.open('POST','/miniapp-api/knowledge/videos?'+new URLSearchParams({title}));
  request.setRequestHeader('Content-Type',file.type||'application/octet-stream');
  request.setRequestHeader('X-Pinggy-No-Screen','1');
  if(initData)request.setRequestHeader('Authorization','tma '+initData);
  request.timeout=15*60*1000;
  $('#knowledge-upload-submit').disabled=true;$('#knowledge-upload-title').disabled=true;$('#knowledge-upload-file').disabled=true;
  $('#knowledge-upload-progress').hidden=false;$('#knowledge-upload-fill').style.width='0%';$('#knowledge-upload-status').textContent='Загружаем видео…';
  request.upload.onprogress=event=>{
    if(!event.lengthComputable)return;
    const percent=Math.round(100*event.loaded/event.total);
    $('#knowledge-upload-fill').style.width=percent+'%';
    $('#knowledge-upload-status').textContent=percent===100?'Видео передано. Подготавливаем для просмотра — это может занять несколько минут…':`Загружаем видео · ${percent}%`;
  };
  request.onload=async()=>{
    knowledgeUploadReset();
    let data;try{data=JSON.parse(request.responseText);}catch{data={};}
    if(request.status!==201){const message=typeof data.detail==='string'?data.detail:'Не удалось сохранить видео. Попробуй ещё раз.';$('#knowledge-upload-status').textContent=message;toast(message);return;}
    $('#knowledge-upload-form').reset();$('#knowledge-upload-form').hidden=true;$('#knowledge-add-toggle').setAttribute('aria-expanded','false');$('#knowledge-upload-progress').hidden=true;
    knowledgeState.category='';knowledgeState.query='';$('#knowledge-search').value='';knowledgeState.loaded=false;
    await knowledgeLoad();toast('Видео добавлено в «Знания»');
  };
  request.onerror=()=>{knowledgeUploadReset();$('#knowledge-upload-status').textContent='Соединение прервалось. Проверь интернет и попробуй ещё раз.';};
  request.ontimeout=()=>{knowledgeUploadReset();$('#knowledge-upload-status').textContent='Загрузка заняла слишком много времени. Попробуй ещё раз.';};
  request.onabort=()=>{knowledgeUploadReset();$('#knowledge-upload-status').textContent='Загрузка отменена.';};
  request.send(file);
});
