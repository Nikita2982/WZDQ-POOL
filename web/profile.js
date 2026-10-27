'use strict';
let profileRequest=0;
function profileRow(row){
  return `<li class="ranking-row ${row.is_me?'is-me':''} ${row.rank<=3?'top-rank rank-'+row.rank:''}"><span class="ranking-place">${row.rank<=3?icon('spark'):''}<b>${row.rank}</b></span><span class="ranking-avatar">${escapeHtml(row.name.slice(0,2).toUpperCase())}</span><span class="ranking-name">${escapeHtml(row.name)}${row.is_me?'<small>Это ты</small>':''}</span><span class="ranking-score"><strong>${row.generations.toLocaleString('ru-RU')}</strong><small>генераций</small></span></li>`;
}
function profileRender(data,error=''){
  const stats=data?.stats||{generations:state.sets.length,minutes:Math.round(state.sets.reduce((n,row)=>n+row.total_duration_sec/60,0)),favorites:state.sets.filter(row=>row.favorite).length};
  const me=data?.me,rows=data?.leaderboard||[],name=state.user.first_name||'DJ';
  const milestone=[10,30,50,100,250,500,1000].find(n=>n>stats.generations)||Math.ceil((stats.generations+1)/1000)*1000;
  const percent=Math.min(100,100*stats.generations/milestone);
  $('#page-profile').innerHTML=`<div class="page-heading"><p class="eyebrow">YOUR DJ IDENTITY</p><h1>За пультом — ты.</h1><p>Твои сеты. Твой вклад в ритм пула.</p></div>
  <article class="dj-profile"><div class="dj-profile-grain"></div><div class="dj-member-label"><span class="live-dot"></span>${state.local?'LOCAL DJ':state.demo?'ПРЕДПРОСМОТР':'WZDQ POOL MEMBER'}<span>EST. IN MUSIC</span></div><div class="dj-identity"><div class="dj-avatar"><span>${escapeHtml(name.slice(0,2).toUpperCase())}</span></div><div><p class="eyebrow">НА СВОЕЙ ВОЛНЕ</p><h2>${escapeHtml(name)}</h2><p>${state.local?'Локальная коллекция':state.demo?'Открой приложение через Telegram':'Доступ к пулу подтверждён'}</p></div></div>
  <div class="dj-profile-bottom"><span>${stats.favorite_genre?icon('wave')+' '+escapeHtml(genreName(stats.favorite_genre)):'Твой следующий сет — впереди'}</span><span>${me?'#'+me.rank+' в рейтинге':'Каждый сет имеет значение'}</span></div></article>
  <div class="dj-metrics"><button data-page="sets">${icon('layers')}<strong>${stats.generations.toLocaleString('ru-RU')}</strong><span>генераций</span></button><div>${icon('clock')}<strong>${stats.minutes.toLocaleString('ru-RU')}</strong><span>минут музыки</span></div><button data-page="favorites">${icon('heart')}<strong>${stats.favorites.toLocaleString('ru-RU')}</strong><span>в избранном</span></button></div>
  <div class="dj-next"><div><span>${icon('spark')} Следующая отметка</span><strong>${stats.generations} / ${milestone} генераций</strong></div><div class="dj-next-track"><span style="width:${percent}%"></span></div><p>${milestone-stats.generations} до новой отметки. Собери сет под своё настроение.</p><button class="secondary" data-page="home">Создать плейлист ${icon('arrow-right')}</button></div>
  <section class="dj-leaderboard" aria-labelledby="ranking-title"><div class="ranking-heading"><div><p class="eyebrow">POOL COMMUNITY</p><h2 id="ranking-title">В ритме пула</h2></div><span class="ranking-pill">${data?.participants||0} участников</span></div><p class="ranking-description">Рейтинг по количеству сгенерированных сетов за всё время в Mini App. При равном счёте — одинаковое место.</p>
  ${error?`<div class="ranking-empty"><p>${escapeHtml(error)}</p><button class="secondary" id="profile-retry">Повторить</button></div>`:!data?'<div class="ranking-empty">Загружаем рейтинг…</div>':state.local||state.demo?'<div class="ranking-empty">Рейтинг участников доступен при входе через Telegram. Локальные генерации в него не входят.</div>':!rows.length?`<div class="ranking-empty">${icon('spark')}<h3>Первый бит за тобой</h3><p>Создай первый сет — и открой рейтинг пула.</p><button class="primary" data-page="home">Собрать сет ${icon('arrow-right')}</button></div>`:`<ol class="ranking-list">${rows.map(profileRow).join('')}</ol>${me&&!rows.some(row=>row.is_me)?`<p class="ranking-your-label">Твоё место</p><ol class="ranking-list">${profileRow(me)}</ol>`:''}${!me?'<p class="ranking-footnote">Сгенерируй первый сет, чтобы появиться в рейтинге.</p>':''}`}
  <p class="ranking-footnote">В списке видны только имя и число генераций. Твои плейлисты доступны тебе.</p></section>`;
  $('#profile-retry')?.addEventListener('click',profileLoad);
}
async function profileLoad(){
  const request=++profileRequest;
  profileRender(null);
  if(state.demo){profileRender({stats:{generations:0,minutes:0,favorites:0},leaderboard:[],me:null,participants:0});return;}
  try{const data=await api('/profile');if(request===profileRequest)profileRender(data);}
  catch(error){if(request===profileRequest)profileRender(null,error.message);}
}
if(state.page==='profile')profileLoad();
