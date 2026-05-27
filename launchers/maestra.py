"""Maestra Sección — Sodimac/Falabella/Construmart.

Invocado desde Maestra_Seccion.ipynb vía `from launchers import boot; boot("maestra")`.
"""

def run():
    from IPython.display import clear_output
    clear_output(wait=True)

    import sys, json
    from pathlib import Path

    try:
        from google.colab import files as colab_files
        IN_COLAB = True
    except Exception:
        colab_files = None
        IN_COLAB = False

    OUTPUT_DIR = Path.cwd()


    # ===== Codigo fuente de los 3 scrapers (.py) =====
    # ===== UIs ipywidgets de cada notebook standalone (celda 3) =====
    _UI_SODIMAC = r'''import asyncio, re
    from datetime import datetime
    from pathlib import Path
    import nest_asyncio
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    nest_asyncio.apply()

    clear_output(wait=True)  # reset celda — evita duplicar UI al re-ejecutar

    try:
        from google.colab import files as colab_files
        IN_COLAB = True
    except ImportError:
        IN_COLAB = False

    OUTPUT_DIR = Path.cwd()

    # ─── Telemetry: log activity al Sheet ──────────────────────────────
    import uuid as _uuid
    _ACTIVITY_URL = "https://script.google.com/macros/s/AKfycbwYNVObEiq8NSslHNsPA3vcNsfPPf8zo6oLAOLVXEGQ7cqT_FwA4PxVxjNaEqt_566Z/exec"
    _ACTIVITY_TOKEN = "6kT2hQjLp_VxR8mN3wYsZ-aF7bGdEcU4"
    _BUILD_HASH = "5c4dba0ea3acb1375cdffccab4d63aad371fe0124f0b915fe6e05dd30d3f0577"
    _COLAB_TAG = "seccion-sodimac"
    _SESSION_ID = globals().get("_SESSION_ID") or _uuid.uuid4().hex[:8]
    globals()["_SESSION_ID"] = _SESSION_ID

    def _user_hint():
        """Intenta obtener email del usuario de Colab; falla silencioso."""
        try:
            import subprocess
            # En Colab, /tmp/__colab_user_email__ no existe; intentar via auth
            from google.colab import auth as _ca
            # auth.authenticate_user() pediría permiso — no lo hacemos.
            # Mejor: leer env si existe.
            import os
            for k in ("COLAB_USER", "USER", "JUPYTERHUB_USER"):
                v = os.environ.get(k)
                if v: return v
        except Exception:
            pass
        return ""

    def _log_activity(retailer="", mode="", n_skus=0, n_stores=0,
                       n_rows_output=0, n_with_price=0, runtime_s=0,
                       output_file=""):
        """Mandar 1 POST con resumen del run. Nunca propaga errores."""
        try:
            import requests as _rq
            _rq.post(_ACTIVITY_URL, json={
                "token": _ACTIVITY_TOKEN,
                "session_id": _SESSION_ID,
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
            pass  # silencioso — no romper el flow del usuario
    # Fallback PARTIAL_DIR: si no estamos en Colab o Drive mount falla,
    # usar filesystem efímero local del Colab/notebook.
    PARTIAL_DIR = Path.cwd() / "_sodimac_partials"
    PARTIAL_DIR.mkdir(parents=True, exist_ok=True)
    state = {"sections": None, "selected_stores": [], "running": False, "pending_resume": None}

    # ─── Checkpoint en Google Drive + autolimpieza de 12 h ───────────────
    import os as _os, time as _time, json as _json
    PARTIAL_TTL_SECONDS = 12 * 3600  # 12 horas
    if IN_COLAB:
        try:
            from google.colab import drive as _drive
            if not _os.path.isdir("/content/drive/MyDrive"):
                _drive.mount("/content/drive", force_remount=False)
            _drv = Path("/content/drive/MyDrive/sodimac_scraper_partials")
            _drv.mkdir(parents=True, exist_ok=True)
            PARTIAL_DIR = _drv  # redirige PartialWriter al Drive
        except Exception as _e:
            print(f"⚠️ No se pudo montar Drive ({_e}); usando filesystem efímero.")

    # Limpieza inicial: borra checkpoints con más de 12 h de vida
    _now = _time.time()
    for _glob in ("*.jsonl", "*.meta.json", "*.done.tsv"):
        for _p in PARTIAL_DIR.glob(_glob):
            try:
                if _now - _p.stat().st_mtime > PARTIAL_TTL_SECONDS:
                    _p.unlink()
            except Exception:
                pass

    def _meta_path(run_id): return PARTIAL_DIR / f"{run_id}.meta.json"
    def _done_path(run_id): return PARTIAL_DIR / f"{run_id}.done.tsv"

    def _write_meta(run_id, payload):
        _meta_path(run_id).write_text(_json.dumps(payload, ensure_ascii=False, indent=2))

    def _append_done(run_id, store_id, subcat_name):
        with open(_done_path(run_id), "a", encoding="utf-8") as f:
            f.write(f"{store_id}\t{subcat_name}\n")

    def _read_done(run_id):
        p = _done_path(run_id)
        if not p.exists(): return set()
        done = set()
        for line in p.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) == 2:
                done.add((parts[0], parts[1]))
        return done

    def _cleanup_run(run_id):
        for p in (PARTIAL_DIR / f"{run_id}.jsonl", _meta_path(run_id), _done_path(run_id)):
            try: p.unlink()
            except Exception: pass

    def _find_resumable_all():
        """Devuelve lista [(run_id, meta, prior_rows, done_set), ...] de partials vigentes, más reciente primero."""
        out = []
        metas = sorted(PARTIAL_DIR.glob("*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for m in metas:
            run_id = m.name[:-len(".meta.json")]
            jsonl = PARTIAL_DIR / f"{run_id}.jsonl"
            if not jsonl.exists():
                continue
            try:
                meta = _json.loads(m.read_text(encoding="utf-8"))
                prior_rows = PartialWriter.load(jsonl)
                done = _read_done(run_id)
                out.append((run_id, meta, prior_rows, done))
            except Exception:
                continue
        return out

    display(HTML("""
    <div style='background:linear-gradient(90deg,#0277bd,#01579b);color:white;
    padding:1.2rem 1.5rem;border-radius:12px;margin-bottom:1rem;font-family:sans-serif;'>
      <h2 style='margin:0;color:white;'>🛒 Sodimac Seller Scraper</h2>
      <p style='margin:.3rem 0 0;color:rgba(255,255,255,.85);font-size:.95rem;'>
        Captura productos vendidos por Sodimac de cualquier sección, en una o más tiendas.
      </p>
    </div>
    <style>
    @keyframes scraper-spin { to { transform: rotate(360deg); } }
    @keyframes scraper-pulse { 0%,100%{opacity:1} 50%{opacity:.6} }
    .scraper-spinner{display:inline-block;width:14px;height:14px;border:2px solid #f0a020;
      border-top-color:transparent;border-radius:50%;animation:scraper-spin .8s linear infinite;
      vertical-align:-3px;margin-right:8px;}
    .scraper-spinner-blue{border-color:#01579b;border-top-color:transparent;}
    .scraper-banner-running{background:linear-gradient(90deg,#ffb84d,#f0a020);color:#3a2400;
      padding:.7rem 1rem;border-radius:8px;font-family:sans-serif;font-weight:600;
      animation:scraper-pulse 1.6s ease-in-out infinite;margin:.5rem 0;}
    </style>
    """))

    def _checkbox_panel(items, all_checked=True, height="220px"):
        boxes = []
        for label, val in items:
            cb = widgets.Checkbox(value=all_checked, description=label, indent=False,
                                  layout=widgets.Layout(width="auto", margin="0"))
            cb._payload = val
            boxes.append(cb)
        list_box = widgets.VBox(boxes, layout=widgets.Layout(
            max_height=height, overflow_y="auto", border="1px solid #d0d0d0",
            border_radius="6px", padding="6px 10px", width="540px",
        ))
        btn_all = widgets.Button(description="Marcar todas", layout=widgets.Layout(width="130px"))
        btn_none = widgets.Button(description="Desmarcar todas", layout=widgets.Layout(width="150px"))
        btn_inv = widgets.Button(description="Invertir", layout=widgets.Layout(width="100px"))
        counter = widgets.HTML()
        def refresh_counter(*_):
            n = sum(1 for b in boxes if b.value)
            counter.value = f"<span style='color:#555;font-size:.9em;'>{n} de {len(boxes)} seleccionadas</span>"
        for b in boxes:
            b.observe(refresh_counter, "value")
        btn_all.on_click(lambda _: [setattr(b, "value", True) for b in boxes])
        btn_none.on_click(lambda _: [setattr(b, "value", False) for b in boxes])
        btn_inv.on_click(lambda _: [setattr(b, "value", not b.value) for b in boxes])
        refresh_counter()
        container = widgets.VBox([
            widgets.HBox([btn_all, btn_none, btn_inv, counter],
                         layout=widgets.Layout(align_items="center", gap="8px")),
            list_box,
        ])
        def get_selected():
            return [b._payload for b in boxes if b.value]
        return container, get_selected

    # ─── Paso 1: tiendas ──────────────────────────────────────────────
    rm_stores = [s for s in ALL_STORES if s["region"] == "Metropolitana"]
    PRESETS = {
        "Solo La Florida (más rápido)": [s for s in ALL_STORES if s["id"] == "E510"],
        f"Todas RM ({len(rm_stores)} tiendas)": rm_stores,
        f"Todas Chile ({len(ALL_STORES)} tiendas)": ALL_STORES,
        "Personalizado": None,
    }

    preset_radio = widgets.RadioButtons(
        options=list(PRESETS.keys()), value="Solo La Florida (más rápido)",
        description="Preset:", layout=widgets.Layout(width="auto"),
        style={"description_width": "initial"},
    )

    store_panel_items = [(f"{s['id']}  {s['name']}  ({s['comuna']})", s) for s in ALL_STORES]
    store_panel, get_selected_stores = _checkbox_panel(store_panel_items, all_checked=False, height="240px")
    store_panel_wrap = widgets.VBox([store_panel], layout=widgets.Layout(display="none"))
    store_eta = widgets.HTML()

    def update_stores(*_):
        preset = PRESETS[preset_radio.value]
        if preset is None:
            store_panel_wrap.layout.display = ""
            sel = get_selected_stores()
            state["selected_stores"] = sel if sel else [s for s in ALL_STORES if s["id"] == "E510"]
        else:
            store_panel_wrap.layout.display = "none"
            state["selected_stores"] = preset
        n = len(state["selected_stores"])
        try: load_btn.disabled = (n == 0)
        except NameError: pass
        if n == 0:
            store_eta.value = "<span style='color:#c0392b'>⚠️ Seleccioná al menos una tienda</span>"
        else:
            filt = "todos vendedores" if include_non_sodimac.value else "filtro Sodimac"
            store_eta.value = f"<span style='color:#27ae60'>✓ {n} tienda(s) ({filt})</span>"
        try: _update_run_summary()
        except NameError: pass

    include_non_sodimac = widgets.Checkbox(
        value=False, description="Incluir productos no-Sodimac (marketplace)",
        indent=False, layout=widgets.Layout(width="auto"),
    )
    capture_screenshots = widgets.Checkbox(
        value=False, description="Capturar screenshots de cards (Excel más pesado)",
        indent=False, layout=widgets.Layout(width="auto"),
    )

    preset_radio.observe(update_stores, "value")
    for child in store_panel.children[1].children:
        child.observe(update_stores, "value")
    include_non_sodimac.observe(update_stores, "value")

    step1 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.3rem 0;'>📍 Paso 1 — Tiendas</h4>"),
        preset_radio, store_panel_wrap, store_eta,
        widgets.HTML("<h4 style='margin:.8rem 0 .3rem;'>⚙️ Opciones avanzadas</h4>"),
        include_non_sodimac, capture_screenshots,
    ])

    # ─── Paso 2: secciones ────────────────────────────────────────────
    load_btn = widgets.Button(description="🔍 Cargar secciones", button_style="info",
                              disabled=True, layout=widgets.Layout(width="220px"))
    load_status = widgets.Output()
    section_dd = widgets.Dropdown(description="Sección:",
                                  layout=widgets.Layout(width="500px", display="none"),
                                  style={"description_width": "initial"})
    subcat_container = widgets.VBox(layout=widgets.Layout(display="none"))
    get_selected_subcats = lambda: []

    mode_selector = widgets.RadioButtons(
        options=[("Sección del menú de Sodimac", "menu"),
                 ("URL personalizada (pegar link de categoría)", "url")],
        value="menu",
        description="Modo:",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="500px"),
    )
    custom_url_input = widgets.Text(
        description="URL:", placeholder="https://www.sodimac.cl/sodimac-cl/lista/CATG.../...",
        layout=widgets.Layout(width="700px"),
        style={"description_width": "initial"},
    )
    custom_name_input = widgets.Text(
        description="Nombre:", placeholder="ej: Pisos-y-revestimientos",
        layout=widgets.Layout(width="500px"),
        style={"description_width": "initial"},
    )
    custom_box = widgets.VBox(
        [widgets.HTML("<b>Categoría personalizada:</b>"
                      "<br><span style='font-size:.85em;color:#666;'>"
                      "Pegá una URL de listado de Sodimac (no funcionan URLs con <code>isLanding=true</code>)."
                      "</span>"),
         custom_url_input, custom_name_input],
        layout=widgets.Layout(display="none", margin="6px 0"),
    )

    def on_mode_change(change):
        if mode_selector.value == "menu":
            load_btn.layout.display = ""
            load_status.layout.display = ""
            section_dd.layout.display = "" if section_dd.options else "none"
            subcat_container.layout.display = "" if section_dd.options else "none"
            custom_box.layout.display = "none"
            run_btn.disabled = not bool(section_dd.options)
        else:
            load_btn.layout.display = "none"
            load_status.layout.display = "none"
            section_dd.layout.display = "none"
            subcat_container.layout.display = "none"
            custom_box.layout.display = ""
            run_btn.disabled = False

    mode_selector.observe(on_mode_change, "value")

    def on_section_change(change):
        global get_selected_subcats
        if not section_dd.value:
            return
        _, subs = section_dd.value
        items = [(n, (n, u)) for n, u in subs]
        panel, getter = _checkbox_panel(items, all_checked=True, height="260px")
        get_selected_subcats = getter
        subcat_container.children = [
            widgets.HTML("<b>Subcategorías:</b>"),
            panel,
        ]
        subcat_container.layout.display = ""

    section_dd.observe(on_section_change, "value")

    async def _discover():
        first = state["selected_stores"][0]
        async with Stealth().use_async(async_playwright()) as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900}, color_scheme="light",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="es-CL", timezone_id="America/Santiago",
            )
            page = await ctx.new_page()
            # set_zone es opcional — si falla, el __NEXT_DATA__ de la home sigue teniendo el megamenú
            try:
                await set_zone_with_retry(page, first["region"], first["comuna"])
            except Exception:
                pass
            secs = await discover_sections(page)
            # Reintento defensivo: si vino vacío, warmup + retry
            if not secs:
                try:
                    await page.goto("https://www.sodimac.cl/sodimac-cl/", wait_until="networkidle", timeout=60000)
                    await page.wait_for_timeout(5000)
                    secs = await discover_sections(page)
                except Exception:
                    pass
            await browser.close()
            return secs

    def on_load_clicked(_):
        if not state["selected_stores"]:
            with load_status:
                clear_output(); print("⚠️ Seleccioná al menos una tienda primero.")
            return
        load_btn.disabled = True
        with load_status:
            clear_output()
            display(HTML("<span class='scraper-spinner scraper-spinner-blue'></span>"
                         "Configurando zona y leyendo el megamenú de Sodimac…"))
        try:
            secs = asyncio.run(_discover())
        except Exception as e:
            with load_status:
                clear_output(); print(f"❌ Error: {e}")
            load_btn.disabled = False
            return
        if not secs:
            with load_status:
                clear_output(); print("❌ No se pudieron leer las secciones. Esperá unos segundos e intentá de nuevo.")
            load_btn.disabled = False
            return
        state["sections"] = secs
        section_dd.options = [(f"{n}  ·  {len(subs)} subcat.", (n, subs)) for n, subs in secs]
        section_dd.layout.display = ""
        section_dd.value = section_dd.options[0][1]
        with load_status:
            clear_output(); print(f"✓ {len(secs)} secciones cargadas.")
        load_btn.disabled = False
        run_btn.disabled = False

    load_btn.on_click(on_load_clicked)

    step2 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.8rem 0 .3rem;'>📂 Paso 2 — Sección a scrapear</h4>"),
        mode_selector, load_btn, load_status, section_dd, subcat_container, custom_box,
    ])

    # ─── Paso 3: ejecutar ─────────────────────────────────────────────
    run_btn = widgets.Button(description="🚀 Iniciar scraping", button_style="success",
                             disabled=True, layout=widgets.Layout(width="220px"))
    running_banner = widgets.HTML()

    store_bar = widgets.IntProgress(min=0, max=100, value=0, description="Tiendas:",
                                    bar_style="info", layout=widgets.Layout(width="540px"),
                                    style={"description_width": "initial"})
    store_pct = widgets.HTML(layout=widgets.Layout(width="110px"))
    subcat_bar = widgets.IntProgress(min=0, max=100, value=0, description="Subcat:",
                                     bar_style="info", layout=widgets.Layout(width="540px"),
                                     style={"description_width": "initial"})
    subcat_pct = widgets.HTML(layout=widgets.Layout(width="110px"))
    page_bar = widgets.IntProgress(min=0, max=100, value=0, description="Páginas:",
                                    bar_style="info", layout=widgets.Layout(width="540px"),
                                    style={"description_width": "initial"})
    page_pct = widgets.HTML(layout=widgets.Layout(width="110px"))
    store_row = widgets.HBox([store_bar, store_pct], layout=widgets.Layout(align_items="center"))
    subcat_row = widgets.HBox([subcat_bar, subcat_pct], layout=widgets.Layout(align_items="center"))
    page_row = widgets.HBox([page_bar, page_pct], layout=widgets.Layout(align_items="center"))
    live_status = widgets.HTML()
    live_metrics = widgets.HTML()
    result_out = widgets.Output()

    def _set_pct(w, value, total):
        if not total:
            w.value = ""
            return
        pct = int(round(100 * value / total))
        w.value = f"<span style='color:#555;font-size:.9em;margin-left:8px;'>{value}/{total} · {pct}%</span>"

    def _set_running_ui(on):
        if on:
            run_btn.layout.display = "none"
            try: resume_panel.layout.display = "none"
            except NameError: pass
            running_banner.value = ("<div class='scraper-banner-running'>"
                                    "<span class='scraper-spinner'></span>"
                                    "Trabajando — no cierres esta pestaña ni la celda</div>")
        else:
            run_btn.description = "🚀 Iniciar scraping"
            run_btn.button_style = "success"
            run_btn.disabled = False
            run_btn.layout.display = ""
            try:
                resume_panel.layout.display = ""
                _refresh_resume_panel()
            except NameError: pass
            running_banner.value = ""

    def _status_with_spinner(text):
        return f"<span class='scraper-spinner'></span>{text}"

    async def _run_scrape(stores, section_name, subcats, include_non_sod, screenshots,
                          run_id=None, prior_rows=None, prior_done=None):
        all_rows = list(prior_rows or [])
        non_sodimac = 0
        skipped_zone = []
        failed_subcats = []
        truncated_subcats = []
        if not run_id:
            run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{re.sub(r'[^A-Za-z0-9]+', '', section_name) or 'run'}"
        prior_done = prior_done or set()
        # En reanudación, abrimos el JSONL en modo append para no borrar las filas previas.
        partial = PartialWriter.__new__(PartialWriter)
        partial.path = PARTIAL_DIR / f"{run_id}.jsonl"
        partial._fh = open(partial.path, "a" if prior_rows else "w", encoding="utf-8")
        partial.count = len(prior_rows or [])
        # Reset UI residual de runs anteriores
        store_bar.value = 0; store_bar.description = "Tiendas:"
        subcat_bar.value = 0; subcat_bar.description = "Subcat:"
        page_bar.value = 0;  page_bar.description = "Páginas:"
        for _w in (store_pct, subcat_pct, page_pct):
            _w.value = ""
        live_status.value = ""
        live_metrics.value = ""
        _t0 = _time.time()
        _global_skus = {r.get("SKU") for r in all_rows if r.get("SKU")}
        _done_session = 0
        n_stores = len(stores)
        n_subs = max(len(subcats), 1)
        store_bar.max = n_stores
        subcat_bar.max = n_subs
        _set_pct(store_pct, 0, n_stores)
        _set_pct(subcat_pct, 0, n_subs)

        async with Stealth().use_async(async_playwright()) as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900}, color_scheme="light",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = await ctx.new_page()
            first = stores[0]
            live_status.value = _status_with_spinner(f"Configurando zona inicial: {first['name']}…")
            ok = await set_zone_with_retry(page, first["region"], first["comuna"])
            if not ok:
                live_status.value = f"<span style='color:#c0392b'>❌ Falla zona inicial en {first['name']}. Aborto.</span>"
                await browser.close()
                return None

            class _DummyProg:
                def update(self, *a, **kw): pass
                def advance(self, *a, **kw): pass
            dummy = _DummyProg()

            for st_idx, store in enumerate(stores):
                store_bar.value = st_idx
                store_bar.description = f"Tiendas {st_idx+1}/{n_stores}"
                _set_pct(store_pct, st_idx, n_stores)
                if st_idx > 0:
                    live_status.value = _status_with_spinner(f"Cambiando zona a {store['name']}…")
                    ok = await set_zone_with_retry(page, store["region"], store["comuna"])
                    if not ok:
                        skipped_zone.append(store["id"])
                        continue
                seen = {r.get("SKU") for r in all_rows if r.get("Tienda") == store["id"] and r.get("SKU")}
                for sc_idx, (sc_name, sc_url) in enumerate(subcats):
                    subcat_bar.value = sc_idx
                    subcat_bar.description = f"Subcat {sc_idx+1}/{n_subs}"
                    _set_pct(subcat_pct, sc_idx, n_subs)
                    if (store["id"], sc_name) in prior_done:
                        live_status.value = _status_with_spinner(f"⏭ Saltando (ya hecho): {store['name']} · {sc_name}")
                        continue
                    live_status.value = _status_with_spinner(f"📍 {store['name']} · 🗂 {sc_name}")
                    page_bar.max = 1
                    page_bar.value = 0
                    page_bar.description = "Páginas:"
                    _set_pct(page_pct, 0, 0)

                    def _page_cb(curr, total, _sc=sc_name):
                        if total and total > 0:
                            page_bar.max = total
                            page_bar.value = min(curr, total)
                            page_bar.description = f"Páginas {curr}/{total}"
                            _set_pct(page_pct, curr, total)
                        else:
                            page_bar.max = max(page_bar.max, curr)
                            page_bar.value = curr
                            page_bar.description = f"Página {curr}"
                            _set_pct(page_pct, curr, page_bar.max)

                    res = await scrape_subcat(page, section_name, sc_name, sc_url, dummy, None,
                                               capture_screenshots=screenshots,
                                               only_sodimac=not include_non_sod,
                                               page_progress_cb=_page_cb,
                                               auto_breadcrumb=(section_name == "Custom"))
                    if res["failed"]:
                        failed_subcats.append((store["id"], sc_name))
                    if res["truncated"]:
                        truncated_subcats.append((store["id"], sc_name))
                    for r in res["rows"]:
                        vendedor = (r.get("Vendedor") or "").strip().upper()
                        is_sod = "SODIMAC" in vendedor
                        if not include_non_sod and not is_sod:
                            non_sodimac += 1
                            continue
                        sku = r.get("SKU")
                        if not sku or sku in seen:
                            continue
                        seen.add(sku)
                        r2 = {"Tienda": store["id"], "Nombre Tienda": store["name"], **r}
                        all_rows.append(r2)
                        partial.write(r2)
                        if sku: _global_skus.add(sku)
                    _elapsed = _time.time() - _t0
                    _mm, _ss = divmod(int(_elapsed), 60)
                    _hh, _mm = divmod(_mm, 60)
                    _elapsed_str = f"{_hh}:{_mm:02d}:{_ss:02d}" if _hh else f"{_mm}:{_ss:02d}"
                    _rate = (len(all_rows) - len(prior_rows or [])) / max(_elapsed / 60, 0.01)
                    _parts = [
                        f"<b>🧮 Filas:</b> {len(all_rows)}",
                        f"<b>SKUs únicos:</b> {len(_global_skus)}",
                        f"<b>⏱</b> {_elapsed_str}",
                        f"<b>~{_rate:.0f}</b> filas/min",
                    ]
                    if _done_session >= 1:
                        _pairs_total = n_stores * n_subs - len(prior_done)
                        _pairs_left = max(0, _pairs_total - _done_session)
                        _eta_s = (_elapsed / _done_session) * _pairs_left
                        _em, _es = divmod(int(_eta_s), 60); _eh, _em = divmod(_em, 60)
                        _eta_str = f"{_eh}:{_em:02d}:{_es:02d}" if _eh else f"{_em}:{_es:02d}"
                        _parts.append(f"<b>ETA:</b> ~{_eta_str}")
                    if include_non_sod and non_sodimac:
                        _parts.append(f"<b>No-Sodimac:</b> {non_sodimac}")
                    live_metrics.value = " · ".join(_parts)
                    _append_done(run_id, store["id"], sc_name)
                    _done_session += 1
                subcat_bar.value = n_subs
                _set_pct(subcat_pct, n_subs, n_subs)
            store_bar.value = n_stores
            _set_pct(store_pct, n_stores, n_stores)
            live_status.value = "✓ Scraping completado."
            await browser.close()
        partial.close()
        return {"rows": all_rows, "non_sodimac": non_sodimac,
                "skipped_zone": skipped_zone,
                "failed_subcats": failed_subcats,
                "truncated_subcats": truncated_subcats,
                "partial_path": str(partial.path),
                "run_id": run_id,
                "section_name": section_name,
                "include_non_sodimac": include_non_sod, "capture_screenshots": screenshots}

    def on_run_clicked(_):
        if state["running"]:
            return
        if not state["selected_stores"]:
            with result_out:
                clear_output(); print("⚠️ Seleccioná al menos una tienda.")
            return
        # Si venimos de "Continuar", usamos sección/subcats del meta, no de los widgets.
        pending = state.get("pending_resume")
        if pending:
            meta = pending.get("meta") or {}
            section_name = meta.get("section_name") or "run"
            subcats = [tuple(s) for s in (meta.get("subcats") or [])]
            if not subcats:
                with result_out:
                    clear_output(); print("⚠️ El checkpoint no tiene subcategorías.")
                state.pop("pending_resume", None)
                return
        elif mode_selector.value == "url":
            url = (custom_url_input.value or "").strip()
            name = (custom_name_input.value or "").strip()
            if not url.startswith("http"):
                with result_out:
                    clear_output(); print("⚠️ Pegá una URL válida (debe empezar con http).")
                return
            if "isLanding=true" in url:
                with result_out:
                    clear_output(); print("⚠️ Esa URL es una landing page (isLanding=true) y no tiene grid de productos.")
                return
            if not name:
                name = url.rstrip("/").split("/")[-1] or "custom"
            section_name = "Custom"
            subcats = [(name, url)]
        else:
            if not section_dd.value:
                with result_out:
                    clear_output(); print("⚠️ Cargá las secciones primero.")
                return
            section_name, _ = section_dd.value
            subcats = get_selected_subcats()
            if not subcats:
                with result_out:
                    clear_output(); print("⚠️ Marcá al menos una subcategoría.")
                return
        state["running"] = True
        _set_running_ui(True)
        load_btn.disabled = True
        with result_out:
            clear_output()
        # Resume context (si vino de "Continuar")
        resume = state.pop("pending_resume", None)
        if resume:
            run_id = resume["run_id"]
            prior_rows = resume["rows"]
            prior_done = resume["done"]
        else:
            run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{re.sub(r'[^A-Za-z0-9]+', '', section_name) or 'run'}"
            prior_rows = None
            prior_done = None
            _write_meta(run_id, {
                "run_id": run_id,
                "section_name": section_name,
                "subcats": [list(s) for s in subcats],
                "stores": state["selected_stores"],
                "include_non_sodimac": include_non_sodimac.value,
                "capture_screenshots": capture_screenshots.value,
                "mode": mode_selector.value,
                "created_at": datetime.now().isoformat(),
            })
        try:
            result = asyncio.run(_run_scrape(
                state["selected_stores"], section_name, subcats,
                include_non_sodimac.value, capture_screenshots.value,
                run_id=run_id, prior_rows=prior_rows, prior_done=prior_done,
            ))
        except Exception as e:
            with result_out:
                print(f"❌ Error durante scraping: {e}")
            state["running"] = False
            _set_running_ui(False)
            load_btn.disabled = False
            return
        state["running"] = False
        _set_running_ui(False)
        load_btn.disabled = False

        if not result or not result["rows"]:
            with result_out:
                print("⚠️ No se encontraron productos.")
                if result and result["skipped_zone"]:
                    print(f"Tiendas saltadas: {', '.join(result['skipped_zone'])}")
            return

        rows = result["rows"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        safe = re.sub(r"[^\w\s-]", "", result["section_name"]).strip().replace(" ", "_")
        suffix = "_all_sellers" if result["include_non_sodimac"] else ""
        suffix += "_con_imgs" if result["capture_screenshots"] else ""
        output = OUTPUT_DIR / f"sodimac_{safe}{suffix}_{timestamp}.xlsx"
        with result_out:
            print("💾 Escribiendo Excel…")
            write_excel(rows, str(output))
            n_skus = len({x["SKU"] for x in rows if x.get("SKU")})
            n_stores_res = len({x["Tienda"] for x in rows if x.get("Tienda")})
            print(f"\n✅ Listo — {len(rows)} filas · {n_skus} SKUs únicos · {n_stores_res} tienda(s)")
            print(f"   Descartadas (no-Sodimac): {result['non_sodimac']}")
            if result["skipped_zone"]:
                print(f"   Tiendas saltadas por zona: {', '.join(result['skipped_zone'])}")
            if result.get("failed_subcats"):
                print(f"   Subcats que fallaron: {len(result['failed_subcats'])}")
            if result.get("truncated_subcats"):
                print(f"   Subcats truncadas: {len(result['truncated_subcats'])}")
            if result.get("partial_path"):
                print(f"   Backup incremental (JSONL): {result['partial_path']}")
            print(f"   Archivo: {output.name}")
            _log_activity(retailer="sodimac", mode="seccion",
                           n_skus=0,
                           n_stores=len(state.get("selected_stores") or []),
                           n_rows_output=len(rows or []),
                           n_with_price=sum(1 for r in (rows or []) if r.get("Precio Internet")),
                           runtime_s=0,
                           output_file=output.name if output else "")
            if IN_COLAB:
                print("\n⬇️  Descargando…")
                colab_files.download(str(output))
                _redl_btn = widgets.Button(
                    description="Descargar Excel de nuevo",
                    icon="download", button_style="info",
                    layout=widgets.Layout(width="260px"),
                )
                def _redl_cb(_b, _p=str(output)):
                    try: colab_files.download(_p)
                    except Exception as _e: print(f"download fallo: {_e}")
                _redl_btn.on_click(_redl_cb)
                display(_redl_btn)
            else:
                print(f"\n📁 Guardado en: {output}")
            # Excel escrito OK → borrar checkpoint del Drive
            if result.get("run_id"):
                _cleanup_run(result["run_id"])
                print(f"🧹 Checkpoint eliminado ({result['run_id']}).")
            _refresh_resume_panel()

    run_btn.on_click(on_run_clicked)

    # ─── Resumen pre-run ───────────────────────────────────────────
    run_summary = widgets.HTML()

    def _update_run_summary(*_):
        try:
            n_st = len(state.get("selected_stores", []))
        except Exception:
            n_st = 0
        if mode_selector.value == "url":
            url_ok = (custom_url_input.value or "").strip().startswith("http")
            if n_st == 0 or not url_ok:
                run_summary.value = ""
                return
            run_summary.value = (
                "<div style='background:#f0f7ff;padding:.6rem;border-radius:6px;"
                "border:1px solid #bcdcff;margin:.4rem 0;font-size:.95em;'>"
                f"📋 Vas a scrapear <b>{n_st}</b> tienda(s) × 1 URL personalizada.</div>"
            )
            return
        try:
            sel = get_selected_subcats()
            n_sc = len(sel) if sel else 0
        except Exception:
            n_sc = 0
        if n_st == 0 or n_sc == 0:
            run_summary.value = ""
            return
        run_summary.value = (
            "<div style='background:#f0f7ff;padding:.6rem;border-radius:6px;"
            "border:1px solid #bcdcff;margin:.4rem 0;font-size:.95em;'>"
            f"📋 Vas a scrapear <b>{n_st}</b> tienda(s) × <b>{n_sc}</b> subcategoría(s) "
            f"= <b>{n_st * n_sc}</b> combinaciones.</div>"
        )

    # Hook observers
    try:
        mode_selector.observe(_update_run_summary, "value")
        custom_url_input.observe(_update_run_summary, "value")
        section_dd.observe(_update_run_summary, "value")
    except NameError:
        pass

    # Patch on_section_change para que también attache observer a checkboxes nuevas
    _orig_on_section_change = on_section_change
    def on_section_change(change):
        _orig_on_section_change(change)
        try:
            for child in subcat_container.children:
                if hasattr(child, "children"):
                    for sub in getattr(child, "children", []):
                        if isinstance(sub, widgets.VBox) or isinstance(sub, widgets.HBox):
                            for cb in getattr(sub, "children", []):
                                if isinstance(cb, widgets.Checkbox):
                                    cb.observe(_update_run_summary, "value")
        except Exception:
            pass
        _update_run_summary()
    section_dd.unobserve(_orig_on_section_change, "value")
    section_dd.observe(on_section_change, "value")

    # ─── Panel de reanudación de checkpoint ────────────────────────
    resume_panel = widgets.VBox()

    def _make_resume_card(run_id, meta, prior_rows, done):
        age_min = int((_time.time() - _meta_path(run_id).stat().st_mtime) / 60)
        ttl_min = max(0, PARTIAL_TTL_SECONDS // 60 - age_min)
        section = meta.get("section_name") or "(sin nombre)"
        mode = meta.get("mode", "menu")
        subcats = meta.get("subcats") or []
        stores = meta.get("stores") or []
        done_names = {sc for _, sc in done}

        if mode == "url" and subcats:
            sc_html = (f"<b>URL:</b> <code style='font-size:.85em;'>{subcats[0][1]}</code><br>"
                       f"<b>Nombre:</b> {subcats[0][0]}")
        else:
            items = []
            for n, _ in subcats:
                check = "✓" if n in done_names else "○"
                items.append(f"<span style='color:{'#2e8b2e' if n in done_names else '#888'};'>{check}</span> {n}")
            sc_html = "<b>Subcategorías:</b><br>" + " · ".join(items) if items else "(sin subcats)"

        store_html = ", ".join(s.get("id","?") for s in stores[:6])
        if len(stores) > 6:
            store_html += f" … (+{len(stores)-6})"

        info = widgets.HTML(
            "<div style='background:#fff7e0;padding:.7rem;border-radius:6px;border:1px solid #f0c060;'>"
            f"📦 <b>Sección:</b> {section} <span style='color:#888;'>· modo: {mode}</span><br>"
            f"<b>Tiendas:</b> {len(stores)} ({store_html})<br>"
            f"{sc_html}<br>"
            f"<span style='color:#555;font-size:.9em;'>"
            f"💾 {len(prior_rows)} filas · {len(done)}/{len(subcats) * max(len(stores),1)} (tienda·subcat) completos · "
            f"hace {age_min} min · expira en {ttl_min} min · "
            f"<code>{run_id}</code></span></div>"
        )
        btn_cont = widgets.Button(description="▶ Continuar", button_style="success")
        btn_disc = widgets.Button(description="🗑 Descartar", button_style="danger")

        def _on_cont(_):
            state["pending_resume"] = {"run_id": run_id, "rows": prior_rows, "done": done, "meta": meta}
            state["selected_stores"] = stores or state["selected_stores"]
            on_run_clicked(None)
        def _on_disc(_):
            _cleanup_run(run_id)
            _refresh_resume_panel()
        btn_cont.on_click(_on_cont)
        btn_disc.on_click(_on_disc)
        return widgets.VBox([info, widgets.HBox([btn_cont, btn_disc])],
                            layout=widgets.Layout(margin="0 0 .6rem 0"))

    def _refresh_resume_panel():
        found = _find_resumable_all()
        if not found:
            resume_panel.children = []
            return
        cards = [_make_resume_card(*x) for x in found]
        if len(found) == 1:
            header = widgets.HTML(
                "<h4 style='margin:.6rem 0 .3rem;'>📦 Checkpoint disponible</h4>"
            )
            resume_panel.children = [header] + cards
            return
        cards_box = widgets.VBox(cards, layout=widgets.Layout(display="none"))
        toggle = widgets.Button(description=f"▶ Mostrar {len(found)} checkpoints",
                                button_style="warning",
                                layout=widgets.Layout(width="280px"))
        def _toggle(_):
            if cards_box.layout.display == "none":
                cards_box.layout.display = ""
                toggle.description = f"▼ Ocultar {len(found)} checkpoints"
            else:
                cards_box.layout.display = "none"
                toggle.description = f"▶ Mostrar {len(found)} checkpoints"
        toggle.on_click(_toggle)
        header = widgets.HTML(
            "<span style='color:#888;font-size:.85em;'>"
            "Reanudá el que corresponda o descartá los que ya no necesités.</span>"
        )
        resume_panel.children = [toggle, header, cards_box]

    _refresh_resume_panel()

    step3 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.8rem 0 .3rem;'>🚀 Paso 3 — Ejecutar</h4>"),
        resume_panel, run_summary, run_btn, running_banner, store_row, subcat_row, page_row, live_status, live_metrics, result_out,
    ])
    _update_run_summary()

    footer = widgets.HTML(
        "<div style='margin-top:1.5rem;padding-top:.6rem;border-top:1px solid #e0e0e0;"
        "text-align:right;color:#aaa;font-size:.75em;font-family:sans-serif;font-style:italic;'>"
        "Creado por Carlos Cruz</div>"
    )

    update_stores()
    display(widgets.VBox([step1, step2, step3, footer]))
    '''

    _UI_FALABELLA = r'''import asyncio, re
    from datetime import datetime
    from pathlib import Path
    import nest_asyncio
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    nest_asyncio.apply()

    clear_output(wait=True)  # reset celda — evita duplicar UI al re-ejecutar

    try:
        from google.colab import files as colab_files
        IN_COLAB = True
    except ImportError:
        IN_COLAB = False

    OUTPUT_DIR = Path.cwd()

    # ─── Telemetry: log activity al Sheet ──────────────────────────────
    import uuid as _uuid
    _ACTIVITY_URL = "https://script.google.com/macros/s/AKfycbwYNVObEiq8NSslHNsPA3vcNsfPPf8zo6oLAOLVXEGQ7cqT_FwA4PxVxjNaEqt_566Z/exec"
    _ACTIVITY_TOKEN = "6kT2hQjLp_VxR8mN3wYsZ-aF7bGdEcU4"
    _BUILD_HASH = "5c4dba0ea3acb1375cdffccab4d63aad371fe0124f0b915fe6e05dd30d3f0577"
    _COLAB_TAG = "seccion-falabella"
    _SESSION_ID = globals().get("_SESSION_ID") or _uuid.uuid4().hex[:8]
    globals()["_SESSION_ID"] = _SESSION_ID

    def _user_hint():
        """Intenta obtener email del usuario de Colab; falla silencioso."""
        try:
            import subprocess
            # En Colab, /tmp/__colab_user_email__ no existe; intentar via auth
            from google.colab import auth as _ca
            # auth.authenticate_user() pediría permiso — no lo hacemos.
            # Mejor: leer env si existe.
            import os
            for k in ("COLAB_USER", "USER", "JUPYTERHUB_USER"):
                v = os.environ.get(k)
                if v: return v
        except Exception:
            pass
        return ""

    def _log_activity(retailer="", mode="", n_skus=0, n_stores=0,
                       n_rows_output=0, n_with_price=0, runtime_s=0,
                       output_file=""):
        """Mandar 1 POST con resumen del run. Nunca propaga errores."""
        try:
            import requests as _rq
            _rq.post(_ACTIVITY_URL, json={
                "token": _ACTIVITY_TOKEN,
                "session_id": _SESSION_ID,
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
            pass  # silencioso — no romper el flow del usuario
    state = {"sections": None, "selected_stores": [], "running": False, "pending_resume": None}

    # ─── Checkpoint en Google Drive + autolimpieza de 12 h ───────────────
    import os as _os, time as _time, json as _json
    PARTIAL_TTL_SECONDS = 12 * 3600  # 12 horas
    if IN_COLAB:
        try:
            from google.colab import drive as _drive
            if not _os.path.isdir("/content/drive/MyDrive"):
                _drive.mount("/content/drive", force_remount=False)
            _drv = Path("/content/drive/MyDrive/falabella_scraper_partials")
            _drv.mkdir(parents=True, exist_ok=True)
            PARTIAL_DIR = _drv  # redirige PartialWriter al Drive
        except Exception as _e:
            print(f"⚠️ No se pudo montar Drive ({_e}); usando filesystem efímero.")

    # Limpieza inicial: borra checkpoints con más de 12 h de vida
    _now = _time.time()
    for _glob in ("*.jsonl", "*.meta.json", "*.done.tsv"):
        for _p in PARTIAL_DIR.glob(_glob):
            try:
                if _now - _p.stat().st_mtime > PARTIAL_TTL_SECONDS:
                    _p.unlink()
            except Exception:
                pass

    def _meta_path(run_id): return PARTIAL_DIR / f"{run_id}.meta.json"
    def _done_path(run_id): return PARTIAL_DIR / f"{run_id}.done.tsv"

    def _write_meta(run_id, payload):
        _meta_path(run_id).write_text(_json.dumps(payload, ensure_ascii=False, indent=2))

    def _append_done(run_id, store_id, subcat_name):
        with open(_done_path(run_id), "a", encoding="utf-8") as f:
            f.write(f"{store_id}\t{subcat_name}\n")

    def _read_done(run_id):
        p = _done_path(run_id)
        if not p.exists(): return set()
        done = set()
        for line in p.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) == 2:
                done.add((parts[0], parts[1]))
        return done

    def _cleanup_run(run_id):
        for p in (PARTIAL_DIR / f"{run_id}.jsonl", _meta_path(run_id), _done_path(run_id)):
            try: p.unlink()
            except Exception: pass

    def _find_resumable_all():
        out = []
        metas = sorted(PARTIAL_DIR.glob("*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for m in metas:
            run_id = m.name[:-len(".meta.json")]
            jsonl = PARTIAL_DIR / f"{run_id}.jsonl"
            if not jsonl.exists():
                continue
            try:
                meta = _json.loads(m.read_text(encoding="utf-8"))
                prior_rows = PartialWriter.load(jsonl)
                done = _read_done(run_id)
                out.append((run_id, meta, prior_rows, done))
            except Exception:
                continue
        return out

    display(HTML("""
    <div style='background:linear-gradient(90deg,#2e7d32,#1b5e20);color:white;
    padding:1.2rem 1.5rem;border-radius:12px;margin-bottom:1rem;font-family:sans-serif;'>
      <h2 style='margin:0;color:white;'>🛍️ Falabella Seller Scraper</h2>
      <p style='margin:.3rem 0 0;color:rgba(255,255,255,.85);font-size:.95rem;'>
        Captura productos de cualquier sección de Falabella, con filtro opcional por vendedor.
      </p>
    </div>
    <style>
    @keyframes scraper-spin { to { transform: rotate(360deg); } }
    @keyframes scraper-pulse { 0%,100%{opacity:1} 50%{opacity:.6} }
    .scraper-spinner{display:inline-block;width:14px;height:14px;border:2px solid #2e7d32;
      border-top-color:transparent;border-radius:50%;animation:scraper-spin .8s linear infinite;
      vertical-align:-3px;margin-right:8px;}
    .scraper-spinner-blue{border-color:#1b5e20;border-top-color:transparent;}
    .scraper-banner-running{background:linear-gradient(90deg,#ffb84d,#f0a020);color:#3a2400;
      padding:.7rem 1rem;border-radius:8px;font-family:sans-serif;font-weight:600;
      animation:scraper-pulse 1.6s ease-in-out infinite;margin:.5rem 0;}
    </style>
    """))

    def _checkbox_panel(items, all_checked=True, height="220px"):
        boxes = []
        for label, val in items:
            cb = widgets.Checkbox(value=all_checked, description=label, indent=False,
                                  layout=widgets.Layout(width="auto", margin="0"))
            cb._payload = val
            boxes.append(cb)
        list_box = widgets.VBox(boxes, layout=widgets.Layout(
            max_height=height, overflow_y="auto", border="1px solid #d0d0d0",
            border_radius="6px", padding="6px 10px", width="540px",
        ))
        btn_all = widgets.Button(description="Marcar todas", layout=widgets.Layout(width="130px"))
        btn_none = widgets.Button(description="Desmarcar todas", layout=widgets.Layout(width="150px"))
        btn_inv = widgets.Button(description="Invertir", layout=widgets.Layout(width="100px"))
        counter = widgets.HTML()
        def refresh_counter(*_):
            n = sum(1 for b in boxes if b.value)
            counter.value = f"<span style='color:#555;font-size:.9em;'>{n} de {len(boxes)} seleccionadas</span>"
        for b in boxes:
            b.observe(refresh_counter, "value")
        btn_all.on_click(lambda _: [setattr(b, "value", True) for b in boxes])
        btn_none.on_click(lambda _: [setattr(b, "value", False) for b in boxes])
        btn_inv.on_click(lambda _: [setattr(b, "value", not b.value) for b in boxes])
        refresh_counter()
        container = widgets.VBox([
            widgets.HBox([btn_all, btn_none, btn_inv, counter],
                         layout=widgets.Layout(align_items="center", gap="8px")),
            list_box,
        ])
        def get_selected():
            return [b._payload for b in boxes if b.value]
        return container, get_selected

    # ─── Paso 1: zonas ────────────────────────────────────────────────
    rm_stores = [s for s in ALL_STORES if s["region"] == "Metropolitana"]
    PRESETS = {
        "Solo Kennedy / Las Condes (más rápido)": [s for s in ALL_STORES if s["id"] == "E502"],
        f"Todas RM ({len(rm_stores)} zonas)": rm_stores,
        f"Todas Chile ({len(ALL_STORES)} zonas)": ALL_STORES,
        "Personalizado": None,
    }

    preset_radio = widgets.RadioButtons(
        options=list(PRESETS.keys()), value="Solo Kennedy / Las Condes (más rápido)",
        description="Preset:", layout=widgets.Layout(width="auto"),
        style={"description_width": "initial"},
    )

    store_panel_items = [(f"{s['id']}  {s['name']}  ({s['comuna']})", s) for s in ALL_STORES]
    store_panel, get_selected_stores = _checkbox_panel(store_panel_items, all_checked=False, height="240px")
    store_panel_wrap = widgets.VBox([store_panel], layout=widgets.Layout(display="none"))
    store_eta = widgets.HTML()

    def update_stores(*_):
        preset = PRESETS[preset_radio.value]
        if preset is None:
            store_panel_wrap.layout.display = ""
            sel = get_selected_stores()
            state["selected_stores"] = sel if sel else [s for s in ALL_STORES if s["id"] == "E502"]
        else:
            store_panel_wrap.layout.display = "none"
            state["selected_stores"] = preset
        n = len(state["selected_stores"])
        try: load_btn.disabled = (n == 0)
        except NameError: pass
        if n == 0:
            store_eta.value = "<span style='color:#c0392b'>⚠️ Seleccioná al menos una zona</span>"
        else:
            filt = "filtro Falabella" if only_falabella_cb.value else "todos vendedores"
            store_eta.value = f"<span style='color:#27ae60'>✓ {n} zona(s) ({filt})</span>"
        try: _update_run_summary()
        except NameError: pass

    # Sin filtro por vendedor: incluimos todos los resultados que Falabella
    # devuelva en el PLP. Stub de only_falabella_cb para no romper referencias
    # existentes (.value = False -> sin filtro).
    class _StubCb:
        value = False
        def observe(self, fn, names="value"): pass
    only_falabella_cb = _StubCb()
    # Imagenes apagadas por default; el usuario puede activarlas si quiere.
    capture_images_cb = widgets.Checkbox(
        value=False, description="Capturar imágenes de cards",
        indent=False, layout=widgets.Layout(width="auto"),
    )
    download_images_cb = capture_images_cb

    preset_radio.observe(update_stores, "value")
    for child in store_panel.children[1].children:
        child.observe(update_stores, "value")
    only_falabella_cb.observe(update_stores, "value")

    step1 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.3rem 0;'>📍 Paso 1 — Zonas</h4>"
                     "<p style='margin:.2rem 0;color:#666;font-size:.9em;'>"
                     "Falabella tiene precios nacionales — una sola zona alcanza. "
                     "Múltiples zonas solo sirven para verificar disponibilidad/envío por región.</p>"),
        preset_radio, store_panel_wrap, store_eta,
        widgets.HTML("<h4 style='margin:.8rem 0 .3rem;'>⚙️ Opciones</h4>"),
        capture_images_cb,
    ])

    # ─── Paso 2: secciones ────────────────────────────────────────────
    load_btn = widgets.Button(disabled=True, description="🔍 Cargar secciones", button_style="success",
                              layout=widgets.Layout(width="220px"))
    load_status = widgets.Output()
    section_dd = widgets.Dropdown(description="Sección:",
                                  layout=widgets.Layout(width="500px", display="none"),
                                  style={"description_width": "initial"})
    subcat_container = widgets.VBox(layout=widgets.Layout(display="none"))
    get_selected_subcats = lambda: []

    def on_section_change(change):
        global get_selected_subcats
        if not section_dd.value:
            return
        _, groups = section_dd.value
        # Un panel de checkboxes por grupo, cada uno colapsable. A la izquierda
        # de cada grupo va un checkbox que marca/desmarca todo el grupo.
        group_rows = []
        group_getters = []
        group_pieces = []  # [(group_cb, panel)] para mark_all/none global
        for g_name, _g_url, leaves in groups:
            items = []
            for ln, lu in leaves:
                label_full = ln if ln == g_name else f"{g_name} / {ln}"
                items.append((ln, (label_full, lu)))
            panel, getter = _checkbox_panel(items, all_checked=True, height="200px")
            group_getters.append(getter)
            # Checkbox de grupo (al lado izquierdo)
            group_cb = widgets.Checkbox(
                value=True, description="", indent=False,
                layout=widgets.Layout(width="28px", margin="0 0 0 4px"),
            )
            # Cuando se toca el group_cb, se propaga a sus hijos
            def _make_group_toggle(p, gcb):
                child_boxes = p.children[1].children
                _busy = {"flag": False}
                def _on_group(change):
                    if _busy["flag"]: return
                    _busy["flag"] = True
                    try:
                        for b in child_boxes:
                            b.value = gcb.value
                    finally:
                        _busy["flag"] = False
                # Sincronía inversa: cuando cambian los hijos, refleja en el grupo
                def _on_child(change):
                    if _busy["flag"]: return
                    _busy["flag"] = True
                    try:
                        vals = [b.value for b in child_boxes]
                        if all(vals):
                            gcb.value = True
                        elif not any(vals):
                            gcb.value = False
                    finally:
                        _busy["flag"] = False
                gcb.observe(_on_group, "value")
                for b in child_boxes:
                    b.observe(_on_child, "value")
            _make_group_toggle(panel, group_cb)
            acc = widgets.Accordion(children=[panel])
            acc.set_title(0, f"{g_name} ({len(leaves)} subcat.)")
            acc.selected_index = None
            acc.layout = widgets.Layout(flex="1")
            row = widgets.HBox([group_cb, acc],
                                layout=widgets.Layout(align_items="flex-start", width="100%"))
            group_rows.append(row)
            group_pieces.append((group_cb, panel))

        btn_all_subs = widgets.Button(description="✓ Marcar todas las subcats",
                                       layout=widgets.Layout(width="240px"))
        btn_none_subs = widgets.Button(description="✗ Desmarcar todas",
                                        layout=widgets.Layout(width="200px"))

        def _mark_all_subs(_):
            for gcb, _p in group_pieces:
                gcb.value = True
        def _mark_none_subs(_):
            for gcb, _p in group_pieces:
                gcb.value = False
        btn_all_subs.on_click(_mark_all_subs)
        btn_none_subs.on_click(_mark_none_subs)

        def _get_all_selected():
            out = []
            for getter in group_getters:
                out.extend(getter())
            return out
        get_selected_subcats = _get_all_selected

        subcat_container.children = [
            widgets.HTML("<b>Subcategorías</b> — agrupadas. El checkbox a la izquierda "
                         "marca/desmarca todo el grupo. Hacé click en el título para expandir."),
            widgets.HBox([btn_all_subs, btn_none_subs], layout=widgets.Layout(gap="8px")),
            widgets.VBox(group_rows),
        ]
        subcat_container.layout.display = ""

    section_dd.observe(on_section_change, "value")

    async def _discover():
        first = state["selected_stores"][0]
        async with Stealth().use_async(async_playwright()) as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900}, color_scheme="light",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = await ctx.new_page()
            await set_zone_with_retry(page, first["region"], first["comuna"])
            secs = await discover_sections(page)
            await browser.close()
            return secs

    def on_load_clicked(_):
        if not state["selected_stores"]:
            with load_status:
                clear_output(); print("⚠️ Seleccioná al menos una zona primero.")
            return
        load_btn.disabled = True
        with load_status:
            clear_output()
            display(HTML("<span class='scraper-spinner scraper-spinner-blue'></span>"
                         "Configurando zona y leyendo el menú de Falabella…"))
        try:
            secs = asyncio.run(_discover())
        except Exception as e:
            with load_status:
                clear_output(); print(f"❌ Error: {e}")
            load_btn.disabled = False
            return
        if not secs:
            with load_status:
                clear_output(); print("❌ No se pudieron leer secciones del menú.")
            load_btn.disabled = False
            return
        state["sections"] = secs
        section_dd.options = [(f"{n}  ·  {len(subs)} subcat.", (n, subs)) for n, subs in secs]
        section_dd.layout.display = ""
        section_dd.value = section_dd.options[0][1]
        with load_status:
            clear_output(); print(f"✓ {len(secs)} secciones cargadas.")
        load_btn.disabled = False
        run_btn.disabled = False

    load_btn.on_click(on_load_clicked)

    step2 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.8rem 0 .3rem;'>📂 Paso 2 — Sección a scrapear</h4>"),
        load_btn, load_status, section_dd, subcat_container,
    ])

    # ─── Paso 3: ejecutar ─────────────────────────────────────────────
    run_btn = widgets.Button(description="🚀 Iniciar scraping", button_style="success",
                             disabled=True, layout=widgets.Layout(width="220px"))
    running_banner = widgets.HTML()

    store_bar = widgets.IntProgress(min=0, max=100, value=0, description="Zonas:",
                                    bar_style="info", layout=widgets.Layout(width="540px"),
                                    style={"description_width": "initial"})
    store_pct = widgets.HTML(layout=widgets.Layout(width="110px"))
    subcat_bar = widgets.IntProgress(min=0, max=100, value=0, description="Subcat:",
                                     bar_style="info", layout=widgets.Layout(width="540px"),
                                     style={"description_width": "initial"})
    subcat_pct = widgets.HTML(layout=widgets.Layout(width="110px"))
    page_bar = widgets.IntProgress(min=0, max=100, value=0, description="Páginas:",
                                    bar_style="info", layout=widgets.Layout(width="540px"),
                                    style={"description_width": "initial"})
    page_pct = widgets.HTML(layout=widgets.Layout(width="110px"))
    store_row = widgets.HBox([store_bar, store_pct], layout=widgets.Layout(align_items="center"))
    subcat_row = widgets.HBox([subcat_bar, subcat_pct], layout=widgets.Layout(align_items="center"))
    page_row = widgets.HBox([page_bar, page_pct], layout=widgets.Layout(align_items="center"))
    live_status = widgets.HTML()
    live_metrics = widgets.HTML()
    result_out = widgets.Output()

    def _set_pct(w, value, total):
        if not total:
            w.value = ""
            return
        pct = int(round(100 * value / total))
        w.value = f"<span style='color:#555;font-size:.9em;margin-left:8px;'>{value}/{total} · {pct}%</span>"

    def _set_running_ui(on):
        if on:
            run_btn.layout.display = "none"
            try: resume_panel.layout.display = "none"
            except NameError: pass
            running_banner.value = ("<div class='scraper-banner-running'>"
                                    "<span class='scraper-spinner'></span>"
                                    "Trabajando — no cierres esta pestaña ni la celda</div>")
        else:
            run_btn.description = "🚀 Iniciar scraping"
            run_btn.button_style = "success"
            run_btn.disabled = False
            run_btn.layout.display = ""
            try:
                resume_panel.layout.display = ""
                _refresh_resume_panel()
            except NameError: pass
            running_banner.value = ""

    def _status_with_spinner(text):
        return f"<span class='scraper-spinner'></span>{text}"

    async def _run_scrape(stores, section_name, subcats, only_fal, dl_imgs,
                          run_id=None, prior_rows=None, prior_done=None):
        all_rows = list(prior_rows or [])
        non_seller = 0
        skipped_zone = []
        failed_subcats = []
        truncated_subcats = []
        if not run_id:
            run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{re.sub(r'[^A-Za-z0-9]+', '', section_name) or 'run'}"
        prior_done = prior_done or set()
        partial = PartialWriter.__new__(PartialWriter)
        partial.path = PARTIAL_DIR / f"{run_id}.jsonl"
        partial._fh = open(partial.path, "a" if prior_rows else "w", encoding="utf-8")
        partial.count = len(prior_rows or [])
        store_bar.value = 0; store_bar.description = "Zonas:"
        subcat_bar.value = 0; subcat_bar.description = "Subcat:"
        page_bar.value = 0;  page_bar.description = "Páginas:"
        for _w in (store_pct, subcat_pct, page_pct):
            _w.value = ""
        live_status.value = ""
        live_metrics.value = ""
        _t0 = _time.time()
        _global_skus = {r.get("SKU") for r in all_rows if r.get("SKU")}
        _done_session = 0
        n_stores = len(stores)
        n_subs = max(len(subcats), 1)
        store_bar.max = n_stores
        subcat_bar.max = n_subs
        _set_pct(store_pct, 0, n_stores)
        _set_pct(subcat_pct, 0, n_subs)

        async with Stealth().use_async(async_playwright()) as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900}, color_scheme="light",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = await ctx.new_page()
            first = stores[0]
            live_status.value = _status_with_spinner(f"Configurando zona inicial: {first['name']}…")
            await set_zone_with_retry(page, first["region"], first["comuna"])

            for st_idx, store in enumerate(stores):
                store_bar.value = st_idx
                store_bar.description = f"Zonas {st_idx+1}/{n_stores}"
                _set_pct(store_pct, st_idx, n_stores)
                if st_idx > 0:
                    live_status.value = _status_with_spinner(f"Cambiando zona a {store['name']}…")
                    ok = await set_zone_with_retry(page, store["region"], store["comuna"])
                    if not ok:
                        skipped_zone.append(store["id"])
                        continue
                seen = {r.get("SKU") for r in all_rows if r.get("Tienda") == store["id"] and r.get("SKU")}
                for sc_idx, (sc_name, sc_url) in enumerate(subcats):
                    subcat_bar.value = sc_idx
                    subcat_bar.description = f"Subcat {sc_idx+1}/{n_subs}"
                    _set_pct(subcat_pct, sc_idx, n_subs)
                    if (store["id"], sc_name) in prior_done:
                        live_status.value = _status_with_spinner(f"⏭ Saltando (ya hecho): {store['name']} · {sc_name}")
                        continue
                    live_status.value = _status_with_spinner(f"📍 {store['name']} · 🗂 {sc_name}")
                    page_bar.max = 1
                    page_bar.value = 0
                    page_bar.description = "Páginas:"
                    _set_pct(page_pct, 0, 0)

                    def _page_cb(curr, total, _sc=sc_name):
                        if total and total > 0:
                            page_bar.max = total
                            page_bar.value = min(curr, total)
                            page_bar.description = f"Páginas {curr}/{total}"
                            _set_pct(page_pct, curr, total)
                        else:
                            page_bar.max = max(page_bar.max, curr)
                            page_bar.value = curr
                            page_bar.description = f"Página {curr}"
                            _set_pct(page_pct, curr, page_bar.max)

                    res = await scrape_subcat(page, section_name, sc_name, sc_url, None, None,
                                               download_images=dl_imgs, only_falabella=only_fal,
                                               page_progress_cb=_page_cb)
                    if res["failed"]:
                        failed_subcats.append((store["id"], sc_name))
                    if res["truncated"]:
                        truncated_subcats.append((store["id"], sc_name))
                    for r in res["rows"]:
                        if only_fal:
                            vendor = (r.get("Vendedor") or "").strip().upper()
                            if "FALABELLA" not in vendor:
                                non_seller += 1
                                continue
                        sku = r.get("SKU")
                        if not sku or sku in seen:
                            continue
                        seen.add(sku)
                        r2 = {"Tienda": store["id"], "Nombre Tienda": store["name"], **r}
                        all_rows.append(r2)
                        partial.write(r2)
                        if sku: _global_skus.add(sku)
                    _elapsed = _time.time() - _t0
                    _mm, _ss = divmod(int(_elapsed), 60)
                    _hh, _mm = divmod(_mm, 60)
                    _elapsed_str = f"{_hh}:{_mm:02d}:{_ss:02d}" if _hh else f"{_mm}:{_ss:02d}"
                    _rate = (len(all_rows) - len(prior_rows or [])) / max(_elapsed / 60, 0.01)
                    _parts = [
                        f"<b>🧮 Filas:</b> {len(all_rows)}",
                        f"<b>SKUs únicos:</b> {len(_global_skus)}",
                        f"<b>⏱</b> {_elapsed_str}",
                        f"<b>~{_rate:.0f}</b> filas/min",
                    ]
                    if _done_session >= 1:
                        _pairs_total = n_stores * n_subs - len(prior_done)
                        _pairs_left = max(0, _pairs_total - _done_session)
                        _eta_s = (_elapsed / _done_session) * _pairs_left
                        _em, _es = divmod(int(_eta_s), 60); _eh, _em = divmod(_em, 60)
                        _eta_str = f"{_eh}:{_em:02d}:{_es:02d}" if _eh else f"{_em}:{_es:02d}"
                        _parts.append(f"<b>ETA:</b> ~{_eta_str}")
                    if not only_fal and non_seller:
                        _parts.append(f"<b>No-Falabella:</b> {non_seller}")
                    live_metrics.value = " · ".join(_parts)
                    _append_done(run_id, store["id"], sc_name)
                    _done_session += 1
                subcat_bar.value = n_subs
                _set_pct(subcat_pct, n_subs, n_subs)
            store_bar.value = n_stores
            _set_pct(store_pct, n_stores, n_stores)
            live_status.value = "✓ Scraping completado."
            await browser.close()
        partial.close()
        return {"rows": all_rows, "non_seller": non_seller, "skipped_zone": skipped_zone,
                "failed_subcats": failed_subcats, "truncated_subcats": truncated_subcats,
                "partial_path": str(partial.path), "run_id": run_id, "section_name": section_name,
                "only_falabella": only_fal, "download_images": dl_imgs}

    def on_run_clicked(_):
        if state["running"]:
            return
        if not state["selected_stores"]:
            with result_out:
                clear_output(); print("⚠️ Seleccioná al menos una zona.")
            return
        pending = state.get("pending_resume")
        if pending:
            meta = pending.get("meta") or {}
            section_name = meta.get("section_name") or "run"
            subcats = [tuple(s) for s in (meta.get("subcats") or [])]
            if not subcats:
                with result_out:
                    clear_output(); print("⚠️ El checkpoint no tiene subcategorías.")
                state.pop("pending_resume", None)
                return
        else:
            if not section_dd.value:
                with result_out:
                    clear_output(); print("⚠️ Cargá las secciones primero.")
                return
            section_name, _ = section_dd.value
            subcats = get_selected_subcats()
            if not subcats:
                with result_out:
                    clear_output(); print("⚠️ Marcá al menos una subcategoría.")
                return
        state["running"] = True
        _set_running_ui(True)
        load_btn.disabled = True
        with result_out:
            clear_output()
        resume = state.pop("pending_resume", None)
        if resume:
            run_id = resume["run_id"]
            prior_rows = resume["rows"]
            prior_done = resume["done"]
        else:
            run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{re.sub(r'[^A-Za-z0-9]+', '', section_name) or 'run'}"
            prior_rows = None
            prior_done = None
            _write_meta(run_id, {
                "run_id": run_id,
                "section_name": section_name,
                "subcats": [list(s) for s in subcats],
                "stores": state["selected_stores"],
                "only_falabella": only_falabella_cb.value,
                "download_images": download_images_cb.value,
                "created_at": datetime.now().isoformat(),
            })
        try:
            result = asyncio.run(_run_scrape(
                state["selected_stores"], section_name, subcats,
                only_falabella_cb.value, download_images_cb.value,
                run_id=run_id, prior_rows=prior_rows, prior_done=prior_done,
            ))
        except Exception as e:
            with result_out:
                print(f"❌ Error durante scraping: {e}")
            state["running"] = False
            _set_running_ui(False)
            load_btn.disabled = False
            return
        state["running"] = False
        _set_running_ui(False)
        load_btn.disabled = False

        if not result or not result["rows"]:
            with result_out:
                print("⚠️ No se encontraron productos.")
                if result and result["skipped_zone"]:
                    print(f"Zonas saltadas: {', '.join(result['skipped_zone'])}")
            return

        rows = result["rows"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        safe = re.sub(r"[^\w\s-]", "", result["section_name"]).strip().replace(" ", "_")
        suffix = "" if result["only_falabella"] else "_all_sellers"
        suffix += "_con_imgs" if result["download_images"] else ""
        output = OUTPUT_DIR / f"falabella_{safe}{suffix}_{timestamp}.xlsx"
        with result_out:
            print("💾 Escribiendo Excel…")
            write_excel(rows, str(output))
            n_skus = len({x["SKU"] for x in rows if x.get("SKU")})
            n_zones = len({x["Tienda"] for x in rows if x.get("Tienda")})
            print(f"\n✅ Listo — {len(rows)} filas · {n_skus} SKUs únicos · {n_zones} zona(s)")
            print(f"   Descartadas (no-Falabella): {result['non_seller']}")
            if result["skipped_zone"]:
                print(f"   Zonas saltadas: {', '.join(result['skipped_zone'])}")
            if result.get("failed_subcats"):
                print(f"   Subcats que fallaron: {len(result['failed_subcats'])}")
            if result.get("truncated_subcats"):
                print(f"   Subcats truncadas: {len(result['truncated_subcats'])}")
            if result.get("partial_path"):
                print(f"   Backup incremental (JSONL): {result['partial_path']}")
            print(f"   Archivo: {output.name}")
            _log_activity(retailer="falabella", mode="seccion",
                           n_skus=0,
                           n_stores=len(state.get("selected_stores") or []),
                           n_rows_output=len(rows or []),
                           n_with_price=sum(1 for r in (rows or []) if r.get("Precio Internet")),
                           runtime_s=0,
                           output_file=output.name if output else "")
            if IN_COLAB:
                print("\n⬇️  Descargando…")
                colab_files.download(str(output))
                _redl_btn = widgets.Button(
                    description="Descargar Excel de nuevo",
                    icon="download", button_style="info",
                    layout=widgets.Layout(width="260px"),
                )
                def _redl_cb(_b, _p=str(output)):
                    try: colab_files.download(_p)
                    except Exception as _e: print(f"download fallo: {_e}")
                _redl_btn.on_click(_redl_cb)
                display(_redl_btn)
            else:
                print(f"\n📁 Guardado en: {output}")
            if result.get("run_id"):
                _cleanup_run(result["run_id"])
                print(f"🧹 Checkpoint eliminado ({result['run_id']}).")
            _refresh_resume_panel()

    run_btn.on_click(on_run_clicked)

    # ─── Resumen pre-run ───────────────────────────────────────────
    run_summary = widgets.HTML()

    def _update_run_summary(*_):
        try: n_st = len(state.get("selected_stores", []))
        except Exception: n_st = 0
        try:
            sel = get_selected_subcats()
            n_sc = len(sel) if sel else 0
        except Exception:
            n_sc = 0
        if n_st == 0 or n_sc == 0:
            run_summary.value = ""
            return
        run_summary.value = (
            "<div style='background:#f0f7ff;padding:.6rem;border-radius:6px;"
            "border:1px solid #bcdcff;margin:.4rem 0;font-size:.95em;'>"
            f"📋 Vas a scrapear <b>{n_st}</b> zona(s) × <b>{n_sc}</b> subcategoría(s) "
            f"= <b>{n_st * n_sc}</b> combinaciones.</div>"
        )

    try: section_dd.observe(_update_run_summary, "value")
    except NameError: pass

    _orig_on_section_change = on_section_change
    def on_section_change(change):
        _orig_on_section_change(change)
        try:
            for child in subcat_container.children:
                if hasattr(child, "children"):
                    for sub in getattr(child, "children", []):
                        for cb in getattr(sub, "children", []):
                            if isinstance(cb, widgets.Checkbox):
                                cb.observe(_update_run_summary, "value")
        except Exception:
            pass
        _update_run_summary()
    section_dd.unobserve(_orig_on_section_change, "value")
    section_dd.observe(on_section_change, "value")

    # ─── Panel de reanudación de checkpoint ────────────────────────
    resume_panel = widgets.VBox()

    def _make_resume_card(run_id, meta, prior_rows, done):
        age_min = int((_time.time() - _meta_path(run_id).stat().st_mtime) / 60)
        ttl_min = max(0, PARTIAL_TTL_SECONDS // 60 - age_min)
        section = meta.get("section_name") or "(sin nombre)"
        subcats = meta.get("subcats") or []
        stores = meta.get("stores") or []
        done_names = {sc for _, sc in done}

        items = []
        for n, _u in subcats:
            check = "✓" if n in done_names else "○"
            items.append(f"<span style='color:{'#2e8b2e' if n in done_names else '#888'};'>{check}</span> {n}")
        sc_html = "<b>Subcategorías:</b><br>" + " · ".join(items) if items else "(sin subcats)"
        store_html = ", ".join(s.get("id","?") for s in stores[:6])
        if len(stores) > 6:
            store_html += f" … (+{len(stores)-6})"

        info = widgets.HTML(
            "<div style='background:#fff7e0;padding:.7rem;border-radius:6px;border:1px solid #f0c060;'>"
            f"📦 <b>Sección:</b> {section}<br>"
            f"<b>Zonas:</b> {len(stores)} ({store_html})<br>"
            f"{sc_html}<br>"
            f"<span style='color:#555;font-size:.9em;'>"
            f"💾 {len(prior_rows)} filas · {len(done)}/{len(subcats) * max(len(stores),1)} (zona·subcat) completos · "
            f"hace {age_min} min · expira en {ttl_min} min · "
            f"<code>{run_id}</code></span></div>"
        )
        btn_cont = widgets.Button(description="▶ Continuar", button_style="success")
        btn_disc = widgets.Button(description="🗑 Descartar", button_style="danger")

        def _on_cont(_):
            state["pending_resume"] = {"run_id": run_id, "rows": prior_rows, "done": done, "meta": meta}
            state["selected_stores"] = stores or state["selected_stores"]
            on_run_clicked(None)
        def _on_disc(_):
            _cleanup_run(run_id)
            _refresh_resume_panel()
        btn_cont.on_click(_on_cont)
        btn_disc.on_click(_on_disc)
        return widgets.VBox([info, widgets.HBox([btn_cont, btn_disc])],
                            layout=widgets.Layout(margin="0 0 .6rem 0"))

    def _refresh_resume_panel():
        found = _find_resumable_all()
        if not found:
            resume_panel.children = []
            return
        cards = [_make_resume_card(*x) for x in found]
        if len(found) == 1:
            resume_panel.children = [widgets.HTML("<h4 style='margin:.6rem 0 .3rem;'>📦 Checkpoint disponible</h4>")] + cards
            return
        cards_box = widgets.VBox(cards, layout=widgets.Layout(display="none"))
        toggle = widgets.Button(description=f"▶ Mostrar {len(found)} checkpoints",
                                button_style="warning", layout=widgets.Layout(width="280px"))
        def _toggle(_):
            if cards_box.layout.display == "none":
                cards_box.layout.display = ""
                toggle.description = f"▼ Ocultar {len(found)} checkpoints"
            else:
                cards_box.layout.display = "none"
                toggle.description = f"▶ Mostrar {len(found)} checkpoints"
        toggle.on_click(_toggle)
        resume_panel.children = [toggle, cards_box]

    _refresh_resume_panel()

    step3 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.8rem 0 .3rem;'>🚀 Paso 3 — Ejecutar</h4>"),
        resume_panel, run_summary, run_btn, running_banner, store_row, subcat_row, page_row, live_status, live_metrics, result_out,
    ])
    _update_run_summary()

    footer = widgets.HTML(
        "<div style='margin-top:1.5rem;padding-top:.6rem;border-top:1px solid #e0e0e0;"
        "text-align:right;color:#aaa;font-size:.75em;font-family:sans-serif;font-style:italic;'>"
        "Creado por Carlos Cruz</div>"
    )

    update_stores()
    display(widgets.VBox([step1, step2, step3, footer]))
    '''

    _UI_CONSTRUMART = r'''import asyncio, re
    from datetime import datetime
    from pathlib import Path
    import nest_asyncio
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    nest_asyncio.apply()

    clear_output(wait=True)  # reset celda — evita duplicar UI al re-ejecutar

    try:
        from google.colab import files as colab_files
        IN_COLAB = True
    except ImportError:
        IN_COLAB = False

    OUTPUT_DIR = Path.cwd()

    # ─── Telemetry: log activity al Sheet ──────────────────────────────
    import uuid as _uuid
    _ACTIVITY_URL = "https://script.google.com/macros/s/AKfycbwYNVObEiq8NSslHNsPA3vcNsfPPf8zo6oLAOLVXEGQ7cqT_FwA4PxVxjNaEqt_566Z/exec"
    _ACTIVITY_TOKEN = "6kT2hQjLp_VxR8mN3wYsZ-aF7bGdEcU4"
    _BUILD_HASH = "5c4dba0ea3acb1375cdffccab4d63aad371fe0124f0b915fe6e05dd30d3f0577"
    _COLAB_TAG = "seccion-construmart"
    _SESSION_ID = globals().get("_SESSION_ID") or _uuid.uuid4().hex[:8]
    globals()["_SESSION_ID"] = _SESSION_ID

    def _user_hint():
        """Intenta obtener email del usuario de Colab; falla silencioso."""
        try:
            import subprocess
            # En Colab, /tmp/__colab_user_email__ no existe; intentar via auth
            from google.colab import auth as _ca
            # auth.authenticate_user() pediría permiso — no lo hacemos.
            # Mejor: leer env si existe.
            import os
            for k in ("COLAB_USER", "USER", "JUPYTERHUB_USER"):
                v = os.environ.get(k)
                if v: return v
        except Exception:
            pass
        return ""

    def _log_activity(retailer="", mode="", n_skus=0, n_stores=0,
                       n_rows_output=0, n_with_price=0, runtime_s=0,
                       output_file=""):
        """Mandar 1 POST con resumen del run. Nunca propaga errores."""
        try:
            import requests as _rq
            _rq.post(_ACTIVITY_URL, json={
                "token": _ACTIVITY_TOKEN,
                "session_id": _SESSION_ID,
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
            pass  # silencioso — no romper el flow del usuario
    state = {"sections": None, "selected_stores": [], "running": False, "pending_resume": None,
             "all_stores": None}

    # ─── Checkpoint en Google Drive + autolimpieza de 12 h ───────────────
    import os as _os, time as _time, json as _json
    PARTIAL_TTL_SECONDS = 12 * 3600  # 12 horas
    if IN_COLAB:
        try:
            from google.colab import drive as _drive
            if not _os.path.isdir("/content/drive/MyDrive"):
                _drive.mount("/content/drive", force_remount=False)
            _drv = Path("/content/drive/MyDrive/construmart_scraper_partials")
            _drv.mkdir(parents=True, exist_ok=True)
            PARTIAL_DIR = _drv
        except Exception as _e:
            print(f"⚠️ No se pudo montar Drive ({_e}); usando filesystem efímero.")

    _now = _time.time()
    for _glob in ("*.jsonl", "*.meta.json", "*.done.tsv"):
        for _p in PARTIAL_DIR.glob(_glob):
            try:
                if _now - _p.stat().st_mtime > PARTIAL_TTL_SECONDS:
                    _p.unlink()
            except Exception:
                pass

    def _meta_path(run_id): return PARTIAL_DIR / f"{run_id}.meta.json"
    def _done_path(run_id): return PARTIAL_DIR / f"{run_id}.done.tsv"

    def _write_meta(run_id, payload):
        _meta_path(run_id).write_text(_json.dumps(payload, ensure_ascii=False, indent=2))

    def _append_done(run_id, store_id, subcat_name):
        with open(_done_path(run_id), "a", encoding="utf-8") as f:
            f.write(f"{store_id}\t{subcat_name}\n")

    def _read_done(run_id):
        p = _done_path(run_id)
        if not p.exists(): return set()
        done = set()
        for line in p.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) == 2:
                done.add((parts[0], parts[1]))
        return done

    def _cleanup_run(run_id):
        for p in (PARTIAL_DIR / f"{run_id}.jsonl", _meta_path(run_id), _done_path(run_id)):
            try: p.unlink()
            except Exception: pass

    def _find_resumable_all():
        out = []
        metas = sorted(PARTIAL_DIR.glob("*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for m in metas:
            run_id = m.name[:-len(".meta.json")]
            jsonl = PARTIAL_DIR / f"{run_id}.jsonl"
            if not jsonl.exists():
                continue
            try:
                meta = _json.loads(m.read_text(encoding="utf-8"))
                prior_rows = PartialWriter.load(jsonl)
                done = _read_done(run_id)
                out.append((run_id, meta, prior_rows, done))
            except Exception:
                continue
        return out

    display(HTML("""
    <div style='background:linear-gradient(90deg,#c89004,#8a5d00);color:white;
    padding:1.2rem 1.5rem;border-radius:12px;margin-bottom:1rem;font-family:sans-serif;'>
      <h2 style='margin:0;color:white;'>🏗️ Construmart Section Scraper</h2>
      <p style='margin:.3rem 0 0;color:rgba(255,255,255,.85);font-size:.95rem;'>
        Captura productos de Construmart por sección y tienda (precios varían por tienda).
      </p>
    </div>
    <style>
    @keyframes scraper-spin { to { transform: rotate(360deg); } }
    @keyframes scraper-pulse { 0%,100%{opacity:1} 50%{opacity:.6} }
    .scraper-spinner{display:inline-block;width:14px;height:14px;border:2px solid #c89004;
      border-top-color:transparent;border-radius:50%;animation:scraper-spin .8s linear infinite;
      vertical-align:-3px;margin-right:8px;}
    .scraper-banner-running{background:linear-gradient(90deg,#ffb84d,#f0a020);color:#3a2400;
      padding:.7rem 1rem;border-radius:8px;font-family:sans-serif;font-weight:600;
      animation:scraper-pulse 1.6s ease-in-out infinite;margin:.5rem 0;}
    </style>
    """))

    def _checkbox_panel(items, all_checked=True, height="220px"):
        boxes = []
        for label, val in items:
            cb = widgets.Checkbox(value=all_checked, description=label, indent=False,
                                  layout=widgets.Layout(width="auto", margin="0"))
            cb._payload = val
            boxes.append(cb)
        list_box = widgets.VBox(boxes, layout=widgets.Layout(
            max_height=height, overflow_y="auto", border="1px solid #d0d0d0",
            border_radius="6px", padding="6px 10px", width="540px",
        ))
        btn_all = widgets.Button(description="Marcar todas", layout=widgets.Layout(width="130px"))
        btn_none = widgets.Button(description="Desmarcar todas", layout=widgets.Layout(width="150px"))
        btn_inv = widgets.Button(description="Invertir", layout=widgets.Layout(width="100px"))
        counter = widgets.HTML()
        def refresh_counter(*_):
            n = sum(1 for b in boxes if b.value)
            counter.value = f"<span style='color:#555;font-size:.9em;'>{n} de {len(boxes)} seleccionadas</span>"
        for b in boxes:
            b.observe(refresh_counter, "value")
        btn_all.on_click(lambda _: [setattr(b, "value", True) for b in boxes])
        btn_none.on_click(lambda _: [setattr(b, "value", False) for b in boxes])
        btn_inv.on_click(lambda _: [setattr(b, "value", not b.value) for b in boxes])
        refresh_counter()
        container = widgets.VBox([
            widgets.HBox([btn_all, btn_none, btn_inv, counter],
                         layout=widgets.Layout(align_items="center", gap="8px")),
            list_box,
        ])
        def get_selected():
            return [b._payload for b in boxes if b.value]
        return container, get_selected

    # ─── Descubrir tiendas (popup #store-popup) ────────────────────────
    async def _discover_stores_async():
        async with Stealth().use_async(async_playwright()) as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900}, color_scheme="light",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = await ctx.new_page()
            stores = await discover_stores(page)
            await browser.close()
            return stores

    print("🔎 Descubriendo tiendas de Construmart…")
    try:
        state["all_stores"] = asyncio.run(_discover_stores_async())
    except Exception as _e:
        state["all_stores"] = []
    if not state["all_stores"]:
        state["all_stores"] = STATIC_STORES
        print(f"⚠️ Usando listado estático ({len(STATIC_STORES)} tiendas RM).")
    else:
        print(f"✓ {len(state['all_stores'])} tiendas detectadas.")
    ALL_STORES_DYN = state["all_stores"]

    # ─── Paso 1: tiendas ─────────────────────────────────────────────
    rm_stores = [s for s in ALL_STORES_DYN if "METROPOLITANA" in (s["region"] or "").upper()]
    PRESETS = {
        "Solo LAS CONDES (más rápido)": [s for s in ALL_STORES_DYN if s["id"] == "14"] or ALL_STORES_DYN[:1],
        f"Todas RM ({len(rm_stores)} tiendas)": rm_stores,
        f"Todas Chile ({len(ALL_STORES_DYN)} tiendas)": ALL_STORES_DYN,
        "Personalizado": None,
    }

    preset_radio = widgets.RadioButtons(
        options=list(PRESETS.keys()), value="Solo LAS CONDES (más rápido)",
        description="Preset:", layout=widgets.Layout(width="auto"),
        style={"description_width": "initial"},
    )

    def _store_label(s):
        eq = sodimac_equivalent(s["id"])
        eq_str = f"  → {eq}" if eq else ""
        return f"{s['id']:>4}  {s['name']:<22}  ({s['region']}){eq_str}"

    store_panel_items = [(_store_label(s), s) for s in ALL_STORES_DYN]
    store_panel, get_selected_stores = _checkbox_panel(store_panel_items, all_checked=False, height="240px")
    store_panel_wrap = widgets.VBox([store_panel], layout=widgets.Layout(display="none"))
    store_eta = widgets.HTML()

    def update_stores(*_):
        preset = PRESETS[preset_radio.value]
        if preset is None:
            store_panel_wrap.layout.display = ""
            sel = get_selected_stores()
            state["selected_stores"] = sel if sel else ([s for s in ALL_STORES_DYN if s["id"] == "14"] or ALL_STORES_DYN[:1])
        else:
            store_panel_wrap.layout.display = "none"
            state["selected_stores"] = preset
        n = len(state["selected_stores"])
        try: load_btn.disabled = (n == 0)
        except NameError: pass
        if n == 0:
            store_eta.value = "<span style='color:#c0392b'>⚠️ Seleccioná al menos una tienda</span>"
        else:
            store_eta.value = f"<span style='color:#27ae60'>✓ {n} tienda(s)</span>"
        try: _update_run_summary()
        except NameError: pass

    download_images_cb = widgets.Checkbox(
        value=False, description="Capturar screenshot del card y embeber en Excel",
        indent=False, layout=widgets.Layout(width="auto"),
    )

    preset_radio.observe(update_stores, "value")
    for child in store_panel.children[1].children:
        child.observe(update_stores, "value")

    step1 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.3rem 0;'>📍 Paso 1 — Tiendas</h4>"
                     "<p style='margin:.2rem 0;color:#666;font-size:.9em;'>"
                     "Los precios de Construmart <b>varían por tienda</b>. La columna "
                     "<b>Tienda</b> del Excel guarda la equivalencia con la tienda Easy/Sodimac más cercana.</p>"),
        preset_radio, store_panel_wrap, store_eta,
        widgets.HTML("<h4 style='margin:.8rem 0 .3rem;'>⚙️ Opciones</h4>"),
        download_images_cb,
    ])

    # ─── Paso 2: secciones ────────────────────────────────────────────
    load_btn = widgets.Button(disabled=True, description="🔍 Cargar secciones", button_style="success",
                              layout=widgets.Layout(width="220px"))
    load_status = widgets.Output()
    section_dd = widgets.Dropdown(description="Sección:",
                                  layout=widgets.Layout(width="500px", display="none"),
                                  style={"description_width": "initial"})
    subcat_container = widgets.VBox(layout=widgets.Layout(display="none"))
    get_selected_subcats = lambda: []

    def on_section_change(change):
        global get_selected_subcats
        if not section_dd.value:
            return
        _, groups = section_dd.value
        # Mostrar solo grupos L2 (sin abrir a hojas L3). Cada grupo se scrappea
        # entrando a su propia URL, que en Construmart lista todos los productos
        # de las hojas hijas. Mas limpio para el usuario.
        items = []
        seen = set()
        for g_name, g_url, _leaves in groups:
            if not g_url or g_url in seen:
                continue
            seen.add(g_url)
            items.append((g_name, (g_name, g_url)))
        panel, getter = _checkbox_panel(items, all_checked=True, height="260px")
        get_selected_subcats = getter
        subcat_container.children = [
            widgets.HTML("<b>Subcategorías:</b>"),
            panel,
        ]
        subcat_container.layout.display = ""

    section_dd.observe(on_section_change, "value")

    async def _discover():
        first = state["selected_stores"][0]
        async with Stealth().use_async(async_playwright()) as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900}, color_scheme="light",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="es-CL", timezone_id="America/Santiago",
            )
            page = await ctx.new_page()
            try:
                await set_store_with_retry(page, first["id"], first.get("region"))
            except Exception:
                pass
            secs = await discover_sections(page)
            # Reintento defensivo: warmup + retry si vacío
            if not secs:
                try:
                    await page.goto("https://www.construmart.cl/", wait_until="networkidle", timeout=60000)
                    await page.wait_for_timeout(5000)
                    secs = await discover_sections(page)
                except Exception:
                    pass
            await browser.close()
            return secs

    def on_load_clicked(_):
        if not state["selected_stores"]:
            with load_status:
                clear_output(); print("⚠️ Seleccioná al menos una tienda primero.")
            return
        load_btn.disabled = True
        with load_status:
            clear_output()
            display(HTML("<span class='scraper-spinner'></span>"
                         "Configurando tienda y leyendo el menú de Construmart…"))
        try:
            secs = asyncio.run(_discover())
        except Exception as e:
            with load_status:
                clear_output(); print(f"❌ Error: {e}")
            load_btn.disabled = False
            return
        if not secs:
            with load_status:
                clear_output(); print("❌ No se pudieron leer las secciones. Esperá unos segundos e intentá de nuevo.")
            load_btn.disabled = False
            return
        state["sections"] = secs
        section_dd.options = [(f"{n}  ·  {len(subs)} subcat.", (n, subs)) for n, subs in secs]
        section_dd.layout.display = ""
        section_dd.value = section_dd.options[0][1]
        with load_status:
            clear_output(); print(f"✓ {len(secs)} secciones cargadas.")
        load_btn.disabled = False
        run_btn.disabled = False

    load_btn.on_click(on_load_clicked)

    step2 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.8rem 0 .3rem;'>📂 Paso 2 — Sección a scrapear</h4>"),
        load_btn, load_status, section_dd, subcat_container,
    ])

    # ─── Paso 3: ejecutar ─────────────────────────────────────────────
    run_btn = widgets.Button(description="🚀 Iniciar scraping", button_style="success",
                             disabled=True, layout=widgets.Layout(width="220px"))
    running_banner = widgets.HTML()

    store_bar = widgets.IntProgress(min=0, max=100, value=0, description="Tiendas:",
                                    bar_style="info", layout=widgets.Layout(width="540px"),
                                    style={"description_width": "initial"})
    store_pct = widgets.HTML(layout=widgets.Layout(width="110px"))
    subcat_bar = widgets.IntProgress(min=0, max=100, value=0, description="Subcat:",
                                     bar_style="info", layout=widgets.Layout(width="540px"),
                                     style={"description_width": "initial"})
    subcat_pct = widgets.HTML(layout=widgets.Layout(width="110px"))
    store_row = widgets.HBox([store_bar, store_pct], layout=widgets.Layout(align_items="center"))
    subcat_row = widgets.HBox([subcat_bar, subcat_pct], layout=widgets.Layout(align_items="center"))
    live_status = widgets.HTML()
    live_metrics = widgets.HTML()
    result_out = widgets.Output()

    def _set_pct(w, value, total):
        if not total:
            w.value = ""
            return
        pct = int(round(100 * value / total))
        w.value = f"<span style='color:#555;font-size:.9em;margin-left:8px;'>{value}/{total} · {pct}%</span>"

    def _set_running_ui(on):
        if on:
            run_btn.layout.display = "none"
            try: resume_panel.layout.display = "none"
            except NameError: pass
            running_banner.value = ("<div class='scraper-banner-running'>"
                                    "<span class='scraper-spinner'></span>"
                                    "Trabajando — no cierres esta pestaña ni la celda</div>")
        else:
            run_btn.description = "🚀 Iniciar scraping"
            run_btn.button_style = "success"
            run_btn.disabled = False
            run_btn.layout.display = ""
            try:
                resume_panel.layout.display = ""
                _refresh_resume_panel()
            except NameError: pass
            running_banner.value = ""

    def _status_with_spinner(text):
        return f"<span class='scraper-spinner'></span>{text}"

    async def _run_scrape(stores, section_name, subcats, dl_imgs,
                          run_id=None, prior_rows=None, prior_done=None):
        all_rows = list(prior_rows or [])
        skipped_zone = []
        failed_subcats = []
        truncated_subcats = []
        if not run_id:
            run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{re.sub(r'[^A-Za-z0-9]+', '', section_name) or 'run'}"
        prior_done = prior_done or set()
        partial = PartialWriter.__new__(PartialWriter)
        partial.path = PARTIAL_DIR / f"{run_id}.jsonl"
        partial._fh = open(partial.path, "a" if prior_rows else "w", encoding="utf-8")
        partial.count = len(prior_rows or [])
        store_bar.value = 0; store_bar.description = "Tiendas:"
        subcat_bar.value = 0; subcat_bar.description = "Subcat:"
        for _w in (store_pct, subcat_pct): _w.value = ""
        live_status.value = ""; live_metrics.value = ""
        _t0 = _time.time()
        _global_skus = {r.get("SKU") for r in all_rows if r.get("SKU")}
        _done_session = 0
        n_stores = len(stores)
        n_subs = max(len(subcats), 1)
        store_bar.max = n_stores
        subcat_bar.max = n_subs
        _set_pct(store_pct, 0, n_stores)
        _set_pct(subcat_pct, 0, n_subs)

        async with Stealth().use_async(async_playwright()) as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 900}, color_scheme="light",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = await ctx.new_page()
            first = stores[0]
            live_status.value = _status_with_spinner(f"Configurando tienda inicial: {first['name']}…")
            await set_store_with_retry(page, first["id"], first.get("region"))

            for st_idx, store in enumerate(stores):
                store_bar.value = st_idx
                store_bar.description = f"Tiendas {st_idx+1}/{n_stores}"
                _set_pct(store_pct, st_idx, n_stores)
                if st_idx > 0:
                    live_status.value = _status_with_spinner(f"Cambiando tienda a {store['name']}…")
                    ok = await set_store_with_retry(page, store["id"], store.get("region"))
                    if not ok:
                        skipped_zone.append(store["id"])
                        continue
                seen = {r.get("SKU") for r in all_rows
                        if (r.get("Nombre Tienda") == store["name"]) and r.get("SKU")}
                for sc_idx, (sc_name, sc_url) in enumerate(subcats):
                    subcat_bar.value = sc_idx
                    subcat_bar.description = f"Subcat {sc_idx+1}/{n_subs}"
                    _set_pct(subcat_pct, sc_idx, n_subs)
                    if (store["id"], sc_name) in prior_done:
                        live_status.value = _status_with_spinner(f"⏭ Saltando (ya hecho): {store['name']} · {sc_name}")
                        continue
                    live_status.value = _status_with_spinner(f"📍 {store['name']} · 🗂 {sc_name}")
                    res = await scrape_subcat(page, section_name, sc_name, sc_url, store,
                                               None, None, download_images=dl_imgs)
                    if res["failed"]: failed_subcats.append((store["id"], sc_name))
                    if res["truncated"]: truncated_subcats.append((store["id"], sc_name))
                    for r in res["rows"]:
                        sku = r.get("SKU")
                        if not sku or sku in seen:
                            continue
                        seen.add(sku)
                        all_rows.append(r)
                        partial.write(r)
                        if sku: _global_skus.add(sku)
                    _elapsed = _time.time() - _t0
                    _mm, _ss = divmod(int(_elapsed), 60); _hh, _mm = divmod(_mm, 60)
                    _elapsed_str = f"{_hh}:{_mm:02d}:{_ss:02d}" if _hh else f"{_mm}:{_ss:02d}"
                    _rate = (len(all_rows) - len(prior_rows or [])) / max(_elapsed / 60, 0.01)
                    _parts = [
                        f"<b>🧮 Filas:</b> {len(all_rows)}",
                        f"<b>SKUs únicos:</b> {len(_global_skus)}",
                        f"<b>⏱</b> {_elapsed_str}",
                        f"<b>~{_rate:.0f}</b> filas/min",
                    ]
                    if _done_session >= 1:
                        _pairs_total = n_stores * n_subs - len(prior_done)
                        _pairs_left = max(0, _pairs_total - _done_session)
                        _eta_s = (_elapsed / _done_session) * _pairs_left
                        _em, _es = divmod(int(_eta_s), 60); _eh, _em = divmod(_em, 60)
                        _eta_str = f"{_eh}:{_em:02d}:{_es:02d}" if _eh else f"{_em}:{_es:02d}"
                        _parts.append(f"<b>ETA:</b> ~{_eta_str}")
                    live_metrics.value = " · ".join(_parts)
                    _append_done(run_id, store["id"], sc_name)
                    _done_session += 1
                subcat_bar.value = n_subs
                _set_pct(subcat_pct, n_subs, n_subs)
            store_bar.value = n_stores
            _set_pct(store_pct, n_stores, n_stores)
            live_status.value = "✓ Scraping completado."
            await browser.close()
        partial.close()
        return {"rows": all_rows, "skipped_zone": skipped_zone,
                "failed_subcats": failed_subcats, "truncated_subcats": truncated_subcats,
                "partial_path": str(partial.path), "run_id": run_id,
                "section_name": section_name, "download_images": dl_imgs}

    def on_run_clicked(_):
        if state["running"]:
            return
        if not state["selected_stores"]:
            with result_out:
                clear_output(); print("⚠️ Seleccioná al menos una tienda.")
            return
        pending = state.get("pending_resume")
        if pending:
            meta = pending.get("meta") or {}
            section_name = meta.get("section_name") or "run"
            subcats = [tuple(s) for s in (meta.get("subcats") or [])]
            if not subcats:
                with result_out:
                    clear_output(); print("⚠️ El checkpoint no tiene subcategorías.")
                state.pop("pending_resume", None)
                return
        else:
            if not section_dd.value:
                with result_out:
                    clear_output(); print("⚠️ Cargá las secciones primero.")
                return
            section_name, _ = section_dd.value
            subcats = get_selected_subcats()
            if not subcats:
                with result_out:
                    clear_output(); print("⚠️ Marcá al menos una subcategoría.")
                return
        state["running"] = True
        _set_running_ui(True)
        load_btn.disabled = True
        with result_out:
            clear_output()
        resume = state.pop("pending_resume", None)
        if resume:
            run_id = resume["run_id"]
            prior_rows = resume["rows"]
            prior_done = resume["done"]
        else:
            run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{re.sub(r'[^A-Za-z0-9]+', '', section_name) or 'run'}"
            prior_rows = None
            prior_done = None
            _write_meta(run_id, {
                "run_id": run_id,
                "section_name": section_name,
                "subcats": [list(s) for s in subcats],
                "stores": state["selected_stores"],
                "download_images": download_images_cb.value,
                "created_at": datetime.now().isoformat(),
            })
        try:
            result = asyncio.run(_run_scrape(
                state["selected_stores"], section_name, subcats,
                download_images_cb.value,
                run_id=run_id, prior_rows=prior_rows, prior_done=prior_done,
            ))
        except Exception as e:
            with result_out:
                print(f"❌ Error durante scraping: {e}")
            state["running"] = False
            _set_running_ui(False)
            load_btn.disabled = False
            return
        state["running"] = False
        _set_running_ui(False)
        load_btn.disabled = False

        if not result or not result["rows"]:
            with result_out:
                print("⚠️ No se encontraron productos.")
                if result and result["skipped_zone"]:
                    print(f"Tiendas saltadas: {', '.join(result['skipped_zone'])}")
            return

        rows = result["rows"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        safe = re.sub(r"[^\w\s-]", "", result["section_name"]).strip().replace(" ", "_")
        suffix = "_con_imgs" if result["download_images"] else ""
        output = OUTPUT_DIR / f"construmart_{safe}{suffix}_{timestamp}.xlsx"
        with result_out:
            print("💾 Escribiendo Excel…")
            write_excel(rows, str(output))
            n_skus = len({x["SKU"] for x in rows if x.get("SKU")})
            n_stores_out = len({x["Nombre Tienda"] for x in rows if x.get("Nombre Tienda")})
            print(f"\n✅ Listo — {len(rows)} filas · {n_skus} SKUs únicos · {n_stores_out} tienda(s)")
            if result["skipped_zone"]:
                print(f"   Tiendas saltadas: {', '.join(result['skipped_zone'])}")
            if result.get("failed_subcats"):
                print(f"   Subcats que fallaron: {len(result['failed_subcats'])}")
            if result.get("truncated_subcats"):
                print(f"   Subcats truncadas: {len(result['truncated_subcats'])}")
            if result.get("partial_path"):
                print(f"   Backup incremental (JSONL): {result['partial_path']}")
            print(f"   Archivo: {output.name}")
            _log_activity(retailer="construmart", mode="seccion",
                           n_skus=0,
                           n_stores=len(state.get("selected_stores") or []),
                           n_rows_output=len(rows or []),
                           n_with_price=sum(1 for r in (rows or []) if r.get("Precio Internet")),
                           runtime_s=0,
                           output_file=output.name if output else "")
            if IN_COLAB:
                print("\n⬇️  Descargando…")
                colab_files.download(str(output))
                _redl_btn = widgets.Button(
                    description="Descargar Excel de nuevo",
                    icon="download", button_style="info",
                    layout=widgets.Layout(width="260px"),
                )
                def _redl_cb(_b, _p=str(output)):
                    try: colab_files.download(_p)
                    except Exception as _e: print(f"download fallo: {_e}")
                _redl_btn.on_click(_redl_cb)
                display(_redl_btn)
            else:
                print(f"\n📁 Guardado en: {output}")
            if result.get("run_id"):
                _cleanup_run(result["run_id"])
                print(f"🧹 Checkpoint eliminado ({result['run_id']}).")
            _refresh_resume_panel()

    run_btn.on_click(on_run_clicked)

    run_summary = widgets.HTML()
    def _update_run_summary(*_):
        try: n_st = len(state.get("selected_stores", []))
        except Exception: n_st = 0
        try:
            sel = get_selected_subcats()
            n_sc = len(sel) if sel else 0
        except Exception:
            n_sc = 0
        if n_st == 0 or n_sc == 0:
            run_summary.value = ""; return
        run_summary.value = (
            "<div style='background:#ffeef0;padding:.6rem;border-radius:6px;"
            "border:1px solid #f5b7be;margin:.4rem 0;font-size:.95em;'>"
            f"📋 Vas a scrapear <b>{n_st}</b> tienda(s) × <b>{n_sc}</b> subcategoría(s) "
            f"= <b>{n_st * n_sc}</b> combinaciones.</div>"
        )

    try: section_dd.observe(_update_run_summary, "value")
    except NameError: pass

    resume_panel = widgets.VBox()
    def _make_resume_card(run_id, meta, prior_rows, done):
        age_min = int((_time.time() - _meta_path(run_id).stat().st_mtime) / 60)
        ttl_min = max(0, PARTIAL_TTL_SECONDS // 60 - age_min)
        section = meta.get("section_name") or "(sin nombre)"
        subcats = meta.get("subcats") or []
        stores = meta.get("stores") or []
        done_names = {sc for _, sc in done}
        items = []
        for n, _u in subcats:
            check = "✓" if n in done_names else "○"
            items.append(f"<span style='color:{'#2e8b2e' if n in done_names else '#888'};'>{check}</span> {n}")
        sc_html = "<b>Subcategorías:</b><br>" + " · ".join(items) if items else "(sin subcats)"
        store_html = ", ".join(s.get("name","?") for s in stores[:6])
        if len(stores) > 6: store_html += f" … (+{len(stores)-6})"
        info = widgets.HTML(
            "<div style='background:#fff7e0;padding:.7rem;border-radius:6px;border:1px solid #f0c060;'>"
            f"📦 <b>Sección:</b> {section}<br>"
            f"<b>Tiendas:</b> {len(stores)} ({store_html})<br>"
            f"{sc_html}<br>"
            f"<span style='color:#555;font-size:.9em;'>"
            f"💾 {len(prior_rows)} filas · {len(done)}/{len(subcats) * max(len(stores),1)} (tienda·subcat) completos · "
            f"hace {age_min} min · expira en {ttl_min} min · "
            f"<code>{run_id}</code></span></div>"
        )
        btn_cont = widgets.Button(description="▶ Continuar", button_style="success")
        btn_disc = widgets.Button(description="🗑 Descartar", button_style="danger")
        def _on_cont(_):
            state["pending_resume"] = {"run_id": run_id, "rows": prior_rows, "done": done, "meta": meta}
            state["selected_stores"] = stores or state["selected_stores"]
            on_run_clicked(None)
        def _on_disc(_):
            _cleanup_run(run_id); _refresh_resume_panel()
        btn_cont.on_click(_on_cont); btn_disc.on_click(_on_disc)
        return widgets.VBox([info, widgets.HBox([btn_cont, btn_disc])],
                            layout=widgets.Layout(margin="0 0 .6rem 0"))

    def _refresh_resume_panel():
        found = _find_resumable_all()
        if not found:
            resume_panel.children = []; return
        cards = [_make_resume_card(*x) for x in found]
        if len(found) == 1:
            resume_panel.children = [widgets.HTML("<h4 style='margin:.6rem 0 .3rem;'>📦 Checkpoint disponible</h4>")] + cards
            return
        cards_box = widgets.VBox(cards, layout=widgets.Layout(display="none"))
        toggle = widgets.Button(description=f"▶ Mostrar {len(found)} checkpoints",
                                button_style="warning", layout=widgets.Layout(width="280px"))
        def _toggle(_):
            if cards_box.layout.display == "none":
                cards_box.layout.display = ""
                toggle.description = f"▼ Ocultar {len(found)} checkpoints"
            else:
                cards_box.layout.display = "none"
                toggle.description = f"▶ Mostrar {len(found)} checkpoints"
        toggle.on_click(_toggle)
        resume_panel.children = [toggle, cards_box]

    _refresh_resume_panel()

    step3 = widgets.VBox([
        widgets.HTML("<h4 style='margin:.8rem 0 .3rem;'>🚀 Paso 3 — Ejecutar</h4>"),
        resume_panel, run_summary, run_btn, running_banner, store_row, subcat_row, live_status, live_metrics, result_out,
    ])
    _update_run_summary()

    footer = widgets.HTML(
        "<div style='margin-top:1.5rem;padding-top:.6rem;border-top:1px solid #e0e0e0;"
        "text-align:right;color:#aaa;font-size:.75em;font-family:sans-serif;font-style:italic;'>"
        "Creado por Carlos Cruz</div>"
    )

    update_stores()
    display(widgets.VBox([step1, step2, step3, footer]))
    '''

    # ============================================================
    # Selector de tienda + dispatch automatico al confirmar.
    # Al hacer click en "Confirmar tienda", se limpia el output del
    # selector y se carga la UI del scraper correspondiente en la
    # misma celda. Sin celdas intermedias.
    # ============================================================
    import ipywidgets as widgets
    from IPython.display import display, HTML, clear_output
    import re as _re

    STATE = {"retailer": None}

    # Widgets del selector de retailer (estaban en el cell original, restaurados tras el refactor).
    _radio = widgets.RadioButtons(
        options=[("Sodimac", "sodimac"), ("Falabella", "falabella"), ("Construmart", "construmart")],
        description="Tienda:",
        style={"description_width": "initial"},
    )
    _btn = widgets.Button(description="Confirmar tienda", button_style="primary", icon="check")
    _out = widgets.Output()

    def _dispatch(retailer):
        """Carga el scraper y su UI en globals() segun la tienda."""
        # Las raw strings _UI_* heredaron el indent del def run() (4 espacios).
        # textwrap.dedent NO funciona acá porque la primera línea de cada UI no
        # tiene indent (empieza justo después de r'''), así que el "prefijo común"
        # calculado es 0. Forzamos quitar 4 espacios de cada línea que los tenga.
        def _strip4(s):
            return "\n".join(ln[4:] if ln.startswith("    ") else ln for ln in s.splitlines())
        if retailer == "sodimac":
            from engines import maestra_sodimac as ss
            globals().update({
                "ss": ss,
                "set_zone_with_retry": ss.set_zone_with_retry,
                "discover_sections": ss.discover_sections,
                "scrape_subcat": ss.scrape_subcat,
                "write_excel": ss.write_excel,
                "ALL_STORES": ss.ALL_STORES,
                "PartialWriter": ss.PartialWriter,
                "MAX_PAGES_PER_SUBCAT": ss.MAX_PAGES_PER_SUBCAT,
            })
            exec(_strip4(_UI_SODIMAC), globals())
        elif retailer == "falabella":
            from engines import maestra_falabella as _mf; globals().update({k: getattr(_mf, k) for k in dir(_mf) if not k.startswith('__')})
            exec(_strip4(_UI_FALABELLA), globals())
        elif retailer == "construmart":
            from engines import maestra_construmart as _mc; globals().update({k: getattr(_mc, k) for k in dir(_mc) if not k.startswith('__')})
            exec(_strip4(_UI_CONSTRUMART), globals())
        else:
            raise RuntimeError(f"Tienda desconocida: {retailer}")


    def _on_confirm(_):
        retailer = _radio.value
        STATE["retailer"] = retailer
        # Limpia toda la celda y renderiza la UI del scraper elegido
        clear_output(wait=True)
        print(f"Tienda: {retailer}  --  cargando UI...")
        try:
            _dispatch(retailer)
        except Exception as e:
            print(f"\nError cargando UI {retailer}: {e}")
            raise

    _btn.on_click(_on_confirm)

    display(widgets.HTML("<h3>Elegi la tienda y presiona Confirmar</h3>"))
    display(widgets.VBox([_radio, _btn]))
    display(_out)