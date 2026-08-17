/* Skin Arbitraj Paneli — arayüz mantığı */

let SOURCES = {};
let SETTINGS = {};
let ITEMS = [];
let VARIANTS = [];
let currentGame = localStorage.getItem("currentGame") || "cs2";
let currentItemId = parseInt(localStorage.getItem("currentItemId_" + currentGame) || "", 10) || null;

const GAME_UI = {
  cs2: {
    title: "Fırsatları renklendir.",
    desc: "CS2 fiyatını Steam Market referans alır, yanına Skinport, DMarket, CSFloat, Kopazar, GameSatis, ByNoGame, İtemSatış ve Itemci koyar. Steam'den ucuzsa fırsat; eşiğin tutunca Telegram gelir.",
    placeholder: "örn. AK-47 | Vulcan veya P250 | Visions",
    hint: "Wear yazmana gerek yok: <code>AK-47 | Elite Build</code> yaz, varyantlar bulunur. <code>StatTrak™</code> ve <code>★</code> desteklenir.",
    empty: "Henüz arama yapılmadı. Yukarıdan bir CS2 skin ara,<br>fiyatları pazarlarda aynı anda gör.",
    settingsKey: "enabled_sources_cs2",
  },
  rust: {
    title: "Rust skinlerini izle.",
    desc: "Rust itemlarını Skinport, DMarket, rust.tm, ByNoGame, Waxpeer, Steam Market ve GameSatis üzerinde karşılaştır. USD fiyatlar otomatik TRY'ye çevrilir.",
    placeholder: "örn. Soul Taker AK47 veya Big Grin",
    hint: "Steam market adını yaz. Rust skinlerinde genelde wear yok; tam ad bulunursa doğrudan eklenir.",
    empty: "Henüz Rust araması yok. Yukarıdan bir skin ara,<br>pazarlarda fiyatları gör.",
    settingsKey: "enabled_sources_rust",
  },
  ko: {
    title: "Knight Online itemlerini izle.",
    desc: "KO itemlerini Kopazar ve ByNoGame üzerinde karşılaştır. + basamağı ve Reverse eşleşmesi desteklenir.",
    placeholder: "örn. Raptor +11 (Reverse) veya Shard +9",
    hint: "+ basamağını yaz. Reverse item için <code>Raptor +11 (Reverse)</code> seç — pazarda çoğu +11 Raptor Reverse satılır.",
    empty: "Henüz KO araması yok. Yukarıdan bir item ara,<br>fiyatları gör.",
    settingsKey: "enabled_sources_ko",
  },
};

const fmtTL = (v) =>
  v == null ? "—" : v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " TL";
const fmtOrig = (p) => {
  if (p.price_orig == null) return "";
  const sym = p.currency === "USD" ? "$" : p.currency === "EUR" ? "€" : "₺";
  if (p.currency === "TRY") return "";
  return sym + p.price_orig.toLocaleString("en-US", { maximumFractionDigits: 2 });
};

function toast(msg, cls = "") {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "show " + cls;
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.className = ""), 3500);
}

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

/* ---------- modallar ---------- */
function openModal(id) { document.getElementById(id).classList.add("open"); }
function closeModal(id) { document.getElementById(id).classList.remove("open"); }
document.querySelectorAll(".modal-backdrop").forEach((b) =>
  b.addEventListener("click", (e) => { if (e.target === b) b.classList.remove("open"); })
);

/* ---------- itemlar ---------- */
async function loadItems() {
  const data = await api(`/api/items?game=${currentGame}`);
  SOURCES = data.sources;
  ITEMS = data.items;
  try {
    const d = await api(`/api/depo?game=${currentGame}`);
    TAKIP_NAMES = new Set((d.items || []).map((x) => x.name));
  } catch {}
  renderCurrent();
  if (document.getElementById("historyModal").classList.contains("open")) renderHistory();
}

let currentSection = "ara";
let catalogOffset = 0;
let chartName = "";
let chartSpan = "1h";
let chartFrom = "listele";
let priceChart = null;
let chartInDepo = false;
let TAKIP_NAMES = new Set();

const HUB_COPY = {
  ara: { title: "Item Ara", lead: "Oyunu seç. CS2, Rust veya Knight Online aramasına geçersin." },
  listele: { title: "Item Listele", lead: "Oyunu seç. Tüm isimler listelenir; birine basınca fiyat grafiği açılır." },
  depo: { title: "Takip", lead: "Oyunu seç. Beğenip takibe aldığın itemler burada." },
};

function toggleSidebar() {
  document.body.classList.toggle("sidebar-open");
}
function closeSidebar() {
  document.body.classList.remove("sidebar-open");
}

function hideViews() {
  ["viewHub", "viewSearch", "viewCatalog", "viewChart", "viewDepo", "viewOpps"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
  });
}

function setNav() {
  document.getElementById("navAra").classList.toggle("on", currentSection === "ara");
  document.getElementById("navListele").classList.toggle("on", currentSection === "listele");
  document.getElementById("navDepo").classList.toggle("on", currentSection === "depo");
  document.getElementById("navOpps").classList.toggle("on", currentSection === "opps");
}

function goSection(sec) {
  currentSection = sec;
  setNav();
  closeSidebar();
  hideViews();
  if (sec === "opps") {
    document.getElementById("viewOpps").style.display = "";
    loadOpportunities();
    return;
  }
  const copy = HUB_COPY[sec] || HUB_COPY.ara;
  document.getElementById("hubTitle").textContent = copy.title;
  document.getElementById("hubLead").textContent = copy.lead;
  document.getElementById("viewHub").style.display = "";
}

async function pickGame(game) {
  closeSidebar();
  currentGame = game;
  localStorage.setItem("currentGame", game);
  currentItemId = parseInt(localStorage.getItem("currentItemId_" + game) || "", 10) || null;
  applyGameUi();
  hideViews();
  if (currentSection === "ara") {
    document.getElementById("viewSearch").style.display = "";
    await loadItems();
  } else if (currentSection === "listele") {
    document.getElementById("viewCatalog").style.display = "";
    await loadCatalog(0);
  } else if (currentSection === "depo") {
    document.getElementById("viewDepo").style.display = "";
    await loadDepo();
  }
}

function applyGameUi() {
  const ui = GAME_UI[currentGame] || GAME_UI.cs2;
  const ht = document.getElementById("heroTitle");
  const hd = document.getElementById("heroDesc");
  if (ht) ht.textContent = ui.title;
  if (hd) hd.textContent = ui.desc;
  const inp = document.getElementById("itemInput");
  const hint = document.getElementById("searchHint");
  if (inp) inp.placeholder = ui.placeholder;
  if (hint) hint.innerHTML = ui.hint;
  const hideDiscounts = currentGame === "rust" || currentGame === "ko";
  const t = document.getElementById("oppDiscountTitle");
  const h = document.getElementById("oppDiscountHint");
  const d = document.getElementById("oppDiscounts");
  if (t) t.style.display = hideDiscounts ? "none" : "";
  if (h) h.style.display = hideDiscounts ? "none" : "";
  if (d) d.style.display = hideDiscounts ? "none" : "";
  if (document.getElementById("settingsModal").classList.contains("open")) renderSourceChecks();
}

async function loadCatalog(offset) {
  catalogOffset = offset || 0;
  const q = (document.getElementById("catalogQ").value || "").trim();
  const box = document.getElementById("catalogList");
  box.innerHTML = `<div class="empty"><p>yükleniyor…</p></div>`;
  try {
    const d = await api(`/api/catalog?game=${currentGame}&q=${encodeURIComponent(q)}&offset=${catalogOffset}&limit=80`);
    document.getElementById("catalogMeta").textContent =
      `${(d.total || 0).toLocaleString("tr-TR")} kayıt — ${currentGame.toUpperCase()}`
      + (d.ranked ? ` · ${d.ranked.toLocaleString("tr-TR")} Steam trendi sıralı` : "")
      + (d.ranking ? " · sıralama hesaplanıyor…" : "")
      + (d.syncing ? " · katalog doluyor…" : "");
    const fmtChg = (v, label) => {
      if (v == null || v === "") return `<span class="mu">${label} —</span>`;
      const n = Number(v);
      const sign = n > 0 ? "+" : "";
      const cls = n > 0 ? "up" : n < 0 ? "dn" : "mu";
      return `<span class="${cls}">${label} ${sign}${n.toFixed(1)}%</span>`;
    };
    if (!d.items.length) {
      box.innerHTML = `<div class="empty"><p>${esc(d.hint || d.error || "Sonuç yok.")}</p></div>`;
    } else {
      box.innerHTML = d.items.map((it) => `
        <div class="name-row" data-name="${esc(it.name)}" onclick="openChart(this.dataset.name)">
          <span class="nm">${esc(it.name)}</span>
          <span class="chg">${fmtChg(it.chg_48h, "48s")}<br>${fmtChg(it.chg_24h, "1g")}</span>
          <span class="pr">${it.price_try != null ? fmtTL(it.price_try) : "—"}</span>
          <button class="star" title="takibe ekle" onclick="event.stopPropagation(); addDepoName(this.parentElement.dataset.name)">☆</button>
        </div>`).join("");
    }
    const pager = document.getElementById("catalogPager");
    const prev = catalogOffset > 0;
    const next = catalogOffset + d.limit < d.total;
    pager.innerHTML =
      (prev ? `<button class="btn btn-ghost" onclick="loadCatalog(${Math.max(0, catalogOffset - 80)})">← önceki</button>` : "") +
      (next ? `<button class="btn btn-ghost" onclick="loadCatalog(${catalogOffset + 80})">sonraki →</button>` : "");
    if ((d.syncing || d.ranking) && catalogOffset === 0) {
      clearTimeout(window._catPoll);
      window._catPoll = setTimeout(() => loadCatalog(0), d.ranking ? 7000 : 4000);
    }
  } catch (e) {
    box.innerHTML = `<div class="empty"><p>${esc(e.message)}</p></div>`;
  }
}

async function loadDepo() {
  const box = document.getElementById("depoList");
  try {
    const d = await api(`/api/depo?game=${currentGame}`);
    TAKIP_NAMES = new Set((d.items || []).map((x) => x.name));
    if (!d.items.length) {
      box.innerHTML = `<div class="empty"><p>Bu oyunda takipte ürün yok. Grafikten veya aramadan “Takibe ekle”.</p></div>`;
      return;
    }
    box.innerHTML = d.items.map((it) => `
      <div class="name-row" data-name="${esc(it.name)}" data-id="${it.id}" onclick="openChart(this.dataset.name, 'depo')">
        <span class="nm">${esc(it.name)}</span>
        <button class="star" onclick="event.stopPropagation(); removeDepo(${it.id})">✕</button>
      </div>`).join("");
  } catch (e) {
    box.innerHTML = `<div class="empty"><p>${esc(e.message)}</p></div>`;
  }
}

async function goTakipList() {
  currentSection = "depo";
  setNav();
  closeSidebar();
  hideViews();
  document.getElementById("viewDepo").style.display = "";
  await loadDepo();
}

async function addDepoName(name, goList = false) {
  try {
    if (TAKIP_NAMES.has(name)) {
      if (goList) await goTakipList();
      return;
    }
    await api("/api/depo", { method: "POST", body: JSON.stringify({ game: currentGame, name }) });
    TAKIP_NAMES.add(name);
    toast("Takibe eklendi", "ok");
    chartInDepo = chartName === name ? true : chartInDepo;
    syncDepoBtn();
    if (typeof currentItemId === "number") renderCurrent();
    if (goList) await goTakipList();
  } catch (e) { toast(e.message, "err"); }
}

async function removeDepo(id) {
  await api(`/api/depo/${id}`, { method: "DELETE" });
  loadDepo();
}

function syncDepoBtn() {
  const b = document.getElementById("depoToggle");
  if (!b) return;
  b.textContent = chartInDepo ? "Takiptesin" : "Takibe ekle";
}

function backFromChart() {
  hideViews();
  if (chartFrom === "depo") {
    document.getElementById("viewDepo").style.display = "";
    loadDepo();
  } else {
    document.getElementById("viewCatalog").style.display = "";
  }
}

async function openChart(name, from) {
  chartName = name;
  chartFrom = from || "listele";
  chartSpan = "1h";
  hideViews();
  document.getElementById("viewChart").style.display = "";
  document.getElementById("chartName").textContent = name;
  document.querySelectorAll(".span-btn").forEach((b) => b.classList.toggle("on", b.dataset.span === "1h"));
  await renderChart();
}

function setChartSpan(span) {
  chartSpan = span;
  document.querySelectorAll(".span-btn").forEach((b) => b.classList.toggle("on", b.dataset.span === span));
  renderChart();
}

function fmtChartLabel(t, span) {
  const d = new Date(t);
  if (Number.isNaN(d.getTime())) return t;
  if (span === "1h") {
    return d.toLocaleString("tr-TR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  }
  if (span === "1w") {
    return d.toLocaleDateString("tr-TR", { day: "2-digit", month: "short" });
  }
  if (span === "1m") {
    return d.toLocaleDateString("tr-TR", { month: "short", year: "numeric" });
  }
  return d.toLocaleDateString("tr-TR", { day: "2-digit", month: "short" });
}

async function renderChart() {
  const empty = document.getElementById("chartEmpty");
  const stats = document.getElementById("chartStats");
  try {
    empty.textContent = "geçmiş yükleniyor…";
    empty.style.display = "";
    const d = await api(`/api/catalog/history?game=${currentGame}&name=${encodeURIComponent(chartName)}&span=${chartSpan}`);
    chartInDepo = !!d.in_depo;
    syncDepoBtn();
    document.getElementById("chartNow").textContent = d.latest != null ? fmtTL(d.latest) : "—";
    const pts = d.points || [];
    if (stats) {
      if (pts.length >= 2 && d.first != null && d.latest != null) {
        const sign = (d.change_pct || 0) >= 0 ? "+" : "";
        stats.textContent = `${fmtChartLabel(d.from_t, chartSpan)} ${fmtTL(d.first)}  →  ${fmtChartLabel(d.to_t, chartSpan)} ${fmtTL(d.latest)}  (${sign}${d.change_pct}%)`;
      } else {
        stats.textContent = pts.length ? "Tek kayıt var — pazar geçmişi henüz yok." : "";
      }
    }
    if (!pts.length) {
      empty.style.display = "";
      empty.textContent = "Bu item için fiyat geçmişi bulunamadı.";
      if (priceChart) { priceChart.destroy(); priceChart = null; }
      return;
    }
    empty.style.display = "none";
    const ctx = document.getElementById("priceChart");
    if (priceChart) priceChart.destroy();
    let series = pts.map((p) => p.v);
    let labels = pts.map((p) => fmtChartLabel(p.t, chartSpan));
    if (series.length === 1) {
      series = [series[0], series[0]];
      labels = [labels[0], "şimdi"];
    }
    const low = d.low;
    const up = (d.change_pct || 0) >= 0;
    priceChart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: d.chart_label || (currentGame === "ko" ? "ByNoGame fiyat" : currentGame === "rust" ? "rust.tm fiyat" : "Steam fiyat"),
            data: series,
            borderColor: up ? "#a2d12d" : "#e85d5d",
            backgroundColor: up ? "rgba(162,209,45,.12)" : "rgba(232,93,93,.12)",
            fill: true,
            stepped: false,
            tension: 0.15,
            pointRadius: series.length < 50 ? 3 : 0,
            pointHoverRadius: 5,
            borderWidth: 2,
            spanGaps: true,
          },
          ...(low != null ? [{
            label: "Dönem düşük",
            data: series.map(() => low),
            borderColor: "#3a86ff",
            borderDash: [6, 4],
            pointRadius: 0,
            borderWidth: 1.5,
            fill: false,
          }] : []),
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { color: "#c8d0dc" } },
          tooltip: {
            callbacks: {
              label(ctx) {
                if (ctx.parsed.y == null) return ctx.dataset.label;
                return `${ctx.dataset.label}: ${fmtTL(ctx.parsed.y)}`;
              },
            },
          },
        },
        scales: {
          x: {
            ticks: {
              color: "#8b93a7",
              maxTicksLimit: ({ "1h": 12, "1d": 8, "1w": 8, "1m": 6 }[chartSpan] || 10),
              maxRotation: 0,
            },
            grid: { color: "rgba(255,255,255,.06)" },
          },
          y: {
            beginAtZero: false,
            ticks: {
              color: "#8b93a7",
              callback(v) {
                const d = Math.max(...series) < 30 ? 2 : 0;
                return Number(v).toLocaleString("tr-TR", { maximumFractionDigits: d }) + " ₺";
              },
            },
            grid: { color: "rgba(255,255,255,.06)" },
          },
        },
      },
    });
    ctx.parentElement.style.height = "360px";
  } catch (e) {
    empty.style.display = "";
    empty.textContent = e.message;
    if (stats) stats.textContent = "";
  }
}

async function toggleDepoFromChart() {
  if (chartInDepo) {
    await goTakipList();
    return;
  }
  await addDepoName(chartName, true);
}

function renderCurrent() {
  const grid = document.getElementById("itemsGrid");
  if (!ITEMS.length) {
    currentItemId = null;
    localStorage.removeItem("currentItemId_" + currentGame);
    const ui = GAME_UI[currentGame] || GAME_UI.cs2;
    grid.innerHTML = `<div class="empty"><div class="big">🖌️</div>
      <p>${ui.empty}</p></div>`;
    return;
  }
  let it = ITEMS.find((i) => i.id === currentItemId);
  if (!it) it = ITEMS[ITEMS.length - 1];
  currentItemId = it.id;
  localStorage.setItem("currentItemId_" + currentGame, it.id);
  grid.innerHTML = renderItem(it);
}

function enabledSourcesList() {
  const ui = GAME_UI[currentGame] || GAME_UI.cs2;
  const key = ui.settingsKey;
  return (SETTINGS[key] || SETTINGS.enabled_sources || Object.keys(SOURCES).join(",")).split(",");
}

function listingOffers(p) {
  const raw = (p && p.offers) || [];
  const rows = raw
    .filter((o) => o && o.price_try != null)
    .map((o) => ({ price: Number(o.price_try), url: o.url || p.url }));
  if (!rows.length && p && p.price_try != null) {
    rows.push({ price: Number(p.price_try), url: p.url });
  }
  rows.sort((a, b) => a.price - b.price);
  return rows.slice(0, 3).map((o, i, all) => ({
    rank: i + 1,
    price: o.price,
    url: o.url,
    diff_prev: i ? Math.round((o.price - all[i - 1].price) * 100) / 100 : null,
  }));
}

function renderOfferList(p) {
  const rows = listingOffers(p);
  if (!rows.length) return `<div class="val">${fmtTL(p.price_try)}</div><div class="orig">${fmtOrig(p)}</div>`;
  return rows.map((o) => {
    const gap = o.rank === 1
      ? `<span class="offer-gap">en ucuz ilan</span>`
      : `<span class="offer-gap">${o.rank - 1}. ilana göre <b>${fmtTL(o.diff_prev)}</b> fark</span>`;
    const body = `<span class="offer-rank">${o.rank}.</span><span class="offer-price">${fmtTL(o.price)}</span>${gap}`;
    return o.url
      ? `<a class="offer-line r${o.rank}" href="${esc(o.url)}" target="_blank" rel="noopener">${body}</a>`
      : `<div class="offer-line r${o.rank}">${body}</div>`;
  }).join("");
}

function renderItem(it) {
  const enabled = enabledSourcesList();
  const scanning = currentItemId === it.id && window._priceScan;
  const cells = enabled.filter((s) => SOURCES[s]).map((src) => {
    const p = it.prices[src];
    const label = SOURCES[src];
    if (!p) return `<div class="price-cell err"><div class="src">${label}</div><div class="val">${scanning ? "taranıyor…" : "henüz veri yok"}</div></div>`;
    if (p.error || p.price_try == null)
      return `<div class="price-cell err"><div class="src">${label}</div><div class="val">${esc(p.error || "veri yok")}</div></div>`;
    const cls = it.spread
      ? src === it.spread.low_source ? "low" : src === it.spread.high_source ? "high" : ""
      : "";
    const inner = `<div class="src">${label}</div><div class="offer-list">${renderOfferList(p)}</div>`;
    return `<div class="price-cell ${cls}">${inner}</div>`;
  }).join("");

  const spread = it.spread
    ? `<span class="spread-badge ${it.spread.spread_pct >= 10 ? "hot" : ""}">makas %${it.spread.spread_pct.toFixed(1)}</span>`
    : "";

  const alerts = it.alerts.map((a) => {
    const desc =
      a.kind === "below" ? `📉 ${a.source ? SOURCES[a.source] : "en ucuz"} ≤ ${fmtTL(a.threshold)}` :
      a.kind === "above" ? `📈 ${a.source ? SOURCES[a.source] : "en ucuz"} ≥ ${fmtTL(a.threshold)}` :
      `⚖️ makas ≥ %${a.threshold}`;
    return `<span class="alert-chip ${a.enabled ? "" : "disabled"}">
      ${desc}
      <button title="aç/kapat" onclick="toggleAlert(${a.id})">${a.enabled ? "⏸" : "▶"}</button>
      <button title="sil" onclick="deleteAlert(${a.id})">✕</button>
    </span>`;
  }).join("");

  const srcOpts = Object.entries(SOURCES)
    .map(([k, v]) => `<option value="${k}">${v}</option>`).join("");

  return `<div class="item-card" data-id="${it.id}">
    <div class="item-head">
      <span class="item-name">${esc(it.name)}</span>
      ${spread}
      <span class="spacer"></span>
      <button class="btn btn-primary btn-sm" onclick="followSearchItem(${it.id})">${TAKIP_NAMES.has(it.name) ? "Takiptesin" : "Takibe ekle"}</button>
      <button class="btn btn-ghost btn-sm" onclick="toggleAlertForm(${it.id})">+ alarm</button>
      <button class="btn btn-danger btn-sm" onclick="deleteItem(${it.id}, '${esc(it.name).replace(/'/g, "\\'")}')">sil</button>
    </div>
    <div class="price-row">${cells}</div>
    <div class="alerts-box">${alerts}</div>
    <div class="alert-form" id="alertForm-${it.id}">
      <select id="alertKind-${it.id}" onchange="onKindChange(${it.id})">
        <option value="below">fiyat altına inince</option>
        <option value="above">fiyat üstüne çıkınca</option>
        <option value="spread">siteler arası makas (%)</option>
      </select>
      <select id="alertSource-${it.id}"><option value="">en ucuz kaynak</option>${srcOpts}</select>
      <input type="number" id="alertThreshold-${it.id}" placeholder="eşik" step="any">
      <button class="btn btn-primary btn-sm" onclick="addAlert(${it.id})">kaydet</button>
    </div>
  </div>`;
}

function followSearchItem(id) {
  const it = ITEMS.find((x) => x.id === id);
  if (!it) return;
  return addDepoName(it.name, true);
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function toggleAlertForm(id) {
  document.getElementById(`alertForm-${id}`).classList.toggle("open");
}
function onKindChange(id) {
  const kind = document.getElementById(`alertKind-${id}`).value;
  document.getElementById(`alertSource-${id}`).style.display = kind === "spread" ? "none" : "";
  document.getElementById(`alertThreshold-${id}`).placeholder = kind === "spread" ? "% eşik" : "TL eşik";
}

/* ---------- arama & varyant seçimi ---------- */
async function searchItem() {
  const input = document.getElementById("itemInput");
  const q = input.value.trim();
  if (!q) return toast("Önce ürün adı yaz", "err");
  const btn = document.getElementById("searchBtn");
  btn.disabled = true;
  btn.textContent = "⏳ aranıyor…";
  try {
    const r = await api("/api/items/resolve", {
      method: "POST",
      body: JSON.stringify({ query: q, game: currentGame }),
    });
    if (r.variants) {
      showVariantModal(q, r.variants);
    } else {
      input.value = "";
      await selectItem(r.resolved);
    }
  } catch (e) { toast(e.message, "err"); }
  btn.disabled = false;
  btn.textContent = "🔍 Ara";
}

function showVariantModal(q, variants) {
  VARIANTS = variants;
  document.getElementById("variantHint").textContent =
    `"${q}" için ${variants.length} model bulundu — hangisini istiyorsun?`;
  document.getElementById("variantList").innerHTML = variants.map((v, i) =>
    `<button class="variant-btn" onclick="pickVariant(${i})">${esc(v)}</button>`
  ).join("");
  openModal("variantModal");
}

async function pickVariant(i) {
  closeModal("variantModal");
  document.getElementById("itemInput").value = "";
  await selectItem(VARIANTS[i]);
}

async function refreshItem(itemId, silent) {
  const btn = document.getElementById("refreshBtn");
  if (btn) btn.disabled = true;
  window._priceScan = true;
  const poll = setInterval(() => { loadItems().catch(() => {}); }, 1200);
  try {
    const r = await api(`/api/items/${itemId}/refresh`, { method: "POST" });
    if (r && r.ok === false) throw new Error(r.msg || "tarama atlandı");
    if (!silent) toast("Fiyatlar güncellendi 🎨", "ok");
    await loadItems();
    loadStatus();
  } catch (e) {
    toast(e.message, "err");
  } finally {
    clearInterval(poll);
    window._priceScan = false;
    if (btn) btn.disabled = false;
    await loadItems().catch(() => {});
  }
}

async function selectItem(name) {
  try {
    const r = await api("/api/items", {
      method: "POST",
      body: JSON.stringify({ names: name, game: currentGame }),
    });
    const data = await api(`/api/items?game=${currentGame}`);
    SOURCES = data.sources;
    ITEMS = data.items;
    const it = ITEMS.find((x) => x.name === name);
    if (it) {
      currentItemId = it.id;
      localStorage.setItem("currentItemId_" + currentGame, it.id);
    }
    renderCurrent();
    toast(r.added.length ? `"${name}" taranıyor…` : `"${name}" güncelleniyor…`, "ok");
    if (it) await refreshItem(it.id, true);
  } catch (e) { toast(e.message, "err"); }
}

async function deleteItem(id, name) {
  if (!confirm(`"${name}" silinsin mi?`)) return;
  await api(`/api/items/${id}`, { method: "DELETE" });
  if (currentItemId === id) {
    currentItemId = null;
    localStorage.removeItem("currentItemId_" + currentGame);
  }
  toast("Ürün silindi", "ok");
  loadItems();
}

/* ---------- sekmeler ---------- */
function switchView(v) {
  goSection(v === "search" ? "ara" : "opps");
}

/* ---------- fırsatlar ---------- */
async function loadOpportunities() {
  const btn = document.getElementById("oppRefreshBtn");
  btn.disabled = true;
  btn.textContent = "⏳";
  const minSpread = parseFloat(document.getElementById("oppMinSpread").value) || 0;
  const minDiscount = parseFloat(document.getElementById("oppMinDiscount").value) || 0;
  try {
    const d = await api(`/api/opportunities?min_spread=${minSpread}&min_discount=${minDiscount}&game=${currentGame}`);
    renderSpreads(d.spreads || []);
    renderDiscounts(d.discounts || []);
  } catch (e) { toast(e.message, "err"); }
  btn.disabled = false;
  btn.textContent = "↻ Yenile";
}

function renderSpreads(rows) {
  const box = document.getElementById("oppSpreads");
  if (!rows.length) {
    box.innerHTML = `<div class="empty small"><p>Şu an eşiği aşan makas yok.<br>
      Arama sekmesinden ürün ekledikçe burada karşılaştırma birikir.</p></div>`;
    return;
  }
  box.innerHTML = rows.map((r) => `
    <div class="opp-card">
      <div class="opp-head">
        <span class="opp-name">${esc(r.name)}</span>
        <span class="spread-badge ${r.spread_pct >= 15 ? "hot" : ""}">%${r.spread_pct.toFixed(1)} fark</span>
      </div>
      <div class="opp-compare">
        <div class="opp-side buy">
          <div class="opp-side-label">💰 En ucuz — ${esc(r.low_label)}</div>
          <div class="opp-side-price">${fmtTL(r.low)}</div>
          ${r.low_url ? `<a href="${esc(r.low_url)}" target="_blank" rel="noopener" class="opp-link">ilana git →</a>` : ""}
        </div>
        <div class="opp-arrow">➜</div>
        <div class="opp-side sell">
          <div class="opp-side-label">🏷️ En pahalı — ${esc(r.high_label)}</div>
          <div class="opp-side-price">${fmtTL(r.high)}</div>
          ${r.high_url ? `<a href="${esc(r.high_url)}" target="_blank" rel="noopener" class="opp-link">ilana git →</a>` : ""}
        </div>
        <div class="opp-profit">aradaki fark<br><b>${fmtTL(r.diff)}</b></div>
      </div>
    </div>`).join("");
}

function renderDiscounts(rows) {
  const box = document.getElementById("oppDiscounts");
  if (!rows.length) {
    box.innerHTML = `<div class="empty small"><p>Eşiği aşan indirim bulunamadı.</p></div>`;
    return;
  }
  box.innerHTML = rows.map((r) => `
    <div class="opp-card discount">
      <div class="opp-head">
        <span class="opp-name">${esc(r.name)}</span>
        <span class="spread-badge hot">-%${r.discount_pct.toFixed(0)}</span>
      </div>
      <div class="opp-discount-row">
        <span class="opp-old">${fmtTL(r.suggested)}</span>
        <span class="opp-new">${fmtTL(r.price)}</span>
        <span class="opp-qty">${r.quantity} adet</span>
        ${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener" class="opp-link">Skinport'ta gör →</a>` : ""}
      </div>
    </div>`).join("");
}

/* ---------- geçmiş aramalar ---------- */
function openHistory() {
  renderHistory();
  openModal("historyModal");
}

function cheapestOf(it) {
  let best = null;
  for (const [src, p] of Object.entries(it.prices || {})) {
    if (p.price_try != null && (!best || p.price_try < best.price)) {
      best = { price: p.price_try, src };
    }
  }
  return best;
}

function renderHistory() {
  const box = document.getElementById("historyList");
  if (!ITEMS.length) {
    box.innerHTML = `<div class="empty"><div class="big">🕘</div><p>Henüz geçmiş arama yok.</p></div>`;
    return;
  }
  box.innerHTML = [...ITEMS].reverse().map((it) => {
    const best = cheapestOf(it);
    const priceTxt = best ? `${fmtTL(best.price)} <span class="hist-src">(${SOURCES[best.src] || best.src})</span>` : "fiyat yok";
    const spread = it.spread ? `<span class="spread-badge ${it.spread.spread_pct >= 10 ? "hot" : ""}">%${it.spread.spread_pct.toFixed(1)}</span>` : "";
    const alarms = it.alerts.length ? `<span class="hist-alarms">🔔 ${it.alerts.length}</span>` : "";
    return `<div class="history-row ${it.id === currentItemId ? "active" : ""}">
      <div class="hist-info">
        <div class="hist-name">${esc(it.name)}</div>
        <div class="hist-meta">${priceTxt} ${spread} ${alarms}</div>
      </div>
      <button class="btn btn-primary btn-sm" onclick="showFromHistory(${it.id})">göster</button>
      <button class="btn btn-danger btn-sm" onclick="deleteFromHistory(${it.id})">sil</button>
    </div>`;
  }).join("");
}

function showFromHistory(id) {
  currentItemId = id;
  localStorage.setItem("currentItemId_" + currentGame, id);
  currentSection = "ara";
  setNav();
  hideViews();
  document.getElementById("viewSearch").style.display = "";
  renderCurrent();
  closeModal("historyModal");
}

async function deleteFromHistory(id) {
  const it = ITEMS.find((x) => x.id === id);
  if (!confirm(`"${it ? it.name : id}" geçmişten silinsin mi? (alarmları da silinir)`)) return;
  await api(`/api/items/${id}`, { method: "DELETE" });
  if (currentItemId === id) {
    currentItemId = null;
    localStorage.removeItem("currentItemId_" + currentGame);
  }
  await loadItems();
  renderHistory();
}

async function addAlert(itemId) {
  const kind = document.getElementById(`alertKind-${itemId}`).value;
  const source = document.getElementById(`alertSource-${itemId}`).value || null;
  const threshold = parseFloat(document.getElementById(`alertThreshold-${itemId}`).value);
  if (isNaN(threshold)) return toast("Eşik değeri gir", "err");
  try {
    await api("/api/alerts", {
      method: "POST",
      body: JSON.stringify({ item_id: itemId, kind, threshold, source: kind === "spread" ? null : source }),
    });
    toast("Alarm kuruldu 🔔", "ok");
    loadItems();
  } catch (e) { toast(e.message, "err"); }
}

async function deleteAlert(id) {
  await api(`/api/alerts/${id}`, { method: "DELETE" });
  loadItems();
}
async function toggleAlert(id) {
  await api(`/api/alerts/${id}/toggle`, { method: "POST" });
  loadItems();
}

/* ---------- ayarlar ---------- */
async function openSettings() {
  await loadItems();
  await loadSettings();
  renderSourceChecks();
  openModal("settingsModal");
}

async function loadSettings() {
  SETTINGS = await api("/api/settings");
  document.getElementById("tgToken").value = SETTINGS.telegram_token || "";
  document.getElementById("tgChat").value = SETTINGS.telegram_chat_id || "";
  document.getElementById("setInterval").value = SETTINGS.check_interval_min || 5;
  document.getElementById("setBitskins").value = SETTINGS.bitskins_api_key || "";
  renderSourceChecks();
}

function renderSourceChecks() {
  const box = document.getElementById("sourceChecks");
  const ui = GAME_UI[currentGame] || GAME_UI.cs2;
  const enabled = (SETTINGS[ui.settingsKey] || SETTINGS.enabled_sources || "").split(",");
  const all = Object.keys(SOURCES).length ? SOURCES : {};
  box.innerHTML = Object.entries(all).map(([k, v]) =>
    `<label><input type="checkbox" value="${k}" ${enabled.includes(k) ? "checked" : ""}> ${v}</label>`
  ).join("");
}

async function saveTelegram() {
  try {
    SETTINGS = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        telegram_token: document.getElementById("tgToken").value.trim(),
        telegram_chat_id: document.getElementById("tgChat").value.trim(),
      }),
    });
    toast("Telegram ayarları kaydedildi", "ok");
    closeModal("telegramModal");
  } catch (e) { toast(e.message, "err"); }
}

async function testTelegram() {
  try {
    await saveTelegram();
    openModal("telegramModal");
    await api("/api/telegram/test", { method: "POST" });
    toast("Test mesajı gönderildi ✈️", "ok");
  } catch (e) { toast("Telegram hatası: " + e.message, "err"); }
}

async function saveSettings() {
  const checked = [...document.querySelectorAll("#sourceChecks input:checked")].map((c) => c.value);
  const ui = GAME_UI[currentGame] || GAME_UI.cs2;
  const payload = {
    check_interval_min: document.getElementById("setInterval").value,
    bitskins_api_key: document.getElementById("setBitskins").value.trim(),
  };
  payload[ui.settingsKey] = checked.join(",");
  try {
    SETTINGS = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    toast("Ayarlar kaydedildi", "ok");
    closeModal("settingsModal");
    loadItems();
  } catch (e) { toast(e.message, "err"); }
}

/* ---------- durum & tarama ---------- */
async function refreshNow(silent) {
  const btn = document.getElementById("refreshBtn");
  btn.disabled = true;
  btn.textContent = "⏳ taranıyor…";
  try {
    await api("/api/refresh", { method: "POST" });
    if (!silent) toast("Tarama tamamlandı 🎨", "ok");
    await loadItems();
  } catch (e) { toast(e.message, "err"); }
  btn.disabled = false;
  btn.textContent = "↻ Şimdi Tara";
  loadStatus();
}

async function loadStatus() {
  try {
    const s = await api("/api/status");
    const el = document.getElementById("navStatus");
    const last = s.last_run ? new Date(s.last_run).toLocaleTimeString("tr-TR") : "—";
    const tg = SETTINGS.telegram_token && SETTINGS.telegram_chat_id ? "<b>bağlı</b>" : "ayarlanmadı";
    el.innerHTML = `son tarama: <b>${s.running ? "⏳ sürüyor" : last}</b><br>telegram: ${tg}`;
  } catch {}
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeSidebar();
});

/* ---------- başlangıç ---------- */
(async function init() {
  applyGameUi();
  goSection("ara");
  await loadSettings();
  await loadStatus();
  setInterval(() => {
    if (document.getElementById("viewSearch").style.display !== "none") loadItems();
  }, 60000);
  setInterval(loadStatus, 20000);
})();
