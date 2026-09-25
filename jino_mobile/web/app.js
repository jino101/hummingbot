const $ = (id) => document.getElementById(id);
let accessToken = sessionStorage.getItem("jinoToken") || "";
const apiFetch = (path, options={}) => fetch(path, {
  ...options,
  cache: "no-store",
  headers: {...(options.headers || {}), Authorization: `Bearer ${accessToken}`}
});
const fmt = (v, n=4) => {
  const x = Number(v);
  return Number.isFinite(x) ? x.toFixed(n) : "–";
};

function renderBest(opportunities) {
  const box = $("best");
  if (!opportunities || !opportunities.length) {
    box.className = "empty";
    box.textContent = "Noch keine passende Gelegenheit.";
    return;
  }
  const o = opportunities[0];
  const profit = Number(o.expected_profit_after_rebalance_quote ?? o.expected_profit_quote ?? 0);
  box.className = "";
  box.innerHTML = `
    <div class="opp">
      <div>
        <strong>${o.trading_pair || ""}</strong><br>
        <span class="muted">Kaufen ${o.buy_exchange} @ ${fmt(o.buy_price,2)} · Verkaufen ${o.sell_exchange} @ ${fmt(o.sell_price,2)}</span>
      </div>
      <strong class="${profit > 0 ? "good" : "bad"}">${fmt(profit,4)} USDT</strong>
    </div>
    <div class="row"><span>Netto-Spread</span><strong>${fmt(Number(o.net_spread_pct)*100,3)}%</strong></div>
    <div class="row"><span>Rebalancing</span><strong>${fmt(o.rebalance_fee_quote,4)} USDT</strong></div>
  `;
}

function renderHistory(records) {
  const box = $("history");
  if (!records || !records.length) {
    box.innerHTML = '<div class="empty">Noch keine Historie gespeichert.</div>';
    return;
  }
  box.innerHTML = records.slice(-30).reverse().map(r => {
    const count = (r.opportunities || []).length;
    const when = r.timestamp ? new Date(Number(r.timestamp)*1000).toLocaleString() : "–";
    return `<div class="hist"><strong>${when}</strong> · ${count} Chancen · ${r.trading_pair || "–"} · ${r.mode || "–"}</div>`;
  }).join("");
}

async function refresh() {
  try {
    const [statusRes, summaryRes, historyRes] = await Promise.all([
      apiFetch("/api/status"),
      apiFetch("/api/summary"),
      apiFetch("/api/history"),
    ]);
    const status = await statusRes.json();
    const summary = await summaryRes.json();
    const history = await historyRes.json();

    $("mode").textContent = status.mode || "offline";
    $("pair").textContent = status.trading_pair || "–";
    const readiness = status.readiness || {};
    $("marketReady").textContent = readiness.market_data_ready === true ? "ONLINE" : "WARTET";
    $("marketReady").className = "big " + (readiness.market_data_ready === true ? "good" : "bad");
    $("transfer").textContent = readiness.transfer_route_verified === true ? "JA" : "NEIN";
    $("opps").textContent = (status.opportunities || []).length;
    $("samples").textContent = summary.samples || 0;
    $("profitable").textContent = `${summary.profitable_opportunities || 0} profitabel`;
    $("executors").textContent = status.executors ?? 0;
    $("positions").textContent = status.positions ?? 0;
    $("killState").textContent = status.runtime_kill_switch ? "AN" : "AUS";
    $("killState").className = status.runtime_kill_switch ? "bad" : "good";
    $("killButton").disabled = !!status.runtime_kill_switch;
    renderBest(status.opportunities || []);
    renderHistory(history.records || []);
    $("updated").textContent = "Aktualisiert: " + new Date().toLocaleTimeString();
  } catch (e) {
    $("marketReady").textContent = "OFFLINE";
    $("marketReady").className = "big bad";
    $("updated").textContent = "Dashboard-API nicht erreichbar";
  }
}

$("killButton").addEventListener("click", async () => {
  if (!confirm("Kill-Switch wirklich aktivieren? Neue Trades werden blockiert.")) return;
  await apiFetch("/api/kill-switch/enable", {method:"POST"});
  refresh();
});

async function login(token) {
  accessToken = (token || "").trim();
  if (!accessToken) return;
  try {
    const response = await apiFetch("/api/status");
    if (!response.ok) throw new Error("auth");
    sessionStorage.setItem("jinoToken", accessToken);
    $("authCard").hidden = true;
    $("dashboard").hidden = false;
    $("authError").textContent = "";
    await refresh();
  } catch (e) {
    $("authError").textContent = "Token nicht akzeptiert.";
    $("dashboard").hidden = true;
  }
}

$("loginButton").addEventListener("click", () => login($("tokenInput").value));
$("tokenInput").addEventListener("keydown", e => {
  if (e.key === "Enter") login($("tokenInput").value);
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(()=>{});
if (accessToken) login(accessToken);
setInterval(() => { if (accessToken) refresh(); }, 5000);
