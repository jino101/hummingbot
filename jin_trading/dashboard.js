let token = '', timer;
const el = id => document.getElementById(id);
async function api(path, method='GET') {
  const response = await fetch(path, {method, headers:{Authorization:'Bearer '+token}});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Anfrage fehlgeschlagen');
  return data;
}
function textNode(tag, text) { const n=document.createElement(tag); n.textContent=text; return n; }
async function action(path) { try { render(await api(path,'POST')); el('error').textContent=''; } catch(e) {el('error').textContent=e.message;} }
function render(state) {
  el('panel').hidden=false; el('login').hidden=true;
  el('capital').textContent=Number(state.capital).toFixed(4)+' USDT';
  el('baseline').textContent=Number(state.baseline).toFixed(4)+' USDT';
  el('risk').textContent=state.halt ? 'Gesperrt: '+state.reason : 'Gemeinsames Tagesverlustlimit: 10 % · Start/Stop steuert nur Paper-Trades';
  el('bots').replaceChildren();
  for(const bot of state.bots) {
    const card=textNode('article',''); card.className='bot';
    card.append(textNode('h3',bot.id));
    card.append(textNode('p',Number(bot.capital).toFixed(4)+' USDT · PnL '+Number(bot.pnl).toFixed(4)+' USDT'));
    const stale=(Date.now()/1000-bot.updated)>30;
    card.append(textNode('p',(bot.enabled?'Paper aktiv':'Gestoppt')+' · Daten '+(stale?'veraltet / fehlen':'aktuell')));
    const row=textNode('div',''); row.className='row';
    for(const [verb,label] of [['start','Start'],['stop','Stop']]) {
      const button=textNode('button',label); button.disabled=verb==='start' && state.halt;
      button.onclick=()=>action('/api/bots/'+encodeURIComponent(bot.id)+'/'+verb); row.append(button);
    }
    card.append(row);
    const status=textNode('p','Max. Einsatz '+bot.max_order+' USDT · Risikobudget '+bot.risk_budget+' USDT'); status.className='status'; card.append(status);
    const details=textNode('details',''); details.append(textNode('summary','Chancen und Börsenstatus'));
    const list=textNode('ul','');
    for(const chance of bot.status.opportunities || []) list.append(textNode('li',chance.kind+' · '+chance.route.map(r=>r.join(':')).join(' → ')+' · geschätzt '+(Number(chance.net_fraction)*100).toFixed(3)+' %'));
    for(const error of bot.status.errors || []) list.append(textNode('li',error));
    if(!list.childNodes.length) list.append(textNode('li','Keine passende Chance / noch keine Daten'));
    details.append(list);card.append(details);el('bots').append(card);
  }
  el('trades').replaceChildren();
  for(const trade of state.trades) {const row=textNode('tr','');for(const key of ['bot','input','output']) row.append(textNode('td',trade[key]));el('trades').append(row);}
}
async function refresh() {try{
  const [state, existing]=await Promise.all([api('/api/state'),api('/api/existing/status')]);
  render(state);
  const o=existing.observation || {};
  el('existing').textContent=existing.available ? 'Beobachtungsmodus: '+o.mode+' · '+o.exchange_1+' / '+o.exchange_2+' · '+(existing.stale?'Daten veraltet':'Daten aktuell')+' · Runtime-Not-Aus: '+(o.runtime_kill_switch?'AN':'AUS')+' · Chancen: '+(o.opportunities || []).length : 'Kein vorhandener Beobachtungsprozess / keine lesbare Datei';
  el('error').textContent='';
}catch(e){el('error').textContent=e.message;}}
el('login').onsubmit=async event=>{event.preventDefault();token=el('token').value;await refresh();if(!el('panel').hidden){el('token').value='';clearInterval(timer);timer=setInterval(refresh,5000);}};
el('halt').onclick=()=>action('/api/halt');
el('reset').onclick=()=>{if(confirm('Nur die Paper-Sperre zurücksetzen? Der Runtime-Not-Aus des bestehenden Bots bleibt gesetzt.'))action('/api/reset');};
el('export').onclick=async()=>{try{const r=await fetch('/api/trades.csv',{headers:{Authorization:'Bearer '+token}});if(!r.ok)throw new Error('Export fehlgeschlagen');const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download='jin-paper-trades.csv';a.click();URL.revokeObjectURL(url);}catch(e){el('error').textContent=e.message;}};
