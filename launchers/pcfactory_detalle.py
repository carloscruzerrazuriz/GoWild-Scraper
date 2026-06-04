# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""PCFactory — Full detail by SKU (UI ipywidgets para Colab).

Se llega desde el hub (`boot("pcfactory")` → "Full detail by SKU"). Al estilo del
MK7: el usuario sube un Excel con SKU (+ Desc. opcional) — o los pega — y la
herramienta entra al detalle de cada producto vía API y extrae TODO. UI EN INGLÉS
(requerimiento del cliente). Salida = workbook multi-hoja. Ver engines/pcf_detalle.
"""


def run():
    import io
    import time as _time
    import uuid as _uuid
    import os as _os
    from datetime import datetime
    from pathlib import Path
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output

    from engines import pcf_detalle as eng

    try:
        from google.colab import files as colab_files
        IN_COLAB = True
    except ImportError:
        colab_files = None
        IN_COLAB = False

    clear_output(wait=True)
    OUTPUT_DIR = Path.cwd()
    state = {"skus": [], "output_path": None, "running": False}

    # ─── Telemetría (mismo Manifest que el resto del proyecto) ──────────────
    _ACTIVITY_URL = "https://script.google.com/macros/s/AKfycbzALm18Xuw9c7U0tcAE0u1lPvq1j4P5kCxIJvdkDuG5MLVrqKyWd5qt-Kjb-TSP3B82/exec"
    _ACTIVITY_TOKEN = "6kT2hQjLp_VxR8mN3wYsZ-aF7bGdEcU4"
    _SESSION_ID = globals().get("_SESSION_ID") or _uuid.uuid4().hex[:8]
    globals()["_SESSION_ID"] = _SESSION_ID

    def _log_activity(n_skus=0, n_rows_output=0, runtime_s=0, output_file=""):
        try:
            import requests as _rq
            _rq.post(_ACTIVITY_URL, json={
                "token": _ACTIVITY_TOKEN, "session_id": _SESSION_ID, "colab": "pcfactory",
                "retailer": "pcfactory", "mode": "detalle", "n_skus": int(n_skus or 0),
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
      <h2 style='margin:0;color:white;'>🔍 PCFactory — Full detail by SKU</h2>
      <p style='margin:.3rem 0 0;color:rgba(255,255,255,.92);font-size:.92rem;'>
        Upload (or paste) a SKU list and I'll pull <b>everything</b> for each product:
        prices, stock by store, specifications, images and video.
      </p>
    </div>
    <style>
    @keyframes pcfd-spin {{ to {{ transform: rotate(360deg); }} }}
    .pcfd-spinner{{display:inline-block;width:14px;height:14px;border:2px solid #1f5fbf;
      border-top-color:transparent;border-radius:50%;animation:pcfd-spin .8s linear infinite;
      vertical-align:-3px;margin-right:8px;}}
    </style>"""))

    # ─── Parseo de entrada (acepta cabeceras en inglés o español) ────────────
    def _parse_pasted(text):
        """SKUs pegados (coma / espacio / línea) → [(sku, ''), ...]."""
        import re
        toks = [t for t in re.split(r"[\s,;]+", text or "") if t.strip()]
        return [(t.strip(), "") for t in toks]

    def _parse_xlsx(content):
        """Lee un .xlsx y detecta columna de SKU (+ Desc. opcional). → [(sku, desc), ...]."""
        import pandas as pd
        df = pd.read_excel(io.BytesIO(content), dtype=str)
        low = {str(c).lower().strip(): c for c in df.columns}

        def _find(keys):
            for k, orig in low.items():
                if any(t in k for t in keys):
                    return orig
            return None
        sku_col = (_find(["sku pcfactory", "sku", "codigo", "código", "id"])
                   or (df.columns[0] if len(df.columns) else None))
        desc_col = _find(["desc", "name", "nombre", "producto", "product"])
        out = []
        if sku_col is None:
            return out
        for _, row in df.iterrows():
            sku = str(row[sku_col]).strip()
            if not sku or sku.lower() == "nan":
                continue
            desc = ""
            if desc_col is not None:
                d = str(row[desc_col]).strip()
                desc = "" if d.lower() == "nan" else d
            out.append((sku, desc))
        return out

    upload = widgets.FileUpload(accept=".xlsx", multiple=False,
                               description="Upload SKU Excel")
    paste = widgets.Textarea(
        placeholder="…or paste the SKUs here (comma, space or newline separated). e.g. 55320, 56743, 27776",
        layout=widgets.Layout(width="660px", height="80px"))
    parse_status = widgets.HTML()

    def _gather_skus():
        skus = []
        # 1) Uploaded Excel
        try:
            up = upload.value
            content = None
            if up:
                if isinstance(up, dict):           # ipywidgets <8
                    item = next(iter(up.values()))
                    content = item["content"]
                else:                                # ipywidgets >=8 (tuple)
                    content = up[0]["content"]
                if hasattr(content, "tobytes"):
                    content = content.tobytes()
            if content:
                skus += _parse_xlsx(content)
        except Exception as e:
            parse_status.value = (f"<span style='color:#c0392b'>⚠️ Couldn't read the "
                                  f"Excel: {e}</span>")
        # 2) Pasted
        skus += _parse_pasted(paste.value)
        return skus

    def _refresh_count(*_):
        skus = _gather_skus()
        state["skus"] = skus
        n = len({str(s).strip() for s, _ in skus if str(s).strip()})
        if n:
            parse_status.value = (f"<div style='background:#eaf3fc;border:1px solid #aacdf0;"
                                  f"padding:.5rem;border-radius:6px;'>📋 <b>{n}</b> unique SKUs "
                                  f"detected.</div>")
            run_btn.disabled = False
        else:
            parse_status.value = ""
            run_btn.disabled = True
    upload.observe(_refresh_count, "value")
    paste.observe(_refresh_count, "value")

    # ─── Options ─────────────────────────────────────────────────────────────
    img_toggle = widgets.Checkbox(
        value=False, indent=False,
        description="Embed main image in the Excel (heavier and slower)",
        layout=widgets.Layout(width="auto"))

    # ─── Run ─────────────────────────────────────────────────────────────────
    run_btn = widgets.Button(description="🚀 Extract details", button_style="success",
                             disabled=True, layout=widgets.Layout(width="230px"))
    banner = widgets.HTML()
    bar = widgets.IntProgress(min=0, max=100, value=0, description="Products:",
                              bar_style="info", layout=widgets.Layout(width="540px"),
                              style={"description_width": "initial"})
    bar_pct = widgets.HTML(layout=widgets.Layout(width="180px"))
    live = widgets.HTML()
    result_out = widgets.Output()

    def _progress(ev):
        e = ev.get("event")
        if e == "product":
            bar.max = ev.get("total", 1) or 1
            bar.value = min(ev.get("done", 0), bar.max)
            bar.description = f"Products {bar.value}/{bar.max}"
            mark = "✓" if ev.get("ok") else "✗"
            bar_pct.value = (f"<span style='color:#555;font-size:.9em;margin-left:8px;'>"
                             f"{bar.value}/{bar.max} · "
                             f"{int(round(100*bar.value/max(1,bar.max)))}%</span>")
            live.value = (f"<span class='pcfd-spinner'></span>{mark} SKU {ev.get('sku','')}…")
        elif e == "complete":
            live.value = "<span style='color:#27ae60'>✓ Extraction completed.</span>"

    def _start(_b):
        if state["running"]:
            return
        skus = _gather_skus()
        if not skus:
            return
        state["running"] = True
        run_btn.layout.display = "none"
        banner.value = ("<div style='background:linear-gradient(90deg,#ffb84d,#f0a020);"
                        "color:#3a2400;padding:.7rem 1rem;border-radius:8px;font-weight:600;'>"
                        "<span class='pcfd-spinner'></span>Working — don't close the cell</div>")
        with result_out:
            clear_output()
        bar.value = 0
        with_images = bool(img_toggle.value)
        ts = datetime.now().strftime("%Y-%m-%d_%H%M")
        t0 = _time.time()
        try:
            data = eng.scrape_skus(skus, progress_cb=_progress)
            if with_images:
                with result_out:
                    display(HTML("<span class='pcfd-spinner'></span>Downloading and embedding "
                                 "images… (may take a while)"))
            out = OUTPUT_DIR / f"PCFactory_Details_{ts}.xlsx"
            eng.write_excel(data, str(out), with_images=with_images)
            state["output_path"] = out
            nf = data.get("notfound") or []
            nf_html = ""
            if nf:
                nf_html = (f"<br>⚠️ Not found ({len(nf)}): "
                           f"<code>{', '.join(map(str, nf[:30]))}</code>")
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
            run_btn.layout.display = ""
    run_btn.on_click(_start)

    watermark = widgets.HTML(
        "<div style='margin-top:1.2rem;padding-top:.6rem;border-top:1px solid #ddd;"
        "color:#999;font-size:.8em;font-family:sans-serif;'>"
        "🖥️ PCFactory — Carlos Cruz E.<br>"
        "<span style='font-size:.92em;'>Copyright (c) 2026 Carlos Cruz Errazuriz · "
        "All rights reserved · Proprietary — No unauthorized use or distribution</span></div>")

    step1 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.3rem 0;'>📂 Step 1 — SKU list</h4>"),
        widgets.HTML("<span style='font-size:.9em;color:#555;'>Upload an Excel with a "
                     "SKU column (and optional Description), or paste the SKUs below.</span>"),
        upload, paste, parse_status])
    options_box = widgets.VBox([
        widgets.HTML("<h4 style='margin:.6rem 0 .3rem;'>⚙️ Options</h4>"), img_toggle])
    step2 = widgets.VBox([
        options_box,
        widgets.HTML("<h4 style='margin:.6rem 0 .3rem;'>🚀 Step 2 — Run</h4>"),
        run_btn, banner,
        widgets.HBox([bar, bar_pct], layout=widgets.Layout(align_items="center")),
        live, result_out])
    display(widgets.VBox([step1, step2, watermark]))
