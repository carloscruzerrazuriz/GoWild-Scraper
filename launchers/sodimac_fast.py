# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Sodimac Fast — hub (Buscador por SKU / Maestra Sección) browserless y rápido.

`boot("sodimac_fast")` muestra un selector y despacha a uno de dos modos, ambos
sobre el engine browserless `engines/sodimac_fast` (handshake de zona con el
navegador una sola vez por zona; el resto por urllib leyendo el __NEXT_DATA__).

Trade-off vs MK7/Maestra de producción: NO trae Precio CMR/Mayorista/Congelados
ni fotos (sólo del DOM). A cambio es bastante más rápido.
"""

_SPIN_CSS = """
<style>
@keyframes sf-spin { to { transform: rotate(360deg); } }
.sf-spin{display:inline-block;width:13px;height:13px;border:2px solid #fa6900;
  border-top-color:transparent;border-radius:50%;animation:sf-spin .8s linear infinite;
  vertical-align:-2px;margin-right:7px;}
</style>
"""


def run():
    import nest_asyncio
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output

    nest_asyncio.apply()
    clear_output(wait=True)

    display(HTML("""
    <div style='background:linear-gradient(120deg,#fa6900,#ff9a3c);color:white;
    padding:1.2rem 1.5rem;border-radius:12px;margin-bottom:1rem;font-family:sans-serif;'>
      <h2 style='margin:0;color:white;'>⚡ Sodimac Fast</h2>
      <p style='margin:.3rem 0 0;color:rgba(255,255,255,.92);font-size:.95rem;'>
        Versión rápida (extracción por API/JSON, sin render). Elegí la herramienta.
        <br><small>No incluye Precio CMR/Mayorista/Congelados ni fotos.</small>
      </p>
    </div>
    """))

    selector = widgets.RadioButtons(
        options=[
            ("🔍  Buscador por SKU — subís un Excel de SKUs (como el MK7)", "sku"),
            ("🗂️  Maestra Sección — recorre categorías completas", "seccion"),
        ],
        value="sku", description="Herramienta:",
        style={"description_width": "initial"}, layout=widgets.Layout(width="auto"))
    cont = widgets.Button(description="Continuar →", button_style="warning",
                          layout=widgets.Layout(width="200px"))

    def _go(_b):
        clear_output(wait=True)
        (_run_sku if selector.value == "sku" else _run_seccion)()
    cont.on_click(_go)
    display(widgets.VBox([selector, cont]))


# ─── Helpers compartidos ─────────────────────────────────────────────────────
def _fmt_elapsed(secs):
    secs = int(secs)
    return f"{secs}s" if secs < 60 else f"{secs // 60}m {secs % 60:02d}s"


def _running_banner(widgets):
    return widgets.HTML("<div style='background:linear-gradient(90deg,#ffb84d,#f0a020);"
                        "color:#3a2400;padding:.6rem 1rem;border-radius:8px;font-weight:600;"
                        "font-family:sans-serif;'><span class='sf-spin'></span>"
                        "Trabajando — no cierres la celda</div>")


def _metrics_html(n_rows, elapsed, extra=""):
    rate = (n_rows / elapsed * 60) if elapsed > 0 else 0
    return (f"<div style='display:flex;gap:1.2rem;flex-wrap:wrap;background:#fff8ef;"
            f"border:1px solid #f0c890;padding:.55rem .8rem;border-radius:8px;"
            f"font-family:sans-serif;font-size:.95rem;'>"
            f"<span>📦 <b>{n_rows}</b> filas</span>"
            f"<span>⏱ {_fmt_elapsed(elapsed)}</span>"
            f"<span>⚡ {rate:.0f} filas/min</span>{extra}</div>")


def _zone_picker(widgets):
    """Panel de selección de zonas (Cerrillos pre-marcada). Devuelve (box, getter)."""
    from engines import sodimac_fast as eng
    stores = eng.ALL_STORES
    boxes = []
    for s in stores:
        cb = widgets.Checkbox(value=(s["id"] == "E522"), description=f"{s['name']} ({s['id']})",
                              indent=False, layout=widgets.Layout(width="auto", margin="0"))
        cb._store = s
        boxes.append(cb)
    grid = widgets.VBox(boxes, layout=widgets.Layout(
        max_height="220px", overflow_y="auto", border="1px solid #d0d0d0",
        padding="6px 10px", width="420px"))
    b_rm = widgets.Button(description="Todas RM", layout=widgets.Layout(width="110px"))
    b_all = widgets.Button(description="Todas Chile", layout=widgets.Layout(width="120px"))
    b_none = widgets.Button(description="Ninguna", layout=widgets.Layout(width="100px"))
    counter = widgets.HTML()

    def refresh(*_):
        n = sum(1 for b in boxes if b.value)
        counter.value = f"<span style='color:#555;font-size:.9em;'>{n} zona(s)</span>"
    for b in boxes:
        b.observe(refresh, "value")
    b_rm.on_click(lambda _: [setattr(b, "value", b._store["region"] == "Metropolitana") for b in boxes])
    b_all.on_click(lambda _: [setattr(b, "value", True) for b in boxes])
    b_none.on_click(lambda _: [setattr(b, "value", False) for b in boxes])
    refresh()
    box = widgets.VBox([
        widgets.HTML("<b>Zonas / tiendas:</b>"),
        widgets.HBox([b_rm, b_all, b_none, counter], layout=widgets.Layout(gap="6px")),
        grid])
    return box, (lambda: [b._store for b in boxes if b.value])


def _telemetry(mode, n_rows, runtime_s, output_file):
    try:
        import os as _os, uuid as _uuid, requests as _rq
        _SID = globals().get("_SESSION_ID") or _uuid.uuid4().hex[:8]
        globals()["_SESSION_ID"] = _SID
        _rq.post("https://script.google.com/macros/s/AKfycbzALm18Xuw9c7U0tcAE0u1lPvq1j4P5kCxIJvdkDuG5MLVrqKyWd5qt-Kjb-TSP3B82/exec",
                 json={"token": "6kT2hQjLp_VxR8mN3wYsZ-aF7bGdEcU4", "session_id": _SID,
                       "colab": "sodimac_fast", "retailer": "sodimac", "mode": mode,
                       "n_rows_output": int(n_rows or 0), "runtime_s": int(runtime_s or 0),
                       "output_file": str(output_file or "")[:120],
                       "user_hint": (_os.environ.get("COLAB_USER") or _os.environ.get("USER") or "")[:80]},
                 timeout=5, allow_redirects=True)
    except Exception:
        pass


def _watermark(widgets):
    return widgets.HTML(
        "<div style='margin-top:1.2rem;padding-top:.6rem;border-top:1px solid #ddd;"
        "color:#999;font-size:.8em;font-family:sans-serif;'>⚡ Sodimac Fast — Carlos Cruz E.<br>"
        "<span style='font-size:.92em;'>Copyright (c) 2026 Carlos Cruz Errazuriz · "
        "All rights reserved · Proprietary — No unauthorized use or distribution</span></div>")


def _zfail_note(state):
    """Nota HTML si hubo zonas que no pudieron fijar zona (set_zone falló)."""
    n = state.get("zfail", 0)
    return (f"<br><span style='color:#c0392b;font-size:.9em'>⚠️ {n} zona(s) no fijaron "
            f"zona y se saltaron (latencia/Cloudflare) — reintentá esas zonas.</span>") if n else ""


# ─── Modo 1: Buscador por SKU ────────────────────────────────────────────────
def _run_sku():
    import io, time as _time, asyncio
    from datetime import datetime
    from pathlib import Path
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output
    from engines import sodimac_fast as eng
    try:
        from google.colab import files as colab_files
        IN_COLAB = True
    except ImportError:
        colab_files = None
        IN_COLAB = False

    OUTPUT_DIR = Path.cwd()
    display(HTML(_SPIN_CSS + "<h3 style='font-family:sans-serif'>⚡🔍 Sodimac Fast — Buscador por SKU</h3>"))
    upload = widgets.FileUpload(accept=".xlsx", multiple=False, description="Subir Excel SKUs")
    paste = widgets.Textarea(placeholder="…o pegá SKU Sodimac separados por coma/espacio/línea",
                             layout=widgets.Layout(width="560px", height="70px"))
    status = widgets.HTML()
    zbox, get_zones = _zone_picker(widgets)
    run_btn = widgets.Button(description="🚀 Buscar", button_style="warning",
                             layout=widgets.Layout(width="200px"))

    # ── Panel de progreso en vivo ──
    banner = widgets.HTML()
    zone_bar = widgets.IntProgress(min=0, max=100, value=0, description="Zonas:",
                                   bar_style="warning", layout=widgets.Layout(width="520px"),
                                   style={"description_width": "initial"})
    zone_pct = widgets.HTML(layout=widgets.Layout(width="150px"))
    batch_bar = widgets.IntProgress(min=0, max=100, value=0, description="Batches:",
                                    bar_style="info", layout=widgets.Layout(width="520px"),
                                    style={"description_width": "initial"})
    batch_pct = widgets.HTML(layout=widgets.Layout(width="150px"))
    metrics = widgets.HTML()
    live = widgets.HTML()
    out = widgets.Output()
    state = {"running": False, "rows": [], "zi": 0}

    def _parse():
        skus, easy, desc = [], {}, {}
        up = upload.value
        if up:
            try:
                import pandas as pd
                content = (next(iter(up.values()))["content"] if isinstance(up, dict) else up[0]["content"])
                if hasattr(content, "tobytes"):
                    content = content.tobytes()
                df = pd.read_excel(io.BytesIO(content), dtype=str)
                low = {str(c).lower().strip(): c for c in df.columns}
                sc = next((low[k] for k in low if "sodimac" in k), None) or \
                    next((low[k] for k in low if k.strip() in ("sku", "sku producto")), None)
                ec = next((low[k] for k in low if "easy" in k), None)
                dc = next((low[k] for k in low if "desc" in k), None)
                if sc:
                    for _, r in df.iterrows():
                        s = str(r[sc]).strip()
                        if s and s.lower() != "nan":
                            skus.append(s)
                            if ec and str(r[ec]).lower() != "nan":
                                easy[s] = str(r[ec]).strip()
                            if dc and str(r[dc]).lower() != "nan":
                                desc[s] = str(r[dc]).strip()
            except Exception as e:
                status.value = f"<span style='color:#c0392b'>⚠️ Error leyendo Excel: {e}</span>"
        for t in __import__("re").split(r"[\s,;]+", paste.value or ""):
            if t.strip():
                skus.append(t.strip())
        seen, ded = set(), []
        for s in skus:
            if s not in seen:
                seen.add(s)
                ded.append(s)
        return ded, easy, desc

    def _refresh(*_):
        skus, _e, _d = _parse()
        status.value = (f"<div style='background:#fff4e0;border:1px solid #f0a020;padding:.4rem;"
                        f"border-radius:6px;'>📋 {len(skus)} SKU únicos</div>" if skus else "")
    upload.observe(_refresh, "value")
    paste.observe(_refresh, "value")

    def _start(_b):
        if state["running"]:
            return
        skus, easy, desc = _parse()
        zones = get_zones()
        if not skus or not zones:
            with out:
                clear_output()
                print("⚠️ Falta SKUs o zonas.")
            return
        state.update(running=True, rows=[], zi=0, zfail=0)
        run_btn.layout.display = "none"
        banner.value = _running_banner(widgets).value
        zone_bar.max = len(zones)
        zone_bar.value = 0
        zone_bar.description = f"Zonas 0/{len(zones)}"
        batch_bar.value = 0
        with out:
            clear_output()
        t0 = _time.time()

        def _cb(ev):
            e = ev["event"]
            if e == "zone_start":
                state["zi"] += 1
                batch_bar.value = 0
                live.value = (f"<span class='sf-spin'></span>🗺️ Zona {state['zi']}/{len(zones)}: "
                              f"<b>{ev['store']['name']}</b> — fijando zona (handshake)…")
                metrics.value = _metrics_html(len(state["rows"]), _time.time() - t0)
            elif e == "batch_done":
                batch_bar.max = ev["total_batches"]
                batch_bar.value = ev["batch"]
                batch_bar.description = f"Batches {ev['batch']}/{ev['total_batches']}"
                batch_pct.value = (f"<span style='color:#555;font-size:.9em'>"
                                   f"{int(100*ev['batch']/max(1,ev['total_batches']))}%</span>")
                live.value = (f"<span class='sf-spin'></span>🔎 {ev['store']['name']} · "
                              f"batch {ev['batch']}/{ev['total_batches']} · +{ev['found_in_batch']} encontrados")
                metrics.value = _metrics_html(len(state["rows"]), _time.time() - t0)
            elif e == "zone_done":
                zone_bar.value = min(zone_bar.value + 1, zone_bar.max)
                zone_bar.description = f"Zonas {zone_bar.value}/{zone_bar.max}"
                zone_pct.value = (f"<span style='color:#555;font-size:.9em'>"
                                  f"{int(100*zone_bar.value/max(1,zone_bar.max))}%</span>")
                if ev.get("zone_failed"):
                    state["zfail"] = state.get("zfail", 0) + 1
                    live.value = (f"<span style='color:#c0392b'>✗ {ev['store']['name']}: "
                                  f"no se pudo fijar la zona (saltada)</span>")
                metrics.value = _metrics_html(len(state["rows"]), _time.time() - t0)

        try:
            rows = asyncio.run(eng.search_skus(
                skus, zones, easy_map=easy, desc_map=desc, progress_cb=_cb,
                on_row=lambda r: state["rows"].append(r)))
            el = _time.time() - t0
            metrics.value = _metrics_html(len(rows), el)
            live.value = "<span style='color:#27ae60'>✓ Listo.</span>"
            if not rows:
                with out:
                    display(HTML("<div style='background:#fff4e0;border:1px solid #f0a020;padding:.8rem;"
                                 "border-radius:8px;'>⚠️ <b>0 productos</b> encontrados — no se generó archivo. "
                                 "Revisá los SKU o las zonas (¿zonas con set_zone fallido?).</div>"))
                _telemetry("sku", 0, el, "")
            else:
                ts = datetime.now().strftime("%Y-%m-%d_%H%M")
                outp = OUTPUT_DIR / f"SodimacFast_SKU_{ts}.xlsx"
                eng.write_excel(rows, str(outp))
                with out:
                    display(HTML(f"<div style='background:#e8f5e9;border:1px solid #66bb6a;padding:.8rem;"
                                 f"border-radius:8px;'>✅ <b>{len(rows)}</b> filas en {_fmt_elapsed(el)} · "
                                 f"<code>{outp.name}</code>{_zfail_note(state)}</div>"))
                _telemetry("sku", len(rows), el, outp.name)
                if IN_COLAB and outp.exists():
                    def _dl(_x=None, _p=str(outp)):
                        try:
                            colab_files.download(_p)
                        except Exception:
                            pass
                    _dl()
                    redl = widgets.Button(description="Descargar Excel de nuevo", icon="download",
                                          button_style="info", layout=widgets.Layout(width="260px"))
                    redl.on_click(_dl)
                    with out:
                        display(redl)
        except Exception as e:
            with out:
                display(HTML(f"<div style='background:#ffe4e4;border:1px solid #c0392b;padding:.8rem;"
                             f"border-radius:8px;'>❌ {e}</div>"))
                import traceback
                traceback.print_exc()
        finally:
            state["running"] = False
            banner.value = ""
            run_btn.layout.display = ""
    run_btn.on_click(_start)

    display(widgets.VBox([
        widgets.HTML("<b>1) SKUs</b> (formato MK7: columna <code>SKU Sodimac</code> + opcional SKU Easy / Desc.)"),
        upload, paste, status,
        widgets.HTML("<b>2) Zonas</b>"), zbox,
        widgets.HTML("<b>3) Ejecutar</b>"), run_btn, banner,
        widgets.HBox([zone_bar, zone_pct], layout=widgets.Layout(align_items="center")),
        widgets.HBox([batch_bar, batch_pct], layout=widgets.Layout(align_items="center")),
        metrics, live, out, _watermark(widgets)]))


# ─── Modo 2: Maestra Sección ─────────────────────────────────────────────────
def _run_seccion():
    import time as _time, asyncio
    from datetime import datetime
    from pathlib import Path
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output
    from engines import sodimac_fast as eng
    try:
        from google.colab import files as colab_files
        IN_COLAB = True
    except ImportError:
        colab_files = None
        IN_COLAB = False

    OUTPUT_DIR = Path.cwd()
    display(HTML(_SPIN_CSS + "<h3 style='font-family:sans-serif'>⚡🗂️ Sodimac Fast — Maestra Sección</h3>"))
    load_btn = widgets.Button(description="🔍 Cargar secciones", button_style="info",
                              layout=widgets.Layout(width="220px"))
    load_st = widgets.Output()
    sec_dd = widgets.Dropdown(description="Sección:", layout=widgets.Layout(width="560px", display="none"),
                              style={"description_width": "initial"})
    sub_box = widgets.VBox(layout=widgets.Layout(display="none"))
    zbox, get_zones = _zone_picker(widgets)
    run_btn = widgets.Button(description="🚀 Recorrer", button_style="warning",
                             disabled=True, layout=widgets.Layout(width="200px"))

    # ── Panel de progreso en vivo ──
    banner = widgets.HTML()
    zone_bar = widgets.IntProgress(min=0, max=100, value=0, description="Zonas:",
                                   bar_style="warning", layout=widgets.Layout(width="520px"),
                                   style={"description_width": "initial"})
    zone_pct = widgets.HTML(layout=widgets.Layout(width="150px"))
    sub_bar = widgets.IntProgress(min=0, max=100, value=0, description="Subcat:",
                                  bar_style="info", layout=widgets.Layout(width="520px"),
                                  style={"description_width": "initial"})
    sub_pct = widgets.HTML(layout=widgets.Layout(width="160px"))
    metrics = widgets.HTML()
    live = widgets.HTML()
    out = widgets.Output()
    state = {"sections": None, "running": False, "get_subs": (lambda: []), "rows": [], "zi": 0}

    def _subpanel(subs, sec_name):
        boxes = []
        for sub_name, sub_url in subs:
            cb = widgets.Checkbox(value=True, description=sub_name, indent=False,
                                  layout=widgets.Layout(width="auto", margin="0"))
            cb._payload = ((sec_name, sub_name), sub_url)
            boxes.append(cb)
        grid = widgets.VBox(boxes, layout=widgets.Layout(max_height="240px", overflow_y="auto",
                            border="1px solid #d0d0d0", padding="6px 10px", width="560px"))
        ball = widgets.Button(description="Todas", layout=widgets.Layout(width="90px"))
        bnone = widgets.Button(description="Ninguna", layout=widgets.Layout(width="100px"))
        ball.on_click(lambda _: [setattr(b, "value", True) for b in boxes])
        bnone.on_click(lambda _: [setattr(b, "value", False) for b in boxes])
        state["get_subs"] = lambda: [b._payload for b in boxes if b.value]
        return widgets.VBox([widgets.HBox([ball, bnone]), grid])

    def _on_sec(_=None):
        if not sec_dd.value:
            return
        name = sec_dd.label.split("  ·")[0]
        sub_box.children = [widgets.HTML("<b>Subcategorías:</b>"), _subpanel(sec_dd.value, name)]
        sub_box.layout.display = ""
        run_btn.disabled = False
    sec_dd.observe(_on_sec, "value")

    def _load(_b=None):
        load_btn.disabled = True
        with load_st:
            clear_output()
            display(HTML("<span class='sf-spin'></span>Cargando árbol de secciones (navegador, una vez)…"))
        try:
            secs = asyncio.run(eng.discover_sections())
        except Exception as e:
            with load_st:
                clear_output()
                print(f"❌ {e}")
            load_btn.disabled = False
            return
        state["sections"] = secs
        sec_dd.options = [(f"{n}  ·  {len(s)} subcat.", s) for n, s in secs if s]
        sec_dd.layout.display = ""
        if sec_dd.options:
            sec_dd.value = sec_dd.options[0][1]
        with load_st:
            clear_output()
            print(f"✓ {len(secs)} secciones.")
        load_btn.disabled = False
        _on_sec()
    load_btn.on_click(_load)

    def _start(_b):
        if state["running"]:
            return
        subs = state["get_subs"]()
        zones = get_zones()
        if not subs or not zones:
            with out:
                clear_output()
                print("⚠️ Falta subcategorías o zonas.")
            return
        state.update(running=True, rows=[], zi=0, zfail=0)
        run_btn.layout.display = "none"
        banner.value = _running_banner(widgets).value
        zone_bar.max = len(zones)
        zone_bar.value = 0
        zone_bar.description = f"Zonas 0/{len(zones)}"
        sub_bar.max = len(subs)
        sub_bar.value = 0
        with out:
            clear_output()
        t0 = _time.time()

        def _cb(ev):
            e = ev["event"]
            if e == "zone_start":
                state["zi"] += 1
                sub_bar.value = 0
                live.value = (f"<span class='sf-spin'></span>🗺️ Zona {state['zi']}/{len(zones)}: "
                              f"<b>{ev['store']['name']}</b> — fijando zona (handshake)…")
                metrics.value = _metrics_html(len(state["rows"]), _time.time() - t0)
            elif e == "subcat_start":
                sub_bar.max = ev["total"]
                live.value = (f"<span class='sf-spin'></span>🗂️ {ev['store']['name']} › "
                              f"<b>{ev['subcat']}</b> ({ev['idx']}/{ev['total']})")
            elif e == "subcat_page":
                live.value = (f"<span class='sf-spin'></span>🗂️ {ev['store']['name']} › "
                              f"{ev['subcat']} · pág {ev['page']} (+{ev['n_new']} SKU)")
                metrics.value = _metrics_html(len(state["rows"]), _time.time() - t0)
            elif e == "subcat_done":
                sub_bar.value = min(ev["idx"], sub_bar.max)
                sub_bar.description = f"Subcat {sub_bar.value}/{sub_bar.max}"
                sub_pct.value = (f"<span style='color:#555;font-size:.9em'>"
                                 f"{int(100*sub_bar.value/max(1,sub_bar.max))}%</span>")
                metrics.value = _metrics_html(len(state["rows"]), _time.time() - t0)
            elif e == "zone_done":
                zone_bar.value = min(zone_bar.value + 1, zone_bar.max)
                zone_bar.description = f"Zonas {zone_bar.value}/{zone_bar.max}"
                zone_pct.value = (f"<span style='color:#555;font-size:.9em'>"
                                  f"{int(100*zone_bar.value/max(1,zone_bar.max))}%</span>")
                if ev.get("zone_failed"):
                    state["zfail"] = state.get("zfail", 0) + 1
                    live.value = (f"<span style='color:#c0392b'>✗ {ev['store']['name']}: "
                                  f"no se pudo fijar la zona (saltada)</span>")
                metrics.value = _metrics_html(len(state["rows"]), _time.time() - t0)

        try:
            rows = asyncio.run(eng.scrape_sections(
                subs, zones, progress_cb=_cb, on_row=lambda r: state["rows"].append(r)))
            el = _time.time() - t0
            metrics.value = _metrics_html(len(rows), el)
            live.value = "<span style='color:#27ae60'>✓ Listo.</span>"
            if not rows:
                with out:
                    display(HTML("<div style='background:#fff4e0;border:1px solid #f0a020;padding:.8rem;"
                                 "border-radius:8px;'>⚠️ <b>0 productos</b> en la selección — no se generó archivo. "
                                 "Probá otra sección/subcategoría.{_zf}</div>".format(_zf=_zfail_note(state))))
                _telemetry("seccion", 0, el, "")
            else:
                ts = datetime.now().strftime("%Y-%m-%d_%H%M")
                outp = OUTPUT_DIR / f"SodimacFast_Seccion_{ts}.xlsx"
                eng.write_excel(rows, str(outp))
                with out:
                    display(HTML(f"<div style='background:#e8f5e9;border:1px solid #66bb6a;padding:.8rem;"
                                 f"border-radius:8px;'>✅ <b>{len(rows)}</b> filas en {_fmt_elapsed(el)} · "
                                 f"<code>{outp.name}</code>{_zfail_note(state)}</div>"))
                _telemetry("seccion", len(rows), el, outp.name)
                if IN_COLAB and outp.exists():
                    def _dl(_x=None, _p=str(outp)):
                        try:
                            colab_files.download(_p)
                        except Exception:
                            pass
                    _dl()
                    redl = widgets.Button(description="Descargar Excel de nuevo", icon="download",
                                          button_style="info", layout=widgets.Layout(width="260px"))
                    redl.on_click(_dl)
                    with out:
                        display(redl)
        except Exception as e:
            with out:
                display(HTML(f"<div style='background:#ffe4e4;border:1px solid #c0392b;padding:.8rem;"
                             f"border-radius:8px;'>❌ {e}</div>"))
                import traceback
                traceback.print_exc()
        finally:
            state["running"] = False
            banner.value = ""
            run_btn.layout.display = ""
    run_btn.on_click(_start)

    display(widgets.VBox([
        widgets.HTML("<b>1) Secciones</b>"), load_btn, load_st, sec_dd, sub_box,
        widgets.HTML("<b>2) Zonas</b>"), zbox,
        widgets.HTML("<b>3) Ejecutar</b>"), run_btn, banner,
        widgets.HBox([zone_bar, zone_pct], layout=widgets.Layout(align_items="center")),
        widgets.HBox([sub_bar, sub_pct], layout=widgets.Layout(align_items="center")),
        metrics, live, out, _watermark(widgets)]))
