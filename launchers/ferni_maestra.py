# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Ferni Maestra Sodimac — UI: recorre el árbol de categorías de Sodimac y extrae
con la lógica de variantes (medidas exactas para puertas "y más").

Se lanza desde el hub launchers/ferni.py (selector "Maestra Sección").
Motor: engines/ferni_maestra_sodimac.py (reusa el crawl del Maestra de producción).
"""
from engines import ferni_maestra_sodimac as _eng

ALL_STORES        = _eng.ALL_STORES
discover_sections = _eng.discover_sections
scrape_maestra    = _eng.scrape_maestra
write_excel       = _eng.write_excel


def run():
    import asyncio, uuid as _uuid, time as _time
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
             "rows": [], "output_path": None, "running": False}

    # ─── Telemetría ────────────────────────────────────────────────────
    _ACTIVITY_URL = "https://script.google.com/macros/s/AKfycbzALm18Xuw9c7U0tcAE0u1lPvq1j4P5kCxIJvdkDuG5MLVrqKyWd5qt-Kjb-TSP3B82/exec"
    _ACTIVITY_TOKEN = "6kT2hQjLp_VxR8mN3wYsZ-aF7bGdEcU4"
    _SESSION_ID = globals().get("_SESSION_ID") or _uuid.uuid4().hex[:8]
    globals()["_SESSION_ID"] = _SESSION_ID

    def _log_activity(mode="", n_skus=0, n_stores=0, n_rows_output=0, runtime_s=0, output_file=""):
        try:
            import requests as _rq, os as _os
            _rq.post(_ACTIVITY_URL, json={
                "token": _ACTIVITY_TOKEN, "session_id": _SESSION_ID, "colab": "ferni_maestra",
                "retailer": "sodimac", "mode": str(mode or "")[:30],
                "n_skus": int(n_skus or 0), "n_stores": int(n_stores or 0),
                "n_rows_output": int(n_rows_output or 0), "n_with_price": 0,
                "runtime_s": int(runtime_s or 0), "output_file": str(output_file or "")[:120],
                "user_hint": (_os.environ.get("COLAB_USER") or _os.environ.get("USER") or "")[:80],
                "colab_url": "",
            }, timeout=5, allow_redirects=True)
        except Exception:
            pass

    # ─── Header ────────────────────────────────────────────────────────
    display(HTML("""
    <div style='background:linear-gradient(120deg,#2E86C1,#5DADE2);color:white;
    padding:1.2rem 1.5rem;border-radius:12px;margin-bottom:1rem;font-family:sans-serif;'>
      <h2 style='margin:0;color:white;'>🗂️ Ferni — Maestra Sección Sodimac</h2>
      <p style='margin:.3rem 0 0;color:rgba(255,255,255,.92);font-size:.95rem;'>
        Elegí secciones/subcategorías y las recorremos completas. Las puertas (y
        cualquier producto con medidas) salen con <b>una fila por medida</b> y su
        <b>precio exacto</b>.
      </p>
    </div>
    <style>
    @keyframes fm-spin { to { transform: rotate(360deg); } }
    .fm-spinner{display:inline-block;width:14px;height:14px;border:2px solid #2E86C1;
      border-top-color:transparent;border-radius:50%;animation:fm-spin .8s linear infinite;
      vertical-align:-3px;margin-right:8px;}
    .fm-banner{background:linear-gradient(90deg,#ffb84d,#f0a020);color:#3a2400;
      padding:.7rem 1rem;border-radius:8px;font-family:sans-serif;font-weight:600;margin:.5rem 0;}
    </style>
    """))

    # ─── Paso 1: descubrir + elegir secciones ──────────────────────────
    discover_status = widgets.HTML("<span class='fm-spinner'></span>Descubriendo el árbol de categorías de Sodimac…")
    sections_box = widgets.VBox()
    sel_counter = widgets.HTML()
    step1 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.3rem 0;'>📂 Paso 1 — Secciones a recorrer</h4>"),
        discover_status, sections_box, sel_counter,
    ])

    # contenedores de pasos 2 y 3 (ocultos hasta que se descubran secciones)
    stores_container = widgets.VBox(layout=widgets.Layout(display="none"))
    run_container = widgets.VBox(layout=widgets.Layout(display="none"))

    _subcat_boxes = []  # cada cb tiene cb._payload = (section, subcat, url)

    def _refresh_selection(*_):
        sel = [cb._payload for cb in _subcat_boxes if cb.value]
        state["selected_subcats"] = sel
        sel_counter.value = (
            f"<span style='color:#27ae60'>✓ {len(sel)} subcategoría(s) seleccionada(s)</span>"
            if sel else "<span style='color:#c0392b'>⚠️ Seleccioná al menos 1 subcategoría</span>")
        _update_run_summary()

    def _build_sections_ui(sections):
        _subcat_boxes.clear()
        panes = []
        titles = []
        for section_name, subs in sections:
            sec_boxes = []
            for subcat_name, url in subs:
                cb = widgets.Checkbox(value=False, description=subcat_name, indent=False,
                                      layout=widgets.Layout(width="auto", margin="0"))
                cb._payload = (section_name, subcat_name, url)
                cb.observe(_refresh_selection, "value")
                _subcat_boxes.append(cb)
                sec_boxes.append(cb)
            # "todas" de la sección
            all_cb = widgets.Checkbox(value=False, description=f"— Todas ({len(sec_boxes)}) —",
                                      indent=False, layout=widgets.Layout(width="auto"))
            def _toggle_all(change, boxes=sec_boxes):
                for b in boxes:
                    b.value = change["new"]
            all_cb.observe(_toggle_all, "value")
            pane = widgets.VBox([all_cb] + sec_boxes,
                                layout=widgets.Layout(max_height="240px", overflow_y="auto"))
            panes.append(pane)
            titles.append(f"{section_name} ({len(sec_boxes)})")
        acc = widgets.Accordion(children=panes)
        for i, t in enumerate(titles):
            acc.set_title(i, t)
        acc.selected_index = None
        sections_box.children = [acc]

    async def _discover():
        async with Stealth().use_async(async_playwright()) as pw:
            b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx = await b.new_context(viewport={"width": 1280, "height": 900},
                                      user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                                  "Chrome/120.0.0.0 Safari/537.36"))
            page = await ctx.new_page()
            try:
                secs = await discover_sections(page)
            finally:
                await b.close()
            return secs

    # ─── Paso 2: Zonas (presets) ───────────────────────────────────────
    def _build_stores():
        def _checkbox_panel(items, height="220px"):
            boxes = []
            for label, val in items:
                cb = widgets.Checkbox(value=False, description=label, indent=False,
                                      layout=widgets.Layout(width="auto", margin="0"))
                cb._payload = val
                boxes.append(cb)
            list_box = widgets.VBox(boxes, layout=widgets.Layout(
                max_height=height, overflow_y="auto", border="1px solid #d0d0d0",
                padding="6px 10px", width="640px"))
            return list_box, (lambda: [b._payload for b in boxes if b.value]), boxes

        rm = [s for s in ALL_ST if s["region"] == "Metropolitana"]
        presets = {
            "Solo Cerrillos (default — más rápido)": [s for s in ALL_ST if s["id"] == "E522"],
            f"Todas RM ({len(rm)} tiendas)": rm,
            f"Todas Chile ({len(ALL_ST)} tiendas)": ALL_ST,
            "Personalizado": None,
        }
        labeler = lambda s: f"{s['id']}  {s['name']:<14}  ({s.get('comuna','')}, {s['region']})"
        preset_radio = widgets.RadioButtons(options=list(presets.keys()), value=list(presets.keys())[0],
                                            description="Preset:", style={"description_width": "initial"})
        panel, getcustom, boxes = _checkbox_panel([(labeler(s), s) for s in ALL_ST])
        wrap = widgets.VBox([panel], layout=widgets.Layout(display="none"))
        eta = widgets.HTML()

        def _upd(*_):
            preset = presets[preset_radio.value]
            if preset is None:
                wrap.layout.display = ""
                sel = getcustom()
                state["selected_stores"] = sel if sel else [s for s in ALL_ST if s["id"] == "E522"]
            else:
                wrap.layout.display = "none"
                state["selected_stores"] = preset
            n = len(state["selected_stores"])
            eta.value = (f"<span style='color:#27ae60'>✓ {n} tienda(s)</span>" if n
                         else "<span style='color:#c0392b'>⚠️ Seleccioná al menos 1</span>")
            _update_run_summary()

        preset_radio.observe(_upd, "value")
        for b in boxes:
            b.observe(_upd, "value")
        _upd()
        stores_container.children = [
            widgets.HTML("<h4 style='margin:.6rem 0 .3rem;'>📍 Paso 2 — Tiendas</h4>"),
            preset_radio, wrap, eta,
        ]

    # ─── Paso 3: Run ───────────────────────────────────────────────────
    run_btn = widgets.Button(description="🚀 Iniciar recorrido", button_style="success",
                             disabled=True, layout=widgets.Layout(width="230px"))
    running_banner = widgets.HTML()
    live_status = widgets.HTML()
    live_metrics = widgets.HTML()
    result_out = widgets.Output()
    run_summary = widgets.HTML()

    def _update_run_summary(*_):
        n_sc = len(state.get("selected_subcats") or [])
        n_st = len(state.get("selected_stores") or [])
        if n_sc and n_st:
            run_summary.value = (
                f"<div style='background:#eaf4fb;border:1px solid #aed6f1;padding:.6rem;"
                f"border-radius:6px;margin:.4rem 0;font-size:.95em;'>"
                f"📋 Vas a recorrer <b>{n_sc}</b> subcategoría(s) en <b>{n_st}</b> tienda(s). "
                f"<span style='color:#b9770e;'>Ojo: recorrer secciones completas puede tardar "
                f"(cada subcategoría pagina todos sus productos).</span></div>")
            run_btn.disabled = False
        else:
            run_summary.value = ""
            run_btn.disabled = True

    _T0 = [None]; _zones_done = [0]; _subcats_done = [0]

    def _fmt(s):
        s = int(s); m, s = divmod(s, 60); h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _progress(ev):
        e = ev.get("event"); st = ev.get("store") or {}; sn = st.get("name", "?")
        n_st = len(state["selected_stores"]) or 1
        if e == "browser_launching":
            _T0[0] = _time.time(); _zones_done[0] = 0; _subcats_done[0] = 0
            live_status.value = "<span class='fm-spinner'></span>🚀 Lanzando Chromium…"
        elif e == "browser_ready":
            live_status.value = "<span class='fm-spinner'></span>✓ Chromium listo…"
        elif e == "browser_error":
            live_status.value = f"<span style='color:#c0392b'>✗ Error Chromium: {ev.get('msg','')}</span>"
        elif e == "warmup_start":
            live_status.value = f"<span class='fm-spinner'></span>⏳ {sn} · calentando sesión…"
        elif e == "warmup_done":
            live_status.value = f"<span class='fm-spinner'></span>🔧 {sn} · seteando zona…"
        elif e == "subcat_start":
            live_status.value = (f"<span class='fm-spinner'></span>🗂️ {sn} · "
                                 f"{ev.get('section','')} › {ev.get('subcat','')} "
                                 f"({ev.get('idx')}/{ev.get('total')})")
        elif e == "subcat_page":
            tot = ev.get("total_pages")
            live_status.value = (f"<span class='fm-spinner'></span>🗂️ {sn} · {ev.get('subcat','')} · "
                                 f"pág {ev.get('page')}{('/'+str(tot)) if tot else ''} · "
                                 f"{len(state['rows'])} filas")
        elif e == "subcat_done":
            _subcats_done[0] += 1
        elif e == "zone_end":
            _zones_done[0] += 1
            failed = ev.get("zone_failed")
            live_status.value = (f"<span style='color:#c0392b'>✗ {sn} · falló set_zone</span>" if failed
                                 else f"<span style='color:#27ae60'>✓ {sn} · {ev.get('n_rows',0)} filas</span>")
        elif e == "complete":
            live_status.value = "<span style='color:#27ae60'>✓ Recorrido completado.</span>"
        if _T0[0]:
            el = _time.time() - _T0[0]
            parts = [f"<b>🧮 Filas:</b> {len(state['rows'])}",
                     f"<b>Zonas:</b> {_zones_done[0]}/{n_st}",
                     f"<b>Subcats:</b> {_subcats_done[0]}", f"<b>⏱</b> {_fmt(el)}"]
            live_metrics.value = " · ".join(parts)

    def _on_row(r):
        state["rows"].append(r)

    async def _run_pipeline():
        state["rows"] = []
        ts = datetime.now().strftime("%Y-%m-%d_%H%M")
        subcats = state["selected_subcats"]
        stores = list(state["selected_stores"])
        shots = OUTPUT_DIR / "ferni_maestra_shots"
        rows = await scrape_maestra(subcats, stores, headless=True,
                                    screenshot_dir=str(shots),
                                    progress_cb=_progress, on_row=_on_row)
        out = OUTPUT_DIR / f"Maestra_Puertas_Sodimac_Ferni_{ts}.xlsx"
        write_excel(rows, str(out))
        state["output_path"] = out
        return out, rows

    def _on_run(_b):
        if state["running"] or not state.get("selected_subcats") or not state.get("selected_stores"):
            return
        state["running"] = True
        run_btn.layout.display = "none"
        running_banner.value = ("<div class='fm-banner'><span class='fm-spinner'></span>"
                                "Trabajando — no cierres esta pestaña ni la celda</div>")
        with result_out:
            clear_output()
        _t0 = _time.time()
        try:
            out, rows = asyncio.get_event_loop().run_until_complete(_run_pipeline())
            with result_out:
                display(HTML(
                    f"<div style='background:#e8f5e9;border:1px solid #66bb6a;padding:.9rem;"
                    f"border-radius:8px;'>✅ <b>Listo.</b> {len(rows)} filas.<br>"
                    f"📄 Archivo: <code>{out.name}</code></div>"))
            _log_activity(mode="maestra", n_stores=len(state["selected_stores"]),
                          n_rows_output=len(rows), runtime_s=int(_time.time() - _t0),
                          output_file=out.name)
            if IN_COLAB:
                try:
                    colab_files.download(str(out))
                except Exception:
                    pass
                redl = widgets.Button(description="Descargar Excel de nuevo", icon="download",
                                      button_style="info", layout=widgets.Layout(width="260px"))
                redl.on_click(lambda _x: colab_files.download(str(out)))
                with result_out:
                    display(redl)
        except Exception as e:
            with result_out:
                display(HTML(f"<div style='background:#ffe4e4;border:1px solid #c0392b;"
                             f"padding:.9rem;border-radius:8px;'>❌ Error: {e}</div>"))
                import traceback; traceback.print_exc()
        finally:
            state["running"] = False
            running_banner.value = ""
            run_btn.layout.display = ""

    run_btn.on_click(_on_run)
    run_container.children = [
        widgets.HTML("<h4 style='margin:.6rem 0 .3rem;'>🚀 Paso 3 — Ejecutar</h4>"),
        run_summary, run_btn, running_banner, live_status, live_metrics, result_out,
    ]

    watermark = widgets.HTML(
        "<div style='margin-top:1.2rem;padding-top:.6rem;border-top:1px solid #ddd;"
        "color:#999;font-size:.8em;font-family:sans-serif;'>"
        "🚪 Ferni Maestra — Carlos Cruz E.<br>"
        "<span style='font-size:.92em;'>Copyright (c) 2026 Carlos Cruz Errazuriz · "
        "All rights reserved · Proprietary — No unauthorized use or distribution</span></div>")

    display(widgets.VBox([step1, stores_container, run_container, watermark]))

    # ─── Lanzar descubrimiento (async) y poblar la UI ──────────────────
    try:
        sections = asyncio.get_event_loop().run_until_complete(_discover())
    except Exception as e:
        sections = []
        discover_status.value = f"<span style='color:#c0392b'>❌ No se pudo descubrir el árbol: {e}</span>"
    if sections:
        state["sections"] = sections
        n_sub = sum(len(s[1]) for s in sections)
        discover_status.value = (f"<span style='color:#27ae60'>✓ {len(sections)} secciones · "
                                  f"{n_sub} subcategorías</span>")
        _build_sections_ui(sections)
        _build_stores()
        _refresh_selection()
        stores_container.layout.display = ""
        run_container.layout.display = ""
