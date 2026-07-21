/* Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved. Proprietary. */
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const state = { tool: "mk7", stores: [], sections: [], ferniSections: [], upload: null, t0: 0, timer: null };

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
    showResult("No se pudieron cargar las secciones: " + e.message, true);
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

/* ── ejecutar ── */
function log(msg, cls = "") {
  const el = $("#log");
  el.classList.remove("hidden");
  el.innerHTML += `<span class="${cls}">${msg}</span>\n`;
  el.scrollTop = el.scrollHeight;
}
$("#runBtn").onclick = async () => {
  let params;
  try { params = buildParams(); }
  catch (e) { showResult(e.message, true); return; }

  $("#runBtn").disabled = true;
  $("#runBtn").textContent = "Trabajando…";
  $("#progWrap").classList.remove("hidden");
  $("#result").classList.add("hidden");
  $("#log").innerHTML = ""; $("#bar").style.width = "0";
  state.t0 = Date.now();
  state.timer = setInterval(() => {
    const s = Math.round((Date.now() - state.t0) / 1000);
    $("#elapsed").textContent = s > 90 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
  }, 1000);

  const es = new EventSource("/api/events");
  es.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    if (ev.type === "progress") {
      const pct = ev.total ? Math.round(100 * ev.done / ev.total) : 0;
      $("#bar").style.width = pct + "%";
      $("#progMsg").textContent = ev.msg || "";
      $("#progPct").textContent = ev.total ? `${ev.done}/${ev.total}` : "";
    } else if (ev.type === "count") {
      $("#rowCount").textContent = ev.rows;
    } else if (ev.type === "info") { log(ev.msg);
    } else if (ev.type === "warn") { log("⚠ " + ev.msg, "w");
    } else if (ev.type === "error") {
      log("✖ " + ev.msg, "e"); showResult(ev.msg, true);
    } else if (ev.type === "done") {
      $("#bar").style.width = "100%";
      showResult(`Listo — <a href="/api/download?f=${encodeURIComponent(ev.path)}">${ev.file}</a>`);
      loadOutputs();
    } else if (ev.type === "eof") {
      es.close(); finish();
    }
  };
  es.onerror = () => { es.close(); finish(); };

  const r = await fetch("/api/run", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool: state.tool, params })
  });
  if (!r.ok) { const j = await r.json(); showResult(j.error, true); es.close(); finish(); }
};
function finish() {
  clearInterval(state.timer);
  $("#runBtn").disabled = false;
  $("#runBtn").textContent = "Iniciar";
}
function showResult(html, bad = false) {
  const el = $("#result");
  el.className = "result" + (bad ? " bad" : "");
  el.innerHTML = html;
  el.classList.remove("hidden");
}

/* ── archivos generados ── */
async function loadOutputs() {
  const files = await (await fetch("/api/outputs")).json();
  $("#outputs").innerHTML = files.length
    ? files.map(f => `<div><a href="/api/download?f=${encodeURIComponent(f.path)}">${f.name}</a>
        <span>${(f.size / 1024).toFixed(0)} KB</span></div>`).join("")
    : "Todavía no hay archivos.";
}

loadStores(); loadOutputs();
