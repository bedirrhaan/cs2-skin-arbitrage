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
    desc: "CS2 itemlarını dokuz pazarda aynı anda izle — Skinport, DMarket, Bitskins, Kopazar, GameSatis, ByNoGame, CSFloat, İtemSatış ve Itemci. Fiyat eşiğin tutunca ya da siteler arası makas açılınca Telegram'dan haber alırsın.",
    placeholder: "örn. AK-47 | Vulcan veya P250 | Visions",
    hint: "Wear yazmana gerek yok: <code>AK-47 | Elite Build</code> yaz, varyantlar bulunur. <code>StatTrak™</code> ve <code>★</code> desteklenir.",
    empty: "Henüz arama yapılmadı. Yukarıdan bir CS2 skin ara,<br>fiyatları pazarlarda aynı anda gör.",
    settingsKey: "enabled_sources_cs2",
  },
  rust: {
    title: "Rust skinlerini izle.",
    desc: "Rust itemlarını Skinport, DMarket, rust.tm, ByNoGame, Waxpeer ve Steam Market üzerinde karşılaştır. USD fiyatlar otomatik TRY'ye çevrilir.",
    placeholder: "örn. Soul Taker AK47 veya Big Grin",
    hint: "Steam market adını yaz. Rust skinlerinde genelde wear yok; tam ad bulunursa doğrudan eklenir.",
    empty: "Henüz Rust araması yok. Yukarıdan bir skin ara,<br>altı pazarda fiyatları gör.",
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
  renderCurrent();
  if (document.getElementById("historyModal").classList.contains("open")) renderHistory();
}

function applyGameUi() {
  const ui = GAME_UI[currentGame] || GAME_UI.cs2;
  document.getElementById("heroTitle").textContent = ui.title;
  document.getElementById("heroDesc").textContent = ui.desc;
  document.getElementById("itemInput").placeholder = ui.placeholder;
  document.getElementById("searchHint").innerHTML = ui.hint;
  document.getElementById("tabGameCs2").classList.toggle("active", currentGame === "cs2");
  document.getElementById("tabGameRust").classList.toggle("active", currentGame === "rust");
  document.getElementById("tabGameKo").classList.toggle("active", currentGame === "ko");
  const hideDiscounts = currentGame === "rust" || currentGame === "ko";
  document.getElementById("oppDiscountTitle").style.display = hideDiscounts ? "none" : "";
  document.getElementById("oppDiscountHint").style.display = hideDiscounts ? "none" : "";
  document.getElementById("oppDiscounts").style.display = hideDiscounts ? "none" : "";
  if (document.getElementById("settingsModal").classList.contains("open")) renderSourceChecks();
}

function switchGame(game) {
  if (game === currentGame) return;
  currentGame = game;
  localStorage.setItem("currentGame", game);
  currentItemId = parseInt(localStorage.getItem("currentItemId_" + game) || "", 10) || null;
  applyGameUi();
  loadItems();
  if (document.getElementById("viewOpps").style.display !== "none") loadOpportunities();
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

function renderItem(it) {
  const enabled = enabledSourcesList();
  const cells = enabled.filter((s) => SOURCES[s]).map((src) => {
    const p = it.prices[src];
    const label = SOURCES[src];
    if (!p) return `<div class="price-cell err"><div class="src">${label}</div><div class="val">henüz veri yok</div></div>`;
    if (p.error || p.price_try == null)
      return `<div class="price-cell err"><div class="src">${label}</div><div class="val">${esc(p.error || "veri yok")}</div></div>`;
    const cls = it.spread
      ? src === it.spread.low_source ? "low" : src === it.spread.high_source ? "high" : ""
      : "";
    const inner = `<div class="src">${label}</div><div class="val">${fmtTL(p.price_try)}</div><div class="orig">${fmtOrig(p)}</div>`;
    return `<div class="price-cell ${cls}">${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${inner}</a>` : inner}</div>`;
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
  try {
    await api(`/api/items/${itemId}/refresh`, { method: "POST" });
    if (!silent) toast("Fiyatlar güncellendi 🎨", "ok");
    await loadItems();
    loadStatus();
  } catch (e) {
    if (!silent) toast(e.message, "err");
  }
  if (btn) btn.disabled = false;
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
  const search = v === "search";
  document.getElementById("viewSearch").style.display = search ? "" : "none";
  document.getElementById("viewOpps").style.display = search ? "none" : "";
  document.getElementById("tabSearch").classList.toggle("active", search);
  document.getElementById("tabOpps").classList.toggle("active", !search);
  if (!search) loadOpportunities();
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

/* ---------- başlangıç ---------- */
(async function init() {
  applyGameUi();
  await loadSettings();
  await loadItems();
  await loadStatus();
  setInterval(loadItems, 60000);
  setInterval(loadStatus, 20000);
})();
