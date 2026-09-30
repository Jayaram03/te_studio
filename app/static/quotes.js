// Quotations: every quote sent, numbered and kept as sent. Plus the quote and hotel-option parts of a trip.
"use strict";

const Q_STATUSES = ["draft", "sent", "accepted", "declined", "expired"];
const Q_CLS = {draft: "", sent: "quoted", accepted: "confirmed", declined: "lost", expired: "lost"};
let editingQuote = {};              // trip id -> {id, number} while a quotation is open for editing

function qStatusPill(q) { return `<span class="pill ${Q_CLS[q.status] || ""}">${q.is_expired ? "past validity" : q.status}</span>`; }
function quoteUrl(q) { return q.share_token ? `${location.origin}/q/${q.share_token}` : null; }

async function pageQuotes(main, arg) {
  if (arg) return showQuote(main, +arg);
  main.innerHTML = `<div class="pagehead"><div><h1>Quotations</h1><p>Every quotation you saved, exactly as it was sent. Open one to share it again, edit it or start a new trip from it.</p></div>
      <button class="btn primary" data-go="trips/new">${icon("plus")} New trip &amp; quotation</button></div>
    <div class="card"><div class="row center" style="margin-bottom:12px"><input id="qq" placeholder="Search number, customer, trip, destination" style="width:300px">
      <select id="qs"><option value="">Any status</option>${Q_STATUSES.map(s => `<option>${s}</option>`).join("")}</select></div><div id="qbody"></div></div>`;
  wireGo(main);
  const load = async () => {
    const p = new URLSearchParams(); if ($("#qq").value) p.set("q", $("#qq").value); if ($("#qs").value) p.set("status", $("#qs").value);
    const rows = await api("/api/quotations?" + p);
    $("#qbody").innerHTML = rows.length ? `<div class="scroll"><table><thead><tr><th>Number</th><th>Trip</th><th>Customer</th><th>Status</th><th>Saved</th><th>Valid until</th><th class="num">Total</th><th></th></tr></thead><tbody>
      ${rows.map(q => `<tr class="click" data-q="${q.id}"><td><b>${esc(q.number)}</b><div class="small muted">v${q.version}</div></td><td>${esc(q.title)}<div class="small muted">${esc([q.destination, q.start_date && fmtDate(q.start_date), q.travellers && q.travellers + " pax"].filter(Boolean).join(" · "))}</div></td>
        <td>${esc(q.customer_name || "")}</td><td>${qStatusPill(q)}</td><td class="small">${fmtDate(q.created_at)}${q.created_by ? `<div class="muted">${esc(q.created_by)}</div>` : ""}</td>
        <td class="small ${q.is_expired ? "due" : ""}">${fmtDate(q.valid_until)}</td>
        <td class="num">${q.options.length ? `<span class="small muted">from </span>` : ""}<b>${money(q.total, q.currency)}</b>${q.options.length ? `<div class="small muted">${q.options.length} options</div>` : ""}</td>
        <td class="num" data-stop>${menu("⋯", quoteActions(q, () => load()), "sm")}</td></tr>`).join("")}</tbody></table></div>`
      : empty("No quotations yet. Build a trip, then press “Save as quotation”.", `<button class="btn primary" style="margin-top:10px" data-go="trips/new">${icon("plus")} New trip</button>`);
    $$("#qbody tr[data-q]").forEach(tr => tr.onclick = e => { if (!e.target.closest(".menu")) go("quotes", tr.dataset.q); });
    wireGo($("#qbody"));
  };
  let t; $("#qq").oninput = () => { clearTimeout(t); t = setTimeout(load, 250); }; $("#qs").onchange = load;
  await load();
}

function quoteActions(q, after) {
  return [
    {label: "Open", act: () => go("quotes", q.id)},
    {label: "Download PDF", sub: "with prices", act: () => download(`/api/quotations/${q.id}/pdf`)},
    {label: "Copy client link", act: async () => { const r = q.share_token ? q : await post(`/api/quotations/${q.id}/share`, {}); await copy(quoteUrl(r), "Link copied"); after && after(); }},
    "hr",
    {label: "Edit this quotation", sub: q.trip_id ? "opens it in its trip" : "its trip was deleted: makes a new trip", act: () => editQuote(q)},
    {label: "New trip from this", sub: "same plan, another customer", act: async () => { const t = await post(`/api/quotations/${q.id}/new-trip`, {}); toast("New trip created"); go("trips", t.id); }},
    "hr",
    ...Q_STATUSES.filter(s => s !== q.status).map(s => ({label: `Mark as ${s}`, act: async () => { await patch(`/api/quotations/${q.id}`, {status: s}); toast(`Marked ${s}`); after && after(); }})),
    "hr",
    {label: "Delete quotation", sub: "the trip stays", act: async () => { if (!confirm(`Delete ${q.number}? This can't be undone.`)) return; await del(`/api/quotations/${q.id}`); toast("Deleted"); after ? after() : go("quotes"); }},
  ];
}

async function editQuote(q) {
  if (!confirm(`Open ${q.number} for editing? Its itinerary and costing are loaded into the trip, replacing what the trip has now.`)) return;
  const t = await post(`/api/quotations/${q.id}/restore`);
  editingQuote[t.id] = {id: q.id, number: q.number};
  toast(`${q.number} is open for editing`); go("trips", t.id);
}

async function showQuote(main, id) {
  const q = await api(`/api/quotations/${id}`), v = q.snapshot, tt = v.totals, cur = tt.currency;
  const opts = tt.options || [];
  main.innerHTML = `<div class="pagehead"><div><div class="small muted"><button class="link" data-go="quotes">Quotations</button> / ${esc(q.number)}</div>
      <h1>${esc(q.title)} ${qStatusPill(q)}</h1><p>${esc([q.customer_name, q.destination, q.start_date && fmtDate(q.start_date), q.travellers + " travellers", `version ${q.version}`].filter(Boolean).join(" · "))}</p></div>
    <div class="row">${menu("Actions", quoteActions(q, () => showQuote(main, id)))}<button class="btn primary" id="qe">Edit quotation</button></div></div>
  <div class="grid g-main"><div>
    <div class="card"><h2>Day by day</h2>${v.days.map(d => `<div class="day"><div class="dayhead"><span class="dnum">${String(d.position).padStart(2, "0")}</span><span style="font-weight:500">${esc(d.title || "")}</span>${d.overnight ? `<span class="muted small">· ${esc(d.overnight)}</span>` : ""}</div><p class="small" style="margin:6px 0 0">${esc(d.description || "")}</p></div>`).join("") || `<div class="muted small">No itinerary.</div>`}</div>
    <div class="card"><h2>Costing as quoted</h2><div class="scroll"><table><thead><tr><th>Item</th><th>Option</th><th class="num">Amount</th></tr></thead><tbody>
      ${v.items.map(i => `<tr><td>${esc(i.description)}${i.optional ? ` <span class="pill warn">add-on</span>` : ""}</td><td>${esc(i.option_label || "all")}</td><td class="num">${money(i.amount, i.currency)}</td></tr>`).join("")}</tbody></table></div>
      <div class="small muted" style="margin-top:8px">Markup ${v.markup_pct}% · GST ${v.gst_pct}%</div></div>
  </div><div class="rail">
    <div class="card"><h2>Price</h2>${opts.length ? `<div class="opts">${opts.map(o => `<div class="opt ${o.label === tt.chosen_option ? "on" : ""}"><span>${esc(o.label)}<div class="small muted">${money(o.per_person, cur)} pp</div></span><b>${money(o.sell, cur)}</b></div>`).join("")}</div>`
      : `<div class="bigprice">${money(tt.sell, cur)}</div><div class="small muted">${money(tt.per_person, cur)} per person</div>`}
      <div class="row" style="margin-top:12px"><button class="btn sm" id="qpdf">${icon("down")} PDF</button><button class="btn sm" id="qlink">${icon("share")} ${q.share_token ? "Copy link" : "Create client link"}</button>
      ${q.customer_phone ? `<a class="btn sm" target="_blank" href="https://wa.me/${esc(q.customer_phone.replace(/\D/g, ""))}">${icon("chat")} WhatsApp</a>` : ""}</div></div>
    <div class="card"><h2>Status</h2>
      <div class="row"><label class="grow">Status<select id="qst" class="w100">${Q_STATUSES.map(s => `<option ${s === q.status ? "selected" : ""}>${s}</option>`).join("")}</select></label>
        <label class="grow">Valid until<input type="date" id="qvu" class="w100" value="${q.valid_until || ""}"></label></div>
      ${opts.length ? `<label class="w100">Customer chose<select id="qch" class="w100"><option value="">— not yet —</option>${opts.map(o => `<option ${o.label === tt.chosen_option ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select></label>` : ""}
      <label class="w100">Internal note<textarea id="qnote" style="min-height:60px">${esc(q.note || "")}</textarea></label>
      <button class="btn primary sm" id="qsave">Save</button>
      <div class="small muted" style="margin-top:10px">Saved ${fmtDate(q.created_at)}${q.created_by ? " by " + esc(q.created_by) : ""}${q.sent_at ? ` · sent ${fmtDate(q.sent_at)}` : ""}${q.updated_at && q.updated_at !== q.created_at ? ` · updated ${fmtDate(q.updated_at)}` : ""}</div>
      ${q.trip_id ? `<div style="margin-top:8px"><button class="link" data-go="trips/${q.trip_id}">Open the trip</button></div>` : `<div class="small muted" style="margin-top:8px">The trip was deleted; the quotation is kept.</div>`}</div>
  </div></div>`;
  wireGo(main);
  $("#qe").onclick = () => editQuote(q);
  $("#qpdf").onclick = () => download(`/api/quotations/${id}/pdf`);
  $("#qlink").onclick = async () => { const r = q.share_token ? q : await post(`/api/quotations/${id}/share`, {}); await copy(quoteUrl(r), "Client link copied"); if (!q.share_token) showQuote(main, id); };
  $("#qsave").onclick = async () => {
    try { const body = {status: $("#qst").value, valid_until: $("#qvu").value || "", note: $("#qnote").value};
      if ($("#qch")) body.chosen_option = $("#qch").value;
      await patch(`/api/quotations/${id}`, body); toast("Saved"); showQuote(main, id); } catch (e) { toast(e.message, true); }
  };
}

// ---------------------------------------------------------------- inside the trip workspace
async function tripQuotesCard(t) {
  const rows = await api(`/api/quotations?trip_id=${t.id}`);
  const ed = editingQuote[t.id];
  return `<div class="card"><h2>Quotations <button class="btn sm primary" id="tq-save">${icon("plus")} Save as quotation</button></h2>
    ${ed ? `<div class="banner lav" style="margin:0 0 10px"><span>Editing <b>${esc(ed.number)}</b></span><span class="row"><button class="btn sm primary" id="tq-update">Save changes to ${esc(ed.number)}</button><button class="btn sm" id="tq-stop">Stop editing</button></span></div>` : ""}
    ${rows.length ? rows.map(q => `<div class="row between center" style="padding:7px 0;border-bottom:1px solid var(--line);flex-wrap:nowrap">
        <span><button class="link" data-go="quotes/${q.id}">${esc(q.number)}</button> <span class="small muted">v${q.version} · ${fmtDate(q.created_at)}</span><br>${qStatusPill(q)}</span>
        <span class="num"><b>${money(q.total, q.currency)}</b></span></div>`).join("")
      : `<div class="small muted">Nothing saved yet. Saving keeps a numbered copy of the itinerary and prices exactly as sent, with its own PDF and client link.</div>`}</div>`;
}

function wireTripQuotes(main) {
  const id = T.id;
  $("#tq-save") && ($("#tq-save").onclick = async () => {
    try { const q = await post(`/api/trips/${id}/quotations`, {}); delete editingQuote[id]; toast(`${q.number} saved`); T = await api(`/api/trips/${id}`); drawTrip(main); }
    catch (e) { toast(e.message, true); }
  });
  $("#tq-update") && ($("#tq-update").onclick = async () => {
    const ed = editingQuote[id];
    try { const q = await post(`/api/quotations/${ed.id}/update`); delete editingQuote[id]; toast(`${q.number} updated`); drawTrip(main); } catch (e) { toast(e.message, true); }
  });
  $("#tq-stop") && ($("#tq-stop").onclick = () => { delete editingQuote[id]; drawTrip(main); });
}

// hotel options: "Option A / Option B" or a category name; lines without one are in every option
function optionSelect(i, labels) {
  const all = [...new Set([...labels, "Option A", "Option B", "Option C"])];
  return `<select data-f="option_label" title="Which hotel option this line belongs to" style="width:112px">
    <option value="">all options</option>${all.map(l => `<option ${l === i.option_label ? "selected" : ""}>${esc(l)}</option>`).join("")}<option value="__new">New option…</option></select>`;
}

function optionsPriceHtml(t) {
  const tt = t.totals, cur = tt.currency;
  if (!tt.options.length) return "";
  return `<div class="small muted" style="margin-top:6px">${tt.chosen_option ? "Customer chose" : "Hotel options — the customer picks one:"}</div>
    <div class="opts">${tt.options.map(o => `<label class="opt ${o.label === tt.chosen_option ? "on" : ""}" style="margin:0"><span><input type="radio" name="chosen" value="${esc(o.label)}" ${o.label === tt.chosen_option ? "checked" : ""}> ${esc(o.label)}
      <div class="small muted">${money(o.per_person, cur)} per person</div></span><b>${money(o.sell, cur)}</b></label>`).join("")}
      ${tt.chosen_option ? `<button class="link small" id="opt-clear">Customer hasn't chosen yet</button>` : ""}</div>`;
}
