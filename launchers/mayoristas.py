"""Precios Mayoristas — Sodimac.

Invocado desde Precios_Mayoristas.ipynb vía `from launchers import boot; boot("mayoristas")`.
"""

def run():
    from IPython.display import clear_output
    clear_output(wait=True)

    import asyncio, os, sys, json, re, time
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
    _ACTIVITY_URL = "https://script.google.com/macros/s/AKfycbwYNVObEiq8NSslHNsPA3vcNsfPPf8zo6oLAOLVXEGQ7cqT_FwA4PxVxjNaEqt_566Z/exec"
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
    CHECKPOINT_DIR = OUTPUT_DIR / "_pm_checkpoints"
    CHECKPOINT_DIR.mkdir(exist_ok=True)

    # Engine Sodimac importado desde engines/ (refactor v2.0: ya no se embebe inline).
    # Expone TODO menos los dunders (__name__, __doc__, etc.) — las funciones internas
    # con un solo underscore (ej: _build_extract_all_js) sí las necesita la UI.
    from engines import maestra_sodimac as _ss
    globals().update({k: getattr(_ss, k) for k in dir(_ss) if not k.startswith('__')})
    print(f"Scraper Sodimac cargado. {len(ALL_STORES)} tiendas disponibles.")

    # ============================================================
    # Scraper Ventas por Mayor: pagina ?page=N en la landing curada,
    # extrae cards usando el JS del scraper Sodimac (_build_extract_all_js).
    # ============================================================
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output

    VENTAS_MAYOR_BASE = "https://www.sodimac.cl/sodimac-cl/seleccion/ventas-por-mayor?sid=SO_HO_HOM_HBA_409161&store=so_com"
    SECTION_NAME = ""    # Vacio por requerimiento
    SUBCAT_NAME = ""     # Vacio por requerimiento
    MAX_PAGES_PM = 200

    async def scrape_ventas_mayor(page, store, capture_screenshots=False,
                                  page_progress_cb=None, kill_check=None,
                                  partial=None, start_page=1, seen_skus=None):
        """Recorre todas las paginas de la landing y devuelve filas extraidas.

        Reutiliza _build_extract_all_js del scraper Sodimac para la extraccion
        JS de cada pagina. Salida con misma estructura de columnas que el
        scraper de seccion Sodimac.

        Args:
          page: Playwright Page (zona ya seteada).
          store: dict {id, name, region, comuna}.
          capture_screenshots: si True, hace screenshot de cada card en JPEG.
          page_progress_cb: callable(curr, total) para actualizar UI.
          kill_check: callable() -> bool. Si True, corta limpiamente.
          partial: PartialWriter para append por fila.
          start_page: pagina inicial (para reanudacion).
          seen_skus: set de SKUs ya capturados (para dedup en reanudacion).
        """
        result = {"rows": [], "pages": 0, "truncated": False, "failed": False,
                  "empty": False, "stopped": False, "last_page": 0}
        seen = seen_skus if seen_skus is not None else set()
        extract_js = _build_extract_all_js(SECTION_NAME, SUBCAT_NAME)
        total_pages = None
        base_url = None
        page_num = start_page

        while True:
            if kill_check and kill_check():
                result["stopped"] = True
                break

            # Construir URL de la pagina
            if base_url is None:
                sep = "&" if "?" in VENTAS_MAYOR_BASE else "?"
                page_url = VENTAS_MAYOR_BASE if page_num == 1 else f"{VENTAS_MAYOR_BASE}{sep}page={page_num}"
            else:
                base = re.sub(r"([?&])page=\\d+&?", r"\\1", base_url).rstrip("?&")
                sep = "&" if "?" in base else "?"
                page_url = f"{base}{sep}page={page_num}"

            # Navegar
            try:
                await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                if page_num == start_page:
                    result["failed"] = True
                break

            # Esperar grid o empty-state
            try:
                await page.wait_for_selector(
                    f"{SELECTORS['card']}, {SELECTORS['no_results']}",
                    timeout=15000,
                )
            except Exception:
                if page_num == start_page:
                    result["empty"] = True
                break

            has_cards = await page.evaluate(
                f"() => document.querySelectorAll({json.dumps(SELECTORS['card'])}).length"
            )
            if not has_cards:
                if page_num == start_page:
                    result["empty"] = True
                break

            await page.wait_for_timeout(1500)

            # Quitar overlays + lazy-load
            await page.evaluate("""() => {
                document.querySelectorAll('[data-testid="overlay"], [class*="overlay"], [class*="Modal"], [class*="Tooltip"]').forEach(o => o.remove());
            }""")
            for _ in range(5):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await page.wait_for_timeout(250)

            # Extraer cards (mismo JS que scraper Sodimac)
            page_data = await page.evaluate(extract_js, {"sel": SELECTORS, "section": SECTION_NAME, "subcat": SUBCAT_NAME})

            if capture_screenshots:
                cards = await page.query_selector_all(SELECTORS["card"])
                for i, card in enumerate(cards):
                    if i >= len(page_data):
                        break
                    sku = page_data[i].get("SKU") or f"unknown_{page_num}_{i}"
                    img_path = SCREENSHOT_DIR / f"{sku}.jpg"
                    if not img_path.exists():
                        try:
                            await card.scroll_into_view_if_needed()
                            await card.screenshot(path=str(img_path), type="jpeg", quality=80)
                        except Exception:
                            pass
                    page_data[i]["Image Path"] = str(img_path)
            else:
                for d in page_data:
                    d["Image Path"] = ""

            if base_url is None:
                try:
                    base_url = page.url
                except Exception:
                    base_url = VENTAS_MAYOR_BASE

            # Detectar total_pages
            try:
                await page.evaluate("""() => {
                    const p = document.querySelector('[id^="testId-pagination-top-"]');
                    if (p) p.scrollIntoView({behavior:'instant', block:'center'});
                }""")
                await page.wait_for_timeout(400)
            except Exception:
                pass
            try:
                detected_total = await page.evaluate("""() => {
                    const nodes = document.querySelectorAll('[id^="testId-pagination-"]');
                    let max = 1;
                    nodes.forEach(n => {
                        const txt = ((n.textContent || '') + ' ' + (n.getAttribute('aria-label') || '')).trim();
                        const matches = txt.match(/\\d+/g) || [];
                        matches.forEach(m => {
                            const num = parseInt(m, 10);
                            if (!isNaN(num) && num > max && num < 1000) max = num;
                        });
                    });
                    return max;
                }""")
            except Exception:
                detected_total = None
            if detected_total and detected_total > 1:
                if total_pages is None or detected_total > total_pages:
                    total_pages = detected_total

            # Agregar filas nuevas (con metadata de tienda)
            new_in_page = 0
            for d in page_data:
                sku = d.get("SKU")
                if not sku or sku in seen:
                    continue
                seen.add(sku)
                row = dict(d)
                row["Tienda"] = store["id"]
                row["Nombre Tienda"] = store["name"]
                result["rows"].append(row)
                if partial is not None:
                    partial.write(row)
                new_in_page += 1

            result["pages"] = page_num
            result["last_page"] = page_num

            if page_progress_cb is not None:
                try:
                    page_progress_cb(page_num, total_pages)
                except Exception:
                    pass

            # ¿Hay mas paginas?
            if total_pages and page_num >= total_pages:
                break
            next_page = page_num + 1
            if next_page > MAX_PAGES_PM:
                result["truncated"] = True
                break
            if new_in_page == 0 and not total_pages:
                break

            page_num = next_page
            await page.wait_for_timeout(1200)

        return result


    # ============================================================
    # Checkpoint helpers
    # ============================================================
    def _list_unfinished_runs():
        """Lista runs previos sin marca de fin."""
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
        """Carga filas previas del JSONL (para reanudacion)."""
        rows = []
        if jsonl_path.exists():
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except Exception:
                            pass
        return rows


    # ============================================================
    # UI ipywidgets
    # ============================================================

    # Estado UI
    state = {"selected_stores": [], "running": False, "resume_from": None}

    # ─── Paso 1: Tiendas ────────────────────────────────────────
    rm_stores = [s for s in ALL_STORES if s["region"] == "Metropolitana"]
    PRESETS = {
        "Solo La Florida (mas rapido)": [s for s in ALL_STORES if s["id"] == "E510"],
        f"Todas RM ({len(rm_stores)} tiendas)": rm_stores,
        f"Todas Chile ({len(ALL_STORES)} tiendas)": ALL_STORES,
        "Personalizado": None,
    }
    preset_radio = widgets.RadioButtons(
        options=list(PRESETS.keys()),
        value="Solo La Florida (mas rapido)",
        description="Preset:",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="auto"),
    )

    # Panel custom (checkbox por tienda)
    store_panel_items = [
        (f"{s['id']}  {s['name']:<14}  ({s['region']} / {s['comuna']})", s) for s in ALL_STORES
    ]
    store_boxes = []
    for label, val in store_panel_items:
        cb = widgets.Checkbox(value=False, description=label, indent=False,
                              layout=widgets.Layout(width="auto", margin="0"))
        cb._payload = val
        store_boxes.append(cb)
    store_list = widgets.VBox(store_boxes, layout=widgets.Layout(
        max_height="240px", overflow_y="auto", border="1px solid #d0d0d0",
        border_radius="6px", padding="6px 10px", width="540px",
    ))
    btn_all_st = widgets.Button(description="Marcar todas", layout=widgets.Layout(width="130px"))
    btn_none_st = widgets.Button(description="Desmarcar todas", layout=widgets.Layout(width="150px"))
    btn_all_st.on_click(lambda _: [setattr(b, "value", True) for b in store_boxes])
    btn_none_st.on_click(lambda _: [setattr(b, "value", False) for b in store_boxes])
    store_panel = widgets.VBox([
        widgets.HBox([btn_all_st, btn_none_st], layout=widgets.Layout(gap="8px")),
        store_list,
    ])
    store_panel_wrap = widgets.VBox([store_panel], layout=widgets.Layout(display="none"))
    store_eta = widgets.HTML()

    capture_cb = widgets.Checkbox(
        value=False, description="Capturar screenshots de cards (Excel mas pesado)",
        indent=False, layout=widgets.Layout(width="auto"),
    )

    def _update_stores(*_):
        preset = PRESETS[preset_radio.value]
        if preset is None:
            store_panel_wrap.layout.display = ""
            sel = [b._payload for b in store_boxes if b.value]
            state["selected_stores"] = sel if sel else [s for s in ALL_STORES if s["id"] == "E510"]
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
        preset_radio, store_panel_wrap, store_eta,
        widgets.HTML("<h4 style='margin:.8rem 0 .3rem;'>Opciones</h4>"),
        capture_cb,
    ])

    # ─── Paso 2: Reanudacion ────────────────────────────────────
    resume_panel = widgets.VBox([])
    def _refresh_resume_panel():
        unfinished = _list_unfinished_runs()
        if not unfinished:
            resume_panel.children = []
            return
        children = [widgets.HTML(
            "<h4 style='margin:.8rem 0 .3rem;'>Runs interrumpidos (podes reanudar):</h4>"
        )]
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
                f"actual: {last_store_id}, filas guardadas: {rows_n}</div>"
            )
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

    # ─── Paso 3: Ejecutar ───────────────────────────────────────
    run_btn = widgets.Button(description="Iniciar scraping", button_style="success",
                              layout=widgets.Layout(width="220px"))
    running_banner = widgets.HTML()

    store_bar = widgets.IntProgress(min=0, max=100, value=0, description="Tiendas:",
                                    bar_style="info", layout=widgets.Layout(width="540px"),
                                    style={"description_width": "initial"})
    store_pct = widgets.HTML(layout=widgets.Layout(width="110px"))
    page_bar = widgets.IntProgress(min=0, max=100, value=0, description="Paginas:",
                                    bar_style="info", layout=widgets.Layout(width="540px"),
                                    style={"description_width": "initial"})
    page_pct = widgets.HTML(layout=widgets.Layout(width="110px"))
    store_row = widgets.HBox([store_bar, store_pct], layout=widgets.Layout(align_items="center"))
    page_row = widgets.HBox([page_bar, page_pct], layout=widgets.Layout(align_items="center"))
    live_status = widgets.HTML()
    live_metrics = widgets.HTML()
    result_out = widgets.Output()

    def _set_pct(w, value, total):
        if not total:
            w.value = ""
            return
        pct = int(round(100 * value / total))
        w.value = f"<span style='color:#555;font-size:.9em;margin-left:8px;'>{value}/{total} - {pct}%</span>"

    def _running_ui(on):
        if on:
            run_btn.layout.display = "none"
            running_banner.value = (
                "<div style='background:#fff3cd;border-left:4px solid #f39c12;"
                "padding:.6rem;margin:.4rem 0;border-radius:4px;'>"
                "<b>Trabajando</b> - no cierres esta pestaña ni la celda.</div>"
            )
        else:
            run_btn.layout.display = ""
            running_banner.value = ""


    async def _do_scrape():
        """Loop principal: por cada tienda, scrapear todas las paginas."""
        capture = capture_cb.value

        # Determinar si es reanudacion
        resume_info = state.get("resume_from")
        is_resume = bool(resume_info)
        if resume_info:
            cp_path, ckpt = resume_info
            run_id = cp_path.stem
            jsonl_path = CHECKPOINT_DIR / (run_id + ".jsonl")
            stores = ckpt["stores"]
            stores_done = set(ckpt.get("stores_done", []))
            prior_rows = _load_partial_rows(jsonl_path)
            capture = ckpt.get("capture_screenshots", False)
            state["resume_from"] = None
        else:
            run_id = "pm_" + datetime.now().strftime("%Y%m%d_%H%M%S")
            cp_path = CHECKPOINT_DIR / (run_id + ".json")
            jsonl_path = CHECKPOINT_DIR / (run_id + ".jsonl")
            stores = state["selected_stores"]
            stores_done = set()
            prior_rows = []
            ckpt = {
                "ts": run_id.replace("pm_", ""),
                "stores": stores,
                "stores_done": [],
                "current_store_id": None,
                "rows_count": 0,
                "capture_screenshots": capture,
                "finished": False,
            }
            _save_checkpoint(cp_path, ckpt)

        all_rows = list(prior_rows)
        # PartialWriter append-only
        partial = PartialWriter.__new__(PartialWriter)
        partial.path = jsonl_path
        partial._fh = open(jsonl_path, "a", encoding="utf-8")
        partial.count = len(all_rows)

        n_stores = len(stores)
        store_bar.max = n_stores
        store_bar.value = len(stores_done)
        _set_pct(store_pct, len(stores_done), n_stores)
        page_bar.value = 0
        page_bar.max = 1

        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth

        t0 = time.time()
        async with Stealth().use_async(async_playwright()) as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900}, color_scheme="light",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="es-CL", timezone_id="America/Santiago",
            )
            page = await ctx.new_page()

            try:
                for idx, store in enumerate(stores):
                    if store["id"] in stores_done:
                        continue

                    store_bar.value = idx
                    _set_pct(store_pct, idx, n_stores)
                    live_status.value = (
                        f"<b>Sucursal {idx+1}/{n_stores}:</b> {store['name']} "
                        f"({store['region']} / {store['comuna']}) - fijando zona..."
                    )
                    ckpt["current_store_id"] = store["id"]
                    _save_checkpoint(cp_path, ckpt)

                    try:
                        ok = await set_zone_with_retry(page, store["region"], store["comuna"])
                    except Exception as e:
                        ok = False
                        live_status.value = f"<span style='color:#c0392b'>Error set_zone {store['name']}: {e}</span>"
                    if not ok:
                        live_status.value = f"<span style='color:#c0392b'>No pude fijar zona en {store['name']}, salto.</span>"
                        stores_done.add(store["id"])
                        ckpt["stores_done"] = list(stores_done)
                        _save_checkpoint(cp_path, ckpt)
                        continue

                    live_status.value = f"<b>Sucursal {idx+1}/{n_stores}:</b> {store['name']} - scrapeando..."
                    page_bar.value = 0; page_bar.max = 1
                    page_bar.description = "Paginas:"

                    def _page_cb(curr, total):
                        if total and total > 0:
                            page_bar.max = total
                            page_bar.value = min(curr, total)
                            page_bar.description = f"Paginas {curr}/{total}"
                            _set_pct(page_pct, curr, total)
                        else:
                            page_bar.max = max(page_bar.max, curr)
                            page_bar.value = curr
                            page_bar.description = f"Pagina {curr}"
                            _set_pct(page_pct, curr, page_bar.max)

                    res = await scrape_ventas_mayor(
                        page, store,
                        capture_screenshots=capture,
                        page_progress_cb=_page_cb,
                        kill_check=None,
                        partial=partial,
                    )
                    all_rows.extend(res["rows"])
                    ckpt["rows_count"] = len(all_rows)

                    stores_done.add(store["id"])
                    ckpt["stores_done"] = list(stores_done)
                    _save_checkpoint(cp_path, ckpt)

                    elapsed = time.time() - t0
                    rate = len(all_rows) / max(elapsed, 1) * 60
                    live_metrics.value = (
                        f"<b>Filas:</b> {len(all_rows)}  - "
                        f"<b>Tiendas:</b> {len(stores_done)}/{n_stores}  - "
                        f"<b>{rate:.0f}</b> filas/min"
                    )
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass
                partial.close()

        # Si todas las tiendas se completaron, marcar finished
        if len(stores_done) == n_stores:
            ckpt["finished"] = True
            _save_checkpoint(cp_path, ckpt)

        # Escribir Excel final
        if all_rows:
            out_name = f"sodimac_ventas_mayor_{run_id.replace('pm_','')}.xlsx"
            out_path = OUTPUT_DIR / out_name
            try:
                # Columnas específicas de Precios Mayoristas (las del Excel template del cliente).
                _PM_OUTPUT_COLS = [
                    "Tienda", "Nombre Tienda", "Sección", "Subcategoría",
                    "Vendedor", "Marca", "SKU", "Descripción Producto",
                    "Precio Normal", "Precio Internet", "% Descuento",
                    "Precio CMR", "Precio Mayorista", "Descuento Mayorista",
                    "Todos los Precios", "URL",
                ]
                write_excel(all_rows, str(out_path), columns=_PM_OUTPUT_COLS)
                with result_out:
                    clear_output()
                    print(f"Excel generado: {out_name}  ({len(all_rows)} filas, {len(stores_done)}/{n_stores} tiendas)")
                try:
                    _log_activity(retailer="sodimac",
                                   mode="pm-resume" if is_resume else "pm",
                                   n_skus=0,
                                   n_stores=n_stores,
                                   n_rows_output=len(all_rows),
                                   n_with_price=0,
                                   runtime_s=int(time.time() - t0),
                                   output_file=out_name)
                except Exception: pass
                if IN_COLAB and colab_files is not None:
                    try:
                        colab_files.download(str(out_path))
                    except Exception as e:
                        with result_out:
                            print(f"download fallo: {e}")
                    _redl_btn = widgets.Button(
                        description="Descargar Excel de nuevo",
                        icon="download", button_style="info",
                        layout=widgets.Layout(width="260px"),
                    )
                    def _redl(_p=str(out_path)):
                        try: colab_files.download(_p)
                        except Exception as _e:
                            with result_out: print(f"download fallo: {_e}")
                    _redl_btn.on_click(lambda _b: _redl())
                    with result_out:
                        display(_redl_btn)
            except Exception as e:
                with result_out:
                    clear_output()
                    print(f"write_excel fallo: {e}")
        else:
            with result_out:
                clear_output()
                print("Sin filas para escribir.")


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
        _start_scrape()
    run_btn.on_click(_on_run)


    # Mostrar todo
    step3 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.8rem 0 .3rem;'>Paso 2 - Ejecutar</h4>"),
        run_btn,
        running_banner,
        store_row, page_row, live_status, live_metrics, result_out,
    ])

    footer = widgets.HTML(
        "<div style='margin-top:1.5rem;padding-top:.6rem;border-top:1px solid #e0e0e0;"
        "text-align:right;color:#aaa;font-size:.75em;font-family:sans-serif;font-style:italic;'>"
        "Precios Mayoristas - landing Sodimac /seleccion/ventas-por-mayor</div>"
    )

    _refresh_resume_panel()

    display(widgets.VBox([step1, resume_panel, step3, footer]))