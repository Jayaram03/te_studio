// Rate history: how prices moved from sheet to sheet. Hotel rate timelines, package versions, recent changes,
// and the supplier page.
"use strict";

const PALETTE = ["#8286cb", "#ef712c", "#b54a21", "#5f6062", "#f39d6f", "#a5a4d4"];
const STATE_LBL = {current: "current", upcoming: "upcoming", expired: "expired", replaced: "replaced"};
const statePill = s => `<span class="pill ${s === "current" ? "ok" : s === "upcoming" ? "" : s === "replaced" ? "bad" : "warn"}">${STATE_LBL[s] || s}</span>`;
const pctTxt = p => p == null || p === 0 ? "" : `<span class="${p > 0 ? "up" : "downc"}">${p > 0 ? "▲ +" : "▼ "}${p}%</span>`;

const tsOf = iso => new Date(iso.slice(0, 10) + "T00:00:00").getTime();
const shortDate = t => new Date(t).toLocaleDateString("en-GB", {month: "short", year: "2-digit"});
function niceTicks(lo, hi, n = 4) {
  if (hi <= lo) { hi = lo + 1; }
  const raw = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(raw)), step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw);
  const out = []; for (let v = Math.floor(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v); return out;
}

// every rate of one room / meal / occupancy as a bar along its dates; replaced rates dashed and grey
function rateTimelineSVG(series) {
  const W = 760, H = 250, L = 64, R = 16, Tp = 14, B = 34;
  const pts = series.flatMap(sr => sr.points.map(p => ({...p, sr})));
  if (!pts.length) return "";
  const x0 = Math.min(...pts.map(p => tsOf(p.valid_from))), x1 = Math.max(...pts.map(p => tsOf(p.valid_to) + 864e5));
  const amts = pts.map(p => p.amount), ticks = niceTicks(Math.min(...amts) * 0.9, Math.max(...amts) * 1.05);
  const y0 = ticks[0], y1 = ticks.at(-1);
  const X = t => L + (t - x0) / (x1 - x0 || 1) * (W - L - R), Y = v => Tp + (1 - (v - y0) / (y1 - y0 || 1)) * (H - Tp - B);
  const months = []; const d = new Date(x0); d.setDate(1);
  while (d.getTime() <= x1) { if (d.getTime() >= x0) months.push(d.getTime()); d.setMonth(d.getMonth() + (x1 - x0 > 400 * 864e5 ? 3 : 1)); }
  const today = Date.now();
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Rate by date">
    ${ticks.map(v => `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)"/><text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end">${num(v)}</text>`).join("")}
    ${months.map(t => `<text x="${X(t)}" y="${H - 12}" text-anchor="middle">${shortDate(t)}</text>`).join("")}
    ${today > x0 && today < x1 ? `<line x1="${X(today)}" x2="${X(today)}" y1="${Tp}" y2="${H - B}" stroke="var(--orange)" stroke-dasharray="3 3"/><text x="${X(today) + 4}" y="${Tp + 10}" fill="var(--orange)">today</text>` : ""}
    ${series.map((sr, si) => sr.points.map(p => {
      const c = p.state === "replaced" ? "var(--ink-muted)" : PALETTE[si % PALETTE.length];
      const xa = X(tsOf(p.valid_from)), xb = X(tsOf(p.valid_to) + 864e5), y = Y(p.amount);
      return `<g><title>${esc(sr.label)}: ${num(p.amount)} ${esc(p.currency)} · ${fmtDate(p.valid_from)} – ${fmtDate(p.valid_to)} · ${p.state}${p.change_pct ? ` · ${p.change_pct > 0 ? "+" : ""}${p.change_pct}%` : ""}${p.document ? ` · from ${esc(p.document.filename)}` : ""}</title>
        <line x1="${xa}" x2="${Math.max(xb, xa + 3)}" y1="${y}" y2="${y}" stroke="${c}" stroke-width="${p.state === "replaced" ? 2 : 5}" stroke-linecap="round" ${p.state === "replaced" ? `stroke-dasharray="4 4"` : ""} opacity="${p.state === "expired" ? .45 : 1}"/></g>`;
    }).join("")).join("")}
  </svg>`;
}

async function hotelHistoryCard(hotelId) {
  const box = $("#hh"); if (!box) return;
  const h = await api(`/api/catalog/hotels/${hotelId}/history`);
  if (!h.series.length) { box.innerHTML = ""; return; }
  const key = sr => `${sr.room_type}|${sr.meal_plan}`;
  const combos = [...new Map(h.series.map(sr => [key(sr), sr])).values()];
  const occs = [...new Set(h.series.map(sr => sr.occupancy))];
  const first = combos.find(sr => sr.points.some(p => p.state === "replaced")) || combos[0];
  box.innerHTML = `<div class="card"><h2>Rate history <span class="row"><select id="hh-c">${combos.map(sr => `<option value="${esc(key(sr))}" ${sr === first ? "selected" : ""}>${esc(sr.room_type)} · ${sr.meal_plan}</option>`).join("")}</select>
      <select id="hh-o"><option value="">all occupancies</option>${occs.map(o => `<option ${o === "double" ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></span></h2>
    <div id="hh-chart"></div><div class="legendrow" id="hh-leg"></div>
    <div class="small muted" style="margin-top:6px">Each bar is one rate over its dates. Grey dashed = replaced by a newer sheet. Hover a bar for its source file.</div>
    ${h.changes.length ? `<h3>Price changes · ${h.changes.length}</h3><div class="scroll"><table><thead><tr><th>Room</th><th>Meal</th><th>Occupancy</th><th class="num">Before</th><th class="num">Now</th><th class="num">Change</th><th>For dates</th><th>From sheet</th></tr></thead><tbody>
      ${h.changes.map(c => `<tr><td>${esc(c.room_type)}</td><td>${c.meal_plan}</td><td>${esc(words(c.occupancy))}${c.weekdays ? ` <span class="muted">${esc(c.weekdays)}</span>` : ""}</td><td class="num">${num(c.old)}</td><td class="num"><b>${num(c.new)}</b></td>
        <td class="num">${pctTxt(c.pct)}</td><td class="small">${fmtDate(c.valid_from)} – ${fmtDate(c.valid_to)}</td><td class="small">${c.document ? `<button class="link" data-doc="${c.document.id}">${esc(c.document.filename)}</button><div class="muted">${fmtDate(c.document.approved_at)}</div>` : ""}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="small muted" style="margin-top:8px">No price changes yet — they appear when this hotel's next sheet is uploaded.</div>`}</div>`;
  const draw = () => {
    const [room, meal] = $("#hh-c").value.split("|"), occ = $("#hh-o").value;
    const list = h.series.filter(sr => sr.room_type === room && sr.meal_plan === meal && (!occ || sr.occupancy === occ))
      .map(sr => ({...sr, label: `${sr.room_type} ${sr.meal_plan} ${words(sr.occupancy)}${sr.weekdays ? " " + sr.weekdays : ""}`}));
    $("#hh-chart").innerHTML = rateTimelineSVG(list) || `<div class="small muted">No rates for that choice.</div>`;
    $("#hh-leg").innerHTML = list.map((sr, i) => `<span style="--c:${PALETTE[i % PALETTE.length]}">${esc(sr.label)}</span>`).join("");
  };
  $("#hh-c").onchange = $("#hh-o").onchange = draw; draw();
  $$("[data-doc]", box).forEach(b => b.onclick = () => go("docs", b.dataset.doc));
}

// package prices per category across versions (the price at the common group size, usually 2 people)
function versionTrendSVG(trend) {
  const pts = trend.flatMap(t => t.points);
  const vs = [...new Set(pts.map(p => p.version))].sort((a, b) => a - b);
  if (vs.length < 2) return "";
  const W = 760, H = 230, L = 64, R = 90, Tp = 14, B = 30;
  const ticks = niceTicks(Math.min(...pts.map(p => p.amount)) * 0.92, Math.max(...pts.map(p => p.amount)) * 1.04), y0 = ticks[0], y1 = ticks.at(-1);
  const X = v => L + vs.indexOf(v) / (vs.length - 1) * (W - L - R), Y = a => Tp + (1 - (a - y0) / (y1 - y0 || 1)) * (H - Tp - B);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Package price by version">
    ${ticks.map(v => `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)"/><text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end">${num(v)}</text>`).join("")}
    ${vs.map(v => `<text x="${X(v)}" y="${H - 10}" text-anchor="middle">v${v}</text>`).join("")}
    ${trend.map((t, i) => { const c = PALETTE[i % PALETTE.length], ps = t.points.sort((a, b) => a.version - b.version);
      return `<polyline fill="none" stroke="${c}" stroke-width="2.5" points="${ps.map(p => `${X(p.version)},${Y(p.amount)}`).join(" ")}"/>
        ${ps.map(p => `<circle cx="${X(p.version)}" cy="${Y(p.amount)}" r="4" fill="${c}"><title>${esc(t.category)} v${p.version}: ${num(p.amount)} per person (${p.pax} pax)</title></circle>`).join("")}
        <text x="${X(ps.at(-1).version) + 8}" y="${Y(ps.at(-1).amount) + 4}" fill="${c}">${esc(t.category)}</text>`; }).join("")}
  </svg>`;
}

async function packageVersionsCard(id) {
  const box = $("#pv"); if (!box) return;
  const h = await api(`/api/catalog/packages/${id}/versions`);
  if (h.versions.length < 2) { box.innerHTML = ""; return; }
  box.innerHTML = `<div class="card"><h2>Versions · ${h.versions.length}</h2>
    <div class="scroll"><table><thead><tr><th>Version</th><th>Title</th><th>Valid</th><th>State</th><th class="num">From (pp)</th><th>Sheet</th></tr></thead><tbody>
    ${h.versions.map(v => `<tr class="${v.is_this ? "sel" : "click"}" data-pk="${v.id}"><td><b>v${v.version}</b>${v.is_this ? ` <span class="small muted">this one</span>` : ""}</td><td>${esc(v.title)}${v.edition ? `<div class="small muted">${esc(v.edition)}</div>` : ""}</td>
      <td class="small">${fmtDate(v.valid_from)} – ${fmtDate(v.valid_to)}</td><td>${statePill(v.state)}</td><td class="num">${money(v.from_price, v.currency)}</td>
      <td class="small">${v.document ? esc(v.document.filename) + `<div class="muted">${fmtDate(v.document.approved_at)}</div>` : ""}</td></tr>`).join("")}</tbody></table></div>
    ${h.trend.length ? `<h3>Price per person across versions</h3>${versionTrendSVG(h.trend)}` : ""}
    ${h.comparison ? `<h3>Compared with v${h.compared_with.version}: ${h.comparison.counts.up} up · ${h.comparison.counts.down} down · ${h.comparison.counts.same} unchanged${h.comparison.avg_change_pct ? ` · average ${h.comparison.avg_change_pct > 0 ? "+" : ""}${h.comparison.avg_change_pct}%` : ""}</h3>${priceDiffGrid(h.comparison.cells)}` : ""}</div>`;
  $$("#pv tr.click[data-pk]").forEach(tr => tr.onclick = () => go("catalog", "p" + tr.dataset.pk));
}

// ---------------------------------------------------------------- catalog tab: price changes
let chDays = 90;
async function catChanges() {
  const body = $("#cat-body");
  const f = await api(`/api/changes?days=${chDays}`);
  const lbl = {up: "up", down: "down", new_season: "new season"};
  body.innerHTML = `<div class="row between center"><span class="small muted">Price moves in the supplier sheets approved in the last
      <select id="chd">${[30, 90, 180, 365].map(d => `<option ${d === chDays ? "selected" : ""} value="${d}">${d} days</option>`).join("")}</select></span></div>
    <div class="kpis" style="margin-top:12px"><div class="kpi"><small>Sheets approved</small><b>${f.documents}</b></div>
      <div class="kpi"><small>Prices up</small><b class="accent">${f.up}</b><span>${f.avg_up_pct ? `average +${f.avg_up_pct}%` : ""}</span></div>
      <div class="kpi"><small>Prices down</small><b>${f.down}</b><span>${f.avg_down_pct ? `average ${f.avg_down_pct}%` : ""}</span></div>
      <div class="kpi"><small>Already in library</small><b>${f.totals.same || 0}</b><span>skipped, not duplicated</span></div></div>
    ${f.packages.length ? `<h3>Package updates</h3><table><tbody>${f.packages.map(p => `<tr class="click" data-pk="${p.package_id}"><td><b>${esc(p.title)}</b> <span class="pill">v${p.version}</span></td>
      <td class="small">${p.counts ? `${p.counts.up} up · ${p.counts.down} down · ${p.counts.same} same` : ""}</td><td class="num">${pctTxt(p.avg_change_pct)}</td><td class="small muted">${esc(p.document.filename)} · ${fmtDate(p.document.approved_at)}</td></tr>`).join("")}</tbody></table>` : ""}
    ${f.items.length ? `<h3>Rates</h3><div class="scroll"><table><thead><tr><th>What</th><th>Change</th><th class="num">Before</th><th class="num">Now</th><th class="num">%</th><th>Dates</th><th>Sheet</th></tr></thead><tbody>
      ${f.items.map(i => `<tr><td>${esc(i.name)}<div class="small muted">${esc(i.what)}</div></td><td>${lbl[i.change] || i.change}</td><td class="num">${num(i.old)}</td><td class="num"><b>${num(i.new)}</b> ${esc(i.currency || "")}</td>
        <td class="num">${pctTxt(i.pct)}</td><td class="small">${esc(i.valid || "")}</td><td class="small"><button class="link" data-doc="${i.document.id}">${esc(i.document.filename)}</button></td></tr>`).join("")}</tbody></table></div>`
      : empty("No price changes in this period. When a supplier sends a new sheet, what went up or down shows here.")}`;
  $("#chd").onchange = e => { chDays = +e.target.value; catChanges(); };
  $$("[data-pk]", body).forEach(tr => tr.onclick = () => go("catalog", "p" + tr.dataset.pk));
  $$("[data-doc]", body).forEach(b => b.onclick = () => go("docs", b.dataset.doc));
}

// ---------------------------------------------------------------- supplier page
async function showSupplier(main, id) {
  const sp = await api(`/api/catalog/suppliers/${id}`);
  const F = [["name", "Name"], ["type", "Type"], ["contact_person", "Contact person"], ["phone", "Phone"], ["email", "Email"], ["city", "City"], ["country", "Country"],
    ["gst_number", "GSTIN"], ["website", "Website"]];
  main.innerHTML = `<div class="pagehead"><div><div class="small muted"><button class="link" data-go="catalog">Catalog</button> / supplier</div><h1>${esc(sp.name)}</h1>
      <p>${esc([sp.type, sp.city, sp.rates_valid_until && "rates valid until " + fmtDate(sp.rates_valid_until)].filter(Boolean).join(" · "))}</p></div>
    <div class="row">${sp.phone ? `<a class="btn" href="tel:${esc(sp.phone.split(",")[0])}">${icon("phone")} Call</a><a class="btn" target="_blank" href="https://wa.me/${esc(sp.phone.split(",")[0].replace(/\D/g, ""))}">${icon("chat")} WhatsApp</a>` : ""}
      ${sp.email ? `<a class="btn" href="mailto:${esc(sp.email.split(",")[0])}?subject=${encodeURIComponent("Updated rates")}">Ask for new rates</a>` : ""}</div></div>
  ${sp.possible_duplicates.length ? `<div class="banner"><span>Looks like the same company as ${sp.possible_duplicates.map(d => `<b>${esc(d.name)}</b> <span class="small">(${d.why.join(", ")})</span>`).join(", ")}.</span>
      <span class="row">${sp.possible_duplicates.map(d => `<button class="btn sm" data-merge="${d.id}" data-name="${esc(d.name)}">Merge ${esc(d.name)} into this</button>`).join("")}</span></div>` : ""}
  <div class="grid g-main"><div>
    ${sp.packages.length ? `<div class="card"><h2>Packages · ${sp.packages.length}</h2>${sp.packages.map(p => `<div style="padding:5px 0"><button class="link" data-go="catalog/p${p.id}">${esc(p.title)}</button> <span class="small muted">v${p.version} · ${fmtDate(p.valid_from)} – ${fmtDate(p.valid_to)}</span></div>`).join("")}</div>` : ""}
    ${sp.hotels.length ? `<div class="card"><h2>Hotels with rates · ${sp.hotels.length}</h2>${sp.hotels.map(h => `<div style="padding:4px 0"><button class="link" data-go="catalog/h${h.id}">${esc(h.name)}</button> <span class="small muted">${esc(h.city || "")}</span></div>`).join("")}</div>` : ""}
    ${sp.services.length ? `<div class="card"><h2>Activities, transfers &amp; add-ons · ${sp.services.length}</h2>${servicesTable(sp.services)}</div>` : ""}
    <div class="card"><h2>Sheets received · ${sp.documents.length}</h2><table><tbody>${sp.documents.map(d => `<tr class="click" data-doc="${d.id}"><td>${esc(d.filename)}</td><td><span class="pill ${d.status}">${esc(words(d.status))}</span></td><td class="small">${fmtDate(d.created_at)}</td></tr>`).join("") || `<tr><td class="muted">None</td></tr>`}</tbody></table>
      ${sp.price_updates.length ? `<h3>What each sheet changed</h3><table><tbody>${sp.price_updates.map(u => `<tr><td class="small">${esc(u.filename)}<div class="muted">${fmtDate(u.at)}</div></td><td class="small">${u.new} new · ${u.up} up · ${u.down} down · ${u.same} same</td><td class="num">${pctTxt(u.avg_change_pct)}</td></tr>`).join("")}</tbody></table>` : ""}</div>
  </div><div class="rail"><div class="card"><h2>Details</h2>
    ${F.map(([k, l]) => `<label class="w100">${l}<input class="w100" data-sf="${k}" value="${esc(sp[k] || "")}"></label>`).join("")}
    <label class="w100">Address<textarea data-sf="address" style="min-height:60px">${esc(sp.address || "")}</textarea></label>
    <button class="btn primary sm" id="sp-save">Save</button>
    <h3>Merge a duplicate</h3><div class="row"><select id="sp-other" class="grow"><option value="">Pick a supplier…</option></select><button class="btn sm" id="sp-merge">Merge into this</button></div>
    <div class="small muted" style="margin-top:6px">Everything of the other supplier (sheets, rates, packages) moves here; empty details are filled in from it.</div></div></div></div>`;
  wireGo(main);
  $$("[data-doc]", main).forEach(tr => tr.onclick = () => go("docs", tr.dataset.doc));
  $("#sp-save").onclick = async () => { const body = {}; $$("[data-sf]", main).forEach(i => body[i.dataset.sf] = i.value);
    try { await patch(`/api/catalog/suppliers/${id}`, body); toast("Saved"); showSupplier(main, id); } catch (e) { toast(e.message, true); } };
  const merge = async (other, name) => {
    if (!confirm(`Merge "${name}" into "${sp.name}"? "${name}" disappears; its sheets, rates and packages move here.`)) return;
    try { const r = await post(`/api/catalog/suppliers/${id}/merge`, {merge_id: +other}); toast(`Merged: ${Object.values(r.moved).reduce((a, b) => a + b, 0)} records moved`); showSupplier(main, id); } catch (e) { toast(e.message, true); }
  };
  $$("[data-merge]", main).forEach(b => b.onclick = () => merge(b.dataset.merge, b.dataset.name));
  const all = await api("/api/catalog/suppliers");
  $("#sp-other").innerHTML += all.filter(x => x.id !== id).map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join("");
  $("#sp-merge").onclick = () => { const o = $("#sp-other"); if (o.value) merge(o.value, o.selectedOptions[0].textContent); };
}
