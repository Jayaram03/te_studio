// Document review: check what was read, see what saving will change, edit anything, then save or cancel.
// Loaded before app.js; uses its helpers ($, esc, api, ...) only inside functions, at run time.
"use strict";

let RV = null;                 // {doc, tab, ed (working copy of the extraction), dirty, links, showSame}
const RV_TABS = [["summary", "Review"], ["edit", "Edit data"], ["changes", "What changes"]];

async function openDoc(id, quiet, tab) {
  selectedDoc = id;
  const d = await api(`/api/documents/${id}`);
  const keepTab = RV && RV.doc.id === id ? RV.tab : null;
  RV = {doc: d, tab: tab || keepTab || "summary", ed: structuredClone(d.extraction || {}), dirty: false,
        links: RV && RV.doc.id === id ? RV.links : {}, showSame: false};
  drawReview();
  if (!quiet) $("#detail")?.scrollIntoView({behavior: "smooth"});
}

function drawReview() {
  const el = $("#detail"); if (!el || !RV) return;
  const d = RV.doc;
  el.classList.remove("hidden");
  const canAct = d.status === "needs_review";
  const manual = d.media_type === "application/x-manual" || (d.filename || "").startsWith("Manual entry");
  const head = `<div class="row between center" style="margin-bottom:6px"><h2 style="margin:0">#${d.id} ${esc(d.filename)} <span class="pill ${d.status}">${esc(words(d.status))}</span></h2>
    <button class="icon" id="rv-close" title="Close">✕</button></div>
    <p class="small muted" style="margin-top:0">${esc(d.supplier || "Supplier not detected")} · ${esc(words(d.document_type))} · read by ${esc(d.model || "—")}
      ${d.approved_at ? ` · saved ${fmtDate(d.approved_at)}${d.approved_by ? " by " + esc(d.approved_by) : ""}` : ""}
      ${manual ? "" : ` · <button class="link" id="d-file">open original</button>`}</p>`;
  if (d.status === "processing") { el.innerHTML = head + `<p>Reading the document… this page refreshes by itself.</p>`; wireReviewHead(); return; }
  if (d.status === "failed" || !d.extraction) {
    el.innerHTML = head + `<div class="issue error">${esc(d.error || "Nothing was read")}</div>
      <div class="row" style="margin-top:10px">${manual ? "" : `<button class="btn primary" id="d-re">Try again</button>`}<button class="btn" id="d-discard">Remove this upload</button></div>`;
    wireReviewHead(); return;
  }
  const tabs = `<div class="subnav" id="rv-tabs">${RV_TABS.map(([k, l]) => `<button data-t="${k}" class="${k === RV.tab ? "on" : ""}">${l}${k === "edit" && RV.dirty ? " •" : ""}</button>`).join("")}</div>`;
  const bar = canAct ? `<div class="actionbar">
      <button class="btn primary" id="d-approve" ${RV.dirty ? "disabled title='Save your edits first'" : ""}>Save to library</button>
      ${RV.tab === "edit" ? `<button class="btn primary" id="ed-save">Save edits &amp; check again</button><button class="btn" id="ed-reset" ${RV.dirty ? "" : "disabled"}>Undo my edits</button>`
                          : `<button class="btn" data-go-tab="edit">Edit data</button><button class="btn" id="d-check">Check again</button>`}
      <span class="grow"></span>
      ${manual ? "" : `<button class="btn" id="d-re" title="Send the file to the AI again">Read again</button>`}
      <button class="btn" id="d-reject" title="Keep the record, don't use it">Reject</button>
      <button class="btn" id="d-discard" title="Delete this upload and everything read from it">Cancel upload</button></div>`
    : d.status === "approved" ? `<div class="actionbar"><span class="small muted">In the library.</span><span class="grow"></span>
      <button class="btn" id="d-undo" title="Remove what this document added and bring back the earlier rates">Take out of library</button></div>`
    : `<div class="actionbar"><span class="small muted">Rejected — not used.</span><span class="grow"></span><button class="btn" id="d-discard">Delete</button></div>`;
  let body = "";
  if (RV.tab === "summary") body = reviewSummary(d, canAct);
  else if (RV.tab === "changes") body = changesHtml(d.changes, canAct);
  else body = canAct ? editorHtml() : `<div class="issue ok">This document is ${esc(words(d.status))}. Its data can't be edited here — correct rates in the Catalog, or take it out of the library first.</div>`;
  el.innerHTML = head + tabs + `<div id="rv-body">${body}</div>` + bar;
  wireReviewHead();
  wireReview();
}

// ---------------------------------------------------------------- summary tab
function changeCounts(ch) {
  if (!ch || !ch.summary) return "";
  const s = ch.summary;
  const avg = kind => { const xs = ch.items.filter(i => i.change === kind && i.pct != null).map(i => i.pct);
    return xs.length ? ` (avg ${kind === "up" ? "+" : ""}${(xs.reduce((a, b) => a + b, 0) / xs.length).toFixed(1)}%)` : ""; };
  const pills = [[s.new, "new", "ok"], [s.up, "price up" + avg("up"), "bad"], [s.down, "price down" + avg("down"), "ok"], [s.new_season, "new season (compared with last)", ""], [s.extended, "same price, new dates", ""],
    [s.same, "already in the library (skipped)", ""], [s.replaced, "older rates replaced or trimmed", "warn"]]
    .filter(p => p[0]).map(([n, l, c]) => `<span class="pill ${c}">${n} ${l}</span>`);
  return pills.join(" ") || `<span class="pill">nothing to change</span>`;
}

function reviewSummary(d, canAct) {
  const st = (d.normalized || {}).stats || {};
  const found = [["hotel_rates", "hotel rates"], ["package_prices", "package prices"], ["package_hotels", "package hotels"],
    ["services", "activities & transfers"], ["places", "places"], ["surcharges", "supplements / blackouts"]].filter(([k]) => st[k]);
  const ch = d.changes;
  const nothingNew = ch && ch.summary && !ch.summary.new && !ch.summary.up && !ch.summary.down && !ch.summary.new_season && !ch.summary.extended
    && !(ch.packages || []).some(p => !p.matched || (p.prices && (p.prices.counts.up || p.prices.counts.down || p.prices.counts.new)));
  return `
    <div class="kpis" style="margin-bottom:10px">${found.map(([k, l]) => `<div class="kpi"><small>${l}</small><b>${st[k]}</b></div>`).join("") || `<div class="kpi"><small>Found</small><b>0</b><span>add data in Edit data</span></div>`}</div>
    ${ch && !ch.error ? `<h3>What saving will change</h3><div>${changeCounts(ch)}</div>
      ${nothingNew ? `<div class="issue ok" style="margin-top:8px">Everything in this document is already in the library with the same prices — saving changes nothing.</div>` : ""}
      ${packageMatchHtml(ch, canAct)}
      <p class="small"><button class="link" data-go-tab="changes">See every change</button></p>` : ch && ch.error ? `<div class="issue warning">Couldn't work out the changes: ${esc(ch.error)}</div>` : ""}
    <h3>Checks</h3><div id="d-issues">${issuesHtml(d.issues || [])}</div>
    ${canAct ? `<h3>Fill in what the document doesn't say</h3>
      <div class="row"><label>Valid from<input type="date" id="o-valid_from"></label><label>Valid to<input type="date" id="o-valid_to"></label>
        <label>Currency<input id="o-currency" placeholder="INR" style="width:80px"></label>
        <label>Rates are<select id="o-rate_type"><option value="">as detected</option><option value="net">Net / B2B</option><option value="rack">Rack / public</option></select></label>
        <label>Taxes<select id="o-taxes"><option value="">as detected</option><option value="excluded">Extra</option><option value="included">Included</option></select></label>
        <label>Approved by<select id="o-approved_by"><option value="">—</option>${(SETTINGS?.team || []).map(m => `<option>${esc(m.name)}</option>`).join("")}</select></label></div>` : ""}
    <h3>Everything that was read</h3><div class="small muted" style="margin-bottom:6px">Check it against the original. Anything wrong? Open <button class="link" data-go-tab="edit">Edit data</button>.</div>
    <div id="d-preview">${previewHtml(d.normalized)}</div>
    ${d.normalized?.general_terms?.length ? `<h3>Terms</h3><ul>${d.normalized.general_terms.map(t => `<li class="small">${esc(t)}</li>`).join("")}</ul>` : ""}`;
}

function packageMatchHtml(ch, canAct) {
  if (!ch.packages?.length) return "";
  return ch.packages.map(p => {
    const pr = p.prices, c = pr?.counts;
    const older = (p.older_versions || []).map(o => `v${o.version} ${esc(o.action)}`).join(", ");
    const opts = [`<option value="auto" ${!RV.links[p.index] ? "selected" : ""}>${p.matched ? `New version of “${esc(p.family_title)}” (found automatically)` : "A new package (no earlier version found)"}</option>`,
      ...(p.candidates || []).filter(x => !p.matched || x.family_id !== p.family_id).map(x => `<option value="${x.family_id}" ${RV.links[p.index] == x.family_id ? "selected" : ""}>New version of “${esc(x.title)}” (v${x.version}, ${x.score}% alike)</option>`),
      `<option value="new" ${RV.links[p.index] === "new" ? "selected" : ""}>A separate new package</option>`];
    return `<div class="versionbox"><div><b>${esc(p.title)}</b> → ${p.matched ? `<span class="pill ok">version ${p.version}</span>` : `<span class="pill">new package</span>`}
        ${older ? `<span class="small muted"> · ${older}</span>` : ""}</div>
      ${c ? `<div class="small" style="margin-top:4px">Compared with v${p.compared_with.version}: ${c.up ? `<b class="up">${c.up} up</b> · ` : ""}${c.down ? `<b class="downc">${c.down} down</b> · ` : ""}${c.same} unchanged${c.new ? ` · ${c.new} new` : ""}${c.removed ? ` · ${c.removed} no longer offered` : ""}${pr.avg_change_pct ? ` · average ${pr.avg_change_pct > 0 ? "+" : ""}${pr.avg_change_pct}%` : ""}</div>` : ""}
      ${canAct ? `<label style="margin:8px 0 0">This package is<select data-link="${p.index}" style="max-width:520px">${opts.join("")}</select></label>` : ""}</div>`;
  }).join("");
}

// ---------------------------------------------------------------- changes tab
function changesHtml(ch, canAct) {
  if (!ch || ch.error) return `<div class="muted">${ch?.error ? esc(ch.error) : canAct ? "Fix the errors first, then the changes are worked out." : "No change record for this document."}</div>`;
  const items = ch.items.filter(i => RV.showSame || i.change !== "same");
  const lbl = {up: "price up", down: "price down", new: "new", same: "unchanged", extended: "same price, new dates", new_season: "new season"};
  const cls = {up: "bad", down: "ok", new: "ok", new_season: "", extended: "", same: ""};
  const arrow = i => i.pct == null ? "" : `<span class="${i.pct > 0 ? "up" : i.pct < 0 ? "downc" : ""}">${i.pct > 0 ? "▲ +" : i.pct < 0 ? "▼ " : ""}${i.pct}%</span>`;
  return `<div>${changeCounts(ch)}</div>
    <div class="row between center" style="margin:12px 0 6px"><span class="small muted">${ch.applied ? "What saving changed." : "Nothing is saved yet — this is what saving will do."}</span>
      <label class="check" style="margin:0"><input type="checkbox" id="ch-same" ${RV.showSame ? "checked" : ""}>show unchanged</label></div>
    ${(ch.packages || []).map(p => p.prices ? `<h3>${esc(p.title)} — v${p.version} vs v${p.compared_with.version}</h3>${priceDiffGrid(p.prices.cells)}` : "").join("")}
    ${items.length ? `<h3>Rates, supplements and add-ons</h3><div class="scroll" style="max-height:520px;overflow:auto"><table><thead><tr><th>What</th><th>Change</th><th class="num">Before</th><th class="num">Now</th><th class="num">%</th><th>Dates</th><th>Compared with</th></tr></thead><tbody>
      ${items.map(i => `<tr><td>${esc(i.name)}<div class="small muted">${esc(i.what)}</div></td><td><span class="pill ${cls[i.change]}">${lbl[i.change] || i.change}</span></td>
        <td class="num">${i.old == null ? "" : num(i.old)}</td><td class="num"><b>${num(i.new)}</b> ${esc(i.currency || "")}</td><td class="num">${arrow(i)}</td>
        <td class="small">${esc(i.valid || "")}</td><td class="small muted">${esc(i.vs ? i.vs + ": " : "")}${esc(i.old_valid || "")}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="small muted">No rate changes${RV.showSame ? "" : " (unchanged rates are hidden)"}.</div>`}`;
}

function priceDiffGrid(cells) {
  const cats = [...new Set(cells.map(c => c.category || "-"))], rows = {};
  cells.forEach(c => (rows[c.label] ??= {})[c.category || "-"] = c);
  const cell = c => !c ? "" : c.change === "same" ? `<span class="muted">${num(c.new)}</span>` : c.change === "new" ? `<b>${num(c.new)}</b> <span class="pill ok">new</span>`
    : `<span class="muted small" style="text-decoration:line-through">${num(c.old)}</span> <b>${num(c.new)}</b> <span class="${c.pct > 0 ? "up" : "downc"} small">${c.pct > 0 ? "+" : ""}${c.pct}%</span>`;
  return `<div class="scroll"><table><thead><tr><th>Per person</th>${cats.map(c => `<th class="num">${esc(c)}</th>`).join("")}</tr></thead><tbody>
    ${Object.entries(rows).map(([k, v]) => `<tr><td>${esc(k)}</td>${cats.map(c => `<td class="num">${cell(v[c])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

// ---------------------------------------------------------------- editor
const OCC = ["single", "double", "triple", "extra adult", "child with bed", "child without bed", "per person"];
const MEALS = ["EP", "CP", "MAP", "AP", "AI"];
const RATE_T = ["unknown", "net", "rack"];
const COLS = {
  rates: [{k: "room_type", l: "Room", w: 150}, {k: "meal_plan", l: "Meal", t: "list", o: MEALS, w: 70}, {k: "occupancy", l: "Occupancy", t: "list", o: OCC, w: 120},
    {k: "amount", l: "Amount", t: "num", w: 90}, {k: "season_key", l: "Season", w: 90}, {k: "valid_from", l: "From", w: 105}, {k: "valid_to", l: "To", w: 105},
    {k: "days", l: "Days", w: 80}, {k: "rate_type", l: "Net/rack", t: "sel", o: RATE_T, w: 90}, {k: "currency", l: "Cur.", w: 55}, {k: "notes", l: "Notes", w: 140}],
  supplements: [{k: "name", l: "Supplement", w: 180}, {k: "date_from", l: "From", w: 105}, {k: "date_to", l: "To", w: 105}, {k: "amount", l: "Amount", t: "num", w: 90},
    {k: "basis", l: "Basis", t: "sel", o: ["unknown", "per_person", "per_adult", "per_child", "per_room", "per_room_per_night", "per_booking"], w: 130}, {k: "mandatory", l: "Compulsory", t: "bool"}],
  blackout_dates: [{k: "start", l: "From", w: 110}, {k: "end", l: "To", w: 110}, {k: "room_type", l: "Only this room (blank = all)", w: 200}],
  prices: [{k: "category", l: "Category", w: 110}, {k: "pax_min", l: "Pax", t: "num", w: 60}, {k: "pax_max", l: "Pax max", t: "num", w: 60},
    {k: "occupancy", l: "Occupancy", t: "list", o: ["per person twin sharing", "single supplement", "extra bed", "child with bed", "child without bed"], w: 170},
    {k: "amount", l: "Amount", t: "num", w: 90}, {k: "season_key", l: "Season", w: 80}, {k: "valid_from", l: "From", w: 105}, {k: "valid_to", l: "To", w: 105}, {k: "rate_type", l: "Net/rack", t: "sel", o: RATE_T, w: 90}],
  hotels: [{k: "city", l: "City", w: 110}, {k: "hotel_name", l: "Hotel", w: 190}, {k: "category", l: "Category", w: 100}, {k: "nights", l: "Nights", t: "num", w: 60},
    {k: "meal_plan", l: "Meal", t: "list", o: MEALS, w: 70}, {k: "property_type", l: "Type", t: "sel", o: ["", "hotel", "resort", "houseboat", "homestay", "camp", "villa", "other"], w: 100}],
  itinerary: [{k: "day", l: "Day", t: "num", w: 50}, {k: "title", l: "Title", w: 200}, {k: "overnight", l: "Overnight", w: 110}, {k: "meals", l: "Meals", w: 70}, {k: "description", l: "Description", t: "area", w: 360}],
  services: [{k: "kind", l: "Kind", t: "sel", o: ["transfer", "sightseeing", "activity", "entry_ticket", "guide", "vehicle_hire", "rental", "meal", "other"], w: 110},
    {k: "name", l: "Service", w: 200}, {k: "destination", l: "Where", w: 100}, {k: "vehicle_type", l: "Vehicle", w: 110},
    {k: "basis", l: "Basis", t: "sel", o: ["unknown", "per_vehicle", "per_person", "per_adult", "per_child", "per_group"], w: 110}, {k: "pax_max", l: "Seats", t: "num", w: 60},
    {k: "amount", l: "Price", t: "num", w: 85}, {k: "amount_max", l: "Up to", t: "num", w: 85}, {k: "optional", l: "Add-on", t: "bool"},
    {k: "valid_from", l: "From", w: 105}, {k: "valid_to", l: "To", w: 105}, {k: "notes", l: "Notes", w: 140}],
  places: [{k: "name", l: "Place", w: 160}, {k: "destination", l: "Region", w: 100}, {k: "region", l: "Near", w: 100},
    {k: "kind", l: "Kind", t: "sel", o: ["", "attraction", "offbeat", "viewpoint", "religious", "garden", "lake", "valley", "market", "other"], w: 100},
    {k: "description", l: "About", t: "area", w: 300}, {k: "availability", l: "Open", w: 110}],
  seasons: [{k: "key", l: "Key (used by rates)", w: 120}, {k: "name", l: "Name", w: 150}, {k: "periods", l: "Date ranges (from to to; …)", t: "periods", w: 360}],
};

function getPath(obj, path) { return path.split(".").reduce((o, k) => o?.[k], obj); }
function setPath(obj, path, v) {
  const ks = path.split("."), last = ks.pop();
  const tgt = ks.reduce((o, k) => (o[k] ??= /^\d+$/.test(k) ? [] : {}), obj);
  tgt[last] = v;
}

function cellInput(path, c, v) {
  const a = `data-p="${path}" data-t="${c.t || "text"}" style="width:${c.w || 110}px"`;
  if (c.t === "bool") return `<input type="checkbox" data-p="${path}" data-t="bool" ${v ? "checked" : ""}>`;
  if (c.t === "sel") return `<select ${a}>${c.o.map(o => `<option value="${esc(o)}" ${String(v ?? "") === o ? "selected" : ""}>${esc(words(o) || "—")}</option>`).join("")}</select>`;
  if (c.t === "area") return `<textarea ${a} rows="2" style="width:${c.w}px;min-height:38px">${esc(v ?? "")}</textarea>`;
  if (c.t === "periods") return `<input ${a} value="${esc((v || []).map(p => `${p.start} to ${p.end}`).join("; "))}">`;
  const list = c.t === "list" ? ` list="dl-${c.k}"` : "";
  return `<input ${a}${list} ${c.t === "num" ? `inputmode="decimal"` : ""} value="${esc(v ?? "")}">`;
}

function gridEditor(path, rows, cols, title, emptyRow = {}) {
  rows = rows || [];
  const dl = cols.filter(c => c.t === "list").map(c => `<datalist id="dl-${c.k}">${c.o.map(o => `<option value="${esc(o)}">`).join("")}</datalist>`).join("");
  return `<div class="edgrid"><div class="row between center"><h4>${esc(title)} <span class="muted small">${rows.length}</span></h4>
      <button class="btn sm" data-add="${path}" data-empty='${esc(JSON.stringify(emptyRow))}'>+ Add row</button></div>${dl}
    ${rows.length ? `<div class="scroll"><table class="ed"><thead><tr>${cols.map(c => `<th>${esc(c.l)}</th>`).join("")}<th></th></tr></thead><tbody>
      ${rows.map((r, i) => `<tr>${cols.map(c => `<td>${cellInput(`${path}.${i}.${c.k}`, c, r?.[c.k])}</td>`).join("")}
        <td style="white-space:nowrap"><button class="icon" data-dup="${path}.${i}" title="Copy this row">⎘</button><button class="icon" data-rm="${path}.${i}" title="Delete this row">✕</button></td></tr>`).join("")}</tbody></table></div>` : ""}</div>`;
}

function fields(path, obj, spec) {
  return `<div class="row">${spec.map(c => `<label>${esc(c.l)}${cellInput(`${path}${path ? "." : ""}${c.k}`, c, obj?.[c.k])}</label>`).join("")}</div>`;
}

function editorHtml() {
  const x = RV.ed;
  x.hotels ??= []; x.packages ??= []; x.services ??= []; x.places ??= []; x.seasons ??= []; x.supplier ??= {};
  const docSpec = [{k: "document_type", l: "Document type", t: "sel", o: ["hotel_rate_sheet", "dmc_rate_sheet", "package", "mixed", "unknown"], w: 150},
    {k: "currency", l: "Currency", w: 70}, {k: "rate_type", l: "Rates are", t: "sel", o: RATE_T, w: 100},
    {k: "taxes", l: "Taxes", t: "sel", o: ["unknown", "included", "excluded"], w: 100}, {k: "issued_on", l: "Issued on", w: 110}, {k: "is_revision", l: "Revised sheet", t: "bool"}];
  const supSpec = [{k: "name", l: "Supplier", w: 200}, {k: "type", l: "Type", t: "sel", o: ["", "hotel", "dmc", "transport", "activity", "other"], w: 100},
    {k: "city", l: "City", w: 110}, {k: "contact_person", l: "Contact", w: 140}, {k: "phone", l: "Phone", w: 150}, {k: "email", l: "Email", w: 190}, {k: "gst_number", l: "GSTIN", w: 150}];
  const hotelSpec = [{k: "name", l: "Hotel", w: 220}, {k: "city", l: "City", w: 110}, {k: "destination", l: "Region", w: 110}, {k: "category", l: "Category", w: 100},
    {k: "property_type", l: "Type", t: "sel", o: ["", "hotel", "resort", "houseboat", "homestay", "camp", "villa", "other"], w: 100}, {k: "star_rating", l: "Stars", t: "num", w: 60}];
  const pkgSpec = [{k: "title", l: "Package", w: 260}, {k: "base_name", l: "Name without season/year", w: 180}, {k: "edition", l: "Edition", w: 130},
    {k: "region", l: "Region", w: 100}, {k: "nights", l: "Nights", t: "num", w: 60}, {k: "days", l: "Days", t: "num", w: 60}, {k: "valid_from", l: "Valid from", w: 105}, {k: "valid_to", l: "Valid to", w: 105}];
  const lines = (path, v, l) => `<label class="w100">${l} <span class="muted">(one per line)</span><textarea data-p="${path}" data-t="lines" rows="3">${esc((v || []).join("\n"))}</textarea></label>`;
  return `<div class="small muted" style="margin-bottom:10px">Change anything below — cells, rows, whole hotels or packages. Dates as YYYY-MM-DD (or "Aug 2026").
      Nothing is saved to the library until you press <b>Save to library</b>. <b>Save edits &amp; check again</b> re-runs every check and the change preview.</div>
    <div class="edsec"><h3>Document</h3>${fields("", x, docSpec)}
      <div class="row"><label>Valid from${cellInput("validity.start", {w: 120}, x.validity?.start)}</label><label>Valid to${cellInput("validity.end", {w: 120}, x.validity?.end)}</label></div>
      ${fields("supplier", x.supplier, supSpec)}
      ${gridEditor("seasons", x.seasons, COLS.seasons, "Seasons", {key: "", name: "", periods: []})}</div>
    <div class="edsec"><div class="row between center"><h3>Hotels · ${x.hotels.length}</h3><button class="btn sm" data-add="hotels" data-empty='{"name":"New hotel","rates":[],"supplements":[],"blackout_dates":[]}'>+ Add hotel</button></div>
      ${x.hotels.map((h, i) => `<details class="edblock" ${i === 0 || x.hotels.length < 3 ? "open" : ""}><summary><b>${esc(h.name || "Hotel")}</b> <span class="muted small">${esc(h.city || "")} · ${(h.rates || []).length} rates</span></summary>
        <div class="row between">${fields(`hotels.${i}`, h, hotelSpec)}<button class="btn sm" data-rm="hotels.${i}">Delete hotel</button></div>
        ${gridEditor(`hotels.${i}.rates`, h.rates, COLS.rates, "Rates", {room_type: "", meal_plan: "CP", occupancy: "double", amount: null, rate_type: "unknown"})}
        ${gridEditor(`hotels.${i}.supplements`, h.supplements, COLS.supplements, "Supplements (gala dinners, surcharges)", {name: "", mandatory: true, basis: "unknown"})}
        ${gridEditor(`hotels.${i}.blackout_dates`, h.blackout_dates, COLS.blackout_dates, "Blackout / stop-sale dates", {start: "", end: ""})}
        <label class="w100">Child policy<textarea data-p="hotels.${i}.child_policy" data-t="text" rows="2">${esc(h.child_policy || "")}</textarea></label></details>`).join("")}</div>
    <div class="edsec"><div class="row between center"><h3>Packages · ${x.packages.length}</h3><button class="btn sm" data-add="packages" data-empty='{"title":"New package","itinerary":[],"hotels":[],"prices":[],"inclusions":[],"exclusions":[],"terms":[],"destinations":[]}'>+ Add package</button></div>
      ${x.packages.map((p, i) => `<details class="edblock" open><summary><b>${esc(p.title || "Package")}</b> <span class="muted small">${(p.prices || []).length} prices · ${(p.itinerary || []).length} days · ${(p.hotels || []).length} hotels</span></summary>
        <div class="row between">${fields(`packages.${i}`, p, pkgSpec)}<button class="btn sm" data-rm="packages.${i}">Delete package</button></div>
        <label class="w100">Places visited <span class="muted">(comma separated, in order)</span><input class="w100" data-p="packages.${i}.destinations" data-t="csv" value="${esc((p.destinations || []).join(", "))}"></label>
        ${gridEditor(`packages.${i}.prices`, p.prices, COLS.prices, "Prices", {category: "", occupancy: "per person twin sharing", amount: null, basis: "per_person", rate_type: "unknown"})}
        ${gridEditor(`packages.${i}.hotels`, p.hotels, COLS.hotels, "Hotels by city and category", {hotel_name: ""})}
        ${gridEditor(`packages.${i}.itinerary`, p.itinerary, COLS.itinerary, "Day by day", {day: (p.itinerary || []).length + 1})}
        <div class="grid g2">${lines(`packages.${i}.inclusions`, p.inclusions, "Included")}${lines(`packages.${i}.exclusions`, p.exclusions, "Not included")}</div>
        ${lines(`packages.${i}.terms`, p.terms, "Package terms")}</details>`).join("")}</div>
    <div class="edsec">${gridEditor("services", x.services, COLS.services, "Activities, transfers & add-ons", {kind: "transfer", name: "", basis: "unknown", optional: false, rate_type: "unknown"})}</div>
    <div class="edsec">${gridEditor("places", x.places, COLS.places, "Places", {name: ""})}</div>
    <div class="edsec">${lines("general_terms", x.general_terms, "Terms & policies")}
      ${(x.warnings || []).length ? `<h4>Notes from the AI</h4>${x.warnings.map(w => `<div class="issue warning">${esc(w)}</div>`).join("")}` : ""}</div>`;
}

function readInput(inp) {
  const t = inp.dataset.t, v = inp.type === "checkbox" ? inp.checked : inp.value;
  if (t === "bool") return !!v;
  if (t === "num") { const s = String(v).replace(/[, ₹]/g, "").trim(); if (!s) return null; const n = Number(s); return Number.isFinite(n) ? n : s; }
  if (t === "lines") return String(v).split("\n").map(x => x.trim()).filter(Boolean);
  if (t === "csv") return String(v).split(",").map(x => x.trim()).filter(Boolean);
  if (t === "periods") return String(v).split(";").map(x => x.trim()).filter(Boolean).map(x => {
    const [a, b] = x.split(/\s+(?:to|–|—|-)\s+/); return {start: (a || "").trim(), end: (b || a || "").trim()}; });
  const s = String(v).trim();
  return s === "" ? null : s;
}

// the extraction schema wants some fields filled; the editor lets people leave them blank and tidies up here
function cleanForSave(x) {
  const y = structuredClone(x);
  const fix = (arr, fn) => (arr || []).forEach(fn);
  fix(y.hotels, h => { fix(h.rates, r => { r.rate_type ||= "unknown"; r.basis ||= "per_room_per_night"; r.taxes ||= "unknown"; r.occupancy ||= "double"; r.room_type ||= "Room"; });
    fix(h.supplements, sp => { sp.basis ||= "unknown"; sp.name ||= "Supplement"; if (sp.mandatory == null) sp.mandatory = true; });
    h.name ||= "Hotel"; h.property_type ||= null; });
  fix(y.packages, p => { p.title ||= "Package"; fix(p.prices, q => { q.basis ||= "per_person"; q.rate_type ||= "unknown"; q.occupancy ||= "double"; });
    fix(p.hotels, hh => { hh.hotel_name ||= "Hotel"; hh.property_type ||= null; }); fix(p.itinerary, (d, i) => { if (d.day == null || d.day === "") d.day = i + 1; }); });
  fix(y.services, sv => { sv.kind ||= "other"; sv.basis ||= "unknown"; sv.rate_type ||= "unknown"; sv.name ||= "Service"; });
  fix(y.places, pl => { pl.name ||= "Place"; pl.kind ||= null; });
  fix(y.seasons, (se, i) => { se.key ||= "season" + (i + 1); });
  if (y.supplier) y.supplier.type ||= null;
  y.document_type ||= "mixed"; y.rate_type ||= "unknown"; y.taxes ||= "unknown";
  if (y.validity && !y.validity.start && !y.validity.end) y.validity = null;
  else if (y.validity) { y.validity.start ||= y.validity.end; y.validity.end ||= y.validity.start; }
  return y;
}

// ---------------------------------------------------------------- wiring
function wireReviewHead() {
  const d = RV.doc, id = d.id;
  $("#rv-close") && ($("#rv-close").onclick = () => { if (RV.dirty && !confirm("Close without saving your edits?")) return; $("#detail").classList.add("hidden"); RV = null; selectedDoc = null; refreshDocs(); });
  $("#d-file") && ($("#d-file").onclick = () => openInTab(`/api/documents/${id}/file`));
  $("#d-re") && ($("#d-re").onclick = async () => { if (RV.dirty && !confirm("Reading again replaces your edits. Continue?")) return; toast("Reading again…");
    try { await post(`/api/documents/${id}/reprocess`); } catch (e) { toast(e.message, true); } await refreshDocs(); openDoc(id, true, "summary"); });
  $("#d-discard") && ($("#d-discard").onclick = async () => { if (!confirm("Cancel this upload? The file and everything read from it are deleted. Nothing is saved to the library.")) return;
    try { await del(`/api/documents/${id}`); toast("Upload cancelled"); $("#detail").classList.add("hidden"); RV = null; selectedDoc = null; await refreshDocs(); refreshBadges(); } catch (e) { toast(e.message, true); } });
}

function overridesWithLinks() {
  const o = overrides();
  const links = Object.fromEntries(Object.entries(RV.links).filter(([, v]) => v && v !== "auto"));
  if (Object.keys(links).length) o.package_links = links;
  return o;
}

function wireReview() {
  const d = RV.doc, id = d.id;
  $$("#rv-tabs [data-t]").forEach(b => b.onclick = () => { RV.tab = b.dataset.t; drawReview(); });
  $$("[data-go-tab]").forEach(b => b.onclick = () => { RV.tab = b.dataset.goTab; drawReview(); });
  $("#ch-same") && ($("#ch-same").onchange = e => { RV.showSame = e.target.checked; drawReview(); });
  $$("[data-link]").forEach(s => s.onchange = async () => { RV.links[s.dataset.link] = s.value; await recheck(); });
  $("#d-check") && ($("#d-check").onclick = recheck);
  $("#d-approve") && ($("#d-approve").onclick = async e => {
    e.target.disabled = true;
    try {
      const r = await post(`/api/documents/${id}/approve`, overridesWithLinks()), L = r.loaded, c = L.changes || {};
      packagesCache = null; await refreshDocs(); refreshBadges();
      toast(`Saved to the library: ${c.new || 0} new, ${c.up || 0} up, ${c.down || 0} down, ${L.unchanged || 0} already there`);
      openDoc(id, true, "changes");
    } catch (err) { toast(err.message, true); e.target.disabled = false; }
  });
  $("#d-reject") && ($("#d-reject").onclick = async () => { if (!confirm("Reject this document? It stays in the list but nothing is used.")) return; await post(`/api/documents/${id}/reject`); await refreshDocs(); openDoc(id, true); refreshBadges(); });
  $("#d-undo") && ($("#d-undo").onclick = async () => {
    if (!confirm("Take this document out of the library? Everything it added is removed and the rates it replaced come back.")) return;
    try { const r = await post(`/api/documents/${id}/undo`); toast(`Taken out: ${Object.entries(r.removed).map(([k, v]) => `${v} ${k}`).join(", ") || "nothing"}; ${r.restored} earlier rates restored`);
      packagesCache = null; await refreshDocs(); openDoc(id, true, "summary"); refreshBadges(); } catch (e) { toast(e.message, true); }
  });
  // editor
  const body = $("#rv-body");
  if (RV.tab !== "edit" || !body) return;
  body.oninput = body.onchange = e => {
    const inp = e.target.closest("[data-p]"); if (!inp) return;
    setPath(RV.ed, inp.dataset.p, readInput(inp));
    if (!RV.dirty) { RV.dirty = true; $("#ed-reset") && ($("#ed-reset").disabled = false); $("#d-approve") && ($("#d-approve").disabled = true); $$("#rv-tabs [data-t=edit]").forEach(b => b.textContent = "Edit data •"); }
  };
  const redraw = () => { const y = window.scrollY; RV.dirty = true; drawReview(); window.scrollTo(0, y); };
  $$("[data-add]", body).forEach(b => b.onclick = () => { const arr = getPath(RV.ed, b.dataset.add) || []; arr.push(JSON.parse(b.dataset.empty || "{}")); setPath(RV.ed, b.dataset.add, arr); redraw(); });
  $$("[data-rm]", body).forEach(b => b.onclick = () => { const p = b.dataset.rm.split("."), i = +p.pop(), arr = getPath(RV.ed, p.join("."));
    if (/^(hotels|packages)$/.test(p.join(".")) && !confirm("Delete this whole " + (p[0] === "hotels" ? "hotel with its rates" : "package") + "?")) return; arr.splice(i, 1); redraw(); });
  $$("[data-dup]", body).forEach(b => b.onclick = () => { const p = b.dataset.dup.split("."), i = +p.pop(), arr = getPath(RV.ed, p.join(".")); arr.splice(i + 1, 0, structuredClone(arr[i])); redraw(); });
  $("#ed-reset") && ($("#ed-reset").onclick = () => { if (!confirm("Undo all your edits?")) return; RV.ed = structuredClone(RV.doc.extraction); RV.dirty = false; drawReview(); });
  $("#ed-save") && ($("#ed-save").onclick = async e => {
    e.target.disabled = true;
    try { const doc = await put(`/api/documents/${id}/extraction`, cleanForSave(RV.ed));
      RV.doc = doc; RV.ed = structuredClone(doc.extraction); RV.dirty = false; RV.tab = "summary"; drawReview(); await refreshDocs();
      const errs = (doc.issues || []).filter(i => i.level === "error").length;
      toast(errs ? `Saved — ${errs} error(s) still to fix` : "Edits saved and checked. Review, then Save to library.", !!errs);
    } catch (err) { toast(err.message.slice(0, 300), true); e.target.disabled = false; }
  });
}

async function recheck() {
  try {
    const n = await post(`/api/documents/${RV.doc.id}/preview`, overridesWithLinks());
    const keep = overrides();
    RV.doc = {...RV.doc, normalized: n, issues: n.issues, changes: n.changes || RV.doc.changes};
    drawReview();
    Object.entries(keep).forEach(([k, v]) => { const el = document.getElementById("o-" + k); if (el) el.value = v; });
    toast("Checked again");
  } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- manual entry
async function manualEntry() {
  const box = $("#manualbox");
  if (!box) return;
  box.classList.toggle("hidden");
  box.innerHTML = `<div class="row"><label>Supplier<input id="mn-sup" placeholder="e.g. Houseboat Hari" style="width:220px"></label>
    <label>What are you entering?<select id="mn-type"><option value="hotel_rate_sheet">Hotel rates</option><option value="package">A package</option><option value="dmc_rate_sheet">Transfers / activities</option><option value="mixed">A mix</option></select></label>
    <button class="btn primary" id="mn-go" style="margin-bottom:12px">Start</button></div>
    <div class="small muted">For rates you got on the phone or on WhatsApp. They go through the same checks and review as an uploaded file.</div>`;
  $("#mn-go").onclick = async () => {
    try { const d = await post("/api/documents/manual", {supplier: $("#mn-sup").value, document_type: $("#mn-type").value});
      box.classList.add("hidden"); await refreshDocs();
      if (d.extraction && d.document_type === "hotel_rate_sheet") { d.extraction.hotels = [{name: "", rates: [{room_type: "", meal_plan: "CP", occupancy: "double", amount: null, rate_type: "net"}], supplements: [], blackout_dates: []}]; }
      if (d.extraction && d.document_type === "package") { d.extraction.packages = [{title: "", itinerary: [{day: 1}], hotels: [], prices: [{category: "Standard", pax_min: 2, pax_max: 2, occupancy: "per person twin sharing", amount: null}], inclusions: [], exclusions: [], terms: [], destinations: []}]; }
      if (d.extraction && d.document_type === "dmc_rate_sheet") { d.extraction.services = [{kind: "transfer", name: "", basis: "per_vehicle", amount: null, optional: false}]; }
      selectedDoc = d.id;
      RV = {doc: d, tab: "edit", ed: structuredClone(d.extraction), dirty: true, links: {}, showSame: false};
      drawReview(); $("#detail").scrollIntoView({behavior: "smooth"});
    } catch (e) { toast(e.message, true); }
  };
}
