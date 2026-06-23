# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Competidores — un solo Colab para barrer catálogos de la competencia.

`boot("competidores")` muestra un selector de retailer y despacha:
  - PuntoMaestro / Ferrobal / Imperial → engines de API (engines/comp_*.py),
    todos con el mismo contrato (discover_sections / scrape_section / write_excel),
    manejados por una UI unificada tipo "Maestra Sección".
  - Sodimac / Construmart → delega en la Maestra de producción (launchers/maestra.py),
    que ya tiene set_zone, tiendas y todo el flujo probado (no se reinventa).

Salida unificada (engines/comp_base.OUTPUT_COLS) para comparar competidores lado a
lado: Tienda, Sección, Subcategoría, Marca, SKU, Descripción, Precio Normal,
Precio Internet, % Descuento, URL.
"""

# Engines disponibles (clave interna → módulo en engines/). Todos cumplen el mismo
# contrato (discover_sections / scrape_section / write_excel) y los maneja la misma
# UI, sin importar si por dentro usan API JSON, DOM (HTML plano) o navegador.
_API_ENGINES = {
    # Tier A — API JSON pública (rápidos)
    "puntomaestro": "engines.comp_puntomaestro",
    "ferrobal":     "engines.comp_ferrobal",
    "imperial":     "engines.comp_imperial",
    # Tier B — DOM server-rendered (HTML plano, urllib + BeautifulSoup)
    "construplaza": "engines.comp_construplaza",
    "dvp":          "engines.comp_dvp",
    "yolito":       "engines.comp_yolito",
    "oviedo":       "engines.comp_oviedo",
    # Tier C — SPA con navegador (Playwright headless)
    "prodalam":     "engines.comp_prodalam",
}
# Retailers que delegan en la Maestra de producción.
_MAESTRA_RETAILERS = {"sodimac", "construmart"}


def run():
    import importlib
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output

    clear_output(wait=True)

    display(HTML("""
    <div style='background:linear-gradient(120deg,#2E86C1,#5DADE2);color:white;
    padding:1.2rem 1.5rem;border-radius:12px;margin-bottom:1rem;font-family:sans-serif;'>
      <h2 style='margin:0;color:white;'>🛰️ Competidores — Inteligencia de precios</h2>
      <p style='margin:.3rem 0 0;color:rgba(255,255,255,.92);font-size:.95rem;'>
        Elegí un retailer y recorré sus categorías. Salida unificada para comparar
        precios lado a lado. <b>Uso interno.</b>
      </p>
    </div>
    """))

    selector = widgets.Dropdown(
        options=[
            ("🟢 PuntoMaestro  (API VTEX — rápido)", "puntomaestro"),
            ("🟢 Ferrobal  (API WooCommerce — rápido)", "ferrobal"),
            ("🟢 Imperial  (API Oracle — rápido, precio por zona)", "imperial"),
            ("🟡 Construplaza  (Magento — DOM, tienda Matucana 27)", "construplaza"),
            ("🟡 DVP  (Salesforce Commerce — DOM)", "dvp"),
            ("🟡 Yolito  (ASP.NET — DOM)", "yolito"),
            ("🟡 Oviedo  (PHP — DOM)", "oviedo"),
            ("🔴 Prodalam  (Angular SPA — navegador, más lento)", "prodalam"),
            ("🔧 Sodimac  (vía Maestra Sección con tiendas/zona)", "sodimac"),
            ("🔧 Construmart  (vía Maestra Sección)", "construmart"),
        ],
        value="puntomaestro", description="Retailer:",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="560px"),
    )
    cont_btn = widgets.Button(description="Continuar →", button_style="success",
                              layout=widgets.Layout(width="200px"))

    def _go(_b):
        choice = selector.value
        clear_output(wait=True)
        if choice in _MAESTRA_RETAILERS:
            from launchers import maestra
            maestra.run()  # la Maestra de producción ya cubre Sodimac/Construmart
            return
        eng = importlib.import_module(_API_ENGINES[choice])
        _run_api_ui(eng)

    cont_btn.on_click(_go)
    display(widgets.VBox([selector, cont_btn]))


def _run_api_ui(eng):
    """UI unificada (tipo Maestra) para un engine de API que cumple el contrato."""
    import time as _time
    import uuid as _uuid
    import os as _os
    from datetime import datetime
    from pathlib import Path
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output

    try:
        from google.colab import files as colab_files
        IN_COLAB = True
    except ImportError:
        colab_files = None
        IN_COLAB = False

    OUTPUT_DIR = Path.cwd()
    retailer = eng.RETAILER_NAME
    state = {"sections": None, "rows": [], "output_path": None, "running": False}

    # ─── Telemetría (mismo patrón que los demás launchers) ──────────────
    _ACTIVITY_URL = "https://script.google.com/macros/s/AKfycbzALm18Xuw9c7U0tcAE0u1lPvq1j4P5kCxIJvdkDuG5MLVrqKyWd5qt-Kjb-TSP3B82/exec"
    _ACTIVITY_TOKEN = "6kT2hQjLp_VxR8mN3wYsZ-aF7bGdEcU4"
    _SESSION_ID = globals().get("_SESSION_ID") or _uuid.uuid4().hex[:8]
    globals()["_SESSION_ID"] = _SESSION_ID

    def _log_activity(mode="", n_rows_output=0, runtime_s=0, output_file=""):
        try:
            import requests as _rq
            _rq.post(_ACTIVITY_URL, json={
                "token": _ACTIVITY_TOKEN, "session_id": _SESSION_ID, "colab": "competidores",
                "retailer": retailer.lower(), "mode": str(mode or "")[:30], "n_skus": 0,
                "n_stores": 0, "n_rows_output": int(n_rows_output or 0), "n_with_price": 0,
                "runtime_s": int(runtime_s or 0), "output_file": str(output_file or "")[:120],
                "user_hint": (_os.environ.get("COLAB_USER") or _os.environ.get("USER") or "")[:80],
                "colab_url": "",
            }, timeout=5, allow_redirects=True)
        except Exception:
            pass

    display(HTML(f"""
    <div style='background:linear-gradient(120deg,#2E86C1,#5DADE2);color:white;
    padding:1rem 1.4rem;border-radius:12px;margin-bottom:1rem;font-family:sans-serif;'>
      <h2 style='margin:0;color:white;'>🛰️ Competidores · {retailer}</h2>
      <p style='margin:.3rem 0 0;color:rgba(255,255,255,.92);font-size:.92rem;'>
        Cargá las secciones, elegí subcategorías y recorré. Extracción por API (rápida).
      </p>
    </div>
    <style>
    @keyframes c-spin {{ to {{ transform: rotate(360deg); }} }}
    .c-spinner{{display:inline-block;width:14px;height:14px;border:2px solid #2E86C1;
      border-top-color:transparent;border-radius:50%;animation:c-spin .8s linear infinite;
      vertical-align:-3px;margin-right:8px;}}
    </style>"""))

    # ─── Panel de checkboxes (idéntico patrón a Maestra/Ferni) ──────────
    def _checkbox_panel(items, all_checked=True, height="260px", width="640px"):
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
        return cont, (lambda: [b._payload for b in boxes if b.value])

    # ─── Paso 1: cargar secciones ───────────────────────────────────────
    load_btn = widgets.Button(description="🔍 Cargar secciones", button_style="info",
                              layout=widgets.Layout(width="220px"))
    load_status = widgets.Output()
    section_dd = widgets.Dropdown(description="Sección:",
                                  layout=widgets.Layout(width="560px", display="none"),
                                  style={"description_width": "initial"})
    subcat_container = widgets.VBox(layout=widgets.Layout(display="none"))
    _get_subcats = [lambda: []]

    def on_section_change(_=None):
        if not section_dd.value:
            return
        subs = section_dd.value  # [(subcat_name, ref), ...]
        items = [(n, (section_dd.label.split("  ·")[0], n, ref)) for n, ref in subs]
        panel, getter = _checkbox_panel(items, all_checked=True)
        _get_subcats[0] = getter
        subcat_container.children = [widgets.HTML("<b>Subcategorías:</b>"), panel]
        subcat_container.layout.display = ""
        _update_summary()
    section_dd.observe(on_section_change, "value")

    def _discover_progress(ev):
        # Feedback durante la carga de secciones (Imperial escanea el catálogo).
        if ev.get("event") != "discover":
            return
        ph = ev.get("phase"); done = ev.get("done", 0); tot = ev.get("total", 0)
        if ph == "scan" and tot:
            load_status.clear_output(wait=True)
            with load_status:
                display(HTML(f"<span class='c-spinner'></span>Escaneando catálogo de "
                             f"{retailer}… {done}/{tot} ({int(round(100*done/tot))}%)"))
        elif ph == "names":
            load_status.clear_output(wait=True)
            with load_status:
                display(HTML("<span class='c-spinner'></span>Resolviendo nombres de secciones…"))

    def on_load(_b=None):
        load_btn.disabled = True
        with load_status:
            clear_output()
            display(HTML(f"<span class='c-spinner'></span>Cargando secciones de {retailer}…"))
        try:
            secs = eng.discover_sections(progress_cb=_discover_progress)
        except Exception as e:
            with load_status:
                clear_output(); print(f"❌ Error cargando secciones: {e}")
            load_btn.disabled = False
            return
        state["sections"] = secs
        section_dd.options = [(f"{n}  ·  {len(subs)} subcat.", subs) for n, subs in secs]
        section_dd.layout.display = ""
        if section_dd.options:
            section_dd.value = section_dd.options[0][1]
        with load_status:
            clear_output(); print(f"✓ {len(secs)} secciones cargadas.")
        load_btn.disabled = False
        on_section_change()
    load_btn.on_click(on_load)

    # ─── Opciones: zona (si el engine la soporta) + imágenes ────────────
    _zones = getattr(eng, "ZONES", None)
    zone_dd = None
    zone_note = None
    if _zones:
        zone_dd = widgets.Dropdown(
            options=list(_zones), value=_zones[0][1],
            description=getattr(eng, "ZONE_TITLE", "Zona") + ":",
            style={"description_width": "initial"},
            layout=widgets.Layout(width="460px"))
    else:
        # Sin selector de zona: explicar POR QUÉ (precio único / tienda fija / etc.).
        _msg = getattr(eng, "ZONE_NOTE", None) or (
            f"{retailer} no usa selector de zona (precio único en su catálogo).")
        zone_note = widgets.HTML(
            f"<div style='background:#fef9e7;border:1px solid #f7dc6f;border-radius:6px;"
            f"padding:.55rem .8rem;margin:.2rem 0;font-size:.9em;color:#7d6608;'>"
            f"📍 <b>Zona:</b> {_msg}</div>")
    # Toggle de imágenes — SIEMPRE apagado por defecto (Excel más liviano y rápido).
    img_toggle = widgets.Checkbox(
        value=False, indent=False,
        description="Incluir imágenes de producto (Excel más pesado y lento)",
        layout=widgets.Layout(width="auto"))

    # ─── Paso 2: ejecutar ────────────────────────────────────────────────
    run_btn = widgets.Button(description="🚀 Iniciar recorrido", button_style="success",
                             disabled=True, layout=widgets.Layout(width="230px"))
    summary = widgets.HTML()
    banner = widgets.HTML()
    subcat_bar = widgets.IntProgress(min=0, max=100, value=0, description="Subcat:",
                                     bar_style="info", layout=widgets.Layout(width="540px"),
                                     style={"description_width": "initial"})
    subcat_pct = widgets.HTML(layout=widgets.Layout(width="160px"))
    live = widgets.HTML()
    result_out = widgets.Output()

    def _selected_subcats():
        return _get_subcats[0]()  # [(seccion, subcat, ref), ...]

    def _update_summary(*_):
        n = len(_selected_subcats())
        if n:
            summary.value = (f"<div style='background:#eaf4fb;border:1px solid #aed6f1;"
                             f"padding:.6rem;border-radius:6px;margin:.4rem 0;'>"
                             f"📋 Vas a recorrer <b>{n}</b> subcategoría(s) de <b>{retailer}</b>.</div>")
            run_btn.disabled = False
        else:
            summary.value = ""
            run_btn.disabled = True

    def _progress(ev):
        e = ev.get("event")
        if e == "subcat_start":
            subcat_bar.max = ev.get("total", 1) or 1
            live.value = (f"<span class='c-spinner'></span>🗂️ {ev.get('section','')} › "
                          f"{ev.get('subcat','')} ({ev.get('idx')}/{ev.get('total')})")
        elif e == "subcat_page":
            live.value = (f"<span class='c-spinner'></span>🗂️ {ev.get('subcat','')} · "
                          f"pág {ev.get('page')} · {ev.get('n_rows',0)} filas")
        elif e == "subcat_done":
            subcat_bar.value = min(ev.get("idx", subcat_bar.value + 1), subcat_bar.max)
            subcat_bar.description = f"Subcat {subcat_bar.value}/{subcat_bar.max}"
            subcat_pct.value = (f"<span style='color:#555;font-size:.9em;margin-left:8px;'>"
                                f"{subcat_bar.value}/{subcat_bar.max} · "
                                f"{int(round(100*subcat_bar.value/max(1,subcat_bar.max)))}%</span>")
        elif e == "complete":
            live.value = "<span style='color:#27ae60'>✓ Recorrido completado.</span>"

    def _start(_b):
        if state["running"]:
            return
        state["running"] = True
        run_btn.layout.display = "none"
        banner.value = ("<div style='background:linear-gradient(90deg,#ffb84d,#f0a020);"
                        "color:#3a2400;padding:.7rem 1rem;border-radius:8px;font-weight:600;'>"
                        "<span class='c-spinner'></span>Trabajando — no cierres la celda</div>")
        with result_out:
            clear_output()
        state["rows"] = []
        subcat_bar.value = 0
        subcats = _selected_subcats()
        subcat_bar.max = len(subcats) or 1
        ts = datetime.now().strftime("%Y-%m-%d_%H%M")
        zone = zone_dd.value if zone_dd else None
        with_images = bool(img_toggle.value)
        t0 = _time.time()
        try:
            rows = eng.scrape_section(subcats, on_row=lambda r: state["rows"].append(r),
                                      progress_cb=_progress, zone=zone)
            if with_images:
                with result_out:
                    display(HTML("<span class='c-spinner'></span>Descargando y embebiendo "
                                 "imágenes… (puede tardar)"))
            out = OUTPUT_DIR / f"Competidores_{retailer}_{ts}.xlsx"
            eng.write_excel(rows, str(out), with_images=with_images)
            state["output_path"] = out
            n_priced = sum(1 for r in rows if r.get("Precio Internet") not in (None, ""))
            with result_out:
                display(HTML(
                    f"<div style='background:#e8f5e9;border:1px solid #66bb6a;padding:.9rem;"
                    f"border-radius:8px;'>✅ <b>Listo.</b> {len(rows)} filas "
                    f"({n_priced} con precio).<br>📄 Archivo: <code>{out.name}</code></div>"))
            _log_activity(mode="api", n_rows_output=len(rows),
                          runtime_s=int(_time.time() - t0), output_file=out.name)
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
            banner.value = ""
            run_btn.layout.display = ""
    run_btn.on_click(_start)

    watermark = widgets.HTML(
        "<div style='margin-top:1.2rem;padding-top:.6rem;border-top:1px solid #ddd;"
        "color:#999;font-size:.8em;font-family:sans-serif;'>"
        "🛰️ Competidores — Carlos Cruz E.<br>"
        "<span style='font-size:.92em;'>Copyright (c) 2026 Carlos Cruz Errazuriz · "
        "All rights reserved · Proprietary — No unauthorized use or distribution</span></div>")

    step1 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.3rem 0;'>📂 Paso 1 — Secciones</h4>"),
        load_btn, load_status, section_dd, subcat_container])
    opt_children = [widgets.HTML("<h4 style='margin:.6rem 0 .3rem;'>⚙️ Opciones</h4>")]
    if zone_dd is not None:
        opt_children.append(zone_dd)
    elif zone_note is not None:
        opt_children.append(zone_note)
    opt_children.append(img_toggle)
    options_box = widgets.VBox(opt_children)

    step2 = widgets.VBox([
        options_box,
        widgets.HTML("<h4 style='margin:.6rem 0 .3rem;'>🚀 Paso 2 — Ejecutar</h4>"),
        summary, run_btn, banner,
        widgets.HBox([subcat_bar, subcat_pct], layout=widgets.Layout(align_items="center")),
        live, result_out])
    display(widgets.VBox([step1, step2, watermark]))
