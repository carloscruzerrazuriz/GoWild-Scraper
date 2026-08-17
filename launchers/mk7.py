# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""MK7 — Buscador unificado de SKUs (Sodimac · Falabella · Construmart).

Invocado desde el notebook MK7.ipynb vía `from launchers import boot; boot("mk7")`.
"""
from engines import sodimac_engine as _so
from engines import falabella_engine as _fa
from engines import construmart_engine as _co

# Exponer nombres con sufijo de retailer (lo que espera el cuerpo de la UI)
ALL_STORES_SODIMAC               = _so.ALL_STORES
search_skus_mk6_sodimac          = _so.search_skus_mk6
write_output_sodimac             = _so.write_output

ALL_STORES_FALABELLA             = _fa.ALL_STORES
search_skus_falabella            = _fa.search_skus
write_output_falabella           = _fa.write_output

STATIC_STORES_CONSTRUMART        = _co.STATIC_STORES
search_skus_construmart          = _co.search_skus
write_output_construmart         = _co.write_output
discover_stores_construmart      = _co.discover_stores
sodimac_equivalent_construmart   = _co.sodimac_equivalent


def run():
    from IPython.display import clear_output
    clear_output(wait=True)

    # === MK7 — Buscador unificado de SKUs (Sodimac + Falabella + Construmart) ===
    import asyncio, re, base64, time as _time, hashlib as _hl, json as _json
    from datetime import datetime
    from pathlib import Path
    import nest_asyncio
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output
    import pandas as pd
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    nest_asyncio.apply()


    try:
        from google.colab import files as colab_files
        IN_COLAB = True
    except ImportError:
        IN_COLAB = False

    OUTPUT_DIR = Path.cwd()

    # ─── Telemetry: log activity al Sheet ──────────────────────────────
    import uuid as _uuid
    _ACTIVITY_URL = "https://script.google.com/macros/s/AKfycbzALm18Xuw9c7U0tcAE0u1lPvq1j4P5kCxIJvdkDuG5MLVrqKyWd5qt-Kjb-TSP3B82/exec"
    _ACTIVITY_TOKEN = "6kT2hQjLp_VxR8mN3wYsZ-aF7bGdEcU4"
    _BUILD_HASH = "5c4dba0ea3acb1375cdffccab4d63aad371fe0124f0b915fe6e05dd30d3f0577"
    _COLAB_TAG = "mk7"
    _SESSION_ID = globals().get("_SESSION_ID") or _uuid.uuid4().hex[:8]
    globals()["_SESSION_ID"] = _SESSION_ID

    def _user_hint():
        try:
            import os as _os, sys as _sys
            user = None
            for k in ("COLAB_USER", "USER", "USERNAME", "JUPYTERHUB_USER"):
                user = _os.environ.get(k)
                if user: break
            user = user or "Unknown"
            if "google.colab" not in _sys.modules:
                return f"{user} (Cruzer)"
            return user
        except Exception:
            pass
        return ""

    def _log_activity(retailer="", mode="", n_skus=0, n_stores=0,
                       n_rows_output=0, n_with_price=0, runtime_s=0,
                       output_file=""):
        try:
            import requests as _rq
            _rq.post(_ACTIVITY_URL, json={
                "token": _ACTIVITY_TOKEN, "session_id": _SESSION_ID,
                "colab": _COLAB_TAG,
                "retailer": str(retailer or "")[:30],
                "mode": str(mode or "")[:30],
                "n_skus": int(n_skus or 0),
                "n_stores": int(n_stores or 0),
                "n_rows_output": int(n_rows_output or 0),
                "n_with_price": int(n_with_price or 0),
                "runtime_s": int(runtime_s or 0),
                "output_file": str(output_file or "")[:120],
                "user_hint": _user_hint()[:80],
                "colab_url": "",
                "build_hash": _BUILD_HASH,
            }, timeout=5, allow_redirects=True)
        except Exception:
            pass

    def _post_consolidate(input_df, sku_col=None, easy_col=None, desc_col=None):
        """Postea las filas del archivo de carga al System Manifest, hoja
        'Consolidado SKUs'. El servidor dedupea por SKU Easy: si ya existe,
        actualiza solo las columnas no vacías; si no existe, agrega fila.
        Best-effort: errores silenciados para no romper el flujo del usuario.
        """
        if input_df is None or len(input_df) == 0:
            return
        try:
            import requests as _rq
            CONSOL_COLS = ["SKU Easy", "Desc. Producto", "SKU Sodimac", "SKU Falabella", "SKU Construmart"]
            # Aliases del archivo de carga real (las columnas detectadas pueden tener
            # otros nombres como "Cód. Easy", "Descripción", "SKU Sodimac ", etc).
            col_aliases = {
                "SKU Easy":       easy_col,
                "Desc. Producto": desc_col,
                "SKU Sodimac":    sku_col if sku_col in ("SKU Sodimac",) else None,
                "SKU Falabella":  sku_col if sku_col in ("SKU Falabella",) else None,
                "SKU Construmart":sku_col if sku_col in ("SKU Construmart",) else None,
            }
            cols_in_df = set(input_df.columns)
            rows_out = []
            for _, src in input_df.iterrows():
                row = {}
                for canon in CONSOL_COLS:
                    val = ""
                    # 1) si la columna canónica está en el df, úsala
                    if canon in cols_in_df:
                        val = src.get(canon, "")
                    # 2) si no, prueba el alias detectado
                    elif col_aliases.get(canon) and col_aliases[canon] in cols_in_df:
                        val = src.get(col_aliases[canon], "")
                    val = "" if val is None else str(val).strip()
                    if val.lower() in ("nan", "none"):
                        val = ""
                    row[canon] = val
                if row.get("SKU Easy") or any(row.get(k) for k in ("SKU Sodimac", "SKU Falabella", "SKU Construmart")):
                    rows_out.append(row)
            if not rows_out:
                return
            _rq.post(_ACTIVITY_URL, json={
                "token": _ACTIVITY_TOKEN,
                "type": "sku_consolidate",
                "session_id": _SESSION_ID,
                "colab": _COLAB_TAG,
                "user_hint": _user_hint()[:80],
                "build_hash": _BUILD_HASH,
                "rows": rows_out,
            }, timeout=10, allow_redirects=True)
        except Exception:
            pass

    state = {
        "retailer": None, "input_df": None,
        "skus_with_meta": None, "skus_list": None,
        "sku_col": None, "easy_col": None, "desc_col": None,
        "selected_stores": [], "construmart_stores": None,
        "running": False, "rows": [], "matches": [], "output_path": None,
        "pending_resume": None,
    }

    def _show_redownload_button(out_widget, file_path):
        """Botón para re-descargar el Excel después del download automático."""
        if not IN_COLAB: return
        from engines._excel_utils import download_once
        btn = widgets.Button(description="Descargar Excel de nuevo",
                              icon="download", button_style="info",
                              layout=widgets.Layout(width="260px"))
        def _do(_b, _p=str(file_path)):
            try: download_once(_p, colab_files)
            except Exception as _e:
                with out_widget: print(f"download fallo: {_e}")
        btn.on_click(_do)
        with out_widget:
            display(btn)



    # ─── Checkpoints (módulo compartido engines/_checkpoints.py) ─────────
    from engines import _checkpoints as _ckpts
    PARTIAL_DIR, _ckpt_ephemeral = _ckpts.resolve_dir(
        in_colab=IN_COLAB, drive_subdir="mk7_scraper_partials",
        local_name="mk7_partial_runs")
    _ckpts.purge_expired(PARTIAL_DIR)  # TTL 12h por RUN (protege el meta al reanudar)
    if _ckpt_ephemeral:
        display(HTML(_ckpts.ephemeral_warning_html("MK7")))

    def _ckpt_meta_path(run_id):  return _ckpts.meta_path(PARTIAL_DIR, run_id)
    def _ckpt_jsonl_path(run_id): return _ckpts.jsonl_path(PARTIAL_DIR, run_id)

    def _ckpt_save_meta(run_id, meta):
        _ckpts.write_meta(PARTIAL_DIR, run_id, meta)
        _ckpts.ensure_jsonl(PARTIAL_DIR, run_id)  # jsonl EAGER (fix #3)

    def _ckpt_append_row(run_id, row):
        _ckpts.append_row(PARTIAL_DIR, run_id, row)

    def _ckpt_load_rows(run_id, dedup_keys=None):
        # dedup_keys evita acumular filas si una tienda se re-scrapeó tras un
        # corte (fix #5). Sodimac ya colapsa por (sku_input, store_id) en
        # write_output, pero deduplicamos al cargar por robustez multi-reanudación.
        return _ckpts.load_rows(PARTIAL_DIR, run_id, dedup_keys=dedup_keys)

    def _ckpt_list_unfinished():
        # Compat: el panel espera 2-tuplas (run_id, meta).
        return [(rid, meta) for rid, meta, _rows, _done
                in _ckpts.list_runs(PARTIAL_DIR, unfinished_only=True)]

    def _ckpt_discard(run_id):
        _ckpts.cleanup_run(PARTIAL_DIR, run_id)

    def _ckpt_mark_finished(run_id):
        _ckpts.mark_finished(PARTIAL_DIR, run_id)


    display(HTML("""
    <div style='background:linear-gradient(120deg,#1a237e,#3949ab);color:white;
    padding:1.2rem 1.5rem;border-radius:12px;margin-bottom:1rem;font-family:sans-serif;'>
      <h2 style='margin:0;color:white;'>🏷️ MK7 — Buscador unificado de SKUs</h2>
      <p style='margin:.3rem 0 0;color:rgba(255,255,255,.9);font-size:.95rem;'>
        Sodimac · Falabella · Construmart en un sólo colab.
        Sube un Excel con tus SKUs y detectamos automáticamente la tienda.
      </p>
    </div>
    <style>
    @keyframes mk7-spin { to { transform: rotate(360deg); } }
    @keyframes mk7-pulse { 0%,100%{opacity:1} 50%{opacity:.55} }
    .mk7-spinner{display:inline-block;width:14px;height:14px;border:2px solid #3949ab;
      border-top-color:transparent;border-radius:50%;animation:mk7-spin .8s linear infinite;
      vertical-align:-3px;margin-right:8px;}
    .mk7-banner-running{background:linear-gradient(90deg,#ffb84d,#f0a020);color:#3a2400;
      padding:.7rem 1rem;border-radius:8px;font-family:sans-serif;font-weight:600;
      animation:mk7-pulse 1.6s ease-in-out infinite;margin:.5rem 0;}
    </style>
    """))

    # ─── Template embebido (5 cols + 3 filas de ejemplo) ───────────────
    _FORMATO_CARGA_B64 = "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"

    def _download_formato_carga(_btn):
        _path = "formato_carga_unificado.xlsx"
        with open(_path, "wb") as _fh:
            _fh.write(base64.b64decode(_FORMATO_CARGA_B64))
        try:
            from google.colab import files as _f
            _f.download(_path)
        except Exception:
            print("📁 Guardado en ./" + _path)

    download_format_btn = widgets.Button(
        description="📥 Descargar formato de carga (Excel)",
        icon="download", button_style="info",
        layout=widgets.Layout(width="320px"),
    )
    download_format_btn.on_click(_download_formato_carga)

    # ─── Helper común: checkbox panel ──────────────────────────────────
    def _checkbox_panel(items, all_checked=False, height="260px"):
        boxes = []
        for label, val in items:
            cb = widgets.Checkbox(value=all_checked, description=label, indent=False,
                                  layout=widgets.Layout(width="auto", margin="0"))
            cb._payload = val
            boxes.append(cb)
        list_box = widgets.VBox(boxes, layout=widgets.Layout(
            max_height=height, overflow_y="auto", border="1px solid #d0d0d0",
            border_radius="6px", padding="6px 10px", width="660px",
        ))
        btn_all = widgets.Button(description="Marcar todas", layout=widgets.Layout(width="130px"))
        btn_none = widgets.Button(description="Desmarcar todas", layout=widgets.Layout(width="150px"))
        btn_inv = widgets.Button(description="Invertir", layout=widgets.Layout(width="100px"))
        counter = widgets.HTML()
        def refresh(*_):
            n = sum(1 for b in boxes if b.value)
            counter.value = f"<span style='color:#555;font-size:.9em;'>{n} de {len(boxes)} seleccionadas</span>"
        for b in boxes: b.observe(refresh, "value")
        btn_all.on_click(lambda _: [setattr(b, "value", True) for b in boxes])
        btn_none.on_click(lambda _: [setattr(b, "value", False) for b in boxes])
        btn_inv.on_click(lambda _: [setattr(b, "value", not b.value) for b in boxes])
        refresh()
        cont = widgets.VBox([
            widgets.HBox([btn_all, btn_none, btn_inv, counter],
                         layout=widgets.Layout(align_items="center", gap="8px")),
            list_box,
        ])
        return cont, (lambda: [b._payload for b in boxes if b.value])

    # ─── Step 1: Upload + auto-detect retailer ─────────────────────────
    upload_w = widgets.FileUpload(accept=".xlsx,.xls,.csv", multiple=False,
                                  description="📤 Subir Excel/CSV")
    upload_status = widgets.HTML("<span style='color:#888;'>Sin archivo cargado.</span>")
    preview_out = widgets.Output()

    # Aliases de SKU por retailer (con tolerancia a typos comunes)
    SKU_ALIASES = {
        "sodimac":    ["SKU Sodimac", "SKU Sodimac ", "sku sodimac"],
        "falabella":  ["SKU Falabella", "SKU Fallabella", "SKU Falabela", "sku falabella"],
        "construmart":["SKU Construmart", "sku construmart"],
    }

    def _find_col(df_cols, aliases):
        cols_lower = {c.lower().strip(): c for c in df_cols}
        for a in aliases:
            key = a.lower().strip()
            if key in cols_lower:
                return cols_lower[key]
        return None

    def _detect_retailer(df):
        """Devuelve {'retailer': str, 'sku_col': str, 'cols_with_data': [(ret, col)]}.
        Si más de 1 retailer tiene SKUs, devuelve cols_with_data poblado para que
        la UI muestre el error correspondiente."""
        cols_with_data = []
        for ret, aliases in SKU_ALIASES.items():
            col = _find_col(df.columns, aliases)
            if not col: continue
            s = df[col].dropna().astype(str).str.strip()
            s = s[s != ""]
            s = s[~s.str.lower().isin(["nan","none","por definir"])]
            if len(s) > 0:
                cols_with_data.append((ret, col))
        if not cols_with_data:
            return {"retailer": None, "sku_col": None, "cols_with_data": []}
        return {"retailer": cols_with_data[0][0], "sku_col": cols_with_data[0][1],
                "cols_with_data": cols_with_data}

    def _on_upload(change):
        if not upload_w.value: return
        # Leer file (ipywidgets v7/v8 compat)
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
        det = _detect_retailer(df)

        # Caso 1: ningún retailer tiene SKUs
        if not det["cols_with_data"]:
            upload_status.value = (
                "<div style='background:#fff3cd;border:1px solid #ffc107;padding:.7rem;border-radius:6px;'>"
                "⚠️ <b>El archivo no tiene SKUs en ninguna columna conocida.</b><br>"
                "Esperamos al menos una de: <code>SKU Sodimac</code>, <code>SKU Falabella</code> o <code>SKU Construmart</code> con valores."
                "</div>"
            )
            stores_container.layout.display = "none"
            run_container.layout.display = "none"
            state["retailer"] = None
            return

        # Caso 2: más de un retailer tiene SKUs → ERROR
        if len(det["cols_with_data"]) > 1:
            cols_msg = ", ".join(f"<code>{c}</code> ({r})" for r, c in det["cols_with_data"])
            upload_status.value = (
                "<div style='background:#ffe4e4;border:2px solid #c0392b;padding:.9rem;border-radius:6px;'>"
                "<b style='font-size:1.05em;'>❌ Sólo se permite UNA tienda por archivo.</b><br>"
                f"Encontré SKUs en <b>{len(det['cols_with_data'])} columnas</b>: {cols_msg}.<br>"
                "<br>Por favor:<br>"
                "1. Vacía las columnas de los retailers que NO quieres scrapear.<br>"
                "2. Volvé a subir el archivo.<br>"
                "<small style='color:#666;'>(Para procesar varias tiendas, corré el MK7 una vez por cada una.)</small>"
                "</div>"
            )
            stores_container.layout.display = "none"
            run_container.layout.display = "none"
            state["retailer"] = None
            return

        # Caso 3: OK — un sólo retailer detectado
        retailer = det["retailer"]
        sku_col = det["sku_col"]
        easy_col = _find_col(df.columns, ["SKU Easy", "sku easy", "Cód. Easy", "Codigo Easy"])
        desc_col = _find_col(df.columns, ["Desc. Producto", "Desc Producto", "Descripción",
                                           "Descripcion", "Descripcion Easy", "Descripción Producto",
                                           "Descripcion Producto"])
        # Filter rows with data in sku_col
        df_filt = df[df[sku_col].notna()].copy()
        df_filt[sku_col] = df_filt[sku_col].astype(str).str.strip()
        # Quitar decimales tipo "12345.0" del df para que matchee al escribir el output
        df_filt[sku_col] = df_filt[sku_col].apply(lambda s: s.split(".")[0] if pd.notna(s) and re.fullmatch(r"\d+\.0+", str(s)) else s)
        df_filt = df_filt[df_filt[sku_col] != ""]
        df_filt = df_filt[~df_filt[sku_col].str.lower().isin(["nan","none","por definir"])]
        # Build skus_with_meta + skus_list
        skus_meta, seen = [], set()
        for _, r in df_filt.iterrows():
            sku = str(r[sku_col]).strip()
            if not sku or sku in seen: continue
            seen.add(sku)
            skus_meta.append({"sku": sku,
                               "easy": str(r.get(easy_col, "")) if easy_col else "",
                               "desc": str(r.get(desc_col, "")) if desc_col else ""})
        state.update(retailer=retailer, input_df=df_filt, sku_col=sku_col,
                     easy_col=easy_col, desc_col=desc_col,
                     skus_with_meta=skus_meta, skus_list=[m["sku"] for m in skus_meta])

        # Mostrar feedback
        ret_colors = {"sodimac": "#fa6900", "falabella": "#2e7d32", "construmart": "#e30613"}
        ret_emojis = {"sodimac": "🛒", "falabella": "🛍️", "construmart": "🏗️"}
        ret_names = {"sodimac":"SODIMAC","falabella":"FALABELLA","construmart":"CONSTRUMART"}
        upload_status.value = (
            f"<div style='background:#e8f5e9;border:1px solid #66bb6a;padding:.8rem;border-radius:6px;'>"
            f"✓ <b>{name}</b> · {len(df_filt)} filas con SKUs · <b>{len(skus_meta)} únicos</b><br>"
            f"<span style='color:{ret_colors[retailer]};font-size:1.1em;font-weight:bold;'>"
            f"{ret_emojis[retailer]} Tienda detectada: {ret_names[retailer]}</span> "
            f"<span style='color:#666;'>(col <code>{sku_col}</code>)</span>"
            f"</div>"
        )
        with preview_out:
            clear_output()
            display(df_filt.head(8))

        # Construir UI de tiendas
        _build_stores_for(retailer)
        stores_container.layout.display = ""
        run_container.layout.display = ""
        _update_run_summary()

    upload_w.observe(_on_upload, names="value")

    step1 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.3rem 0;'>📂 Paso 1 — Archivo de SKUs</h4>"),
        widgets.HTML(
            "<div style='background:#e8f5e9;border:1px solid #66bb6a;padding:.5rem;"
            "border-radius:6px;margin:.3rem 0;font-size:.9em;'>"
            "💡 <b>Formato unificado</b>: completa <b>SOLO UNA</b> columna de SKU "
            "(<code>SKU Sodimac</code> O <code>SKU Falabella</code> O <code>SKU Construmart</code>). "
            "Si completás más de una, el sistema te avisará.</div>"
        ),
        download_format_btn,
        widgets.HTML("<hr style='margin:.6rem 0;'>"),
        upload_w, upload_status, preview_out,
    ])

    # ─── Step 2: Tiendas (depende del retailer) ────────────────────────
    stores_container = widgets.VBox(layout=widgets.Layout(display="none"))
    get_selected_stores = lambda: []

    async def _discover_construmart_stores():
        async with Stealth().use_async(async_playwright()) as pw:
            b = await pw.chromium.launch(headless=True)
            ctx = await b.new_context(viewport={"width":1280,"height":900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36")
            page = await ctx.new_page()
            s = await discover_stores_construmart(page)
            await b.close()
            return s

    def _build_stores_for(retailer):
        global get_selected_stores
        if retailer == "sodimac":
            all_st = ALL_STORES_SODIMAC
            rm = [s for s in all_st if s["region"] == "Metropolitana"]
            presets = {
                "Solo Cerrillos (default — más rápido)": [s for s in all_st if s["id"] == "E522"],
                f"Todas RM ({len(rm)} tiendas)": rm,
                f"Todas Chile ({len(all_st)} tiendas)": all_st,
                "Personalizado": None,
            }
            labeler = lambda s: f"{s['id']}  {s['name']:<14}  ({s.get('comuna','')}, {s['region']})"
            default_id = "E522"
        elif retailer == "falabella":
            all_st = ALL_STORES_FALABELLA
            rm = [s for s in all_st if s["region"] == "Metropolitana"]
            presets = {
                "Solo Kennedy / Las Condes (Falabella tiene precios nacionales)": [s for s in all_st if s["id"] == "E502"],
                f"Todas RM ({len(rm)} zonas)": rm,
                f"Todas Chile ({len(all_st)} zonas)": all_st,
                "Personalizado": None,
            }
            labeler = lambda s: f"{s['id']}  {s['name']:<14}  ({s.get('comuna','')}, {s['region']})"
            default_id = "E502"
        else:  # construmart
            if not state.get("construmart_stores"):
                try:
                    state["construmart_stores"] = asyncio.run(_discover_construmart_stores())
                except Exception:
                    state["construmart_stores"] = []
                if not state["construmart_stores"]:
                    state["construmart_stores"] = STATIC_STORES_CONSTRUMART
            all_st = state["construmart_stores"]
            rm = [s for s in all_st if "METROPOLITANA" in (s["region"] or "").upper()]
            presets = {
                "Solo LAS CONDES (default — más rápido)": [s for s in all_st if s["id"] == "14"] or all_st[:1],
                f"Todas RM ({len(rm)} tiendas)": rm,
                f"Todas Chile ({len(all_st)} tiendas)": all_st,
                "Personalizado": None,
            }
            def labeler(s):
                eq = sodimac_equivalent_construmart(s["id"])
                return f"{s['id']:>4}  {s['name']:<22}  ({s['region']})" + (f"  → {eq}" if eq else "")
            default_id = "14"

        preset_radio = widgets.RadioButtons(
            options=list(presets.keys()), value=list(presets.keys())[0],
            description="Preset:", style={"description_width": "initial"},
            layout=widgets.Layout(width="auto"),
        )
        store_panel, _get_custom = _checkbox_panel(
            [(labeler(s), s) for s in all_st], all_checked=False, height="260px",
        )
        store_panel_wrap = widgets.VBox([store_panel], layout=widgets.Layout(display="none"))
        store_eta = widgets.HTML()

        def _update(*_):
            preset = presets[preset_radio.value]
            if preset is None:
                store_panel_wrap.layout.display = ""
                sel = _get_custom()
                state["selected_stores"] = sel if sel else (
                    [s for s in all_st if s["id"] == default_id] or all_st[:1]
                )
            else:
                store_panel_wrap.layout.display = "none"
                state["selected_stores"] = preset
            n = len(state["selected_stores"])
            store_eta.value = (
                "<span style='color:#c0392b'>⚠️ Selecciona al menos 1</span>" if n == 0
                else f"<span style='color:#27ae60'>✓ {n} tienda(s) seleccionada(s)</span>"
            )
            _update_run_summary()

        preset_radio.observe(_update, "value")
        for child in store_panel.children[1].children:
            child.observe(_update, "value")
        _update()
        get_selected_stores = _get_custom  # noop pero accesible


        stores_container.children = [
            widgets.HTML("<h4 style='margin:.6rem 0 .3rem;'>📍 Paso 2 — Tiendas</h4>"),
            preset_radio, store_panel_wrap, store_eta,
        ]

    # ─── Step 3: Run ──────────────────────────────────────────────────
    speed_note = widgets.HTML(layout=widgets.Layout(display="none"))
    run_btn = widgets.Button(description="🚀 Iniciar búsqueda", button_style="success",
                             disabled=True, layout=widgets.Layout(width="220px"))
    running_banner = widgets.HTML()
    store_bar = widgets.IntProgress(min=0, max=100, value=0, description="Tiendas:",
                                    bar_style="info", layout=widgets.Layout(width="540px"),
                                    style={"description_width": "initial"})
    store_pct = widgets.HTML(layout=widgets.Layout(width="140px"))
    sku_bar = widgets.IntProgress(min=0, max=100, value=0, description="SKUs:",
                                  bar_style="info", layout=widgets.Layout(width="540px"),
                                  style={"description_width": "initial"})
    sku_pct = widgets.HTML(layout=widgets.Layout(width="140px"))
    live_status = widgets.HTML()
    live_metrics = widgets.HTML()
    result_out = widgets.Output()
    run_summary = widgets.HTML()

    def _set_pct(w, v, t):
        if not t: w.value = ""; return
        p = int(round(100 * v / t))
        w.value = f"<span style='color:#555;font-size:.9em;margin-left:8px;'>{v}/{t} · {p}%</span>"

    def _set_running_ui(on):
        if on:
            run_btn.layout.display = "none"
            running_banner.value = ("<div class='mk7-banner-running'>"
                                    "<span class='mk7-spinner'></span>"
                                    "Trabajando — no cierres esta pestaña ni la celda</div>")
        else:
            run_btn.description = "🚀 Iniciar búsqueda"
            run_btn.disabled = False
            run_btn.layout.display = ""
            running_banner.value = ""

    def _update_run_summary(*_):
        n_st = len(state.get("selected_stores", []))
        n_sk = len(state.get("skus_with_meta") or [])
        ret = state.get("retailer") or "—"
        if n_st == 0 or n_sk == 0:
            run_summary.value = ""; return
        ret_colors = {"sodimac":"#fa6900","falabella":"#2e7d32","construmart":"#e30613"}
        color = ret_colors.get(ret, "#3949ab")
        run_summary.value = (
            f"<div style='background:#f0f7ff;border:1px solid #bcdcff;"
            f"padding:.6rem;border-radius:6px;margin:.4rem 0;font-size:.95em;'>"
            f"📋 Vas a buscar <b>{n_sk}</b> SKU(s) en <b>{n_st}</b> tienda(s) "
            f"de <span style='color:{color};font-weight:bold;'>{ret.upper()}</span> "
            f"= <b>{n_st * n_sk}</b> filas.</div>"
        )

    _RUN_T0 = [None]
    _GLOBAL_SKUS = [set()]
    _LAST_ZONE_INFO = [""]

    def _fmt_time(s):
        s = int(s); m, s = divmod(s, 60); h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _update_metrics(si, n_st, total_rows):
        """Actualiza live_metrics con filas reales, SKUs únicos, elapsed, rate, ETA."""
        import time as _t
        if _RUN_T0[0] is None: return
        elapsed = _t.time() - _RUN_T0[0]
        # Usar conteo REAL de state["rows"] (poblado en vivo por on_row/on_match)
        rows_so_far = state.get("rows") or []
        real_total = len(rows_so_far) or total_rows
        # SKUs únicos: probar cada key conocido (cada retailer usa el suyo)
        try:
            for r in rows_so_far:
                v = (r.get("SKU Construmart") or r.get("SKU Falabella")
                      or r.get("SKU Sodimac") or r.get("sku_input"))
                if v: _GLOBAL_SKUS[0].add(str(v))
        except Exception:
            pass
        rate = real_total / max(elapsed/60, 0.01)
        parts = [
            f"<b>🧮 Filas:</b> {real_total}",
            f"<b>SKUs únicos:</b> {len(_GLOBAL_SKUS[0])}",
            f"<b>⏱</b> {_fmt_time(elapsed)}",
            f"<b>~{rate:.0f}</b> filas/min",
        ]
        # ETA basado en stores hechos
        if si and si >= 1:
            per_store = elapsed / si
            remaining = (n_st - si) * per_store
            if remaining > 0:
                parts.append(f"<b>ETA:</b> ~{_fmt_time(remaining)}")
        if _LAST_ZONE_INFO[0]:
            parts.append(_LAST_ZONE_INFO[0])
        live_metrics.value = " · ".join(parts)

    def _progress_cb(si, n_st, store, ki, total_rows):
        import time as _t
        if _RUN_T0[0] is None:
            _RUN_T0[0] = _t.time()
            _GLOBAL_SKUS[0] = set()
            _LAST_ZONE_INFO[0] = ""
        store_bar.max = n_st
        store_bar.value = si if ki is None else si - 1
        _set_pct(store_pct, si if ki is None else si - 1, n_st)
        if ki is None:
            live_status.value = (f"<span style='color:#c0392b'>"
                                  f"✗ {store.get('name','?')}: no se pudo setear tienda</span>")
            _LAST_ZONE_INFO[0] = f"<span style='color:#c0392b'><b>Última:</b> ✗ {store.get('name','?')}</span>"
        else:
            n_total_skus = len(state.get("skus_with_meta") or state.get("skus_list") or [1])
            sku_bar.max = n_total_skus
            sku_bar.value = ki
            _set_pct(sku_pct, ki, n_total_skus)
            live_status.value = (f"<span class='mk7-spinner'></span>"
                                  f"📍 {store.get('name','?')} · SKU {ki}/{n_total_skus} · "
                                  f"{total_rows} filas")
            # Si recién entramos a una nueva zona (ki==n_total_skus), marcamos como completa
            if ki >= n_total_skus:
                _LAST_ZONE_INFO[0] = f"<b>Última:</b> ✓ {store.get('name','?')}"
        _update_metrics(si, n_st, total_rows)

    def _sodimac_progress_wrapper(event_dict):
        """Adapt sodimac engine progress events to _progress_cb + granular live_status."""
        ev = event_dict.get("event")
        st = event_dict.get("store") or {}
        sn = st.get("name","?")
        if ev == "browser_launching":
            live_status.value = "<span class='mk7-spinner'></span>🚀 Lanzando Chromium…"
        elif ev == "browser_ready":
            live_status.value = "<span class='mk7-spinner'></span>✓ Chromium listo. Comenzando…"
        elif ev == "warmup_start":
            live_status.value = f"<span class='mk7-spinner'></span>⏳ {sn} · calentando sesión (anti-bot, ~6s)…"
        elif ev == "warmup_done":
            live_status.value = f"<span class='mk7-spinner'></span>🔧 {sn} · seteando zona…"
        elif ev == "zone_start":
            # Ya cubierto por warmup_done; este evento llega justo antes del set_zone
            pass
        elif ev == "batch_done":
            # NO pasamos por _progress_cb porque sobreescribiría el live_status.
            # Actualizamos barras + métricas a mano.
            import time as _t
            if _RUN_T0[0] is None: _RUN_T0[0] = _t.time()
            idx = state.get("_sodimac_zone_idx", 0)
            total_batches = event_dict.get("total_batches_in_zone", 1)
            done = event_dict.get("batches_done_in_zone", 1)
            found = event_dict.get("found_in_batch", 0)
            live_status.value = (f"<span class='mk7-spinner'></span>"
                                  f"🔍 {sn} · lote {done}/{total_batches} → {found} matches")
            # Actualizar barra de SKUs (proporción dentro de la zona)
            approx_skus = int(len(state["skus_list"]) * done / total_batches)
            sku_bar.max = len(state["skus_list"]) or 1
            sku_bar.value = approx_skus
            _set_pct(sku_pct, approx_skus, len(state["skus_list"]) or 1)
            # No tocamos store_bar (eso lo hace zone_end)
            _update_metrics(idx, len(state["selected_stores"]),
                             idx * len(state["skus_list"]) + approx_skus)
        elif ev == "zone_end":
            import time as _t
            if _RUN_T0[0] is None: _RUN_T0[0] = _t.time()
            failed = event_dict.get("zone_failed", False)
            found = event_dict.get("found_in_zone", 0)
            idx = state.get("_sodimac_zone_idx", 0) + 1
            state["_sodimac_zone_idx"] = idx
            n = len(state["selected_stores"])
            if failed:
                live_status.value = f"<span style='color:#c0392b'>✗ {sn} · falló set_zone</span>"
                _LAST_ZONE_INFO[0] = f"<span style='color:#c0392b'><b>Última:</b> ✗ {sn} FAIL</span>"
            else:
                live_status.value = f"<span style='color:#27ae60'>✓ {sn} · {found} matches</span>"
                _LAST_ZONE_INFO[0] = f"<b>Última:</b> ✓ {sn} ({found})"
            # Avanzar barra de tiendas
            store_bar.max = n
            store_bar.value = idx
            _set_pct(store_pct, idx, n)
            # Reset SKU bar para próxima zona
            sku_bar.value = 0
            _set_pct(sku_pct, 0, len(state["skus_list"]) or 1)
            _update_metrics(idx, n, idx * len(state["skus_list"]))
        elif ev == "complete":
            live_status.value = "<span style='color:#27ae60'>✓ Scraping completado.</span>"

    _RUN_T0[0] = None  # reset al iniciar pipeline
    async def _run_pipeline():
        retailer = state["retailer"]
        all_stores = list(state["selected_stores"])
        screenshot = True  # Siempre capturar — el Excel siempre tiene hoja "Con fotos"

        # ─── Resume support ───────────────────────────────────────────
        resume_id = state.get("_resume_run_id")
        if resume_id:
            run_id = resume_id
            meta = _json.loads(_ckpt_meta_path(run_id).read_text(encoding="utf-8"))
            ts = meta.get("ts") or datetime.now().strftime("%Y-%m-%d_%H%M")
            stores_done_ids = set(meta.get("stores_done") or [])
            # Sodimac: dedup por (store_id, sku_input) para no acumular filas si
            # una tienda se re-scrapeó tras un corte (fix #5).
            _dk = ["store_id", "sku_input"] if retailer == "sodimac" else None
            prior_rows = _ckpt_load_rows(run_id, dedup_keys=_dk)
        else:
            ts = datetime.now().strftime("%Y-%m-%d_%H%M")
            run_id = f"mk7_{retailer}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            stores_done_ids = set()
            prior_rows = []
            try:
                input_df_records = state["input_df"].to_dict(orient="records") if state.get("input_df") is not None else []
            except Exception:
                input_df_records = []
            meta = {
                "run_id": run_id, "ts": ts, "retailer": retailer,
                "stores": all_stores,
                "stores_done": [],
                "skus_with_meta": state.get("skus_with_meta") or [],
                "skus_list": state.get("skus_list") or [],
                "sku_col": state.get("sku_col"),
                "easy_col": state.get("easy_col"),
                "desc_col": state.get("desc_col"),
                "input_df_records": input_df_records,
                "rows_count": 0,
                "finished": False,
            }
            _ckpt_save_meta(run_id, meta)
        state["_current_run_id"] = run_id
        state["_current_meta"] = meta

        pending_stores = [s for s in all_stores if s.get("id") not in stores_done_ids]
        n_total_stores = len(all_stores)

        # Mantener barra de tiendas sincronizada desde el inicio (refleja
        # cuántas tiendas ya están done según el checkpoint).
        try:
            store_bar.max = n_total_stores
            store_bar.value = len(stores_done_ids)
            _set_pct(store_pct, len(stores_done_ids), n_total_stores)
        except Exception:
            pass

        # Helper: marcar tienda completada (idempotente, escribe meta)
        def _mark_store_done(store_id):
            if not store_id: return
            sd = set(meta.get("stores_done") or [])
            if store_id in sd: return
            sd.add(store_id)
            meta["stores_done"] = list(sd)
            meta["rows_count"] = len(state.get("rows") or [])
            _ckpt_save_meta(run_id, meta)
            # Actualizar barra de tiendas en vivo
            try:
                store_bar.value = len(sd)
                _set_pct(store_pct, len(sd), n_total_stores)
            except Exception:
                pass

        state["_mark_store_done"] = _mark_store_done

        if retailer == "construmart":
            state["rows"] = list(prior_rows)
            _last_store_c = {"id": None}
            def _on_row_c(r):
                state.setdefault("rows", []).append(r)
                _ckpt_append_row(run_id, r)
                # Detectar cambio de tienda por la columna "Tienda" o "Nombre Tienda"
                try:
                    cur = (r.get("Tienda") or r.get("Nombre Tienda") or "").strip()
                    if cur and _last_store_c["id"] and _last_store_c["id"] != cur:
                        _mark_store_done(_last_store_c["id"])
                    if cur:
                        _last_store_c["id"] = cur
                except Exception:
                    pass
            def _status_c(msg):
                live_status.value = f"<span class='mk7-spinner'></span>{msg}"
            if pending_stores:
                await search_skus_construmart(
                    state["skus_with_meta"], pending_stores,
                    screenshot=screenshot, headless=True,
                    progress_cb=_progress_cb,
                    on_row=_on_row_c,
                    status_cb=_status_c,
                )
            # marcar TODAS las pending_stores como done (la búsqueda terminó OK)
            for _s in pending_stores:
                _mark_store_done(_s.get("id"))
            live_status.value = "<span style='color:#27ae60'>✓ Scraping completado.</span>"
            rows = list(state["rows"])
            out = OUTPUT_DIR / f"Construmart_MK7_{ts}.xlsx"
            write_output_construmart(rows, str(out))
            state["rows"] = rows
        elif retailer == "falabella":
            state["rows"] = list(prior_rows)
            _last_store_f = {"id": None}
            def _on_row_f(r):
                state.setdefault("rows", []).append(r)
                _ckpt_append_row(run_id, r)
                try:
                    cur = (r.get("Zona") or r.get("Comuna") or "").strip()
                    if cur and _last_store_f["id"] and _last_store_f["id"] != cur:
                        _mark_store_done(_last_store_f["id"])
                    if cur:
                        _last_store_f["id"] = cur
                except Exception:
                    pass
            def _status_f(msg):
                live_status.value = f"<span class='mk7-spinner'></span>{msg}"
            if pending_stores:
                await search_skus_falabella(
                    state["skus_with_meta"], zones=pending_stores,
                    screenshot=screenshot, headless=True,
                    progress_cb=_progress_cb,
                    on_row=_on_row_f,
                    status_cb=_status_f,
                )
            # Falabella usa "Zona" (no id E5xx) en las rows; marcamos por id de pending_stores.
            for _s in pending_stores:
                _mark_store_done(_s.get("id"))
            live_status.value = "<span style='color:#27ae60'>✓ Scraping completado.</span>"
            rows = list(state["rows"])
            out = OUTPUT_DIR / f"Falabella_MK7_{ts}.xlsx"
            write_output_falabella(rows, str(out))
            state["rows"] = rows
        elif retailer == "sodimac":
            state["_sodimac_zone_idx"] = 0
            shots_dir = OUTPUT_DIR / "mk7_shots"
            shots_dir.mkdir(exist_ok=True)
            state["rows"] = list(prior_rows)
            def _on_match_s(m):
                state.setdefault("rows", []).append(m)
                _ckpt_append_row(run_id, m)
            # Wrap sodimac progress: zone_end OK → marcar tienda. zone_end fail → no marcar.
            def _sodimac_wrap(event_dict):
                _sodimac_progress_wrapper(event_dict)
                if event_dict.get("event") == "zone_end":
                    st = event_dict.get("store") or {}
                    sid = st.get("id")
                    if sid and not event_dict.get("zone_failed"):
                        _mark_store_done(sid)
            if pending_stores:
                await search_skus_mk6_sodimac(
                    state["skus_list"], pending_stores,
                    headless=True,
                    screenshot_dir=str(shots_dir),
                    progress_cb=_sodimac_wrap,
                    on_match=_on_match_s,
                )
            # Guard: si alguna tienda completó sin event zone_end (raro), no la marcamos
            # — preferimos que aparezca como "no terminada" en lugar de un falso done.
            matches = list(state["rows"])
            state["matches"] = matches
            out = OUTPUT_DIR / f"Sodimac_MK7_{ts}.xlsx"
            in_df = state.get("input_df")
            if in_df is None and meta.get("input_df_records"):
                in_df = pd.DataFrame(meta["input_df_records"])
            write_output_sodimac(in_df, meta.get("desc_col") or "Desc. Producto",
                                  meta.get("sku_col"), meta.get("easy_col") or "SKU Easy",
                                  matches, str(out), stores=all_stores)
            state["rows"] = matches
        else:
            raise RuntimeError(f"Retailer no soportado: {retailer}")

        _ckpt_mark_finished(run_id)
        state["_resume_run_id"] = None
        state["output_path"] = out
        return state["rows"]

    def on_run_clicked(_):
        if state["running"]: return
        if not state.get("retailer"):
            with result_out: clear_output(); print("⚠️ Sube un archivo válido primero."); return
        if not state.get("selected_stores"):
            with result_out: clear_output(); print("⚠️ Selecciona al menos una tienda."); return
        if not state.get("skus_with_meta"):
            with result_out: clear_output(); print("⚠️ El archivo no tiene SKUs."); return
        state["running"] = True
        _set_running_ui(True)
        with result_out: clear_output()
        try:
            rows = asyncio.run(_run_pipeline())
        except Exception as e:
            import traceback
            with result_out:
                print(f"❌ Error: {e}"); traceback.print_exc()
            state["running"] = False
            _set_running_ui(False)
            return
        state["running"] = False
        _set_running_ui(False)
        # Tras un run completo, ocultar el botón y refrescar panel.
        run_btn.layout.display = "none"
        try: _refresh_resume_panel()
        except Exception: pass

        if not rows:
            with result_out: print("⚠️ No se generaron resultados."); return
        retailer = state["retailer"]
        if retailer == "sodimac":
            n_found = len(rows)  # matches
            with result_out:
                print(f"✅ Listo — {n_found} matches · {len(state['skus_list'])} SKUs · "
                      f"{len(state['selected_stores'])} tienda(s)")
                print(f"   Excel: {state['output_path'].name}")
        else:
            n_with_price = sum(1 for r in rows if r.get("Precio Internet"))
            n_distinct = len({r.get("SKU "+retailer.title()) or r.get("SKU Falabella") or r.get("SKU Construmart") for r in rows})
            with result_out:
                print(f"✅ Listo — {len(rows)} filas · {n_with_price} con precio · "
                      f"{len(state['selected_stores'])} tienda(s)")
                print(f"   Excel: {state['output_path'].name}")
                df_view = pd.DataFrame(rows)
                cols_p = ["Tienda","Nombre Tienda","Zona","Comuna",
                           "SKU Construmart","SKU Falabella","Marca",
                           "Descripción Producto","Precio Internet","% Descuento"]
                view = [c for c in cols_p if c in df_view.columns]
                if view: display(df_view[view].head(12))
        # Log activity antes del download
        try:
            _log_activity(retailer=state.get("retailer",""),
                           mode="mk7",
                           n_skus=len(state.get("skus_with_meta") or state.get("skus_list") or []),
                           n_stores=len(state.get("selected_stores") or []),
                           n_rows_output=len(rows or []),
                           n_with_price=sum(1 for r in (rows or []) if r.get("Precio Internet")),
                           runtime_s=0,
                           output_file=state.get("output_path").name if state.get("output_path") else "")
        except Exception: pass
        # Consolidar SKUs del archivo de carga al System Manifest (hoja "Consolidado SKUs").
        try:
            _post_consolidate(state.get("input_df"),
                              sku_col=state.get("sku_col"),
                              easy_col=state.get("easy_col"),
                              desc_col=state.get("desc_col"))
        except Exception: pass
        if IN_COLAB:
            with result_out:
                print("\n⬇️  Descargando Excel…")
            # download FUERA del contexto del Output → evita re-disparo al re-renderizar
            from engines._excel_utils import download_once
            download_once(state["output_path"], colab_files)
            _show_redownload_button(result_out, state["output_path"])
        else:
            with result_out:
                print(f"\n📁 Excel: {state['output_path']}")

    run_btn.on_click(on_run_clicked)

    run_container = widgets.VBox([
        widgets.HTML("<h4 style='margin:.8rem 0 .3rem;'>🚀 Paso 3 — Ejecutar</h4>"),
        run_summary, speed_note, run_btn, running_banner,
        widgets.HBox([store_bar, store_pct], layout=widgets.Layout(align_items="center")),
        widgets.HBox([sku_bar, sku_pct], layout=widgets.Layout(align_items="center")),
        live_status, live_metrics, result_out,
    ], layout=widgets.Layout(display="none"))

    footer = widgets.HTML(
        "<div style='margin-top:1.5rem;padding-top:.6rem;border-top:1px solid #e0e0e0;"
        "text-align:right;color:#aaa;font-size:.75em;font-family:sans-serif;font-style:italic;'>"
        "MK7 — Carlos Cruz E.<br/><span style='font-size:.85em;'>Copyright (c) 2026 Carlos Cruz Errazuriz · All rights reserved · Proprietary — No unauthorized use or distribution</span></div>"
    )

    # Habilitar run_btn cuando hay retailer + stores + skus
    def _maybe_enable_run(*_):
        ok = state.get("retailer") and state.get("selected_stores") and state.get("skus_with_meta")
        run_btn.disabled = not bool(ok)
        # Si volvió a haber inputs válidos y no estamos corriendo, mostrar el botón
        # (puede estar oculto por un run previo terminado).
        if ok and not state.get("running"):
            run_btn.layout.display = ""

    # Re-chequear cada vez que cambia algo
    import functools
    _orig_update = _update_run_summary
    def _update_run_summary(*_):
        _orig_update()
        _maybe_enable_run()


    # ─── Panel de reanudación ─────────────────────────────────────────
    resume_panel = widgets.VBox([], layout=widgets.Layout(display="none"))

    def _refresh_resume_panel():
        runs = _ckpt_list_unfinished()
        if not runs:
            resume_panel.children = []
            resume_panel.layout.display = "none"
            return
        children = [widgets.HTML(
            "<h4 style='margin:.4rem 0;'>⏯️ Runs interrumpidos (puedes reanudar)</h4>"
        )]
        for run_id, meta in runs:
            ret = meta.get("retailer", "?")
            ts = meta.get("ts", run_id)
            n_done = len(meta.get("stores_done") or [])
            n_total = len(meta.get("stores") or [])
            n_skus = len(meta.get("skus_with_meta") or meta.get("skus_list") or [])
            rows_n = meta.get("rows_count", 0)
            ret_colors = {"sodimac":"#fa6900","falabella":"#2e7d32","construmart":"#e30613"}
            color = ret_colors.get(ret, "#3949ab")
            info = widgets.HTML(
                f"<div style='padding:.5rem .7rem;border-left:3px solid #f39c12;"
                f"background:#fff8e1;border-radius:4px;margin:.2rem 0;'>"
                f"<b style='color:{color};'>{ret.upper()}</b> · <b>{ts}</b><br>"
                f"<span style='font-size:.9em;color:#555;'>"
                f"{n_done}/{n_total} tiendas hechas · {n_skus} SKUs · "
                f"{rows_n} filas guardadas</span></div>"
            )
            btn_r = widgets.Button(description=f"▶ Reanudar",
                                    button_style="warning",
                                    layout=widgets.Layout(width="160px"))
            btn_d = widgets.Button(description="🗑 Descartar",
                                    layout=widgets.Layout(width="130px"))
            def _make_resume(rid=run_id, m=meta):
                def _f(_):
                    _do_resume(rid, m)
                return _f
            def _make_discard(rid=run_id):
                def _f(_):
                    _ckpt_discard(rid)
                    _refresh_resume_panel()
                return _f
            btn_r.on_click(_make_resume())
            btn_d.on_click(_make_discard())
            children.append(widgets.HBox([info, btn_r, btn_d],
                                           layout=widgets.Layout(align_items="center", gap="8px")))
        resume_panel.children = children
        resume_panel.layout.display = ""

    def _do_resume(run_id, meta):
        """Rehidrata state desde meta y arranca el pipeline."""
        if state.get("running"): return
        # Ocultar panel de resume INMEDIATAMENTE (antes del await) para evitar
        # que otros runs queden clickeables mientras corre uno.
        resume_panel.layout.display = "none"
        state["retailer"] = meta.get("retailer")
        state["selected_stores"] = meta.get("stores") or []
        state["skus_with_meta"] = meta.get("skus_with_meta") or []
        state["skus_list"] = meta.get("skus_list") or [m.get("sku") for m in (meta.get("skus_with_meta") or [])]
        state["sku_col"] = meta.get("sku_col")
        state["easy_col"] = meta.get("easy_col")
        state["desc_col"] = meta.get("desc_col")
        if meta.get("input_df_records"):
            try:
                state["input_df"] = pd.DataFrame(meta["input_df_records"])
            except Exception:
                state["input_df"] = None
        state["_resume_run_id"] = run_id
        state["_was_resumed"] = True
        state["running"] = True
        _set_running_ui(True)
        with result_out:
            clear_output()
            print(f"⏯️ Reanudando run {run_id} ({meta.get('retailer','?').upper()})…")
        # Mostrar contenedores
        stores_container.layout.display = ""
        run_container.layout.display = ""
        try:
            rows = asyncio.run(_run_pipeline())
        except Exception as e:
            import traceback
            with result_out:
                print(f"❌ Error en resume: {e}"); traceback.print_exc()
            state["running"] = False
            _set_running_ui(False)
            state["_was_resumed"] = False
            _refresh_resume_panel()
            return
        state["running"] = False
        _set_running_ui(False)
        # Tras resume: ocultar el botón "Iniciar búsqueda" y mostrar mensaje final
        run_btn.layout.display = "none"
        state["_was_resumed"] = False
        _refresh_resume_panel()
        # Log activity (modo resume)
        try:
            _log_activity(retailer=state.get("retailer",""),
                           mode="mk7-resume",
                           n_skus=len(state.get("skus_with_meta") or state.get("skus_list") or []),
                           n_stores=len(state.get("selected_stores") or []),
                           n_rows_output=len(rows or []),
                           n_with_price=sum(1 for r in (rows or []) if r.get("Precio Internet")),
                           runtime_s=0,
                           output_file=state.get("output_path").name if state.get("output_path") else "")
        except Exception: pass
        # Consolidar SKUs del archivo de carga al System Manifest.
        try:
            _post_consolidate(state.get("input_df"),
                              sku_col=state.get("sku_col"),
                              easy_col=state.get("easy_col"),
                              desc_col=state.get("desc_col"))
        except Exception: pass
        # Mostrar resumen final igual que on_run_clicked
        if rows:
            retailer = state["retailer"]
            with result_out:
                if retailer == "sodimac":
                    print(f"✅ Listo — {len(rows)} matches")
                else:
                    n_wp = sum(1 for r in rows if r.get("Precio Internet"))
                    print(f"✅ Listo — {len(rows)} filas · {n_wp} con precio")
                print(f"   Excel: {state['output_path'].name}")
                if IN_COLAB:
                    print("\n⬇️  Descargando Excel…")
            if IN_COLAB:
                from engines._excel_utils import download_once
                download_once(state["output_path"], colab_files)
            _show_redownload_button(result_out, state["output_path"])

    _refresh_resume_panel()

    display(widgets.VBox([resume_panel, step1, stores_container, run_container, footer]))