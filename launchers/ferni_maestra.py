# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Ferni Maestra Sodimac — UI: recorre el árbol de categorías de Sodimac y extrae
con la lógica de variantes (medidas exactas para puertas "y más").

Se lanza desde el hub launchers/ferni.py (selector "Maestra Sección").
Motor: engines/ferni_maestra_sodimac.py (reusa el crawl del Maestra de producción).

Incluye checkpoints en Google Drive (reanudación tras corte) — igual que el
Maestra de producción: cada (tienda, subcategoría) completada se marca y un run
interrumpido se puede retomar sin re-scrapear lo ya hecho.
"""
from engines import ferni_maestra_sodimac as _eng

ALL_STORES        = _eng.ALL_STORES
discover_sections = _eng.discover_sections
scrape_maestra    = _eng.scrape_maestra
write_excel       = _eng.write_excel


def run():
    import asyncio, uuid as _uuid, time as _time, json as _json, os as _os
    from datetime import datetime
    from pathlib import Path
    import nest_asyncio
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    nest_asyncio.apply()
    clear_output(wait=True)

    try:
        from google.colab import files as colab_files
        IN_COLAB = True
    except ImportError:
        colab_files = None
        IN_COLAB = False

    OUTPUT_DIR = Path.cwd()
    ALL_ST = ALL_STORES
    state = {"sections": None, "selected_subcats": [], "selected_stores": [],
             "rows": [], "output_path": None, "running": False,
             "pending_resume": None, "_run_id": None}

    # ─── Telemetría ────────────────────────────────────────────────────
    _ACTIVITY_URL = "https://script.google.com/macros/s/AKfycbzALm18Xuw9c7U0tcAE0u1lPvq1j4P5kCxIJvdkDuG5MLVrqKyWd5qt-Kjb-TSP3B82/exec"
    _ACTIVITY_TOKEN = "6kT2hQjLp_VxR8mN3wYsZ-aF7bGdEcU4"
    _SESSION_ID = globals().get("_SESSION_ID") or _uuid.uuid4().hex[:8]
    globals()["_SESSION_ID"] = _SESSION_ID

    def _log_activity(mode="", n_stores=0, n_rows_output=0, runtime_s=0, output_file=""):
        try:
            import requests as _rq
            _rq.post(_ACTIVITY_URL, json={
                "token": _ACTIVITY_TOKEN, "session_id": _SESSION_ID, "colab": "ferni_maestra",
                "retailer": "sodimac", "mode": str(mode or "")[:30], "n_skus": 0,
                "n_stores": int(n_stores or 0), "n_rows_output": int(n_rows_output or 0),
                "n_with_price": 0, "runtime_s": int(runtime_s or 0),
                "output_file": str(output_file or "")[:120],
                "user_hint": (_os.environ.get("COLAB_USER") or _os.environ.get("USER") or "")[:80],
                "colab_url": "",
            }, timeout=5, allow_redirects=True)
        except Exception:
            pass

    # ─── Checkpoints (módulo compartido engines/_checkpoints.py) ─────────
    from engines import _checkpoints as _ckpts
    PARTIAL_TTL = _ckpts.DEFAULT_TTL_SECS
    PARTIAL_DIR, _ckpt_ephemeral = _ckpts.resolve_dir(
        in_colab=IN_COLAB, drive_subdir="ferni_maestra_partials",
        local_name="_ferni_maestra_partials")
    _ckpts.purge_expired(PARTIAL_DIR)  # TTL 12h por RUN (protege el meta al reanudar)
    if _ckpt_ephemeral:
        display(HTML(_ckpts.ephemeral_warning_html("Ferni Maestra")))

    def _meta_path(rid): return _ckpts.meta_path(PARTIAL_DIR, rid)
    def _jsonl_path(rid): return _ckpts.jsonl_path(PARTIAL_DIR, rid)
    def _done_path(rid): return _ckpts.done_path(PARTIAL_DIR, rid)

    def _write_meta(rid, payload):
        _ckpts.write_meta(PARTIAL_DIR, rid, payload)
        _ckpts.ensure_jsonl(PARTIAL_DIR, rid)  # jsonl EAGER (fix #3)

    def _append_row(rid, row):
        _ckpts.append_row(PARTIAL_DIR, rid, row)

    def _load_rows(rid):
        return _ckpts.load_rows(PARTIAL_DIR, rid)

    def _append_done(rid, store_id, subcat_url):
        _ckpts.append_done(PARTIAL_DIR, rid, store_id, subcat_url)

    def _read_done(rid):
        return _ckpts.read_done(PARTIAL_DIR, rid)

    def _cleanup_run(rid):
        _ckpts.cleanup_run(PARTIAL_DIR, rid)

    def _find_resumable():
        return _ckpts.list_runs(PARTIAL_DIR, unfinished_only=True)

    # ─── Header ────────────────────────────────────────────────────────
    display(HTML("""
    <div style='background:linear-gradient(120deg,#2E86C1,#5DADE2);color:white;
    padding:1.2rem 1.5rem;border-radius:12px;margin-bottom:1rem;font-family:sans-serif;'>
      <h2 style='margin:0;color:white;'>🗂️ Ferni — Maestra Sección Sodimac</h2>
      <p style='margin:.3rem 0 0;color:rgba(255,255,255,.92);font-size:.95rem;'>
        Elige secciones/subcategorías y las recorremos completas. Las puertas (y
        cualquier producto con medidas) salen con <b>una fila por medida</b> y su
        <b>precio exacto</b>. Checkpoints en Drive: si se corta, puedes reanudar.
      </p>
    </div>
    <style>
    @keyframes fm-spin { to { transform: rotate(360deg); } }
    @keyframes fm-pulse { 0%,100%{opacity:1} 50%{opacity:.6} }
    .fm-spinner{display:inline-block;width:14px;height:14px;border:2px solid #2E86C1;
      border-top-color:transparent;border-radius:50%;animation:fm-spin .8s linear infinite;
      vertical-align:-3px;margin-right:8px;}
    .fm-banner{background:linear-gradient(90deg,#ffb84d,#f0a020);color:#3a2400;
      padding:.7rem 1rem;border-radius:8px;font-family:sans-serif;font-weight:600;
      animation:fm-pulse 1.6s ease-in-out infinite;margin:.5rem 0;}
    </style>
    """))

    # ─── Helper: panel de checkboxes limpio (estilo Maestra) ───────────
    def _checkbox_panel(items, all_checked=False, height="240px", width="640px"):
        boxes = []
        for label, val in items:
            cb = widgets.Checkbox(value=all_checked, description=label, indent=False,
                                  layout=widgets.Layout(width="auto", margin="0"))
            cb._payload = val
            boxes.append(cb)
        list_box = widgets.VBox(boxes, layout=widgets.Layout(
            max_height=height, overflow_y="auto", border="1px solid #d0d0d0",
            border_radius="6px", padding="6px 10px", width=width))
        btn_all = widgets.Button(description="Marcar todas", layout=widgets.Layout(width="130px"))
        btn_none = widgets.Button(description="Desmarcar todas", layout=widgets.Layout(width="150px"))
        btn_inv = widgets.Button(description="Invertir", layout=widgets.Layout(width="100px"))
        counter = widgets.HTML()
        def refresh(*_):
            n = sum(1 for b in boxes if b.value)
            counter.value = f"<span style='color:#555;font-size:.9em;'>{n} de {len(boxes)} seleccionadas</span>"
        for b in boxes:
            b.observe(refresh, "value")
        btn_all.on_click(lambda _: [setattr(b, "value", True) for b in boxes])
        btn_none.on_click(lambda _: [setattr(b, "value", False) for b in boxes])
        btn_inv.on_click(lambda _: [setattr(b, "value", not b.value) for b in boxes])
        refresh()
        cont = widgets.VBox([
            widgets.HBox([btn_all, btn_none, btn_inv, counter],
                         layout=widgets.Layout(align_items="center", gap="8px")),
            list_box])
        return cont, (lambda: [b._payload for b in boxes if b.value]), boxes

    # ─── Paso 1: Sección a scrapear (IDÉNTICO a Maestra Sección Sodimac) ──
    stores_container = widgets.VBox(layout=widgets.Layout(display="none"))
    run_container = widgets.VBox(layout=widgets.Layout(display="none"))

    load_btn = widgets.Button(description="🔍 Cargar secciones", button_style="info",
                              layout=widgets.Layout(width="220px"))
    load_status = widgets.Output()
    section_dd = widgets.Dropdown(description="Sección:",
                                  layout=widgets.Layout(width="500px", display="none"),
                                  style={"description_width": "initial"})
    subcat_container = widgets.VBox(layout=widgets.Layout(display="none"))
    _get_subcats = [lambda: []]  # getter del panel de subcats de la sección actual

    mode_selector = widgets.RadioButtons(
        options=[("Sección del menú de Sodimac", "menu"),
                 ("URL personalizada (pegar link de categoría)", "url")],
        value="menu", description="Modo:", style={"description_width": "initial"},
        layout=widgets.Layout(width="500px"))
    custom_url_input = widgets.Text(
        description="URL:", placeholder="https://www.sodimac.cl/sodimac-cl/lista/CATG.../...",
        layout=widgets.Layout(width="700px"), style={"description_width": "initial"})
    custom_name_input = widgets.Text(
        description="Nombre:", placeholder="ej: Pisos-y-revestimientos",
        layout=widgets.Layout(width="500px"), style={"description_width": "initial"})
    custom_box = widgets.VBox(
        [widgets.HTML("<b>Categoría personalizada:</b><br>"
                      "<span style='font-size:.85em;color:#666;'>Pega una URL de listado "
                      "de Sodimac (no funcionan URLs con <code>isLanding=true</code>).</span>"),
         custom_url_input, custom_name_input],
        layout=widgets.Layout(display="none", margin="6px 0"))

    def on_mode_change(change=None):
        if mode_selector.value == "menu":
            load_btn.layout.display = ""
            load_status.layout.display = ""
            section_dd.layout.display = "" if section_dd.options else "none"
            subcat_container.layout.display = "" if section_dd.options else "none"
            custom_box.layout.display = "none"
        else:
            load_btn.layout.display = "none"
            load_status.layout.display = "none"
            section_dd.layout.display = "none"
            subcat_container.layout.display = "none"
            custom_box.layout.display = ""
        _update_run_summary()
    mode_selector.observe(on_mode_change, "value")

    def on_section_change(change=None):
        if not section_dd.value:
            return
        _, subs = section_dd.value
        items = [(n, (n, u)) for n, u in subs]
        panel, getter, _bx = _checkbox_panel(items, all_checked=True, height="260px")
        _get_subcats[0] = getter
        for child in panel.children[1].children:
            child.observe(lambda *_: _update_run_summary(), "value")
        subcat_container.children = [widgets.HTML("<b>Subcategorías:</b>"), panel]
        subcat_container.layout.display = ""
        _update_run_summary()
    section_dd.observe(on_section_change, "value")

    def _collect_subcats():
        """[(section, subcat, url), ...] según el modo (menú / URL personalizada)."""
        if mode_selector.value == "url":
            u = (custom_url_input.value or "").strip()
            nm = (custom_name_input.value or "").strip() or "Categoría personalizada"
            return [(nm, nm, u)] if u else []
        if not section_dd.value:
            return []
        section_name, _subs = section_dd.value
        return [(section_name, n, u) for (n, u) in _get_subcats[0]()]

    def on_load_clicked(_b=None):
        load_btn.disabled = True
        with load_status:
            clear_output()
            display(HTML("<span class='fm-spinner'></span>Leyendo el megamenú de Sodimac…"))
        try:
            secs = asyncio.get_event_loop().run_until_complete(_discover())
        except Exception as e:
            with load_status:
                clear_output(); print(f"❌ Error: {e}")
            load_btn.disabled = False
            return
        if not secs:
            with load_status:
                clear_output(); print("❌ No se pudieron leer las secciones. Espera unos segundos e intenta de nuevo.")
            load_btn.disabled = False
            return
        state["sections"] = secs
        section_dd.options = [(f"{n}  ·  {len(subs)} subcat.", (n, subs)) for n, subs in secs]
        section_dd.layout.display = ""
        section_dd.value = section_dd.options[0][1]
        with load_status:
            clear_output(); print(f"✓ {len(secs)} secciones cargadas.")
        load_btn.disabled = False
        _update_run_summary()
    load_btn.on_click(on_load_clicked)

    step1 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.3rem 0;'>📂 Paso 1 — Sección a scrapear</h4>"),
        mode_selector, load_btn, load_status, section_dd, subcat_container, custom_box])

    async def _discover():
        async with Stealth().use_async(async_playwright()) as pw:
            b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx = await b.new_context(viewport={"width": 1280, "height": 900},
                                      user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                                  "Chrome/120.0.0.0 Safari/537.36"))
            page = await ctx.new_page()
            try:
                # include_landing=False: Ferni Maestra dedup SOLO dentro de cada
                # subcat (no entre subcats), así que el roll-up de las entradas
                # "Todo X" (isLanding) duplicaría filas. Mantiene el árbol clásico.
                return await discover_sections(page, include_landing=False)
            finally:
                await b.close()

    # ─── Paso 2: Zonas (selector limpio estilo Maestra) ────────────────
    rm = [s for s in ALL_ST if s["region"] == "Metropolitana"]
    PRESETS = {
        "Solo Cerrillos (más rápido)": [s for s in ALL_ST if s["id"] == "E522"],
        f"Todas RM ({len(rm)} tiendas)": rm,
        f"Todas Chile ({len(ALL_ST)} tiendas)": ALL_ST,
        "Personalizado": None,
    }
    preset_radio = widgets.RadioButtons(options=list(PRESETS.keys()), value="Solo Cerrillos (más rápido)",
                                        description="Preset:", style={"description_width": "initial"},
                                        layout=widgets.Layout(width="auto"))
    store_items = [(f"{s['id']}  {s['name']}  ({s['comuna']})", s) for s in ALL_ST]
    store_panel, get_custom_stores, store_boxes = _checkbox_panel(store_items, all_checked=False, height="240px")
    store_panel_wrap = widgets.VBox([store_panel], layout=widgets.Layout(display="none"))
    store_eta = widgets.HTML()
    capture_screenshots = widgets.Checkbox(
        value=False, description="Capturar screenshots de cards (Excel más pesado y lento)",
        indent=False, layout=widgets.Layout(width="auto"))

    def _update_stores(*_):
        preset = PRESETS[preset_radio.value]
        if preset is None:
            store_panel_wrap.layout.display = ""
            sel = get_custom_stores()
            state["selected_stores"] = sel if sel else [s for s in ALL_ST if s["id"] == "E522"]
        else:
            store_panel_wrap.layout.display = "none"
            state["selected_stores"] = preset
        n = len(state["selected_stores"])
        store_eta.value = (f"<span style='color:#27ae60'>✓ {n} tienda(s)</span>" if n
                           else "<span style='color:#c0392b'>⚠️ Selecciona al menos 1 tienda</span>")
        _update_run_summary()

    preset_radio.observe(_update_stores, "value")
    for b in store_boxes:
        b.observe(_update_stores, "value")
    stores_container.children = [
        widgets.HTML("<h4 style='margin:.6rem 0 .3rem;'>📍 Paso 2 — Tiendas</h4>"),
        preset_radio, store_panel_wrap, store_eta,
        widgets.HTML("<h4 style='margin:.8rem 0 .3rem;'>⚙️ Opciones</h4>"),
        capture_screenshots,
    ]

    # ─── Paso 3: Run (barras tienda/subcat/página) ─────────────────────
    run_btn = widgets.Button(description="🚀 Iniciar recorrido", button_style="success",
                             disabled=True, layout=widgets.Layout(width="230px"))
    running_banner = widgets.HTML()
    resume_panel = widgets.VBox()
    store_bar = widgets.IntProgress(min=0, max=100, value=0, description="Tiendas:",
                                    bar_style="info", layout=widgets.Layout(width="540px"),
                                    style={"description_width": "initial"})
    store_pct = widgets.HTML(layout=widgets.Layout(width="120px"))
    subcat_bar = widgets.IntProgress(min=0, max=100, value=0, description="Subcat:",
                                     bar_style="info", layout=widgets.Layout(width="540px"),
                                     style={"description_width": "initial"})
    subcat_pct = widgets.HTML(layout=widgets.Layout(width="120px"))
    page_bar = widgets.IntProgress(min=0, max=100, value=0, description="Páginas:",
                                   bar_style="info", layout=widgets.Layout(width="540px"),
                                   style={"description_width": "initial"})
    page_pct = widgets.HTML(layout=widgets.Layout(width="120px"))
    live_status = widgets.HTML()
    live_metrics = widgets.HTML()
    result_out = widgets.Output()
    run_summary = widgets.HTML()

    def _set_pct(w, v, t):
        w.value = "" if not t else f"<span style='color:#555;font-size:.9em;margin-left:8px;'>{v}/{t} · {int(round(100*v/t))}%</span>"

    def _update_run_summary(*_):
        n_sc = len(_collect_subcats())
        n_st = len(state.get("selected_stores") or [])
        if n_sc and n_st:
            run_summary.value = (
                f"<div style='background:#eaf4fb;border:1px solid #aed6f1;padding:.6rem;"
                f"border-radius:6px;margin:.4rem 0;font-size:.95em;'>"
                f"📋 Vas a recorrer <b>{n_sc}</b> subcategoría(s) en <b>{n_st}</b> tienda(s). "
                f"<span style='color:#b9770e;'>Recorrer secciones completas puede tardar; "
                f"si se corta, puedes reanudar desde el checkpoint.</span></div>")
            run_btn.disabled = False
        else:
            run_summary.value = ""
            run_btn.disabled = True

    _T0 = [None]; _last_store = [None]

    def _fmt(s):
        s = int(s); m, s = divmod(s, 60); h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _progress(ev):
        e = ev.get("event"); st = ev.get("store") or {}; sn = st.get("name", "?")
        n_st = store_bar.max or 1
        # Reset subcat bar al cambiar de tienda (cubre tiendas skipeadas en resume).
        sid = st.get("id")
        if sid and sid != _last_store[0]:
            _last_store[0] = sid
            subcat_bar.value = 0; _set_pct(subcat_pct, 0, subcat_bar.max)
            page_bar.value = 0; page_bar.description = "Páginas:"; _set_pct(page_pct, 0, page_bar.max)
        if e == "browser_launching":
            _T0[0] = _time.time()
            live_status.value = "<span class='fm-spinner'></span>🚀 Lanzando Chromium…"
        elif e == "browser_ready":
            live_status.value = "<span class='fm-spinner'></span>✓ Chromium listo…"
        elif e == "browser_error":
            live_status.value = f"<span style='color:#c0392b'>✗ Error Chromium: {ev.get('msg','')}</span>"
        elif e == "warmup_start":
            live_status.value = f"<span class='fm-spinner'></span>⏳ {sn} · calentando sesión…"
        elif e == "warmup_done":
            live_status.value = f"<span class='fm-spinner'></span>🔧 {sn} · seteando zona…"
        elif e == "zone_start":
            subcat_bar.max = ev.get("n_subcats", 1) or 1
            subcat_bar.value = 0; _set_pct(subcat_pct, 0, subcat_bar.max)
        elif e == "subcat_start":
            live_status.value = (f"<span class='fm-spinner'></span>🗂️ {sn} · "
                                 f"{ev.get('section','')} › {ev.get('subcat','')} "
                                 f"({ev.get('idx')}/{ev.get('total')})")
            page_bar.max = 1; page_bar.value = 0; page_bar.description = "Páginas:"; _set_pct(page_pct, 0, 1)
        elif e == "subcat_page":
            tot = ev.get("total_pages"); cur = ev.get("page", 1)
            if tot:
                page_bar.max = tot; page_bar.value = min(cur, tot); page_bar.description = f"Páginas {cur}/{tot}"
                _set_pct(page_pct, min(cur, tot), tot)
            else:
                page_bar.max = max(page_bar.max, cur); page_bar.value = cur; page_bar.description = f"Página {cur}"
                _set_pct(page_pct, cur, page_bar.max)
            live_status.value = (f"<span class='fm-spinner'></span>🗂️ {sn} · {ev.get('subcat','')} · "
                                 f"pág {cur}{('/'+str(tot)) if tot else ''} · {len(state['rows'])} filas")
        elif e == "subcat_done":
            subcat_bar.max = ev.get("total", subcat_bar.max) or subcat_bar.max
            subcat_bar.value = min(ev.get("idx", subcat_bar.value + 1), subcat_bar.max)
            subcat_bar.description = f"Subcat {subcat_bar.value}/{subcat_bar.max}"
            _set_pct(subcat_pct, subcat_bar.value, subcat_bar.max)
            # Persistir checkpoint: marcar (tienda, subcat) como hecha.
            if not ev.get("skipped") and state.get("_run_id") and ev.get("subcat_url") and sid:
                _append_done(state["_run_id"], sid, ev["subcat_url"])
        elif e == "zone_end":
            store_bar.value = min(store_bar.value + 1, n_st)
            store_bar.description = f"Tiendas {store_bar.value}/{n_st}"
            _set_pct(store_pct, store_bar.value, n_st)
            failed = ev.get("zone_failed")
            live_status.value = (f"<span style='color:#c0392b'>✗ {sn} · falló set_zone</span>" if failed
                                 else f"<span style='color:#27ae60'>✓ {sn} · {ev.get('n_rows',0)} filas</span>")
        elif e == "complete":
            live_status.value = "<span style='color:#27ae60'>✓ Recorrido completado.</span>"
        if _T0[0]:
            el = _time.time() - _T0[0]
            live_metrics.value = " · ".join([f"<b>🧮 Filas:</b> {len(state['rows'])}",
                                             f"<b>⏱</b> {_fmt(el)}"])

    def _on_row(r):
        state["rows"].append(r)
        if state.get("_run_id"):
            _append_row(state["_run_id"], r)

    async def _run_pipeline(resume=None):
        ts = datetime.now().strftime("%Y-%m-%d_%H%M")
        if resume:
            run_id = resume["run_id"]; meta = resume["meta"]
            subcats = [tuple(x) for x in meta["subcats"]]
            stores = meta["stores"]
            done = resume["done"]
            state["rows"] = list(resume["rows"])
            shots_on = meta.get("screenshots", True)
        else:
            run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_ferni_maestra"
            subcats = _collect_subcats()
            stores = list(state["selected_stores"])
            done = set()
            state["rows"] = []
            shots_on = bool(capture_screenshots.value)
            _write_meta(run_id, {"run_id": run_id, "ts": ts, "subcats": subcats,
                                 "stores": stores, "screenshots": shots_on, "finished": False})
        state["_run_id"] = run_id

        store_bar.max = len(stores); store_bar.value = 0; _set_pct(store_pct, 0, len(stores))
        subcat_bar.max = len(subcats); subcat_bar.value = 0; _set_pct(subcat_pct, 0, len(subcats))
        _last_store[0] = None

        shots = (OUTPUT_DIR / "ferni_maestra_shots") if shots_on else None
        rows = await scrape_maestra(subcats, stores, headless=True,
                                    screenshot_dir=(str(shots) if shots else None),
                                    progress_cb=_progress, on_row=_on_row, done_keys=done)
        # Usar el acumulado real (prior + nuevos) por si el engine devolvió solo nuevos.
        all_rows = state["rows"] if resume else rows
        out = OUTPUT_DIR / f"Maestra_Puertas_Sodimac_Ferni_{ts}.xlsx"
        write_excel(all_rows, str(out), with_images=shots_on)
        state["output_path"] = out
        _cleanup_run(run_id)  # Excel OK → borrar checkpoint
        state["_run_id"] = None
        return out, all_rows

    def _start(resume=None):
        if state["running"]:
            return
        state["running"] = True
        run_btn.layout.display = "none"
        resume_panel.layout.display = "none"
        running_banner.value = ("<div class='fm-banner'><span class='fm-spinner'></span>"
                                "Trabajando — no cierres esta pestaña ni la celda</div>")
        with result_out:
            clear_output()
        _t0 = _time.time()
        try:
            out, rows = asyncio.get_event_loop().run_until_complete(_run_pipeline(resume))
            with result_out:
                display(HTML(
                    f"<div style='background:#e8f5e9;border:1px solid #66bb6a;padding:.9rem;"
                    f"border-radius:8px;'>✅ <b>Listo.</b> {len(rows)} filas.<br>"
                    f"📄 Archivo: <code>{out.name}</code></div>"))
            _log_activity(mode="maestra", n_stores=len(state.get("selected_stores") or []),
                          n_rows_output=len(rows), runtime_s=int(_time.time() - _t0), output_file=out.name)
            if IN_COLAB:
                try: colab_files.download(str(out))
                except Exception: pass
                redl = widgets.Button(description="Descargar Excel de nuevo", icon="download",
                                      button_style="info", layout=widgets.Layout(width="260px"))
                redl.on_click(lambda _x: colab_files.download(str(out)))
                with result_out: display(redl)
        except Exception as e:
            with result_out:
                display(HTML(f"<div style='background:#ffe4e4;border:1px solid #c0392b;"
                             f"padding:.9rem;border-radius:8px;'>❌ Error: {e}<br>"
                             f"<small>El checkpoint quedó guardado: puedes reanudar.</small></div>"))
                import traceback; traceback.print_exc()
        finally:
            state["running"] = False
            running_banner.value = ""
            run_btn.layout.display = ""
            _refresh_resume_panel()

    run_btn.on_click(lambda _b: _start(None))
    run_container.children = [
        widgets.HTML("<h4 style='margin:.6rem 0 .3rem;'>🚀 Paso 3 — Ejecutar</h4>"),
        run_summary, resume_panel, run_btn, running_banner,
        widgets.HBox([store_bar, store_pct], layout=widgets.Layout(align_items="center")),
        widgets.HBox([subcat_bar, subcat_pct], layout=widgets.Layout(align_items="center")),
        widgets.HBox([page_bar, page_pct], layout=widgets.Layout(align_items="center")),
        live_status, live_metrics, result_out]

    # ─── Panel de reanudación ──────────────────────────────────────────
    def _refresh_resume_panel():
        if state["running"]:
            resume_panel.children = []; return
        resumables = _find_resumable()
        if not resumables:
            resume_panel.children = []; return
        cards = [widgets.HTML("<h4 style='margin:.4rem 0;'>🔄 Recorridos sin terminar (reanudables)</h4>")]
        for rid, meta, prior_rows, done in resumables[:4]:
            n_sc = len(meta.get("subcats") or []); n_st = len(meta.get("stores") or [])
            info = widgets.HTML(
                f"<div style='font-size:.9em;'>📦 <code>{meta.get('ts','?')}</code> · "
                f"{n_sc} subcat × {n_st} tiendas · <b>{len(prior_rows)}</b> filas guardadas · "
                f"{len(done)} (tienda×subcat) hechas</div>")
            btn = widgets.Button(description="Reanudar", button_style="warning",
                                 icon="play", layout=widgets.Layout(width="140px"))
            dele = widgets.Button(description="Descartar", layout=widgets.Layout(width="120px"))
            def _mk(rid=rid, meta=meta, prior_rows=prior_rows, done=done):
                def _do(_b):
                    _start({"run_id": rid, "meta": meta, "rows": prior_rows, "done": done})
                return _do
            def _mkdel(rid=rid):
                def _do(_b):
                    _cleanup_run(rid); _refresh_resume_panel()
                return _do
            btn.on_click(_mk()); dele.on_click(_mkdel())
            cards.append(widgets.HBox([info, btn, dele], layout=widgets.Layout(align_items="center", gap="8px")))
        resume_panel.children = cards

    watermark = widgets.HTML(
        "<div style='margin-top:1.2rem;padding-top:.6rem;border-top:1px solid #ddd;"
        "color:#999;font-size:.8em;font-family:sans-serif;'>"
        "🚪 Ferni Maestra — Carlos Cruz E.<br>"
        "<span style='font-size:.92em;'>Copyright (c) 2026 Carlos Cruz Errazuriz · "
        "All rights reserved · Proprietary — No unauthorized use or distribution</span></div>")

    display(widgets.VBox([step1, stores_container, run_container, watermark]))

    # Mostrar todo de una. Las secciones se cargan con el botón "Cargar secciones"
    # (modo menú) o se pega una URL (modo URL personalizada) — igual que Maestra.
    on_mode_change()
    _update_stores()
    _refresh_resume_panel()
    stores_container.layout.display = ""
    run_container.layout.display = ""
    _update_run_summary()
