# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Ferni — Buscador de Puertas Sodimac por SKU (resuelve el selector de medidas).

Invocado desde el notebook Buscador_Puertas_Sodimac.ipynb vía
`from launchers import boot; boot("ferni")`.

A diferencia del MK7 (que extrae del DOM de la card y para puertas devuelve solo
un rango "desde $X"), Ferni parsea el array `variants[]` del __NEXT_DATA__ y
resuelve la medida y el precio EXACTOS de cada SKU. Ver engines/ferni_sodimac.py.
"""
from engines import ferni_sodimac as _eng

ALL_STORES        = _eng.ALL_STORES
search_doors      = _eng.search_doors
write_output      = _eng.write_output


def run():
    import asyncio, re, uuid as _uuid
    from datetime import datetime
    from pathlib import Path
    import nest_asyncio
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output
    import pandas as pd

    nest_asyncio.apply()
    clear_output(wait=True)

    try:
        from google.colab import files as colab_files
        IN_COLAB = True
    except ImportError:
        colab_files = None
        IN_COLAB = False

    OUTPUT_DIR = Path.cwd()

    # ─── Telemetría: log al System Manifest (igual que los otros tools) ──
    _ACTIVITY_URL = "https://script.google.com/macros/s/AKfycbzALm18Xuw9c7U0tcAE0u1lPvq1j4P5kCxIJvdkDuG5MLVrqKyWd5qt-Kjb-TSP3B82/exec"
    _ACTIVITY_TOKEN = "6kT2hQjLp_VxR8mN3wYsZ-aF7bGdEcU4"
    _COLAB_TAG = "ferni"
    _SESSION_ID = globals().get("_SESSION_ID") or _uuid.uuid4().hex[:8]
    globals()["_SESSION_ID"] = _SESSION_ID

    def _user_hint():
        try:
            import os as _os
            for k in ("COLAB_USER", "USER", "JUPYTERHUB_USER"):
                v = _os.environ.get(k)
                if v:
                    return v
        except Exception:
            pass
        return ""

    def _log_activity(mode="", n_skus=0, n_stores=0, n_rows_output=0,
                      n_with_price=0, runtime_s=0, output_file=""):
        try:
            import requests as _rq
            _rq.post(_ACTIVITY_URL, json={
                "token": _ACTIVITY_TOKEN, "session_id": _SESSION_ID,
                "colab": _COLAB_TAG, "retailer": "sodimac",
                "mode": str(mode or "")[:30],
                "n_skus": int(n_skus or 0), "n_stores": int(n_stores or 0),
                "n_rows_output": int(n_rows_output or 0),
                "n_with_price": int(n_with_price or 0),
                "runtime_s": int(runtime_s or 0),
                "output_file": str(output_file or "")[:120],
                "user_hint": _user_hint()[:80], "colab_url": "",
            }, timeout=5, allow_redirects=True)
        except Exception:
            pass

    ALL_ST = ALL_STORES
    state = {
        "input_df": None, "sku_col": None, "easy_col": None, "desc_col": None,
        "skus_list": None, "selected_stores": [], "rows": [], "matches": [],
        "output_path": None, "running": False,
    }

    # ─── Header + animaciones ──────────────────────────────────────────
    display(HTML("""
    <div style='background:linear-gradient(120deg,#5d4037,#8d6e63);color:white;
    padding:1.2rem 1.5rem;border-radius:12px;margin-bottom:1rem;font-family:sans-serif;'>
      <h2 style='margin:0;color:white;'>🚪 Ferni — Buscador de Puertas Sodimac</h2>
      <p style='margin:.3rem 0 0;color:rgba(255,255,255,.92);font-size:.95rem;'>
        Sube un Excel con SKUs de puertas y obtené la <b>medida</b> y el
        <b>precio exacto</b> de cada una — resuelto desde el selector de medidas.
      </p>
    </div>
    <style>
    @keyframes fn-spin { to { transform: rotate(360deg); } }
    @keyframes fn-pulse { 0%,100%{opacity:1} 50%{opacity:.55} }
    .fn-spinner{display:inline-block;width:14px;height:14px;border:2px solid #8d6e63;
      border-top-color:transparent;border-radius:50%;animation:fn-spin .8s linear infinite;
      vertical-align:-3px;margin-right:8px;}
    .fn-banner-running{background:linear-gradient(90deg,#ffb84d,#f0a020);color:#3a2400;
      padding:.7rem 1rem;border-radius:8px;font-family:sans-serif;font-weight:600;
      animation:fn-pulse 1.6s ease-in-out infinite;margin:.5rem 0;}
    </style>
    """))

    # ─── Template de carga embebido (SKU Easy, Desc. Producto, SKU Sodimac) ──
    def _download_formato(_btn):
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active; ws.title = "Carga"
        ws.append(["SKU Easy", "Desc. Producto", "SKU Sodimac"])
        ws.append(["", "Puerta terciada carpintera 90x200 (ejemplo)", "139566229"])
        ws.append(["", "Puerta MDF Milano 60x200 (ejemplo)", "120822458"])
        for row in ws.iter_rows(min_row=2, min_col=3, max_col=3):
            for cell in row:
                cell.number_format = "@"
        path = OUTPUT_DIR / "formato_carga_puertas.xlsx"
        wb.save(path)
        if IN_COLAB:
            try:
                colab_files.download(str(path))
            except Exception:
                print("📁 Guardado en ./" + path.name)
        else:
            print("📁 Guardado en", path)

    download_format_btn = widgets.Button(
        description="📥 Descargar formato de carga (Excel)",
        icon="download", button_style="info",
        layout=widgets.Layout(width="320px"))
    download_format_btn.on_click(_download_formato)

    # ─── Paso 1: Upload + detección de columna SKU ─────────────────────
    upload_w = widgets.FileUpload(accept=".xlsx,.xls,.csv", multiple=False,
                                  description="📤 Subir Excel/CSV")
    upload_status = widgets.HTML("<span style='color:#888;'>Sin archivo cargado.</span>")
    preview_out = widgets.Output()

    SKU_ALIASES = ["SKU Sodimac", "SKU Sodimac ", "sku sodimac", "SKU Producto", "SKU"]
    EASY_ALIASES = ["SKU Easy", "sku easy", "Cód. Easy", "Codigo Easy", "Cod Easy"]
    DESC_ALIASES = ["Desc. Producto", "Desc Producto", "Descripción", "Descripcion",
                    "Descripción Producto", "Descripcion Producto"]

    def _find_col(df_cols, aliases):
        cols_lower = {str(c).lower().strip(): c for c in df_cols}
        for a in aliases:
            if a.lower().strip() in cols_lower:
                return cols_lower[a.lower().strip()]
        return None

    def _on_upload(change):
        if not upload_w.value:
            return
        raw = upload_w.value
        if isinstance(raw, dict):
            item = next(iter(raw.values()))
            name, content = item["metadata"]["name"], item["content"]
        else:
            item = raw[0]
            name = item["name"] if isinstance(item, dict) else item.name
            c = item["content"] if isinstance(item, dict) else item.content
            content = c.tobytes() if hasattr(c, "tobytes") else c
        in_path = OUTPUT_DIR / name
        in_path.write_bytes(content)
        try:
            if in_path.suffix.lower() in (".csv", ".tsv"):
                df = pd.read_csv(in_path, dtype=str)
            else:
                df = pd.read_excel(in_path, dtype=str)
        except Exception as e:
            upload_status.value = f"<span style='color:#c0392b'>❌ Error leyendo: {e}</span>"
            return
        df.columns = [str(c).strip() for c in df.columns]
        sku_col = _find_col(df.columns, SKU_ALIASES)
        if not sku_col:
            upload_status.value = (
                "<div style='background:#fff3cd;border:1px solid #ffc107;padding:.7rem;border-radius:6px;'>"
                "⚠️ <b>No encontré columna de SKU.</b> Esperaba <code>SKU Sodimac</code> con valores.</div>")
            stores_container.layout.display = "none"
            run_container.layout.display = "none"
            return
        easy_col = _find_col(df.columns, EASY_ALIASES)
        desc_col = _find_col(df.columns, DESC_ALIASES)

        df_filt = df[df[sku_col].notna()].copy()
        df_filt[sku_col] = df_filt[sku_col].astype(str).str.strip()
        df_filt = df_filt[df_filt[sku_col] != ""]
        df_filt = df_filt[~df_filt[sku_col].str.lower().isin(["nan", "none", "por definir"])]

        skus, seen = [], set()
        for _, r in df_filt.iterrows():
            sku = str(r[sku_col]).strip()
            if re.fullmatch(r"\d+\.0+", sku):
                sku = sku.split(".")[0]
            if not sku or sku in seen:
                continue
            seen.add(sku)
            skus.append(sku)

        state.update(input_df=df_filt, sku_col=sku_col, easy_col=easy_col,
                     desc_col=desc_col, skus_list=skus)

        upload_status.value = (
            f"<div style='background:#e8f5e9;border:1px solid #66bb6a;padding:.8rem;border-radius:6px;'>"
            f"✓ <b>{name}</b> · {len(df_filt)} filas con SKUs · <b>{len(skus)} únicos</b> "
            f"<span style='color:#666;'>(col <code>{sku_col}</code>)</span></div>")
        with preview_out:
            clear_output()
            display(df_filt.head(8))

        stores_container.layout.display = ""
        run_container.layout.display = ""
        _update_run_summary()
        run_btn.disabled = False

    upload_w.observe(_on_upload, names="value")

    step1 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.3rem 0;'>📂 Paso 1 — Archivo de SKUs de puertas</h4>"),
        widgets.HTML(
            "<div style='background:#efebe9;border:1px solid #bcaaa4;padding:.5rem;"
            "border-radius:6px;margin:.3rem 0;font-size:.9em;'>"
            "💡 Completá la columna <code>SKU Sodimac</code> con los SKU de las "
            "<b>medidas específicas</b> de las puertas. <code>SKU Easy</code> y "
            "<code>Desc. Producto</code> son opcionales.</div>"),
        download_format_btn,
        widgets.HTML("<hr style='margin:.6rem 0;'>"),
        upload_w, upload_status, preview_out,
    ])

    # ─── Paso 2: Zonas (presets como MK7) ──────────────────────────────
    stores_container = widgets.VBox(layout=widgets.Layout(display="none"))

    def _checkbox_panel(items, height="240px"):
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

    preset_radio = widgets.RadioButtons(
        options=list(presets.keys()), value=list(presets.keys())[0],
        description="Preset:", style={"description_width": "initial"},
        layout=widgets.Layout(width="auto"))
    store_panel, _get_custom, _store_boxes = _checkbox_panel([(labeler(s), s) for s in ALL_ST])
    store_panel_wrap = widgets.VBox([store_panel], layout=widgets.Layout(display="none"))
    store_eta = widgets.HTML()

    def _update_stores(*_):
        preset = presets[preset_radio.value]
        if preset is None:
            store_panel_wrap.layout.display = ""
            sel = _get_custom()
            state["selected_stores"] = sel if sel else [s for s in ALL_ST if s["id"] == "E522"]
        else:
            store_panel_wrap.layout.display = "none"
            state["selected_stores"] = preset
        n = len(state["selected_stores"])
        store_eta.value = (
            "<span style='color:#c0392b'>⚠️ Seleccioná al menos 1</span>" if n == 0
            else f"<span style='color:#27ae60'>✓ {n} tienda(s) seleccionada(s)</span>")
        _update_run_summary()

    preset_radio.observe(_update_stores, "value")
    for b in _store_boxes:
        b.observe(_update_stores, "value")
    _update_stores()

    stores_container.children = [
        widgets.HTML("<h4 style='margin:.6rem 0 .3rem;'>📍 Paso 2 — Tiendas</h4>"),
        preset_radio, store_panel_wrap, store_eta,
    ]

    # ─── Paso 3: Run ───────────────────────────────────────────────────
    run_container = widgets.VBox(layout=widgets.Layout(display="none"))
    run_btn = widgets.Button(description="🚀 Iniciar búsqueda", button_style="success",
                             disabled=True, layout=widgets.Layout(width="220px"))
    running_banner = widgets.HTML()
    store_bar = widgets.IntProgress(min=0, max=100, value=0, description="Tiendas:",
                                    bar_style="info", layout=widgets.Layout(width="540px"),
                                    style={"description_width": "initial"})
    store_pct = widgets.HTML(layout=widgets.Layout(width="140px"))
    sku_bar = widgets.IntProgress(min=0, max=100, value=0, description="Lotes:",
                                  bar_style="info", layout=widgets.Layout(width="540px"),
                                  style={"description_width": "initial"})
    sku_pct = widgets.HTML(layout=widgets.Layout(width="140px"))
    live_status = widgets.HTML()
    live_metrics = widgets.HTML()
    result_out = widgets.Output()
    run_summary = widgets.HTML()

    def _set_pct(w, v, t):
        if not t:
            w.value = ""; return
        p = int(round(100 * v / t))
        w.value = f"<span style='color:#555;font-size:.9em;margin-left:8px;'>{v}/{t} · {p}%</span>"

    def _update_run_summary(*_):
        n_st = len(state.get("selected_stores", []))
        n_sk = len(state.get("skus_list") or [])
        if n_st == 0 or n_sk == 0:
            run_summary.value = ""; return
        run_summary.value = (
            f"<div style='background:#f0f7ff;border:1px solid #bcdcff;padding:.6rem;"
            f"border-radius:6px;margin:.4rem 0;font-size:.95em;'>"
            f"📋 Vas a buscar <b>{n_sk}</b> puerta(s) en <b>{n_st}</b> tienda(s) "
            f"= <b>{n_st * n_sk}</b> filas.</div>")

    _T0 = [None]
    _zone_idx = [0]

    def _fmt_time(s):
        s = int(s); m, s = divmod(s, 60); h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _progress(event):
        import time as _t
        ev = event.get("event")
        st = event.get("store") or {}
        sn = st.get("name", "?")
        n_st = len(state["selected_stores"])
        if _T0[0] is None and ev != "browser_launching":
            _T0[0] = _t.time()
        if ev == "browser_launching":
            _T0[0] = _t.time(); _zone_idx[0] = 0
            live_status.value = "<span class='fn-spinner'></span>🚀 Lanzando Chromium…"
        elif ev == "browser_ready":
            live_status.value = "<span class='fn-spinner'></span>✓ Chromium listo. Comenzando…"
        elif ev == "browser_error":
            live_status.value = f"<span style='color:#c0392b'>✗ Error Chromium: {event.get('msg','')}</span>"
        elif ev == "warmup_start":
            live_status.value = f"<span class='fn-spinner'></span>⏳ {sn} · calentando sesión (anti-bot, ~6s)…"
        elif ev == "warmup_done":
            live_status.value = f"<span class='fn-spinner'></span>🔧 {sn} · seteando zona…"
        elif ev == "batch_done":
            done = event.get("batches_done_in_zone", 1)
            total = event.get("total_batches_in_zone", 1)
            found = event.get("found_in_batch", 0)
            live_status.value = (f"<span class='fn-spinner'></span>🔍 {sn} · "
                                 f"lote {done}/{total} → {found} puertas")
            sku_bar.max = total; sku_bar.value = done
            _set_pct(sku_pct, done, total)
        elif ev == "zone_end":
            _zone_idx[0] += 1
            failed = event.get("zone_failed", False)
            found = event.get("found_in_zone", 0)
            if failed:
                live_status.value = f"<span style='color:#c0392b'>✗ {sn} · falló set_zone</span>"
            else:
                live_status.value = f"<span style='color:#27ae60'>✓ {sn} · {found} puertas</span>"
            store_bar.max = n_st; store_bar.value = _zone_idx[0]
            _set_pct(store_pct, _zone_idx[0], n_st)
            sku_bar.value = 0
            elapsed = _t.time() - (_T0[0] or _t.time())
            parts = [f"<b>🧮 Filas:</b> {len(state['rows'])}", f"<b>⏱</b> {_fmt_time(elapsed)}"]
            if _zone_idx[0] >= 1:
                per = elapsed / _zone_idx[0]
                rem = (n_st - _zone_idx[0]) * per
                if rem > 0:
                    parts.append(f"<b>ETA:</b> ~{_fmt_time(rem)}")
            live_metrics.value = " · ".join(parts)
        elif ev == "complete":
            live_status.value = "<span style='color:#27ae60'>✓ Búsqueda completada.</span>"

    def _on_match(row):
        state["rows"].append(row)

    async def _run_pipeline():
        state["rows"] = []
        state["matches"] = []
        ts = datetime.now().strftime("%Y-%m-%d_%H%M")
        skus = state["skus_list"]
        stores = list(state["selected_stores"])

        matches = await search_doors(
            skus, stores, headless=True,
            progress_cb=_progress, on_match=_on_match)
        state["matches"] = matches

        out = OUTPUT_DIR / f"Puertas_Sodimac_Ferni_{ts}.xlsx"
        write_output(
            state["input_df"], state["desc_col"], state["sku_col"], state["easy_col"],
            matches, str(out), stores=stores,
            image_dir=str(OUTPUT_DIR / "_ferni_imgs"))
        state["output_path"] = out
        return out, matches

    def _on_run(_btn):
        import time as _t
        if state["running"]:
            return
        if not state.get("skus_list") or not state.get("selected_stores"):
            return
        state["running"] = True
        run_btn.layout.display = "none"
        running_banner.value = ("<div class='fn-banner-running'><span class='fn-spinner'></span>"
                                "Trabajando — no cierres esta pestaña ni la celda</div>")
        with result_out:
            clear_output()
        _t0 = _t.time()
        try:
            out, matches = asyncio.get_event_loop().run_until_complete(_run_pipeline())
            n_found = len({m.get("sku_input") for m in matches})
            n_total = len(state["skus_list"])
            n_with_price = sum(1 for m in matches if m.get("precio_internet"))
            with result_out:
                display(HTML(
                    f"<div style='background:#e8f5e9;border:1px solid #66bb6a;padding:.9rem;"
                    f"border-radius:8px;'>✅ <b>Listo.</b> {len(matches)} filas · "
                    f"<b>{n_found}/{n_total}</b> puertas encontradas.<br>"
                    f"📄 Archivo: <code>{out.name}</code></div>"))
            _log_activity(mode="puertas", n_skus=n_total,
                          n_stores=len(state["selected_stores"]),
                          n_rows_output=len(matches), n_with_price=n_with_price,
                          runtime_s=int(_t.time() - _t0), output_file=out.name)
            if IN_COLAB:
                try:
                    colab_files.download(str(out))
                except Exception:
                    pass
                redl = widgets.Button(description="Descargar Excel de nuevo", icon="download",
                                      button_style="info", layout=widgets.Layout(width="260px"))
                redl.on_click(lambda _b: colab_files.download(str(out)))
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
            run_btn.disabled = False

    run_btn.on_click(_on_run)
    run_container.children = [
        widgets.HTML("<h4 style='margin:.6rem 0 .3rem;'>🚀 Paso 3 — Ejecutar</h4>"),
        run_summary, run_btn, running_banner,
        widgets.HBox([store_bar, store_pct]),
        widgets.HBox([sku_bar, sku_pct]),
        live_status, live_metrics, result_out,
    ]

    # ─── Watermark ─────────────────────────────────────────────────────
    watermark = widgets.HTML(
        "<div style='margin-top:1.2rem;padding-top:.6rem;border-top:1px solid #ddd;"
        "color:#999;font-size:.8em;font-family:sans-serif;'>"
        "🚪 Ferni — Carlos Cruz E.<br>"
        "<span style='font-size:.92em;'>Copyright (c) 2026 Carlos Cruz Errazuriz · "
        "All rights reserved · Proprietary — No unauthorized use or distribution</span></div>")

    display(widgets.VBox([step1, stores_container, run_container, watermark]))
