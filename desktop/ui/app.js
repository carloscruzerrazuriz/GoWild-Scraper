/* Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved. Proprietary. */
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const state = { tool: "mk7", retailer: "sodimac", loadedRetailer: null, stores: [], sections: [], ferniSections: [], upload: null, storeSel: new Set() };

/* ── retailer (solo Buscar por SKU y Catálogo) ── */
const MULTI_RETAILER = new Set(["mk7", "seccion"]);
function syncRetailerSeg() {
  $$("#retailerSeg button").forEach(b => b.classList.toggle("on", b.dataset.ret === state.retailer));
}
function updateRetailerRow() {
  const multi = MULTI_RETAILER.has(state.tool);
  $("#retailerRow").classList.toggle("hidden", !multi);
  if (!multi && state.retailer !== "sodimac") selectRetailer("sodimac");
}
async function selectRetailer(ret) {
  state.retailer = ret; syncRetailerSeg();
  state.sections = []; $("#secWrap")?.classList.add("hidden");  // secciones son por-retailer
  if (state.loadedRetailer !== ret) await loadStores(ret);
}
$$("#retailerSeg button").forEach(b => b.onclick = () => selectRetailer(b.dataset.ret));

/* ── tema (claro por defecto, recordado) ── */
(function initTheme() {
  const t = localStorage.getItem("cruzer-theme") || "light";
  document.documentElement.setAttribute("data-theme", t);
  setThemeLabel(t);
})();
function setThemeLabel(t) { $("#themeLbl").textContent = t === "dark" ? "🌙 Oscuro" : "☀️ Claro"; }
$("#themeBtn").onclick = () => {
  const d = document.documentElement, next = d.getAttribute("data-theme") === "dark" ? "light" : "dark";
  d.setAttribute("data-theme", next); localStorage.setItem("cruzer-theme", next); setThemeLabel(next);
};

/* ── navegación entre herramientas ── */
$$(".tool").forEach(b => b.onclick = () => {
  $$(".tool").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  state.tool = b.dataset.tool;
  $("#paneTitle").textContent = b.dataset.title;
  $("#paneKick").textContent = b.dataset.kick;
  $$(".pane").forEach(p => p.classList.add("hidden"));
  $(`#pane-${state.tool}`).classList.remove("hidden");
  updateRetailerRow();
});

/* ── tiendas (chips + búsqueda + colapso) ── */
const RM = "Metropolitana";
async function loadStores(retailer) {
  retailer = retailer || state.retailer || "sodimac";
  if (retailer === "construmart") {
    $("#storeSummary").textContent = "Descubriendo tiendas…";
    $("#storeSub").textContent = "abriendo navegador (~20s)";
  }
  try {
    const data = await (await fetch("/api/stores?retailer=" + retailer)).json();
    if (!Array.isArray(data)) throw new Error(data && data.error ? data.error : "respuesta inválida");
    state.stores = data;
  } catch (e) {
    showGlobalError("No se pudieron cargar las tiendas: " + (e.message || e));
    state.stores = [];
  }
  state.loadedRetailer = retailer;
  const def = state.stores.find(s => s.id === "E522") || state.stores[0];
  state.storeSel = new Set(def ? [def.id] : []);
  renderChips($("#storeSearch")?.value || ""); summ();
}
function renderChips(filter = "") {
  const f = filter.toLowerCase();
  $("#storeChips").innerHTML = state.stores
    .filter(s => s.name.toLowerCase().includes(f) || (s.comuna || "").toLowerCase().includes(f))
    .map(s => `<span class="stchip ${state.storeSel.has(s.id) ? "on" : ""}" data-id="${s.id}">${s.name} <small>${s.comuna}</small></span>`).join("");
  $$("#storeChips .stchip").forEach(c => c.onclick = () => {
    const id = c.dataset.id;
    state.storeSel.has(id) ? state.storeSel.delete(id) : state.storeSel.add(id);
    renderChips($("#storeSearch").value); summ();
  });
}
function summ() {
  const ids = [...state.storeSel];
  const names = ids.map(id => (state.stores.find(s => s.id === id) || {}).name).filter(Boolean);
  $("#storeSummary").textContent = names.length ? (names[0] + (names.length > 1 ? ` +${names.length - 1}` : "")) : "Ninguna";
  $("#storeSub").textContent = `${ids.length} de ${state.stores.length} seleccionada${ids.length === 1 ? "" : "s"}`;
}
const selectedStores = () => [...state.storeSel];
function toggleStores(open) {
  const t = $("#storeToggle"), cur = t.getAttribute("aria-expanded") === "true";
  const next = open === undefined ? !cur : open;
  t.setAttribute("aria-expanded", next);
  $("#storePanel").classList.toggle("hidden", !next);
}
$("#storeToggle").onclick = () => toggleStores();
$("#storeToggle").onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleStores(); } };
$("#storeSearch").oninput = e => renderChips(e.target.value);
$$(".preset").forEach(p => p.onclick = () => {
  const k = p.dataset.preset; state.storeSel.clear();
  state.stores.forEach(s => {
    if (k === "all") state.storeSel.add(s.id);
    else if (k === "rm" && s.region === RM) state.storeSel.add(s.id);
    else if (k === "cerrillos" && s.id === "E522") state.storeSel.add(s.id);
  });
  renderChips($("#storeSearch").value); summ();
});

/* ── subir Excel (reusable + drag & drop) ── */
async function uploadFile(file, labelSel) {
  if (!file) return;
  const span = $(labelSel), old = span.textContent;
  span.textContent = "Subiendo…";
  try {
    const r = await fetch("/api/upload", { method: "POST", headers: { "X-Filename": file.name }, body: await file.arrayBuffer() });
    state.upload = (await r.json()).path;
    span.textContent = `✓ ${file.name}`;
  } catch (e) { span.textContent = old; showGlobalError("No se pudo subir el archivo."); }
}
$("#mk7File").onchange = e => uploadFile(e.target.files[0], "#mk7FileName");
$("#ferniFile").onchange = e => uploadFile(e.target.files[0], "#ferniFileName");
$$(".drop").forEach(d => {
  const sel = d.dataset.drop === "mk7" ? "#mk7FileName" : "#ferniFileName";
  d.addEventListener("dragover", e => { e.preventDefault(); d.classList.add("drag"); });
  d.addEventListener("dragleave", () => d.classList.remove("drag"));
  d.addEventListener("drop", e => { e.preventDefault(); d.classList.remove("drag"); uploadFile(e.dataTransfer.files[0], sel); });
});

/* ── Sección: cargar árbol ── */
async function fetchSections(btn, ferni = false) {
  const old = btn.textContent;
  btn.textContent = "Abriendo navegador… (~20s)";
  btn.disabled = true;
  try {
    const qs = ferni ? "?ferni=1" : ("?retailer=" + encodeURIComponent(state.retailer));
    const res = await fetch("/api/sections" + qs);
    const tree = await res.json();
    if (!res.ok || tree.error) throw new Error(tree.error || ("HTTP " + res.status));
    if (ferni) state.ferniSections = tree; else state.sections = tree;
    return tree;
  } catch (e) {
    showGlobalError("No se pudieron cargar las secciones: " + e.message);
    return null;
  } finally { btn.textContent = old; btn.disabled = false; }
}

/* ── Ferni Sección ── */
$("#fsLoadSections").onclick = async (e) => {
  const tree = await fetchSections(e.target, true);
  if (!tree) return;
  $("#fsWrap").classList.remove("hidden");
  $("#fsSelect").innerHTML = tree.map((s, i) =>
    `<option value="${i}">${s.section} (${s.subcats.length})</option>`).join("");
  $("#fsSelect").onchange = renderFsSubcats;
  renderFsSubcats();
};
function renderFsSubcats() {
  const sec = state.ferniSections[$("#fsSelect").value];
  $("#fsSubcats").innerHTML = sec.subcats.map((s, i) =>
    `<label><input type="checkbox" class="fsub" value="${i}" checked> ${s.name}</label>`).join("");
  $$(".fsub").forEach(c => c.onchange = countFsubs);
  countFsubs();
}
function countFsubs() { $("#fsCount").textContent = `${$$(".fsub:checked").length} subcategorías`; }
$$("[data-fsub]").forEach(b => b.onclick = () => {
  $$(".fsub").forEach(c => c.checked = b.dataset.fsub === "all"); countFsubs();
});

/* ── Maestra Sección ── */
$("#loadSections").onclick = async (e) => {
  const tree = await fetchSections(e.target);
  if (!tree) return;
  $("#secWrap").classList.remove("hidden");
  $("#secSelect").innerHTML = tree.map((s, i) =>
    `<option value="${i}">${s.section} (${s.subcats.length})</option>`).join("");
  $("#secSelect").onchange = renderSubcats;
  renderSubcats();
};
function renderSubcats() {
  const sec = state.sections[$("#secSelect").value];
  $("#subcats").innerHTML = sec.subcats.map((s, i) =>
    `<label><input type="checkbox" class="sub" value="${i}" checked> ${s.name}</label>`).join("");
  $$(".sub").forEach(c => c.onchange = countSubs);
  countSubs();
}
function countSubs() { $("#subCount").textContent = `${$$(".sub:checked").length} subcategorías`; }
$$("[data-sub]").forEach(b => b.onclick = () => {
  $$(".sub").forEach(c => c.checked = b.dataset.sub === "all"); countSubs();
});

/* ── Catálogo: modo (menú del sitio vs URL directa, como en Colab) ── */
$$("[name=secMode]").forEach(r => r.onchange = () => {
  const url = r.value === "url" && r.checked;
  $("#secMenuWrap").classList.toggle("hidden", url);
  $("#secUrlWrap").classList.toggle("hidden", !url);
});

/* ── Fast: alcance ── */
$$("[name=fastScope]").forEach(r => r.onchange = () => {
  $("#fastSecWrap").classList.toggle("hidden", r.value !== "sections" || !r.checked);
  $("#fastUrl").classList.toggle("hidden", r.value !== "url" || !r.checked);
});
$("#fastLoadSections").onclick = async (e) => {
  const tree = await fetchSections(e.target);
  if (!tree) return;
  $("#fastSections").innerHTML = tree.map(s =>
    `<label><input type="checkbox" class="fsec" value="${s.section}" checked> ${s.section}</label>`).join("");
};

/* ── construir params ── */
function buildParams() {
  const stores = selectedStores();
  if (!stores.length) throw new Error("Selecciona al menos una tienda.");
  if (state.tool === "mk7") {
    if (!state.upload) throw new Error("Sube el archivo Excel con los SKUs.");
    return { retailer: state.retailer, input_path: state.upload, store_ids: stores, screenshots: $("#mk7Shots").checked };
  }
  if (state.tool === "seccion") {
    const mode = $("[name=secMode]:checked")?.value || "menu";
    if (mode === "url") {
      const url = $("#secUrl").value.trim();
      if (!/^https?:\/\//.test(url)) throw new Error("Pega una URL válida de la categoría (empieza con http).");
      const name = $("#secUrlName").value.trim() || "URL personalizada";
      return {
        retailer: state.retailer, section: "Custom", subcats: [{ name, url }], store_ids: stores,
        include_non_sodimac: $("#secNonSod").checked, screenshots: $("#secShots").checked
      };
    }
    const sec = state.sections[$("#secSelect")?.value];
    if (!sec) throw new Error("Carga y elige una sección.");
    const subs = $$(".sub:checked").map(c => sec.subcats[+c.value]);
    if (!subs.length) throw new Error("Marca al menos una subcategoría.");
    return {
      retailer: state.retailer, section: sec.section, subcats: subs, store_ids: stores,
      include_non_sodimac: $("#secNonSod").checked, screenshots: $("#secShots").checked
    };
  }
  if (state.tool === "ferni_sku") {
    if (!state.upload) throw new Error("Sube el archivo Excel con los SKUs de puertas.");
    return { input_path: state.upload, store_ids: stores, screenshots: $("#ferniShots").checked };
  }
  if (state.tool === "ferni_seccion") {
    const sec = state.ferniSections?.[$("#fsSelect")?.value];
    if (!sec) throw new Error("Carga y elige una sección.");
    const subs = $$(".fsub:checked").map(c => sec.subcats[+c.value]);
    if (!subs.length) throw new Error("Marca al menos una subcategoría.");
    return { section: sec.section, subcats: subs, store_ids: stores, screenshots: $("#fsShots").checked };
  }
  const scope = $("[name=fastScope]:checked").value;
  const p = { store_ids: stores, wholesale_only: $("#fastWholesale").checked };
  if (scope === "sections") {
    p.sections = $$(".fsec:checked").map(c => c.value);
    if (!p.sections.length) throw new Error("Marca al menos una sección.");
  } else if (scope === "url") {
    p.url = $("#fastUrl").value.trim();
    if (!p.url.includes("sodimac.cl")) throw new Error("Pega una URL válida de Sodimac.");
  }
  return p;
}

/* ═══ ejecutar — hasta 3 jobs en paralelo ═══ */
const MAX_JOBS = 3;
let activeJobs = 0;

const PHASE = {
  zona:   { label: "Tiendas",       order: 0 },
  subcat: { label: "Subcategorías", order: 1 },
  lote:   { label: "Lotes",         order: 2 },
  pagina: { label: "Páginas",       order: 3 },
};
function jobPhaseBar(card, phase) {
  const bars = card.querySelector(".bars");
  let row = bars.querySelector(`[data-phase="${phase}"]`);
  if (!row) {
    const m = PHASE[phase] || { label: phase, order: 9 };
    row = document.createElement("div");
    row.className = "barrow"; row.dataset.phase = phase; row.style.order = m.order;
    row.innerHTML = `<div class="barhead"><span class="barlabel">${m.label}</span><span class="barcount"></span></div>
      <div class="track"><div class="fill"></div></div><div class="barmsg"></div>`;
    bars.appendChild(row);
  }
  return row;
}
function jobAlert(card, msg, cls) {
  const box = card.querySelector(".alerts");
  box.classList.remove("hidden");
  const d = document.createElement("div");
  d.className = "alert " + cls;
  d.innerHTML = `<span>${cls === "e" ? "✖" : "⚠"}</span><span>${msg}</span>`;
  box.appendChild(d);
}
function showJobResult(card, html, bad = false) {
  const el = card.querySelector(".result");
  el.className = "result" + (bad ? " bad" : "");
  el.innerHTML = html;
  el.classList.remove("hidden");
}
function setStatus(card, kind, text) {
  const s = card.querySelector(".status");
  s.className = "status " + kind;
  s.querySelector(".stxt").textContent = text;
}
function showGlobalError(msg) {
  const el = $("#globalMsg");
  el.textContent = msg; el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 6000);
}
function updateRunBtn() {
  const full = activeJobs >= MAX_JOBS;
  $("#runBtn").disabled = full;
  $("#runBtn").textContent = full ? `Máximo ${MAX_JOBS} a la vez` : "Iniciar";
  $("#runHint").textContent = activeJobs ? `${activeJobs} de ${MAX_JOBS} en curso.` : `Puedes lanzar hasta ${MAX_JOBS} a la vez`;
}
function afterRemove() { if (!$("#jobs").children.length) $("#jobsEmpty").classList.remove("hidden"); }

async function startJob() {
  if (activeJobs >= MAX_JOBS) return;
  let params;
  try { params = buildParams(); } catch (e) { showGlobalError(e.message); return; }
  const tool = state.tool;
  const toolLabel = document.querySelector(`.tool[data-tool="${tool}"] .tt b`).textContent;

  const r = await fetch("/api/run", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool, params })
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { showGlobalError(j.error || "No se pudo iniciar."); return; }
  $("#globalMsg").classList.add("hidden");

  const card = $("#jobTpl").content.firstElementChild.cloneNode(true);
  card.querySelector(".job-tool").textContent = toolLabel;
  card.querySelector(".jclose").onclick = () => { card.remove(); afterRemove(); };
  card.querySelector(".jcancel").onclick = async () => {
    card.dataset.cancelled = "1";
    setStatus(card, "warn", "Cancelando…");
    card.querySelector(".jcancel").disabled = true;
    await fetch("/api/cancel", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job: j.job_id })
    }).catch(() => {});
  };
  $("#jobsEmpty").classList.add("hidden");
  $("#jobs").prepend(card);
  activeJobs++; updateRunBtn();
  streamJob(j.job_id, card);
}

function fmtDur(s) {
  s = Math.max(0, Math.round(s));
  return s > 90 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
}
function streamJob(jobId, card) {
  const q = (s) => card.querySelector(s);
  const t0 = Date.now();
  let rows = 0, frac = 0, etaShown = false, tick = 0;   // frac = avance global (0..1)
  const speed = () => {
    const min = (Date.now() - t0) / 60000;
    if (min > 0.05 && rows > 0) q(".speed").textContent = `${Math.round(rows / min)} filas/min`;
  };
  // ETA en MINUTOS, se refresca cada 20 s (no cada segundo).
  const eta = () => {
    const el = (Date.now() - t0) / 1000;
    if (frac > 0.01 && frac < 0.995 && el > 6) {
      const mins = Math.max(1, Math.round(el * (1 - frac) / frac / 60));
      q(".eta").textContent = `~${mins} min restante`;
      q(".eta-sep").classList.remove("hidden");
      etaShown = true;
    }
  };
  const timer = setInterval(() => {
    const s = Math.round((Date.now() - t0) / 1000);
    q(".elapsed").textContent = fmtDur(s);
    speed();
    if (++tick % 20 === 0) eta();   // refresco del ETA cada 20 s
  }, 1000);

  const es = new EventSource("/api/events?job=" + encodeURIComponent(jobId));
  es.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    if (ev.type === "progress") {
      const row = jobPhaseBar(card, ev.phase);
      const pct = ev.total ? Math.round(100 * ev.done / ev.total) : 0;
      row.querySelector(".fill").style.width = pct + "%";
      row.querySelector(".barcount").textContent = ev.total ? `${ev.done}/${ev.total}` : "";
      row.querySelector(".barmsg").textContent = ev.msg || "";
      if (ev.msg) q(".curaction").textContent = ev.msg;
      if (typeof ev.frac === "number") { frac = ev.frac; if (!etaShown) eta(); }  // 1er ETA apenas hay avance
    } else if (ev.type === "count") {
      rows = ev.rows; q(".rowCount").textContent = ev.rows; speed();
    } else if (ev.type === "info") {
      q(".curaction").textContent = ev.msg;
    } else if (ev.type === "warn") {
      jobAlert(card, ev.msg, "w");
    } else if (ev.type === "error") {
      jobAlert(card, ev.msg, "e"); showJobResult(card, ev.msg, true); card.dataset.err = "1";
    } else if (ev.type === "done") {
      card.querySelectorAll(".fill").forEach(f => { f.style.width = "100%"; f.classList.add("ok"); });
      showJobResult(card, `Listo — <a href="/api/download?f=${encodeURIComponent(ev.path)}">${ev.file}</a>`);
      loadOutputs();
    } else if (ev.type === "eof") {
      es.close(); endJob(card, timer);
    }
  };
  es.onerror = () => { es.close(); endJob(card, timer); };
}

function endJob(card, timer) {
  clearInterval(timer);
  activeJobs = Math.max(0, activeJobs - 1); updateRunBtn();
  card.querySelector(".jcancel")?.remove();
  card.querySelector(".jclose").classList.remove("hidden");
  card.querySelector(".curaction").classList.add("hidden");
  card.querySelector(".eta").textContent = "";
  card.querySelector(".eta-sep").classList.add("hidden");
  card.dataset.done = "1";
  if (card.dataset.cancelled) setStatus(card, "warn", "Cancelado");
  else if (card.dataset.err) setStatus(card, "err", "Error");
  else if (card.querySelector(".alert.w")) setStatus(card, "warn", "Con avisos");
  else setStatus(card, "done", "Listo");
}
$("#runBtn").onclick = startJob;

/* ── archivos generados ── */
function fmtDate(ms) {
  if (!ms) return "";
  return new Date(ms).toLocaleString("es-CL",
    { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
async function loadOutputs() {
  const files = await (await fetch("/api/outputs")).json();
  if (!files.length) {
    $("#outputs").innerHTML = `<div class="empty"><span class="ei">▦</span>Todavía no hay archivos.</div>`;
    return;
  }
  $("#outputs").innerHTML = files.map(f => `<div class="file">
    <span class="fic">▦</span>
    <span class="fmeta"><a href="/api/download?f=${encodeURIComponent(f.path)}">${f.name}</a><small>${fmtDate(f.mtime)}</small></span>
    <span class="fsize">${(f.size / 1048576).toFixed(1)} MB</span>
    <button class="iconbtn ren" data-path="${encodeURIComponent(f.path)}" data-name="${encodeURIComponent(f.name)}" title="Cambiar nombre">✎</button>
    <button class="iconbtn del" data-path="${encodeURIComponent(f.path)}" title="Borrar">✕</button>
  </div>`).join("");
  $$("#outputs .del").forEach(b => b.onclick = () => deleteOutput(decodeURIComponent(b.dataset.path), b));
  $$("#outputs .ren").forEach(b => b.onclick = () =>
    renameOutput(decodeURIComponent(b.dataset.path), decodeURIComponent(b.dataset.name), b));
}
async function renameOutput(path, current, btn) {
  const name = prompt("Nuevo nombre del archivo:", current);
  if (name === null) return;
  const trimmed = name.trim();
  if (!trimmed || trimmed === current) return;
  btn.disabled = true;
  const r = await fetch("/api/rename", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, name: trimmed })
  });
  if (r.ok) { loadOutputs(); return; }
  btn.disabled = false;
  const j = await r.json().catch(() => ({}));
  alert(j.error || "No se pudo cambiar el nombre.");
}
async function deleteOutput(path, btn) {
  if (!confirm("¿Borrar este archivo? No se puede deshacer.")) return;
  btn.disabled = true;
  const r = await fetch("/api/delete", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path })
  });
  if (r.ok) { loadOutputs(); return; }
  btn.disabled = false;
  const j = await r.json().catch(() => ({}));
  alert(j.error || "No se pudo borrar el archivo.");
}

/* ── atajos de teclado ── */
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); startJob(); }
  if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
    e.preventDefault(); toggleStores(true); $("#storeSearch").focus();
  }
});

loadStores(); loadOutputs(); updateRetailerRow();
