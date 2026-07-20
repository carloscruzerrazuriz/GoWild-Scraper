# Copyright (c) 2026 Carlos Cruz Errazuriz. All rights reserved.
# Proprietary - see LICENSE file. No unauthorized use, redistribution, or reverse engineering.
"""Portal Inmobiliario — extractor de avisos (modo listado, rápido).

Invocado desde PortalInmobiliario.ipynb vía `from launchers import boot; boot("portalinmobiliario")`.
Extracción 100% HTTP + JSON embebido SSR (engine engines/portalinmobiliario.py):
sin navegador, sin API gateada. Modo por defecto: SOLO LISTADO (id, precio UF/CLP,
dormitorios/baños/m², ubicación, vendedor, foto), ~1 request cada 48 avisos.
"""

def run():
    from IPython.display import clear_output, display, HTML
    clear_output(wait=True)

    import os, time, uuid as _uuid
    from datetime import datetime
    from pathlib import Path
    import ipywidgets as widgets

    try:
        from google.colab import files as colab_files
        IN_COLAB = True
    except Exception:
        colab_files = None
        IN_COLAB = False

    from engines import portalinmobiliario as pi

    # --- Telemetría (mismo Systems Manifest que el resto) --------------------
    _ACTIVITY_URL = "https://script.google.com/macros/s/AKfycbzALm18Xuw9c7U0tcAE0u1lPvq1j4P5kCxIJvdkDuG5MLVrqKyWd5qt-Kjb-TSP3B82/exec"
    _ACTIVITY_TOKEN = "6kT2hQjLp_VxR8mN3wYsZ-aF7bGdEcU4"
    _COLAB_TAG = "portal-inmobiliario"
    _SESSION_ID = globals().get("_SESSION_ID") or _uuid.uuid4().hex[:8]
    globals()["_SESSION_ID"] = _SESSION_ID

    def _log_activity(mode="listado", n_rows=0, runtime_s=0, output_file=""):
        try:
            import requests as _rq
            _rq.post(_ACTIVITY_URL, json={
                "token": _ACTIVITY_TOKEN, "session_id": _SESSION_ID, "colab": _COLAB_TAG,
                "retailer": "portalinmobiliario", "mode": str(mode)[:30],
                "n_rows_output": int(n_rows or 0), "runtime_s": int(runtime_s or 0),
                "output_file": str(output_file or "")[:120],
            }, timeout=5, allow_redirects=True)
        except Exception:
            pass

    OUTPUT_DIR = Path.cwd()
    state = {"running": False}

    # ─── Paso 1: Qué buscar ─────────────────────────────────────
    mode_radio = widgets.RadioButtons(
        options=["Por filtros", "Pegar URL de búsqueda"], value="Por filtros",
        description="Modo:", style={"description_width": "initial"},
        layout=widgets.Layout(width="auto"))

    op_dd = widgets.Dropdown(options=pi.OPERATIONS, value="venta", description="Operación:",
                             style={"description_width": "initial"})
    type_dd = widgets.Dropdown(options=pi.PROPERTY_TYPES, value="departamento", description="Tipo:",
                               style={"description_width": "initial"})
    ubic_txt = widgets.Text(
        value="nunoa-metropolitana", description="Ubicación:",
        placeholder="comuna-region (ej: las-condes-metropolitana)",
        style={"description_width": "initial"}, layout=widgets.Layout(width="520px"))
    filtros_help = widgets.HTML(
        "<div style='color:#666;font-size:.85em;'>La ubicación es el slug de comuna-región: "
        "<code>las-condes-metropolitana</code>, <code>providencia-metropolitana</code>, "
        "<code>vina-del-mar-valparaiso</code>. Déjala vacía para toda la operación/tipo. "
        "Para filtros más finos (precio, m², dormitorios) usa 'Pegar URL de búsqueda'.</div>")
    filtros_box = widgets.VBox([op_dd, type_dd, ubic_txt, filtros_help])

    url_txt = widgets.Text(
        description="URL:", placeholder="https://www.portalinmobiliario.com/venta/departamento/...",
        style={"description_width": "initial"}, layout=widgets.Layout(width="640px"))
    url_help = widgets.HTML(
        "<div style='color:#666;font-size:.85em;'>Navega Portal Inmobiliario, aplica los filtros "
        "que quieras y pega acá el link de resultados. Se pagina y extrae todo.</div>")
    url_box = widgets.VBox([url_txt, url_help], layout=widgets.Layout(display="none"))

    def _update_mode(*_):
        by_url = mode_radio.value.startswith("Pegar")
        url_box.layout.display = "" if by_url else "none"
        filtros_box.layout.display = "none" if by_url else ""
    mode_radio.observe(_update_mode, "value")
    _update_mode()

    # ─── Paso 2: Opciones ───────────────────────────────────────
    pages_txt = widgets.BoundedIntText(value=5, min=1, max=200, description="Páginas (48 c/u):",
                                       style={"description_width": "initial"},
                                       layout=widgets.Layout(width="240px"))
    ads_cb = widgets.Checkbox(value=False, description="Incluir avisos publicitarios (Ads)",
                              indent=False)
    img_cb = widgets.Checkbox(value=False, description="Incluir imágenes (Excel más pesado)",
                              indent=False)

    # ─── Paso 3: Ejecutar ───────────────────────────────────────
    run_btn = widgets.Button(description="Extraer avisos", button_style="success",
                             layout=widgets.Layout(width="220px"))
    bar = widgets.IntProgress(min=0, max=100, value=0, description="Páginas:", bar_style="info",
                              layout=widgets.Layout(width="520px"),
                              style={"description_width": "initial"})
    live = widgets.HTML()
    out = widgets.Output()

    def _running(on):
        run_btn.disabled = on
        run_btn.description = "Trabajando…" if on else "Extraer avisos"

    def _on_run(_):
        if state["running"]:
            return
        state["running"] = True
        _running(True)
        with out:
            clear_output()
        bar.value = 0; live.value = ""
        try:
            by_url = mode_radio.value.startswith("Pegar")
            if by_url:
                base_url = (url_txt.value or "").strip()
                if "portalinmobiliario.com" not in base_url:
                    live.value = "<span style='color:#c0392b'>Pega una URL válida de Portal Inmobiliario.</span>"
                    return
                op_name = tipo_name = ""
            else:
                base_url = pi.build_url(op_dd.value, type_dd.value, ubic_txt.value)
                op_name = dict(pi.OPERATIONS).get(op_dd.value, op_dd.label)
                tipo_name = dict((v, k) for k, v in pi.PROPERTY_TYPES).get(type_dd.value, "")
            live.value = f"<b>Buscando…</b> {base_url}"

            t0 = time.time()
            rows = []
            bar.max = pages_txt.value

            def _page_cb(page, new, total_pages):
                bar.value = page
                pc = min(total_pages or pages_txt.value, pages_txt.value)
                bar.max = max(pc, 1)
                live.value = (f"<b>{len(rows)}</b> avisos · página {page}"
                              + (f" de ~{total_pages}" if total_pages else "")
                              + f" · {len(rows)/max(time.time()-t0,1):.0f} avisos/s")

            rows = pi.search(base_url, operacion=op_name, tipo=tipo_name,
                             max_pages=pages_txt.value, include_ads=ads_cb.value,
                             page_cb=_page_cb)

            if not rows:
                live.value = "<span style='color:#c0392b'>Sin avisos (¿URL/ubicación correcta?).</span>"
                return

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            name = f"portal_inmobiliario_{ts}.xlsx"
            path = OUTPUT_DIR / name
            pi.write_excel(rows, str(path), with_images=img_cb.value)
            dt = time.time() - t0
            live.value = f"<b style='color:#27ae60'>{len(rows)} avisos</b> en {dt:.0f}s → {name}"
            with out:
                print(f"Excel generado: {name}  ({len(rows)} avisos)")
            try:
                _log_activity(mode="listado-url" if by_url else "listado",
                              n_rows=len(rows), runtime_s=int(dt), output_file=name)
            except Exception:
                pass
            if IN_COLAB and colab_files is not None:
                try:
                    from engines._excel_utils import download_once
                    download_once(str(path), colab_files)
                except Exception as e:
                    with out:
                        print(f"download falló: {e}")
                redl = widgets.Button(description="Descargar de nuevo", icon="download",
                                      button_style="info", layout=widgets.Layout(width="230px"))
                def _redl(_b, _p=str(path)):
                    try:
                        from engines._excel_utils import download_once
                        download_once(_p, colab_files)
                    except Exception as e:
                        with out:
                            print(f"download falló: {e}")
                redl.on_click(_redl)
                with out:
                    display(redl)
        except Exception as e:
            live.value = f"<span style='color:#c0392b'>Error: {e}</span>"
        finally:
            state["running"] = False
            _running(False)
    run_btn.on_click(_on_run)

    footer = widgets.HTML(
        "<div style='margin-top:1.5rem;padding-top:.6rem;border-top:1px solid #e0e0e0;"
        "text-align:right;color:#aaa;font-size:.75em;font-family:sans-serif;font-style:italic;'>"
        "Portal Inmobiliario — Carlos Cruz E.<br/><span style='font-size:.85em;'>Copyright (c) 2026 "
        "Carlos Cruz Errazuriz · All rights reserved · Proprietary — No unauthorized use or distribution</span></div>")

    display(widgets.VBox([
        widgets.HTML("<h3 style='margin:.2rem 0;'>Portal Inmobiliario — Avisos</h3>"),
        widgets.HTML("<h4 style='margin:.6rem 0 .2rem;'>Paso 1 — Qué buscar</h4>"),
        mode_radio, filtros_box, url_box,
        widgets.HTML("<h4 style='margin:.8rem 0 .2rem;'>Paso 2 — Opciones</h4>"),
        pages_txt, ads_cb, img_cb,
        widgets.HTML("<h4 style='margin:.8rem 0 .2rem;'>Paso 3 — Ejecutar</h4>"),
        run_btn, bar, live, out, footer,
    ]))
