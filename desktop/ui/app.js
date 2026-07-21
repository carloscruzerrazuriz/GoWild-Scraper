/* Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved. Proprietary. */
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const state = { tool: "mk7", stores: [], sections: [], ferniSections: [], upload: null, t0: 0, timer: null, rows: 0 };

/* ── navegación entre herramientas ── */
$$(".tool").forEach(b => b.onclick = () => {
  $$(".tool").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  state.tool = b.dataset.tool;
  $$(".pane").forEach(p => p.classList.add("hidden"));
  $(`#pane-${state.tool}`).classList.remove("hidden");
});

/* ── tiendas ── */
const RM = "Metropolitana";
async function loadStores() {
  state.stores = await (await fetch("/api/stores")).json();
  $("#stores").innerHTML = state.stores.map(s => `
    <label><input type="checkbox" class="st" value="${s.id}" ${s.id === "E522" ? "checked" : ""}>
    ${s.name} <small>${s.comuna}</small></label>`).join("");
  $$(".st").forEach(c => c.onchange = updateStoreCount);
  updateStoreCount();
}
function updateStoreCount() {
  const n = $$(".st:checked").length;
  $("#storeCount").textContent = `${n} de ${state.stores.length} seleccionadas`;
}
$$(".chip").forEach(c => c.onclick = () => {
  const p = c.dataset.preset;
  $$(".st").forEach(cb => {
    const st = state.stores.find(s => s.id === cb.value);
    cb.checked = p === "all" ? true : p === "none" ? false
      : p === "rm" ? st.region === RM : st.id === "E522";
  });
  updateStoreCount();
});
const selectedStores = () => $$(".st:checked").map(c => c.value);

/* ── MK7: archivo ── */
$("#mk7File").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  $("#mk7FileName").textContent = "Subiendo…";
  const r = await fetch("/api/upload", {
    method: "POST", headers: { "X-Filename": f.name }, body: await f.arrayBuffer()
  });
  const j = await r.json();
  state.upload = j.path;
  $("#mk7FileName").textContent = `✓ ${f.name}`;
};

/* ── Ferni: archivo ── */
$("#ferniFile").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  $("#ferniFileName").textContent = "Subiendo…";
  const r = await fetch("/api/upload", {
    method: "POST", headers: { "X-Filename": f.name }, body: await f.arrayBuffer()
  });
  state.upload = (await r.json()).path;
  $("#ferniFileName").textContent = `✓ ${f.name}`;
};

/* ── Sección: cargar árbol ── */
async function fetchSections(btn, ferni = false) {
  const old = btn.textContent;
  btn.textContent = "Abriendo navegador… (~20s)";
  btn.disabled = true;
  try {
    const res = await fetch("/api/sections" + (ferni ? "?ferni=1" : ""));
    const tree = await res.json();
    if (!res.ok || tree.error) throw new Error(tree.error || ("HTTP " + res.status));
    if (ferni) state.ferniSections = tree; else state.sections = tree;
    return tree;
  } catch (e) {
    // Antes el error se tragaba en silencio (el botón sólo revertía). Ahora se muestra.
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
function countFsubs() {
  $("#fsCount").textContent = `${$$(".fsub:checked").length} subcategorías`;
}
$$("[data-fsub]").forEach(b => b.onclick = () => {
  $$(".fsub").forEach(c => c.checked = b.dataset.fsub === "all"); countFsubs();
});
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
function countSubs() {
  $("#subCount").textContent = `${$$(".sub:checked").length} subcategorías`;
}
$$("[data-sub]").forEach(b => b.onclick = () => {
  $$(".sub").forEach(c => c.checked = b.dataset.sub === "all"); countSubs();
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
    return { input_path: state.upload, store_ids: stores, screenshots: $("#mk7Shots").checked };
  }
  if (state.tool === "seccion") {
    const sec = state.sections[$("#secSelect")?.value];
    if (!sec) throw new Error("Carga y elige una sección.");
    const subs = $$(".sub:checked").map(c => sec.subcats[+c.value]);
    if (!subs.length) throw new Error("Marca al menos una subcategoría.");
    return {
      section: sec.section, subcats: subs, store_ids: stores,
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
    return { section: sec.section, subcats: subs, store_ids: stores,
             screenshots: $("#fsShots").checked };
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

/* ── ejecutar — hasta 3 jobs en paralelo ── */
const MAX_JOBS = 3;
let activeJobs = 0;

/* una barra por fase — se crea sola cuando llega la 1ª señal de esa fase.
   Refleja las mismas fases que el Colab (Tiendas/Subcats/…) sin hardcodear
   cuáles emite cada herramienta. Todo scopeado a la TARJETA del job. */
const PHASE = {
  zona:   { label: "Tiendas",        order: 0 },
  subcat: { label: "Subcategorías",  order: 1 },
  lote:   { label: "Lotes",          order: 2 },
  pagina: { label: "Páginas",        order: 3 },
};
function jobPhaseBar(card, phase) {
  const bars = card.querySelector(".bars");
  let row = bars.querySelector(`[data-phase="${phase}"]`);
  if (!row) {
    const m = PHASE[phase] || { label: phase, order: 9 };
    row = document.createElement("div");
    row.className = "barrow";
    row.dataset.phase = phase;
    row.style.order = m.order;
    row.innerHTML =
      `<div class="barhead"><span class="barlabel">${m.label}</span>` +
      `<span class="barcount"></span></div>` +
      `<div class="bar"><div class="fill"></div></div>` +
      `<div class="barmsg"></div>`;
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
function showGlobalError(msg) {
  const el = $("#globalMsg");
  el.textContent = msg;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 6000);
}
function updateRunBtn() {
  const full = activeJobs >= MAX_JOBS;
  $("#runBtn").disabled = full;
  $("#runBtn").textContent = full ? `Máximo ${MAX_JOBS} a la vez` : "Iniciar";
  $("#runHint").textContent = activeJobs
    ? `${activeJobs} de ${MAX_JOBS} en curso.` : `Puedes lanzar hasta ${MAX_JOBS} a la vez.`;
}

async function startJob() {
  if (activeJobs >= MAX_JOBS) return;
  let params;
  try { params = buildParams(); }        // snapshot de la config actual
  catch (e) { showGlobalError(e.message); return; }
  const tool = state.tool;
  const toolLabel = document.querySelector(`.tool[data-tool="${tool}"] b`).textContent;

  const r = await fetch("/api/run", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool, params })
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { showGlobalError(j.error || "No se pudo iniciar."); return; }

  const card = $("#jobTpl").content.firstElementChild.cloneNode(true);
  card.querySelector(".job-tool").textContent = toolLabel;
  card.querySelector(".job-close").onclick = () => { if (card.dataset.done) card.remove(); };
  $("#jobs").prepend(card);
  activeJobs++; updateRunBtn();
  streamJob(j.job_id, card);
}

function streamJob(jobId, card) {
  const q = (s) => card.querySelector(s);
  const t0 = Date.now();
  let rows = 0;
  const speed = () => {
    const min = (Date.now() - t0) / 60000;
    if (min > 0.05 && rows > 0) q(".speed").textContent = `${Math.round(rows / min)} filas/min`;
  };
  const timer = setInterval(() => {
    const s = Math.round((Date.now() - t0) / 1000);
    q(".elapsed").textContent = s > 90 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
    speed();
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
      if (ev.msg) q(".bannerMsg").textContent = ev.msg;
    } else if (ev.type === "count") {
      rows = ev.rows; q(".rowCount").textContent = ev.rows; speed();
    } else if (ev.type === "info") {
      q(".bannerMsg").textContent = ev.msg;
    } else if (ev.type === "warn") {
      jobAlert(card, ev.msg, "w");
    } else if (ev.type === "error") {
      jobAlert(card, ev.msg, "e"); showJobResult(card, ev.msg, true);
    } else if (ev.type === "done") {
      card.querySelectorAll(".fill").forEach(f => f.style.width = "100%");
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
  card.dataset.done = "1";
  card.querySelector(".banner").classList.add("done");
  const bm = card.querySelector(".bannerMsg");
  if (bm.textContent === "Trabajando…" || !card.querySelector(".result").innerHTML)
    bm.textContent = "Listo.";
  activeJobs = Math.max(0, activeJobs - 1);
  updateRunBtn();
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
  if (!files.length) { $("#outputs").innerHTML = "Todavía no hay archivos."; return; }
  $("#outputs").innerHTML = files.map(f => `<div>
      <span class="out-file">
        <a href="/api/download?f=${encodeURIComponent(f.path)}">${f.name}</a>
        <small class="out-date">${fmtDate(f.mtime)}</small>
      </span>
      <span class="out-meta">
        <span class="out-size">${(f.size / 1048576).toFixed(1)} MB</span>
        <button class="ren" data-path="${encodeURIComponent(f.path)}" data-name="${encodeURIComponent(f.name)}" title="Cambiar nombre">✎</button>
        <button class="del" data-path="${encodeURIComponent(f.path)}" title="Borrar archivo">✕</button>
      </span>
    </div>`).join("");
  $$(".del").forEach(b => b.onclick = () => deleteOutput(decodeURIComponent(b.dataset.path), b));
  $$(".ren").forEach(b => b.onclick = () =>
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

loadStores(); loadOutputs();
