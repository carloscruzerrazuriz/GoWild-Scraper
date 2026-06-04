# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""PCFactory — Section → Full detail.

Tercera herramienta del hub (`boot("pcfactory")` → "Section → Full detail").
Compone los dos engines: elegís una sección/subcategorías (como en Section
catalog), se juntan todos los productos y a CADA uno se le corre el extractor
profundo por SKU (engines/pcf_detalle) → mismo Excel multi-hoja.

UI EN INGLÉS (requerimiento del cliente). Como cada producto = 4 llamadas extra,
el flujo es en 2 pasos: primero CUENTA los productos (el listado es barato) y
muestra el estimado; recién al CONFIRMAR arranca la extracción profunda.
"""


def run():
    import time as _time
    import uuid as _uuid
    import os as _os
    from datetime import datetime
    from pathlib import Path
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output

    from engines import pcf_seccion as seccion
    from engines import pcf_detalle as detalle

    try:
        from google.colab import files as colab_files
        IN_COLAB = True
    except ImportError:
        colab_files = None
        IN_COLAB = False

    clear_output(wait=True)
    OUTPUT_DIR = Path.cwd()
    state = {"sections": None, "light_rows": None, "running": False}

    # ─── Telemetría ──────────────────────────────────────────────────────────
    _ACTIVITY_URL = "https://script.google.com/macros/s/AKfycbzALm18Xuw9c7U0tcAE0u1lPvq1j4P5kCxIJvdkDuG5MLVrqKyWd5qt-Kjb-TSP3B82/exec"
    _ACTIVITY_TOKEN = "6kT2hQjLp_VxR8mN3wYsZ-aF7bGdEcU4"
    _SESSION_ID = globals().get("_SESSION_ID") or _uuid.uuid4().hex[:8]
    globals()["_SESSION_ID"] = _SESSION_ID

    def _log_activity(n_skus=0, n_rows_output=0, runtime_s=0, output_file=""):
        try:
            import requests as _rq
            _rq.post(_ACTIVITY_URL, json={
                "token": _ACTIVITY_TOKEN, "session_id": _SESSION_ID, "colab": "pcfactory",
                "retailer": "pcfactory", "mode": "seccion_detalle", "n_skus": int(n_skus or 0),
                "n_stores": 0, "n_rows_output": int(n_rows_output or 0), "n_with_price": 0,
                "runtime_s": int(runtime_s or 0), "output_file": str(output_file or "")[:120],
                "user_hint": (_os.environ.get("COLAB_USER") or _os.environ.get("USER") or "")[:80],
                "colab_url": "",
            }, timeout=5, allow_redirects=True)
        except Exception:
            pass

    display(HTML("""
    <div style='background:linear-gradient(120deg,#1f5fbf,#3aa0e8);color:white;
    padding:1.1rem 1.5rem;border-radius:12px;margin-bottom:1rem;font-family:sans-serif;'>
      <h2 style='margin:0;color:white;'>🗂️🔍 PCFactory — Section → Full detail</h2>
      <p style='margin:.3rem 0 0;color:rgba(255,255,255,.92);font-size:.92rem;'>
        Pick a section and I'll pull the <b>full detail</b> of every product
        (prices, stock by store, specifications, images, video).
      </p>
    </div>
    <style>
    @keyframes pcfsd-spin {{ to {{ transform: rotate(360deg); }} }}
    .pcfsd-spinner{{display:inline-block;width:14px;height:14px;border:2px solid #1f5fbf;
      border-top-color:transparent;border-radius:50%;animation:pcfsd-spin .8s linear infinite;
      vertical-align:-3px;margin-right:8px;}}
    </style>"""))

    # ─── Checkbox panel ──────────────────────────────────────────────────────
    def _checkbox_panel(items, all_checked=True, height="300px", width="660px"):
        boxes = []
        for label, val in items:
            cb = widgets.Checkbox(value=all_checked, description=label, indent=False,
                                  layout=widgets.Layout(width="auto", margin="0"))
            cb._payload = val
            boxes.append(cb)
        list_box = widgets.VBox(boxes, layout=widgets.Layout(
            max_height=height, overflow_y="auto", border="1px solid #d0d0d0",
            padding="6px 10px", width=width))
        btn_all = widgets.Button(description="Select all", layout=widgets.Layout(width="120px"))
        btn_none = widgets.Button(description="Clear all", layout=widgets.Layout(width="120px"))
        btn_inv = widgets.Button(description="Invert", layout=widgets.Layout(width="100px"))
        counter = widgets.HTML()

        def refresh(*_):
            n = sum(1 for b in boxes if b.value)
            counter.value = (f"<span style='color:#555;font-size:.9em;'>"
                             f"{n} of {len(boxes)} selected</span>")
            _reset_to_count()
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

    # ─── Step 1: load sections ───────────────────────────────────────────────
    load_btn = widgets.Button(description="🔍 Load sections", button_style="info",
                              layout=widgets.Layout(width="220px"))
    load_status = widgets.Output()
    section_dd = widgets.Dropdown(description="Section:",
                                  layout=widgets.Layout(width="600px", display="none"),
                                  style={"description_width": "initial"})
    subcat_container = widgets.VBox(layout=widgets.Layout(display="none"))
    _get_subcats = [lambda: []]

    def on_section_change(_=None):
        if not section_dd.value:
            return
        seccion_nombre = section_dd.label.split("  ·")[0]
        subs = section_dd.value
        items = [(n, ((seccion_nombre, n), cid)) for n, cid in subs]
        panel, getter = _checkbox_panel(items, all_checked=True)
        _get_subcats[0] = getter
        subcat_container.children = [widgets.HTML("<b>Subcategories:</b>"), panel]
        subcat_container.layout.display = ""
        _reset_to_count()
    section_dd.observe(on_section_change, "value")

    def on_load(_b=None):
        load_btn.disabled = True
        with load_status:
            clear_output()
            display(HTML("<span class='pcfsd-spinner'></span>Loading sections…"))
        try:
            secs = seccion.discover_sections()
        except Exception as e:
            with load_status:
                clear_output(); print(f"❌ Error loading sections: {e}")
            load_btn.disabled = False
            return
        state["sections"] = secs
        section_dd.options = [(f"{n}  ·  {len(subs)} subcat.", subs) for n, subs in secs]
        section_dd.layout.display = ""
        if section_dd.options:
            section_dd.value = section_dd.options[0][1]
        with load_status:
            clear_output(); print(f"✓ {len(secs)} sections loaded.")
        load_btn.disabled = False
        on_section_change()
    load_btn.on_click(on_load)

    # ─── Options ─────────────────────────────────────────────────────────────
    img_toggle = widgets.Checkbox(
        value=False, indent=False,
        description="Embed main image in the Excel (heavier and slower)",
        layout=widgets.Layout(width="auto"))

    # ─── Step 2: count ───────────────────────────────────────────────────────
    count_btn = widgets.Button(description="🔢 Count products", button_style="warning",
                               disabled=True, layout=widgets.Layout(width="230px"))
    count_live = widgets.HTML()
    confirm_box = widgets.VBox(layout=widgets.Layout(display="none"))
    confirm_msg = widgets.HTML()
    confirm_btn = widgets.Button(description="✅ Confirm and extract details",
                                 button_style="success", layout=widgets.Layout(width="300px"))
    cancel_btn = widgets.Button(description="Cancel", layout=widgets.Layout(width="120px"))
    confirm_box.children = [confirm_msg,
                            widgets.HBox([confirm_btn, cancel_btn],
                                         layout=widgets.Layout(gap="8px"))]

    # ─── Step 3: extraction progress ─────────────────────────────────────────
    banner = widgets.HTML()
    bar = widgets.IntProgress(min=0, max=100, value=0, description="Products:",
                              bar_style="info", layout=widgets.Layout(width="540px"),
                              style={"description_width": "initial"})
    bar_pct = widgets.HTML(layout=widgets.Layout(width="180px"))
    live = widgets.HTML()
    result_out = widgets.Output()

    def _selected_subcats():
        return _get_subcats[0]()

    def _reset_to_count(*_):
        """Cualquier cambio de selección invalida el conteo previo."""
        state["light_rows"] = None
        confirm_box.layout.display = "none"
        count_live.value = ""
        n = len(_selected_subcats())
        count_btn.disabled = (n == 0)

    def _est_minutes(n):
        secs = max(2, round(n / 3))
        return f"{secs}s" if secs < 90 else f"~{round(secs/60)} min"

    def on_count(_b=None):
        if state["running"]:
            return
        subcats = _selected_subcats()
        if not subcats:
            return
        count_btn.disabled = True
        count_live.value = "<span class='pcfsd-spinner'></span>Counting products in the selection…"

        def _sec_progress(ev):
            if ev.get("event") == "subcat_page":
                count_live.value = (f"<span class='pcfsd-spinner'></span>Counting… "
                                    f"{ev.get('subcat','')} · {ev.get('n_rows',0)} in subcat")

        try:
            rows = seccion.scrape_section(subcats, progress_cb=_sec_progress)
        except Exception as e:
            count_live.value = f"<span style='color:#c0392b'>❌ Error counting: {e}</span>"
            count_btn.disabled = False
            return
        # Dedup por SKU (una sección puede repetir un producto en 2 subcats).
        seen, light = set(), []
        for r in rows:
            sku = str(r.get("SKU", "")).strip()
            if sku and sku not in seen:
                seen.add(sku)
                light.append(r)
        state["light_rows"] = light
        n = len(light)
        count_live.value = ""
        if n == 0:
            confirm_box.layout.display = "none"
            count_live.value = "<span style='color:#c0392b'>No products in the selection.</span>"
            count_btn.disabled = False
            return
        confirm_msg.value = (
            f"<div style='background:#fff4e0;border:1px solid #f0a020;padding:.8rem;"
            f"border-radius:8px;'>📦 The selection has <b>{n}</b> unique products.<br>"
            f"I'll extract the full detail of each one → ~<b>{4*n}</b> API calls, "
            f"<b>{_est_minutes(n)}</b> approx.<br>Confirm the deep extraction?</div>")
        confirm_box.layout.display = ""
        count_btn.disabled = False
    count_btn.on_click(on_count)

    def on_cancel(_b=None):
        confirm_box.layout.display = "none"
        state["light_rows"] = None
    cancel_btn.on_click(on_cancel)

    # ─── Deep extraction progress ────────────────────────────────────────────
    def _detail_progress(ev):
        e = ev.get("event")
        if e == "product":
            bar.max = ev.get("total", 1) or 1
            bar.value = min(ev.get("done", 0), bar.max)
            bar.description = f"Details {bar.value}/{bar.max}"
            bar_pct.value = (f"<span style='color:#555;font-size:.9em;margin-left:8px;'>"
                             f"{bar.value}/{bar.max} · "
                             f"{int(round(100*bar.value/max(1,bar.max)))}%</span>")
            mark = "✓" if ev.get("ok") else "✗"
            live.value = f"<span class='pcfsd-spinner'></span>{mark} SKU {ev.get('sku','')}…"
        elif e == "complete":
            live.value = "<span style='color:#27ae60'>✓ Extraction completed.</span>"

    def on_confirm(_b=None):
        if state["running"] or not state["light_rows"]:
            return
        state["running"] = True
        confirm_box.layout.display = "none"
        count_btn.disabled = True
        banner.value = ("<div style='background:linear-gradient(90deg,#ffb84d,#f0a020);"
                        "color:#3a2400;padding:.7rem 1rem;border-radius:8px;font-weight:600;'>"
                        "<span class='pcfsd-spinner'></span>Working — don't close the cell</div>")
        with result_out:
            clear_output()
        bar.value = 0
        with_images = bool(img_toggle.value)
        skus = [(r["SKU"], r.get("Product Name", "")) for r in state["light_rows"]]
        ts = datetime.now().strftime("%Y-%m-%d_%H%M")
        t0 = _time.time()
        try:
            data = detalle.scrape_skus(skus, progress_cb=_detail_progress)
            if with_images:
                with result_out:
                    display(HTML("<span class='pcfsd-spinner'></span>Downloading and embedding "
                                 "images… (may take a while)"))
            out = OUTPUT_DIR / f"PCFactory_Section_Details_{ts}.xlsx"
            detalle.write_excel(data, str(out), with_images=with_images)
            nf = data.get("notfound") or []
            nf_html = (f"<br>⚠️ Not found ({len(nf)}): <code>{', '.join(map(str, nf[:30]))}</code>"
                       if nf else "")
            with result_out:
                display(HTML(
                    f"<div style='background:#e8f5e9;border:1px solid #66bb6a;padding:.9rem;"
                    f"border-radius:8px;'>✅ <b>Done.</b> {len(data['productos'])} products · "
                    f"{len(data['especificaciones'])} specs · {len(data['stock'])} stock rows · "
                    f"{len(data['imagenes'])} images.<br>📄 File: <code>{out.name}</code>"
                    f"{nf_html}</div>"))
            _log_activity(n_skus=len(skus), n_rows_output=len(data["productos"]),
                          runtime_s=int(_time.time() - t0), output_file=out.name)
            if IN_COLAB:
                try:
                    colab_files.download(str(out))
                except Exception:
                    pass
                redl = widgets.Button(description="Download Excel again", icon="download",
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
            count_btn.disabled = False
    confirm_btn.on_click(on_confirm)

    watermark = widgets.HTML(
        "<div style='margin-top:1.2rem;padding-top:.6rem;border-top:1px solid #ddd;"
        "color:#999;font-size:.8em;font-family:sans-serif;'>"
        "🖥️ PCFactory — Carlos Cruz E.<br>"
        "<span style='font-size:.92em;'>Copyright (c) 2026 Carlos Cruz Errazuriz · "
        "All rights reserved · Proprietary — No unauthorized use or distribution</span></div>")

    step1 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.3rem 0;'>📂 Step 1 — Sections</h4>"),
        load_btn, load_status, section_dd, subcat_container])
    options_box = widgets.VBox([
        widgets.HTML("<h4 style='margin:.6rem 0 .3rem;'>⚙️ Options</h4>"), img_toggle])
    step2 = widgets.VBox([
        options_box,
        widgets.HTML("<h4 style='margin:.6rem 0 .3rem;'>🔢 Step 2 — Count and confirm</h4>"),
        count_btn, count_live, confirm_box, banner,
        widgets.HBox([bar, bar_pct], layout=widgets.Layout(align_items="center")),
        live, result_out])
    display(widgets.VBox([step1, step2, watermark]))
