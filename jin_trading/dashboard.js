let token = '', timer, mode='paper', lastContact=0;
const el = id => document.getElementById(id);
async function api(path, method='GET') {
  const response = await fetch(path, {method, headers:{Authorization:'Bearer '+token},cache:'no-store',redirect:'error',signal:AbortSignal.timeout(8000)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Anfrage fehlgeschlagen');
  return data;
}
function textNode(tag, text) { const n=document.createElement(tag); n.textContent=text; return n; }
async function action(path) { if(Date.now()-lastContact>15000)return;try {await api(path,'POST');await refresh();} catch(e) {el('error').textContent=e.message;lastContact=0;disableControls();} }
function disableControls(){for(const button of document.querySelectorAll('#panel button'))button.disabled=true;}
function render(state) {
  lastContact=Date.now();mode=state.mode;for(const button of document.querySelectorAll('#panel button'))button.disabled=false;
  el('mode').textContent=mode.toUpperCase();el('mode-note').textContent=mode==='live'?'LIVE: lokal aktiviertes Echtgeldkonto. Start/Stop wirkt auf echte Orders.':'PAPER: öffentliche Kurse und virtuelles Kapital. Keine echten Orders.';
  el('panel').hidden=false; el('login').hidden=true;
  el('capital').textContent=Number(state.capital).toFixed(4)+' USDT';
  el('baseline').textContent=Number(state.baseline).toFixed(4)+' USDT';
  el('risk').textContent=state.halt ? 'Gesperrt: '+state.reason : 'Gemeinsames Tagesverlustlimit: 10 % · Modus '+mode.toUpperCase();
  el('bots').replaceChildren();
  for(const bot of state.bots) {
    const card=textNode('article',''); card.className='bot';
    card.append(textNode('h3',bot.id));
    card.append(textNode('p',Number(bot.capital).toFixed(4)+' USDT · PnL '+Number(bot.pnl).toFixed(4)+' USDT'));
    const stale=(Date.now()/1000-bot.updated)>30;
    card.append(textNode('p',(bot.enabled?mode.toUpperCase()+' aktiv':'Gestoppt')+' · Daten '+(stale?'veraltet / fehlen':'aktuell')));
    const universe=bot.status.universe || {};
    if(universe.mode==='auto') card.append(textNode('p','Automatische Märkte: '+(universe.scheduled_pairs || 0)+' Paare · Gruppe '+(universe.batch_number || 0)+' / '+(universe.batch_count || 0)+' · REST-Rotation, nicht gleichzeitig'));
    const row=textNode('div',''); row.className='row';
    for(const [verb,label] of [['start','Start'],['stop','Stop']]) {
      const button=textNode('button',label); button.disabled=verb==='start' && (state.halt || (state.portfolio && !state.portfolio.ready));
      button.onclick=()=>action('/api/bots/'+encodeURIComponent(bot.id)+'/'+verb); row.append(button);
    }
    card.append(row);
    const status=textNode('p','Max. Einsatz '+bot.max_order+' USDT · Risikobudget '+bot.risk_budget+' USDT'); status.className='status'; card.append(status);
    const details=textNode('details',''); details.append(textNode('summary','Chancen und Börsenstatus'));
    const list=textNode('ul','');
    for(const chance of bot.status.opportunities || []) list.append(textNode('li','PASSEND · '+chance.kind+' · '+chance.route.map(r=>r.join(':')).join(' → ')+' · netto '+(Number(chance.net_fraction)*100).toFixed(3)+' %'));
    for(const miss of bot.status.near_misses || []) list.append(textNode('li','KNAPP VERFEHLT · '+miss.route.map(r=>r.join(':')).join(' → ')+' · netto '+(Number(miss.net_fraction)*100).toFixed(3)+' % · '+miss.reason));
    const rejected=bot.status.rejected_counts || {};
    const rejectedEntries=Object.entries(rejected).sort((a,b)=>b[1]-a[1]).slice(0,5);
    for(const [reason,count] of rejectedEntries) list.append(textNode('li','ABGELEHNT · '+count+'× · '+reason));
    for(const error of bot.status.errors || []) list.append(textNode('li','FEHLER · '+error));
    if(!list.childNodes.length) list.append(textNode('li','Keine passende oder knapp verfehlte Chance / noch keine Daten'));
    details.append(list);card.append(details);el('bots').append(card);
  }
  el('orders').replaceChildren();for(const order of state.portfolio?.orders || []){const row=textNode('tr','');for(const key of ['client_id','pair','filled','state'])row.append(textNode('td',order[key]));el('orders').append(row);}
  el('trades').replaceChildren();
  for(const trade of state.trades) {const row=textNode('tr','');for(const key of ['bot','input','output']) row.append(textNode('td',trade[key]));el('trades').append(row);}
}
async function refresh() {try{
  const [state, existing]=await Promise.all([api('/api/state'),api('/api/existing/status')]);
  render(state);
  const o=existing.observation || {};
  el('existing').textContent=existing.available ? 'Beobachtungsmodus: '+o.mode+' · '+o.exchange_1+' / '+o.exchange_2+' · '+(existing.stale?'Daten veraltet':'Daten aktuell')+' · Runtime-Not-Aus: '+(o.runtime_kill_switch?'AN':'AUS')+' · Chancen: '+(o.opportunities || []).length : 'Kein vorhandener Beobachtungsprozess / keine lesbare Datei';
  el('error').textContent='';
}catch(e){lastContact=0;disableControls();el('error').textContent='Verbindung veraltet: '+e.message;}}
el('login').onsubmit=async event=>{event.preventDefault();token=el('token').value;await refresh();if(!el('panel').hidden){el('token').value='';clearInterval(timer);timer=setInterval(refresh,5000);}};
el('reconcile').onclick=()=>action('/api/reconcile');
el('halt').onclick=()=>action('/api/halt');
el('reset').onclick=()=>{if(confirm('Sperre nach Konto- und Orderprüfung zurücksetzen? Der Runtime-Not-Aus des bestehenden Bots bleibt gesetzt.'))action('/api/reset');};
el('export').onclick=async()=>{try{const r=await fetch('/api/trades.csv',{headers:{Authorization:'Bearer '+token}});if(!r.ok)throw new Error('Export fehlgeschlagen');const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download='jin-paper-trades.csv';a.click();URL.revokeObjectURL(url);}catch(e){el('error').textContent=e.message;}};
