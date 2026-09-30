/* Travel Episodes Studio — rate library, trips, quotes. Plain JS, no build step. */
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const num = n => n == null || n === "" ? "" : Number(n).toLocaleString("en-IN", {maximumFractionDigits: 2});
const money = (n, c) => n == null ? "—" : (c === "INR" || !c ? "₹" + Number(n).toLocaleString("en-IN", {maximumFractionDigits: 0}) : `${c} ${num(n)}`);
const words = s => String(s ?? "").replaceAll("_", " ");
const range = (a, b) => b != null && b !== a ? `${num(a)}–${num(b)}` : num(a);
const fmtDate = iso => iso ? new Date(iso.slice(0, 10) + "T00:00:00").toLocaleDateString("en-GB", {day: "numeric", month: "short", year: "numeric"}) : "";
const todayISO = () => new Date().toISOString().slice(0, 10);
const STATUSES = ["enquiry", "quoted", "confirmed", "completed", "lost"];
const STATUS_COLOR = {enquiry: "#a5a4d4", quoted: "#fae7b6", confirmed: "#8286cb", completed: "#4f4c4d", lost: "#e4bdae"};

// small solid icons (generic)
const IC = {
  home: '<path d="M3 11 12 3l9 8v10h-6v-6H9v6H3z" fill="currentColor"/>',
  trips: '<path d="M4 7h16v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2zm5-4h6a2 2 0 0 1 2 2v2h-2V5H9v2H7V5a2 2 0 0 1 2-2z" fill="currentColor"/>',
  catalog: '<path d="M4 4h7v7H4zm9 0h7v7h-7zM4 13h7v7H4zm9 0h7v7h-7z" fill="currentColor"/>',
  docs: '<path d="M6 2h8l6 6v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm7 1.5V9h5.5z" fill="currentColor"/>',
  tools: '<path d="M4 3h16v4H4zm0 6h7v12H4zm9 0h7v5h-7zm0 7h7v5h-7z" fill="currentColor"/>',
  settings: '<path d="M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8zm-1-6h2l.6 3 2.3 1 2.6-1.7 1.4 1.4L18.2 8.3l1 2.3 3 .6v2l-3 .6-1 2.3 1.7 2.6-1.4 1.4-2.6-1.7-2.3 1-.6 3h-2l-.6-3-2.3-1-2.6 1.7-1.4-1.4 1.7-2.6-1-2.3-3-.6v-2l3-.6 1-2.3L4.1 5.7l1.4-1.4 2.6 1.7 2.3-1z" fill="currentColor" fill-rule="evenodd"/>',
  down: '<path d="M11 3h2v10l3.5-3.5 1.4 1.4L12 16.8l-5.9-5.9 1.4-1.4L11 13zM4 19h16v2H4z" fill="currentColor"/>',
  share: '<path d="M18 16a3 3 0 1 1-2.9 3.7L8.6 16.4a3 3 0 1 1 0-4.8l6.5-3.3A3 3 0 1 1 16 10l-6.5 3.3.1.7-.1.7 6.5 3.3A3 3 0 0 1 18 16z" fill="currentColor"/>',
  phone: '<path d="M6.6 10.8a15 15 0 0 0 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1A17 17 0 0 1 3 4c0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1z" fill="currentColor"/>',
  chat: '<path d="M4 3h16a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H9l-5 4v-4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" fill="currentColor"/>',
  plus: '<path d="M11 4h2v7h7v2h-7v7h-2v-7H4v-2h7z" fill="currentColor"/>',
  quotes: '<path d="M5 2h14a1 1 0 0 1 1 1v18l-3-2-2 2-3-2-3 2-2-2-3 2V3a1 1 0 0 1 1-1zm3 5v2h8V7zm0 4v2h8v-2zm0 4v2h5v-2z" fill="currentColor"/>',
};
const icon = n => `<svg viewBox="0 0 24 24" aria-hidden="true">${IC[n]}</svg>`;
const icon16 = n => `<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">${IC[n]}</svg>`;

// ---------------------------------------------------------------- API (session cookie; signed-in admins only)
function toLogin() { location.href = "/login?next=" + encodeURIComponent(location.pathname + location.hash); }
async function api(path, opts = {}) {
  const headers = {"X-Requested-With": "studio"};
  if (opts.body && !(opts.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const r = await fetch(path, {...opts, headers, credentials: "same-origin"});
  if (r.status === 401 && !path.startsWith("/api/auth/password")) { toLogin(); throw new Error("Please sign in again"); }
  if (opts.raw) { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText); return r; }
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json().catch(() => ({})) : await r.text();
  if (!r.ok) throw new Error((data && data.detail) || r.statusText);
  return data;
}
const post = (p, body) => api(p, {method: "POST", body: body instanceof FormData ? body : JSON.stringify(body ?? {})});
const patch = (p, body) => api(p, {method: "PATCH", body: JSON.stringify(body)});
const put = (p, body) => api(p, {method: "PUT", body: JSON.stringify(body)});
const del = p => api(p, {method: "DELETE"});
let toastT;
function toast(text, bad) { const t = $("#toast"); t.textContent = text; t.className = bad ? "bad" : ""; t.style.display = "block"; clearTimeout(toastT); toastT = setTimeout(() => t.style.display = "none", 3200); }
async function download(path, fallbackName = "download") {
  try {
    const r = await api(path, {raw: true});
    const cd = r.headers.get("content-disposition") || "";
    const name = (cd.match(/filename="([^"]+)"/) || [])[1] || fallbackName;
    const url = URL.createObjectURL(await r.blob());
    const a = Object.assign(document.createElement("a"), {href: url, download: name}); document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000); toast(`Downloaded ${name}`);
  } catch (e) { toast(e.message, true); }
}
async function openInTab(path) {
  const w = window.open("", "_blank");
  try { const r = await api(path, {raw: true}); const url = URL.createObjectURL(await r.blob()); if (w) w.location = url; else location.href = url; }
  catch (e) { if (w) w.close(); toast(e.message, true); }
}
async function copy(text, okMsg) {
  try { await navigator.clipboard.writeText(text); toast(okMsg || "Copied"); }
  catch (e) { prompt("Copy this:", text); }
}
function menu(label, items, cls = "") {   // items: [{label, sub, act}] | "hr"
  const id = "m" + Math.random().toString(36).slice(2, 8);
  setTimeout(() => {
    const m = document.getElementById(id); if (!m) return;
    $("button.btn", m).onclick = e => { e.stopPropagation(); $$(".menu.open").forEach(x => x !== m && x.classList.remove("open")); m.classList.toggle("open"); };
    $$(".pop [data-i]", m).forEach(b => b.onclick = () => { m.classList.remove("open"); items[+b.dataset.i].act(); });
  });
  return `<div class="menu" id="${id}"><button class="btn ${cls}">${label}</button><div class="pop">${items.map((it, i) => it === "hr" ? "<hr>" :
    `<button data-i="${i}">${esc(it.label)}${it.sub ? `<small>${esc(it.sub)}</small>` : ""}</button>`).join("")}</div></div>`;
}
document.addEventListener("click", () => $$(".menu.open").forEach(m => m.classList.remove("open")));
const dots = () => `<div class="dots" aria-hidden="true">${"<i></i>".repeat(36)}</div>`;
const empty = (text, action = "") => `<div class="empty"><img src="/static/brand/emblem.png" alt=""><div>${text}</div>${action}</div>`;
let SETTINGS = null, ME = null;
async function settings() { SETTINGS ??= await api("/api/settings"); return SETTINGS; }

// ---------------------------------------------------------------- routing
const PAGES = [["home", "Dashboard"], ["trips", "Trips"], ["quotes", "Quotations"], ["catalog", "Catalog"], ["docs", "Documents"], ["tools", "Tools"], ["settings", "Settings"]];
const ROUTES = {home: pageHome, trips: pageTrips, quotes: pageQuotes, catalog: pageCatalog, docs: pageDocs, tools: pageTools, settings: pageSettings};
$("#mainnav").innerHTML = PAGES.map(([k, l]) => `<button data-p="${k}">${icon(k)}<span class="lbl">${l}</span><span class="count hidden" id="cnt-${k}"></span></button>`).join("");
$$("#mainnav button").forEach(b => b.onclick = () => go(b.dataset.p));
function go(page, arg) {
  const h = page + (arg ? "/" + arg : "");
  if (location.hash.slice(1) === h) route(); else location.hash = h;
}
async function route() {
  const [page, arg] = (location.hash.slice(1) || "home").split("/");
  $$("#mainnav button").forEach(b => b.classList.toggle("on", b.dataset.p === page));
  // each navigation renders into its own container: a slower page from an earlier click can't overwrite this one
  const main = document.createElement("div");
  main.innerHTML = `<div class="muted">Loading…</div>`;
  $("#main").replaceChildren(main);
  try { await (ROUTES[page] || pageHome)(main, arg); } catch (e) { if (main.isConnected) main.innerHTML = `<div class="card"><div class="issue error">${esc(e.message)}</div></div>`; }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
async function refreshBadges() {
  try { const s = await api("/api/catalog/summary"); const c = $("#cnt-docs"); c.textContent = s.documents_to_review; c.classList.toggle("hidden", !s.documents_to_review); } catch (e) {}
}
function wireGo(root) {
  $$("[data-trip]", root).forEach(el => el.onclick = () => go("trips", el.dataset.trip));
  $$("[data-go]", root).forEach(el => el.onclick = () => { const [p, a] = el.dataset.go.split("/"); go(p, a); });
  $$("[data-stop]", root).forEach(el => el.addEventListener("click", e => e.stopPropagation()));   // links inside clickable rows
}

// ================================================================ DASHBOARD
async function pageHome(main) {
  const d = await api("/api/dashboard");
  const h = new Date().getHours(), greet = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  const P = d.pipeline, M = d.month, L = d.library;
  const open = P.enquiry.count + P.quoted.count;
  const totalVal = STATUSES.reduce((a, s) => a + (s === "lost" ? 0 : P[s].value), 0) || 1;
  const srcMax = Math.max(1, ...d.lead_sources.map(s => s.trips));
  const trow = t => `<tr class="click" data-trip="${t.id}"><td><span style="font-weight:500">${esc(t.title)}</span><div class="small muted">${esc(t.customer_name || "")}${t.assigned_to ? " · " + esc(t.assigned_to) : ""}</div></td>`;
  main.innerHTML = `
  <div class="card hero">${dots()}<h1>${greet}.</h1>
    <p>${d.follow_ups.length ? `${d.follow_ups.length} follow-up${d.follow_ups.length > 1 ? "s" : ""} due` : "No follow-ups due today"}${open ? ` · ${open} open enquir${open > 1 ? "ies" : "y"}` : ""}</p>
    <div class="actions"><button class="btn" id="h-new">${icon("plus")} New trip</button><button class="btn" id="h-up">${icon("docs")} Upload rate sheet</button><button class="btn" id="h-cat">${icon("catalog")} Browse packages</button></div></div>

  <div class="kpis">
    <div class="kpi"><small>Enquiries this month</small><b>${M.enquiries}</b><span>${open} still open</span></div>
    <div class="kpi"><small>Quoted this month</small><b>${money(M.quoted_value)}</b></div>
    <div class="kpi"><small>Confirmed this month</small><b class="accent">${money(M.confirmed_value)}</b><span>${M.confirmed} trip${M.confirmed === 1 ? "" : "s"}</span></div>
    <div class="kpi"><small>Markup earned</small><b>${money(M.profit)}</b><span>this month</span></div>
    <div class="kpi"><small>Conversion</small><b>${d.conversion_pct == null ? "—" : d.conversion_pct + "%"}</b><span>won of decided trips</span></div>
    <div class="kpi"><small>To collect</small><b>${money(d.balance_due)}</b><span>balance on confirmed trips</span></div>
  </div>

  <div class="grid g2">
    <div class="card"><h2>Follow-ups due ${d.follow_ups.length ? `<span class="pill bad">${d.follow_ups.length}</span>` : ""}</h2>
      ${d.follow_ups.length ? `<table><tbody>${d.follow_ups.map(t => `${trow(t)}<td><span class="pill ${t.status}">${t.status}</span></td>
        <td class="num"><span class="${t.overdue_days ? "due" : ""}">${t.overdue_days ? t.overdue_days + "d overdue" : "today"}</span></td>
        <td class="num">${t.customer_phone ? `<a class="icon" href="tel:${esc(t.customer_phone)}" title="Call" data-stop>${icon16("phone")}</a><a class="icon" target="_blank" href="https://wa.me/${esc(t.customer_phone.replace(/\D/g, ""))}" title="WhatsApp" data-stop>${icon16("chat")}</a>` : ""}</td></tr>`).join("")}</tbody></table>`
        : empty("All caught up. Give any enquiry a follow-up date and it shows up here on that day.")}
    </div>
    <div class="card"><h2>Pipeline <button class="link" data-go="trips">open board</button></h2>
      <div class="pbar">${STATUSES.filter(s => s !== "lost").map(s => `<i style="width:${100 * P[s].value / totalVal}%;background:${STATUS_COLOR[s]}"></i>`).join("")}</div>
      <div class="legend">${STATUSES.map(s => `<span style="--c:${STATUS_COLOR[s]}">${s} · ${P[s].count}</span>`).join("")}</div>
      <table style="margin-top:12px"><tbody>${STATUSES.map(s => `<tr><td style="text-transform:capitalize">${s}</td><td class="num">${P[s].count}</td><td class="num">${money(P[s].value)}</td></tr>`).join("")}</tbody></table>
    </div>
  </div>

  <div class="grid g3">
    <div class="card"><h2>Where business comes from</h2>
      ${d.lead_sources.length ? d.lead_sources.map(s => `<div style="margin:10px 0"><div class="row between small"><span>${esc(s.source)}</span><span class="muted">${s.trips} trip${s.trips > 1 ? "s" : ""} · ${s.confirmed} won · ${money(s.value)}</span></div>
        <div class="bar" style="width:${100 * s.trips / srcMax}%"></div></div>`).join("") : empty("Set the lead source on trips to see which channels bring business.")}
    </div>
    <div class="card"><h2>Departing in 30 days</h2>
      ${d.upcoming_departures.length ? `<table><tbody>${d.upcoming_departures.map(t => `${trow(t)}<td class="num">${fmtDate(t.start_date)}<div class="small ${t.balance > 0 ? "due" : "muted"}">${t.balance > 0 ? money(t.balance) + " due" : "paid"}</div></td></tr>`).join("")}</tbody></table>` : empty("No confirmed departures in the next 30 days.")}
    </div>
    <div class="card"><h2>Rate library <button class="link" data-go="catalog">browse</button></h2>
      <table><tbody>
        <tr><td>Packages</td><td class="num">${L.packages}</td></tr><tr><td>Hotels</td><td class="num">${L.hotels} <span class="muted small">(${L.hotels_with_rates} with rates)</span></td></tr>
        <tr><td>Activities &amp; transfers</td><td class="num">${L.services}</td></tr><tr><td>Places</td><td class="num">${L.places}</td></tr><tr><td>Suppliers</td><td class="num">${L.suppliers}</td></tr>
        ${L.documents_to_review ? `<tr class="click" data-go="docs"><td><span class="pill warn">To review</span></td><td class="num">${L.documents_to_review} document${L.documents_to_review > 1 ? "s" : ""}</td></tr>` : ""}
      </tbody></table>
      ${d.expiring.length ? `<h3>Rates expiring in 30 days</h3>${d.expiring.map(x => `<div class="small">${esc(x.name)} <span class="muted">· until ${fmtDate(x.last_valid_date)}</span></div>`).join("")}` : ""}
    </div>
  </div>

  <div class="card"><h2>Recent trips <button class="link" data-go="trips">all trips</button></h2>
    ${d.recent.length ? `<div class="scroll"><table><thead><tr><th>Trip</th><th>Status</th><th>Travel</th><th class="num">Value</th></tr></thead><tbody>
      ${d.recent.map(t => `${trow(t)}<td><span class="pill ${t.status}">${t.status}</span></td><td>${fmtDate(t.start_date)}</td><td class="num">${money(t.sell, t.currency)}</td></tr>`).join("")}</tbody></table></div>`
      : empty("No trips yet.", `<button class="btn primary" style="margin-top:10px" data-go="trips/new">${icon("plus")} Create the first trip</button>`)}
  </div>`;
  $("#h-new").onclick = () => go("trips", "new");
  $("#h-up").onclick = () => go("docs");
  $("#h-cat").onclick = () => go("catalog");
  wireGo(main);
}

// ================================================================ TRIPS (board / list)
let tripView = "board";
async function pageTrips(main, arg) {
  if (arg === "new") return newTrip(main);
  if (arg) return tripWorkspace(main, +arg);
  const [rows, st] = await Promise.all([api(tripView === "templates" ? "/api/templates" : "/api/trips"), settings()]);
  main.innerHTML = `<div class="pagehead"><div><h1>Trips</h1><p>Every enquiry, from first message to completed trip.</p></div>
    <div class="row">${menu(`${icon("down")} Export`, [{label: "All trips (CSV)", sub: "customer, status, value, paid, balance", act: () => download("/api/export/trips.csv")},
      {label: "Everything (Excel)", sub: "trips + the full rate library", act: () => download("/api/export/library.xlsx")}])}
      <button class="btn primary" id="t-new">${icon("plus")} New trip</button></div></div>
    <div class="card"><div class="row between center" style="margin-bottom:14px">
      <div class="row center"><input id="t-q" placeholder="Search customer, trip, destination" style="width:280px">
        <select id="t-owner"><option value="">Everyone</option>${st.team.map(m => `<option>${esc(m.name)}</option>`).join("")}</select>
        <select id="t-src"><option value="">All sources</option>${st.lead_sources.map(s => `<option>${esc(s)}</option>`).join("")}</select></div>
      <div class="subnav" style="margin:0"><button data-v="board" class="${tripView === "board" ? "on" : ""}">Board</button><button data-v="list" class="${tripView === "list" ? "on" : ""}">List</button><button data-v="templates" class="${tripView === "templates" ? "on" : ""}" title="Your own ready-made itineraries">Templates</button></div></div>
      <div id="t-body"></div></div>`;
  $("#t-new").onclick = () => go("trips", "new");
  $$(".subnav [data-v]", main).forEach(b => b.onclick = () => { tripView = b.dataset.v; pageTrips(main); });
  const draw = () => {
    const q = $("#t-q").value.toLowerCase(), o = $("#t-owner").value, sr = $("#t-src").value;
    const list = rows.filter(t => (!q || [t.title, t.customer_name, t.destination].join(" ").toLowerCase().includes(q)) && (!o || t.assigned_to === o) && (!sr || t.lead_source === sr));
    const fu = t => t.follow_up_date ? `<span class="${t.follow_up_date <= todayISO() && ["enquiry", "quoted"].includes(t.status) ? "due" : ""}">follow up ${fmtDate(t.follow_up_date)}</span>` : "";
    if (tripView === "templates") {
      $("#t-body").innerHTML = rows.length ? `<div class="cards">${list.map(t => `<div class="pcard" data-trip="${t.id}"><h4>${esc(t.title)}</h4><div class="small muted">${esc(t.destination || "")} · ${t.days} days${t.options ? ` · ${t.options} hotel options` : ""}</div>
        <div class="price">${t.sell ? `${t.is_from_price ? "from " : ""}<b>${money(t.sell, t.currency)}</b> for ${t.travellers}` : ""}</div></div>`).join("")}</div>`
        : empty("No templates yet. Open a trip you often sell and choose More → Save as template.");
      wireGo(main); return;
    }
    if (!rows.length) { $("#t-body").innerHTML = empty("No trips yet. Start one from a package or from scratch.", `<button class="btn primary" style="margin-top:10px" data-go="trips/new">${icon("plus")} New trip</button>`); wireGo(main); return; }
    if (tripView === "board") {
      $("#t-body").innerHTML = `<div class="board">${STATUSES.map(s => { const c = list.filter(t => t.status === s);
        return `<div class="col"><h4>${s} <span>${c.length} · ${money(c.reduce((a, t) => a + (t.sell || 0), 0))}</span></h4>
        ${c.map(t => `<div class="tcard" data-trip="${t.id}"><b>${esc(t.title)}</b><div class="meta">${esc([t.customer_name, t.destination].filter(Boolean).join(" · "))}</div>
          <div class="meta">${t.start_date ? fmtDate(t.start_date) + " · " : ""}${t.travellers} pax · <span style="font-weight:600;color:var(--ink)">${t.is_from_price ? "from " : ""}${money(t.sell, t.currency)}</span>${t.quotations ? ` · ${t.quotations} quote${t.quotations > 1 ? "s" : ""}` : ""}</div>
          <div class="meta">${esc(t.assigned_to || "")}${t.assigned_to && t.follow_up_date ? " · " : ""}${fu(t)}</div></div>`).join("") || `<div class="small muted" style="padding:6px">—</div>`}</div>`; }).join("")}</div>`;
    } else {
      $("#t-body").innerHTML = `<div class="scroll"><table><thead><tr><th>Trip</th><th>Customer</th><th>Status</th><th>Travel</th><th>Owner</th><th>Source</th><th>Follow-up</th><th class="num">Value</th><th class="num">Balance</th></tr></thead><tbody>
        ${list.map(t => `<tr class="click" data-trip="${t.id}"><td>${esc(t.title)}</td><td>${esc(t.customer_name || "")}</td><td><span class="pill ${t.status}">${t.status}</span></td><td>${fmtDate(t.start_date)}</td>
          <td>${esc(t.assigned_to || "")}</td><td>${esc(t.lead_source || "")}</td><td>${fu(t)}</td><td class="num">${money(t.sell, t.currency)}</td><td class="num">${t.status === "confirmed" && t.balance > 0 ? money(t.balance, t.currency) : ""}</td></tr>`).join("")}</tbody></table></div>`;
    }
    wireGo(main);
  };
  ["#t-q", "#t-owner", "#t-src"].forEach(s => $(s).oninput = draw);
  draw();
}

let pendingNewTrip = null, packagesCache = null;
async function packageOptions() { packagesCache ??= await api("/api/catalog/packages"); return packagesCache; }

async function newTrip(main) {
  const pre = pendingNewTrip || {}; pendingNewTrip = null;
  const [pk, st, tpls] = await Promise.all([packageOptions(), settings(), api("/api/templates")]);
  main.innerHTML = `<div class="pagehead"><div><div class="small muted"><button class="link" data-go="trips">Trips</button> / new</div><h1>New trip</h1><p>Start from a supplier package, one of your templates, or build it day by day.</p></div></div>
  <div class="card">${dots()}
    <h3 style="margin-top:0">Customer</h3>
    <div class="row"><label class="grow">Trip title<input id="n-title" class="w100" value="${esc(pre.title || "")}" placeholder="Kashmir for the Iyer family"></label>
      <label>Customer name<input id="n-cust"></label><label>Phone / WhatsApp<input id="n-phone" placeholder="+91"></label><label>Email<input id="n-email" type="email"></label></div>
    <div class="row"><label>Lead source<select id="n-src"><option value="">—</option>${st.lead_sources.map(s => `<option>${esc(s)}</option>`).join("")}</select></label>
      <label>Handled by<select id="n-owner"><option value="">—</option>${st.team.map(m => `<option>${esc(m.name)}</option>`).join("")}</select></label>
      <label>Follow up on<input type="date" id="n-fu" value="${todayISO()}"></label></div>
    <h3>Travellers</h3>
    <div class="row"><label>Start date<input type="date" id="n-start" value="${esc(pre.start_date || "")}"></label>
      <label>Adults<input type="number" id="n-ad" class="small" min="1" value="${pre.adults || 2}"></label>
      <label>Adults on extra bed<input type="number" id="n-eb" class="small" min="0" value="${pre.extra_beds || 0}"></label>
      <label>Child with bed<input type="number" id="n-cwb" class="small" min="0" value="${pre.children_with_bed || 0}"></label>
      <label>Child no bed<input type="number" id="n-cnb" class="small" min="0" value="${pre.children_without_bed || 0}"></label>
      <label>Markup %<input type="number" id="n-mk" class="small" value="${st.quote.default_markup_pct}"></label>
      <label>GST %<input type="number" id="n-gst" class="small" value="${st.quote.default_gst_pct}"></label></div>
    <h3>Start from</h3>
    <div class="row"><label class="grow">Package or template<select id="n-pkg" class="w100"><option value="">Blank trip — build day by day</option>
      ${tpls.length ? `<optgroup label="Your templates">${tpls.map(t => `<option value="t${t.id}" ${pre.template_id == t.id ? "selected" : ""}>${esc(t.title)} · ${t.days} days</option>`).join("")}</optgroup>` : ""}
      <optgroup label="Supplier packages">${pk.map(p => `<option value="${p.id}" ${pre.package_id == p.id ? "selected" : ""}>${esc(p.title)} · ${esc(p.supplier || "")}${p.from_price ? " · from " + money(p.from_price, p.currency) : ""}</option>`).join("")}</optgroup></select></label>
      <label>Hotel category<select id="n-cat"></select></label>
      <label class="check" style="margin-bottom:20px" id="n-allbox"><input type="checkbox" id="n-all">quote every category as options</label></div>
    <div class="row" style="margin-top:6px"><button class="btn primary" id="n-go">Create trip</button><button class="btn" data-go="trips">Cancel</button></div></div>`;
  const fillCats = () => { const p = pk.find(x => x.id == $("#n-pkg").value);
    $("#n-cat").innerHTML = (p?.categories || []).map(c => `<option ${c === pre.category ? "selected" : ""}>${esc(c)}</option>`).join("") || `<option value="">—</option>`;
    $("#n-allbox").classList.toggle("hidden", !(p?.categories || []).length); $("#n-cat").disabled = !p; };
  $("#n-pkg").onchange = fillCats; fillCats(); wireGo(main);
  $("#n-go").onclick = async () => {
    const body = {title: $("#n-title").value || "New trip", customer_name: $("#n-cust").value, customer_phone: $("#n-phone").value, customer_email: $("#n-email").value,
      lead_source: $("#n-src").value || null, assigned_to: $("#n-owner").value || null, follow_up_date: $("#n-fu").value || null,
      start_date: $("#n-start").value || null, adults: +$("#n-ad").value, extra_beds: +$("#n-eb").value, children_with_bed: +$("#n-cwb").value,
      children_without_bed: +$("#n-cnb").value, markup_pct: +$("#n-mk").value, gst_pct: +$("#n-gst").value};
    const pick = $("#n-pkg").value;
    if (pick.startsWith("t")) body.template_id = +pick.slice(1);
    else if (pick) { body.package_id = +pick; body.category = $("#n-cat").value; body.all_categories = $("#n-all").checked; }
    try { const t = await post("/api/trips", body); toast("Trip created"); go("trips", t.id); } catch (e) { toast(e.message, true); }
  };
}

// ---------------------------------------------------------------- trip workspace
let T = null;
async function tripWorkspace(main, id) {
  T = await api(`/api/trips/${id}`);
  await settings();
  drawTrip(main);
}

function shareUrl(t) { return t.share_token ? `${location.origin}/share/${t.share_token}` : null; }
async function ensureShare() { if (!T.share_token) T = await post(`/api/trips/${T.id}/share`, {enable: true}); return shareUrl(T); }
function shareText(url) {
  const tt = T.totals;
  return `Hi${T.customer_name ? " " + T.customer_name.split(" ")[0] : ""}, here is your ${T.title} plan from Travel Episodes` +
    (T.share_prices && tt.sell ? ` (${money(tt.sell, tt.currency)} for ${tt.travellers} traveller${tt.travellers > 1 ? "s" : ""})` : "") + `:\n${url}`;
}

function drawTrip(main) {
  const t = T, tt = t.totals, cur = tt.currency, st = SETTINGS;
  const phoneDigits = (t.customer_phone || "").replace(/\D/g, "");
  const shareMenu = menu(`${icon("share")} Share`, [
    {label: "Copy client link", sub: t.share_token ? "link is live" : "creates a private link for the customer", act: async () => { const u = await ensureShare(); await copy(u, "Link copied"); drawTrip(main); }},
    {label: "Send on WhatsApp", sub: phoneDigits ? "to " + t.customer_phone : "pick the contact in WhatsApp", act: async () => { const u = await ensureShare(); window.open(`https://wa.me/${phoneDigits}?text=${encodeURIComponent(shareText(u))}`, "_blank"); drawTrip(main); }},
    {label: "Send by email", sub: t.customer_email || "opens your mail app", act: async () => { const u = await ensureShare(); location.href = `mailto:${t.customer_email || ""}?subject=${encodeURIComponent(t.title + " · Travel Episodes")}&body=${encodeURIComponent(shareText(u))}`; drawTrip(main); }},
    ...(navigator.share ? [{label: "Share…", sub: "phone share sheet", act: async () => { const u = await ensureShare(); navigator.share({title: t.title, text: shareText(u), url: u}).catch(() => {}); }}] : []),
    {label: "Copy itinerary as text", sub: "paste into WhatsApp or notes", act: async () => copy(await api(`/api/trips/${t.id}/text`), "Itinerary text copied")},
    "hr",
    {label: t.share_prices ? "Hide prices on the client link" : "Show prices on the client link", act: async () => { T = await post(`/api/trips/${t.id}/share`, {enable: !!t.share_token, prices: !t.share_prices}); drawTrip(main); toast("Updated"); }},
    ...(t.share_token ? [{label: "Open client link", act: () => window.open(shareUrl(t), "_blank")}, {label: "Turn off client link", sub: "the old link stops working", act: async () => { T = await post(`/api/trips/${t.id}/share`, {enable: false}); drawTrip(main); toast("Link turned off"); }}] : []),
  ]);
  const dlMenu = menu(`${icon("down")} Download`, [
    {label: "Quote PDF", sub: "branded, with prices", act: () => download(`/api/trips/${t.id}/pdf`)},
    {label: "Itinerary PDF", sub: "branded, without prices", act: () => download(`/api/trips/${t.id}/pdf?prices=false`)},
    {label: "Preview / print PDF", act: () => openInTab(`/api/trips/${t.id}/pdf`)},
    "hr",
    {label: "Excel workbook", sub: "itinerary + costing sheets", act: () => download(`/api/trips/${t.id}/xlsx`)},
    {label: "Costing (CSV)", act: () => download(`/api/trips/${t.id}/csv`)},
    {label: "Itinerary (CSV)", act: () => download(`/api/trips/${t.id}/csv?part=itinerary`)},
  ]);
  const moreMenu = menu("More", [
    {label: "Save as quotation", sub: "a numbered copy, exactly as sent", act: () => $("#tq-save")?.click()},
    {label: "Duplicate trip", sub: "re-use this plan for another customer", act: async () => { const c = await post(`/api/trips/${t.id}/duplicate`, {}); toast("Copy created"); go("trips", c.id); }},
    {label: "Save as template", sub: "your own ready-made itinerary to start trips from", act: async () => { const n = prompt("Template name", t.title); if (!n) return;
      try { await post(`/api/trips/${t.id}/save-template`, {title: n}); toast("Template saved — find it under Trips → Templates"); } catch (e) { toast(e.message, true); } }},
    "hr",
    {label: "Delete trip", act: async () => { if (!confirm("Delete this trip permanently?")) return; await del(`/api/trips/${t.id}`); toast("Trip deleted"); go("trips"); }},
  ]);

  const labels = [...new Set(t.items.map(i => i.option_label).filter(Boolean))];
  const itemRow = i => `<tr data-item="${i.id}"><td><span class="pill">${esc(words(i.kind))}</span></td>
      <td>${esc(i.description)}${(i.details.errors || []).map(e => `<div class="issue error">${esc(e)}</div>`).join("")}${(i.details.warnings || []).map(e => `<div class="issue warning">${esc(e)}</div>`).join("")}
        ${i.details.quantity_note ? `<div class="small muted">${esc(i.details.quantity_note)}</div>` : ""}
        ${i.details.breakdown ? `<details><summary class="small">breakdown</summary>${i.details.breakdown.map(b => `<div class="small muted">${esc(b.item)}: ${num(b.amount)}</div>`).join("")}</details>` : ""}</td>
      <td><input class="small" data-f="day_position" type="number" min="1" value="${i.day_position ?? ""}" title="Day"></td>
      <td><input class="small" data-f="quantity" type="number" min="0" step="1" value="${i.quantity}" ${i.kind === "package" || i.kind === "hotel" ? "disabled" : ""}></td>
      <td><input data-f="unit_amount" type="number" min="0" value="${i.unit_amount}" style="width:92px"></td>
      <td class="num">${money(i.amount, i.currency)}</td>
      <td>${optionSelect(i, labels)}</td>
      <td><label class="check" title="Show as optional add-on, not in the total"><input type="checkbox" data-f="optional" ${i.optional ? "checked" : ""}>add-on</label></td>
      <td><button class="icon" data-del="${i.id}" title="Remove">✕</button></td></tr>`;

  main.innerHTML = `
  <div class="pagehead"><div><div class="small muted"><button class="link" data-go="trips">Trips</button> / #${t.id} <span class="pill ${t.status}">${t.status}</span></div>
      <h1>${esc(t.title)}</h1><p>${esc([t.customer_name, t.destination, t.start_date && fmtDate(t.start_date) + " – " + fmtDate(t.end_date), tt.travellers + " travellers", t.category].filter(Boolean).join(" · "))}</p></div>
    <div class="row noprint">${shareMenu}${dlMenu}${moreMenu}</div></div>
  ${t.is_template ? `<div class="banner lav"><span>This is a <b>template</b>: start new trips from it (New trip → Package or template). It isn't on the sales board.</span></div>` : ""}
  ${t.newer_versions.map(n => `<div class="banner"><span>A newer version (<b>v${n.to_version}</b>) of <b>${esc(n.title)}</b> was uploaded. This trip uses v${n.from_version}.</span>
    <button class="btn sm primary" data-upgrade="${n.from_id}:${n.to_id}">Use v${n.to_version} and reprice</button></div>`).join("")}
  ${t.problems.filter(p => !p.startsWith("A newer version")).map(p => `<div class="issue error">${esc(p)}</div>`).join("")}
  <div class="grid g-main">
   <div>
    <div class="card"><h2>Trip details</h2>
      <div class="row"><label class="grow">Title<input id="tr-title" class="w100" value="${esc(t.title)}"></label><label>Destination<input id="tr-dest" value="${esc(t.destination || "")}"></label></div>
      <div class="row"><label>Start date<input type="date" id="tr-start" value="${t.start_date || ""}"></label>
        <label>Adults<input type="number" id="tr-ad" class="small" min="1" value="${t.adults}"></label>
        <label>On extra bed<input type="number" id="tr-eb" class="small" min="0" value="${t.extra_beds}"></label>
        <label>Child w/ bed<input type="number" id="tr-cwb" class="small" min="0" value="${t.children_with_bed}"></label>
        <label>Child no bed<input type="number" id="tr-cnb" class="small" min="0" value="${t.children_without_bed}"></label>
        <label>Markup %<input type="number" id="tr-mk" class="small" value="${t.markup_pct}"></label><label>GST %<input type="number" id="tr-gst" class="small" value="${t.gst_pct}"></label>
        <button class="btn primary" id="tr-save" style="margin-bottom:12px">Save &amp; reprice</button></div>
    </div>

    <div class="card"><h2>Itinerary · ${t.days.length} day${t.days.length === 1 ? "" : "s"}
        <span class="row"><button class="btn sm" id="dy-add">${icon("plus")} Blank day</button><button class="btn sm" id="dy-lib">${icon("plus")} Days from other packages</button><button class="btn sm primary" id="dy-save">Save itinerary</button></span></h2>
      <div id="dy-libbox" class="hidden" style="margin:0 0 14px;padding:14px;background:var(--page);border-radius:18px">
        <div class="row"><label>Search days<input id="lb-q" placeholder="Gulmarg, houseboat, Munnar…"></label><label>Destination<input id="lb-d"></label>
          <button class="btn" id="lb-go" style="margin-bottom:12px">Search</button>
          <label>Insert after<select id="lb-after">${[0, ...t.days.map(d => d.position)].map(n => `<option value="${n}" ${n === t.days.length ? "selected" : ""}>${n === 0 ? "the start" : "day " + n}</option>`).join("")}</select></label>
          <button class="btn primary" id="lb-add" style="margin-bottom:12px">Add selected</button></div><div id="lb-out"></div></div>
      <div id="dy-list">${t.days.map((d, ix) => `<div class="day" data-ix="${ix}">
        <div class="dayhead"><span class="dnum">${String(d.position).padStart(2, "0")}</span><span class="small muted" style="min-width:86px">${fmtDate(d.date)}</span>
          <input class="title" data-k="title" value="${esc(d.title || "")}" placeholder="Title">
          <input data-k="overnight" value="${esc(d.overnight || "")}" placeholder="Overnight" style="width:150px">
          <input data-k="meals" value="${esc(d.meals || "")}" placeholder="Meals" style="width:70px">
          <button class="icon" data-up="${ix}" title="Move up">↑</button><button class="icon" data-down="${ix}" title="Move down">↓</button><button class="icon" data-rm="${ix}" title="Remove">✕</button></div>
        <textarea data-k="description" style="margin-top:8px">${esc(d.description || "")}</textarea></div>`).join("") || empty("No days yet — pull days from any package or add a blank day.")}</div>
    </div>

    <div class="card"><h2>Costing</h2>
      <div class="scroll"><table class="costing"><thead><tr><th>Type</th><th>Item</th><th>Day</th><th>Qty</th><th>Unit</th><th class="num">Amount</th><th title="Hotel options: lines for one option only">Option</th><th></th><th></th></tr></thead>
        <tbody id="it-body">${t.items.map(itemRow).join("") || `<tr><td colspan="9" class="muted">No costs yet.</td></tr>`}</tbody></table></div>
      <div style="margin-top:16px"><div class="subnav" id="add-tabs"><button data-add="svc" class="on">+ Activity / transfer</button><button data-add="hotel">+ Hotel stay</button><button data-add="pkg">+ Package price</button><button data-add="custom">+ Custom line</button></div>
        <div id="add-box"></div></div>
      ${t.suggested_addons.length ? `<details ${t.items.length < 3 ? "open" : ""}><summary>Suggested add-ons from this trip's suppliers (${t.suggested_addons.length})</summary>
        <div class="scroll"><table><tbody>${t.suggested_addons.map(a => `<tr><td>${esc(a.name)}</td><td class="muted">${esc(a.destination || "")}</td>
          <td class="num">${range(a.amount, a.amount_max)} ${esc(a.currency)}</td><td class="muted">${words(a.basis)}${a.pax_max && a.basis === "per_vehicle" ? ` · ${a.pax_max} seats` : ""}</td>
          <td class="num"><button class="icon" data-sugg="${a.id}" data-opt="1">+ optional</button><button class="icon" data-sugg="${a.id}" data-opt="0">+ include</button></td></tr>`).join("")}</tbody></table></div></details>` : ""}
      <div class="grid g2" style="margin-top:14px"><div><h3 style="margin-top:0">Included <span class="muted small">(one per line)</span></h3><textarea id="tr-inc">${esc(t.inclusions.join("\n"))}</textarea></div>
        <div><h3 style="margin-top:0">Not included</h3><textarea id="tr-exc">${esc(t.exclusions.join("\n"))}</textarea></div></div>
      <button class="btn sm" id="tr-savelists" style="margin-top:8px">Save lists</button>
    </div>
   </div>

   <div class="rail">
    <div class="card"><h2>Price</h2>
      <div class="bigprice">${tt.is_from_price ? `<span class="small muted" style="font-size:14px">from </span>` : ""}${money(tt.sell, cur)}</div><div class="muted small">${money(tt.per_person, cur)} per person · ${tt.travellers} travellers${tt.option ? ` · ${esc(tt.option)}` : ""}</div>
      ${optionsPriceHtml(t)}
      <table class="totals" style="margin-top:10px">
        <tr><td>Cost</td><td class="num">${money(tt.cost, cur)}</td></tr><tr><td>Markup ${t.markup_pct}%</td><td class="num">${money(tt.markup, cur)}</td></tr>
        <tr><td>GST ${t.gst_pct}%</td><td class="num">${money(tt.gst, cur)}</td></tr><tr class="sum"><td>Selling price</td><td class="num">${money(tt.sell, cur)}</td></tr>
        <tr><td>Received</td><td class="num">${money(tt.paid, cur)}</td></tr><tr><td><b>Balance</b></td><td class="num"><b>${money(tt.balance, cur)}</b></td></tr></table>
      <div class="row" style="margin-top:12px"><button class="btn sm" id="rq-pdf">${icon("down")} Quote PDF</button>${t.share_token ? `<button class="btn sm" id="rq-link">${icon("share")} Copy link</button>` : `<button class="btn sm" id="rq-share">${icon("share")} Create client link</button>`}</div>
    </div>

    <div id="tq"></div>
    <div class="card"><h2>Sale</h2>
      <div class="row"><label class="grow">Status<select id="cr-status" class="w100">${STATUSES.map(s => `<option ${s === t.status ? "selected" : ""}>${s}</option>`).join("")}</select></label>
        <label class="grow">Handled by<select id="cr-owner" class="w100"><option value="">—</option>${st.team.map(m => `<option ${m.name === t.assigned_to ? "selected" : ""}>${esc(m.name)}</option>`).join("")}</select></label></div>
      <div class="row"><label class="grow">Follow up on<input type="date" id="cr-fu" class="w100" value="${t.follow_up_date || ""}"></label>
        <label class="grow">Lead source<select id="cr-src" class="w100"><option value="">—</option>${st.lead_sources.map(s => `<option ${s === t.lead_source ? "selected" : ""}>${esc(s)}</option>`).join("")}</select></label></div>
      <div id="cr-lostbox" class="${t.status === "lost" ? "" : "hidden"}"><label class="w100">Why lost?<input id="cr-lost" class="w100" value="${esc(t.lost_reason || "")}" placeholder="price, dates, went elsewhere…"></label></div>
      <h3>Customer</h3>
      <label class="w100">Name<input id="cr-name" class="w100" value="${esc(t.customer_name || "")}"></label>
      <div class="row"><label class="grow">Phone<input id="cr-phone" class="w100" value="${esc(t.customer_phone || "")}"></label><label class="grow">Email<input id="cr-email" class="w100" value="${esc(t.customer_email || "")}"></label></div>
      <div class="quicklinks">${t.customer_phone ? `<a class="btn sm" href="tel:${esc(t.customer_phone)}">${icon("phone")} Call</a><a class="btn sm" target="_blank" href="https://wa.me/${phoneDigits}">${icon("chat")} WhatsApp</a>` : ""}</div>
      <button class="btn primary sm" id="cr-save" style="margin-top:8px">Save</button>
    </div>

    <div class="card"><h2>Payments</h2>
      ${t.payments.map(p => `<div class="row between small" style="padding:6px 0;border-bottom:1px solid var(--line)"><span>${fmtDate(p.paid_on)} · ${esc(p.mode || "")}${p.reference ? " · " + esc(p.reference) : ""}</span><span><b>${money(p.amount, cur)}</b> <button class="icon" data-delpay="${p.id}">✕</button></span></div>`).join("") || `<div class="small muted">No payments yet.</div>`}
      <div class="row" style="margin-top:10px"><input id="pay-amt" type="number" placeholder="Amount" class="num"><select id="pay-mode"><option>UPI</option><option>Bank transfer</option><option>Card</option><option>Cash</option></select></div>
      <div class="row" style="margin-top:6px"><input id="pay-date" type="date" value="${todayISO()}"><input id="pay-ref" placeholder="Ref" style="width:90px"><button class="btn sm" id="pay-add">Add</button></div>
    </div>

    <div class="card"><h2>Notes &amp; follow-ups</h2>
      <textarea id="nt-text" placeholder="Called, sent the quote, wants a houseboat upgrade…" style="min-height:60px"></textarea>
      <div class="row center" style="margin-top:6px"><label style="margin:0">Next follow-up<input type="date" id="nt-fu"></label><button class="btn sm" id="nt-add" style="margin-top:16px">Add note</button></div>
      <div style="margin-top:10px">${t.notes_log.map(n => `<div class="note">${esc(n.text)}<small>${esc([n.author, n.at && new Date(n.at.replace(" ", "T") + (n.at.endsWith("Z") ? "" : "Z")).toLocaleString("en-IN", {dateStyle: "medium", timeStyle: "short"})].filter(Boolean).join(" · "))}</small></div>`).join("") || `<div class="small muted">No notes yet.</div>`}</div>
    </div>
   </div>
  </div>`;
  wireTrip(main);
  addBox("svc");
  if (!t.is_template) tripQuotesCard(t).then(h => { const el = $("#tq"); if (el && T.id === t.id) { el.innerHTML = h; wireGo(el); wireTripQuotes(main); } }).catch(() => {});
}

function readDays() {
  return $$("#dy-list .day").map(d => { const v = {...(T.days[+d.dataset.ix] || {})}; $$("[data-k]", d).forEach(i => v[i.dataset.k] = i.value); return v; });
}

function wireTrip(main) {
  const id = T.id;
  wireGo(main);
  const run = async (fn, ok) => { try { T = await fn(); drawTrip(main); if (ok) toast(ok); } catch (e) { toast(e.message, true); } };
  $("#tr-save").onclick = () => run(() => patch(`/api/trips/${id}`, {title: $("#tr-title").value, destination: $("#tr-dest").value, start_date: $("#tr-start").value || null,
    adults: +$("#tr-ad").value, extra_beds: +$("#tr-eb").value, children_with_bed: +$("#tr-cwb").value, children_without_bed: +$("#tr-cnb").value,
    markup_pct: +$("#tr-mk").value, gst_pct: +$("#tr-gst").value}), "Saved and repriced");
  $("#cr-status").onchange = e => $("#cr-lostbox").classList.toggle("hidden", e.target.value !== "lost");
  $("#cr-save").onclick = () => run(() => patch(`/api/trips/${id}`, {status: $("#cr-status").value, assigned_to: $("#cr-owner").value || null,
    follow_up_date: $("#cr-fu").value || "", lead_source: $("#cr-src").value || null, lost_reason: $("#cr-lost").value || null,
    customer_name: $("#cr-name").value, customer_phone: $("#cr-phone").value, customer_email: $("#cr-email").value}), "Saved");
  $("#rq-pdf").onclick = () => download(`/api/trips/${id}/pdf`);
  $("#rq-link") && ($("#rq-link").onclick = () => copy(shareUrl(T), "Client link copied"));
  $("#rq-share") && ($("#rq-share").onclick = async () => { const u = await ensureShare(); await copy(u, "Client link created and copied"); drawTrip(main); });
  $("#tr-savelists").onclick = () => run(() => patch(`/api/trips/${id}`, {inclusions: $("#tr-inc").value.split("\n").map(s => s.trim()).filter(Boolean),
    exclusions: $("#tr-exc").value.split("\n").map(s => s.trim()).filter(Boolean)}), "Saved");
  $("#pay-add").onclick = () => run(() => post(`/api/trips/${id}/payments`, {amount: +$("#pay-amt").value, mode: $("#pay-mode").value, paid_on: $("#pay-date").value, reference: $("#pay-ref").value}), "Payment added");
  $$("[data-delpay]").forEach(b => b.onclick = () => confirm("Remove this payment?") && run(() => del(`/api/trips/${id}/payments/${b.dataset.delpay}`)));
  $("#nt-add").onclick = () => run(() => post(`/api/trips/${id}/notes`, {text: $("#nt-text").value, author: T.assigned_to, follow_up_date: $("#nt-fu").value || undefined}), "Note added");
  // itinerary
  const saveDays = days => run(() => put(`/api/trips/${id}/days`, days), "Itinerary saved");
  $("#dy-save").onclick = () => saveDays(readDays());
  $("#dy-add").onclick = () => saveDays([...readDays(), {title: "New day", description: ""}]);
  $$("[data-rm]").forEach(b => b.onclick = () => { const d = readDays(); d.splice(+b.dataset.rm, 1); saveDays(d); });
  $$("[data-up]").forEach(b => b.onclick = () => { const d = readDays(), i = +b.dataset.up; if (i > 0) { [d[i - 1], d[i]] = [d[i], d[i - 1]]; saveDays(d); } });
  $$("[data-down]").forEach(b => b.onclick = () => { const d = readDays(), i = +b.dataset.down; if (i < d.length - 1) { [d[i + 1], d[i]] = [d[i], d[i + 1]]; saveDays(d); } });
  $("#dy-lib").onclick = () => { $("#dy-libbox").classList.toggle("hidden"); if (!$("#lb-out").innerHTML) $("#lb-go").click(); };
  $("#lb-go").onclick = async () => {
    const p = new URLSearchParams(); if ($("#lb-q").value) p.set("q", $("#lb-q").value); if ($("#lb-d").value) p.set("destination", $("#lb-d").value);
    const rows = await api("/api/library/days?" + p);
    $("#lb-out").innerHTML = rows.map(d => `<label class="check" style="align-items:flex-start;margin:8px 0"><input type="checkbox" value="${d.id}" style="margin-top:4px">
      <span><span style="font-weight:500">${esc(d.title || "")}</span> <span class="muted small">— ${esc(d.package)}, day ${d.day}${d.overnight ? " · " + esc(d.overnight) : ""}</span><br><span class="muted small">${esc((d.description || "").slice(0, 180))}</span></span></label>`).join("") || `<div class="small muted">No days found.</div>`;
  };
  $("#lb-add").onclick = () => { const ids = $$("#lb-out input:checked").map(i => +i.value); if (!ids.length) return;
    run(async () => { await put(`/api/trips/${id}/days`, readDays()); return post(`/api/trips/${id}/days/from-library`, {day_ids: ids, after_position: +$("#lb-after").value}); }, `${ids.length} day(s) added`); };
  // items
  $$("#it-body tr[data-item]").forEach(tr => $$("input[data-f]", tr).forEach(inp => inp.onchange = () => {
    const f = inp.dataset.f, val = inp.type === "checkbox" ? inp.checked : inp.value === "" ? null : +inp.value;
    run(() => patch(`/api/trips/${id}/items/${tr.dataset.item}`, {[f]: val}));
  }));
  $$("#it-body select[data-f=option_label]").forEach(sel => sel.onchange = () => {
    let v = sel.value;
    if (v === "__new") { v = prompt("Name of the option (e.g. Option D, Houseboat upgrade)"); if (!v) { drawTrip(main); return; } }
    run(() => patch(`/api/trips/${id}/items/${sel.closest("tr").dataset.item}`, {option_label: v || null}), v ? `Moved to ${v}` : "Now in every option");
  });
  $$("input[name=chosen]").forEach(r => r.onchange = () => run(() => patch(`/api/trips/${id}`, {chosen_option: r.value}), `Customer chose ${r.value}`));
  $("#opt-clear") && ($("#opt-clear").onclick = () => run(() => patch(`/api/trips/${id}`, {chosen_option: null}), "Choice cleared"));
  $$("[data-upgrade]").forEach(b => b.onclick = () => { const [f, to] = b.dataset.upgrade.split(":");
    run(() => post(`/api/trips/${id}/upgrade-package`, {from_id: +f, to_id: +to}), "Moved to the latest version and repriced"); });
  $$("[data-del]").forEach(b => b.onclick = () => run(() => del(`/api/trips/${id}/items/${b.dataset.del}`), "Removed"));
  $$("[data-sugg]").forEach(b => b.onclick = () => run(() => post(`/api/trips/${id}/items`, {kind: "service", service_id: +b.dataset.sugg, optional: b.dataset.opt === "1"}), "Added"));
  $$("#add-tabs button").forEach(b => b.onclick = () => { $$("#add-tabs button").forEach(x => x.classList.toggle("on", x === b)); addBox(b.dataset.add); });
}

async function addBox(kind) {
  const t = T, id = t.id, box = $("#add-box");
  const add = async body => { try { T = await post(`/api/trips/${id}/items`, body); drawTrip($("#main")); toast("Added"); } catch (e) { toast(e.message, true); } };
  const dayOpts = sel => [...Array(Math.max(t.days.length, 1)).keys()].map(i => `<option value="${i + 1}" ${sel === i + 1 ? "selected" : ""}>Day ${i + 1}</option>`).join("");
  const existing = [...new Set(t.items.map(i => i.option_label).filter(Boolean))];
  const optField = `<label title="Put this line in one hotel option only (the customer chooses one option)">Hotel option<input id="add-opt" list="add-opts" placeholder="all options" style="width:120px">
    <datalist id="add-opts">${[...new Set([...existing, "Option A", "Option B", "Option C"])].map(o => `<option value="${esc(o)}">`).join("")}</datalist></label>`;
  const optVal = () => ($("#add-opt")?.value || "").trim() || null;
  if (kind === "svc") {
    box.innerHTML = `<div class="row"><label>Destination<input id="as-d" value="${esc((t.destination || "").split(",")[0])}"></label><label>Search<input id="as-q" placeholder="gondola, cab, ticket"></label>
      <label>Day<select id="as-day">${dayOpts(1)}</select></label><button class="btn" id="as-go" style="margin-bottom:12px">Find</button></div><div id="as-out"></div>`;
    const load = async () => {
      const p = new URLSearchParams(); if ($("#as-d").value) p.set("destination", $("#as-d").value); if ($("#as-q").value) p.set("q", $("#as-q").value);
      const rows = await api("/api/catalog/services?" + p);
      $("#as-out").innerHTML = rows.length ? `<div style="max-height:360px;overflow:auto">${rows.map(s => `<div class="row between center" style="padding:8px 2px;border-bottom:1px solid var(--line);flex-wrap:nowrap">
        <div><span style="font-weight:500">${esc(s.name)}</span> ${s.optional ? `<span class="pill warn">add-on</span>` : ""}<div class="small muted">${esc([words(s.kind), s.destination, s.vehicle_type, words(s.basis) + (s.basis === "per_vehicle" && s.pax_max ? ` · ${s.pax_max} seats` : ""), s.notes].filter(Boolean).join(" · "))}</div></div>
        <div class="row center" style="flex-wrap:nowrap"><span class="num" style="white-space:nowrap">${range(s.amount, s.amount_max)} ${esc(s.currency)}</span><button class="btn sm" data-as="${s.id}">Add</button></div></div>`).join("")}</div>`
        : `<div class="small muted">Nothing found — try another destination or search.</div>`;
      $$("[data-as]").forEach(b => b.onclick = () => add({kind: "service", service_id: +b.dataset.as, day_position: +$("#as-day").value}));
    };
    $("#as-go").onclick = load; load();
  } else if (kind === "hotel") {
    const hotels = await api("/api/hotels");
    if (!hotels.length) { box.innerHTML = `<div class="small muted">No hotels with live rates yet — upload hotel rate sheets in Documents.</div>`; return; }
    box.innerHTML = `<div class="row"><label>Hotel<select id="ah-h">${hotels.map(h => `<option value="${h.id}">${esc(h.name)} — ${esc(h.city || "")}</option>`).join("")}</select></label>
      <label>Room<select id="ah-r"></select></label><label>Meal<select id="ah-m"><option>CP</option><option>MAP</option><option>AP</option><option>EP</option><option>AI</option></select></label>
      <label>Check-in<select id="ah-day">${dayOpts(1)}</select></label><label>Nights<input type="number" id="ah-n" class="small" value="1" min="1"></label>
      ${optField}<button class="btn primary" id="ah-go" style="margin-bottom:12px">Add stay</button></div><div class="small muted">Rooms follow the travellers: 2 adults per room, a 3rd adult on an extra bed. Needs the start date.
      To offer a choice of hotels, add each hotel with its own option name (Option A, Option B…) — the quote then shows one price per option.</div>`;
    const fill = () => { const h = hotels.find(x => x.id == $("#ah-h").value); $("#ah-r").innerHTML = h.room_types.map(r => `<option>${esc(r)}</option>`).join(""); };
    $("#ah-h").onchange = fill; fill();
    $("#ah-go").onclick = () => add({kind: "hotel", hotel_id: +$("#ah-h").value, room_type: $("#ah-r").value, meal_plan: $("#ah-m").value, day_position: +$("#ah-day").value, nights: +$("#ah-n").value, option_label: optVal()});
  } else if (kind === "pkg") {
    const pk = await packageOptions();
    box.innerHTML = `<div class="row"><label class="grow">Package<select id="ap-p" class="w100">${pk.map(p => `<option value="${p.id}">${esc(p.title)}</option>`).join("")}</select></label>
      <label>Category<select id="ap-c"></select></label>${optField}<label class="check" style="margin-bottom:20px"><input type="checkbox" id="ap-all">every category as options</label>
      <button class="btn primary" id="ap-go" style="margin-bottom:12px">Add price</button></div>
      <div class="small muted">Adds that package's price for this group (no days). Use "Days from other packages" to bring its days in too.</div>`;
    const fill = () => { const p = pk.find(x => x.id == $("#ap-p").value); $("#ap-c").innerHTML = (p?.categories || []).map(c => `<option>${esc(c)}</option>`).join(""); };
    $("#ap-p").onchange = fill; fill();
    $("#ap-go").onclick = () => add({kind: "package", package_id: +$("#ap-p").value, category: $("#ap-c").value, option_label: optVal(), all_categories: $("#ap-all").checked});
  } else {
    box.innerHTML = `<div class="row"><label class="grow">Description<input id="ac-d" class="w100" placeholder="Flights, guide, special request…"></label><label>Qty<input type="number" id="ac-q" class="small" value="1"></label>
      <label>Unit price<input type="number" id="ac-u" class="num"></label>${optField}<label class="check" style="margin-bottom:20px"><input type="checkbox" id="ac-o">add-on</label>
      <button class="btn primary" id="ac-go" style="margin-bottom:12px">Add</button></div>`;
    $("#ac-go").onclick = () => add({kind: "custom", description: $("#ac-d").value, quantity: +$("#ac-q").value, unit_amount: +$("#ac-u").value, optional: $("#ac-o").checked, option_label: optVal()});
  }
}

// ================================================================ CATALOG
let catTab = "packages";
function servicesTable(rows, addBtn) {
  return `<div class="scroll"><table><thead><tr><th>Kind</th><th>Service</th><th>Where</th><th>Vehicle</th><th>Basis</th><th class="num">Price</th><th>Valid</th>${addBtn ? "<th></th>" : ""}</tr></thead><tbody>` +
    rows.map(s => `<tr data-svc="${s.id ?? ""}"><td>${esc(words(s.kind))}</td><td>${esc(s.name)} ${s.optional ? `<span class="pill warn">add-on</span>` : ""}${s.change_pct ? ` ${pctTxt(s.change_pct)}` : ""}${s.notes ? `<div class="small muted">${esc(s.notes)}</div>` : ""}</td>
      <td>${esc(s.destination || "")}</td><td>${esc(s.vehicle_type || "")}${s.basis === "per_vehicle" && s.pax_max ? ` <span class="muted">(${s.pax_max} seats)</span>` : ""}</td>
      <td>${esc(words(s.basis))}</td><td class="num">${range(s.amount, s.amount_max)} ${esc(s.currency)}</td><td class="small">${fmtDate(s.valid_from)} – ${fmtDate(s.valid_to)}</td>
      ${addBtn ? `<td>${addBtn(s)}</td>` : ""}</tr>`).join("") + `</tbody></table></div>`;
}

async function pageCatalog(main, arg) {
  if (arg && arg.startsWith("p")) return showPackage(main, +arg.slice(1));
  if (arg && arg.startsWith("h")) return showHotel(main, +arg.slice(1));
  if (arg && arg.startsWith("s")) return showSupplier(main, +arg.slice(1));
  if (arg && ["packages", "hotels", "services", "places", "suppliers", "changes"].includes(arg)) catTab = arg;
  const sm = await api("/api/catalog/summary");
  const tabs = [["packages", "Packages", sm.packages], ["hotels", "Hotels", sm.hotels], ["services", "Activities & transfers", sm.services], ["places", "Places", sm.places], ["suppliers", "Suppliers", sm.suppliers], ["changes", "Price changes", ""]];
  main.innerHTML = `<div class="pagehead"><div><h1>Catalog</h1><p>Everything read from your supplier documents, ready to quote.</p></div>
    ${menu(`${icon("down")} Export`, [{label: "Hotel rates (CSV)", act: () => download("/api/export/hotel-rates.csv")}, {label: "Package prices (CSV)", act: () => download("/api/export/packages.csv")},
      {label: "Activities & transfers (CSV)", act: () => download("/api/export/services.csv")}, {label: "Hotels (CSV)", act: () => download("/api/export/hotels.csv")},
      {label: "Places (CSV)", act: () => download("/api/export/places.csv")}, {label: "Suppliers (CSV)", act: () => download("/api/export/suppliers.csv")}, "hr",
      {label: "Whole library (Excel)", sub: "one sheet per list — good as a backup", act: () => download("/api/export/library.xlsx")}])}</div>
    <div class="card"><div class="subnav">${tabs.map(([k, l, n]) => `<button data-sub="${k}" class="${k === catTab ? "on" : ""}">${l} <span class="muted">${n}</span></button>`).join("")}</div><div id="cat-body"></div></div>`;
  $$(".subnav button", main).forEach(b => b.onclick = () => { catTab = b.dataset.sub; pageCatalog(main); });
  await ({packages: catPackages, hotels: catHotels, services: catServices, places: catPlaces, suppliers: catSuppliers, changes: catChanges})[catTab]();
}

async function catPackages() {
  const body = $("#cat-body");
  body.innerHTML = `<div class="row"><label>Search<input id="cp-q" placeholder="Kashmir, Kerala…"></label><label>Travel date<input type="date" id="cp-date"></label>
    <button class="btn" id="cp-go" style="margin-bottom:12px">Show</button></div><div id="cp-list" class="cards"></div>`;
  const load = async () => {
    const p = new URLSearchParams(); if ($("#cp-q").value) p.set("q", $("#cp-q").value); if ($("#cp-date").value) p.set("on_date", $("#cp-date").value);
    const rows = await api("/api/catalog/packages?" + p);
    $("#cp-list").innerHTML = rows.map(k => `<div class="pcard" data-id="${k.id}"><h4>${esc(k.title)} ${k.versions > 1 ? `<span class="pill" title="${k.versions} versions uploaded">v${k.version}</span>` : ""}</h4>
      <div class="small muted">${esc(k.region || k.destinations.join(", "))} · ${k.nights ?? "?"}N/${k.days ?? "?"}D · ${esc(k.supplier || "")}</div>
      <div>${k.categories.map(c => `<span class="pill">${esc(c)}</span>`).join(" ")}</div>
      <div class="price">${k.from_price ? `from <b>${money(k.from_price, k.currency)}</b> per person` : ""}</div>
      <div class="small muted">Valid ${fmtDate(k.valid_from)} – ${fmtDate(k.valid_to)} · ${k.hotel_options} hotel options</div>
      ${k.change_pct ? `<div class="small">Prices vs previous version: ${pctTxt(k.change_pct)}</div>` : ""}
      ${k.other_editions.length ? `<div class="small muted">Also: ${k.other_editions.map(e => `${esc(e.title)} (${fmtDate(e.valid_from)} – ${fmtDate(e.valid_to)})`).join("; ")}</div>` : ""}</div>`).join("")
      || empty("No packages yet — upload a package PDF in Documents.");
    $$("#cp-list .pcard").forEach(c => c.onclick = () => go("catalog", "p" + c.dataset.id));
  };
  $("#cp-go").onclick = load; await load();
}

async function showPackage(main, id) {
  const p = await api(`/api/catalog/packages/${id}`);
  const g = p.price_grid;
  main.innerHTML = `${p.newer_version ? `<div class="banner"><span>A newer version of this package was uploaded: <b>v${p.newer_version.version}</b> ${esc(p.newer_version.title)}.</span><button class="btn sm" data-go="catalog/p${p.newer_version.id}">Open v${p.newer_version.version}</button></div>` : ""}
  <div class="pagehead"><div><div class="small muted"><button class="link" data-go="catalog">Catalog</button> / package${p.versions > 1 ? ` · version ${p.version} of ${p.versions}` : ""}</div><h1>${esc(p.title)} ${p.state !== "current" ? statePill(p.state) : ""}</h1>
      <p>${esc([p.supplier, p.region, (p.destinations || []).join(" → "), p.nights && `${p.nights}N/${p.days}D`, `valid ${fmtDate(p.valid_from)} – ${fmtDate(p.valid_to)}`].filter(Boolean).join(" · "))}</p></div>
    <div class="row">${menu(`${icon("down")} Download`, [{label: "Rate card PDF", sub: "internal — supplier net rates", act: () => download(`/api/catalog/packages/${id}/pdf`)},
      {label: "Prices (CSV)", act: () => download(`/api/catalog/packages/${id}/csv`)}, {label: "Itinerary (CSV)", act: () => download(`/api/catalog/packages/${id}/csv?part=itinerary`)}])}
      <button class="btn primary" id="pk-build">${icon("plus")} Build a trip from this</button></div></div>
  <div class="grid g-main"><div>
    <div class="card"><h2>Price per person ${g.currency ? `<span class="muted small">${esc(g.currency)} · supplier cost</span>` : ""}</h2>
      <div class="scroll"><table><thead><tr><th></th>${g.categories.map(c => `<th class="num">${esc(c)}</th>`).join("")}</tr></thead><tbody>
      ${g.rows.map(r => `<tr><td>${esc(r.label)}</td>${g.categories.map(c => `<td class="num">${num(r.values[c])}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div>
    <div id="pv"></div>
    <div class="card"><h2>Itinerary</h2>${p.itinerary.map(d => `<div class="day"><div class="dayhead"><span class="dnum">${String(d.day).padStart(2, "0")}</span><span style="font-weight:500">${esc(d.title || "")}</span>${d.overnight ? `<span class="muted small">· ${esc(d.overnight)}</span>` : ""}</div>
      <p style="margin:6px 0 0" class="small">${esc(d.description || "")}</p></div>`).join("")}</div>
    <div class="card"><h2>Hotels by city and category</h2>${p.hotels_by_city.map(c => `<h3>${esc(c.city)} ${c.nights ? `<span class="muted small">${c.nights} night(s)</span>` : ""}</h3>
      <div class="hotelcols">${Object.entries(c.categories).map(([cat, hs]) => `<div><b>${esc(cat)}</b>${hs.map(h => esc(h.name)).join("<br>")}</div>`).join("")}</div>`).join("") || `<div class="muted small">No hotel list.</div>`}</div>
    ${p.addons.length ? `<div class="card"><h2>Add-ons &amp; extra costs</h2>${servicesTable(p.addons)}</div>` : ""}
    <div class="card grid g2"><div><h2>Included</h2><ul>${p.inclusions.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div><div><h2>Not included</h2><ul>${p.exclusions.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div></div>
  </div><div class="rail">
    <div class="card"><h2>Quick price</h2>
      <label class="w100">Category<select id="pq-cat" class="w100">${g.categories.map(c => `<option>${esc(c)}</option>`).join("")}</select></label>
      <div class="row"><label>Adults<input type="number" id="pq-ad" value="2" min="1" class="small"></label><label>On extra bed<input type="number" id="pq-eb" value="0" min="0" class="small"></label></div>
      <div class="row"><label>Child w/ bed<input type="number" id="pq-cwb" value="0" min="0" class="small"></label><label>Child no bed<input type="number" id="pq-cnb" value="0" min="0" class="small"></label></div>
      <label class="w100">Travel date<input type="date" id="pq-date" class="w100"></label>
      <button class="btn primary" id="pq-go">Price it</button><div id="pq-out" style="margin-top:12px"></div></div>
  </div></div>`;
  wireGo(main);
  packageVersionsCard(id);
  $("#pq-go").onclick = async () => {
    const q = new URLSearchParams({category: $("#pq-cat").value, adults: $("#pq-ad").value, extra_beds: $("#pq-eb").value, children_with_bed: $("#pq-cwb").value, children_without_bed: $("#pq-cnb").value});
    if ($("#pq-date").value) q.set("travel_date", $("#pq-date").value);
    try { const r = await api(`/api/catalog/packages/${id}/price?` + q);
      $("#pq-out").innerHTML = r.errors.map(e => `<div class="issue error">${esc(e)}</div>`).join("") + r.warnings.map(e => `<div class="issue warning">${esc(e)}</div>`).join("") +
        `<table>${r.lines.map(l => `<tr><td class="small">${esc(l.item)}</td><td class="num">${num(l.amount)}</td></tr>`).join("")}</table>
        <div class="bigprice" style="margin-top:8px">${money(r.total, r.currency)}</div><div class="small muted">${r.is_net ? "supplier net cost, before markup" : "cost before markup"}</div>`;
    } catch (e) { $("#pq-out").innerHTML = `<div class="issue error">${esc(e.message)}</div>`; }
  };
  $("#pk-build").onclick = () => { pendingNewTrip = {package_id: p.id, category: $("#pq-cat").value, title: p.title, adults: +$("#pq-ad").value, extra_beds: +$("#pq-eb").value,
    children_with_bed: +$("#pq-cwb").value, children_without_bed: +$("#pq-cnb").value, start_date: $("#pq-date").value}; go("trips", "new"); };
}

async function catHotels() {
  const body = $("#cat-body");
  body.innerHTML = `<div class="row"><label>Search<input id="ch-q" placeholder="hotel name"></label><label>City / region<input id="ch-city" placeholder="Srinagar"></label>
    <label>Category<select id="ch-cat"><option value="">Any</option><option>Standard</option><option>Deluxe</option><option>Premium</option><option>Luxury</option></select></label>
    <label>Rates<select id="ch-rates"><option value="">Any</option><option value="true">With live rates</option><option value="false">Listed in packages only</option></select></label>
    <button class="btn" id="ch-go" style="margin-bottom:12px">Show</button></div><div class="scroll" id="ch-out"></div>`;
  const load = async () => {
    const p = new URLSearchParams(); [["q", "#ch-q"], ["city", "#ch-city"], ["category", "#ch-cat"], ["has_rates", "#ch-rates"]].forEach(([k, s]) => $(s).value && p.set(k, $(s).value));
    const rows = await api("/api/catalog/hotels?" + p);
    $("#ch-out").innerHTML = `<div class="small muted" style="margin-bottom:6px">${rows.length} hotels</div><table><thead><tr><th>Hotel</th><th>City</th><th>Category</th><th>Type</th><th class="num">Live rates</th><th class="num">In packages</th></tr></thead><tbody>` +
      rows.map(h => `<tr class="click" data-id="${h.id}"><td>${esc(h.name)}</td><td>${esc(h.city || "")}</td><td>${esc(h.category || "")}</td><td>${esc(h.property_type || "")}</td>
        <td class="num">${h.rates ? `<span class="pill ok">${h.rates}</span>` : "—"}</td><td class="num">${h.in_packages || ""}</td></tr>`).join("") + `</tbody></table>`;
    $$("#ch-out tr.click").forEach(tr => tr.onclick = () => go("catalog", "h" + tr.dataset.id));
  };
  $("#ch-go").onclick = load; await load();
}

async function showHotel(main, id) {
  const h = await api(`/api/catalog/hotels/${id}`);
  main.innerHTML = `<div class="pagehead"><div><div class="small muted"><button class="link" data-go="catalog">Catalog</button> / hotel</div><h1>${esc(h.name)}</h1>
    <p>${esc([h.city, h.destination, h.category, h.property_type, h.star_rating && h.star_rating + "★", h.supplier].filter(Boolean).join(" · "))}</p></div></div>
  <div class="card"><h2>Live rates ${h.history_rows ? `<span class="small muted">${h.history_rows} older rates kept as history</span>` : ""}
      ${h.rates.length > 12 ? `<span class="row"><select id="hr-room"><option value="">every room</option>${[...new Set(h.rates.map(r => r.room_type))].map(r => `<option>${esc(r)}</option>`).join("")}</select>
        <select id="hr-meal"><option value="">every meal plan</option>${[...new Set(h.rates.map(r => r.meal_plan))].map(r => `<option>${r}</option>`).join("")}</select></span>` : ""}</h2>${h.rates.length ? `<div class="scroll"><table id="hr-table"><thead><tr><th>Room</th><th>Meal</th><th>Occupancy</th><th class="num">Amount</th><th>Valid</th><th>Days</th><th>Season</th><th>State</th><th class="num">vs before</th><th></th></tr></thead><tbody>
      ${h.rates.map(r => `<tr data-rate="${r.id}" data-room="${esc(r.room_type)}" data-meal="${r.meal_plan}"><td>${esc(r.room_type)}</td><td>${r.meal_plan}</td><td>${words(r.occupancy)}</td><td class="num">${money(r.amount, r.currency)}</td><td class="small">${fmtDate(r.valid_from)} – ${fmtDate(r.valid_to)}</td><td>${esc(r.weekdays || "all")}</td><td>${esc(r.season || "")}</td>
        <td>${statePill(r.state)}</td><td class="num">${pctTxt(r.change_pct)}</td><td style="white-space:nowrap"><button class="icon" data-edit-rate="${r.id}" title="Correct this rate">✎</button></td></tr>`).join("")}</tbody></table></div>`
      : empty("No rates yet — this hotel is known from package hotel lists. Upload its rate sheet to price it directly.")}
    ${h.surcharges.length ? `<p class="small muted">${h.surcharges.map(x => x.kind === "blackout" ? `Blackout ${fmtDate(x.date_from)} – ${fmtDate(x.date_to)}` : `${esc(x.name)} ${fmtDate(x.date_from)}: ${num(x.amount)}`).join(" · ")}</p>` : ""}</div>
  <div id="hh"></div>
  ${h.packages.length ? `<div class="card"><h2>Offered in packages</h2>${h.packages.map(p => `<div><button class="link" data-go="catalog/p${p.id}">${esc(p.title)}</button> <span class="muted small">${esc(p.category || "")} ${p.nights ? "· " + p.nights + "N" : ""}</span></div>`).join("")}</div>` : ""}`;
  wireGo(main);
  hotelHistoryCard(id);
  const filt = () => { const rm = $("#hr-room")?.value, ml = $("#hr-meal")?.value;
    $$("#hr-table tr[data-rate]").forEach(tr => tr.classList.toggle("hidden", !!(rm && tr.dataset.room !== rm) || !!(ml && tr.dataset.meal !== ml))); };
  $("#hr-room") && ($("#hr-room").onchange = $("#hr-meal").onchange = filt);
  $$("[data-edit-rate]", main).forEach(b => b.onclick = () => editRateRow(b.closest("tr"), h.rates.find(r => r.id == b.dataset.editRate), "hotel-rates", () => showHotel(main, id)));
}

// correct a live rate in place (amount, dates) or take it out of use; the change is noted on the rate
function editRateRow(tr, r, kind, done) {
  const cols = tr.children.length;
  tr.innerHTML = `<td colspan="${cols}"><div class="row center"><b>${esc(r.room_type || r.name || "")}</b>
    <label>Amount<input id="er-a" class="num" value="${r.amount}"></label>${kind === "services" ? `<label>Up to<input id="er-m" class="num" value="${r.amount_max ?? ""}"></label>` : ""}
    <label>Valid from<input type="date" id="er-f" value="${r.valid_from}"></label><label>Valid to<input type="date" id="er-t" value="${r.valid_to}"></label>
    <button class="btn sm primary" id="er-save" style="margin-bottom:12px">Save</button><button class="btn sm" id="er-retire" style="margin-bottom:12px">Retire rate</button><button class="btn sm" id="er-x" style="margin-bottom:12px">Cancel</button></div>
    <div class="small muted">For a quick correction. For a new season or a new sheet, upload it — the history is kept automatically.</div></td>`;
  const send = async body => { try { await patch(`/api/catalog/${kind}/${r.id}`, body); toast("Saved"); done(); } catch (e) { toast(e.message, true); } };
  $("#er-save").onclick = () => { const b = {amount: $("#er-a").value, valid_from: $("#er-f").value, valid_to: $("#er-t").value}; if ($("#er-m")) b.amount_max = $("#er-m").value; send(b); };
  $("#er-retire").onclick = () => confirm("Take this rate out of use? It stays in the history.") && send({status: "retired"});
  $("#er-x").onclick = done;
}

async function catServices() {
  const body = $("#cat-body");
  body.innerHTML = `<div class="row"><label>Search<input id="cs-q" placeholder="gondola, cab…"></label><label>Destination<input id="cs-d" placeholder="Kashmir"></label>
    <label>Kind<select id="cs-k"><option value="">Any</option>${["transfer", "sightseeing", "activity", "entry_ticket", "rental", "guide", "vehicle_hire", "meal", "other"].map(k => `<option value="${k}">${words(k)}</option>`).join("")}</select></label>
    <button class="btn" id="cs-go" style="margin-bottom:12px">Show</button></div><div id="cs-out"></div>`;
  const load = async () => {
    const p = new URLSearchParams(); [["q", "#cs-q"], ["destination", "#cs-d"], ["kind", "#cs-k"]].forEach(([k, s]) => $(s).value && p.set(k, $(s).value));
    const rows = await api("/api/catalog/services?" + p);
    $("#cs-out").innerHTML = rows.length ? servicesTable(rows, x => `<button class="icon" data-edit-svc="${x.id}" title="Correct this rate">✎</button>`) : empty("Nothing found.");
    $$("[data-edit-svc]").forEach(b => b.onclick = () => editRateRow(b.closest("tr"), rows.find(r => r.id == b.dataset.editSvc), "services", load));
  };
  $("#cs-go").onclick = load; await load();
}

async function catPlaces() {
  const body = $("#cat-body");
  body.innerHTML = `<div class="row"><label>Search<input id="cl-q"></label><label>Destination<input id="cl-d" placeholder="Kashmir"></label><button class="btn" id="cl-go" style="margin-bottom:12px">Show</button></div><div id="cl-out" class="cards"></div>`;
  const load = async () => {
    const p = new URLSearchParams(); if ($("#cl-q").value) p.set("q", $("#cl-q").value); if ($("#cl-d").value) p.set("destination", $("#cl-d").value);
    const rows = await api("/api/catalog/places?" + p);
    $("#cl-out").innerHTML = rows.map(x => `<div class="pcard" style="cursor:default"><h4>${esc(x.name)}</h4><div class="small muted">${esc([x.region, x.destination].filter(Boolean).join(", "))} ${x.kind ? `<span class="pill">${esc(x.kind)}</span>` : ""}</div>
      <div class="small">${esc(x.description || "")}</div>${x.availability ? `<div><span class="pill warn">${esc(x.availability)}</span></div>` : ""}</div>`).join("") || empty("Nothing found.");
  };
  $("#cl-go").onclick = load; await load();
}

async function catSuppliers() {
  const rows = await api("/api/catalog/suppliers");
  $("#cat-body").innerHTML = rows.length ? `<div class="scroll"><table><thead><tr><th>Supplier</th><th>Contact</th><th class="num">Hotel rates</th><th class="num">Packages</th><th class="num">Activities</th><th class="num">Files</th></tr></thead><tbody>
    ${rows.map(s => `<tr class="click" data-sup="${s.id}"><td><span style="font-weight:500">${esc(s.name)}</span> <span class="pill">${esc(s.type || "")}</span><div class="small muted">${esc([s.city, s.country].filter(Boolean).join(", "))}${s.gst_number ? " · GSTIN " + esc(s.gst_number) : ""}</div></td>
      <td class="small">${esc(s.contact_person || "")}<div class="muted">${esc(s.phone || "")}</div><div class="muted">${esc(s.email || "")}</div></td>
      <td class="num">${s.hotel_rates}</td><td class="num">${s.packages}</td><td class="num">${s.services}</td><td class="num">${s.documents}</td></tr>`).join("")}</tbody></table></div>` : empty("No suppliers yet — they are added from the sheets you upload.");
  $$("[data-sup]").forEach(tr => tr.onclick = () => go("catalog", "s" + tr.dataset.sup));
}

// ================================================================ DOCUMENTS
let selectedDoc = null;
async function pageDocs(main, arg) {
  main.innerHTML = `<div class="pagehead"><div><h1>Documents</h1><p>Upload supplier rate sheets and packages. Check what was read, then approve it into the library.</p></div></div>
    <div class="card"><div class="drop" id="drop"><b>Drop rate sheets here — PDF, Excel, CSV, Word, XML or photos</b>or <label style="display:inline;margin:0;color:var(--lavender);cursor:pointer;font-size:14px"><u>choose files</u>
      <input type="file" id="file" multiple class="hidden" accept=".pdf,.xlsx,.xlsm,.xls,.csv,.tsv,.docx,.xml,.html,.htm,.json,.txt,.md,.png,.jpg,.jpeg,.webp,.gif"></label>
      <div class="small" style="margin-top:8px">Any layout. Hotel rates, packages with itineraries and prices, activities and places are all picked up, and compared with what you already have. Nothing is saved until you review it.</div></div>
      <div class="row between" style="margin-top:12px"><label>Supplier (optional)<input id="supplier" placeholder="e.g. Abdaal Travels"></label>
        <button class="btn" id="manual" style="margin-bottom:12px">${icon("plus")} Enter rates by hand</button></div>
      <div id="manualbox" class="hidden" style="padding:14px;background:var(--page);border-radius:18px"></div><div id="upmsg" class="msg"></div></div>
    <div class="card"><h2>All documents</h2><div class="scroll"><table id="docs"><thead><tr><th>#</th><th>File</th><th>Supplier</th><th>Type</th><th>Status</th><th class="num">Found</th><th class="num">Errors</th><th class="num">Checks</th></tr></thead><tbody></tbody></table></div></div>
    <div class="card hidden" id="detail"></div>`;
  $("#file").onchange = e => upload(e.target.files);
  $("#manual").onclick = manualEntry;
  const drop = $("#drop");
  drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); upload(e.dataTransfer.files); };
  await refreshDocs();
  if (arg) openDoc(+arg);
}

async function upload(files) {
  const msg = $("#upmsg"), out = [];
  for (const f of files) {
    msg.className = "msg"; msg.textContent = `Reading ${f.name}… this can take up to a minute.`;
    const fd = new FormData(); fd.append("file", f); if ($("#supplier").value) fd.append("supplier", $("#supplier").value);
    try { const d = await post("/api/documents", fd); out.push(d.duplicate ? `${f.name}: already uploaded` : `${f.name}: ${words(d.status)}${d.error ? " – " + d.error : ""}`); selectedDoc = d.id; }
    catch (e) { out.push(`${f.name}: ${e.message}`); }
    await refreshDocs();
  }
  msg.className = "msg " + (out.some(x => /failed|error|larger/i.test(x)) ? "bad" : "good"); msg.textContent = out.join(" · ");
  if (selectedDoc) openDoc(selectedDoc);
  refreshBadges();
}

let pollTimer;
async function refreshDocs() {
  const docs = await api("/api/documents");
  const found = s => (s.hotel_rates || 0) + (s.package_prices || 0) + (s.services || 0) + (s.places || 0) + (s.package_hotels || 0);
  const tb = $("#docs tbody"); if (!tb) return;
  tb.innerHTML = docs.map(d => `<tr class="click ${d.id === selectedDoc ? "sel" : ""}" data-id="${d.id}"><td>${d.id}</td><td>${esc(d.filename)}</td><td>${esc(d.supplier)}</td><td>${esc(words(d.document_type))}</td>
    <td><span class="pill ${d.status}">${esc(words(d.status))}</span></td><td class="num">${found(d.stats) || ""}</td><td class="num">${d.errors || ""}</td><td class="num">${d.warnings || ""}</td></tr>`).join("")
    || `<tr><td colspan="8" class="muted">No documents yet.</td></tr>`;
  $$("#docs tr.click").forEach(tr => tr.onclick = () => openDoc(+tr.dataset.id));
  clearTimeout(pollTimer);
  // while something is being read, refresh the list -- and the open document only if it is the one being read
  if (docs.some(d => d.status === "processing")) pollTimer = setTimeout(async () => { await refreshDocs(); if (RV && RV.doc.status === "processing") openDoc(RV.doc.id, true); }, 3000);
}

function issuesHtml(issues) {
  if (!issues.length) return `<div class="issue ok">No problems found.</div>`;
  const order = {error: 0, warning: 1};
  return [...issues].sort((a, b) => order[a.level] - order[b.level]).map(i => `<div class="issue ${i.level}"><b>${i.level === "error" ? "Must fix" : "Check"}:</b> ${esc(i.message)}<small>${esc(i.where)}</small></div>`).join("");
}

function priceGridFromRows(prices) {
  if (!prices.length) return "";
  const cats = [...new Set(prices.map(q => q.category || "-"))], rows = {};
  prices.forEach(q => { const k = q.occupancy === "double" && q.pax_min ? `${q.pax_min} pax` : words(q.occupancy) + (q.season_name ? ` (${q.season_name})` : ""); (rows[k] ??= {})[q.category || "-"] = q.amount; });
  return `<div class="scroll"><table><thead><tr><th>Per person (${esc(prices[0].currency)})</th>${cats.map(c => `<th class="num">${esc(c)}</th>`).join("")}</tr></thead><tbody>` +
    Object.entries(rows).map(([k, v]) => `<tr><td>${esc(k)}</td>${cats.map(c => `<td class="num">${num(v[c])}</td>`).join("")}</tr>`).join("") + `</tbody></table></div>`;
}

function previewHtml(n) {
  if (!n) return "";
  let h = ""; const s = n.supplier || {};
  if (s.name) h += `<p class="small muted">${esc([s.name, s.city, s.gst_number && "GSTIN " + s.gst_number, s.phone].filter(Boolean).join(" · "))}</p>`;
  for (const ht of n.hotels) {
    h += `<h3>${esc(ht.name)} <span class="muted small">${esc(ht.city || "")}${ht.star_rating ? " · " + ht.star_rating + "★" : ""}</span></h3>`;
    if (ht.rates.length) h += `<div class="scroll"><table><thead><tr><th>Room</th><th>Meal</th><th>Occupancy</th><th class="num">Amount</th><th>Net?</th><th>Tax incl.?</th><th>Valid</th><th>Days</th><th>Season</th></tr></thead><tbody>` +
      ht.rates.map(r => `<tr><td>${esc(r.room_type)}</td><td>${r.meal_plan}</td><td>${words(r.occupancy)}</td><td class="num">${num(r.amount)} ${esc(r.currency)}</td><td>${r.is_net == null ? "?" : r.is_net ? "net" : "rack"}</td>
        <td>${r.taxes_included == null ? "?" : r.taxes_included ? "yes" : "no"}</td><td class="small">${fmtDate(r.valid_from)} – ${fmtDate(r.valid_to)}</td><td>${esc(r.weekdays || "all")}</td><td>${esc(r.season_name || "")}</td></tr>`).join("") + `</tbody></table></div>`;
  }
  for (const p of n.packages) {
    h += `<h3>${esc(p.title)} <span class="muted small">${p.nights ? p.nights + "N/" + p.days + "D · " : ""}${fmtDate(p.valid_from)} – ${fmtDate(p.valid_to)}</span></h3>
      <ol>${p.itinerary.map(d => `<li><span style="font-weight:500">${esc(d.title || "")}</span> <span class="muted small">${esc(d.overnight ? "· " + d.overnight : "")}</span><div class="small">${esc(d.description || "")}</div></li>`).join("")}</ol>` + priceGridFromRows(p.prices);
    if (p.hotels.length) { const by = {}; p.hotels.forEach(x => { ((by[`${x.city || "?"} (${x.nights || "?"}N)`] ??= {})[x.category || "-"] ??= []).push(x.hotel_name); });
      h += Object.entries(by).map(([city, cats]) => `<h3>${esc(city)}</h3><div class="hotelcols">${Object.entries(cats).map(([c, names]) => `<div><b>${esc(c)}</b>${names.map(esc).join("<br>")}</div>`).join("")}</div>`).join(""); }
  }
  if (n.services.length) h += `<h3>Activities, transfers &amp; add-ons</h3>` + servicesTable(n.services);
  if (n.places?.length) h += `<h3>Places</h3><div class="cards">${n.places.map(p => `<div class="pcard" style="cursor:default"><h4>${esc(p.name)}</h4><div class="small muted">${esc([p.region, p.availability].filter(Boolean).join(" · "))}</div><div class="small">${esc(p.description || "")}</div></div>`).join("")}</div>`;
  return h;
}

function overrides() {
  const o = {}; ["valid_from", "valid_to", "currency", "rate_type", "taxes", "approved_by"].forEach(k => { const el = document.getElementById("o-" + k); if (el && el.value) o[k] = el.value; }); return o;
}

// ================================================================ TOOLS
async function pageTools(main) {
  const hotels = await api("/api/hotels");
  main.innerHTML = `<div class="pagehead"><div><h1>Tools</h1><p>Quick checks without building a trip.</p></div></div>
  <div class="grid g-main"><div class="card"><h2>Price a hotel stay</h2>${hotels.length ? `
    <div class="row"><label>Hotel<select id="q-hotel">${hotels.map(h => `<option value="${h.id}">${esc(h.name)}${h.city ? " — " + esc(h.city) : ""}</option>`).join("")}</select></label>
      <label>Room type<select id="q-room"></select></label><label>Meal plan<select id="q-mp"><option>CP</option><option>MAP</option><option>AP</option><option>EP</option><option>AI</option></select></label>
      <label>Check-in<input type="date" id="q-in"></label><label>Check-out<input type="date" id="q-out"></label></div>
    <div id="q-rooms"></div>
    <div class="row"><button class="btn" id="q-add" style="margin-bottom:12px">${icon("plus")} Room</button><label>Markup %<input type="number" id="q-markup" value="0" class="small"></label><button class="btn primary" id="q-go" style="margin-bottom:12px">Price it</button></div><div id="q-res"></div>` : empty("No hotels with rates yet.")}</div>
  <div class="card"><h2>Rates running out</h2><div class="row"><label>Within days<input type="number" id="x-days" value="45" class="small"></label><button class="btn" id="x-go" style="margin-bottom:12px">Check</button></div>
    <div class="small muted">Ask these suppliers for new sheets.</div><div id="x-out"></div></div></div>`;
  $("#x-go").onclick = async () => { const rows = await api("/api/alerts/expiring?days=" + $("#x-days").value);
    $("#x-out").innerHTML = rows.length ? `<table>${rows.map(r => `<tr><td>${esc(r.name)}<div class="small muted">${esc(r.type)}</div></td><td class="num">${fmtDate(r.last_valid_date)}</td></tr>`).join("")}</table>` : `<div class="small muted" style="margin-top:8px">Nothing expiring in that window.</div>`; };
  $("#x-go").click();
  if (!hotels.length) return;
  const fill = () => { const h = hotels.find(x => x.id == $("#q-hotel").value); $("#q-room").innerHTML = h.room_types.map(r => `<option>${esc(r)}</option>`).join(""); };
  $("#q-hotel").onchange = fill; fill();
  const addRoom = () => { const n = $("#q-rooms").children.length + 1, d = document.createElement("div"); d.className = "row";
    d.innerHTML = `<span class="muted small" style="margin:0 6px 20px 0">Room ${n}</span><label>Adults<input type="number" class="r-a small" value="2" min="1"></label><label>Child with bed<input type="number" class="r-cwb small" value="0" min="0"></label><label>Child no bed<input type="number" class="r-cnb small" value="0" min="0"></label>`;
    $("#q-rooms").appendChild(d); };
  $("#q-add").onclick = addRoom; addRoom();
  $("#q-go").onclick = async () => {
    const rooms = [...$("#q-rooms").children].map(r => ({adults: +$(".r-a", r).value, children_with_bed: +$(".r-cwb", r).value, children_without_bed: +$(".r-cnb", r).value}));
    try { const q = await post("/api/quote/hotel-stay", {hotel_id: +$("#q-hotel").value, room_type: $("#q-room").value, meal_plan: $("#q-mp").value, check_in: $("#q-in").value, check_out: $("#q-out").value, rooms, markup_pct: +$("#q-markup").value});
      $("#q-res").innerHTML = q.errors.map(e => `<div class="issue error">${esc(e)}</div>`).join("") + q.warnings.map(e => `<div class="issue warning">${esc(e)}</div>`).join("") +
        `<table><thead><tr><th>Night</th><th>Charges</th><th class="num">Total</th></tr></thead><tbody>` +
        q.nights.map(n => `<tr><td>${fmtDate(n.date)} <span class="muted">${n.day}</span></td><td class="small">${n.lines.map(l => `${esc(l.item)} ${l.qty > 1 ? l.qty + " × " : ""}${num(l.unit)}${l.season ? ` <span class="muted">${esc(l.season)}</span>` : ""}`).join("<br>")}</td><td class="num">${num(n.total)}</td></tr>`).join("") +
        q.supplements.map(s => `<tr><td>Supplement</td><td class="small">${esc(s.item)} ${s.qty} × ${num(s.unit)}</td><td class="num">${num(s.amount)}</td></tr>`).join("") +
        `</tbody></table><div class="row between center" style="margin-top:12px"><span class="muted">Cost ${money(q.cost, q.currency)} · markup ${money(q.markup, q.currency)}</span><span class="bigprice">${money(q.sell, q.currency)}</span></div>`;
    } catch (e) { $("#q-res").innerHTML = `<div class="issue error">${esc(e.message)}</div>`; }
  };
}

// ================================================================ SETTINGS
let setTab = "company";
async function pageSettings(main, arg) {
  if (arg) setTab = arg;
  const tabs = [["company", "Company"], ["quotes", "Quotes"], ["team", "Team & sign-in"], ["ai", "AI connector"], ["processing", "Processing"], ["data", "Data"], ["system", "System"]];
  main.innerHTML = `<div class="pagehead"><div><h1>Settings</h1><p>Everything the Studio does, adjustable here — no code changes needed.</p></div></div>
    <div class="subnav">${tabs.map(([k, l]) => `<button data-st="${k}" class="${k === setTab ? "on" : ""}">${l}</button>`).join("")}</div><div id="st-body"></div>`;
  $$("[data-st]", main).forEach(b => b.onclick = () => go("settings", b.dataset.st));
  await ({company: stCompany, quotes: stQuotes, team: stTeam, ai: stAI, processing: stProcessing, data: stData, system: stSystem})[setTab || "company"]($("#st-body"));
}
const lines = v => v.split("\n").map(x => x.trim()).filter(Boolean);
async function saveSettings(part) { SETTINGS = await put("/api/settings", part); toast("Settings saved"); }

async function stCompany(el) {
  const s = SETTINGS = await api("/api/settings"), c = s.company;
  el.innerHTML = `<div class="card" style="max-width:860px"><h2>Company <span class="small muted">printed on quotes, PDFs and client links</span></h2>
    <div class="row"><label class="grow">Name<input id="c-name" class="w100" value="${esc(c.name)}"></label><label class="grow">Tagline<input id="c-tag" class="w100" value="${esc(c.tagline)}"></label></div>
    <label class="w100">Address<textarea id="c-addr">${esc(c.address)}</textarea></label>
    <div class="row"><label class="grow">Email<input id="c-email" class="w100" value="${esc(c.email)}"></label><label class="grow">Instagram<input id="c-ig" class="w100" value="${esc(c.instagram)}"></label></div>
    <div class="row"><label class="grow">Website<input id="c-web" class="w100" value="${esc(c.website)}"></label><label class="grow">GSTIN<input id="c-gst" class="w100" value="${esc(c.gst_number)}"></label></div>
    <button class="btn primary" id="sv">Save</button></div>`;
  $("#sv").onclick = () => saveSettings({company: {name: $("#c-name").value, tagline: $("#c-tag").value, address: $("#c-addr").value, email: $("#c-email").value,
    instagram: $("#c-ig").value.replace(/^@/, ""), website: $("#c-web").value, gst_number: $("#c-gst").value}}).catch(e => toast(e.message, true));
}

async function stQuotes(el) {
  const s = SETTINGS = await api("/api/settings"), q = s.quote;
  el.innerHTML = `<div class="card" style="max-width:860px"><h2>Quotes</h2>
    <div class="row"><label>Default markup %<input id="q-mk" type="number" class="small" value="${q.default_markup_pct}"></label><label>Default GST %<input id="q-gst" type="number" class="small" value="${q.default_gst_pct}"></label>
      <label>Quote valid for (days)<input id="q-val" type="number" class="small" value="${q.validity_days}"></label></div>
    <label class="w100">Payment terms<input id="q-pay" class="w100" value="${esc(q.payment_terms)}"></label>
    <label class="w100">Bank details <span class="muted">(printed on quotes)</span><textarea id="q-bank" placeholder="Account name, number, IFSC, UPI ID">${esc(q.bank_details)}</textarea></label>
    <label class="w100">Standard terms <span class="muted">(one per line)</span><textarea id="q-terms">${esc((q.terms || []).join("\n"))}</textarea></label>
    <label class="w100">Closing line<input id="q-foot" class="w100" value="${esc(q.footer)}"></label>
    <h3>Lead sources <span class="muted small">(one per line — shown on trips and the dashboard)</span></h3><textarea id="ls">${esc(s.lead_sources.join("\n"))}</textarea>
    <div style="margin-top:10px"><button class="btn primary" id="sv">Save</button></div></div>`;
  $("#sv").onclick = () => saveSettings({lead_sources: lines($("#ls").value), quote: {default_markup_pct: +$("#q-mk").value, default_gst_pct: +$("#q-gst").value,
    validity_days: +$("#q-val").value, payment_terms: $("#q-pay").value, bank_details: $("#q-bank").value, terms: lines($("#q-terms").value), footer: $("#q-foot").value}}).catch(e => toast(e.message, true));
}

async function stTeam(el) {
  const s = SETTINGS = await api("/api/settings");
  el.innerHTML = `<div class="grid g2"><div class="card"><h2>Team on quotes <button class="btn sm" id="tm-add">${icon("plus")} Person</button></h2>
      <div class="small muted" style="margin-bottom:8px">Name and phone printed as "Prepared by" on quotes and client links.</div>
      <div id="tm-list">${s.team.map(m => `<div class="row tm" style="margin-bottom:6px"><input class="grow tm-n" value="${esc(m.name)}" placeholder="Name"><input class="tm-p" value="${esc(m.phone || "")}" placeholder="+91"><button class="icon tm-x">✕</button></div>`).join("")}</div>
      <button class="btn primary" id="sv" style="margin-top:8px">Save team</button></div>
    <div class="card"><h2>Your account</h2><p class="small muted">Signed in as ${esc(ME?.name || "")} (${esc(ME?.email || "")}).</p><button class="btn" id="st-pw">Change my password</button>
      <h3>How sign-in works</h3><ul class="small muted"><li>Only admins listed below can sign in — with their password or with "Sign in with Google" using the same email. There is no public sign-up.</li><li>5 wrong passwords lock an account for 15 minutes.</li>
      <li>Sign-ins last ${esc(String((await api("/api/settings/processing")).values.session_days))} days (Processing tab).</li><li>Disabling a user signs them out everywhere immediately.</li></ul></div></div>
  <div class="card" id="users-card"><h2>Admin users <span class="small muted">only people listed here can sign in</span></h2><div id="users"></div>
    <h3>Add an admin</h3>
    <div class="row"><label>Name<input id="nu-name"></label><label>Email<input id="nu-email" type="email" placeholder="name@gmail.com"></label>
      <label class="check" style="margin-bottom:20px"><input type="checkbox" id="nu-g" checked>Google sign-in only</label>
      <label id="nu-pwbox" class="hidden">Temporary password<input id="nu-pw" type="text" placeholder="10+ characters"></label>
      <button class="btn primary" id="nu-go" style="margin-bottom:12px">Add admin</button></div>
    <div class="small muted" id="nu-help"></div></div>`;
  const wireX = () => $$(".tm-x").forEach(b => b.onclick = () => b.closest(".tm").remove());
  $("#tm-add").onclick = () => { const d = document.createElement("div"); d.className = "row tm"; d.style.marginBottom = "6px"; d.innerHTML = `<input class="grow tm-n" placeholder="Name"><input class="tm-p" placeholder="+91"><button class="icon tm-x">✕</button>`; $("#tm-list").appendChild(d); wireX(); };
  wireX();
  $("#sv").onclick = () => saveSettings({team: $$(".tm").map(r => ({name: $(".tm-n", r).value.trim(), phone: $(".tm-p", r).value.trim()})).filter(m => m.name)}).catch(e => toast(e.message, true));
  $("#st-pw").onclick = () => changePassword(false);
  const prov = await api("/api/auth/providers").catch(() => ({}));
  const help = () => { const g = $("#nu-g").checked; $("#nu-pwbox").classList.toggle("hidden", g);
    $("#nu-help").textContent = g ? (prov.google ? "They sign in with the Google button using exactly this email. No password to share."
                                                 : "Google sign-in isn't set up on the server yet (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET) — until it is, give them a password instead.")
      : "They choose their own password the first time they sign in. Share the temporary one in person or on a call, not in a group chat."; };
  $("#nu-g").onchange = help; help();
  $("#nu-go").onclick = async () => {
    try { await post("/api/users", {name: $("#nu-name").value, email: $("#nu-email").value, google_only: $("#nu-g").checked, password: $("#nu-g").checked ? "" : $("#nu-pw").value});
      ["#nu-name", "#nu-email", "#nu-pw"].forEach(s => $(s).value = ""); toast("Admin added"); drawUsers(); }
    catch (e) { toast(e.message, true); }
  };
  drawUsers();
}

// ---------------------------------------------------------------- AI connector
const fmtTok = n => n >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + "k" : String(n || 0);
const fmtCost = (n, cur) => n == null ? "—" : `${cur === "USD" ? "$" : cur === "INR" ? "₹" : (cur || "") + " "}${Number(n).toLocaleString("en-IN", {maximumFractionDigits: n < 1 ? 4 : 2})}`;
let aiDays = 30, aiTable = false;
async function stAI(el) {
  const [c, u] = await Promise.all([api("/api/ai/settings"), api("/api/ai/usage?days=" + aiDays)]);
  const prov = c.providers.find(p => p.id === c.provider), M = u.month, cur = u.price_currency;
  el.innerHTML = `
  ${c.demo_mode ? `<div class="issue warning">Demo mode is on (FIXTURES_DIR): documents are read from saved examples and no AI is called.</div>` : ""}
  <div class="kpis">
    <div class="kpi"><small>AI calls this month</small><b>${M.calls}</b><span>${M.failed ? `${M.failed} failed` : "none failed"}${M.avg_seconds ? ` · ${M.avg_seconds}s average` : ""}</span></div>
    <div class="kpi"><small>Tokens sent (input)</small><b>${fmtTok(M.input_tokens)}</b><span>this month</span></div>
    <div class="kpi"><small>Tokens received (output)</small><b>${fmtTok(M.output_tokens)}</b><span>this month</span></div>
    <div class="kpi"><small>Estimated cost</small><b class="accent">${u.prices_set ? fmtCost(M.cost || 0, cur) : "—"}</b><span>${u.prices_set ? "this month" : "add prices below to see cost"}</span></div>
    ${u.budget ? `<div class="kpi"><small>Monthly budget</small><b>${u.budget_used_pct}%</b><span>of ${fmtCost(u.budget, cur)} used</span><div class="pbar" style="margin:8px 0 0"><i style="width:${Math.min(100, u.budget_used_pct)}%;background:${u.budget_used_pct >= 90 ? "var(--err)" : "var(--lavender)"}"></i></div></div>` : ""}
  </div>
  <div class="grid g-main"><div>
    <div class="card"><h2>Tokens per day <span class="row"><select id="ai-days">${[7, 30, 90].map(d => `<option value="${d}" ${d === aiDays ? "selected" : ""}>Last ${d} days</option>`).join("")}</select>
      <button class="btn sm" id="ai-tbl">${aiTable ? "Show chart" : "Show table"}</button></span></h2><div id="ai-chart"></div></div>
    <div class="card"><h2>By model <span class="small muted">last ${aiDays} days</span></h2>${u.by_model.length ? `<table><thead><tr><th>Provider · model</th><th class="num">Calls</th><th class="num">Input</th><th class="num">Output</th><th class="num">Cost</th></tr></thead><tbody>
      ${u.by_model.map(m => `<tr><td>${esc(m.model)}</td><td class="num">${m.calls}</td><td class="num">${fmtTok(m.input_tokens)}</td><td class="num">${fmtTok(m.output_tokens)}</td><td class="num">${u.prices_set ? fmtCost(m.cost, cur) : "—"}</td></tr>`).join("")}</tbody></table>` : `<div class="small muted">No AI calls yet in this period.</div>`}</div>
    <div class="card"><h2>Recent AI calls</h2>${u.recent.length ? `<div class="scroll"><table><thead><tr><th>When</th><th>For</th><th class="num">In</th><th class="num">Out</th><th class="num">Time</th><th class="num">Cost</th></tr></thead><tbody>
      ${u.recent.map(r => `<tr><td class="small" style="white-space:nowrap">${new Date(r.at).toLocaleString("en-IN", {day: "numeric", month: "short", hour: "numeric", minute: "2-digit"})}</td>
        <td>${r.document ? `<button class="link" data-go="docs/${r.document_id}">${esc(r.document)}</button>` : esc(r.purpose)}${r.ok ? "" : ` <span class="pill bad" title="${esc(r.error || "")}">failed</span>`}<div class="small muted">${esc(r.model)}</div></td><td class="num">${fmtTok(r.input_tokens)}</td><td class="num">${fmtTok(r.output_tokens)}</td><td class="num">${r.seconds ?? ""}s</td><td class="num">${r.cost == null ? "—" : fmtCost(r.cost, cur)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="small muted">Nothing yet — upload a document or press Test connection.</div>`}</div>
  </div><div class="rail">
    <div class="card"><h2>Connection</h2>
      <label class="w100">AI provider<select id="ai-prov" class="w100">${c.providers.map(p => `<option value="${p.id}" ${p.id === c.provider ? "selected" : ""}>${esc(p.label)}</option>`).join("")}</select></label>
      <div class="small muted" id="ai-note" style="margin:-4px 0 10px">${esc(prov.note)}</div>
      <label class="w100">Model<input id="ai-model" class="w100" list="ai-models" value="${esc(c.model || "")}" placeholder="exact model name from the provider"><datalist id="ai-models">${prov.models.map(m => `<option value="${esc(m)}">`).join("")}</datalist></label>
      <label class="w100 ${prov.kind === "anthropic" ? "hidden" : ""}" id="ai-base-wrap">Base URL<input id="ai-base" class="w100" value="${esc(c.base_url || "")}" placeholder="https://…/v1"></label>
      <label class="w100">API key <span id="ai-keypill">${c.key_set ? `<span class="pill ok">${esc(c.key_hint)} · ${c.key_source === "app" ? "saved in app" : "from " + esc(c.key_env_var)}</span>` : `<span class="pill bad">not set</span>`}</span>
        <input id="ai-key" type="password" class="w100" autocomplete="off" placeholder="${c.key_set ? "leave empty to keep the current key" : "paste the key"}" ${c.can_save_keys ? "" : "disabled"}></label>
      ${c.can_save_keys ? "" : `<div class="issue warning">Set SECRET_KEY on the server to save keys here. Until then use the ${esc(c.key_env_var)} environment variable.</div>`}
      <div class="small muted" id="ai-keylink" style="margin:-4px 0 10px">${prov.keys_url ? `Get a key: <a href="${esc(prov.keys_url)}" target="_blank" rel="noopener">${esc(prov.keys_url.replace("https://", ""))}</a>` : ""}</div>
      <label class="check"><input type="checkbox" id="ai-on" ${c.enabled ? "checked" : ""}> AI reading switched on</label>
      <div class="row" style="margin-top:10px"><button class="btn primary" id="ai-save">Save</button><button class="btn" id="ai-test">Test connection</button>${c.key_source === "app" ? `<button class="btn sm" id="ai-clear">Remove saved key</button>` : ""}</div>
      <div id="ai-testout" class="msg"></div></div>
    <div class="card"><h2>Limits &amp; cost</h2>
      <label class="w100">Max tokens per answer<input id="ai-max" type="number" class="w100" value="${esc(c.max_tokens)}"></label>
      <div class="small muted" style="margin:-4px 0 10px">Big package PDFs need long answers. If a document is cut off, raise this.</div>
      <div class="row"><label class="grow">Price per 1M input tokens<input id="ai-pin" type="number" step="0.01" class="w100" value="${c.price_input_per_mtok ?? ""}"></label>
        <label class="grow">Price per 1M output tokens<input id="ai-pout" type="number" step="0.01" class="w100" value="${c.price_output_per_mtok ?? ""}"></label></div>
      <div class="row"><label class="grow">Currency<select id="ai-cur" class="w100">${["USD", "INR", "EUR"].map(x => `<option ${x === (c.price_currency || "USD") ? "selected" : ""}>${x}</option>`).join("")}</select></label>
        <label class="grow">Monthly budget<input id="ai-budget" type="number" step="0.01" class="w100" value="${c.monthly_budget ?? ""}" placeholder="no limit"></label></div>
      <div class="small muted">Copy prices from your provider's pricing page. When the month's estimated cost reaches the budget, new documents wait until you raise it.</div>
      <label class="w100 ${prov.kind === "anthropic" ? "hidden" : ""}" style="margin-top:10px" id="ai-pages-wrap">Scanned PDF pages to send<input id="ai-pages" type="number" min="1" max="100" class="w100" value="${c.max_pdf_pages ?? 20}"></label>
      <button class="btn primary" id="ai-save2" style="margin-top:10px">Save</button></div>
    <div class="card"><h2>Extra instructions</h2>
      <div class="small muted" style="margin-bottom:8px">Your own rules, added to the built-in ones every time a document is read. Use them when a supplier's sheets keep coming out wrong.</div>
      <textarea id="ai-extra" style="min-height:120px" maxlength="4000" placeholder="e.g. Abdaal Travels prices are always net B2B.&#10;'Room + Brekkie' means CP.&#10;Treat 'Deluxe Plus' as its own category.">${esc(c.extra_instructions || "")}</textarea>
      <div class="small muted" id="ai-extra-n">${(c.extra_instructions || "").length} / 4000</div>
      <button class="btn primary" id="ai-save3" style="margin-top:8px">Save instructions</button></div>
  </div></div>`;
  wireGo(el);
  drawUsageChart(u);
  $("#ai-days").onchange = e => { aiDays = +e.target.value; stAI(el); };
  $("#ai-tbl").onclick = () => { aiTable = !aiTable; stAI(el); };
  $("#ai-prov").onchange = e => {
    const p = c.providers.find(x => x.id === e.target.value);
    $("#ai-note").textContent = p.note; $("#ai-base-wrap").classList.toggle("hidden", p.kind === "anthropic"); $("#ai-pages-wrap").classList.toggle("hidden", p.kind === "anthropic");
    $("#ai-base").value = p.base_url || ""; $("#ai-model").value = p.default_model || "";
    $("#ai-models").innerHTML = p.models.map(m => `<option value="${esc(m)}">`).join("");
    $("#ai-key").placeholder = "paste the " + p.label + " key";
    // the key badge must describe the key the *selected* provider would use
    $("#ai-keypill").innerHTML = p.id === c.provider && c.key_set
      ? `<span class="pill ok">${esc(c.key_hint)} · ${c.key_source === "app" ? "saved in app" : "from " + esc(c.key_env_var)}</span>`
      : p.env_key_set ? `<span class="pill ok">from ${esc(p.env)}</span>` : `<span class="pill bad">not set — paste the ${esc(p.label)} key</span>`;
    $("#ai-keylink").innerHTML = p.keys_url ? `Get a key: <a href="${esc(p.keys_url)}" target="_blank" rel="noopener">${esc(p.keys_url.replace("https://", ""))}</a>` : "";
  };
  const save = async () => {
    const body = {provider: $("#ai-prov").value, model: $("#ai-model").value, base_url: $("#ai-base").value, enabled: $("#ai-on").checked,
      max_tokens: $("#ai-max").value, price_input_per_mtok: $("#ai-pin").value, price_output_per_mtok: $("#ai-pout").value,
      price_currency: $("#ai-cur").value, monthly_budget: $("#ai-budget").value, extra_instructions: $("#ai-extra").value, max_pdf_pages: $("#ai-pages").value};
    if ($("#ai-key").value) body.api_key = $("#ai-key").value;
    try { await put("/api/ai/settings", body); toast("AI settings saved"); stAI(el); } catch (e) { toast(e.message, true); }
  };
  $("#ai-save").onclick = save; $("#ai-save2").onclick = save; $("#ai-save3").onclick = save;
  $("#ai-extra").oninput = e => $("#ai-extra-n").textContent = `${e.target.value.length} / 4000`;
  $("#ai-clear") && ($("#ai-clear").onclick = async () => { if (!confirm("Remove the key saved in the app?")) return; await put("/api/ai/settings", {clear_key: true}); toast("Key removed"); stAI(el); });
  $("#ai-test").onclick = async () => {
    const out = $("#ai-testout"); out.className = "msg"; out.textContent = "Testing…";
    const r = await post("/api/ai/test");
    out.className = "msg " + (r.ok ? "good" : "bad");
    out.textContent = r.ok ? `Connected in ${r.seconds}s — "${r.reply}"${r.input_tokens != null ? ` (${r.input_tokens} in / ${r.output_tokens} out tokens)` : ""}` : `Failed: ${r.error}`;
  };
}

function drawUsageChart(u) {
  const box = $("#ai-chart"), days = u.daily;
  if (aiTable) {
    box.innerHTML = `<div class="scroll" style="max-height:340px;overflow:auto"><table><thead><tr><th>Date</th><th class="num">Calls</th><th class="num">Input tokens</th><th class="num">Output tokens</th><th class="num">Cost</th></tr></thead><tbody>
      ${days.slice().reverse().map(d => `<tr><td>${fmtDate(d.date)}</td><td class="num">${d.calls}</td><td class="num">${d.input_tokens.toLocaleString("en-IN")}</td><td class="num">${d.output_tokens.toLocaleString("en-IN")}</td><td class="num">${u.prices_set ? fmtCost(d.cost, u.price_currency) : "—"}</td></tr>`).join("")}</tbody></table></div>`;
    return;
  }
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const cIn = dark ? "#7d82c9" : "#8286cb", cOut = dark ? "#dd6a2d" : "#ef712c";   // validated for each surface
  const W = 720, H = 220, L = 44, R = 8, T = 10, B = 26, n = days.length;
  const max = Math.max(1, ...days.map(d => d.input_tokens + d.output_tokens));
  const step = [1, 2, 5].flatMap(m => [1, 10, 100, 1e3, 1e4, 1e5, 1e6, 1e7].map(p => m * p)).find(s => max / s <= 4);
  const top = Math.ceil(max / step) * step, y = v => T + (H - T - B) * (1 - v / top);
  const bw = (W - L - R) / n, gap = Math.max(2, bw * 0.28), w = Math.max(2, bw - gap);
  const ticks = []; for (let v = 0; v <= top; v += step) ticks.push(v);
  const labelEvery = Math.ceil(n / 8);
  const bars = days.map((d, i) => {
    const x = L + i * bw + gap / 2, yi = y(d.input_tokens), yo = y(d.input_tokens + d.output_tokens), base = y(0);
    const hIn = base - yi, hOut = yi - yo;
    const seg = (yTop, h, color, roundTop) => h <= 0 ? "" : roundTop
      ? `<path d="M${x},${yTop + h} V${yTop + Math.min(4, h)} Q${x},${yTop} ${x + Math.min(4, w / 2)},${yTop} H${x + w - Math.min(4, w / 2)} Q${x + w},${yTop} ${x + w},${yTop + Math.min(4, h)} V${yTop + h} Z" fill="${color}"/>`
      : `<rect x="${x}" y="${yTop}" width="${w}" height="${h}" fill="${color}"/>`;
    const outTop = hOut > 0;
    return `<g class="bar" data-i="${i}">${seg(yi + (outTop ? 1 : 0), Math.max(0, hIn - (outTop ? 1 : 0)), cIn, !outTop)}${seg(yo, Math.max(0, hOut - 1), cOut, true)}
      <rect x="${L + i * bw}" y="${T}" width="${bw}" height="${H - T - B}" fill="transparent"/></g>`;
  }).join("");
  box.innerHTML = `<div class="legend" style="margin-bottom:6px"><span style="--c:${cIn}">Input tokens (sent to the AI)</span><span style="--c:${cOut}">Output tokens (AI's answer)</span></div>
    <div style="position:relative"><svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="AI tokens per day, last ${n} days">
      ${ticks.map(v => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)" stroke-width="1"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end" font-size="10" fill="var(--ink-muted)">${fmtTok(v)}</text>`).join("")}
      ${bars}
      ${days.map((d, i) => i % labelEvery === 0 ? `<text x="${L + i * bw + bw / 2}" y="${H - 8}" text-anchor="middle" font-size="10" fill="var(--ink-muted)">${new Date(d.date + "T00:00:00").toLocaleDateString("en-GB", {day: "numeric", month: "short"})}</text>` : "").join("")}
    </svg><div id="ai-tip" style="position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:8px 10px;font-size:12px;display:none;white-space:nowrap"></div></div>`;
  const tip = $("#ai-tip"), svg = $("svg", box);
  $$("g.bar", box).forEach(g => {
    g.onmouseenter = () => { const d = days[+g.dataset.i]; g.style.opacity = 1;
      tip.innerHTML = `<b>${fmtDate(d.date)}</b><br>${d.calls} call${d.calls === 1 ? "" : "s"}<br><span style="color:${cIn}">■</span> ${d.input_tokens.toLocaleString("en-IN")} in<br><span style="color:${cOut}">■</span> ${d.output_tokens.toLocaleString("en-IN")} out${u.prices_set ? "<br>" + fmtCost(d.cost, u.price_currency) : ""}`;
      tip.style.display = "block"; };
    g.onmousemove = e => { const r = svg.getBoundingClientRect(); tip.style.left = Math.min(r.width - 150, e.clientX - r.left + 12) + "px"; tip.style.top = (e.clientY - r.top - 10) + "px"; };
    g.onmouseleave = () => tip.style.display = "none";
  });
}

async function stProcessing(el) {
  const p = await api("/api/settings/processing"), v = p.values, h = p.help;
  const field = (k, input) => `<label class="w100">${esc(k.replaceAll("_", " ").replace(/^./, c => c.toUpperCase()))}${input}<span class="small muted" style="font-weight:400">${esc(h[k])} · default ${esc(String(p.defaults[k]))}</span></label>`;
  el.innerHTML = `<div class="card" style="max-width:760px"><h2>Processing <span class="small muted">how documents are read and checked</span></h2>
    ${field("pdf_mode", `<select id="p-pdf_mode">${["auto", "text", "native"].map(x => `<option ${x === v.pdf_mode ? "selected" : ""}>${x}</option>`).join("")}</select>`)}
    ${field("chunk_chars", `<input id="p-chunk_chars" type="number" value="${v.chunk_chars}">`)}
    ${field("default_currency", `<input id="p-default_currency" value="${esc(v.default_currency)}" maxlength="3" style="text-transform:uppercase">`)}
    ${field("weekend_days", `<input id="p-weekend_days" value="${esc(v.weekend_days)}">`)}
    ${field("max_upload_mb", `<input id="p-max_upload_mb" type="number" step="0.1" value="${v.max_upload_mb}">`)}
    ${field("session_days", `<input id="p-session_days" type="number" value="${v.session_days}">`)}
    <label class="check" style="margin-bottom:4px"><input type="checkbox" id="p-auto_approve" ${v.auto_approve ? "checked" : ""}> Auto-approve documents with no errors</label>
    <div class="small muted" style="margin-bottom:14px">${esc(h.auto_approve)}. Recommended: off — a quick human check protects your margins.</div>
    <button class="btn primary" id="sv">Save</button></div>`;
  $("#sv").onclick = async () => {
    const body = {}; ["pdf_mode", "chunk_chars", "default_currency", "weekend_days", "max_upload_mb", "session_days"].forEach(k => body[k] = $("#p-" + k).value);
    body.default_currency = body.default_currency.toUpperCase(); body.auto_approve = $("#p-auto_approve").checked;
    try { await put("/api/settings/processing", body); toast("Saved"); } catch (e) { toast(e.message, true); }
  };
}

async function stData(el) {
  el.innerHTML = `<div class="grid g2"><div class="card"><h2>Backup &amp; export</h2><p class="small muted">Everything as one spreadsheet — rates, packages, activities, hotels, places, suppliers and trips. Download one every week and keep it somewhere safe.</p>
      <button class="btn" id="st-xlsx">${icon("down")} Download full backup (Excel)</button>
      <h3>Single lists (CSV)</h3><div class="row">${["hotel-rates", "packages", "services", "hotels", "places", "suppliers", "trips"].map(k => `<button class="btn sm" data-csv="${k}">${k.replace("-", " ")}</button>`).join("")}</div></div>
    <div class="card"><h2>Where things live</h2><ul class="small">
      <li>All data: your PostgreSQL database (e.g. Supabase). Supabase's <b>Free plan has no backups</b> — download the Excel backup weekly, or move to Pro for daily backups.</li>
      <li>Uploaded documents: stored inside the database with the extracted data.</li>
      <li>AI keys saved here: encrypted with the server's SECRET_KEY.</li>
      <li>Server settings (database address, SECRET_KEY, first admin): environment variables — see the System tab and docs/03-configuration.md.</li></ul></div></div>`;
  $("#st-xlsx").onclick = () => download("/api/export/library.xlsx");
  $$("[data-csv]").forEach(b => b.onclick = () => download(`/api/export/${b.dataset.csv}.csv`));
}

async function stSystem(el) {
  const r = await api("/api/system"), d = r.database;
  const ok = v => v ? '<span class="pill ok">set</span>' : '<span class="pill">not set</span>';
  el.innerHTML = `${r.warnings.map(w => `<div class="issue warning">${esc(w)}</div>`).join("")}
  <div class="grid g2"><div class="card"><h2>Database</h2>
      ${d.kind === "unreachable" ? `<div class="issue error">Can't reach the database: ${esc(d.error)}</div>` : `<table><tbody>
        <tr><td>Type</td><td><b style="font-weight:600">${esc(d.kind)}</b></td></tr>
        ${d.host ? `<tr><td>Host</td><td class="small">${esc(d.host)}${d.port ? ":" + d.port : ""}</td></tr>` : ""}
        ${d.database ? `<tr><td>Database · user</td><td class="small">${esc(d.database)} · ${esc(d.user || "")}</td></tr>` : ""}
        ${d.server_version ? `<tr><td>PostgreSQL</td><td>${esc(d.server_version)}</td></tr>` : ""}
        <tr><td>Schema version</td><td>${esc(d.schema_version || "—")} <span class="small muted">(updated automatically on start)</span></td></tr>
        ${d.size_mb != null ? `<tr><td>Size</td><td>${d.size_mb} MB <span class="small muted">(Supabase free plan: 500 MB)</span></td></tr>` : ""}
        ${d.supabase_roles ? `<tr><td>Supabase Data API</td><td>${d.data_api_locked ? '<span class="pill ok">locked — tables not readable with the anon key</span>' : '<span class="pill bad">open</span>'}</td></tr>` : ""}
      </tbody></table>`}
      <div class="small muted" style="margin-top:10px">The database address is a server setting (DATABASE_URL) — it can't be changed from here because the app needs it to open this page.</div></div>
    <div class="card"><h2>Server settings <span class="small muted">environment variables — values are never shown</span></h2>
      <table><tbody>${r.env.map(e => `<tr><td><code style="font-size:12px">${esc(e.name)}</code>${e.required ? ' <span class="small muted">required</span>' : ""}<div class="small muted">${esc(e.about)}</div></td><td class="num">${ok(e.set)}</td></tr>`).join("")}</tbody></table>
      <div class="small muted" style="margin-top:10px">Change these in your host's dashboard (Vercel → Project → Settings → Environment Variables) or the .env file, then redeploy / restart.</div></div></div>
  <div class="grid g2"><div class="card"><h2>Application</h2><table><tbody>
      <tr><td>Version</td><td>${esc(r.version)}</td></tr><tr><td>Python</td><td>${esc(r.python)}</td></tr><tr><td>Running on</td><td>${r.on_vercel ? "Vercel" : "server / local"}</td></tr>
      <tr><td>Admin users</td><td>${r.counts.users}</td></tr><tr><td>Documents</td><td>${r.counts.documents}</td></tr><tr><td>Trips</td><td>${r.counts.trips}</td></tr><tr><td>AI calls logged</td><td>${r.counts.ai_calls}</td></tr></tbody></table></div>
    <div class="card"><h2>What's set where</h2><ul class="small">
      <li><b>Here in Settings</b> (saved in the database): company, quotes, team, users, AI provider / model / key / prices / budget / instructions, processing options.</li>
      <li><b>Server environment</b> (needed before the database can be opened): DATABASE_URL, SECRET_KEY, first admin, API_KEY, CORS_ORIGINS.</li>
      <li>Full list with explanations: <code>.env.example</code> and <code>docs/03-configuration.md</code>.</li></ul></div></div>`;
}

async function drawUsers() {
  const users = await api("/api/users");
  $("#users").innerHTML = `<div class="scroll"><table><thead><tr><th>Name</th><th>Email</th><th>Status</th><th>Last sign-in</th><th></th></tr></thead><tbody>${users.map(u => `<tr>
    <td>${esc(u.name)}${u.id === ME?.id ? ' <span class="pill">you</span>' : ""}</td><td>${esc(u.email)}</td>
    <td>${u.active ? '<span class="pill ok">active</span>' : '<span class="pill bad">disabled</span>'}${u.has_password ? "" : ' <span class="pill">Google only</span>'}${u.must_change_password ? ' <span class="pill warn">must set password</span>' : ""}</td>
    <td class="small">${u.last_login_at ? new Date(u.last_login_at).toLocaleString("en-IN", {dateStyle: "medium", timeStyle: "short"}) : "never"}</td>
    <td class="num">${u.id === ME?.id ? "" : `<button class="btn sm" data-reset="${u.id}">${u.has_password ? "Reset password" : "Give a password"}</button> <button class="btn sm" data-act="${u.id}" data-on="${u.active ? 0 : 1}">${u.active ? "Disable" : "Enable"}</button>`}</td></tr>`).join("")}</tbody></table></div>`;
  $$("[data-act]").forEach(b => b.onclick = async () => { try { await patch(`/api/users/${b.dataset.act}`, {active: b.dataset.on === "1"}); toast("Updated"); drawUsers(); } catch (e) { toast(e.message, true); } });
  $$("[data-reset]").forEach(b => b.onclick = async () => {
    const pw = prompt("New temporary password for this user (10+ characters). They'll choose their own when they next sign in.");
    if (!pw) return;
    try { await patch(`/api/users/${b.dataset.reset}`, {password: pw}); toast("Password reset; they've been signed out"); drawUsers(); } catch (e) { toast(e.message, true); }
  });
}

function changePassword(forced) {
  const wrap = document.createElement("div");
  wrap.style.cssText = "position:fixed;inset:0;background:rgba(40,38,39,.55);display:flex;align-items:center;justify-content:center;z-index:90;padding:16px";
  wrap.innerHTML = `<div class="card" style="width:100%;max-width:420px;margin:0">${dots()}<h2>${forced ? "Choose your own password" : "Change password"}</h2>
    ${forced ? `<p class="small muted">An admin set a temporary password for you. Pick a new one to continue.</p>` : ""}
    ${ME && ME.has_password === false ? `<p class="small muted">You sign in with Google. Adding a password lets you sign in without it too.</p><input id="pw-cur" type="hidden" value="">`
      : `<label class="w100">Current password<input id="pw-cur" type="password" class="w100" autocomplete="current-password"></label>`}
    <label class="w100">New password <span class="muted">(10+ characters)</span><input id="pw-new" type="password" class="w100" autocomplete="new-password"></label>
    <label class="w100">Repeat new password<input id="pw-rep" type="password" class="w100" autocomplete="new-password"></label>
    <div class="row"><button class="btn primary" id="pw-go">Save password</button>${forced ? "" : `<button class="btn" id="pw-x">Cancel</button>`}</div><div class="msg" id="pw-msg"></div></div>`;
  document.body.appendChild(wrap);
  $("#pw-x") && ($("#pw-x").onclick = () => wrap.remove());
  $("#pw-go").onclick = async () => {
    const m = $("#pw-msg");
    if ($("#pw-new").value !== $("#pw-rep").value) { m.className = "msg bad"; m.textContent = "The new passwords don't match"; return; }
    try { await post("/api/auth/password", {current_password: $("#pw-cur").value, new_password: $("#pw-new").value});
      wrap.remove(); ME.must_change_password = false; toast("Password changed"); }
    catch (e) { m.className = "msg bad"; m.textContent = e.message; }
  };
}

async function signOut() { await post("/api/auth/logout"); location.href = "/login"; }

// ---------------------------------------------------------------- start
(async () => {
  try { ME = await api("/api/auth/me"); } catch (e) { return; }
  $("#sidefoot").innerHTML = `<div style="font-weight:600;color:var(--ink)">${esc(ME.name)}</div><div class="small">${esc(ME.email)}</div>
    <div class="row" style="margin-top:8px"><button class="link small" id="sf-pw">Password</button><button class="link small" id="sf-out">Sign out</button></div>
    <div class="small" style="margin-top:10px">${new Date().toLocaleDateString("en-GB", {weekday: "long", day: "numeric", month: "long"})}</div>`;
  $("#sf-out").onclick = signOut; $("#sf-pw").onclick = () => changePassword(false);
  route(); refreshBadges();
  if (ME.must_change_password) changePassword(true);
})();
