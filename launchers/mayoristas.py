# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Precios Mayoristas — Sodimac (motor BROWSERLESS, v2.17.0).

Invocado desde Precios_Mayoristas.ipynb vía `from launchers import boot; boot("mayoristas")`.

Reescrito para usar `engines/mayoristas_fast.py`: recorre el ÁRBOL COMPLETO de
categorías por HTTP plano (leyendo `__NEXT_DATA__`) y filtra en código a los
productos con precio mayorista (promo PRECIO+PRO). Reemplaza el barrido de la
landing curada `ventas-por-mayor` (que era un subconjunto ~864) y el render DOM
por Playwright. El navegador se usa UNA vez por zona (warmup + set_zone + árbol);
el resto es HTTP paralelo. Trade-off: sin screenshots de card (no aplica al modo
browserless) — la herramienta entrega la tabla de precios.
"""

def run():
    from IPython.display import clear_output
    clear_output(wait=True)

    import asyncio, os, sys, json, time
    from datetime import datetime
    from pathlib import Path

    import nest_asyncio
    nest_asyncio.apply()

    try:
        from google.colab import files as colab_files
        IN_COLAB = True
    except Exception:
        colab_files = None
        IN_COLAB = False

    # --- Telemetry (Systems Manifest / Activity sheet) -----------------
    import uuid as _uuid
    _ACTIVITY_URL = "https://script.google.com/macros/s/AKfycbzALm18Xuw9c7U0tcAE0u1lPvq1j4P5kCxIJvdkDuG5MLVrqKyWd5qt-Kjb-TSP3B82/exec"
    _ACTIVITY_TOKEN = "6kT2hQjLp_VxR8mN3wYsZ-aF7bGdEcU4"
    _BUILD_HASH = "5c4dba0ea3acb1375cdffccab4d63aad371fe0124f0b915fe6e05dd30d3f0577"
    _COLAB_TAG = "precios-mayoristas"
    _SESSION_ID = globals().get("_SESSION_ID") or _uuid.uuid4().hex[:8]
    globals()["_SESSION_ID"] = _SESSION_ID
    def _user_hint():
        try:
            for k in ("COLAB_USER", "USER", "JUPYTERHUB_USER"):
                v = os.environ.get(k)
                if v: return v
        except Exception:
            pass
        return ""
    def _log_activity(retailer="sodimac", mode="pm", n_skus=0, n_stores=0,
                       n_rows_output=0, n_with_price=0, runtime_s=0, output_file=""):
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

    OUTPUT_DIR = Path.cwd()
    # ─── Checkpoints (dir compartido engines/_checkpoints.py) ────────────
    # Naming propio pm_*.json (+ .jsonl); usa el módulo para el fallback
    # RUIDOSO de Drive (fix #2) y TTL 12h por RUN (fix #4).
    from engines import _checkpoints as _ckpts
    CHECKPOINT_DIR, _ckpt_ephemeral = _ckpts.resolve_dir(
        in_colab=IN_COLAB, drive_subdir="pm_scraper_checkpoints",
        local_name="_pm_checkpoints")

    def _pm_purge_expired(ttl=_ckpts.DEFAULT_TTL_SECS):
        """Borra runs (pm_*.json + su .jsonl) cuyo archivo más nuevo venció."""
        import time as _t
        now = _t.time(); groups = {}
        for p in list(CHECKPOINT_DIR.glob("pm_*.json")) + list(CHECKPOINT_DIR.glob("pm_*.jsonl")):
            try: mt = p.stat().st_mtime
            except Exception: continue
            g = groups.setdefault(p.stem, [0, []])
            g[0] = max(g[0], mt); g[1].append(p)
        for _rid, (mt, paths) in groups.items():
            if now - mt > ttl:
                for p in paths:
                    try: p.unlink()
                    except Exception: pass
    _pm_purge_expired()

    # Motor browserless + helpers de zona/tiendas y write_excel de la Maestra.
    from engines import mayoristas_fast as _mf
    from engines import maestra_sodimac as _ss
    ALL_STORES = _ss.ALL_STORES
    write_excel = _ss.write_excel
    print(f"Precios Mayoristas (browserless) cargado. {len(ALL_STORES)} tiendas disponibles.")

    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output

    if _ckpt_ephemeral:  # Drive no montó → checkpoints efímeros (fix #2)
        display(HTML(_ckpts.ephemeral_warning_html("Precios Mayoristas")))

    # Columnas de salida (sin Imagen — modo browserless).
    _PM_OUTPUT_COLS = _mf.OUTPUT_COLS
    WORKERS = 8  # paralelismo HTTP (validado en vivo sin gatillar 429 de Cloudflare)

    # ============================================================
    # Checkpoint helpers
    # ============================================================
    def _list_unfinished_runs():
        runs = []
        for cp in sorted(CHECKPOINT_DIR.glob("pm_*.json")):
            try:
                data = json.loads(cp.read_text(encoding="utf-8"))
                if not data.get("finished"):
                    runs.append((cp, data))
            except Exception:
                pass
        return runs

    def _save_checkpoint(cp_path, data):
        cp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_partial_rows(jsonl_path):
        rows = []
        if jsonl_path.exists():
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try: rows.append(json.loads(line))
                        except Exception: pass
        return rows

    # ============================================================
    # UI ipywidgets
    # ============================================================
    state = {"selected_stores": [], "running": False, "resume_from": None,
             "tree": None, "sections": []}

    # ─── Paso 1: Tiendas ────────────────────────────────────────
    rm_stores = [s for s in ALL_STORES if s["region"] == "Metropolitana"]
    PRESETS = {
        "Solo Cerrillos (mas rapido)": [s for s in ALL_STORES if s["id"] == "E522"],
        f"Todas RM ({len(rm_stores)} tiendas)": rm_stores,
        f"Todas Chile ({len(ALL_STORES)} tiendas)": ALL_STORES,
        "Personalizado": None,
    }
    preset_radio = widgets.RadioButtons(
        options=list(PRESETS.keys()),
        value="Solo Cerrillos (mas rapido)",
        description="Preset:",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="auto"),
    )
    store_boxes = []
    for s in ALL_STORES:
        label = f"{s['id']}  {s['name']:<14}  ({s['region']} / {s['comuna']})"
        cb = widgets.Checkbox(value=False, description=label, indent=False,
                              layout=widgets.Layout(width="auto", margin="0"))
        cb._payload = s
        store_boxes.append(cb)
    store_list = widgets.VBox(store_boxes, layout=widgets.Layout(
        max_height="240px", overflow_y="auto", border="1px solid #d0d0d0",
        border_radius="6px", padding="6px 10px", width="540px"))
    btn_all_st = widgets.Button(description="Marcar todas", layout=widgets.Layout(width="130px"))
    btn_none_st = widgets.Button(description="Desmarcar todas", layout=widgets.Layout(width="150px"))
    btn_all_st.on_click(lambda _: [setattr(b, "value", True) for b in store_boxes])
    btn_none_st.on_click(lambda _: [setattr(b, "value", False) for b in store_boxes])
    store_panel = widgets.VBox([
        widgets.HBox([btn_all_st, btn_none_st], layout=widgets.Layout(gap="8px")),
        store_list])
    store_panel_wrap = widgets.VBox([store_panel], layout=widgets.Layout(display="none"))
    store_eta = widgets.HTML()

    def _update_stores(*_):
        preset = PRESETS[preset_radio.value]
        if preset is None:
            store_panel_wrap.layout.display = ""
            sel = [b._payload for b in store_boxes if b.value]
            state["selected_stores"] = sel if sel else [s for s in ALL_STORES if s["id"] == "E522"]
        else:
            store_panel_wrap.layout.display = "none"
            state["selected_stores"] = preset
        n = len(state["selected_stores"])
        if n == 0:
            store_eta.value = "<span style='color:#c0392b'>Selecciona al menos una tienda</span>"
        else:
            store_eta.value = f"<span style='color:#27ae60'>{n} tienda(s) seleccionada(s)</span>"
    preset_radio.observe(_update_stores, "value")
    for b in store_boxes:
        b.observe(_update_stores, "value")
    _update_stores()

    step1 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.3rem 0;'>Paso 1 - Sucursales</h4>"),
        preset_radio, store_panel_wrap, store_eta])

    # ─── Paso 2: Alcance (todo / secciones / URL directa) ───────
    scope_radio = widgets.RadioButtons(
        options=["Todo el catálogo (mas completo)", "Elegir secciones", "URL personalizada"],
        value="Todo el catálogo (mas completo)",
        description="Alcance:",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="auto"))

    # Panel URL directa (para categorías complicadas, ej. flooring).
    url_input = widgets.Text(
        placeholder="https://www.sodimac.cl/sodimac-cl/lista/catXXXX/...",
        description="URL:", style={"description_width": "initial"},
        layout=widgets.Layout(width="540px"))
    url_name_input = widgets.Text(
        placeholder="Nombre para la sección (ej. Pisos Flotantes)",
        description="Nombre:", style={"description_width": "initial"},
        layout=widgets.Layout(width="540px"))
    url_panel = widgets.VBox([
        widgets.HTML("<div style='color:#666;font-size:.85em;'>Pega el link de la categoría "
                     "de Sodimac; se recorre esa página (y su paginación) filtrando mayoristas.</div>"),
        url_input, url_name_input],
        layout=widgets.Layout(display="none"))

    load_btn = widgets.Button(description="🔍 Cargar secciones", button_style="",
                              layout=widgets.Layout(width="200px"))
    load_status = widgets.HTML()
    section_boxes_box = widgets.VBox([], layout=widgets.Layout(
        max_height="220px", overflow_y="auto", border="1px solid #d0d0d0",
        border_radius="6px", padding="6px 10px", width="540px"))
    btn_all_sec = widgets.Button(description="Marcar todas", layout=widgets.Layout(width="130px"))
    btn_none_sec = widgets.Button(description="Desmarcar todas", layout=widgets.Layout(width="150px"))
    btn_inv_sec = widgets.Button(description="Invertir", layout=widgets.Layout(width="110px"))
    section_counter = widgets.HTML()
    section_boxes = []

    def _update_sec_counter(*_):
        n = sum(1 for b in section_boxes if b.value)
        section_counter.value = f"<span style='color:#555'>{n}/{len(section_boxes)} secciones</span>"
    btn_all_sec.on_click(lambda _: ([setattr(b, "value", True) for b in section_boxes], _update_sec_counter()))
    btn_none_sec.on_click(lambda _: ([setattr(b, "value", False) for b in section_boxes], _update_sec_counter()))
    btn_inv_sec.on_click(lambda _: ([setattr(b, "value", not b.value) for b in section_boxes], _update_sec_counter()))

    section_panel = widgets.VBox([
        widgets.HBox([btn_all_sec, btn_none_sec, btn_inv_sec], layout=widgets.Layout(gap="8px")),
        section_boxes_box, section_counter],
        layout=widgets.Layout(display="none"))

    def _build_section_boxes():
        tree = state.get("tree") or []
        section_boxes.clear()
        for sec_name, subs in tree:
            cb = widgets.Checkbox(value=True, description=f"{sec_name}  ({len(subs)} subcats)",
                                  indent=False, layout=widgets.Layout(width="auto", margin="0"))
            cb._sec = sec_name
            cb.observe(_update_sec_counter, "value")
            section_boxes.append(cb)
        section_boxes_box.children = section_boxes
        _update_sec_counter()

    async def _load_sections():
        stores = state["selected_stores"]
        if not stores:
            load_status.value = "<span style='color:#c0392b'>Selecciona una tienda primero.</span>"
            return
        load_btn.disabled = True
        load_status.value = "<span style='color:#555'>Abriendo navegador, fijando zona y descubriendo el árbol… (~20s)</span>"
        try:
            cookie, tree = await _mf.open_session(stores[0], headless=True)
            if not cookie or not tree:
                load_status.value = "<span style='color:#c0392b'>No pude fijar zona / descubrir secciones. Reintenta.</span>"
                return
            state["tree"] = tree
            state["load_cookie"] = cookie
            state["load_store_id"] = stores[0]["id"]
            n_sub = sum(len(s) for _, s in tree)
            _build_section_boxes()
            load_status.value = (f"<span style='color:#27ae60'>{len(tree)} secciones / {n_sub} subcategorías "
                                 f"descubiertas (zona {stores[0]['name']}).</span>")
        except Exception as e:
            load_status.value = f"<span style='color:#c0392b'>Error: {e}</span>"
        finally:
            load_btn.disabled = False
    load_btn.on_click(lambda _: asyncio.run(_load_sections()))

    def _update_scope(*_):
        is_sec = scope_radio.value.startswith("Elegir")
        is_url = scope_radio.value.startswith("URL")
        section_panel.layout.display = "" if is_sec else "none"
        url_panel.layout.display = "" if is_url else "none"
        # "Cargar secciones" sólo aplica al modo de secciones.
        load_btn.layout.display = "none" if is_url else ""
    scope_radio.observe(_update_scope, "value")
    _update_scope()

    step2 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.8rem 0 .3rem;'>Paso 2 - Alcance</h4>"),
        widgets.HTML("<div style='color:#666;font-size:.85em;margin-bottom:.3rem;'>"
                     "Recorre el catálogo y conserva sólo los productos con <b>precio mayorista</b> "
                     "(PRECIO+PRO). 'Todo el catálogo' ≈ 9 min por zona.</div>"),
        scope_radio, load_btn, load_status, section_panel, url_panel])

    # ─── Paso 3: Reanudacion ────────────────────────────────────
    resume_panel = widgets.VBox([])
    def _refresh_resume_panel():
        unfinished = _list_unfinished_runs()
        if not unfinished:
            resume_panel.children = []
            return
        children = [widgets.HTML(
            "<h4 style='margin:.8rem 0 .3rem;'>Runs interrumpidos (puedes reanudar):</h4>")]
        for cp_path, data in unfinished:
            meta = data
            ts = meta.get("ts", cp_path.stem.replace("pm_", ""))
            stores_done = meta.get("stores_done", [])
            stores_total = len(meta.get("stores", []))
            last_store_id = meta.get("current_store_id", "?")
            rows_n = meta.get("rows_count", 0)
            info = widgets.HTML(
                f"<div style='padding:.4rem;border-left:3px solid #f39c12;background:#fff8e1;margin:.2rem 0;'>"
                f"<b>{ts}</b> - {len(stores_done)}/{stores_total} tiendas hechas, "
                f"actual: {last_store_id}, filas guardadas: {rows_n}</div>")
            btn_resume = widgets.Button(description=f"Reanudar {ts}", button_style="warning",
                                         layout=widgets.Layout(width="220px"))
            btn_discard = widgets.Button(description="Descartar", layout=widgets.Layout(width="120px"))
            def _make_resume(cp=cp_path, d=data):
                def _f(_):
                    state["resume_from"] = (cp, d)
                    live_status.value = f"<b>Reanudando run {cp.stem}</b>"
                    _start_scrape()
                return _f
            def _make_discard(cp=cp_path):
                def _f(_):
                    try:
                        cp.unlink()
                        jsonl = CHECKPOINT_DIR / (cp.stem + ".jsonl")
                        if jsonl.exists(): jsonl.unlink()
                    except Exception: pass
                    _refresh_resume_panel()
                return _f
            btn_resume.on_click(_make_resume())
            btn_discard.on_click(_make_discard())
            children.append(widgets.HBox([info, btn_resume, btn_discard]))
        resume_panel.children = children

    # ─── Paso 4: Ejecutar ───────────────────────────────────────
    run_btn = widgets.Button(description="Iniciar scraping", button_style="success",
                              layout=widgets.Layout(width="220px"))
    running_banner = widgets.HTML()
    store_bar = widgets.IntProgress(min=0, max=100, value=0, description="Tiendas:",
                                    bar_style="info", layout=widgets.Layout(width="540px"),
                                    style={"description_width": "initial"})
    store_pct = widgets.HTML(layout=widgets.Layout(width="110px"))
    sub_bar = widgets.IntProgress(min=0, max=100, value=0, description="Subcats:",
                                  bar_style="info", layout=widgets.Layout(width="540px"),
                                  style={"description_width": "initial"})
    sub_pct = widgets.HTML(layout=widgets.Layout(width="110px"))
    store_row = widgets.HBox([store_bar, store_pct], layout=widgets.Layout(align_items="center"))
    sub_row = widgets.HBox([sub_bar, sub_pct], layout=widgets.Layout(align_items="center"))
    live_status = widgets.HTML()
    live_metrics = widgets.HTML()
    result_out = widgets.Output()

    def _set_pct(w, value, total):
        if not total:
            w.value = ""; return
        pct = int(round(100 * value / total))
        w.value = f"<span style='color:#555;font-size:.9em;margin-left:8px;'>{value}/{total} - {pct}%</span>"

    def _running_ui(on):
        if on:
            run_btn.layout.display = "none"
            running_banner.value = (
                "<div style='background:#fff3cd;border-left:4px solid #f39c12;"
                "padding:.6rem;margin:.4rem 0;border-radius:4px;'>"
                "<b>Trabajando</b> - no cierres esta pestaña ni la celda.</div>")
        else:
            run_btn.layout.display = ""
            running_banner.value = ""

    def _selected_sections():
        """Nombres de sección elegidos (o None = todas)."""
        if scope_radio.value.startswith("Todo"):
            return None
        return [b._sec for b in section_boxes if b.value]

    def _url_scope():
        """(url, nombre) si el alcance es URL personalizada; None si no."""
        if not scope_radio.value.startswith("URL"):
            return None
        url = (url_input.value or "").strip()
        if not url:
            return None
        name = (url_name_input.value or "").strip() or "URL personalizada"
        return url, name

    def _filter_tree(tree, sections):
        if sections is None:
            return tree
        wanted = set(sections)
        return [(sec, subs) for sec, subs in tree if sec in wanted]

    async def _do_scrape():
        # Determinar si es reanudacion
        resume_info = state.get("resume_from")
        is_resume = bool(resume_info)
        if resume_info:
            cp_path, ckpt = resume_info
            run_id = cp_path.stem
            jsonl_path = CHECKPOINT_DIR / (run_id + ".jsonl")
            stores = ckpt["stores"]
            stores_done = set(ckpt.get("stores_done", []))
            sections = ckpt.get("sections")  # None = todas
            url_scope = ckpt.get("url_scope")  # [url, nombre] o None
            prior_rows = _load_partial_rows(jsonl_path)
            state["resume_from"] = None
        else:
            run_id = "pm_" + datetime.now().strftime("%Y%m%d_%H%M%S")
            cp_path = CHECKPOINT_DIR / (run_id + ".json")
            jsonl_path = CHECKPOINT_DIR / (run_id + ".jsonl")
            stores = state["selected_stores"]
            stores_done = set()
            _us = _url_scope()
            url_scope = list(_us) if _us else None
            sections = None if url_scope else _selected_sections()
            prior_rows = []
            ckpt = {
                "ts": run_id.replace("pm_", ""),
                "stores": stores, "stores_done": [], "current_store_id": None,
                "rows_count": 0, "sections": sections, "url_scope": url_scope,
                "finished": False,
            }
            _save_checkpoint(cp_path, ckpt)

        all_rows = list(prior_rows)
        jf = open(jsonl_path, "a", encoding="utf-8")

        n_stores = len(stores)
        store_bar.max = n_stores
        store_bar.value = len(stores_done)
        _set_pct(store_pct, len(stores_done), n_stores)

        t0 = time.time()

        # Árbol: reusar el descubierto en "Cargar secciones" si es el mismo primer
        # store; si no, se descubre dentro de open_session por tienda.
        cached_tree = state.get("tree")

        for idx, store in enumerate(stores):
            if store["id"] in stores_done:
                continue
            store_bar.value = idx
            _set_pct(store_pct, idx, n_stores)
            live_status.value = (f"<b>Sucursal {idx+1}/{n_stores}:</b> {store['name']} "
                                 f"({store['comuna']}) - fijando zona y descubriendo árbol...")
            ckpt["current_store_id"] = store["id"]
            _save_checkpoint(cp_path, ckpt)

            # Handshake de zona + árbol (navegador 1 vez por tienda).
            try:
                if url_scope:
                    # Modo URL directa: sólo cookie de zona, árbol = 1 nodo.
                    cookie = await _mf.fetch_zone_cookie(store, headless=True)
                    tree = [(url_scope[1], [(url_scope[1], url_scope[0])])]
                elif cached_tree and state.get("load_store_id") == store["id"] and state.get("load_cookie"):
                    cookie, tree = state["load_cookie"], cached_tree
                else:
                    cookie, tree = await _mf.open_session(store, headless=True)
            except Exception as e:
                cookie, tree = "", []
                live_status.value = f"<span style='color:#c0392b'>Error zona/árbol {store['name']}: {e}</span>"
            if not cookie or not tree:
                live_status.value = f"<span style='color:#c0392b'>No pude preparar {store['name']}, salto.</span>"
                stores_done.add(store["id"]); ckpt["stores_done"] = list(stores_done)
                _save_checkpoint(cp_path, ckpt); continue

            tree = _filter_tree(tree, sections)
            n_sub = sum(len(s) for _, s in tree)
            sub_bar.value = 0; sub_bar.max = max(n_sub, 1)
            live_status.value = f"<b>Sucursal {idx+1}/{n_stores}:</b> {store['name']} - barriendo {n_sub} subcats..."

            store_rows = []
            def _on_row(row):
                store_rows.append(row)
                jf.write(json.dumps(row, ensure_ascii=False) + "\n")
            def _subcat_cb(i, total, sec, name, kept, scanned):
                sub_bar.max = total; sub_bar.value = i
                sub_bar.description = f"Subcats {i}/{total}"
                _set_pct(sub_pct, i, total)
                elapsed = time.time() - t0
                live_metrics.value = (
                    f"<b>Mayoristas:</b> {len(all_rows)+len(store_rows)}  - "
                    f"<b>Sección:</b> {sec[:20]} / {name[:20]}  - "
                    f"<b>{(len(all_rows)+len(store_rows))/max(elapsed,1)*60:.0f}</b> filas/min")

            # scrape_all_wholesale es síncrono (HTTP+ThreadPool). Lo corremos en un
            # hilo para no bloquear el event loop del notebook.
            rows = await asyncio.to_thread(
                _mf.scrape_all_wholesale, cookie, tree, store,
                wholesale_only=True, only_sodimac=True,
                on_row=_on_row, subcat_cb=_subcat_cb, workers=WORKERS)

            all_rows.extend(rows)
            ckpt["rows_count"] = len(all_rows)
            stores_done.add(store["id"]); ckpt["stores_done"] = list(stores_done)
            _save_checkpoint(cp_path, ckpt)
            jf.flush()

        jf.close()

        if len(stores_done) == n_stores:
            ckpt["finished"] = True
            _save_checkpoint(cp_path, ckpt)

        if all_rows:
            out_name = f"sodimac_mayoristas_{run_id.replace('pm_','')}.xlsx"
            out_path = OUTPUT_DIR / out_name
            try:
                write_excel(all_rows, str(out_path), columns=_PM_OUTPUT_COLS, with_images=False)
                with result_out:
                    clear_output()
                    print(f"Excel generado: {out_name}  ({len(all_rows)} filas, {len(stores_done)}/{n_stores} tiendas)")
                if ckpt.get("finished"):
                    for _p in (cp_path, jsonl_path):
                        try:
                            if _p.exists(): _p.unlink()
                        except Exception: pass
                try:
                    _log_activity(retailer="sodimac",
                                   mode="pm-resume" if is_resume else "pm",
                                   n_skus=0, n_stores=n_stores,
                                   n_rows_output=len(all_rows),
                                   n_with_price=sum(1 for r in all_rows if r.get("Precio Mayorista")),
                                   runtime_s=int(time.time() - t0), output_file=out_name)
                except Exception: pass
                if IN_COLAB and colab_files is not None:
                    try:
                        from engines._excel_utils import download_once
                        download_once(str(out_path), colab_files)
                    except Exception as e:
                        with result_out: print(f"download fallo: {e}")
                    _redl_btn = widgets.Button(description="Descargar Excel de nuevo",
                        icon="download", button_style="info", layout=widgets.Layout(width="260px"))
                    def _redl(_p=str(out_path)):
                        try:
                            from engines._excel_utils import download_once
                            download_once(_p, colab_files)
                        except Exception as _e:
                            with result_out: print(f"download fallo: {_e}")
                    _redl_btn.on_click(lambda _b: _redl())
                    with result_out: display(_redl_btn)
            except Exception as e:
                with result_out:
                    clear_output(); print(f"write_excel fallo: {e}")
        else:
            with result_out:
                clear_output(); print("Sin productos con precio mayorista para escribir.")

    def _start_scrape():
        if state["running"]:
            return
        state["running"] = True
        _running_ui(True)
        try:
            asyncio.run(_do_scrape())
        finally:
            state["running"] = False
            _running_ui(False)
            _refresh_resume_panel()

    def _on_run(_):
        if not state["selected_stores"]:
            live_status.value = "<span style='color:#c0392b'>Selecciona al menos una sucursal.</span>"
            return
        if scope_radio.value.startswith("Elegir"):
            if not state.get("tree"):
                live_status.value = "<span style='color:#c0392b'>Primero pulsa 'Cargar secciones'.</span>"
                return
            if not _selected_sections():
                live_status.value = "<span style='color:#c0392b'>Marca al menos una sección.</span>"
                return
        if scope_radio.value.startswith("URL") and not _url_scope():
            live_status.value = "<span style='color:#c0392b'>Pega una URL de categoría.</span>"
            return
        _start_scrape()
    run_btn.on_click(_on_run)

    step4 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.8rem 0 .3rem;'>Paso 3 - Ejecutar</h4>"),
        run_btn, running_banner,
        store_row, sub_row, live_status, live_metrics, result_out])

    footer = widgets.HTML(
        "<div style='margin-top:1.5rem;padding-top:.6rem;border-top:1px solid #e0e0e0;"
        "text-align:right;color:#aaa;font-size:.75em;font-family:sans-serif;font-style:italic;'>"
        "Precios Mayoristas — Carlos Cruz E.<br/><span style='font-size:.85em;'>Copyright (c) 2026 Carlos Cruz Errazuriz · All rights reserved · Proprietary — No unauthorized use or distribution</span></div>")

    _refresh_resume_panel()
    display(widgets.VBox([step1, step2, resume_panel, step4, footer]))
